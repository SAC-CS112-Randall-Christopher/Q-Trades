import copy
from collections import deque
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from trading.api import create_app
from trading.config import Settings
from trading.live_quotes import quote_snapshot
from trading.market import parse_book
from trading.stream_feed import StreamFeed
from trading.tiered_runtime import TieredPaperRuntime


@pytest.fixture
def feed(monkeypatch, book):
    monkeypatch.setattr("trading.live_quotes.time.time", lambda: 10000.0)
    monkeypatch.setattr("trading.live_quotes.time.monotonic", lambda: 200.0)
    stream = StreamFeed(None)
    stream.plan = {"BTCUSD": 100}
    stream.clock.checked_mono = 199
    stream.clock.wall_minus_mono = 9800
    stream.clock.offset_ms = 0
    stream.clock.uncertainty_ms = 25
    stream.books["BTCUSD"] = {
        "book": parse_book(book),
        "raw": book,
        "observed": 9999.9,
        "received_mono": 199.9,
        "exchange_event_ms": 9999850,
        "event_age_ms": 50,
        "clock_uncertainty_ms": 25,
        "source": "binance.us-depth-websocket",
    }
    stream.stats["BTCUSD"] = {"intervals_ms": deque([110, 200, 180], maxlen=1000)}
    return stream


def test_quote_poll_is_read_only_and_preserves_decimal_prices(feed):
    runtime = object.__new__(TieredPaperRuntime)
    runtime.stream = feed
    runtime.running = True
    runtime.error = None
    runtime._fallback = {}
    runtime._previous_books = {"BTCUSD": [16, "retained"]}
    runtime.feed_errors = {"BTCUSD": "retained diagnostic"}
    before = copy.deepcopy((feed.books, feed.stats, runtime._previous_books, runtime.feed_errors))
    # No store/venue/financial state is present: this route cannot need any of them.
    for _ in range(3):
        result = runtime.quotes()
        row = result["markets"][0]
        assert row["state"] == "fresh"
        assert row["bid"] == "99.90" and row["ask"] == "100.10"
        assert row["valid_for_ms"] == pytest.approx(825)
        assert row["received_age_ms"] == 100
        assert row["exchange_event_ms"] == 9999850
        assert row["interval_p50_ms"] == 180
    assert before == (feed.books, feed.stats, runtime._previous_books, runtime.feed_errors)
    assert not feed.records and not feed.changed.is_set()


@pytest.mark.parametrize("failure", ["age", "clock", "sequence", "stopped", "worker_error"])
def test_invalid_or_expired_quotes_never_claim_freshness(feed, failure):
    previous = {}
    if failure == "age":
        feed.books["BTCUSD"]["received_mono"] = 198
    if failure == "clock":
        feed.clock.wall_minus_mono -= 1
    if failure == "sequence":
        previous = {"BTCUSD": [18, "newer"]}
    row = quote_snapshot(
        feed,
        {},
        previous,
        failure != "stopped",
        "Worker failed" if failure == "worker_error" else None,
    )["markets"][0]
    assert row["state"] == "stale"
    assert row["valid_for_ms"] == 0
    assert row["reason"]
    assert row["bid"] == "99.90"  # Retained evidence, explicitly stale.


def test_fallback_never_inherits_websocket_event_timestamp_or_freshness(feed):
    polled = {
        "book": feed.books["BTCUSD"]["book"],
        "observed": 9999.95,
        "received_mono": 199.95,
        "exchange_event_ms": None,
        "source": "binance.us-rest-fallback",
    }
    # A fresh stream wins; fallback is selected only when stream freshness fails.
    assert quote_snapshot(feed, {"BTCUSD": polled}, {}, True, None)["markets"][0][
        "source"
    ] == "binance.us-depth-websocket"
    feed.books["BTCUSD"]["received_mono"] = 190
    row = quote_snapshot(feed, {"BTCUSD": polled}, {}, True, None)["markets"][0]
    assert row["source"] == "binance.us-rest-fallback" and row["state"] == "fresh"
    assert row["exchange_event_ms"] is None
    assert row["valid_for_ms"] == pytest.approx(950)
    polled["received_mono"] = 198
    assert quote_snapshot(feed, {"BTCUSD": polled}, {}, True, None)["markets"][0][
        "state"
    ] == "stale"


def test_observation_tier_expiry_and_clock_sample_expiry(feed):
    feed.plan["BTCUSD"] = 1000
    feed.books["BTCUSD"]["received_mono"] = 198
    row = quote_snapshot(feed, {}, {}, True, None)["markets"][0]
    assert row["state"] == "fresh"
    assert row["valid_for_ms"] == 425
    feed.clock.checked_mono = 20.05
    row = quote_snapshot(feed, {}, {}, True, None)["markets"][0]
    assert row["valid_for_ms"] == pytest.approx(50)


def test_missing_markets_are_explicit_and_output_bound_is_disclosed(feed):
    feed.plan.update({f"MARKET{n}USD": 1000 for n in range(9)})
    result = quote_snapshot(feed, {}, {}, True, None)
    assert len(result["markets"]) == 8 and result["omitted_markets"] == 2
    assert result["markets"][1]["state"] == "unavailable"
    assert result["markets"][1]["bid"] is None


def test_quotes_endpoint_is_no_store_get_only_and_does_not_call_full_status(tmp_path):
    app = create_app(Settings(), tmp_path / "monitor.db", background=False)
    with TestClient(app) as client:
        response = client.get("/api/paper/quotes")
        assert response.json() == {"enabled": False, "markets": []}
        assert response.headers["Cache-Control"] == "no-store"
        snapshot = {"enabled": True, "markets": [{"symbol": "BTCUSD", "bid": "99.90"}]}
        # Deliberately no snapshot/store/engine methods; this API reads only quotes.
        app.state.paper = SimpleNamespace(quotes=lambda: snapshot)
        assert client.get("/api/paper/quotes").json() == snapshot
        assert client.post("/api/paper/quotes").status_code == 405
        denied = client.get("/api/paper/quotes", headers={"Host": "untrusted.example"})
        assert denied.status_code == 400
