"""Source-independent record produced by every parser."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass
class ParsedPosting:
    source: str
    source_job_id: str | None
    scope_key: str
    raw_ref: str                       # "<item file>#<index in item>" for traceability
    url: str | None
    title_raw: str | None
    company_raw: str | None
    description_text: str | None
    location_raw: str | None = None
    language: str | None = None
    posted_date: date | None = None
    source_updated_at: datetime | None = None
    # Structured salary, when the source provides one (otherwise extracted from text)
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_raw: str | None = None
    # Hints from structured source fields (e.g. a "Remote" workplace type)
    arrangement_hint: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def record_key(self) -> str:
        return self.source_job_id or self.raw_ref


@dataclass
class ParseFailure:
    """A raw record the parser could not turn into a ParsedPosting at all."""

    source: str
    scope_key: str
    raw_ref: str
    reason: str
    details: dict = field(default_factory=dict)
    source_job_id: str | None = None

    @property
    def record_key(self) -> str:
        return self.source_job_id or self.raw_ref


@dataclass
class NormalizedPosting:
    """A validated, normalised posting ready to load into core.posting_version."""

    source: str
    source_job_id: str
    scope_key: str
    raw_ref: str
    url: str
    title_raw: str
    title_clean: str
    company_raw: str
    company_clean: str
    location_raw: str | None
    location_cities: list[str]
    location_country: str | None
    is_uk: bool
    working_arrangement: str
    arrangement_evidence: str | None
    description_text: str
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    salary_period: str | None
    salary_period_inferred: bool | None
    salary_source: str | None
    salary_raw: str | None
    posted_date: date | None
    source_updated_at: datetime | None
    language: str | None
    quality_flags: list[str]

    # Fields whose change counts as a meaningful change to the posting.
    HASHED_FIELDS = (
        "url", "title_raw", "company_raw", "location_raw", "working_arrangement",
        "description_text", "salary_min", "salary_max", "salary_currency", "salary_period",
        "posted_date",
    )

    def content_hash(self) -> str:
        payload = {f: getattr(self, f) for f in self.HASHED_FIELDS}
        payload["description_text"] = " ".join((self.description_text or "").split())
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
