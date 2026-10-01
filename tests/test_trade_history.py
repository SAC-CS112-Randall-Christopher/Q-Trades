"""Read-model economics and permanent paging; never use installed financial state."""

import copy
from contextlib import nullcontext
from decimal import Decimal as D
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict
from test_paper_engine import START, buy, frame, study
from test_paper_store import pg_store as _pg_store

from trading.api import create_app
from trading.config import Settings
from trading.paper_engine import initial_state
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore
from trading.trade_history import closed_row, number, open_row, ratio

pg_store = _pg_store


@pytest.mark.parametrize("password", ["synthetic-password", "synthetic ' quote \\ and space"])
def test_api_reader_keeps_authentication_private_and_separate(password, monkeypatch, tmp_path):
    import trading.api as api

    info = SimpleNamespace(
        dsn="host=127.0.0.1 port=55633 dbname=synthetic user=fixture "
        "options='-c search_path=auth_case'",
        password=password,
    )
    # Psycopg deliberately omits passwords from info.dsn. A password-requiring
    # reader exposes the installed failure even on hosted runners without PG.
    readers = []

    class Reader:
        def __init__(self, dsn):
            params = conninfo_to_dict(dsn)
            if params.get("password") != password:
                raise psycopg.OperationalError("Synthetic authentication requires a password")
            assert params["options"] == "-c search_path=auth_case"
            self.connection = self
            self.closed = False
            self.read_only = False
            readers.append(self)

        def transaction(self):
            return nullcontext()

        def execute(self, query):
            assert query == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            self.read_only = True

        def trade_history(self, **kwargs):
            assert self.read_only and kwargs["status"] == "closed"
            return {"records": [], "closed_count": 0}

        def close(self):
            self.closed = True

    monkeypatch.setattr(api, "PaperStore", Reader)
    writer = SimpleNamespace(connection=SimpleNamespace(info=info))
    runtime = SimpleNamespace(running=False, error=None, store=writer)
    with TestClient(create_app(Settings(), tmp_path / "auth-api", background=False)) as client:
        client.app.state.paper = runtime
        response = client.get("/api/paper/trades?status=closed")
    assert response.status_code == 200
    assert response.json() == {"records": [], "closed_count": 0}
    assert password not in response.text
    assert len(readers) == 1 and readers[0].closed and writer.connection.info is info


def closure(pnl="8", proceeds="109"):
    return {
        "id": 100,
        "account": "primary",
        "revision": 3,
        "at": START + 9,
        "body": {
            "symbol": "BTCUSD",
            "opened_at": START + 2,
            "closed_at": START + 9,
            "version": "breakout-v1",
            "reason": "Synthetic partial exit",
            "cost": "101",
            "proceeds": proceeds,
            "fees": "2",
            "pnl": pnl,
        },
    }


def entry():
    return {
        "id": 90,
        "body": {
            "side": "buy",
            "symbol": "BTCUSD",
            "filled_quantity": "10",
            "gross": "100",
            "fee": "1",
            "fee_asset": "USD",
        },
    }


@pytest.mark.parametrize("pnl,proceeds", [("8", "109"), ("-3", "98"), ("0", "101")])
def test_closed_row_uses_full_trade_costs_and_quantity_weighted_exits(pnl, proceeds):
    event = closure(pnl, proceeds)
    saved = copy.deepcopy(event)
    row = closed_row(event, [entry()])
    assert row["pnl"] == pnl and D(row["return_fraction"]) == D(pnl) / 101
    assert D(row["entry_price"]) == 10
    # Total exit fees exclude the entry fee, even across several partial exits.
    assert D(row["close_price"]) == (D(proceeds) + 1) / 10
    assert row["quantity"] == "10" and row["price_reason"] is None
    assert event == saved


@pytest.mark.parametrize("entries", [[], [entry(), entry()]])
def test_missing_or_ambiguous_original_fill_does_not_invent_prices(entries):
    row = closed_row(closure(), entries)
    assert row["pnl"] == "8" and row["return_fraction"] is not None
    assert row["entry_price"] is None and row["close_price"] is None and row["price_reason"]


