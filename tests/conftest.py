"""Shared fixtures.

Fixture files under tests/fixtures/<source>/ are trimmed *real* source responses.
Hand-made records are built in code and marked with the `synthetic_` prefix and
`is_synthetic=True` on their batch.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from jobintel.raw_store import RawBatch, RawBatchWriter

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(rel: str) -> dict:
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def make_batch(root: Path, source: str, payloads: dict[str, dict | bytes], *,
               failures: dict[str, str] | None = None, is_synthetic: bool = False,
               batch_id: str | None = None) -> RawBatch:
    """Build a finished raw batch: one item per scope (payload), plus failed scopes."""
    w = RawBatchWriter(root, source, is_synthetic=is_synthetic, batch_id=batch_id)
    for scope, payload in payloads.items():
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        w.add(scope_key=scope, url=f"https://example.test/{scope}", body=body,
              status_code=200, content_type="json", meta={"company": scope.title()})
    for scope, err in (failures or {}).items():
        w.add_failure(scope_key=scope, url=f"https://example.test/{scope}", error=err)
    return w.finish()


def synthetic_greenhouse_job(job_id: int | None = 900001, **overrides) -> dict:
    """A clearly synthetic Greenhouse-shaped job (not real data)."""
    job = {
        "id": job_id,
        "title": "synthetic_ Graduate Data Analyst",
        "absolute_url": f"https://example.test/jobs/{job_id}",
        "location": {"name": "Leeds, United Kingdom"},
        "company_name": "synthetic_ Example Ltd",
        "language": "en",
        "first_published": None,
        "updated_at": "2026-09-01T10:00:00+00:00",
        "content": "&lt;p&gt;SYNTHETIC TEST RECORD. You will use SQL, Python and Tableau "
                   "to analyse customer data and build dashboards for stakeholders. "
                   "Training is provided for graduates joining the analytics team.&lt;/p&gt;",
        "offices": [],
        "departments": [],
    }
    if job_id is None:
        job.pop("id")
    job.update(overrides)
    return job


# ------------------------------------------------------------------ database
@pytest.fixture(scope="session")
def db_url():
    """A throwaway database per test session (skipped when DATABASE_URL is unset)."""
    import psycopg

    from jobintel.config import get_settings

    base = os.environ.get("TEST_DATABASE_URL") or get_settings().database_url
    if not base:
        pytest.skip("DATABASE_URL not set; skipping database tests")
    name = f"jobintel_test_{uuid.uuid4().hex[:8]}"
    admin_url = base.rsplit("/", 1)[0] + "/postgres"
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'create database "{name}"')
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    url = base.rsplit("/", 1)[0] + f"/{name}"
    from jobintel import db

    with psycopg.connect(url) as conn:
        db.migrate(conn)
    yield url
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture
def conn(db_url):
    import psycopg

    with psycopg.connect(db_url) as c:
        yield c
        # isolate tests: clear data tables, keep reference data (ops.source)
        c.rollback()
        c.execute("""truncate core.posting_observation, core.posting_version, core.posting,
                     ops.quarantine, ops.load_run, ops.batch_scope, ops.collection_batch
                     restart identity cascade""")
        c.commit()


def count(conn, table: str) -> int:
    return conn.execute(f"select count(*) from {table}").fetchone()[0]
