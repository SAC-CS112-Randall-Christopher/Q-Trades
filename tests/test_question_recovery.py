"""Actual question HTTP acknowledgments and transactional rejection fencing."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_role_worker import make_lab

from trading.api import create_app
from trading.config import Settings
from trading.role_worker import Question, RoleWorker

HEADERS = {"X-Local-Operator": "1"}


@pytest.fixture
def recovery(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    controller = make_lab(store, tmp_path)
    worker = RoleWorker(controller.registry, controller)
    with TestClient(
        create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    ) as client:
        client.app.state.lab.roles = worker
        yield client, worker, controller
    controller.registry.close()


def body(identity="recover-request-0001", **changes):
    return {
        "question": "Recover this explicit research intent without enabling inference.",
        "horizon": "short",
        "parent": None,
        "request_id": identity,
    } | changes


def post(client, value):
    return client.post("/api/lab/roles/questions", json=value, headers=HEADERS)


def test_invalid_parent_rejection_is_confirmed_and_correction_has_new_identity(recovery):
    import sqlite3

    client, worker, controller = recovery
    invalid = body(parent="nonexistent-parent")
    rejected = post(client, invalid)
    detail = rejected.json()["detail"]
    assert rejected.status_code == 409 and detail["outcome"] == "not_created"
    assert (
        detail["request_id"] == invalid["request_id"]
        and detail["intent"]["parent"] == invalid["parent"]
    )
    assert worker.page()["history"]["retained"] == 0
    assert post(client, invalid).json()["detail"] == detail
    assert post(client, body()).json()["detail"]["outcome"] == "intent_conflict"
    accepted = post(client, body("corrected-request-0001"))
    assert accepted.status_code == 200 and accepted.json()["status"] == "queued"
    assert worker.page()["history"]["retained"] == 1 and not worker.enabled
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        worker.registry.db.execute("UPDATE role_rejections SET reason='rewrite'")
    assert controller.paper.store.reconcile()["balanced"]


def test_queue_full_rejection_can_retry_as_new_intent_without_duplicate_creation(recovery):
    client, worker, _ = recovery
    for i in range(8):
        worker.enqueue(
            Question(question=f"Keep ordinary queue fixture question number {i} active.")
        )
    rejected = post(client, body())
    assert rejected.status_code == 409 and rejected.json()["detail"]["outcome"] == "not_created"
    first = worker.page()["tasks"][0]["id"]
    worker._update(worker.get(first), "complete", "done", reason="Owned queue fixture released")
    # A confirmed rejection closes that request forever, including late concurrent copies.
    assert post(client, body()).json()["detail"]["outcome"] == "not_created"
    new = body("queue-retry-request")
    accepted = post(client, new)
    assert accepted.status_code == 200
    for _ in range(3):
        assert post(client, new).json()["id"] == accepted.json()["id"]
    assert worker.page()["history"]["active"] == 8
    assert worker.page()["history"]["retained"] == 9


def test_detail_error_after_creation_never_reports_pre_enqueue_rejection(recovery, monkeypatch):
    client, worker, _ = recovery
    view = worker.view

    def unavailable(identity):
        raise ValueError("Owned detail/disclosure failure after task creation")

    monkeypatch.setattr(worker, "view", unavailable)
    response = post(client, body())
    receipt = response.json()["detail"]
    assert response.status_code == 503 and receipt["outcome"] == "created"
    assert receipt["task"] == worker.page()["tasks"][0]["id"]
    assert not worker.registry.db.execute("SELECT 1 FROM role_rejections").fetchone()
    monkeypatch.setattr(worker, "view", view)
    assert post(client, body()).json()["id"] == receipt["task"]
    assert worker.page()["history"]["retained"] == 1


def test_lost_success_response_reconciles_original_intent_after_source_changes(
    recovery, monkeypatch
):
    from test_autonomous_lab import tick_lab

    client, worker, controller = recovery
    view = worker.view
    identities = []

    def lost_ack(identity):
        identities.append(view(identity)["id"])
        raise OSError("Owned lost final HTTP acknowledgment")

    monkeypatch.setattr(worker, "view", lost_ack)
    assert post(client, body()).status_code == 503
    tick_lab(controller, START + 120)
    restarted = RoleWorker(worker.registry, controller)
    client.app.state.lab.roles = restarted
    response = post(client, body())
    assert response.status_code == 200 and response.json()["id"] == identities[0]
    assert restarted.page()["history"]["retained"] == 1 and not restarted.enabled


def test_committed_rejection_prevents_an_inflight_valid_copy_from_later_creating(
    recovery, monkeypatch
):
    client, worker, controller = recovery
    entered, release = Event(), Event()
    bundle = controller.bundle

    def paused(now):
        entered.set()
        assert release.wait(10)
        return bundle(now)

    monkeypatch.setattr(controller, "bundle", paused)
    policy = controller.paper.state["autonomous_lab"]["policy"]
    horizons = policy["holding_horizons"]
    with ThreadPoolExecutor(max_workers=1) as threads:
        pending = threads.submit(post, client, body())
        try:
            assert entered.wait(10)
            policy["holding_horizons"] = []  # Owned policy-change ordering, no account mutation.
            rejected = post(client, body())
            assert (
                rejected.status_code == 409
                and rejected.json()["detail"]["outcome"] == "not_created"
            )
        finally:
            policy["holding_horizons"] = horizons
            release.set()
        late = pending.result(timeout=10)
    assert late.status_code == 409 and late.json()["detail"]["outcome"] == "not_created"
    assert worker.page()["history"]["retained"] == 0
    assert not worker.registry.db.execute("SELECT 1 FROM role_requests").fetchone()


def test_simultaneous_identical_requests_share_one_task(recovery, monkeypatch):
    client, worker, controller = recovery
    from threading import Barrier

    ready = Barrier(2)
    bundle = controller.bundle

    def simultaneous(now):
        result = bundle(now)
        ready.wait(timeout=10)
        return result

    monkeypatch.setattr(controller, "bundle", simultaneous)
    with ThreadPoolExecutor(max_workers=2) as threads:
        replies = list(threads.map(lambda _: post(client, body()), range(2)))
    assert [r.status_code for r in replies] == [200, 200]
    assert replies[0].json()["id"] == replies[1].json()["id"]
    assert worker.page()["history"]["retained"] == 1
