"""Lever (HTML scraping) and Reed (keyed API) sources.

Lever fixtures are trimmed real pages. Reed has real responses (job_*.json, saved
2026-09-25) and SYNTHETIC ones (synthetic_*.json) for edge cases.
All network access goes through httpx.MockTransport.
"""

from __future__ import annotations

import base64
import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from jobintel.http import HttpClient
from jobintel.load import load_batch
from jobintel.models import ParseFailure
from jobintel.pipeline import collect_source
from jobintel.raw_store import RawBatchWriter
from jobintel.sources.lever import LeverSource, parse_listing
from jobintel.sources.reed import ReedSource, worth_fetching
from jobintel.validate import normalize_posting

from .conftest import FIXTURES, count

LISTING = (FIXTURES / "lever/zopa_listing.html").read_text(encoding="utf-8")
POSTING = (FIXTURES / "lever/zopa_graduate_analyst.html").read_text(encoding="utf-8")
POSTING_ID = "962f3756-6e45-480f-984c-64e024b57c4f"
REED_SEARCH = json.loads((FIXTURES / "reed/synthetic_search_page.json").read_text("utf-8"))
REED_JOBS = {
    "900000101": json.loads((FIXTURES / "reed/synthetic_job_900000101.json").read_text("utf-8")),
    "900000103": json.loads((FIXTURES / "reed/synthetic_job_900000103.json").read_text("utf-8")),
}


def mock_client(handler) -> HttpClient:
    return HttpClient("test", transport=httpx.MockTransport(handler), sleep=lambda s: None,
                      min_interval=0, max_retries=1)


# ------------------------------------------------------------------ Lever
def test_parse_listing_extracts_postings():
    rows = parse_listing(LISTING)
    assert len(rows) == 34
    grad = next(r for r in rows if r["posting_id"] == POSTING_ID)
    assert grad["title"] == "2027 Graduate Analyst"
    assert grad["location"] == "London"
    assert grad["url"] == f"https://jobs.lever.co/zopa/{POSTING_ID}"


def lever_handler(requests_seen, posting_status=200):
    def handler(req: httpx.Request):
        requests_seen.append(str(req.url))
        if req.url.path == "/zopa":
            return httpx.Response(200, text=LISTING)
        if req.url.path == f"/zopa/{POSTING_ID}":
            return httpx.Response(posting_status, text=POSTING)
        # other candidate postings: serve the same page under their URL
        return httpx.Response(200, text=POSTING)
    return handler


def test_lever_fetch_only_requests_candidate_postings(tmp_path):
    seen: list[str] = []
    src = LeverSource({"companies": [{"slug": "zopa", "company": "Zopa"}]})
    batch = collect_source(src, tmp_path, "t", mock_client(lever_handler(seen)))
    assert batch.status == "success"
    posting_urls = [u for u in seen if u.count("/") > 3]
    n_candidates = sum(1 for r in parse_listing(LISTING)
                       if r["title"] and ("Analy" in r["title"] or "Data" in r["title"]
                                          or "BI " in r["title"]))
    # far fewer requests than the 34 postings on the page
    assert 0 < len(posting_urls) <= n_candidates < 34
    kinds = [it.meta["kind"] for it in batch.items]
    assert kinds[0] == "listing" and set(kinds[1:]) == {"posting"}


def test_lever_parse_posting_page(tmp_path):
    src = LeverSource({"companies": [{"slug": "zopa", "company": "Zopa"}]})
    batch = collect_source(src, tmp_path, "t", mock_client(lever_handler([])))
    rec = next(r for r in src.parse(batch) if r.source_job_id == POSTING_ID)
    assert rec.title_raw == "2027 Graduate Analyst"
    assert rec.company_raw == "Zopa"
    assert rec.location_raw == "London"
    assert rec.arrangement_hint == "hybrid"
    assert rec.posted_date == date(2026, 8, 28)
    assert "apply for this job" not in rec.description_text.lower()
    n = normalize_posting(rec)
    assert n.is_uk and n.working_arrangement == "hybrid"
    assert (n.salary_min, n.salary_currency) == (Decimal(45000), "GBP")


