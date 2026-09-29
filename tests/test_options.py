import asyncio
import copy
import json
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from test_paper_store import pg_store as _pg_store

from trading.api import create_app
from trading.config import Settings
from trading.options_data import FreeOptionsData
from trading.options_engine import OptionsEngine, initial_state, reserved
from trading.options_policy import NY, SOURCE, quote_valid
from trading.options_runtime import OptionsRuntime
from trading.options_store import OptionsStore
from trading.paper_store import load_dsn
from trading.venue import FeedError

NOW = datetime(2026, 9, 27, tzinfo=UTC).timestamp()
SYMBOL = "AAPL260619C00110000"
spot_store = _pg_store


def quote(day="2026-06-01", price="0.01", **changes):
    return {
        "symbol": SYMBOL,
        "underlying": "AAPL",
        "expiration_date": "2026-06-19",
        "strike": "110",
        "side": "call",
        "day": day,
        "source": SOURCE,
        "bid": price,
        "ask": price,
        "bid_size": "100",
        "ask_size": "100",
        "volume": "1000",
        "open_interest": "1000",
        "multiplier": "100",
        "receipt_sha256": "synthetic-unit-test-only",
        **changes,
    }


def packet(day="2026-06-01", price="0.01", **changes):
    return {
        "source": SOURCE,
        "day": day,
        "underlying_close": "110",
        "quotes": {SYMBOL: quote(day, price)},
        "receipts": [{"wire": "synthetic isolated test"}],
        "missing_held_quotes": [],
        **changes,
    }


def warmed():
    state = initial_state(NOW)
    state["history"] = [{"day": f"2026-05-{day}", "close": "100"} for day in range(20, 30)]
    return state


def run_session(state, day, price="0.01"):
    engine = OptionsEngine(state, NOW)
    engine.process_session(packet(day, price))
    engine.assert_invariants()
    return engine


def test_full_premium_cash_limits_and_no_same_session_fills():
    state = warmed()
    engine = run_session(state, "2026-06-01")
    a = state["accounts"]["primary"]
    assert not a["positions"] and a["cash"] == "100"
    assert reserved(a) == 2
    assert not any(e["kind"] == "fill" for e in engine.events)
    with pytest.raises(ValueError, match="repeat"):
        run_session(state, "2026-06-01")
    run_session(state, "2026-06-02")
    assert a["cash"] == "98.50" and a["positions"][SYMBOL]["quantity"] == "1"
    assert reserved(a) == D("0.50")
    state = warmed()
    run_session(state, "2026-06-01", "1.00")
    assert not state["accounts"]["primary"]["pending"]
    assert "2.5%" in state["accounts"]["primary"]["last_decision"]


def test_worse_next_session_price_cancels_and_releases_reserve():
    state = warmed()
    run_session(state, "2026-06-01")
    engine = run_session(state, "2026-06-02", "0.02")
    a = state["accounts"]["primary"]
    assert a["cash"] == "100" and not a["positions"] and not a["pending"]
    assert any(e["kind"] == "order_cancelled" for e in engine.events)


def test_sale_proceeds_wait_until_next_session_and_fee_costs_are_not_erased():
    state = warmed()
    run_session(state, "2026-06-01")
    run_session(state, "2026-06-02")
    run_session(state, "2026-06-03", "0.02")
    a = state["accounts"]["primary"]
    assert a["closed"] == 1 and a["fees"] == "1.00"
    assert D(a["cash"]) == 98 and D(a["unsettled"][0]["amount"]) == 2
    assert D(a["equity"]) == 100 and not a["positions"]
    run_session(state, "2026-06-04", "0.02")
    assert D(a["cash"]) == 100 and not a["unsettled"]


@pytest.mark.parametrize(
    "patch",
    [
        {"symbol": "AAPL1260619C00110000"},
        {"multiplier": "10"},
        {"strike": "111"},
        {"day": "2026-06-02"},
        {"bid": "NaN"},
        {"ask": True},
        {"source": "indicative"},
        {"bid": "2", "ask": "1"},
        {"side": "put"},
    ],
)
def test_unverified_contract_or_quote_never_qualifies(patch):
    assert not quote_valid(quote(**patch), "2026-06-01")


def test_expiry_and_missing_exit_data_cannot_invent_payout_or_trigger_replenishment():
    state = warmed()
    run_session(state, "2026-06-01")
    run_session(state, "2026-06-02")
    before = state["accounts"]["primary"]["cash"]
    run_session(state, "2026-06-22", "0.02")
    a = state["accounts"]["primary"]
    assert SYMBOL in a["positions"] and a["positions"][SYMBOL]["exit_blocked"]
    assert not a["valuation_fresh"] and a["risk_pause"]
    assert a["replenishments"] == 0 and a["cash"] == before
    review = OptionsEngine(state, NOW + 14400)
    review.review()
    assert a["risk_pause"]  # A review cannot waive unresolved expiry.


