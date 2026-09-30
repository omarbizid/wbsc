"""Greenhouse Job Board API (public company career boards).

Access: GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
No authentication is needed ("Job Board data is publicly available"). One request
per board per run returns every open job with its full description.
See docs/source_register.md.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime

from jobintel.http import FetchError, HttpClient
from jobintel.models import ParsedPosting, ParseFailure
from jobintel.normalize.text import html_to_text
from jobintel.raw_store import RawBatch, RawBatchWriter
from jobintel.sources.base import Source

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class GreenhouseSource(Source):
    name = "greenhouse"
    parser_version = "greenhouse-1"
    min_interval = 1.0

    @property
    def boards(self) -> list[dict]:
        return self.config.get("boards", [])

    def fetch(self, client: HttpClient, writer: RawBatchWriter) -> None:
        for board in self.boards:
            token = board["token"]
            url = f"{BASE_URL}/{token}/jobs?content=true"
            meta = {"board": token, "company": board.get("company")}
            try:
                resp = client.get(url)
            except FetchError as exc:
                writer.add_failure(scope_key=token, url=url, error=str(exc),
                                   status_code=exc.status_code, meta=meta)
                continue
            if resp.status_code != 200:
                writer.add_failure(scope_key=token, url=url, error=f"HTTP {resp.status_code}",
                                   status_code=resp.status_code, meta=meta)
                continue
            writer.add(scope_key=token, url=url, body=resp.content,
                       status_code=resp.status_code, content_type="json", meta=meta)

    def parse(self, batch: RawBatch) -> Iterator[ParsedPosting | ParseFailure]:
        for item in batch.items:
            if not item.ok:
                continue
            try:
                payload = json.loads(batch.read(item))
                jobs = payload["jobs"]
                if not isinstance(jobs, list):
                    raise TypeError("'jobs' is not a list")
            except Exception as exc:
                yield ParseFailure(self.name, item.scope_key, item.file or str(item.index),
                                   "unparseable_payload", {"error": str(exc)})
                continue
            for i, job in enumerate(jobs):
                raw_ref = f"{item.file}#{i}"
                if not isinstance(job, dict):
                    yield ParseFailure(self.name, item.scope_key, raw_ref,
                                       "unexpected_record_type", {"type": type(job).__name__})
                    continue
                yield self._parse_job(job, item.scope_key, item.meta, raw_ref)

    def _parse_job(self, job: dict, scope_key: str, meta: dict, raw_ref: str) -> ParsedPosting:
        job_id = job.get("id")
        published = _parse_dt(job.get("first_published"))
        location = (job.get("location") or {}).get("name")
        offices = [o.get("name") for o in job.get("offices") or [] if o.get("name")]
        return ParsedPosting(
            source=self.name,
            source_job_id=str(job_id) if job_id not in (None, "") else None,
            scope_key=scope_key,
            raw_ref=raw_ref,
            url=job.get("absolute_url"),
            title_raw=job.get("title"),
            company_raw=job.get("company_name") or meta.get("company"),
            description_text=html_to_text(job.get("content")),
            location_raw=location,
            language=job.get("language"),
            # first_published is the date the employer published the job; only used if present
            posted_date=published.date() if published else None,
            source_updated_at=_parse_dt(job.get("updated_at")),
            extra={"offices": offices,
                   "departments": [d.get("name") for d in job.get("departments") or []]},
        )
