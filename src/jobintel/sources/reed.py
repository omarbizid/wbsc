"""Reed.co.uk Jobseeker API (official keyed API).

Access: free developer key, sent as the Basic-auth username with an empty password.
1. GET /api/1.0/search?keywords=…&resultsToTake=100&resultsToSkip=…   (per query, paged)
2. GET /api/1.0/jobs/{jobId}   for each candidate, to get the full description
   and the salary type (per annum / per day / …)
Each detail page costs one request, so only titles the role classifier reads as a target
role (or cannot classify) are fetched. Business/finance analysts and data scientists are
skipped before any request is made.
Every request is counted against `max_requests` per run. If the cap is reached, the
affected query is recorded as failed, so its missing postings are never treated as
"no longer advertised". See docs/source_register.md.

Field names follow Reed's documented fields in camelCase. The parser accepts a few
alternatives so that small naming differences do not silently drop data.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime

from jobintel.config import get_settings
from jobintel.enrich.classify import classify_role
from jobintel.http import FetchError, HttpClient
from jobintel.models import ParsedPosting, ParseFailure
from jobintel.normalize.text import html_to_text
from jobintel.raw_store import RawBatch, RawBatchWriter
from jobintel.sources.base import Source
from jobintel.validate import is_candidate

BASE_URL = "https://www.reed.co.uk/api/1.0"
PAGE_SIZE = 100


def _first(d: dict, *keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def _parse_date(value) -> date | None:
    """Reed dates are dd/mm/yyyy; ISO dates are accepted too. Unknown → None."""
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:10], fmt).date()
        except ValueError:
            continue
    return None


class _RequestCap(Exception):
    pass


# Roles worth a detail request. "unknown" is kept: the title has a data word but no clear
# family, and the full description may still make it relevant.
FETCH_ROLES = {"data_analyst", "data_engineer", "analytics_engineer", "unknown"}


def worth_fetching(title: str | None, location: str | None) -> bool:
    return is_candidate(title, location) and classify_role(title)[0] in FETCH_ROLES


def query_spec(entry: str | dict) -> tuple[str, dict]:
    """A query is a keyword string, or {keywords: …, graduate: true} for Reed's graduate
    filter. Returns (scope_key, extra search params)."""
    if isinstance(entry, str):
        return f"q:{entry}", {"keywords": entry}
    params = {"keywords": entry["keywords"]}
    scope = f"q:{entry['keywords']}"
    if entry.get("graduate"):
        params["graduate"] = "true"
        scope += " [graduate]"
    return scope, params


class ReedSource(Source):
    name = "reed"
    parser_version = "reed-1"
    min_interval = 1.0

    def __init__(self, config: dict | None = None, api_key: str | None = None):
        super().__init__(config)
        self._api_key = api_key if api_key is not None else get_settings().reed_api_key
        self._requests = 0

    def disabled_reason(self) -> str | None:
        return None if self._api_key else "REED_API_KEY is not set (see .env.example)"

    @property
    def queries(self) -> list[str | dict]:
        return self.config.get("queries", [])

    @property
    def max_requests(self) -> int:
        return int(self.config.get("max_requests", 500))

    @property
    def max_pages(self) -> int:
        return int(self.config.get("max_pages_per_query", 5))

    def _get(self, client: HttpClient, url: str, params: dict | None = None):
        if self._requests >= self.max_requests:
            raise _RequestCap(f"request cap of {self.max_requests} reached")
        self._requests += 1
        return client.get(url, params=params, auth=(self._api_key or "", ""))

    def fetch(self, client: HttpClient, writer: RawBatchWriter) -> None:
        if reason := self.disabled_reason():
            raise RuntimeError(reason)
        self._requests = 0
        location = self.config.get("location")
        seen: set[str] = set()
        for n, query in enumerate(self.queries):
            scope, query_params = query_spec(query)
            candidates = []
            try:
                for page in range(self.max_pages):
                    params = {**query_params, "resultsToTake": PAGE_SIZE,
                              "resultsToSkip": page * PAGE_SIZE}
                    if location:
                        params["locationName"] = location
                    url = f"{BASE_URL}/search"
                    resp = self._get(client, url, params)
                    shown = f"{url}?{'&'.join(f'{k}={v}' for k, v in query_params.items())}"                             f"&resultsToSkip={page * PAGE_SIZE}"
                    if resp.status_code != 200:
                        writer.add_failure(scope_key=scope, url=shown,
                                           error=f"HTTP {resp.status_code}",
                                           status_code=resp.status_code,
                                           meta={"kind": "search"})
                        break
                    writer.add(scope_key=scope, url=shown, body=resp.content, status_code=200,
                               content_type="json", meta={"kind": "search", "page": page})
                    data = resp.json()
                    results = data.get("results") or []
                    for r in results:
                        job_id = str(_first(r, "jobId", "id") or "")
                        if job_id and job_id not in seen and worth_fetching(
                                _first(r, "jobTitle", "title"), _first(r, "locationName")):
                            seen.add(job_id)
                            candidates.append(job_id)
                    total = data.get("totalResults") or 0
                    if len(results) < PAGE_SIZE or (page + 1) * PAGE_SIZE >= total:
                        break
                else:
                    # more pages exist than we are allowed to read: scope is incomplete
                    writer.add_failure(scope_key=scope, url=f"{BASE_URL}/search",
                                       error=f"truncated after {self.max_pages} pages",
                                       meta={"kind": "search"})

                for job_id in candidates:
                    url = f"{BASE_URL}/jobs/{job_id}"
                    try:
                        resp = self._get(client, url)
                    except FetchError as exc:
                        writer.add_failure(scope_key=scope, url=url, error=str(exc),
                                           status_code=exc.status_code,
                                           meta={"kind": "detail", "job_id": job_id})
                        continue
                    if resp.status_code != 200:
                        writer.add_failure(scope_key=scope, url=url,
                                           error=f"HTTP {resp.status_code}",
                                           status_code=resp.status_code,
                                           meta={"kind": "detail", "job_id": job_id})
                        continue
                    writer.add(scope_key=scope, url=url, body=resp.content, status_code=200,
                               content_type="json", meta={"kind": "detail", "job_id": job_id})
            except FetchError as exc:
                writer.add_failure(scope_key=scope, url=exc.url, error=str(exc),
                                   status_code=exc.status_code, meta={"kind": "search"})
            except _RequestCap as exc:
                writer.add_failure(scope_key=scope, url=f"{BASE_URL}/search", error=str(exc),
                                   meta={"kind": "cap"})
                # later queries cannot run either; record them as failed, not empty
                for later in self.queries[n + 1:]:
                    writer.add_failure(scope_key=query_spec(later)[0], url=f"{BASE_URL}/search",
                                       error=str(exc), meta={"kind": "cap"})
                return

    def parse(self, batch: RawBatch) -> Iterator[ParsedPosting | ParseFailure]:
        for item in batch.items:
            if not item.ok or item.meta.get("kind") != "detail":
                continue
            raw_ref = f"{item.file}#0"
            try:
                job = json.loads(batch.read(item))
                if not isinstance(job, dict):
                    raise TypeError("detail payload is not an object")
            except Exception as exc:
                yield ParseFailure(self.name, item.scope_key, raw_ref, "unparseable_payload",
                                   {"error": str(exc)}, source_job_id=item.meta.get("job_id"))
                continue
            yield self._parse_job(job, item.scope_key, raw_ref)

    def _parse_job(self, job: dict, scope_key: str, raw_ref: str) -> ParsedPosting:
        job_id = _first(job, "jobId", "id")
        return ParsedPosting(
            source=self.name,
            source_job_id=str(job_id) if job_id is not None else None,
            scope_key=scope_key,
            raw_ref=raw_ref,
            url=_first(job, "jobUrl", "url"),
            title_raw=_first(job, "jobTitle", "title"),
            company_raw=_first(job, "employerName"),
            description_text=html_to_text(_first(job, "jobDescription", "description")),
            location_raw=_first(job, "locationName"),
            language=None,
            posted_date=_parse_date(_first(job, "datePosted", "date")),
            # Structured salary: the advertised figures, as given (not the yearly equivalents)
            salary_min=_first(job, "minimumSalary"),
            salary_max=_first(job, "maximumSalary"),
            salary_currency=_first(job, "currency"),
            salary_period=_first(job, "salaryType"),
            salary_raw=_first(job, "salary"),
            extra={"contract_type": _first(job, "contractType"),
                   "expiration_date": _first(job, "expirationDate"),
                   "external_url": _first(job, "externalUrl")},
        )