def test_conflicting_or_incomplete_cost_receipt_keeps_recorded_result_and_unknown_exit():
    event = closure()
    event["body"]["cost"] = "102"
    row = closed_row(event, [entry()])
    assert row["pnl"] == "8" and row["entry_price"] == "10" and row["close_price"] is None
    event["body"].pop("cost")
    assert closed_row(event, [entry()])["return_fraction"] is None
    assert number("NaN") is None and number("Infinity") is None and ratio("1", "0") is None


def opened():
    state = initial_state(START)
    buy(state)
    account = state["accounts"]["primary"]
    return account, account["positions"]["BTCUSD"]


def test_open_estimate_includes_exit_fees_and_partial_results_without_mutation():
    account, position = opened()
    # A remaining holding after a recorded partial exit; no closed result is fabricated.
    cost = D(position["cost"])
    position.update(
        quantity=str(D(position["quantity"]) / 2),
        cost=str(cost / 2),
        exit_proceeds=str(cost / 2 - D("0.50")),
        exit_fees="0.01",
    )
    before = copy.deepcopy(account)
    row = open_row("primary", "BTCUSD", position, account, frame(START + 3, "105"), START + 3)
    assert row["status"] == "open" and row["close_price"] is None
    assert D(row["partial_realized_pnl"]) == D("-0.50")
    assert D(row["pnl"]) == D(row["unrealized_pnl"]) - D("0.50")
    assert D(row["return_fraction"]) == D(row["pnl"]) / D(position["total_cost"])
    assert D(row["mark_price"]) < 105  # Frozen adverse execution price is embedded once.
    assert account == before


@pytest.mark.parametrize("case", ["missing", "stale", "future", "depth", "dust", "profile"])
def test_open_stale_or_unexitable_mark_stays_unavailable(case):
    account, position = opened()
    market = frame(START + 3)
    if case == "missing":
        market = None
    elif case == "stale":
        market["observed"] = START - 100
    elif case == "future":
        market["observed"] = START + 100
    elif case == "depth":
        market = frame(START + 3, quantity="0.00001")
    elif case == "dust":
        market["rules"]["min_qty"] = D(100)
    else:
        account["execution_profile"] = "unsupported"
    before = copy.deepcopy(account)
    row = open_row("primary", "BTCUSD", position, account, market, START + 3)
    assert row["pnl"] is None and row["mark_price"] is None and row["price_reason"]
    assert row["status"] == "open" and D(row["partial_realized_pnl"]) == 0
    assert account == before


def test_permanent_history_exceeds_cache_and_pages_all_accounts_without_rewrites(pg_store):
    store, dsn = pg_store

    # Generated read-model receipts are synthetic, not new market/financial performance.
    def seed(engine):
        for i in range(1027):
            body = closure()["body"] | {"closed_at": START + i + 10}
            engine.emit("trade_closed", "primary" if i % 2 else "breakout-v1", body)

    store.transact(START + 2000, seed)
    original, state = store.export(0, 1000), store.read()
    seen, cursor = [], 0
    while True:
        page = store.trade_history(before=cursor, limit=47, status="closed", now=START + 2001)
        seen.extend(r["event_id"] for r in page["records"])
        if not page["has_more"]:
            break
        assert page["next_before"] > 0 and (not cursor or page["next_before"] < cursor)
        cursor = page["next_before"]
    assert len(seen) == len(set(seen)) == 1027 and seen == sorted(seen, reverse=True)
    selected = store.trade_history(account="breakout-v1", limit=100)
    assert {r["account"] for r in selected["records"]} == {"breakout-v1"}
    assert store.export(0, 1000) == original and store.read() == state
    reader = PaperStore(dsn)
    try:
        with reader.connection.transaction():
            reader.connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            assert (
                reader.trade_history(limit=47, status="closed")["records"]
                == store.trade_history(limit=47, status="closed")["records"]
            )
    finally:
        reader.close()


