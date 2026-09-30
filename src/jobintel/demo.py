"""Fresh-checkout demo: load saved source responses into an empty database, then run dbt.

No network access. The responses in `tests/fixtures/` are real pages/API responses saved
from each source (Greenhouse board, Lever listing + posting page, Reed job details). They
go through the same raw store → parse → validate → load path as a live collection, so
the demo exercises the real pipeline. It is a small sample (a handful of postings), not
a market picture.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg

from jobintel import db
from jobintel.config import PROJECT_ROOT
from jobintel.load import LoadStats, load_batch
from jobintel.raw_store import RawBatchWriter
from jobintel.sources.greenhouse import GreenhouseSource
from jobintel.sources.lever import LeverSource, parse_listing
from jobintel.sources.reed import BASE_URL as REED_API, ReedSource

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
DEMO_RAW = PROJECT_ROOT / "data" / "demo_raw"
LEVER_POSTING_ID = "962f3756-6e45-480f-984c-64e024b57c4f"
REED_JOB_IDS = ("57348882", "57385023")


class NotEmpty(RuntimeError):
    pass


def _greenhouse(raw_root: Path):
    w = RawBatchWriter(raw_root, "greenhouse")
    w.add(scope_key="monzo", url="https://boards-api.greenhouse.io/v1/boards/monzo/jobs?content=true",
          body=(FIXTURES / "greenhouse/board_sample.json").read_bytes(), status_code=200,
          content_type="json", meta={"board": "monzo", "company": "Monzo"})
    return GreenhouseSource({}), w.finish()


def _lever(raw_root: Path):
    listing = (FIXTURES / "lever/zopa_listing.html").read_bytes()
    post = next(p for p in parse_listing(listing.decode("utf-8"))
                if p["posting_id"] == LEVER_POSTING_ID)
    w = RawBatchWriter(raw_root, "lever")
    w.add(scope_key="zopa", url="https://jobs.lever.co/zopa", body=listing, status_code=200,
          content_type="html", meta={"kind": "listing", "company": "Zopa"})
    w.add(scope_key="zopa", url=post["url"],
          body=(FIXTURES / "lever/zopa_graduate_analyst.html").read_bytes(), status_code=200,
          content_type="html", meta={"kind": "posting", "company": "Zopa", **post})
    return LeverSource({}), w.finish()


def _reed(raw_root: Path):
    w = RawBatchWriter(raw_root, "reed")
    for job_id in REED_JOB_IDS:
        body = (FIXTURES / f"reed/job_{job_id}.json").read_bytes()
        json.loads(body)  # fail early on a broken fixture
        w.add(scope_key="q:junior data analyst", url=f"{REED_API}/jobs/{job_id}", body=body,
              status_code=200, content_type="json", meta={"kind": "detail", "job_id": job_id})
    return ReedSource({}, api_key="demo-no-network"), w.finish()


def load_demo(conn: psycopg.Connection, raw_root: Path = DEMO_RAW, *,
              force: bool = False) -> list[LoadStats]:
    """Apply migrations and load the demo batches. Refuses to mix the demo into a
    database that already holds collected data, unless `force`."""
    db.migrate(conn)
    other = conn.execute(
        "select count(*) from ops.collection_batch where raw_path not like %s",
        (f"%{Path(raw_root).name}%",)).fetchone()[0]
    if other and not force:
        raise NotEmpty(f"the database already holds {other} collected batches; the demo is "
                       "meant for an empty database (use --force to load it anyway)")
    return [load_batch(conn, source, batch, mode="live")
            for source, batch in (_greenhouse(raw_root), _lever(raw_root), _reed(raw_root))]
