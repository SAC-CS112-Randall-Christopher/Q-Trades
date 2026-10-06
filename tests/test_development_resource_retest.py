"""Append-only retest accounting with synthetic caller evidence; no model/private reads."""

import asyncio
import copy
import hashlib
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from scripts import answer_development_role as route
from trading.api import create_app
from trading.autonomous_lab import InputWait
from trading.config import Settings
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.local_role_model import LocalRoles
from trading.peft_profile import PROFILE, digest
from trading.peft_role_model import DevelopmentTransportFailure, PeftDevelopmentRoles
from trading.role_worker import ResourceRetestAuthorization, RoleWorker

TASK = "role-" + "b" * 32
STAGE = "development_idea"
ANSWER = {
    "action": "no_change",
    "evidence_ids": ["e0"],
    "capability": None,
    "mechanism": "Only synthetic procedural evidence is available.",
    "falsification": "An independently observed outcome could change this limitation.",
    "rationale": "No model or market result was measured by this software fixture.",
    "dependency": None,
}


def row(worker, table):
    key = "id" if table == "role_tasks" else "task"
    return dict(
        worker.registry.db.execute(f"SELECT * FROM {table} WHERE {key}=?", (TASK,)).fetchone()
    )


def state(worker):
    return {
        "task": row(worker, "role_tasks"),
        "attempts": [dict(r) for r in worker.registry.db.execute("SELECT * FROM role_attempts")],
        "allowances": [
            dict(r) for r in worker.registry.db.execute("SELECT * FROM role_attempt_allowances")
        ],
        "events": [dict(r) for r in worker.registry.db.execute("SELECT * FROM experiment_events")],
    }


def authorization(worker, packet, **changes):
    source = Path(__file__).parents[1] / "src" / "trading"
    value = {
        "format": "qtrades-development-resource-retest-v1",
        "grant_id": "synthetic_qa_not_human_permission",
        "task": TASK,
        "stage": STAGE,
        "task_sha256": fingerprint(row(worker, "role_tasks")),
        "prior_attempt_sha256": fingerprint(row(worker, "role_attempts")),
        "packet_sha256": fingerprint(packet),
        "profile_sha256": digest(PROFILE),
        "owner_source_sha256": hashlib.sha256(
            (source / "peft_child_owner.py").read_bytes()
        ).hexdigest(),
        "transport_source_sha256": hashlib.sha256(
            (source / "peft_role_model.py").read_bytes()
        ).hexdigest(),
        "expires_at": time.time() + 60,
    }
    return ResourceRetestAuthorization.model_validate(value | changes)


def retest(worker, model, grant, deadline=None):
    return asyncio.run(
        worker.development_answer(
            TASK,
            model,
            resource_retest_authorization=grant,
            cancel_at_monotonic=time.monotonic() + 5 if deadline is None else deadline,
        )
    )


@pytest.fixture
def development(tmp_path, monkeypatch):
    registry = ExperimentRegistry(tmp_path / "synthetic-registry.sqlite3")
    worker = RoleWorker(registry, None)
    packet = {
        "question": "Which limitations follow from this synthetic procedural evidence?",
        "capabilities": {},
        "evidence": {"e0": {"basis": "synthetic_qa", "fact": "No empirical outcome"}},
    }
    monkeypatch.setattr(worker, "_base_packet", lambda task: ("researcher", copy.deepcopy(packet)))
    receipt = {
        "kind": "development_transport_failure",
        "complete": False,
        "status": "cancelled",
        "exception_type": "ValueError",
        "wall_seconds": 1.0,
        "peak_rss_bytes": None,
        "rss_observations": 0,
        "exit_code": 1,
        "child_terminated": True,
        "cleanup_complete": True,
        "cleanup_error_types": [],
        "profile_sha256": digest(PROFILE),
        "private_dispatch_retained": True,
        "private_job": "c" * 32,
        "scope": "Synthetic failure fixture; no actual development inference",
    }
    now = time.time()
    with registry.transaction():
        registry.db.execute(
            "INSERT INTO role_tasks(id,created,updated,stage,status,context) "
            "VALUES(?,?,?,'idea','queued',?)",
            (TASK, now - 30, now - 30, json.dumps({"question": {"question": packet["question"]}})),
        )
        registry.db.execute(
            "INSERT INTO role_attempts(task,stage,attempt,started,finished,status,profile,packet,"
            "response,reason,wall_reserved,tokens_reserved) VALUES(?,?,1,?,?,'failed',?,?,?,?,?,?)",
            (
                TASK,
                STAGE,
                now - 20,
                now - 19,
                json.dumps(PROFILE),
                json.dumps(packet),
                json.dumps(receipt, sort_keys=True),
                "Synthetic known resource-owner cancellation",
                PROFILE["timeout_seconds"],
                PROFILE["token_allowance"],
            ),
        )
    model = PeftDevelopmentRoles(tmp_path)
    monkeypatch.setattr(model, "declaration", lambda: ({}, {}, copy.deepcopy(PROFILE)))
    guard = Mock()
    monkeypatch.setattr(LocalRoles, "paper_guard", guard)
    infer = Mock(return_value={"answer": ANSWER, "complete": True, "raw_answer": "Synthetic only"})
    monkeypatch.setattr(model, "infer", infer)
    try:
        yield worker, model, packet, guard, infer
    finally:
        registry.close()


