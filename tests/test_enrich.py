"""Skill extraction, role/seniority classification, evaluation gate, and enrichment storage."""

from __future__ import annotations

import pytest

from jobintel.enrich.classify import SENIORITY_LEVELS, classify, classify_role, classify_seniority
from jobintel.enrich.evaluate import evaluate, load_set
from jobintel.enrich.skills import SkillExtractor
from jobintel.load import load_batch
from jobintel.sources.greenhouse import GreenhouseSource

from .conftest import count, load_fixture, make_batch, synthetic_greenhouse_job

EX = SkillExtractor()


def skills(text: str) -> set[str]:
    return {h.skill for h in EX.extract(text)}


# ------------------------------------------------------------------ skills
@pytest.mark.parametrize(
    "text, expected",
    [
        # acceptance test: "JavaScript" must not produce "Java"
        ("Experience with JavaScript and TypeScript", {"JavaScript"}),
        ("Java and JavaScript", {"Java", "JavaScript"}),
        ("Strong SQL; NoSQL is a plus", {"SQL"}),
        ("MySQL and Postgres", {"MySQL", "PostgreSQL"}),         # alias → canonical
        ("PostgreSQL experience", {"PostgreSQL"}),
        ("T-SQL and SSIS", {"SQL", "SQL Server"}),
        ("Python or R for analysis", {"Python", "R"}),
        ("Our R&D team", set()),                                 # "R" in R&D
        ("Grade R band", set()),                                 # R without context
        ("Build dashboards in PowerBI and Power BI", {"Power BI"}),
        ("Apache SparkTM and PySpark", {"Spark"}),
        ("the spark of curiosity", set()),                       # ordinary word
        ("e.g. spark, hadoop", {"Spark"}),                       # lowercase with context
        ("snowflake schema design", set()),
        ("You will excel in this role", set()),
        ("Advanced Excel", {"Excel"}),
        ("Google Cloud Platform and BigQuery", {"GCP", "BigQuery"}),
        ("GitHub Actions", {"Git"}),
        ("Prior experience at Databricks, Snowflake or AWS", set()),  # former employers
        ("pandas, NumPy and scikit-learn", {"pandas", "NumPy", "scikit-learn"}),
        ("", set()),
    ],
)
def test_skill_extraction(text, expected):
    assert skills(text) == expected


def test_each_skill_reported_once_with_evidence():
    hits = EX.extract("Python, python and PYTHON")
    assert [h.skill for h in hits] == ["Python"]
    assert hits[0].matched_text == "Python"


def test_labels_only_use_taxonomy_skills():
    for name in ("tune", "eval"):
        _, labels = load_set(name)
        assert {s for v in labels.values() for s in v} <= set(EX.names)


def test_evaluation_meets_precision_target():
    """Regression gate: the held-out eval set must stay at >= 90% precision."""
    res = evaluate("eval")
    assert res.n_postings >= 50
    assert res.precision >= 0.90, res.errors


# ------------------------------------------------------------------ classification
@pytest.mark.parametrize(
    "title, role",
    [
        ("Graduate Data Analyst", "data_analyst"),
        ("Senior BI Developer", "data_analyst"),
        ("Head of Marketing Analytics", "data_analyst"),
        ("Junior Data Engineer", "data_engineer"),
        ("Head of Data Engineering & Governance", "data_engineer"),
        ("Staff Analytics Engineer", "analytics_engineer"),
        ("Analytics Engineering Manager", "analytics_engineer"),
        ("Senior Data Scientist (Economist)", "data_scientist"),
        ("AI & Business Intelligence Program Manager", "other"),
        ("Senior Regulatory Reporting Analyst", "other"),
        ("Machine Learning Engineer (Synthetic Data)", "other"),
        ("Commercial Analyst", "other"),
        ("Finance Systems Data Assistant", "unknown"),
    ],
)
def test_role_category(title, role):
    assert classify_role(title)[0] == role


@pytest.mark.parametrize(
    "title, description, level, source",
    [
        ("Graduate Data Analyst", None, "entry", "title"),
        ("Junior Data Engineer", None, "entry", "title"),
        ("Data Analyst Intern", None, "intern", "title"),
        ("Associate Director, Data", None, "manager", "title"),   # not entry
        ("Senior Data Analyst", None, "senior", "title"),
        ("Risk Analyst III", None, "senior", "title"),
        ("Analyst II, Credit", None, "mid", "title"),
        ("Staff Data Engineer", None, "lead", "title"),
        ("Data Science Manager", None, "manager", "title"),
        ("Data Analyst", "Join our graduate scheme in Leeds.", "entry", "description"),
        ("Data Analyst", "You have 3+ years of experience with SQL.", "mid", "description"),
        ("Data Analyst", "5+ years' commercial experience required.", "senior", "description"),
        ("Data Analyst", "A great team.", "unknown", "none"),
    ],
)
def test_seniority(title, description, level, source):
    got_level, got_source, _ = classify_seniority(title, description)
    assert (got_level, got_source) == (level, source)
    assert got_level in SENIORITY_LEVELS


def test_classify_returns_evidence():
    c = classify("Senior Data Analyst", None)
    assert c.role_evidence == "Data Analyst" and c.seniority_evidence == "Senior"


# ------------------------------------------------------------------ storage (DB)
@pytest.mark.db
def test_load_enriches_versions_idempotently(conn, tmp_path):
    gh = GreenhouseSource({})
    batch = make_batch(tmp_path, "greenhouse",
                       {"monzo": load_fixture("greenhouse/board_sample.json"),
                        "s": {"jobs": [synthetic_greenhouse_job()]}})
    load_batch(conn, gh, batch)
    first = (count(conn, "core.version_skill"), count(conn, "core.version_classification"))
    load_batch(conn, gh, batch, mode="replay")
    assert (count(conn, "core.version_skill"), count(conn, "core.version_classification")) == first
    assert first[1] == 3
    rows = dict(conn.execute(
        """select v.title_clean, c.role_category from core.version_classification c
           join core.posting_version v using (version_id)""").fetchall())
    assert rows["Analytics Engineer"] == "analytics_engineer"
    skills_synth = {r[0] for r in conn.execute(
        """select s.skill from core.version_skill s join core.posting_version v using (version_id)
           where v.title_raw like 'synthetic_%'""")}
    assert skills_synth == {"SQL", "Python", "Tableau"}
