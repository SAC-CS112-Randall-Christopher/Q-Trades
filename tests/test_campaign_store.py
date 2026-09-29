"""Campaign persistence/API checks use generated schemas on the QA database."""

import copy

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_paper_campaigns import spec
from test_paper_engine import START, frame, study
from test_paper_store import pg_store as _pg_store

from trading.api import create_app
from trading.config import Settings
from trading.paper_campaigns import control_account, create_campaign
from trading.paper_engine import PaperEngine
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore

disposable_store = _pg_store


def launch(store):
    result = {}
    store.transact(START, lambda e: result.update(create_campaign(e, spec())))
    return result["campaign"]["accounts"]


def test_atomic_launch_rollback_and_unchanged_original_accounts(disposable_store):
    store, _ = disposable_store
    before, events = copy.deepcopy(store.read()), store.export(0, 1000)

    def fail(e):
        create_campaign(e, spec())
        raise RuntimeError("Test failure before commit")

    with pytest.raises(RuntimeError, match="before commit"):
        store.transact(START, fail)
    assert store.read() == before and store.export(0, 1000) == events
    names = launch(store)
    assert len(names) == 10 and store.reconcile()["balanced"]
    assert {n: store.read()["accounts"][n] for n in before["accounts"]} == before["accounts"]
    funding = [
        e for e in store.export(0, 1000)["records"] if e["kind"] == "campaign_account_funded"
    ]
    assert len(funding) == 10 and {r["account"] for r in funding} == set(names)
    before_retry = store.export(0, 1000)
    store.transact(START, lambda e: create_campaign(e, spec()))
    assert store.export(0, 1000) == before_retry and store.reconcile()["balanced"]


def test_restart_duplicate_data_launch_controls_and_worker_ownership(disposable_store):
    store, dsn = disposable_store
    names = launch(store)
    store.transact(START, lambda e: e.tick({"BTCUSD": frame()}, study()))
    store.transact(START + 2, lambda e: e.tick({"BTCUSD": frame(START + 2, sequence=2)}, {}))
    store.transact(START + 3, lambda e: control_account(e, names[0], "pause", 0, {}))
    before, events = store.read(), store.export(0, 1000)
    with pytest.raises(RuntimeError, match="Another paper engine"):
        PaperStore(dsn, owner=True)
    store.close()
    reopened = PaperStore(dsn, owner=True)
    try:
        reopened.initialize(START + 4, "50")
        assert reopened.read() == before and reopened.export(0, 1000) == events
        assert reopened.read()["accounts"][names[0]]["entries_paused"]
        reopened.transact(START + 4, lambda e: create_campaign(e, spec()))
        reopened.transact(START + 4, lambda e: control_account(e, names[0], "pause", 0, {}))
        reopened.transact(
            START + 4, lambda e: e.tick({"BTCUSD": frame(START + 4, sequence=2)}, study())
        )
        for name in names:
            a = reopened.read()["accounts"][name]
            assert a["cash"] == before["accounts"][name]["cash"]
            assert a["fees"] == before["accounts"][name]["fees"]
        reopened.transact(
            START + 1, lambda e: e.tick({"BTCUSD": frame(START + 1, sequence=99)}, study(99))
        )
        assert reopened.read()["last_tick"] == START + 4
        assert reopened.reconcile()["balanced"]
    finally:
        reopened.close()


def test_account_fault_rollback_and_recovery_are_journal_consistent(disposable_store, monkeypatch):
    store, _ = disposable_store
    names = launch(store)
    store.transact(START, lambda e: e.tick({"BTCUSD": frame()}, study()))
    original = PaperEngine.tick_account

    def fail(e, name, account, frames, features):
        original(e, name, account, frames, features)
        if name == names[0]:
            raise ArithmeticError("Test rollback after proposed fill")

    with monkeypatch.context() as m:
        m.setattr(PaperEngine, "tick_account", fail)
        store.transact(START + 2, lambda e: e.tick({"BTCUSD": frame(START + 2, sequence=2)}, {}))
    assert store.reconcile()["balanced"]
    page = store.export(0, 1000, names[0])
    assert all(r["account"] == names[0] for r in page["records"])
    assert not any(r["kind"] == "fill" for r in page["records"])
    assert store.read()["accounts"][names[1]]["positions"]
    store.transact(
        START + 3,
        lambda e: control_account(
            e, names[0], "recover", 1, {"BTCUSD": frame(START + 3, sequence=3)}
        ),
    )
    store.transact(START + 4, lambda e: e.tick({"BTCUSD": frame(START + 4, sequence=4)}, {}))
    assert store.read()["accounts"][names[0]]["positions"] and store.reconcile()["balanced"]
    records = store.export(0, 1000, names[0])["records"]
    assert sum(r["kind"] == "campaign_account_funded" for r in records) == 1
    assert sum(r["kind"] == "fill" for r in records) == 1