def test_lever_changed_html_is_quarantined_not_crash(tmp_path):
    w = RawBatchWriter(tmp_path, "lever")
    w.add(scope_key="zopa", url=f"https://jobs.lever.co/zopa/{POSTING_ID}",
          body=b"<html><body><h1>Redesigned page</h1></body></html>", status_code=200,
          content_type="html", meta={"kind": "posting", "posting_id": POSTING_ID})
    (rec,) = LeverSource({}).parse(w.finish())
    assert isinstance(rec, ParseFailure) and rec.reason == "html_structure_changed"


def test_lever_failed_posting_page_marks_scope_failed(tmp_path):
    src = LeverSource({"companies": [{"slug": "zopa", "company": "Zopa"}]})
    batch = collect_source(src, tmp_path, "t", mock_client(lever_handler([], 500)))
    assert batch.status == "partial"
    # the scope is incomplete, so absences in it must not count as "removed"
    assert batch.scope_status() == {"zopa": "failed"}


# ------------------------------------------------------------------ Reed
def reed_handler(seen, *, fail_details=False):
    def handler(req: httpx.Request):
        seen.append(req)
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json=REED_SEARCH)
        job_id = req.url.path.rsplit("/", 1)[-1]
        if fail_details:
            return httpx.Response(503)
        return httpx.Response(200, json=REED_JOBS[job_id])
    return handler


def reed(**cfg) -> ReedSource:
    base = {"queries": ["data analyst"], "location": "United Kingdom"}
    base.update(cfg)
    return ReedSource(base, api_key="secret-test-key")


def test_reed_disabled_without_key():
    assert ReedSource({}, api_key="").disabled_reason() is not None
    assert reed().disabled_reason() is None


def test_reed_fetch_uses_basic_auth_and_skips_non_candidates(tmp_path):
    seen: list[httpx.Request] = []
    batch = collect_source(reed(), tmp_path, "t", mock_client(reed_handler(seen)))
    assert batch.status == "success"
    expected = "Basic " + base64.b64encode(b"secret-test-key:").decode()
    assert all(r.headers["Authorization"] == expected for r in seen)
    detail_ids = [r.url.path.rsplit("/", 1)[-1] for r in seen if "/jobs/" in r.url.path]
    assert detail_ids == ["900000101", "900000103"]      # "Care Assistant" never fetched
    assert seen[0].url.params["keywords"] == "data analyst"
    # the key is never written to the raw store
    manifest = (batch.path / "manifest.json").read_text(encoding="utf-8")
    assert "secret-test-key" not in manifest


def test_reed_parse_structured_salary_and_dates(tmp_path):
    src = reed()
    batch = collect_source(src, tmp_path, "t", mock_client(reed_handler([])))
    recs = {r.source_job_id: normalize_posting(r) for r in src.parse(batch)}
    grad = recs["900000101"]
    assert (grad.salary_min, grad.salary_max, grad.salary_currency, grad.salary_period,
            grad.salary_source) == (Decimal("27000.0"), Decimal("30000.0"), "GBP", "year",
                                    "structured")
    assert grad.posted_date == date(2026, 9, 20)
    assert grad.working_arrangement == "hybrid"
    assert grad.company_clean == "synthetic_ Northwind Analytics"
    junior = recs["900000103"]
    assert junior.salary_min is None and junior.salary_currency is None   # "Competitive"


def test_reed_request_cap_marks_remaining_scopes_failed(tmp_path):
    src = reed(queries=["data analyst", "data engineer"], max_requests=2)
    batch = collect_source(src, tmp_path, "t", mock_client(reed_handler([])))
    assert batch.scope_status() == {"q:data analyst": "failed", "q:data engineer": "failed"}
    assert batch.status == "partial"