def test_append_only_retest_reopens_both_attempts_and_keeps_cached_result(development, tmp_path):
    worker, model, packet, guard, infer = development
    before = state(worker)
    grant = authorization(worker, packet)
    assert retest(worker, model, grant).action == "no_change"
    after = state(worker)
    assert after["task"] == before["task"]
    assert after["attempts"][0] == before["attempts"][0]
    assert after["allowances"][0] == before["allowances"][0]
    assert len(after["attempts"]) == len(after["allowances"]) == 2
    assert sum(a["wall_reserved"] for a in after["allowances"]) == 1200
    assert sum(a["tokens_reserved"] for a in after["allowances"]) == 16384
    second = after["attempts"][1]
    assert second["attempt"] == 2 and second["stage"] == STAGE and second["status"] == "answered"
    assert second["profile"] == before["attempts"][0]["profile"]
    assert second["packet"] == before["attempts"][0]["packet"]
    events = after["events"][len(before["events"]) :]
    assert len(events) == 1 and events[0]["kind"] == "development_resource_retest_reserved"
    body = json.loads(events[0]["body"])
    assert body["authorization"] == grant.model_dump()
    assert body["authorization_sha256"] == fingerprint(grant.model_dump())
    assert body["attempt"] == 2 and body["prior_attempt"] == 1
    guard.assert_called_once()
    infer.assert_called_once()
    assert asyncio.run(worker.development_answer(TASK, model)).action == "no_change"
    with pytest.raises(ValueError, match="original failed attempt one"):
        retest(worker, model, grant)
    assert state(worker) == after
    app = create_app(Settings(), tmp_path / "unused-monitor.sqlite", background=False)
    app.state.lab = SimpleNamespace(roles=worker)
    # Actual normal route, without lifespan/server or a financial database.
    client = TestClient(app, follow_redirects=False)
    try:
        detail = client.get(f"/api/lab/roles/tasks/{TASK}")
        assert detail.status_code == 200
        attempts = detail.json()["attempts"]
        assert [a["attempt"] for a in attempts] == [1, 2]
        assert attempts[0]["response"]["status"] == "cancelled"
        assert attempts[1]["response"]["answer"] == ANSWER
        assert all("packet" not in a for a in attempts)
        assert (
            client.get(
                f"/api/lab/roles/tasks/{TASK}/training-candidate?stage={STAGE}&attempt=2"
            ).status_code
            == 422
        )
    finally:
        client.close()
    assert state(worker) == after


def test_default_failed_request_is_unchanged(development):
    worker, model, _, guard, infer = development
    before = state(worker)
    with pytest.raises(ValueError, match="transport failed; no invisible retry"):
        asyncio.run(worker.development_answer(TASK, model))
    assert state(worker) == before
    guard.assert_not_called()
    infer.assert_not_called()


