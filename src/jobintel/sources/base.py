"""Source interface: fetch() writes a raw batch; parse() reads one, never the network."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from jobintel.http import HttpClient
from jobintel.models import ParsedPosting, ParseFailure
from jobintel.raw_store import RawBatch, RawBatchWriter


class Source(ABC):
    name: str
    parser_version: str
    #: minimum seconds between requests to the same host
    min_interval: float = 1.0

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def disabled_reason(self) -> str | None:
        """Why this source cannot run (e.g. a missing API key), or None if it can."""
        return None

    @abstractmethod
    def fetch(self, client: HttpClient, writer: RawBatchWriter) -> None:
        """Fetch every scope and store each response with writer.add / add_failure.

        Must not raise for per-scope failures. Record them so that other scopes continue.
        """

    @abstractmethod
    def parse(self, batch: RawBatch) -> Iterator[ParsedPosting | ParseFailure]:
        """Turn stored raw items into records. Pure function of the batch contents."""
