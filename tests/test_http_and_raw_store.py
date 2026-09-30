import gzip

import httpx
import pytest

from jobintel.http import FetchError, HttpClient
from jobintel.raw_store import RawBatch, find_batch

from .conftest import make_batch


def client_with(handler, **kw):
    sleeps = []
    c = HttpClient("test-agent", transport=httpx.MockTransport(handler),
                   sleep=sleeps.append, min_interval=0, **kw)
    return c, sleeps


def test_retries_then_succeeds():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": 1})

    c, sleeps = client_with(handler, max_retries=3)
    assert c.get("https://x.test/a").status_code == 200
    assert len(calls) == 3 and len(sleeps) == 2
    assert calls[0].headers["User-Agent"] == "test-agent"


def test_retries_are_bounded():
    calls = []

    def handler(req):
        calls.append(req)
        raise httpx.ConnectTimeout("timeout", request=req)

    c, _ = client_with(handler, max_retries=2)
    with pytest.raises(FetchError):
        c.get("https://x.test/a")
    assert len(calls) == 3  # 1 attempt + 2 retries


def test_client_errors_are_not_retried():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(404)

    c, _ = client_with(handler)
    assert c.get("https://x.test/a").status_code == 404
    assert len(calls) == 1


def test_retry_after_is_respected_and_capped():
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "9999"})
        return httpx.Response(200)

    c, sleeps = client_with(handler, max_backoff=30)
    c.get("https://x.test/a")
    assert sleeps == [30]


def test_raw_batch_roundtrip_and_status(tmp_path):
    b = make_batch(tmp_path, "greenhouse", {"a": {"jobs": []}}, failures={"b": "HTTP 500"})
    assert b.status == "partial"
    assert b.scope_status() == {"a": "success", "b": "failed"}
    again = RawBatch.load(find_batch(tmp_path, b.batch_id))
    assert again.read(again.items[0]) == b'{"jobs": []}'


def test_raw_batch_all_failed_is_failed(tmp_path):
    b = make_batch(tmp_path, "greenhouse", {}, failures={"a": "timeout"})
    assert b.status == "failed"


def test_raw_batch_detects_tampering(tmp_path):
    b = make_batch(tmp_path, "greenhouse", {"a": {"jobs": []}})
    (b.path / b.items[0].file).write_bytes(gzip.compress(b"changed"))
    with pytest.raises(ValueError, match="checksum"):
        b.read(b.items[0])
