"""Orchestration of collect (network → raw store) and load/replay (raw store → DB).

Each source is isolated: an exception in one source is recorded on that source's
batch and never prevents the remaining sources from running.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from pathlib import Path

import psycopg

from jobintel.config import get_settings, load_sources_config
from jobintel.http import HttpClient
from jobintel.load import LoadStats, load_batch
from jobintel.raw_store import RawBatch, RawBatchWriter, find_batch, find_batches
from jobintel.sources import get_source
from jobintel.sources.base import Source

log = logging.getLogger(__name__)


@dataclass
class SourceResult:
    source: str
    batch: RawBatch | None
    load: LoadStats | None
    error: str | None = None
    skipped: str | None = None   # reason, when the source is not configured to run


def collect_source(source: Source, raw_root: Path, user_agent: str,
                   client: HttpClient | None = None) -> RawBatch:
    """Fetch one source into a new raw batch. Always returns a finished batch."""
    writer = RawBatchWriter(raw_root, source.name)
    own_client = client is None
    client = client or HttpClient(user_agent, min_interval=source.min_interval)
    try:
        source.fetch(client, writer)
    except Exception as exc:
        log.exception("collection of %s failed", source.name)
        return writer.finish(error=f"{type(exc).__name__}: {exc}")
    finally:
        if own_client:
            client.close()
    return writer.finish()


def collect_and_load(conn: psycopg.Connection | None, source_names: list[str],
                     *, client_factory=None) -> list[SourceResult]:
    settings = get_settings()
    cfg = load_sources_config()
    results = []
    for name in source_names:
        batch = stats = None
        try:
            source = get_source(name, cfg)
            if reason := source.disabled_reason():
                log.warning("skipping %s: %s", name, reason)
                results.append(SourceResult(name, None, None, skipped=reason))
                continue
            client = client_factory(source) if client_factory else None
            batch = collect_source(source, settings.raw_data_dir, settings.user_agent, client)
            log.info("%s: batch %s status=%s items=%d", name, batch.batch_id, batch.status,
                     len(batch.items))
            if conn is not None:
                stats = load_batch(conn, source, batch, mode="live")
            results.append(SourceResult(name, batch, stats, batch.error))
        except Exception as exc:
            log.error("source %s failed: %s", name, traceback.format_exc())
            results.append(SourceResult(name, batch, stats, f"{type(exc).__name__}: {exc}"))
    return results


def replay(conn: psycopg.Connection, *, batch_id: str | None = None,
           source_name: str | None = None, raw_root: Path | None = None) -> list[LoadStats]:
    """Reprocess saved raw batches. Never touches the network."""
    raw_root = raw_root or get_settings().raw_data_dir
    cfg = load_sources_config()
    paths = [find_batch(raw_root, batch_id)] if batch_id else find_batches(raw_root, source_name)
    out = []
    for path in paths:
        batch = RawBatch.load(path)
        source = get_source(batch.source, cfg)
        out.append(load_batch(conn, source, batch, mode="replay"))
    return out


def load_pending(conn: psycopg.Connection, *, source_name: str | None = None,
                 raw_root: Path | None = None) -> list[LoadStats]:
    """Load raw batches that have no successful load yet (e.g. collected with --no-load,
    or while the database was down). Already loaded batches are left alone."""
    raw_root = raw_root or get_settings().raw_data_dir
    cfg = load_sources_config()
    done = {r[0] for r in conn.execute(
        "select distinct batch_id::text from ops.load_run where status = 'success'")}
    out = []
    for path in find_batches(raw_root, source_name):
        batch = RawBatch.load(path)
        if batch.batch_id in done:
            continue
        source = get_source(batch.source, cfg)
        out.append(load_batch(conn, source, batch, mode="live"))
    return out
