"""CP1 transactions on disposable PostgreSQL, never the operating paper accounts."""

import copy
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from test_paper_engine import START, frame, study
from test_paper_risk import asset_frame
from test_paper_store import pg_store as _pg_store

from trading.api import create_app
from trading.config import Settings
from trading.paper_engine import HARD_STOP_POLICY, policy
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore

disposable_store = _pg_store


def cash_change(engine, delta):
    """Balanced synthetic loss/recovery, not a deposit or performance result."""
    a = engine.state["accounts"]["primary"]
    a["cash"] = str(D(a["cash"]) + D(delta))
    engine.emit(
        "synthetic_test_market_change",
        "primary",
        {},
        [
            engine.line("USD", "cash", D(delta)),
            engine.line("USD", "test_market_change", -D(delta)),
        ],
    )
    engine.tick({}, {})


def test_pending_cancellation_rollback_restart_and_replay_reconcile(disposable_store):
    store, dsn = disposable_store
    store.transact(START, lambda e: e.tick({"BTCUSD": frame()}, study()))
    store.transact(START + 2, lambda e: e.tick({"BTCUSD": frame(START + 2, sequence=2)}, study()))
    both = {s: asset_frame(s, START + 3, 3) for s in ("BTCUSD", "ETHUSD")}
    studies = {"ETHUSD": study()["BTCUSD"]}
    store.transact(START + 3, lambda e: e.tick(both, studies))
    before = store.read()
    count = store.connection.execute("SELECT count(*) AS n FROM paper_events").fetchone()["n"]
    eth = {"ETHUSD": asset_frame("ETHUSD", START + 5, 5)}

    def crash(engine):
        engine.tick(eth, studies)
        raise RuntimeError("synthetic interruption")

    with pytest.raises(RuntimeError, match="synthetic interruption"):
        store.transact(START + 5, crash)
    assert store.read() == before and store.reconcile()["balanced"]
    assert (
        store.connection.execute("SELECT count(*) AS n FROM paper_events").fetchone()["n"] == count
    )
    store.transact(START + 5, lambda e: e.tick(eth, studies))
    assert store.reconcile()["balanced"]
    store.close()
    reopened = PaperStore(dsn, owner=True)
    try:
        reopened.initialize(START + 6)
        both = {s: asset_frame(s, START + 6, 6) for s in ("BTCUSD", "ETHUSD")}
        reopened.transact(START + 6, lambda e: e.tick(both, studies))
        a = reopened.read()["accounts"]["primary"]
        assert set(a["positions"]) == {"BTCUSD"} and not a["pending"]
        assert a["cash"] == before["accounts"]["primary"]["cash"]
        assert reopened.reconcile()["balanced"]
        rows = reopened.connection.execute(
            "SELECT count(*) AS n FROM paper_events "
            "WHERE kind='order_cancelled' AND account='primary'"
        ).fetchone()
        assert rows["n"] == 1
    finally:
        reopened.close()


