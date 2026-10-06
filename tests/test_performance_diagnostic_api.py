"""The normal operator API uses the sole writer and retains lost acknowledgments."""

import copy

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_paper_engine import START
from test_paper_store import pg_store as pg_store

from trading.api import create_app
from trading.config import Settings
from trading.paper_runtime import PaperRuntime

HEADERS = {"X-Local-Operator": "1", "Origin": "http://testserver"}
CREATE = {"request_id": "diagnostic-create-0001"}
START_BODY = {
    "request_id": "diagnostic-start-0001",
    "seed": 1,
    "max_actions": 1000,
    "duration_seconds": 600,
}


def test_single_account_create_lost_ack_restart_and_exact_funding(pg_store, tmp_path, monkeypatch):
    store, dsn = pg_store
    runtime = PaperRuntime(store, None)
    runtime.running = True
    monkeypatch.setattr("trading.paper_runtime.time.time", lambda: START)
    original_accounts = copy.deepcopy(store.read()["accounts"])
    app = create_app(Settings(), tmp_path / "monitor", background=False)
    original = store.transact

    def lost_ack(now, work):
        original(now, work)
        raise psycopg.OperationalError("Synthetic lost acknowledgment after commit")

    with TestClient(app) as client:
        client.app.state.paper = runtime
        assert not client.get("/api/paper/diagnostics").json()["created"]
        assert client.post("/api/paper/diagnostics/create", json=CREATE).status_code == 403
        with monkeypatch.context() as patch:
            patch.setattr(store, "transact", lost_ack)
            response = client.post("/api/paper/diagnostics/create", json=CREATE, headers=HEADERS)
        assert response.status_code == 503 and "same request" in response.json()["detail"]
        retained = store.export(0, 1000)
        reopened = client.get("/api/paper/diagnostics").json()
        assert reopened["created"] and reopened["create_request_id"] == CREATE["request_id"]
        assert reopened["account"]["cash"] == "1000000"
        assert reopened["account"]["purpose"] == "performance_diagnostic"
        retry = client.post("/api/paper/diagnostics/create", json=CREATE, headers=HEADERS)
        assert retry.json()["status"] == "already_applied"
        assert store.export(0, 1000) == retained and store.reconcile()["balanced"]
        assert {
            key: store.read()["accounts"][key] for key in original_accounts
        } == original_accounts
        funded = [e for e in retained["records"] if e["kind"] == "performance_diagnostic_funded"]
        assert len(funded) == 1 and funded[0]["body"]["amount"] == "1000000"
    from trading.paper_store import PaperStore

    store.close()
    reopened_store = PaperStore(dsn, owner=True)
    try:
        reopened_runtime = PaperRuntime(reopened_store, None)
        assert reopened_runtime.diagnostic_snapshot()["create_request_id"] == CREATE["request_id"]
        assert reopened_store.export(0, 1000) == retained
        assert reopened_store.reconcile()["balanced"]
    finally:
        reopened_store.close()


def test_start_budget_origin_and_stale_stop_without_fills(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    runtime = PaperRuntime(store, None)
    runtime.running = True
    monkeypatch.setattr("trading.paper_runtime.time.time", lambda: START)
    app = create_app(Settings(), tmp_path / "monitor", background=False)
    with TestClient(app) as client:
        client.app.state.paper = runtime
        assert (
            client.post("/api/paper/diagnostics/create", json=CREATE, headers=HEADERS).status_code
            == 200
        )
        assert (
            client.post(
                "/api/paper/diagnostics/start",
                json=START_BODY,
                headers={**HEADERS, "Origin": "http://foreign.invalid"},
            ).status_code
            == 403
        )
        for field, value in (("seed", True), ("max_actions", 1001), ("duration_seconds", 601)):
            assert (
                client.post(
                    "/api/paper/diagnostics/start",
                    json={**START_BODY, field: value},
                    headers=HEADERS,
                ).status_code
                == 422
            )
        assert (
            client.post(
                "/api/paper/diagnostics/start", json=START_BODY, headers=HEADERS
            ).status_code
            == 200
        )
        before = store.export(0, 1000)
        assert (
            client.post("/api/paper/diagnostics/start", json=START_BODY, headers=HEADERS).json()[
                "status"
            ]
            == "already_applied"
        )
        assert store.export(0, 1000) == before
        runtime.error, runtime.running = "Synthetic unavailable feed", False
        assert client.get("/api/paper/diagnostics").json()["entries_allowed"] is False
        stop = {"request_id": "diagnostic-stop-0001"}
        assert (
            client.post("/api/paper/diagnostics/stop", json=stop, headers=HEADERS).status_code
            == 200
        )
        status = client.get("/api/paper/diagnostics").json()
        assert status["last_control_request_id"] == stop["request_id"]
        assert status["run"]["status"] == "completed"
        assert status["account"]["valuation_fresh"] is False
        assert not any(e["kind"] == "fill" for e in store.export(0, 1000)["records"])
        assert store.reconcile()["balanced"]


def test_create_rollback_preserves_financial_prefix(pg_store):
    from trading.paper_diagnostics import create_diagnostic

    store, _ = pg_store
    before, events = store.read(), store.export(0, 1000)

    def fail(engine):
        create_diagnostic(engine, CREATE["request_id"])
        raise RuntimeError("Before diagnostic commit")

    with pytest.raises(RuntimeError, match="Before diagnostic commit"):
        store.transact(START, fail)
    assert store.read() == before and store.export(0, 1000) == events