def test_failure_review_precedes_strict_below_five_replenishment():
    state = initial_state(NOW)
    a = state["accounts"]["primary"]
    a.update(cash="5", equity="5")
    engine = OptionsEngine(state, NOW)
    engine.attempts("primary", a)
    assert a["replenishments"] == 0
    a.update(cash="4", equity="4")
    engine.attempts("primary", a)
    kinds = [e["kind"] for e in engine.events]
    assert kinds.index("failure_review") < kinds.index("replenishment")
    assert a["cash"] == "100" and a["funding"] == "196" and a["attempt_failures"] == 1
    assert a["version"] == "options-selective-v1" and a["cooldown_sessions"] == 1


def test_review_requires_sufficient_disjoint_outcomes_and_freezes_prior_evidence():
    state = warmed()
    run_session(state, "2026-06-01")
    engine = OptionsEngine(state, NOW + 14400)
    engine.review()
    saved = copy.deepcopy(state["reviews"][-1])
    assert state["promotions"] == 0 and "Insufficient" in saved["reason"]
    run_session(state, "2026-06-02")
    assert state["reviews"][-1] == saved


def test_promotion_needs_two_complete_windows_and_only_changes_future_policy():
    state = initial_state(NOW)
    state["sessions"] = 40
    state["accounts"]["primary"]["max_drawdown"] = "0.10"
    for version, pnl in [("options-momentum-v1", "1"), ("options-selective-v1", "2")]:
        state["accounts"][version]["max_drawdown"] = "0.05"
        state["accounts"][version]["trades"] = [
            {"opened_sequence": seq - 1, "sequence": seq, "pnl": pnl, "return": pnl}
            for seq in range(2, 41, 2)
        ]
    incomplete = copy.deepcopy(state)
    # A trade crossing the evaluation boundary cannot count in either window.
    incomplete["accounts"]["options-selective-v1"]["trades"][10]["opened_sequence"] = 20
    OptionsEngine(incomplete, NOW + 28800).review()
    assert incomplete["promotions"] == 0
    before = copy.deepcopy(state["accounts"])
    engine = OptionsEngine(state, NOW + 28800)
    engine.review()
    assert state["promotions"] == 1
    assert state["accounts"]["primary"]["version"] == "options-selective-v1"
    assert state["accounts"]["primary"]["cash"] == before["primary"]["cash"]
    assert state["accounts"]["options-selective-v1"] == before["options-selective-v1"]
    saved = copy.deepcopy(state["reviews"][-1])
    OptionsEngine(state, NOW + 43200).review()
    assert state["promotions"] == 1 and state["reviews"][-2] == saved


def test_risk_peak_tracks_gains_and_review_cooldown_skips_next_session():
    state = warmed()
    a = state["accounts"]["primary"]
    engine = OptionsEngine(state, NOW)
    a["cash"] = "200"
    engine.mark_account(a, {}, "2026-05-29")
    assert a["risk_peak"] == "200"
    a["cash"] = "120"
    engine.mark_account(a, {}, "2026-05-29")
    assert a["risk_pause"]
    engine.review()
    assert a["cooldown_sessions"] == 1 and not a["risk_pause"]
    run_session(state, "2026-06-01")
    assert not a["pending"] and a["cooldown_sessions"] == 0


def wire(day="2026-06-01"):
    t = datetime.fromisoformat(day + "T16:00:00").replace(tzinfo=NY).timestamp()
    expiry = datetime(2026, 6, 19, 16, tzinfo=NY).timestamp()
    return {
        "s": "ok",
        "optionSymbol": [SYMBOL],
        "underlying": ["AAPL"],
        "side": ["call"],
        "strike": [110],
        "bid": [0.01],
        "ask": [0.01],
        "bidSize": [100],
        "askSize": [100],
        "volume": [1000],
        "openInterest": [1000],
        "underlyingPrice": [110],
        "updated": [t],
        "expiration": [expiry],
        "iv": [None],
        "delta": [None],
    }


def test_free_http_203_preserves_decimals_provenance_and_rejects_other_routes():
    calls = []

    def handler(request):
        calls.append(request)
        assert "authorization" not in request.headers
        return httpx.Response(203, content=json.dumps(wire()).encode())

    async def scenario():
        source = FreeOptionsData(lambda: None, transport=httpx.MockTransport(handler))
        source.minimum_interval = 0
        try:
            for path in ["/accounts", "/v1/options/chain/SPY/", "https://other.example/"]:
                with pytest.raises(ValueError):
                    await source.get(path, {"date": "2026-06-01"})
            with pytest.raises(ValueError):
                await source.get("/v1/options/chain/AAPL/", {"token": "not-allowed"})
            response = await source.get("/v1/options/chain/AAPL/", {"date": "2026-06-01"})
            quotes = source.quotes(response, "2026-06-01")
            assert quotes[SYMBOL]["ask"] == "0.01" and quotes[SYMBOL]["receipt_sha256"]
            assert len(calls) == 1 and calls[0].method == "GET"
            with pytest.raises(ValueError, match="different historical date"):
                source.quotes(response, "2026-06-02")
            response["raw"]["ask"] = []
            with pytest.raises(ValueError, match="Mismatched"):
                source.quotes(response, "2026-06-01")
        finally:
            await source.close()

    asyncio.run(scenario())


