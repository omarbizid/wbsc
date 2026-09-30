"""Parser tests (no DB) and loader/acceptance tests (need PostgreSQL)."""

from __future__ import annotations

import httpx
import psycopg
import pytest

from jobintel.http import HttpClient
from jobintel.load import load_batch
from jobintel.models import ParsedPosting
from jobintel.pipeline import collect_and_load, load_pending, replay
from jobintel.sources import REGISTRY
from jobintel.sources.base import Source
from jobintel.sources.greenhouse import GreenhouseSource
from jobintel.validate import OutOfScope, Rejection, normalize_posting

from .conftest import count, load_fixture, make_batch, synthetic_greenhouse_job

GH = GreenhouseSource({})


# ------------------------------------------------------------------ parsing (no DB)
def test_parse_real_greenhouse_fixture(tmp_path):
    batch = make_batch(tmp_path, "greenhouse",
                       {"monzo": load_fixture("greenhouse/board_sample.json")})
    recs = list(GH.parse(batch))
    assert len(recs) == 3
    by_id = {r.source_job_id: r for r in recs}

    ae = normalize_posting(by_id["6076740"])   # Senior Analytics Engineer, Monzo
    assert ae.company_clean == "Monzo"
    assert ae.is_uk and ae.location_cities == ["Cardiff", "London"]
    assert ae.working_arrangement == "remote"
    assert (ae.salary_min, ae.salary_max, ae.salary_currency) == (76500, 95000, "GBP")
    assert ae.url.startswith("https://job-boards.greenhouse.io/monzo/jobs/")
    assert ae.posted_date is not None
    assert "<" not in ae.description_text

    dojo = normalize_posting(by_id["4951545101"])  # Analytics Engineer, Dojo: no salary
    assert dojo.salary_min is None and dojo.salary_max is None and dojo.salary_currency is None

    assert isinstance(normalize_posting(by_id["6635595"]), OutOfScope)  # Backend Engineer


def test_missing_required_field_is_rejected(tmp_path):
    job = synthetic_greenhouse_job(job_id=None)
    batch = make_batch(tmp_path, "greenhouse", {"synthetic": {"jobs": [job]}}, is_synthetic=True)
    (rec,) = GH.parse(batch)
    res = normalize_posting(rec)
    assert isinstance(res, Rejection)
    assert res.reason == "missing_required_field" and "source_job_id" in res.details["fields"]


def test_unparseable_payload_becomes_parse_failure(tmp_path):
    batch = make_batch(tmp_path, "greenhouse", {"broken": b"<html>not json</html>"})
    (rec,) = GH.parse(batch)
    assert rec.reason == "unparseable_payload"


def test_posting_date_not_invented(tmp_path):
    batch = make_batch(tmp_path, "greenhouse",
                       {"s": {"jobs": [synthetic_greenhouse_job(first_published=None)]}})
    (rec,) = GH.parse(batch)
    assert normalize_posting(rec).posted_date is None


# ------------------------------------------------------------------ loading (DB)
pytestmark_db = pytest.mark.db


def _snapshot(conn):
    return {t: count(conn, t) for t in (
        "core.posting", "core.posting_version", "core.posting_observation", "ops.quarantine")}


@pytestmark_db
def test_same_batch_twice_creates_no_duplicates(conn, tmp_path):
    batch = make_batch(tmp_path, "greenhouse",
                       {"monzo": load_fixture("greenhouse/board_sample.json")})
    s1 = load_batch(conn, GH, batch)
    first = _snapshot(conn)
    s2 = load_batch(conn, GH, batch, mode="replay")
    assert _snapshot(conn) == first
    assert first["core.posting"] == 2 and first["core.posting_observation"] == 2
    assert (s1.n_accepted, s1.n_out_of_scope, s1.n_duplicate) == (2, 1, 0)
    assert (s2.n_accepted, s2.n_duplicate, s2.n_new_versions) == (0, 2, 0)
    runs = conn.execute("select status, n_collected from ops.load_run order by 1").fetchall()
    assert runs == [("success", 3), ("success", 3)]


@pytestmark_db
def test_repeated_posting_within_batch_counted_once(conn, tmp_path):
    job = synthetic_greenhouse_job()
    batch = make_batch(tmp_path, "greenhouse", {"a": {"jobs": [job]}, "b": {"jobs": [job]}},
                       is_synthetic=True)
    s = load_batch(conn, GH, batch)
    assert (s.n_accepted, s.n_duplicate) == (1, 1)
    assert count(conn, "core.posting_observation") == 1


@pytestmark_db
def test_posting_without_salary_retained_with_null_salary(conn, tmp_path):
    batch = make_batch(tmp_path, "greenhouse", {"s": {"jobs": [synthetic_greenhouse_job()]}},
                       is_synthetic=True)
    load_batch(conn, GH, batch)
    row = conn.execute("""select salary_min, salary_max, salary_currency, salary_period,
                                 working_arrangement, posted_date
                          from core.posting_version""").fetchone()
    assert row == (None, None, None, None, "unknown", None)


@pytestmark_db
def test_changed_content_creates_new_version_and_keeps_history(conn, tmp_path):
    j1 = synthetic_greenhouse_job()
    j2 = synthetic_greenhouse_job(title="synthetic_ Junior Data Analyst")
    load_batch(conn, GH, make_batch(tmp_path, "greenhouse", {"s": {"jobs": [j1]}}))
    load_batch(conn, GH, make_batch(tmp_path, "greenhouse", {"s": {"jobs": [j2]}}))
    assert count(conn, "core.posting") == 1
    assert count(conn, "core.posting_version") == 2
    assert count(conn, "core.posting_observation") == 2


