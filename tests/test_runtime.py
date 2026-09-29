import asyncio
import json
import time

import httpx

from trading.config import Settings
from trading.replay import replay_capture
from trading.runtime import Monitor
from trading.storage import MonitorStore
from trading.venue import PublicVenue, retry_delay


def test_public_adapter_compact_query_and_no_auth(book, metadata, tmp_path):
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "api.binance.us"
        assert "authorization" not in request.headers
        assert "x-mbx-apikey" not in request.headers
        if request.url.path.endswith("exchangeInfo"):
            assert request.url.params["symbols"] == '["BTCUSD"]'
            return httpx.Response(200, json=metadata)
        return httpx.Response(200, json=book)

    async def run():
        venue = PublicVenue(transport=httpx.MockTransport(respond))
        store = MonitorStore(tmp_path / "db")
        monitor = Monitor(Settings(monitored_symbols=["BTCUSD"]), store, venue)
        await monitor.poll_once()
        snapshot = monitor.snapshot()
        assert snapshot["runtime_state"] == "monitoring"
        assert snapshot["markets"][0]["metrics"]["bid"] == "99.90"
        assert not snapshot["markets"][0]["entry_allowed"]
        assert snapshot["execution"]["live_available"] is False
        replay = replay_capture(json.loads(json.dumps(store.export())))
        assert replay["latest_metrics"]["BTCUSD"] == snapshot["markets"][0]["metrics"]
        assert len(requests) == 2
        monitor.last_received["BTCUSD"] -= 46
        assert monitor.snapshot()["markets"][0]["state"] == "stale"
        await venue.close()
        store.close()

    asyncio.run(run())


def test_pause_and_observation_survive_reopen_but_are_not_fresh(book, metadata, tmp_path):
    async def run():
        venue = PublicVenue(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, json=metadata if r.url.path.endswith("exchangeInfo") else book
                )
            )
        )
        config = Settings(monitored_symbols=["BTCUSD"])
        path = tmp_path / "db"
        store = MonitorStore(path)
        monitor = Monitor(config, store, venue)
        await monitor.poll_once()
        monitor.set_paused(True)
        before = store.observation_stats()["total"]
        store.close()
        reopened = MonitorStore(path)
        second = Monitor(config, reopened, venue)
        await second.poll_once()
        assert second.snapshot()["runtime_state"] == "paused"
        assert second.snapshot()["markets"][0]["state"] == "stale"
        assert second.snapshot()["markets"][0]["metrics"]["bid"] == "99.90"
        assert second.snapshot()["markets"][0]["instrument"]["quote"] == "USD"
        assert reopened.observation_stats()["total"] == before
        second.set_paused(False)
        await second.poll_once()
        assert second.snapshot()["markets"][0]["state"] == "observed"
        reopened.close()
        await venue.close()

    asyncio.run(run())


def test_rate_limit_blocks_all_symbols_and_persists_restart_deadline(tmp_path, metadata):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "3600"})

    async def run():
        path = tmp_path / "db"
        store = MonitorStore(path)
        venue = PublicVenue(transport=httpx.MockTransport(respond))
        config = Settings(monitored_symbols=["BTCUSD", "ETHUSD"])
        monitor = Monitor(config, store, venue)
        await monitor.poll_once()
        await monitor.poll_once()
        assert len(requests) == 1
        assert monitor.snapshot()["retry_in_seconds"] > 3500
        store.close()
        reopened = MonitorStore(path)
        second = Monitor(config, reopened, venue)
        await second.poll_once()
        assert len(requests) == 1
        reopened.close()
        await venue.close()

    asyncio.run(run())


def test_sequence_regression_is_captured_but_not_displayed_as_fresh(book, metadata, tmp_path):
    async def run():
        venue = PublicVenue(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, json=metadata if r.url.path.endswith("exchangeInfo") else book
                )
            )
        )
        store = MonitorStore(tmp_path / "db")
        monitor = Monitor(Settings(monitored_symbols=["BTCUSD"]), store, venue)
        await monitor.poll_once()
        book["lastUpdateId"] = 1
        await monitor.poll_once()
        assert monitor.snapshot()["markets"][0]["state"] == "stale"
        assert "backward" in monitor.errors["BTCUSD"]
        assert store.observation_stats()["retained"] == 3
        replay = replay_capture(store.export())
        assert len(replay["rejected"]) == 1
        assert replay["valid_depth_observations"] == 1
        book["lastUpdateId"] = 18
        monitor.cooldown = time.monotonic() - 1
        await monitor.poll_once()
        assert monitor.snapshot()["markets"][0]["state"] == "observed"
        store.close()
        await venue.close()

    asyncio.run(run())