def test_paged_account_journal_retains_every_event_and_excludes_siblings(disposable_store):
    store, _ = disposable_store
    names = launch(store)
    for offset, seq in [(0, 1), (2, 2), (4, 3), (6, 4)]:
        store.transact(
            START + offset,
            lambda e, offset=offset, seq=seq: e.tick(
                {"BTCUSD": frame(START + offset, "100" if offset < 4 else "98", seq)},
                study() if offset == 0 else {},
            ),
        )
    expected = store.export(0, 1000, names[0])["records"]
    collected, cursor = [], 0
    while True:
        page = store.export(cursor, 2, names[0])
        collected.extend(page["records"])
        if not page["has_more"]:
            break
        assert page["next_after"] > cursor
        cursor = page["next_after"]
    assert collected == expected and all(r["account"] == names[0] for r in collected)
    assert store.reconcile()["balanced"]


def test_lost_launch_acknowledgment_retry_confirms_without_refunding(
    disposable_store, tmp_path, monkeypatch
):
    store, _ = disposable_store
    runtime = PaperRuntime(store, None)
    runtime.running = True
    monkeypatch.setattr("trading.paper_runtime.time.time", lambda: START)
    app = create_app(Settings(), tmp_path / "monitor", background=False)
    body = spec().model_dump()
    headers = {"X-Local-Operator": "1", "Origin": "http://testserver"}
    original = store.transact

    def lost_reply(now, work):
        original(now, work)
        raise psycopg.OperationalError("Synthetic lost reply after successful commit")

    with TestClient(app) as client:
        client.app.state.paper = runtime
        with monkeypatch.context() as m:
            m.setattr(store, "transact", lost_reply)
            lost = client.post("/api/paper/campaigns", json=body, headers=headers)
        assert lost.status_code == 503 and "same request" in lost.json()["detail"]
        before = store.export(0, 1000)
        confirmed = client.post("/api/paper/campaigns", json=body, headers=headers)
        assert confirmed.json()["status"] == "already_applied"
        assert store.export(0, 1000) == before and store.reconcile()["balanced"]
        assert sum(r["kind"] == "campaign_account_funded" for r in before["records"]) == 10


def test_api_launch_pause_errors_conflicts_and_unavailable_worker(
    disposable_store, tmp_path, monkeypatch
):
    store, _ = disposable_store
    runtime = PaperRuntime(store, None)
    runtime.running = True
    monkeypatch.setattr("trading.paper_runtime.time.time", lambda: START)
    app = create_app(Settings(), tmp_path / "monitor", background=False)
    headers = {"X-Local-Operator": "1", "Origin": "http://testserver"}
    body = spec().model_dump()
    with TestClient(app) as client:
        client.app.state.paper = runtime
        assert client.post("/api/paper/campaigns", json=body).status_code == 403
        assert (
            client.post(
                "/api/paper/campaigns",
                json=body,
                headers={**headers, "Origin": "http://outside.invalid"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/paper/campaigns", json={**body, "live": True}, headers=headers
            ).status_code
            == 422
        )
        response = client.post("/api/paper/campaigns", json=body, headers=headers)
        assert response.status_code == 200 and response.json()["status"] == "created"
        assert (
            client.post("/api/paper/campaigns", json=body, headers=headers).json()["status"]
            == "already_applied"
        )
        name = response.json()["campaign"]["accounts"][0]
        url = f"/api/paper/accounts/{name}/control"
        assert client.post(url, json={"action": "pause", "expected_version": 0}).status_code == 403
        assert (
            client.post(
                url, json={"action": "pause", "expected_version": True}, headers=headers
            ).status_code
            == 422
        )
        pause = {"action": "pause", "expected_version": 0}
        assert client.post(url, json=pause, headers=headers).json()["status"] == "applied"
        assert client.post(url, json=pause, headers=headers).json()["status"] == "already_applied"
        assert (
            client.post(
                url, json={"action": "resume", "expected_version": 0}, headers=headers
            ).status_code
            == 409
        )
        assert client.get("/api/paper/journal?account=missing").status_code == 404
        status = client.get("/api/status").json()["paper"]
        assert len(status["campaigns"][0]["accounts"]) == 10
        assert "this account" in status["accounts"][name]["risk"]["reason"]
        before = copy.deepcopy(store.read())

        def storage_error(*args):
            raise psycopg.OperationalError("private database detail")

        with monkeypatch.context() as m:
            m.setattr(store, "transact", storage_error)
            failed = client.post(
                url, json={"action": "resume", "expected_version": 1}, headers=headers
            )
            assert failed.status_code == 503 and "private database" not in failed.text
        assert store.read() == before
        runtime.running = False
        assert (
            client.post(
                url, json={"action": "resume", "expected_version": 1}, headers=headers
            ).status_code
            == 409
        )
        assert client.post("/api/paper/campaigns", json=body, headers=headers).status_code == 409