def test_recovery_survives_restart_and_duplicate_command_without_new_money(disposable_store):
    store, dsn = disposable_store
    store.transact(START + 1, lambda e: cash_change(e, "-36"))
    assert store.read()["accounts"]["primary"]["drawdown_pause"]
    now = (int(START // 86400) + 1) * 86400
    store.transact(now, lambda e: cash_change(e, "2"))
    before = store.read()

    def crash(engine):
        engine.recover_hard_stop("primary", 1)
        raise RuntimeError("abort recovery")

    with pytest.raises(RuntimeError):
        store.transact(now, crash)
    assert store.read() == before and store.reconcile()["balanced"]
    store.transact(now, lambda e: e.recover_hard_stop("primary", 1))
    store.close()
    reopened = PaperStore(dsn, owner=True)
    try:
        reopened.initialize(now + 1)
        before = reopened.read()["accounts"]
        reopened.transact(now + 1, lambda e: e.recover_hard_stop("primary", 1))
        assert reopened.read()["accounts"] == before
        a = before["primary"]
        assert a["cash"] == "66" and a["funding"] == "100" and a["risk_peak"] == "100"
        assert reopened.reconcile()["balanced"]
        rows = reopened.connection.execute(
            "SELECT count(*) AS n FROM paper_events WHERE kind='risk_recovered'"
        ).fetchone()
        assert rows["n"] == 1
    finally:
        reopened.close()


def test_api_authorization_durable_policy_opt_in_and_exact_stop_recovery(
    disposable_store, tmp_path, monkeypatch
):
    store, _ = disposable_store
    now = [START]
    monkeypatch.setattr("trading.paper_runtime.time.time", lambda: now[0])
    # A disposable pre-CP1 account; never edit a real policy in this test.
    store.transact(START, lambda e: e.state["accounts"]["primary"].pop("risk_policy"))
    runtime = PaperRuntime(store, None)
    runtime.running = True
    app = create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    headers = {"X-Local-Operator": "1", "Origin": "http://testserver"}
    url = "/api/paper/accounts/primary/risk-control"
    with TestClient(app) as client:
        app.state.paper = runtime
        before = copy.deepcopy(store.read())
        assert client.post(url, json={"action": "adopt_hard_stop"}).status_code == 403
        assert (
            client.post(
                url,
                json={"action": "adopt_hard_stop"},
                headers={**headers, "Origin": "https://testserver"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                url, json={"action": "adopt_hard_stop", "funding": 1000}, headers=headers
            ).status_code
            == 422
        )
        assert store.read() == before
        assert (
            client.post(
                "/api/paper/accounts/missing/risk-control",
                json={"action": "adopt_hard_stop"},
                headers=headers,
            ).status_code
            == 404
        )
        assert client.get("/api/status").json()["paper"]["accounts"]["primary"]["risk"]["legacy"]
        for _ in range(2):
            assert (
                client.post(url, json={"action": "adopt_hard_stop"}, headers=headers).status_code
                == 200
            )
        a = store.read()["accounts"]["primary"]
        assert policy(a) == HARD_STOP_POLICY and a["funding"] == "100"
        assert (
            store.connection.execute(
                "SELECT count(*) AS n FROM paper_events WHERE kind='risk_policy_changed'"
            ).fetchone()["n"]
            == 1
        )
        now[0] += 1
        runtime.state = store.transact(now[0], lambda e: cash_change(e, "-36"))
        risk = client.get("/api/status").json()["paper"]["accounts"]["primary"]["risk"]
        assert risk["blocked"] and not risk["recoverable"]
        assert (
            client.post(
                url, json={"action": "resume_hard_stop", "stop_id": 1}, headers=headers
            ).status_code
            == 409
        )
        now[0] = (int(START // 86400) + 1) * 86400
        runtime.state = store.transact(now[0], lambda e: cash_change(e, "2"))
        for _ in range(2):
            response = client.post(
                url, json={"action": "resume_hard_stop", "stop_id": 1}, headers=headers
            )
            assert response.status_code == 200, response.text
        snapshot = client.get("/api/status").json()["paper"]["accounts"]["primary"]
        assert not snapshot["drawdown_pause"] and snapshot["risk"]["last_recovery"]
        assert store.reconcile()["balanced"]
        runtime.running = False
        assert (
            client.post(
                url, json={"action": "resume_hard_stop", "stop_id": 1}, headers=headers
            ).status_code
            == 409
        )


def test_fresh_database_uses_hard_stops_without_creating_options(
    disposable_store, tmp_path, monkeypatch
):
    store, dsn = disposable_store
    # Inject only the connection selector, leaving the application's real startup path in place.
    store.close()
    monkeypatch.setattr("trading.api.load_dsn", lambda _: dsn)
    # Default test DSN schema has no options schema; this fresh cluster has historical
    # shared test setup so record whether options existed instead of touching it.
    opened = PaperStore(dsn)
    options_existed = opened.connection.execute(
        "SELECT to_regclass('options_paper.paper_state') AS name"
    ).fetchone()["name"]
    opened.close()
    if options_existed:
        pytest.skip("Dedicated fixture database already has historical options; do not remove it")
    with TestClient(
        create_app(
            Settings(),
            tmp_path / "m.sqlite3",
            background=False,
            paper_database=tmp_path / "settings",
        )
    ) as client:
        report = client.get("/api/status").json()
        assert not report["options"]["enabled"] and not report["options"]["error"]
        assert all(
            a["risk"]["policy"] == HARD_STOP_POLICY for a in report["paper"]["accounts"].values()
        )