class BuggyGreenhouse(GreenhouseSource):
    """Simulates a parser bug: reads the job id from the wrong key."""

    parser_version = "greenhouse-buggy"

    def _parse_job(self, job, scope_key, meta, raw_ref) -> ParsedPosting:
        p = super()._parse_job(job, scope_key, meta, raw_ref)
        p.source_job_id = job.get("job_id")
        return p


@pytestmark_db
def test_parser_fix_and_replay_without_network(conn, tmp_path, monkeypatch):
    batch = make_batch(tmp_path, "greenhouse",
                       {"monzo": load_fixture("greenhouse/board_sample.json")})
    s = load_batch(conn, BuggyGreenhouse({}), batch)
    assert s.n_rejected == 3 and s.n_accepted == 0
    assert count(conn, "core.posting") == 0          # nothing entered reporting tables
    reasons = conn.execute("select distinct reason from ops.quarantine").fetchall()
    assert reasons == [("missing_required_field",)]

    def no_network(*a, **k):
        raise AssertionError("replay must not touch the network")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setenv("SOURCES_CONFIG", str(_write_cfg(tmp_path)))
    (fixed,) = replay(conn, batch_id=batch.batch_id, raw_root=tmp_path)
    assert fixed.status == "success" and fixed.n_accepted == 2
    assert count(conn, "core.posting") == 2
    unresolved = conn.execute(
        "select count(*) from ops.quarantine where resolved_at is null").fetchone()[0]
    assert unresolved == 0


@pytestmark_db
def test_one_unavailable_source_does_not_block_others(conn, tmp_path, monkeypatch):
    class DownSource(Source):
        name = "lever"
        parser_version = "down-1"

        def fetch(self, client, writer):
            url = "https://down.test/jobs"
            try:
                client.get(url)
            except Exception as exc:
                writer.add_failure(scope_key="acme", url=url, error=str(exc))

        def parse(self, batch):
            return iter(())

    monkeypatch.setitem(REGISTRY, "lever", DownSource)
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SOURCES_CONFIG", str(_write_cfg(tmp_path)))
    fixture = load_fixture("greenhouse/board_sample.json")

    def handler(req: httpx.Request):
        if req.url.host == "down.test":
            return httpx.Response(503)
        return httpx.Response(200, json=fixture)

    def client_factory(source):
        return HttpClient("t", transport=httpx.MockTransport(handler), sleep=lambda s: None,
                          min_interval=0, max_retries=1)

    results = collect_and_load(conn, ["lever", "greenhouse"], client_factory=client_factory)
    by = {r.source: r for r in results}
    assert by["lever"].batch.status == "failed"
    assert by["greenhouse"].batch.status == "success"
    assert by["greenhouse"].load.n_accepted == 2
    statuses = dict(conn.execute("select source_id, status from ops.collection_batch"))
    assert statuses == {"lever": "failed", "greenhouse": "success"}


def _write_cfg(tmp_path):
    p = tmp_path / "sources.yml"
    p.write_text("greenhouse:\n  boards:\n    - {token: monzo, company: Monzo}\n", "utf-8")
    return p


# ------------------------------------------------------------------ constraints
@pytestmark_db
@pytest.mark.parametrize(
    "sql, error",
    [
        ("insert into core.posting (source_id, source_job_id, scope_key, first_seen_at, "
         "last_seen_at) values ('greenhouse','1','x',now(),now()),"
         "('greenhouse','1','x',now(),now())", psycopg.errors.UniqueViolation),
        ("insert into core.posting (source_id, source_job_id, scope_key, first_seen_at, "
         "last_seen_at) values ('nosuchsource','1','x',now(),now())",
         psycopg.errors.ForeignKeyViolation),
        ("insert into core.posting (source_id, source_job_id, scope_key, first_seen_at, "
         "last_seen_at) values ('greenhouse','','x',now(),now())", psycopg.errors.CheckViolation),
    ],
)
def test_posting_constraints(conn, sql, error):
    with pytest.raises(error):
        conn.execute(sql)


@pytestmark_db
@pytest.mark.parametrize(
    "overrides",
    [
        {"salary_min": 50000, "salary_max": 40000, "salary_currency": "'GBP'"},  # min > max
        {"salary_min": 40000},                                                  # no currency
        {"working_arrangement": "'sometimes'"},
        {"url": "'not-a-url'"},
    ],
)
def test_version_constraints(conn, overrides):
    conn.execute("""insert into core.posting (source_id, source_job_id, scope_key,
                    first_seen_at, last_seen_at) values ('greenhouse','1','x',now(),now())""")
    cols = {"posting_id": 1, "content_hash": "'h'", "parser_version": "'t'",
            "url": "'https://x.test'", "title_raw": "'t'", "title_clean": "'t'",
            "company_raw": "'c'", "company_clean": "'c'", "is_uk": "true",
            "description_text": "'d'", "first_seen_at": "now()"}
    cols.update(overrides)
    sql = (f"insert into core.posting_version ({', '.join(cols)}) "
           f"values ({', '.join(str(v) for v in cols.values())})")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(sql)


@pytestmark_db
def test_load_pending_loads_each_unloaded_batch_once(conn, tmp_path, monkeypatch):
    """Collected with --no-load (or while the DB was down): `jobintel load --pending`."""
    monkeypatch.setenv("SOURCES_CONFIG", str(_write_cfg(tmp_path)))
    make_batch(tmp_path, "greenhouse", {"monzo": load_fixture("greenhouse/board_sample.json")})
    (first,) = load_pending(conn, raw_root=tmp_path)
    assert first.status == "success" and first.n_accepted == 2
    assert load_pending(conn, raw_root=tmp_path) == []       # nothing left to load
    assert count(conn, "ops.load_run") == 1