def test_empty_watchlist_makes_no_network_calls(tmp_path):
    def fail(request):
        raise AssertionError("No request allowed")

    async def run():
        store = MonitorStore(tmp_path / "db")
        venue = PublicVenue(transport=httpx.MockTransport(fail))
        monitor = Monitor(Settings(), store, venue)
        await monitor.poll_once()
        assert monitor.snapshot()["runtime_state"] == "idle"
        store.close()
        await venue.close()

    asyncio.run(run())


def test_capture_retention_is_explicit_and_export_replays(tmp_path, book):
    store = MonitorStore(tmp_path / "db", capacity=10)
    for i in range(12):
        book["lastUpdateId"] = i
        store.record("depth", "BTCUSD", f"2026-09-27T01:00:{i:02d}+00:00", book, "config")
    exported = store.export()
    assert exported["retention"]["total"] == 12
    assert exported["retention"]["retained"] == 10
    assert exported["retention"]["evicted"] == 2
    assert replay_capture(exported)["valid_depth_observations"] == 10
    store.close()


def test_nonfinite_retry_after_falls_back_to_safe_delay():
    assert retry_delay("NaN", 60) == 60
    assert retry_delay("Infinity", 60) == 60
    assert retry_delay("600", 60) == 600


def test_capture_enforces_byte_budget_as_well_as_count(tmp_path, book):
    store = MonitorStore(tmp_path / "db", capacity=100, byte_budget=400)
    for _ in range(10):
        store.record("depth", "BTCUSD", "2026-09-27T00:00:00+00:00", book, "hash")
    assert store.observation_stats()["evicted"] > 0
    size = store.db.execute("SELECT SUM(LENGTH(payload)) FROM observations").fetchone()[0]
    assert size <= 400
    store.close()


def test_transient_failure_preserves_evidence_then_recovers(book, metadata, tmp_path):
    broken = False

    def respond(request):
        if request.url.path.endswith("exchangeInfo"):
            return httpx.Response(200, json=metadata)
        return httpx.Response(503) if broken else httpx.Response(200, json=book)

    async def run():
        nonlocal broken
        store = MonitorStore(tmp_path / "db")
        venue = PublicVenue(transport=httpx.MockTransport(respond))
        monitor = Monitor(Settings(monitored_symbols=["BTCUSD"]), store, venue)
        await monitor.poll_once()
        broken = True
        await monitor.poll_once()
        status = monitor.snapshot()
        assert status["runtime_state"] == "degraded"
        assert status["markets"][0]["book"] == book
        assert status["markets"][0]["state"] == "stale"
        broken = False
        monitor.cooldown = 0
        await monitor.poll_once()
        assert monitor.snapshot()["runtime_state"] == "monitoring"
        monitor.metadata_received -= 601
        assert monitor.snapshot()["markets"][0]["state"] == "stale"
        store.close()
        await venue.close()

    asyncio.run(run())


def test_unexpected_collector_failure_is_visible_not_healthy(tmp_path):
    async def run():
        def fail(request):
            raise RuntimeError("Injected unexpected failure")

        store = MonitorStore(tmp_path / "db")
        venue = PublicVenue(transport=httpx.MockTransport(fail))
        monitor = Monitor(Settings(monitored_symbols=["BTCUSD"]), store, venue)
        await monitor.run()
        assert "Collector stopped unexpectedly" in monitor.snapshot()["storage_error"]
        assert monitor.snapshot()["runtime_state"] == "stopped"
        assert monitor.snapshot()["markets"][0]["state"] != "observed"
        store.close()
        await venue.close()

    asyncio.run(run())


def test_private_paths_and_redirects_are_unavailable():
    async def run():
        import pytest

        from trading.venue import FeedError

        venue = PublicVenue(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(302, headers={"Location": "https://untrusted.example"})
            )
        )
        with pytest.raises(ValueError, match="Only public"):
            await venue._get("/api/v3/account", {})
        with pytest.raises(FeedError, match="HTTP 302"):
            await venue.depth("BTCUSD", 20)
        await venue.close()

    asyncio.run(run())