@pytest.mark.parametrize(
    "field",
    [
        "task_sha256",
        "prior_attempt_sha256",
        "packet_sha256",
        "profile_sha256",
        "owner_source_sha256",
        "transport_source_sha256",
    ],
)
def test_changed_binding_refuses_before_guard_or_allowance(development, field):
    worker, model, packet, guard, infer = development
    grant = authorization(worker, packet, **{field: "0" * 64})
    before = state(worker)
    with pytest.raises(ValueError, match="frozen bindings"):
        retest(worker, model, grant)
    assert state(worker) == before
    guard.assert_not_called()
    infer.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "timeout"},
        {"complete": True},
        {"cleanup_complete": False},
        {"child_terminated": None},
        {"exit_code": None},
        {"exit_code": True},
        {"private_dispatch_retained": False},
        {"cleanup_error_types": ["OSError"]},
        {"answer": ANSWER},
        {"raw_answer": "A retained answer"},
        {"transport_failure": {}},
        {"kind": "development_dispatch"},
    ],
)
def test_only_known_pure_cancelled_failure_can_be_retested(development, changes):
    worker, model, packet, guard, infer = development
    prior = row(worker, "role_attempts")
    # Synthetic fixture setup only: insert a different failed row rather than rewrite a response.
    with worker.registry.transaction():
        worker.registry.db.execute("DELETE FROM role_attempts WHERE task=?", (TASK,))
        columns = list(prior)
        prior["response"] = json.dumps(json.loads(prior["response"]) | changes)
        worker.registry.db.execute(
            f"INSERT INTO role_attempts({','.join(columns)}) "
            f"VALUES({','.join('?' for _ in columns)})",
            tuple(prior.values()),
        )
    grant = authorization(worker, packet)
    before = state(worker)
    with pytest.raises(ValueError, match="known cancelled cleanup"):
        retest(worker, model, grant)
    assert state(worker) == before
    guard.assert_not_called()
    infer.assert_not_called()


@pytest.mark.parametrize(
    "missing",
    [
        "kind",
        "complete",
        "status",
        "exception_type",
        "private_job",
        "wall_seconds",
        "peak_rss_bytes",
        "rss_observations",
        "exit_code",
        "child_terminated",
        "cleanup_complete",
        "cleanup_error_types",
        "profile_sha256",
        "private_dispatch_retained",
        "scope",
        None,
    ],
)
def test_only_exact_emitted_failure_layout_is_eligible(development, missing):
    worker, model, packet, guard, infer = development
    prior = row(worker, "role_attempts")
    response = json.loads(prior["response"])
    if missing is None:
        response["undocumented_original_output"] = "Synthetic retained output must refuse retest"
    else:
        response.pop(missing)
    with worker.registry.transaction():
        worker.registry.db.execute("DELETE FROM role_attempts WHERE task=?", (TASK,))
        prior["response"] = json.dumps(response)
        columns = list(prior)
        worker.registry.db.execute(
            f"INSERT INTO role_attempts({','.join(columns)}) "
            f"VALUES({','.join('?' for _ in columns)})",
            tuple(prior.values()),
        )
    before = state(worker)
    with pytest.raises(ValueError, match="known cancelled cleanup"):
        retest(worker, model, authorization(worker, packet))
    assert state(worker) == before
    guard.assert_not_called()
    infer.assert_not_called()


@pytest.mark.parametrize("fault", ["absent", "unknown", "unfinished", "answered", "third"])
def test_attempt_state_refusals(development, fault):
    worker, model, packet, guard, infer = development
    grant = authorization(worker, packet)
    with worker.registry.transaction():
        if fault == "absent":
            worker.registry.db.execute("DELETE FROM role_attempts WHERE task=?", (TASK,))
        elif fault == "unknown":
            worker.registry.db.execute("DELETE FROM role_attempts WHERE task=?", (TASK,))
            worker.registry.db.execute(
                "INSERT INTO role_attempts(task,stage,attempt,started,status,profile,packet,"
                "wall_reserved,tokens_reserved) VALUES(?,?,1,?,'failed',?,?,600,8192)",
                (TASK, STAGE, time.time(), json.dumps(PROFILE), json.dumps(packet)),
            )
        else:
            field, value = {
                "unfinished": ("finished", None),
                "answered": ("status", "answered"),
                "third": ("attempt", 2),
            }[fault]
            worker.registry.db.execute(
                f"UPDATE role_attempts SET {field}=? WHERE task=?", (value, TASK)
            )
    before = state(worker)
    with pytest.raises(ValueError):
        retest(worker, model, grant)
    assert state(worker) == before
    guard.assert_not_called()
    infer.assert_not_called()