def test_reed_failed_details_do_not_look_like_removed_jobs(tmp_path):
    batch = collect_source(reed(), tmp_path, "t",
                           mock_client(reed_handler([], fail_details=True)))
    assert batch.scope_status() == {"q:data analyst": "failed"}


@pytest.mark.parametrize(
    "title, fetch",
    [
        ("Graduate Data Analyst", True),
        ("Junior Data Engineer", True),
        ("Analytics Engineer", True),
        ("Data Officer", True),              # data word, no clear family: kept ("unknown")
        ("Business Analyst", False),         # other analyst families cost no detail request
        ("Graduate Risk Analyst", False),
        ("Data Science Trainee", False),
        ("Care Assistant", False),
    ],
)
def test_reed_only_fetches_details_for_target_role_titles(title, fetch):
    assert worth_fetching(title, "London") is fetch


def test_reed_graduate_query_sends_flag_and_has_own_scope(tmp_path):
    seen: list[httpx.Request] = []
    src = reed(queries=[{"keywords": "data analyst", "graduate": True}])
    batch = collect_source(src, tmp_path, "t", mock_client(reed_handler(seen)))
    assert seen[0].url.params["graduate"] == "true"
    assert batch.scope_status() == {"q:data analyst [graduate]": "success"}


def reed_real_batch(tmp_path, job: dict):
    w = RawBatchWriter(tmp_path, "reed")
    w.add(scope_key="q:junior data analyst", url=f"https://www.reed.co.uk/api/1.0/jobs/{job['jobId']}",
          body=json.dumps(job).encode(), status_code=200, content_type="json",
          meta={"kind": "detail", "job_id": str(job["jobId"])})
    return w.finish()


def test_reed_real_response_with_salary(tmp_path):
    job = json.loads((FIXTURES / "reed/job_57348882.json").read_text("utf-8"))
    (rec,) = ReedSource({}, api_key="k").parse(reed_real_batch(tmp_path, job))
    n = normalize_posting(rec)
    assert (n.title_raw, n.company_raw) == ("Graduate Risk Analyst", "Virtuoso Recruitment Limited")
    assert (n.salary_min, n.salary_max, n.salary_currency, n.salary_period, n.salary_source) == (
        Decimal("24000.0"), Decimal("27000.0"), "GBP", "year", "structured")
    assert n.posted_date == date(2026, 9, 15)
    assert n.url == "https://www.reed.co.uk/jobs/graduate-risk-analyst/57348882"


def test_reed_real_response_salary_type_alone_is_not_a_salary(tmp_path):
    """Reed sends salaryType "per annum" even when no salary is advertised."""
    job = json.loads((FIXTURES / "reed/job_57385023.json").read_text("utf-8"))
    assert job["salaryType"] == "per annum" and job["minimumSalary"] is None
    (rec,) = ReedSource({}, api_key="k").parse(reed_real_batch(tmp_path, job))
    n = normalize_posting(rec)
    assert n.salary_min is None and n.salary_period is None and n.salary_currency is None
    assert n.location_cities == ["Sheffield"]


# ------------------------------------------------------------------ DB
@pytest.mark.db
def test_lever_and_reed_reload_without_duplicates(conn, tmp_path):
    lever = LeverSource({"companies": [{"slug": "zopa", "company": "Zopa"}]})
    lb = collect_source(lever, tmp_path, "t", mock_client(lever_handler([])))
    rs = reed()
    rb = collect_source(rs, tmp_path, "t", mock_client(reed_handler([])))
    for _ in range(2):
        load_batch(conn, lever, lb)
        load_batch(conn, rs, rb)
    assert count(conn, "core.posting_observation") == count(conn, "core.posting")
    by_source = dict(conn.execute(
        "select source_id, count(*) from core.posting group by 1").fetchall())
    assert by_source["reed"] == 2 and by_source["lever"] >= 1