@pytest.fixture
def options_store():
    settings = Path("data/paper-database.json")
    if not settings.is_file():
        pytest.skip("Dedicated local PostgreSQL unavailable")
    dsn = load_dsn(settings)
    schema = "test_options_" + uuid.uuid4().hex
    store = OptionsStore(dsn, schema=schema)
    store.initialize(NOW)
    try:
        yield store, dsn, schema
    finally:
        store.close()
        assert schema.startswith("test_options_") and len(schema) == 45
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_postgres_cash_inventory_restart_idempotency_and_spot_isolation(options_store, spot_store):
    store, dsn, schema = options_store
    spot, _ = spot_store
    try:
        before = spot.read()["accounts"]["primary"]
        store.transact(NOW, lambda e: e.state.update(history=warmed()["history"]))
        for day, price in [
            ("2026-06-01", "0.01"),
            ("2026-06-02", "0.01"),
            ("2026-06-03", "0.02"),
            ("2026-06-04", "0.02"),
        ]:
            store.transact(NOW, lambda e, d=day, p=price: e.process_session(packet(d, p)))
            assert store.reconcile()["balanced"]
        saved = store.read()
        with pytest.raises(ValueError, match="repeat"):
            store.transact(NOW, lambda e: e.process_session(packet("2026-06-04")))
        assert store.read() == saved
        assert spot.read()["accounts"]["primary"]["funding"] == before["funding"]
        assert spot.reconcile()["balanced"]
        with pytest.raises(psycopg.Error, match="append-only"):
            store.connection.execute("DELETE FROM paper_events")
        store.close()
        restarted = OptionsStore(dsn, schema=schema)
        try:
            restarted.initialize(NOW + 10)
            assert restarted.read() == saved
            assert restarted.reconcile()["balanced"]
        finally:
            restarted.close()
    finally:
        spot.close()


def test_request_budget_persists_and_failed_work_rolls_back(options_store):
    store, _, _ = options_store
    runtime = OptionsRuntime(store)
    runtime.reserve_request()
    assert store.read()["request_budget"]["used"] == 1

    def exhaust(e):
        e.state["request_budget"]["used"] = 60

    store.transact(NOW, exhaust)
    runtime = OptionsRuntime(store)
    with pytest.raises(FeedError, match="budget"):
        runtime.reserve_request()
    before = store.read()

    def broken(e):
        e.state["accounts"]["primary"]["cash"] = "-1"

    with pytest.raises(ValueError, match="invariant"):
        store.transact(NOW, broken)
    assert store.read() == before and store.reconcile()["balanced"]


def test_due_review_runs_even_when_historical_source_is_unavailable(options_store):
    store, _, _ = options_store
    store.transact(time.time(), lambda e: e.state.update(next_review=time.time() - 1))
    runtime = OptionsRuntime(store)

    def offline(request):
        raise httpx.ConnectError("isolated offline test")

    async def scenario():
        source = FreeOptionsData(runtime.reserve_request, transport=httpx.MockTransport(offline))
        try:
            with pytest.raises(FeedError, match="unavailable"):
                await runtime.step(source)
        finally:
            await source.close()

    asyncio.run(scenario())
    assert store.read()["review_count"] == 1 and store.read()["sessions"] == 0
    assert store.reconcile()["balanced"]


def test_options_controls_are_local_and_do_not_change_spot_or_collector(options_store, tmp_path):
    store, _, _ = options_store
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.options = OptionsRuntime(store)
        assert client.get("/api/status").json()["options"]["accounts"]["primary"]["cash"] == "100"
        assert client.post("/api/options/entries", json={"action": "pause"}).status_code == 403
        assert (
            client.post(
                "/api/options/entries",
                json={"action": "pause"},
                headers={"X-Local-Operator": "1", "Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )
        for action in ("pause", "resume"):
            result = client.post(
                "/api/options/entries",
                json={"action": action},
                headers={"X-Local-Operator": "1", "Origin": "http://testserver"},
            )
            assert result.json() == {"paused": action == "pause"}
            status = client.get("/api/status").json()
            assert status["paper"] == {"enabled": False} and not status["paused"]
        assert client.get("/api/options/journal?limit=1001").status_code == 422
        assert client.get("/api/options/journal?limit=10").status_code == 200


def test_postgres_failure_review_replenishment_balances_and_preserves_funding(options_store):
    store, _, _ = options_store

    def loss(e):
        a = e.state["accounts"]["primary"]
        a.update(cash="4", equity="4")
        e.emit(
            "test_loss",
            "primary",
            {},
            [e.line("USD", "cash", D(-96)), e.line("USD", "test_loss", D(96))],
        )
        e.attempts("primary", a)

    store.transact(NOW, loss)
    assert store.reconcile()["balanced"]
    assert store.read()["accounts"]["primary"]["funding"] == "196"
