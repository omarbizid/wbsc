"""Lever-hosted career pages, scraped as HTML.

Access: https://jobs.lever.co/robots.txt allows all paths with `Crawl-delay: 1`.
We fetch:
1. the listing page  https://jobs.lever.co/{company}            (one per company)
2. each candidate posting page  https://jobs.lever.co/{company}/{posting_id}
   "Candidate" means a data-family title in a UK (or unrecognised) location, which
   keeps the number of requests small.
Both kinds of page are stored raw. Records are parsed from the posting pages.
See docs/source_register.md.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date

from bs4 import BeautifulSoup

from jobintel.http import FetchError, HttpClient
from jobintel.models import ParsedPosting, ParseFailure
from jobintel.normalize.text import collapse_ws, html_to_text
from jobintel.raw_store import RawBatch, RawBatchWriter
from jobintel.sources.base import Source
from jobintel.validate import is_candidate

BASE_URL = "https://jobs.lever.co"
_POSTING_ID = re.compile(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$")

# Lever "workplaceTypes" label → our arrangement values
_WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on-site": "on-site", "onsite": "on-site",
              "in-office": "on-site", "in office": "on-site"}
# Page sections that are not part of the job description
_SKIP_SECTIONS = {"ai-disclaimer", "btn-apply-bottom"}


def parse_listing(html: str) -> list[dict]:
    """Extract postings from a company listing page."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for post in soup.select("div.posting"):
        link = post.select_one("a.posting-title")
        title = post.select_one("[data-qa=posting-name]")
        if not link or not title:
            continue
        m = _POSTING_ID.search(link.get("href", ""))
        loc = post.select_one(".posting-categories .location")
        wp = post.select_one(".posting-categories .workplaceTypes")
        out.append({
            "posting_id": m.group(1) if m else None,
            "url": link["href"],
            "title": collapse_ws(title.get_text()),
            "location": collapse_ws(loc.get_text()) if loc else None,
            "workplace": collapse_ws(wp.get_text()).strip(" —-") if wp else None,
        })
    return out


def _json_ld(soup: BeautifulSoup) -> dict:
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return {}


def _category(headline, name: str) -> str | None:
    el = headline.select_one(f".posting-categories .{name}")
    return collapse_ws(el.get_text()).strip(" /—-") if el else None


class LeverSource(Source):
    name = "lever"
    parser_version = "lever-1"
    min_interval = 1.0  # robots.txt Crawl-delay: 1

    @property
    def companies(self) -> list[dict]:
        return self.config.get("companies", [])

    def fetch(self, client: HttpClient, writer: RawBatchWriter) -> None:
        for company in self.companies:
            slug = company["slug"]
            url = f"{BASE_URL}/{slug}"
            meta = {"kind": "listing", "company": company.get("company")}
            try:
                resp = client.get(url)
            except FetchError as exc:
                writer.add_failure(scope_key=slug, url=url, error=str(exc),
                                   status_code=exc.status_code, meta=meta)
                continue
            if resp.status_code != 200:
                writer.add_failure(scope_key=slug, url=url, error=f"HTTP {resp.status_code}",
                                   status_code=resp.status_code, meta=meta)
                continue
            writer.add(scope_key=slug, url=url, body=resp.content, status_code=200,
                       content_type="html", meta=meta)

            for post in parse_listing(resp.text):
                if not post["posting_id"] or not is_candidate(post["title"], post["location"]):
                    continue
                pmeta = {"kind": "posting", "company": company.get("company"), **post}
                try:
                    presp = client.get(post["url"])
                except FetchError as exc:
                    writer.add_failure(scope_key=slug, url=post["url"], error=str(exc),
                                       status_code=exc.status_code, meta=pmeta)
                    continue
                if presp.status_code != 200:
                    # e.g. 404: closed between listing and fetch. Still a gap in this scope.
                    writer.add_failure(scope_key=slug, url=post["url"],
                                       error=f"HTTP {presp.status_code}",
                                       status_code=presp.status_code, meta=pmeta)
                    continue
                writer.add(scope_key=slug, url=post["url"], body=presp.content,
                           status_code=200, content_type="html", meta=pmeta)

    def parse(self, batch: RawBatch) -> Iterator[ParsedPosting | ParseFailure]:
        for item in batch.items:
            if not item.ok or item.meta.get("kind") != "posting":
                continue
            raw_ref = f"{item.file}#0"
            try:
                html = batch.read(item).decode("utf-8", errors="replace")
                yield self._parse_posting(html, item.url, item.scope_key, item.meta, raw_ref)
            except _StructureChanged as exc:
                yield ParseFailure(self.name, item.scope_key, raw_ref, "html_structure_changed",
                                   {"missing": str(exc), "url": item.url},
                                   source_job_id=item.meta.get("posting_id"))

    def _parse_posting(self, html: str, url: str, scope_key: str, meta: dict,
                       raw_ref: str) -> ParsedPosting:
        soup = BeautifulSoup(html, "lxml")
        headline = soup.select_one(".posting-headline")
        if headline is None or headline.select_one("h2") is None:
            raise _StructureChanged(".posting-headline h2")
        ld = _json_ld(soup)

        parts = []
        for sec in soup.select("div.section.page-centered"):
            classes = set(sec.get("class", []))
            if {"posting-header", "last-section-apply"} & classes:
                continue
            if sec.get("data-qa") in _SKIP_SECTIONS:
                continue
            parts.append(html_to_text(str(sec)))
        description = "\n\n".join(p for p in parts if p)

        workplace = (_category(headline, "workplaceTypes") or "").lower()
        posted = None
        if ld.get("datePosted"):
            try:
                posted = date.fromisoformat(ld["datePosted"][:10])
            except ValueError:
                posted = None
        salary = ld.get("baseSalary") or {}
        value = salary.get("value") if isinstance(salary, dict) else None
        m = _POSTING_ID.search(url)
        return ParsedPosting(
            source=self.name,
            source_job_id=(m.group(1) if m else None) or meta.get("posting_id"),
            scope_key=scope_key,
            raw_ref=raw_ref,
            url=url,
            title_raw=collapse_ws(headline.select_one("h2").get_text()),
            company_raw=((ld.get("hiringOrganization") or {}).get("name")
                         or meta.get("company")),
            description_text=description,
            location_raw=_category(headline, "location"),
            language=None,
            posted_date=posted,
            # Structured salary only if the page publishes schema.org baseSalary
            salary_min=value.get("minValue") if isinstance(value, dict) else None,
            salary_max=value.get("maxValue") if isinstance(value, dict) else None,
            salary_currency=salary.get("currency") if isinstance(salary, dict) else None,
            salary_period=value.get("unitText") if isinstance(value, dict) else None,
            arrangement_hint=_WORKPLACE.get(workplace),
            extra={"department": _category(headline, "department"),
                   "commitment": _category(headline, "commitment")},
        )


class _StructureChanged(Exception):
    """The page no longer has the elements the parser relies on."""
