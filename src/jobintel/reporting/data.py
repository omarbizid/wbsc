"""Load the dbt `marts` tables into pandas. The dashboard reads nothing else."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import psycopg

from jobintel import db

UNSPECIFIED_CITY = "Unspecified"

POSTINGS_SQL = """
select posting_id, source_id, source_name, source_job_id, scope_key, url,
       title_raw, title_clean, company_clean, location_raw, location_cities, primary_city,
       location_country, working_arrangement, arrangement_evidence,
       salary_min, salary_max, salary_currency, salary_period, salary_period_inferred,
       salary_source, salary_raw, has_salary, posted_date,
       role_category, role_evidence, seniority, seniority_source, seniority_evidence,
       is_entry_level, is_target_role, first_seen_at, last_seen_at, n_observations,
       n_versions, is_active, n_successful_batches_missed, inactive_since,
       cluster_id, cluster_size, cluster_n_sources, is_canonical, parser_version
from marts.dim_postings
"""


class MartsNotBuilt(RuntimeError):
    """The marts schema is missing: run `jobintel transform` first."""


@dataclass
class Marts:
    postings: pd.DataFrame
    skills: pd.DataFrame
    weeks: pd.DataFrame
    health: pd.DataFrame
    uncertain: pd.DataFrame
    load_runs: pd.DataFrame


def _frame(conn: psycopg.Connection, sql: str) -> pd.DataFrame:
    cur = conn.execute(sql)
    return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])


def _utc(df: pd.DataFrame, *cols: str) -> None:
    for c in cols:
        df[c] = pd.to_datetime(df[c], utc=True)


def prepare_postings(df: pd.DataFrame) -> pd.DataFrame:
    """Types for analysis. `cities` always has at least one entry (`Unspecified`)."""
    df = df.copy()
    _utc(df, "first_seen_at", "last_seen_at", "inactive_since")
    for c in ("salary_min", "salary_max"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["cities"] = df["location_cities"].apply(
        lambda cs: sorted(cs) if cs else [UNSPECIFIED_CITY])
    return df


def load_marts(database_url: str | None = None) -> Marts:
    try:
        with db.connect(database_url) as conn:
            postings = _frame(conn, POSTINGS_SQL)
            skills = _frame(conn, "select posting_id, skill, skill_category, matched_text "
                                  "from marts.fct_posting_skills")
            weeks = _frame(conn, "select posting_id, week_start from marts.fct_posting_weeks")
            health = _frame(conn, "select * from marts.mart_source_health order by source_id")
            uncertain = _frame(conn, "select * from marts.mart_uncertain_matches")
            load_runs = _frame(conn, "select * from marts.mart_load_runs "
                                     "order by started_at desc limit 200")
    except psycopg.errors.UndefinedTable as exc:
        raise MartsNotBuilt(str(exc)) from exc

    postings = prepare_postings(postings)
    weeks["week_start"] = pd.to_datetime(weeks["week_start"])
    _utc(health, "last_batch_at", "last_success_at", "marts_built_at")
    _utc(load_runs, "started_at", "finished_at")
    return Marts(postings, skills, weeks, health, uncertain, load_runs)