@pytest.mark.parametrize("deadline", [False, float("nan"), float("inf"), -1, 0])
def test_invalid_deadline_refuses_without_cost(development, deadline):
    worker, model, packet, guard, infer = development
    before = state(worker)
    with pytest.raises(ValueError, match="deadline"):
        retest(worker, model, authorization(worker, packet), deadline)
    assert state(worker) == before
    guard.assert_not_called()
    infer.assert_not_called()


@pytest.mark.parametrize(
    "fault",
    [
        "expiry",
        "missing_deadline",
        "long_deadline",
        "closed_guard",
        "allowance",
        "profile",
        "task",
        "row",
        "operating",
    ],
)
def test_refusals_before_atomic_reservation(development, monkeypatch, fault):
    worker, model, packet, guard, infer = development
    grant = authorization(worker, packet)
    deadline = time.monotonic() + 5
    if fault == "expiry":
        grant = authorization(worker, packet, expires_at=time.time() - 1)
    elif fault == "missing_deadline":
        deadline = None
    elif fault == "long_deadline":
        deadline = time.monotonic() + 601
    elif fault == "closed_guard":
        guard.side_effect = ValueError("Full paper guard is closed")
    elif fault == "allowance":
        with worker.registry.transaction():
            worker.registry.db.execute(
                "UPDATE role_attempts SET wall_reserved=1800 WHERE task=?", (TASK,)
            )
        grant = authorization(worker, packet)
    elif fault == "profile":
        monkeypatch.setattr(model, "declaration", lambda: ({}, {}, PROFILE | {"seed": 1}))
    elif fault == "task":
        guard.side_effect = lambda: worker.registry.db.execute(
            "UPDATE role_tasks SET reason='Changed during admission' WHERE id=?", (TASK,)
        )
    elif fault == "row":
        guard.side_effect = lambda: worker.registry.db.execute(
            "UPDATE role_attempts SET reason='Changed during admission' WHERE task=?", (TASK,)
        )
    else:
        guard.side_effect = lambda: setattr(worker, "enabled", True)
    before = state(worker)
    with pytest.raises((ValueError, InputWait)):
        asyncio.run(
            worker.development_answer(
                TASK, model, resource_retest_authorization=grant, cancel_at_monotonic=deadline
            )
        )
    after = state(worker)
    assert len(after["attempts"]) == len(after["allowances"]) == 1
    assert after["events"] == before["events"]
    if fault not in {"task", "row"}:
        assert after == before
    infer.assert_not_called()


def test_duplicate_concurrent_grant_reserves_and_dispatches_only_once(development, monkeypatch):
    worker, model, packet, _, infer = development
    grant = authorization(worker, packet)
    barrier = threading.Barrier(2)
    admit = model.development_admit

    def concurrent_admit(role):
        barrier.wait(timeout=5)
        return admit(role)

    monkeypatch.setattr(model, "development_admit", concurrent_admit)

    async def run():
        return await asyncio.gather(
            *(
                worker.development_answer(
                    TASK,
                    model,
                    resource_retest_authorization=grant,
                    cancel_at_monotonic=time.monotonic() + 5,
                )
                for _ in range(2)
            ),
            return_exceptions=True,
        )

    results = asyncio.run(run())
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert len(state(worker)["attempts"]) == 2
    assert len(state(worker)["events"]) == 1
    infer.assert_called_once()


@pytest.mark.parametrize("phase", ["guard", "preflight"])
def test_deadline_expiring_during_admission_has_no_new_reservation(development, monkeypatch, phase):
    worker, model, packet, guard, infer = development
    grant = authorization(worker, packet)
    now = time.monotonic()
    clock = [now]
    monkeypatch.setattr("trading.role_worker.time.monotonic", lambda: clock[0])
    if phase == "guard":
        guard.side_effect = lambda: clock.__setitem__(0, now + 2)
    else:
        monkeypatch.setattr(model, "preflight", lambda *args: clock.__setitem__(0, now + 2))
    before = state(worker)
    with pytest.raises((ValueError, TimeoutError)):
        retest(worker, model, grant, now + 1)
    assert state(worker) == before
    infer.assert_not_called()


def test_authorization_event_failure_rolls_back_new_attempt(development, monkeypatch):
    worker, model, packet, _, infer = development
    grant = authorization(worker, packet)
    before = state(worker)
    original_event = worker.registry.event

    def event(*args):
        original_event(*args)
        assert len(state(worker)["attempts"]) == 2
        raise OSError("Synthetic immutable event write failure")

    monkeypatch.setattr(worker.registry, "event", event)
    with pytest.raises(OSError, match="event write failure"):
        retest(worker, model, grant)
    assert state(worker) == before
    infer.assert_not_called()


