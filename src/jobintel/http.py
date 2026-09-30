"""Polite HTTP client: timeouts, bounded retries with backoff, per-host rate limiting."""

from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """Raised when a request still fails after all retries."""

    def __init__(self, url: str, message: str, status_code: int | None = None):
        super().__init__(f"{url}: {message}")
        self.url = url
        self.status_code = status_code


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        max_backoff: float = 60.0,
        min_interval: float = 1.0,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ):
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff
        self.min_interval = min_interval
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": user_agent},
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self 

    def __exit__(self, *exc) -> None:
        self.close()

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = time.monotonic()

    def get(self, url: str, **kwargs) -> httpx.Response:
        """GET with retries on timeouts, connection errors, 429 and 5xx.

        4xx responses other than 429 are returned immediately and not retried
        (e.g. a 404 for a board that no longer exists).
        """
        attempts = self.max_retries + 1
        last_error = "unknown error"
        last_status = None
        for attempt in range(1, attempts + 1):
            self._throttle(url)
            try:
                resp = self._client.get(url, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error, last_status = f"{type(exc).__name__}: {exc}", None
            else:
                if resp.status_code not in RETRYABLE_STATUS:
                    return resp
                last_error, last_status = f"HTTP {resp.status_code}", resp.status_code
                retry_after = _retry_after_seconds(resp)
                if retry_after is not None and attempt < attempts:
                    log.warning("%s -> %s; Retry-After %.0fs", url, last_error, retry_after)
                    self._sleep(min(retry_after, self.max_backoff))
                    continue
            if attempt < attempts:
                delay = min(self.backoff_base ** attempt, self.max_backoff)
                log.warning("%s failed (%s); retry %d/%d in %.0fs",
                            url, last_error, attempt, self.max_retries, delay)
                self._sleep(delay)
        raise FetchError(url, f"gave up after {attempts} attempts: {last_error}", last_status)


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
