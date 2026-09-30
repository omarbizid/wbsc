"""Validate a ParsedPosting, normalise it, and decide whether it is in scope.

Outcomes:
- Rejection    → quarantined with a reason code (the record is invalid)
- OutOfScope   → valid, but not a UK / English / data-family posting; counted, not loaded
- NormalizedPosting → loaded
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobintel.models import NormalizedPosting, ParsedPosting
from jobintel.normalize.arrangement import classify_arrangement
from jobintel.normalize.location import parse_location
from jobintel.normalize.salary import extract_salary_from_text, normalize_structured
from jobintel.normalize.text import clean_company, clean_title, collapse_ws

# Bump whenever normalisation output changes (location, salary, arrangement, cleaning).
NORMALIZER_VERSION = "norm-3"

REQUIRED_FIELDS = ("source_job_id", "url", "title_raw", "company_raw", "description_text")
MIN_DESCRIPTION_CHARS = 100

# Broad pre-filter on titles. The role classifier (M3) decides the exact category;
# this keeps obviously unrelated postings (e.g. "Backend Engineer") out of the store.
DATA_FAMILY_TITLE = re.compile(
    r"\bdata\b|\banalyt|\banalyst\b|\bbi\b|business\s+intelligence|\binsights?\b|\bdbt\b"
    r"|\betl\b|\bsql\b|\breporting\b|\bmi\s+analyst\b",
    re.I,
)


def is_candidate(title: str | None, location: str | None) -> bool:
    """Cheap pre-filter used *before* fetching a detail page, to avoid needless requests.

    Keeps data-family titles whose location is UK or not recognisable. The full scope
    decision is still made by `normalize_posting` on the parsed record.
    """
    if not title or not DATA_FAMILY_TITLE.search(title):
        return False
    loc = parse_location(location)
    return loc.is_uk or not (loc.other_countries or loc.cities)


@dataclass
class Rejection:
    reason: str
    details: dict = field(default_factory=dict)


@dataclass
class OutOfScope:
    reason: str


def normalize_posting(p: ParsedPosting) -> NormalizedPosting | Rejection | OutOfScope:
    missing = [f for f in REQUIRED_FIELDS if not collapse_ws(getattr(p, f))]
    if missing:
        return Rejection("missing_required_field", {"fields": missing})
    if not re.match(r"^https?://", p.url):
        return Rejection("invalid_url", {"url": p.url})
    if len(p.description_text.strip()) < MIN_DESCRIPTION_CHARS:
        return Rejection("description_too_short", {"chars": len(p.description_text.strip())})

    if p.language and not p.language.lower().startswith("en"):
        return OutOfScope("non_english")
    if not DATA_FAMILY_TITLE.search(p.title_raw):
        return OutOfScope("not_data_family_title")

    offices = p.extra.get("offices") or []
    loc = parse_location(p.location_raw, *offices)
    if not loc.is_uk:
        return OutOfScope("not_uk")

    flags: list[str] = []
    salary = None
    if p.salary_min is not None or p.salary_max is not None:
        salary = normalize_structured(p.salary_min, p.salary_max, p.salary_currency,
                                      p.salary_period, p.salary_raw)
        if salary and salary.currency is None:
            flags.append("salary_dropped_no_currency")
            salary = None
    if salary is None:
        salary = extract_salary_from_text(p.description_text)

    arrangement, evidence = classify_arrangement(
        hint=p.arrangement_hint, location=p.location_raw, title=p.title_raw,
        description=p.description_text,
    )

    return NormalizedPosting(
        source=p.source,
        source_job_id=p.source_job_id.strip(),
        scope_key=p.scope_key,
        raw_ref=p.raw_ref,
        url=p.url.strip(),
        title_raw=p.title_raw,
        title_clean=clean_title(p.title_raw),
        company_raw=p.company_raw,
        company_clean=clean_company(p.company_raw),
        location_raw=p.location_raw,
        location_cities=loc.cities,
        location_country=loc.country,
        is_uk=loc.is_uk,
        working_arrangement=arrangement,
        arrangement_evidence=evidence,
        description_text=p.description_text,
        salary_min=salary.min if salary else None,
        salary_max=salary.max if salary else None,
        salary_currency=salary.currency if salary else None,
        salary_period=salary.period if salary else None,
        salary_period_inferred=salary.period_inferred if salary else None,
        salary_source=salary.source if salary else None,
        salary_raw=salary.raw if salary else None,
        posted_date=p.posted_date,
        source_updated_at=p.source_updated_at,
        language=p.language,
        quality_flags=flags,
    )
