"""CP2 persistence uses generated test schemas only; no operating accounts."""

import copy
from decimal import Decimal as D

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_paper_economics import frames
from test_paper_engine import START, frame, study
from test_paper_store import pg_store as _pg_store

from trading import paper_economics as eco
from trading.api import create_app
from trading.config import Settings
from trading.execution_profiles import LEGACY_EXECUTION, PUBLIC_EXECUTION
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore

disposable_store = _pg_store


@pytest.mark.parametrize("disposable_store", ["50", "100"], indirect=True)
@pytest.mark.parametrize("profile", [LEGACY_EXECUTION, PUBLIC_EXECUTION])
def test_small_account_cash_fees_inventory_and_pnl_reconcile(disposable_store, profile):
    store, _ = disposable_store
    initial = store.read()
    amount = D(initial["accounts"]["primary"]["funding"])
    store.transact(START, lambda e: e.set_economics("primary", profile, "0", 0))
    store.transact(START, lambda e: e.tick(frames(START), study()))
    a = store.read()["accounts"]["primary"]
    reserve = D(a["pending"]["BTCUSD"]["reserved"])
    assert reserve <= amount / 2 and store.reconcile()["balanced"]
    store.transact(START + 2, lambda e: e.tick(frames(START + 2, 2), {}))
    a = store.read()["accounts"]["primary"]
    assert D(a["cash"]) + D(a["positions"]["BTCUSD"]["cost"]) == amount
    assert store.reconcile()["balanced"]
    s = eco.sample(a, START + 2)
    assert D(s["realized"]) + D(s["unrealized"]) == D(s["net_pnl"])
    store.transact(START + 4, lambda e: e.tick(frames(START + 4, 3, "98"), {}))
    store.transact(START + 6, lambda e: e.tick(frames(START + 6, 4, "98"), {}))
    a = store.read()["accounts"]["primary"]
    assert not a["positions"] and a["closed"] == 1
    assert D(a["realized"]) == D(a["cash"]) - amount
    assert store.reconcile()["balanced"]
    row = store.connection.execute(
        "SELECT sum(amount) AS total FROM paper_journal "
        "WHERE account='primary' AND asset='USD' AND bucket='fees'"
    ).fetchone()
    assert row["total"] == D(a["fees"])
    before = store.read()
    store.initialize(START + 8, starting_cash="50")
    assert store.read() == before  # Constructor parameters cannot reset existing history.


@pytest.mark.parametrize("field", ["funding", "fees"])
def test_reconciliation_detects_unjournaled_funding_or_fee_drift(disposable_store, field):
    store, _ = disposable_store
    store.transact(START, lambda e: e.state["accounts"]["primary"].update({field: "999"}))
    assert not store.reconcile()["balanced"]


def test_profile_settings_and_economics_windows_survive_reopen(disposable_store, monkeypatch):
    store, dsn = disposable_store
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    store.transact(START, lambda e: e.set_economics("primary", PUBLIC_EXECUTION, "1.25", 0))
    for i in range(21):
        store.transact(START + i, lambda e, i=i: e.tick(frames(START + i, i + 1), {}))
    before = store.read()
    events = store.export(0, 1000)
    other = PaperStore(dsn)
    try:
        assert other.read() == before and other.reconcile()["balanced"]
        assert other.export(0, 1000) == events
        assert len(before["economics"]["completed"]) == 2
        assert any(r["kind"] == "economics_window" for r in events["records"])
        assert any(r["kind"] == "benchmark_fill" for r in events["records"])
    finally:
        other.close()
    with pytest.raises(RuntimeError, match="intentional rollback"):

        def fail(e):
            e.set_economics("primary", LEGACY_EXECUTION, "9", 1)
            raise RuntimeError("intentional rollback")

        store.transact(START + 22, fail)
    assert store.read() == before and store.export(0, 1000) == events


