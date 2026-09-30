"""Load a raw batch into PostgreSQL. Idempotent: loading the same batch again is a no-op
for business data, and a *replay* after a parser fix rebuilds that batch's contribution.

Count semantics (per load run, recorded in ops.load_run):
    n_collected = n_accepted + n_rejected + n_out_of_scope + n_duplicate
    n_duplicate  = repeated within the batch, or already observed for this batch (rerun)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from jobintel.enrich.store import enrich_versions, stale_version_ids
from jobintel.models import NormalizedPosting, ParseFailure
from jobintel.raw_store import RawBatch
from jobintel.sources.base import Source
from jobintel.validate import NORMALIZER_VERSION, OutOfScope, Rejection, normalize_posting

log = logging.getLogger(__name__)


def processing_version(source: Source) -> str:
    """Version label for everything that shapes stored output: parser + normaliser."""
    return f"{source.parser_version}/{NORMALIZER_VERSION}"


@dataclass
class LoadStats:
    load_run_id: int
    batch_id: str
    status: str = "running"
    n_collected: int = 0
    n_out_of_scope: int = 0
    n_accepted: int = 0
    n_rejected: int = 0
    n_duplicate: int = 0
    n_new_postings: int = 0
    n_new_versions: int = 0
    error: str | None = None


def register_batch(conn: psycopg.Connection, batch: RawBatch) -> None:
    """Record (or refresh) the batch from its manifest. The manifest is the source of truth."""
    n_failed = sum(not it.ok for it in batch.items)
    conn.execute(
        """insert into ops.collection_batch
             (batch_id, source_id, started_at, finished_at, status, n_items, n_failed_items,
              error, raw_path, is_synthetic)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (batch_id) do update set
             finished_at = excluded.finished_at, status = excluded.status,
             n_items = excluded.n_items, n_failed_items = excluded.n_failed_items,
             error = excluded.error, raw_path = excluded.raw_path,
             is_synthetic = excluded.is_synthetic""",
        (batch.batch_id, batch.source, batch.started_at, batch.finished_at, batch.status,
         len(batch.items), n_failed, batch.error, str(batch.path), batch.is_synthetic),
    )
    for scope_key, status in batch.scope_status().items():
        errors = [it.error for it in batch.items if it.scope_key == scope_key and it.error]
        conn.execute(
            """insert into ops.batch_scope (batch_id, scope_key, status, error)
               values (%s, %s, %s, %s)
               on conflict (batch_id, scope_key) do update set
                 status = excluded.status, error = excluded.error""",
            (batch.batch_id, scope_key, status, "; ".join(errors) or None),
        )


def load_batch(conn: psycopg.Connection, source: Source, batch: RawBatch,
               mode: str = "live") -> LoadStats:
    with conn.transaction():
        register_batch(conn, batch)
        run_id = conn.execute(
            """insert into ops.load_run (batch_id, mode, parser_version, status)
               values (%s, %s, %s, 'running') returning load_run_id""",
            (batch.batch_id, mode, processing_version(source)),
        ).fetchone()[0]
    stats = LoadStats(load_run_id=run_id, batch_id=batch.batch_id)
    try:
        with conn.transaction():
            _load_records(conn, source, batch, stats)
        stats.status = "success"
    except Exception as exc:  # recorded on the run; the caller inspects stats.status
        log.exception("load of batch %s failed", batch.batch_id)
        stats.status, stats.error = "failed", f"{type(exc).__name__}: {exc}"
    with conn.transaction():
        conn.execute(
            """update ops.load_run set
                 status = %s, finished_at = now(), error = %s, n_collected = %s,
                 n_out_of_scope = %s, n_accepted = %s, n_rejected = %s, n_duplicate = %s,
                 n_new_postings = %s, n_new_versions = %s
               where load_run_id = %s""",
            (stats.status, stats.error, stats.n_collected, stats.n_out_of_scope,
             stats.n_accepted, stats.n_rejected, stats.n_duplicate, stats.n_new_postings,
             stats.n_new_versions, run_id),
        )
    return stats


def _load_records(conn: psycopg.Connection, source: Source, batch: RawBatch,
                  stats: LoadStats) -> None:
    fetched_at = {it.file: it.fetched_at for it in batch.items if it.file}
    seen: set[str] = set()
    for rec in source.parse(batch):
        stats.n_collected += 1
        if isinstance(rec, ParseFailure):
            _quarantine(conn, batch, source, stats, rec.record_key, rec.reason, rec.details,
                        rec.raw_ref)
            continue
        result = normalize_posting(rec)
        if isinstance(result, Rejection):
            _quarantine(conn, batch, source, stats, rec.record_key, result.reason,
                        result.details, rec.raw_ref)
            continue
        if isinstance(result, OutOfScope):
            stats.n_out_of_scope += 1
            continue
        if result.source_job_id in seen:
            stats.n_duplicate += 1
            continue
        seen.add(result.source_job_id)
        observed_at = fetched_at.get(result.raw_ref.split("#")[0]) or batch.started_at
        if _upsert_posting(conn, batch, result, datetime.fromisoformat(observed_at),
                           processing_version(source), stats):
            stats.n_accepted += 1
        else:
            stats.n_duplicate += 1

    # This run defines the batch's contribution: drop observations it no longer
    # produces (e.g. after a parser fix) and resolve quarantine entries it no longer hits.
    conn.execute(
        "delete from core.posting_observation where batch_id = %s and load_run_id <> %s",
        (batch.batch_id, stats.load_run_id),
    )
    conn.execute(
        """update ops.quarantine set resolved_at = now()
           where batch_id = %s and load_run_id <> %s and resolved_at is null""",
        (batch.batch_id, stats.load_run_id),
    )
    # Derived data (skills, role, seniority) for versions seen in this batch that lack it
    # or were made by an older extractor/classifier.
    touched = [r[0] for r in conn.execute(
        "select distinct version_id from core.posting_observation where batch_id = %s",
        (batch.batch_id,))]
    stale = set(stale_version_ids(conn))
    enrich_versions(conn, [v for v in touched if v in stale])
    conn.execute(
        """update core.posting p set first_seen_at = o.first_seen, last_seen_at = o.last_seen
           from (select posting_id, min(observed_at) first_seen, max(observed_at) last_seen
                 from core.posting_observation group by posting_id) o
           where o.posting_id = p.posting_id and p.source_id = %s""",
        (batch.source,),
    )


def _quarantine(conn, batch: RawBatch, source: Source, stats: LoadStats, record_key: str,
                reason: str, details: dict, raw_ref: str) -> None:
    stats.n_rejected += 1
    conn.execute(
        """insert into ops.quarantine
             (batch_id, source_id, record_key, reason, details, raw_ref, parser_version,
              load_run_id)
           values (%s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (batch_id, record_key) do update set
             reason = excluded.reason, details = excluded.details, raw_ref = excluded.raw_ref,
             parser_version = excluded.parser_version, load_run_id = excluded.load_run_id,
             last_seen_at = now(), resolved_at = null""",
        (batch.batch_id, source.name, record_key, reason,
         Jsonb(json.loads(json.dumps(details, default=str))), raw_ref, processing_version(source),
         stats.load_run_id),
    )


def _upsert_posting(conn, batch: RawBatch, p: NormalizedPosting, observed_at: datetime,
                    parser_version: str, stats: LoadStats) -> bool:
    """Returns True if a new observation was created, False if it already existed."""
    posting_id, new_posting = conn.execute(
        """insert into core.posting (source_id, source_job_id, scope_key, first_seen_at,
                                     last_seen_at)
           values (%s, %s, %s, %s, %s)
           on conflict (source_id, source_job_id) do update set
             scope_key = excluded.scope_key,
             first_seen_at = least(core.posting.first_seen_at, excluded.first_seen_at),
             last_seen_at = greatest(core.posting.last_seen_at, excluded.last_seen_at)
           returning posting_id, (xmax = 0)""",
        (p.source, p.source_job_id, p.scope_key, observed_at, observed_at),
    ).fetchone()
    stats.n_new_postings += int(new_posting)

    version_id, new_version = conn.execute(
        """insert into core.posting_version (
             posting_id, content_hash, parser_version, url, title_raw, title_clean,
             company_raw, company_clean, location_raw, location_cities, location_country,
             is_uk, working_arrangement, arrangement_evidence, description_text,
             salary_min, salary_max, salary_currency, salary_period, salary_period_inferred,
             salary_source, salary_raw, posted_date, source_updated_at, language,
             quality_flags, first_seen_at)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (posting_id, content_hash) do update set
             first_seen_at = least(core.posting_version.first_seen_at, excluded.first_seen_at)
           returning version_id, (xmax = 0)""",
        (posting_id, p.content_hash(), parser_version, p.url, p.title_raw,
         p.title_clean, p.company_raw, p.company_clean, p.location_raw, p.location_cities,
         p.location_country, p.is_uk, p.working_arrangement, p.arrangement_evidence,
         p.description_text, p.salary_min, p.salary_max, p.salary_currency, p.salary_period,
         p.salary_period_inferred, p.salary_source, p.salary_raw, p.posted_date,
         p.source_updated_at, p.language, p.quality_flags, observed_at),
    ).fetchone()
    stats.n_new_versions += int(new_version)

    (new_obs,) = conn.execute(
        """insert into core.posting_observation
             (posting_id, batch_id, version_id, observed_at, load_run_id)
           values (%s, %s, %s, %s, %s)
           on conflict (posting_id, batch_id) do update set
             version_id = excluded.version_id, load_run_id = excluded.load_run_id
           returning (xmax = 0)""",
        (posting_id, batch.batch_id, version_id, observed_at, stats.load_run_id),
    ).fetchone()
    return bool(new_obs)

