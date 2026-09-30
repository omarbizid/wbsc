"""Dashboard aggregation rules (jobintel.reporting.metrics) and a UI smoke test.

All frames here are synthetic (`synthetic_` titles) and never touch the database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from jobintel.reporting import data
from jobintel.reporting import metrics as m

APP = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"


def posting(pid: int, **kw) -> dict:
    row = {
        "posting_id": pid, "source_id": "greenhouse", "source_name": "Greenhouse",
        "source_job_id": str(pid), "scope_key": "acme", "url": f"https://example.test/{pid}",
        "title_raw": f"synthetic_ Data Analyst {pid}", "title_clean": "Data Analyst",
        "company_clean": "synthetic_ Acme", "location_raw": "London",
        "location_cities": ["London"], "primary_city": "London", "location_country": "GB",
        "working_arrangement": "hybrid", "arrangement_evidence": None,
        "salary_min": None, "salary_max": None, "salary_currency": None,
        "salary_period": None, "salary_period_inferred": False, "salary_source": None,
        "salary_raw": None, "has_salary": False, "posted_date": None,
        "role_category": "data_analyst", "role_evidence": "Data Analyst",
        "seniority": "entry", "seniority_source": "title", "seniority_evidence": "Graduate",
        "is_entry_level": True, "is_target_role": True,
        "first_seen_at": "2026-09-01T08:00:00Z", "last_seen_at": "2026-09-20T08:00:00Z",
        "n_observations": 3, "n_versions": 1, "is_active": True,
        "n_successful_batches_missed": 0, "inactive_since": None,
        "cluster_id": pid, "cluster_size": 1, "cluster_n_sources": 1, "is_canonical": True,
        "parser_version": "synthetic-1/norm-3",
    }
    row.update(kw)
    return row


def frame(*rows: dict) -> pd.DataFrame:
    return data.prepare_postings(pd.DataFrame(list(rows)))


def skills_frame(pairs: dict[int, list[str]]) -> pd.DataFrame:
    return pd.DataFrame([{"posting_id": p, "skill": s, "skill_category": "language",
                          "matched_text": s} for p, ss in pairs.items() for s in ss])


# ------------------------------------------------------------------ basics
def test_share_always_shows_denominator():
    assert m.share(3, 12) == "3 of 12 (25%)"
    assert m.share(0, 0) == "0 of 0"


def test_prepare_postings_gives_every_posting_a_city():
    df = frame(posting(1, location_cities=[]), posting(2, location_cities=["Leeds", "Bath"]))
    assert df["cities"].tolist() == [["Unspecified"], ["Bath", "Leeds"]]


# ------------------------------------------------------------------ filters / duplicates
def test_unique_jobs_counts_a_cross_source_duplicate_once():
    df = frame(posting(1, cluster_id=1, is_canonical=True),
               posting(2, cluster_id=1, is_canonical=False, source_id="reed"),
               posting(3))
    assert len(m.apply_filters(df, m.Filters())) == 2
    assert len(m.apply_filters(df, m.Filters(unique_jobs=False))) == 3
    # Filtering to reed keeps reed's copy even though the canonical copy is greenhouse.
    only_reed = m.apply_filters(df, m.Filters(sources=("reed",)))
    assert only_reed["posting_id"].tolist() == [2]


def test_filters_combine():
    df = frame(
        posting(1),
        posting(2, role_category="data_engineer", location_cities=["Leeds"]),
        posting(3, working_arrangement="remote", is_active=False),
        posting(4, first_seen_at="2026-09-21T08:00:00Z", last_seen_at="2026-09-22T08:00:00Z"),
        posting(5, location_cities=[]),
    )
    ids = lambda f: sorted(m.apply_filters(df, f)["posting_id"])  # noqa: E731
    assert ids(m.Filters(roles=("data_engineer",))) == [2]
    assert ids(m.Filters(cities=("Leeds", "Unspecified"))) == [2, 5]
    assert ids(m.Filters(arrangements=("remote",))) == [3]
    assert ids(m.Filters(active_only=True)) == [1, 2, 4, 5]
    # Date range: listed at some point in the range.
    assert ids(m.Filters(start=date(2026, 9, 21))) == [4]
    assert ids(m.Filters(end=date(2026, 9, 10))) == [1, 2, 3, 5]


# ------------------------------------------------------------------ breakdowns
def test_breakdown_keeps_order_zeros_and_denominator():
    df = frame(posting(1), posting(2), posting(3, working_arrangement="unknown"))
    b = m.breakdown(df, "working_arrangement", m.ARRANGEMENTS).set_index("value")
    assert b.loc["hybrid", "n"] == 2 and b.loc["remote", "n"] == 0
    assert (b["total"] == 3).all()
    assert list(b.index) == list(m.ARRANGEMENTS)


def test_city_counts_count_multi_city_postings_in_each_city():
    df = frame(posting(1, location_cities=["London", "Leeds"]), posting(2))
    c = m.city_counts(df).set_index("city")
    assert c.loc["London", "n"] == 2 and c.loc["Leeds", "n"] == 1
    assert c.loc["London", "pct"] == 100
    assert m.postings_in_city(df, "Leeds")["posting_id"].tolist() == [1]


# ------------------------------------------------------------------ skills
def test_skill_counts_and_pairs_use_only_filtered_postings():
    df = frame(posting(1), posting(2), posting(3))
    sk = skills_frame({1: ["SQL", "Python"], 2: ["SQL", "Python", "Tableau"], 3: [],
                       99: ["Java"]})  # 99 is not in the filtered postings
    c = m.skill_counts(sk, df).set_index("skill")
    assert c.loc["SQL", "n"] == 2 and c.loc["SQL", "total"] == 3
    assert "Java" not in c.index
    p = m.skill_pairs(sk, df)
    assert p.iloc[0][["skill_a", "skill_b", "n"]].tolist() == ["Python", "SQL", 2]
    both = m.postings_with_skill(sk, df, "SQL", "Tableau")
    assert both["posting_id"].tolist() == [2] and "evidence: Tableau" in both


# ------------------------------------------------------------------ salaries
def test_salaries_grouped_by_currency_and_period_never_converted():
    rows = [posting(i, has_salary=True, salary_min=30000 + 1000 * i, salary_max=40000,
                    salary_currency="GBP", salary_period="year") for i in range(1, 6)]
    rows += [posting(10, has_salary=True, salary_min=20, salary_max=20,
                     salary_currency="GBP", salary_period="hour"),
             posting(11, has_salary=True, salary_min=90000, salary_max=120000,
                     salary_currency="USD", salary_period="year", salary_period_inferred=True),
             posting(12)]
    g = m.salary_groups(frame(*rows)).set_index(["salary_currency", "salary_period"])
    assert len(g) == 3
    year = g.loc[("GBP", "year")]
    assert year["n"] == 5 and year["enough_for_stats"]
    assert year["median"] == pytest.approx(36500)  # midpoints 35.5k..37.5k
    hour = g.loc[("GBP", "hour")]
    assert hour["min"] == 20 and pd.isna(hour["median"])  # too few for statistics
    assert g.loc[("USD", "year"), "n_period_inferred"] == 1


def test_no_salaries_gives_empty_groups():
    assert m.salary_groups(frame(posting(1))).empty


# ------------------------------------------------------------------ trends
def test_weekly_counts_respect_filters_and_range():
    df = frame(posting(1), posting(2, role_category="data_engineer"))
    weeks = pd.DataFrame({"posting_id": [1, 1, 2, 3],
                          "week_start": pd.to_datetime(["2026-09-07", "2026-09-14",
                                                        "2026-09-14", "2026-09-14"])})
    w = m.weekly_counts(weeks, df)
    assert w["n"].sum() == 3  # posting 3 is filtered out
    w = m.weekly_counts(weeks, df, start=date(2026, 9, 15))
    assert w["week_start"].dt.date.unique().tolist() == [date(2026, 9, 14)]
    assert m.weekly_counts(weeks, df.iloc[0:0]).empty


def test_new_per_week_uses_monday_of_first_seen():
    df = frame(posting(1, first_seen_at="2026-09-23T10:00:00Z"),  # Wednesday
               posting(2, first_seen_at="2026-09-27T23:00:00Z"))  # Sunday, same week
    new = m.new_per_week(df)
    assert new["week_start"].dt.date.tolist() == [date(2026, 9, 21)]
    assert new["n"].tolist() == [2]


# ------------------------------------------------------------------ freshness
def test_stale_sources_include_never_collected_and_old_success():
    health = pd.DataFrame({
        "source_id": ["greenhouse", "lever", "reed"],
        "display_name": ["Greenhouse", "Lever", "Reed"],
        "last_success_at": pd.to_datetime(["2026-09-25T06:00:00Z", "2026-09-22T06:00:00Z",
                                           None], utc=True),
    })
    now = datetime(2026, 9, 25, 12, tzinfo=UTC)
    stale = {s.source_id: s for s in m.stale_sources(health, now)}
    assert set(stale) == {"lever", "reed"}
    assert stale["lever"].hours_since_success == pytest.approx(78)
    assert "no successful collection" in stale["reed"].message


def test_search_is_case_insensitive_over_title_company_location():
    df = frame(posting(1, title_raw="synthetic_ Graduate Analyst"),
               posting(2, location_raw="Manchester"), posting(3))
    assert m.search(df, "GRADUATE")["posting_id"].tolist() == [1]
    assert m.search(df, "manchester")["posting_id"].tolist() == [2]
    assert len(m.search(df, "  ")) == 3


# ------------------------------------------------------------------ UI smoke test
@pytest.fixture
def synthetic_marts(monkeypatch):
    st = pytest.importorskip("streamlit")
    postings = frame(
        posting(1, has_salary=True, salary_min=28000, salary_max=32000,
                salary_currency="GBP", salary_period="year", salary_raw="£28k-£32k"),
        posting(2, cluster_id=1, is_canonical=False, source_id="lever", source_name="Lever"),
        posting(3, role_category="data_engineer", seniority="senior", is_entry_level=False,
                location_cities=[], working_arrangement="remote"),
    )
    marts = data.Marts(
        postings=postings,
        skills=skills_frame({1: ["SQL", "Python"], 3: ["SQL"]}),
        weeks=pd.DataFrame({"posting_id": [1, 2, 3],
                            "week_start": pd.to_datetime(["2026-09-14"] * 3)}),
        health=pd.DataFrame({
            "source_id": ["greenhouse", "lever", "reed"],
            "display_name": ["Greenhouse", "Lever", "Reed"], "method": ["api", "html", "api"],
            "last_batch_at": pd.to_datetime([datetime.now(UTC)] * 2 + [None], utc=True),
            "last_batch_status": ["success", "success", None], "last_batch_error": [None] * 3,
            "last_success_at": pd.to_datetime([datetime.now(UTC)] * 2 + [None], utc=True),
            "hours_since_success": [0.1, 0.1, None], "failed_batches_7d": [0, 0, 0],
            "batches_7d": [1, 1, 0], "open_quarantine": [0, 0, 0],
            "active_postings": [2, 1, 0], "total_postings": [2, 1, 0],
            "marts_built_at": pd.to_datetime([datetime.now(UTC)] * 3, utc=True),
        }),
        uncertain=pd.DataFrame(columns=["match_rule", "company_a", "title_a", "url_a",
                                        "company_b", "title_b", "url_b", "primary_city"]),
        load_runs=pd.DataFrame(columns=[
            "started_at", "source_id", "mode", "status", "batch_status", "n_collected",
            "n_accepted", "n_rejected", "n_duplicate", "n_out_of_scope", "n_new_postings",
            "duration_seconds", "parser_version"]).astype({"started_at": "datetime64[ns, UTC]"}),
    )
    monkeypatch.setattr(data, "load_marts", lambda *a, **k: marts)
    st.cache_data.clear()
    yield marts
    st.cache_data.clear()


@pytest.mark.parametrize("view", ["Overview", "Skills", "Locations", "Salaries", "Trends",
                                  "Job explorer", "Data quality"])
def test_every_view_renders(synthetic_marts, view):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=30).run()
    at.sidebar.radio[0].set_value(view).run()
    assert not at.exception, [e.value for e in at.exception]
    # Reed never succeeded -> the stale banner is shown on every view.
    assert any("Reed" in w.value for w in at.warning)
    if view == "Overview":
        # Posting 2 is a duplicate of 1: 2 unique jobs, not 3.
        assert at.metric[0].value == "2"
    if view == "Trends":
        assert any("at least two weeks" in i.value for i in at.info)