@pytest.mark.parametrize("fault", ["transport", "unknown", "incomplete", "invalid"])
def test_second_failed_attempt_is_retained_and_never_permits_third(development, fault):
    worker, model, packet, _, infer = development
    before = state(worker)
    grant = authorization(worker, packet)
    if fault == "transport":
        infer.side_effect = DevelopmentTransportFailure(
            json.loads(before["attempts"][0]["response"])
        )
    elif fault == "unknown":
        infer.side_effect = ValueError("Synthetic unknown completion")
    else:
        infer.return_value = {
            "answer": ANSWER if fault == "incomplete" else {"invalid": True},
            "complete": fault != "incomplete",
            "raw_answer": "Original synthetic failed answer",
        }
    with pytest.raises(ValueError):
        retest(worker, model, grant)
    saved = state(worker)
    assert saved["attempts"][0] == before["attempts"][0]
    assert saved["attempts"][1]["status"] == "failed"
    assert [a["status"] for a in worker.view(TASK)["attempts"]] == ["failed", "failed"]
    with pytest.raises(ValueError):
        retest(worker, model, grant)
    with pytest.raises(ValueError, match="no invisible retry"):
        asyncio.run(worker.development_answer(TASK, model))
    assert state(worker) == saved
    infer.assert_called_once()


@pytest.mark.parametrize("late_answer", [False, True])
def test_external_cancellation_waits_for_cleanup_and_retains_second_cost(development, late_answer):
    worker, model, packet, _, infer = development
    grant = authorization(worker, packet)
    entered, released, cleaned = threading.Event(), threading.Event(), threading.Event()
    model.cancel = Mock(side_effect=released.set)
    before = state(worker)

    def response(*args):
        entered.set()
        assert released.wait(timeout=3)
        time.sleep(0.02)
        cleaned.set()
        if not late_answer:
            raise ValueError("Synthetic unknown completion after owned cleanup")
        return {"answer": ANSWER, "complete": True, "raw_answer": "Late synthetic original"}

    infer.side_effect = response

    async def cancel():
        running = asyncio.create_task(
            worker.development_answer(
                TASK,
                model,
                resource_retest_authorization=grant,
                cancel_at_monotonic=time.monotonic() + 5,
            )
        )
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        running.cancel()
        with pytest.raises(asyncio.CancelledError if late_answer else ValueError):
            await running

    asyncio.run(cancel())
    assert cleaned.is_set()
    model.cancel.assert_called_once()
    saved = state(worker)
    assert saved["attempts"][0] == before["attempts"][0]
    assert saved["allowances"][0] == before["allowances"][0]
    assert len(saved["attempts"]) == len(saved["allowances"]) == 2
    second = saved["attempts"][1]
    assert second["status"] == "failed" and second["finished"] >= second["started"]
    if late_answer:
        assert json.loads(second["response"])["raw_answer"] == "Late synthetic original"
    else:
        assert second["response"] is None
    with pytest.raises(ValueError):
        retest(worker, model, grant)
    with pytest.raises(ValueError, match="no invisible retry"):
        asyncio.run(worker.development_answer(TASK, model))
    assert state(worker) == saved
    infer.assert_called_once()


def test_deadline_waits_for_owned_cleanup_and_preserves_late_answer_failed_once(development):
    worker, model, packet, _, infer = development
    grant = authorization(worker, packet)
    released, cleaned = threading.Event(), threading.Event()
    cancelled = Mock(side_effect=released.set)
    model.cancel = cancelled

    def late_answer(*args):
        assert released.wait(timeout=3)
        time.sleep(0.02)
        cleaned.set()
        return {"answer": ANSWER, "complete": True, "raw_answer": "Original late synthetic answer"}

    infer.side_effect = late_answer
    with pytest.raises(TimeoutError):
        asyncio.run(route.answer_with_deadline(worker, TASK, model, time.monotonic() + 0.05, grant))
    assert cleaned.is_set()
    cancelled.assert_called_once()
    saved = state(worker)
    assert saved["attempts"][1]["status"] == "failed"
    assert (
        json.loads(saved["attempts"][1]["response"])["raw_answer"]
        == "Original late synthetic answer"
    )
    with pytest.raises(ValueError, match="original failed attempt one"):
        retest(worker, model, grant)
    with pytest.raises(ValueError, match="no invisible retry"):
        asyncio.run(worker.development_answer(TASK, model))
    assert state(worker) == saved


