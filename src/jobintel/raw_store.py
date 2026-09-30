"""Immutable raw batches on disk.

Layout: <root>/<source>/<YYYY-MM-DD>/<batch_id>/
    manifest.json      batch metadata and one entry per fetched item
    items/00001.json.gz  (or .html.gz) raw response bodies, byte-for-byte

Parsers only ever read from here, so a batch can be replayed any number of
times without contacting the source.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

MANIFEST = "manifest.json"


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class RawItem:
    index: int
    scope_key: str
    url: str
    fetched_at: str
    status_code: int | None = None
    file: str | None = None
    sha256: str | None = None
    content_type: str | None = None  # "json" | "html"
    error: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None and self.file is not None


@dataclass
class RawBatch:
    batch_id: str
    source: str
    started_at: str
    finished_at: str | None
    status: str
    path: Path
    items: list[RawItem]
    error: str | None = None
    is_synthetic: bool = False

    @classmethod
    def load(cls, path: Path) -> RawBatch:
        data = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
        items = [RawItem(**it) for it in data.pop("items")]
        return cls(path=path, items=items, **data)

    def read(self, item: RawItem) -> bytes:
        if item.file is None:
            raise ValueError(f"item {item.index} has no stored body")
        body = gzip.decompress((self.path / item.file).read_bytes())
        if item.sha256 and hashlib.sha256(body).hexdigest() != item.sha256:
            raise ValueError(f"checksum mismatch for {item.file}")
        return body

    def scope_status(self) -> dict[str, str]:
        """success/failed per scope; a scope fails if any of its items failed."""
        out: dict[str, str] = {}
        for it in self.items:
            if not it.ok:
                out[it.scope_key] = "failed"
            else:
                out.setdefault(it.scope_key, "success")
        return out

    @property
    def started(self) -> datetime:
        return datetime.fromisoformat(self.started_at)


class RawBatchWriter:
    def __init__(self, root: Path, source: str, *, is_synthetic: bool = False,
                 now: datetime | None = None, batch_id: str | None = None):
        self.source = source
        self.batch_id = batch_id or str(uuid.uuid4())
        self.started_at = now or utcnow()
        self.is_synthetic = is_synthetic
        self.path = Path(root) / source / self.started_at.strftime("%Y-%m-%d") / self.batch_id
        (self.path / "items").mkdir(parents=True, exist_ok=False)
        self.items: list[RawItem] = []

    def add(self, *, scope_key: str, url: str, body: bytes, status_code: int,
            content_type: str, meta: dict | None = None) -> RawItem:
        idx = len(self.items) + 1
        rel = f"items/{idx:05d}.{content_type}.gz"
        (self.path / rel).write_bytes(gzip.compress(body))
        item = RawItem(index=idx, scope_key=scope_key, url=url, fetched_at=utcnow().isoformat(),
                       status_code=status_code, file=rel,
                       sha256=hashlib.sha256(body).hexdigest(), content_type=content_type,
                       meta=meta or {})
        self.items.append(item)
        return item

    def add_failure(self, *, scope_key: str, url: str, error: str,
                    status_code: int | None = None, meta: dict | None = None) -> RawItem:
        item = RawItem(index=len(self.items) + 1, scope_key=scope_key, url=url,
                       fetched_at=utcnow().isoformat(), status_code=status_code,
                       error=error, meta=meta or {})
        self.items.append(item)
        return item

    def finish(self, error: str | None = None) -> RawBatch:
        n_ok = sum(it.ok for it in self.items)
        n_fail = len(self.items) - n_ok
        if error is not None or n_ok == 0:
            status = "failed"
            error = error or "no items fetched"
        elif n_fail:
            status = "partial"
        else:
            status = "success"
        manifest = {
            "batch_id": self.batch_id,
            "source": self.source,
            "started_at": self.started_at.isoformat(),
            "finished_at": utcnow().isoformat(),
            "status": status,
            "error": error,
            "is_synthetic": self.is_synthetic,
            "items": [asdict(it) for it in self.items],
        }
        tmp = self.path / (MANIFEST + ".tmp")
        tmp.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        os.replace(tmp, self.path / MANIFEST)
        return RawBatch.load(self.path)


def find_batches(root: Path, source: str | None = None) -> list[Path]:
    """All completed batch directories (those with a manifest), oldest first."""
    pattern = f"{source or '*'}/*/*/{MANIFEST}"
    paths = [p.parent for p in Path(root).glob(pattern)]
    return sorted(paths, key=lambda p: (p.parent.name, RawBatch.load(p).started_at))


def find_batch(root: Path, batch_id: str) -> Path:
    matches = [p.parent for p in Path(root).glob(f"*/*/{batch_id}/{MANIFEST}")]
    if not matches:
        raise FileNotFoundError(f"no raw batch {batch_id} under {root}")
    return matches[0]