def test_real_engine_partial_exits_reconcile_one_closed_row_and_survive_reopen(pg_store):
    store, dsn = pg_store

    def tick(now, price, sequence, quantity="100"):
        store.transact(
            now,
            lambda e: e.tick({"BTCUSD": frame(now, price, sequence, quantity)}, study(sequence)),
        )

    tick(START, "100", 1)
    tick(START + 2, "100", 2)
    tick(START + 5, "98", 3)
    tick(START + 7, "98", 4, "0.5")
    positions = store.read()["accounts"]["primary"]["positions"]
    assert positions and store.trade_history(account="primary", status="closed")["records"] == []
    assert store.trade_history(account="primary", status="open")["records"][0]["status"] == "open"
    tick(START + 10, "97.5", 5)
    # The lower book first cancels the old price cap; a subsequent executable
    # observation fills the new exit intent. Cancellations remain in the journal.
    tick(START + 12, "97.5", 6)
    records = store.trade_history(account="primary", status="closed")["records"]
    assert len(records) == 1 and D(records[0]["pnl"]) < 0 and records[0]["close_price"] is not None
    fills = [r["body"] for r in store.export(0, 1000, "primary")["records"] if r["kind"] == "fill"]
    sales = [f for f in fills if f["side"] == "sell"]
    assert len(sales) == 2
    assert D(records[0]["close_price"]) == sum(D(f["gross"]) for f in sales) / sum(
        D(f["filled_quantity"]) for f in sales
    )
    assert store.reconcile()["balanced"]
    store.close()
    reopened = PaperStore(dsn)
    try:
        assert reopened.trade_history(account="primary", status="closed")["records"] == records
    finally:
        reopened.close()


def test_retired_account_trade_is_available_in_all_and_account_filtered_history(pg_store, tmp_path):
    from test_autonomous_lab import admit, make_lab, tick_lab

    from trading import autonomous_finance as finance

    store, _ = pg_store
    lab = make_lab(store, tmp_path)
    try:
        trial = admit(lab, START)
        now = trial["started_at"] + 2
        tick_lab(lab, now, eligible=True)
        tick_lab(lab, now + 2, eligible=True)
        tick_lab(lab, now + 5, price="97")
        tick_lab(lab, now + 7, price="97")
        account = trial["candidate"]
        original = store.trade_history(account=account, status="closed")["records"]
        assert len(original) == 1
        lab.paper.state = store.transact(
            now + 9, lambda e: finance.retire_trial(e, trial["id"], "Disposable archive check")
        )
        tick_lab(lab, now + 11)
        assert account not in store.read()["accounts"] and store.archived_account(account)
        records = store.trade_history(account=account, status="closed")["records"]
        assert len(records) == 1 and records[0]["archived"]
        assert records[0]["pnl"] == original[0]["pnl"]
        assert records[0]["event_id"] in {
            r["event_id"] for r in store.trade_history(status="closed")["records"]
        }
        before, journal = store.read(), store.export(0, 1000)
        with TestClient(create_app(Settings(), tmp_path / "read-api", background=False)) as client:
            client.app.state.paper = lab.paper
            response = client.get(
                "/api/paper/trades", params={"account": account, "status": "closed"}
            )
            assert response.status_code == 200 and response.json()["records"] == records
        assert store.read() == before and store.export(0, 1000) == journal
        assert store.reconcile()["balanced"]
    finally:
        lab.registry.close()


def test_api_pages_filters_unknown_account_and_read_only_financial_preservation(pg_store, tmp_path):
    store, _ = pg_store
    store.transact(START, lambda e: e.tick({"BTCUSD": frame()}, study()))
    store.transact(START + 2, lambda e: e.tick({"BTCUSD": frame(START + 2, sequence=2)}, {}))
    runtime = PaperRuntime(store, None)
    before, events = store.read(), store.export(0, 1000)
    with TestClient(create_app(Settings(), tmp_path / "monitor", background=False)) as client:
        assert client.get("/api/paper/trades").status_code == 409
        client.app.state.paper = runtime
        response = client.get("/api/paper/trades?account=primary&status=open")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert len(response.json()["records"]) == 1
        assert response.json()["records"][0]["pnl"] is None  # Worker is stopped.
        assert client.get("/api/paper/trades?account=missing").status_code == 404
        for query in ("before=-1", "limit=101", "status=winning"):
            assert client.get("/api/paper/trades?" + query).status_code == 422
        assert client.post("/api/paper/trades", json={}).status_code == 405
    assert (
        store.read() == before and store.export(0, 1000) == events and store.reconcile()["balanced"]
    )
