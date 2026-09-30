"""Fresh-checkout demo: saved real responses → raw store → database, without network."""

from __future__ import annotations

import httpx
import pytest

from jobintel.demo import NotEmpty, load_demo

from .conftest import count, make_batch, synthetic_greenhouse_job


@pytest.mark.db
def test_demo_loads_every_source_without_network(conn, tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("the demo must not touch the network")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    stats = load_demo(conn, tmp_path / "demo_raw")
    assert [s.status for s in stats] == ["success"] * 3
    by_source = dict(conn.execute(
        "select source_id, count(*) from core.posting group by 1").fetchall())
    assert set(by_source) == {"greenhouse", "lever", "reed"}
    assert count(conn, "core.version_classification") == count(conn, "core.posting_version")


@pytest.mark.db
def test_demo_refuses_a_database_with_collected_data(conn, tmp_path):
    from jobintel.load import load_batch
    from jobintel.sources.greenhouse import GreenhouseSource
    load_batch(conn, GreenhouseSource({}),
               make_batch(tmp_path / "raw", "greenhouse", {"s": {"jobs": [synthetic_greenhouse_job()]}},
                          is_synthetic=True))
    with pytest.raises(NotEmpty):
        load_demo(conn, tmp_path / "demo_raw")