@pytest.mark.parametrize("mode", ["original", "retest"])
def test_second_cancellation_during_deadline_cleanup_retains_original_failure(development, mode):
    worker, model, packet, _, infer = development
    if mode == "original":
        with worker.registry.transaction():
            worker.registry.db.execute("DELETE FROM role_attempts WHERE task=?", (TASK,))
    grant = authorization(worker, packet) if mode == "retest" else None
    before = state(worker)
    entered, draining = threading.Event(), threading.Event()
    released, cleaned = threading.Event(), threading.Event()
    model.cancel = Mock(side_effect=draining.set)

    def late_answer(*args):
        entered.set()
        assert released.wait(timeout=3)
        cleaned.set()
        return {
            "answer": ANSWER,
            "complete": True,
            "raw_answer": "Late after repeated cancellation",
        }

    infer.side_effect = late_answer

    async def interrupt_cleanup():
        running = asyncio.create_task(
            worker.development_answer(
                TASK,
                model,
                resource_retest_authorization=grant,
                cancel_at_monotonic=time.monotonic() + 0.05,
            )
        )
        try:
            if mode == "original":
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(0.01)
                assert entered.is_set()
                running.cancel()
            for _ in range(100):
                if draining.is_set():
                    break
                await asyncio.sleep(0.01)
            assert draining.is_set()
            running.cancel()
            await asyncio.sleep(0.02)
            waited_for_owner = not running.done()
            released.set()
            with pytest.raises(
                TimeoutError if mode == "retest" and waited_for_owner else asyncio.CancelledError
            ):
                await running
            assert waited_for_owner, "Second cancellation abandoned the owned inference drain"
        finally:
            released.set()

    asyncio.run(interrupt_cleanup())
    assert cleaned.is_set()
    model.cancel.assert_called_once()
    infer.assert_called_once()
    saved = state(worker)
    if mode == "retest":
        assert saved["attempts"][0] == before["attempts"][0]
        assert saved["allowances"][0] == before["allowances"][0]
    second = saved["attempts"][-1]
    assert second["status"] == "failed"
    assert second["reason"].startswith("TimeoutError:" if mode == "retest" else "CancelledError:")
    assert json.loads(second["response"])["raw_answer"] == "Late after repeated cancellation"
    assert len(saved["allowances"]) == (2 if mode == "retest" else 1)
    if mode == "retest":
        with pytest.raises(ValueError):
            retest(worker, model, grant)
        with pytest.raises(ValueError, match="no invisible retry"):
            asyncio.run(worker.development_answer(TASK, model))
    assert state(worker) == saved


@pytest.mark.parametrize(
    "fault",
    ["missing_flag", "missing_deadline", "expired", "oversize", "wrong_task", "extra_field"],
)
def test_cli_refusals_happen_before_registry_construction(
    development, tmp_path, monkeypatch, fault
):
    worker, _, packet, _, _ = development
    grant = authorization(worker, packet).model_dump()
    if fault == "expired":
        grant["expires_at"] = time.time() - 1
    if fault == "wrong_task":
        grant["task"] = "role-" + "a" * 32
    if fault == "extra_field":
        grant["unrecognized"] = "Synthetic caller text must not appear in validation diagnostics"
    receipt = tmp_path / "synthetic-caller-evidence-not-permission.json"
    receipt.write_text(" " * 8193 if fault == "oversize" else json.dumps(grant))
    created = Mock(side_effect=AssertionError("No registry constructor permitted"))
    monkeypatch.setattr(route, "ExperimentRegistry", created)
    args = [
        "answer_development_role.py",
        "--registry",
        str(tmp_path / "absent.sqlite3"),
        "--task",
        TASK,
        "--resource-repair-retest-authorization",
        str(receipt),
    ]
    if fault != "missing_flag":
        args += ["--authorized-development-inference"]
    if fault != "missing_deadline":
        args += ["--cancel-at-monotonic", str(time.monotonic() + 5)]
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises((SystemExit, ValueError)):
        route.main()
    created.assert_not_called()