def test_cost_control_authorization_error_and_retry(disposable_store, tmp_path, monkeypatch):
    store, _ = disposable_store
    store.transact(START, lambda e: e.tick(frames(START), {}))
    runtime = PaperRuntime(store, None)
    runtime.running = True
    monkeypatch.setattr("trading.paper_runtime.time.time", lambda: START)
    app = create_app(Settings(), tmp_path / "monitor", background=False)
    url = "/api/paper/accounts/primary/economics-settings"
    body = {
        "execution_profile": PUBLIC_EXECUTION,
        "operating_daily_usd": "0",
        "expected_version": 0,
    }
    headers = {"X-Local-Operator": "1", "Origin": "http://testserver"}
    with TestClient(app) as client:
        client.app.state.paper = runtime
        assert client.post(url, json=body).status_code == 403
        assert (
            client.post(
                url, json=body, headers={**headers, "Origin": "https://other.invalid"}
            ).status_code
            == 403
        )
        assert (
            client.post(url, json={**body, "fee_asset": "BNB"}, headers=headers).status_code == 422
        )
        assert (
            client.post(url, json={**body, "operating_daily_usd": 0.1}, headers=headers).status_code
            == 422
        )
        assert (
            client.post(url.replace("primary", "missing"), json=body, headers=headers).status_code
            == 404
        )
        response = client.post(url, json=body, headers=headers)
        assert response.status_code == 200 and response.json()["status"] == "applied"
        assert client.post(url, json=body, headers=headers).json()["status"] == "already_applied"
        assert (
            client.post(
                url, json={**body, "execution_profile": LEGACY_EXECUTION}, headers=headers
            ).status_code
            == 409
        )
        status = client.get("/api/status").json()["paper"]
        assert status["economics"]["accounts"]["primary"]["operating_daily_usd"] == "0"
        assert status["cost_model"].startswith("Published")
        before = copy.deepcopy(store.read())

        def storage_failure(*args):
            raise psycopg.OperationalError("private-connection-detail")

        with monkeypatch.context() as m:
            m.setattr(store, "transact", storage_failure)
            failed = client.post(
                url,
                json={**body, "expected_version": 1, "operating_daily_usd": "2"},
                headers=headers,
            )
            assert failed.status_code == 503 and "private-connection" not in failed.text
        assert store.read() == before
        assert (
            client.post(
                url,
                json={**body, "expected_version": 1, "operating_daily_usd": "2"},
                headers=headers,
            ).status_code
            == 200
        )


def test_historical_fill_fees_are_not_rewritten_when_scenario_changes(disposable_store):
    store, _ = disposable_store
    for i, price in [(0, "100"), (2, "100"), (4, "98"), (6, "98")]:
        store.transact(
            START + i,
            lambda e, i=i, price=price: e.tick(
                frames(START + i, i + 1, price), study() if i == 0 else {}
            ),
        )
    original = store.export(0, 1000)["records"]
    fees = store.read()["accounts"]["primary"]["fees"]
    store.transact(START + 7, lambda e: e.set_economics("primary", PUBLIC_EXECUTION, None, 0))
    after = store.export(0, 1000)["records"]
    assert after[: len(original)] == original
    assert store.read()["accounts"]["primary"]["fees"] == fees and store.reconcile()["balanced"]


def test_partial_exit_releases_only_committed_cash_and_never_double_charges(disposable_store):
    store, _ = disposable_store
    store.transact(START, lambda e: e.tick(frames(START), study()))
    store.transact(
        START + 2, lambda e: e.tick({"BTCUSD": frame(START + 2, sequence=2, quantity="1")}, {})
    )
    original = store.read()["accounts"]["primary"]["cash"]
    store.transact(START + 4, lambda e: e.tick(frames(START + 4, 3, "98"), {}))
    assert store.read()["accounts"]["primary"]["cash"] == original
    store.transact(START + 6, lambda e: e.tick({"BTCUSD": frame(START + 6, "98", 4, "0.5")}, {}))
    a = store.read()["accounts"]["primary"]
    assert D(a["positions"]["BTCUSD"]["quantity"]) == D("0.05")
    assert D(a["cash"]) > D(original) and store.reconcile()["balanced"]
    cash, fees = a["cash"], a["fees"]
    store.transact(START + 8, lambda e: e.tick({"BTCUSD": frame(START + 8, "98", 4, "0.5")}, {}))
    a = store.read()["accounts"]["primary"]
    assert a["cash"] == cash and a["fees"] == fees and store.reconcile()["balanced"]
