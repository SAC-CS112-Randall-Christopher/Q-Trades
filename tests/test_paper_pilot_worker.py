"""Disposable worker control proof: no model, PostgreSQL or qualification calls."""

import asyncio
import copy
import json
import threading
from types import SimpleNamespace

import pytest
from test_autonomous_lab import bars_at
from test_paper_engine import START, frame
from test_research_storage import plan_at

from trading import autonomous_finance as finance
from trading.autonomous_spec import LabPolicy, LabProposal
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.paper_engine import PaperEngine, initial_state
from trading.peft_role_model import DevelopmentTransportFailure
from trading.research_storage import save_plan
from trading.role_worker import PAPER_RESEARCH_PILOT, Question, RoleWorker


class PilotFixture:
    paper_pilot = True

    def __init__(self, *, tokens=8192):
        self.calls = []
        self.tokens = tokens
        self.grant_id = "synthetic-pilot-grant"

    def policy(self):
        return {"grant_id": self.grant_id, "enabled": True}

    def admit(self, role):
        return {
            "timeout_seconds": 5,
            "hourly_wall_seconds": 60,
            "hourly_tokens": self.tokens,
            "token_allowance": 8192,
        }

    def readiness(self):
        return {"ready": True, "qualified": False, "qualification_valid": False, "profile": {}}

    def infer(self, role, packet, profile):
        self.calls.append((role, copy.deepcopy(packet)))
        assert "knowledge" not in packet and "retrieval_contract" not in packet
        return {
            "complete": True,
            "answer": {
                "action": "request_data",
                "capability": None,
                "evidence_ids": ["e2"],
                "mechanism": "Observe another closed-bar fixture before comparison.",
                "falsification": "Reject any claim without a matched mature comparison.",
                "rationale": "The fixture has no mature evidence of strategy benefit.",
                "dependency": "new_closed_bars",
            },
            "scope": "Synthetic worker fixture; no actual local model call",
        }


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    clock = [START]
    monkeypatch.setattr("trading.role_worker.time.time", lambda: clock[0])
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    state = initial_state(START)
    engine = PaperEngine(state, START)
    engine.universe_experiment(["BTCUSD", "ETHUSD"])
    finance.start(engine, LabPolicy(request_id="pilot-fixture-policy"))
    paper = SimpleNamespace(
        state=state,
        running=True,
        error=None,
        constrained=lambda: True,  # The shared latency guard stays closed.
        lab_history=lambda now, horizon: bars_at(now),
        control_frames=lambda symbols=None: {"BTCUSD": frame(clock[0])},
        memory_book=lambda symbol: None,
    )
    state["last_tick"] = START
    bundle = {"novelty_sha256": "synthetic-pilot-worker", "evidence": {}}
    controller = SimpleNamespace(
        paper=paper,
        can_research=lambda: False,
        bundle=lambda now: {"sha256": fingerprint(bundle), "bundle": bundle},
    )
    worker = RoleWorker(registry, controller, PilotFixture(tokens=65536))
    worker.enabled = True
    worker.paper_admission = lambda: True
    yield worker, clock, tmp_path
    registry.close()


def question(request="pilot-question-request"):
    return Question(
        question="Is there enough closed-bar evidence for a reviewed paper comparison?",
        request_id=request,
    )


def test_new_pilot_context_omits_rag_and_preserves_numerical_typed_inputs(workspace):
    worker, _, _ = workspace
    original = copy.deepcopy(worker.controller.paper.state)
    worker.knowledge = SimpleNamespace(
        retrieve=lambda *a, **k: pytest.fail("RAG is not authorized")
    )
    task = worker.enqueue(question(), START)
    assert task["context"]["execution_mode"] == PAPER_RESEARCH_PILOT
    assert task["context"]["pilot_grant_id"] == worker.transport.grant_id
    assert task["context"]["experimental"] is True and task["context"]["qualified"] is False
    assert "knowledge" not in task["context"]
    role, packet = worker._packet(task)
    assert role == "researcher" and set(packet["evidence"]) == {"e0", "e2"}
    assert packet["evidence"]["e2"]["request_data_conditions"]["new_closed_bars"]
    assert set(packet["capabilities"]) == {"r0", "r1"}
    assert worker.controller.paper.state == original
    readiness = worker.readiness()
    assert readiness["qualified"] is False and readiness["qualification_valid"] is False
    assert readiness["ready"] is True
    assert readiness["stages"]["retrieval"]["state"] == "not_enabled"
    assert worker.controller.can_research() is False  # Shared controller policy unchanged.


def test_existing_request_and_consumed_original_attempt_stay_immutable(workspace):
    worker, _, _ = workspace
    pilot = worker.transport
    worker.transport = SimpleNamespace()  # Historical default-mode question.
    original = worker.enqueue(question(), START)
    with worker.registry.transaction():
        worker.registry.db.execute(
            "INSERT INTO role_attempts(task,stage,attempt,started,status,profile,packet,"
            "wall_reserved,tokens_reserved) VALUES(?,'idea',1,?,'failed','{}','{}',600,8192)",
            (original["id"], START),
        )
    before = worker.get(original["id"])
    worker.transport = pilot
    assert worker.enqueue(question(), START + 1) == before
    assert not asyncio.run(worker.step(START))
    assert worker.get(original["id"]) == before
    with pytest.raises(ValueError, match="different role execution mode"):
        asyncio.run(worker._answer(before))
    with pytest.raises(ValueError, match="different role execution mode"):
        worker.retry(original["id"])
    # A new explicit request gets a different identity even on identical source inputs.
    new = worker.enqueue(question("new-pilot-request"), START)
    assert new["id"] != original["id"]
    assert pilot.calls == []


def test_only_protected_pilot_callback_admits_and_missing_callback_fails_closed(workspace):
    worker, _, _ = workspace
    task = worker.enqueue(question(), START)
    worker.paper_admission = None
    assert not asyncio.run(worker.step(START))
    assert worker.get(task["id"])["attempts"] == []
    assert worker.readiness()["operating_admission"]["state"] == "refused"
    worker.paper_admission = lambda: False
    assert not asyncio.run(worker.step(START + 31))
    assert worker.transport.calls == []
    worker.paper_admission = lambda: True
    assert asyncio.run(worker.step(START + 62))
    retained = worker.get(task["id"])
    assert retained["stage"] == "data_wait" and retained["status"] == "waiting"
    assert len(retained["attempts"]) == 1
    assert worker.controller.can_research() is False


def test_typed_new_bar_continuation_and_hourly_allowance_survive_pilot_restart(workspace):
    worker, clock, _ = workspace
    worker.transport.tokens = 8192
    first = worker.enqueue(question(), START)
    assert asyncio.run(worker.step(START))
    retained = worker.get(first["id"])
    assert retained["result"]["wait_requirement"]["kind"] == "closed_bars"
    assert worker.resume_sources(START) == 0
    clock[0] += 120
    worker.controller.paper.state["last_tick"] = clock[0]
    replacement = RoleWorker(worker.registry, worker.controller, worker.transport)
    replacement.enabled = True
    replacement.paper_admission = lambda: True
    assert replacement.resume_sources(clock[0]) == 1
    successor = worker.registry.db.execute(
        "SELECT id FROM role_tasks WHERE json_extract(context,'$.predecessor_task')=?",
        (first["id"],),
    ).fetchone()[0]
    assert replacement.get(successor)["context"]["execution_mode"] == PAPER_RESEARCH_PILOT
    assert not asyncio.run(replacement.step(clock[0]))
    assert "allowance" in replacement.get(successor)["reason"]
    assert len(worker.transport.calls) == 1
    assert replacement.get(first["id"])["attempts"] == retained["attempts"]


def test_old_wait_and_followup_are_not_mutated_or_used_by_pilot(workspace, monkeypatch):
    worker, _, _ = workspace
    pilot = worker.transport
    worker.transport = SimpleNamespace()
    old = worker.enqueue(question(), START)
    worker._update(
        old, "data_wait", "waiting", result={"wait_requirement": {"kind": "closed_bars"}}
    )
    with worker.registry.transaction():
        worker.registry.db.execute("INSERT INTO role_followups(task) VALUES(?)", (old["id"],))
    before = worker.get(old["id"])
    worker.transport = pilot
    monkeypatch.setattr(worker.history, "discover_followups", lambda: 0)
    assert worker.resume_sources(START + 120) == 0
    assert worker._resume_source(old["id"], START + 120) == 0
    assert worker.select_followups() == {"selected": 0, "waiting": 0}
    assert worker.get(old["id"]) == before
    assert worker.registry.db.execute("SELECT state FROM role_followups").fetchone()[0] == "pending"


def test_pilot_mode_survives_verified_history_archive_and_selected_answer(workspace, monkeypatch):
    worker, _, directory = workspace
    save_plan(directory, plan_at(directory))
    task = worker.enqueue(question(), START)
    assert asyncio.run(worker.step(START))
    completed = worker.get(task["id"])
    worker._update(completed, "complete", "done", reason="Synthetic archive boundary only")
    before = worker.get(task["id"])
    monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
    worker.history.rollover()
    stub = worker.registry.db.execute(
        "SELECT context,archive_reference FROM role_tasks WHERE id=?", (task["id"],)
    ).fetchone()
    assert json.loads(stub["context"])["execution_mode"] == PAPER_RESEARCH_PILOT
    assert json.loads(stub["context"])["pilot_grant_id"] == worker.transport.grant_id
    assert stub["archive_reference"] is not None
    archived = worker.get(task["id"])
    assert archived["context"] == before["context"]
    assert archived["attempts"] == before["attempts"]


def test_pilot_rejects_rag_in_frozen_context_and_reports_actual_owned_task(workspace):
    worker, _, _ = workspace
    task = worker.enqueue(question(), START)
    task["context"]["knowledge"] = {"passages": []}
    with pytest.raises(ValueError, match="RAG inputs"):
        worker._packet(task)
    assert worker.page()["current_task"] is None
    with worker.registry.transaction():
        worker.registry.db.execute(
            "UPDATE role_tasks SET owner=?,lease_until=?,status='running' WHERE id=?",
            (worker.owner, START + 100, task["id"]),
        )
    page = worker.page()
    assert page["paper_pilot"] is True and page["experimental"] is True
    assert page["current_task"]["id"] == task["id"]
    assert page["current_task"]["stage"] == "idea"


@pytest.mark.parametrize("mismatch", ["owner", "execution_mode", "pilot_grant_id"])
def test_current_task_does_not_claim_other_owner_or_old_pilot_authority(workspace, mismatch):
    worker, _, _ = workspace
    task = worker.enqueue(question(), START)
    context = task["context"]
    owner = worker.owner
    if mismatch == "owner":
        owner = "external-or-before-restart-worker"
    else:
        context[mismatch] = "qualified_roles" if mismatch == "execution_mode" else "old-pilot-grant"
    with worker.registry.transaction():
        worker.registry.db.execute(
            "UPDATE role_tasks SET owner=?,lease_until=?,status='running',context=? WHERE id=?",
            (owner, START + 100, json.dumps(context), task["id"]),
        )
    before = worker.get(task["id"])
    page = worker.page()
    assert page["current_task"] is None
    assert task["id"] in {row["id"] for row in page["tasks"]}
    assert worker.get(task["id"]) == before
    assert worker.transport.calls == []


@pytest.mark.parametrize("revocation", ["admission", "paper_pause", "proposals_pause"])
def test_response_wins_revocation_race_is_retained_without_stage_authority(workspace, revocation):
    worker, _, _ = workspace
    task = worker.enqueue(question(), START)
    infer = worker.transport.infer

    def revoke_then_answer(*args):
        response = infer(*args)
        if revocation == "admission":
            worker.paper_admission = lambda: False
        elif revocation == "paper_pause":
            worker.controller.paper.state["paused"] = True
        else:
            worker.controller.paper.state["autonomous_lab"]["proposals_paused"] = True
        return response

    worker.transport.infer = revoke_then_answer
    assert not asyncio.run(worker.step(START))
    retained = worker.get(task["id"])
    assert retained["stage"] == "idea" and retained["status"] == "waiting"
    assert retained["attempts"][0]["status"] == "answered"
    assert json.loads(retained["attempts"][0]["response"])["answer"]["action"] == "request_data"
    worker.paper_admission = lambda: True
    worker.controller.paper.state["paused"] = False
    worker.controller.paper.state["autonomous_lab"]["proposals_paused"] = False
    assert asyncio.run(worker.step(START + 31))
    assert worker.get(task["id"])["stage"] == "data_wait"
    assert len(worker.transport.calls) == 1  # The completed answer is reused exactly.


def review_stage(worker):
    task = worker.enqueue(question(), START)
    proposal = LabProposal(
        request_id="role-proposal-" + task["id"][5:],
        policy_id=task["context"]["policy"]["request_id"],
        source="external",
        mechanism="Review the issued frozen method; no inferred financial authority.",
        question="Does the retained reviewed method support exploratory paper only?",
        evidence_bundle_sha256=task["context"]["issued"]["sha256"],
        **worker._capability(task["context"]["catalog"]["r0"]),
    )
    worker._update(
        task,
        "review",
        proposal=proposal.model_dump(),
        evaluation={"input_count": 1, "input_sha256": "synthetic", "feature": {}},
    )
    return worker.get(task["id"])


def test_failed_reviewer_keeps_actual_answer_failure_and_consumed_allowance(workspace):
    worker, _, _ = workspace
    task = review_stage(worker)
    answer = {
        "complete": True,
        "answer": {
            "action": "exploratory_paper_only",
            "evidence_ids": ["e0", "e1"],
            "issues": [],
            "rationale": "This synthetic review permits only a subsequent paper comparison.",
        },
    }
    failure = {"private_job": "fixture-job", "status": "cleanup", "cleanup_complete": False}

    def fail(role, packet, profile):
        worker.transport.calls.append((role, copy.deepcopy(packet)))
        raise DevelopmentTransportFailure(failure, answer)

    worker.transport.infer = fail
    assert not asyncio.run(worker.step(START))
    retained = worker.get(task["id"])
    assert retained["stage"] == "review" and retained["status"] == "failed"
    attempt = retained["attempts"][0]
    assert attempt["wall_reserved"] == 5 and attempt["tokens_reserved"] == 8192
    response = json.loads(attempt["response"])
    assert response["answer"] == answer["answer"] and response["transport_failure"] == failure
    with pytest.raises(ValueError, match="Completed verdicts"):
        worker.retry(task["id"])
    with pytest.raises(ValueError, match="failed pilot answer"):
        asyncio.run(worker._answer(retained))
    assert not asyncio.run(worker.step(START + 100))
    assert len(worker.transport.calls) == 1


def test_unresolved_pilot_attempt_is_never_restarted_or_rebudgeted(workspace):
    worker, _, _ = workspace
    task = worker.enqueue(question(), START)
    role, packet = worker._packet(task)
    profile = worker.transport.admit(role)
    with worker.registry.transaction():
        worker.registry.db.execute(
            "INSERT INTO role_attempts(task,stage,attempt,started,status,profile,packet,"
            "wall_reserved,tokens_reserved) VALUES(?,'idea',1,?,'running',?,?,5,8192)",
            (task["id"], START, json.dumps(profile), json.dumps(packet)),
        )
    replacement = RoleWorker(worker.registry, worker.controller, worker.transport)
    replacement.enabled = True
    replacement.paper_admission = lambda: True
    assert not asyncio.run(replacement.step(START + 631))
    retained = replacement.get(task["id"])
    assert retained["status"] == "failed" and "completion unknown" in retained["reason"]
    assert len(retained["attempts"]) == 1 and retained["attempts"][0]["wall_reserved"] == 5
    assert worker.transport.calls == []


def test_pilot_supervisor_cancel_awaits_owned_cleanup_and_retains_racing_answer(workspace):
    worker, _, _ = workspace
    task = worker.enqueue(question(), START)
    entered, cleanup = threading.Event(), threading.Event()
    infer = worker.transport.infer

    def blocked(*args):
        entered.set()
        assert cleanup.wait(5)
        return infer(*args)

    worker.transport.infer = blocked
    worker.transport.cancel = cleanup.set

    async def cancel():
        pending = asyncio.create_task(worker.step(START))
        assert await asyncio.to_thread(entered.wait, 5)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert cleanup.is_set()

    asyncio.run(cancel())
    attempt = worker.get(task["id"])["attempts"][0]
    assert attempt["finished"] is not None and attempt["status"] == "failed"
    assert json.loads(attempt["response"])["answer"]["action"] == "request_data"
    assert len(worker.transport.calls) == 1


@pytest.mark.parametrize("archived", [False, True])
def test_pilot_answers_cannot_automatically_become_training_candidates(
    workspace, monkeypatch, archived
):
    worker, _, directory = workspace
    task = worker.enqueue(question(), START)
    assert asyncio.run(worker.step(START))
    if archived:
        save_plan(directory, plan_at(directory))
        worker._update(worker.get(task["id"]), "complete", "done")
        monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
        worker.history.rollover()
        row = worker.registry.db.execute(
            "SELECT context,archive_reference FROM role_tasks WHERE id=?", (task["id"],)
        ).fetchone()
        assert row["archive_reference"] is not None
        # Even a compact stub without the mode cannot reinterpret the verified
        # original archived pilot context as training-export authority.
        with worker.registry.transaction():
            worker.registry.db.execute(
                "UPDATE role_tasks SET context=? WHERE id=?",
                (json.dumps({"question": task["context"]["question"]}), task["id"]),
            )
    before = worker.get(task["id"])
    disclosed_before = worker.registry.db.execute(
        "SELECT count(*) FROM evidence_windows"
    ).fetchone()[0]

    def fail(*args):
        raise AssertionError("Full task dashboard must not be used for selected export")

    with monkeypatch.context() as selected_reader:
        selected_reader.setattr(worker, "get", fail)
        selected_reader.setattr(worker, "view", fail)
        with pytest.raises(ValueError, match="training export needs separate authorization"):
            worker.training_candidate(task["id"], "idea", 1)
    assert (
        worker.registry.db.execute("SELECT count(*) FROM evidence_windows").fetchone()[0]
        == disclosed_before
    )
    assert worker.get(task["id"]) == before


def test_pilot_page_uses_current_activation_without_dispatch(workspace):
    worker, _, _ = workspace
    task = worker.enqueue(question(), START)
    worker.activation = lambda: False
    page = worker.page()
    assert page["enabled"] is False and worker.enabled is True
    assert not asyncio.run(worker.step(START))
    assert worker.get(task["id"])["attempts"] == []
    worker.activation = lambda: True
    assert worker.page()["enabled"] is True
    assert worker.transport.calls == []


def test_default_transport_cancel_preserves_original_unknown_completion_semantics(workspace):
    worker, _, _ = workspace
    worker.transport.paper_pilot = False
    worker.controller.can_research = lambda: True
    task = worker.enqueue(question(), START)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    infer = worker.transport.infer

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        try:
            return infer(*args)
        finally:
            finished.set()

    worker.transport.infer = blocked

    async def cancel():
        pending = asyncio.create_task(worker.step(START))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            attempt = worker.get(task["id"])["attempts"][0]
            assert attempt["status"] == "running" and attempt["finished"] is None
            assert attempt["response"] is None
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 5)

    asyncio.run(cancel())
    assert worker.get(task["id"])["attempts"][0]["status"] == "running"


def test_replaced_pilot_grant_cannot_claim_old_tasks_or_reuse_old_response(workspace):
    worker, _, _ = workspace
    original = worker.enqueue(question(), START)
    before = worker.get(original["id"])
    worker.transport.grant_id = "replacement-pilot-grant"
    assert not asyncio.run(worker.step(START))
    assert worker.get(original["id"]) == before
    replacement = worker.enqueue(question("replacement-question"), START)
    assert replacement["id"] != original["id"]
    assert replacement["context"]["pilot_grant_id"] == "replacement-pilot-grant"
    assert asyncio.run(worker.step(START))
    assert len(worker.transport.calls) == 1
    assert worker.get(original["id"]) == before


def test_grant_replacement_after_model_response_retains_answer_without_advancement(workspace):
    worker, _, _ = workspace
    original = worker.enqueue(question(), START)
    infer = worker.transport.infer

    def replace_then_answer(*args):
        response = infer(*args)
        worker.transport.grant_id = "replacement-pilot-grant"
        return response

    worker.transport.infer = replace_then_answer
    assert not asyncio.run(worker.step(START))
    retained = worker.get(original["id"])
    assert retained["stage"] == "idea" and retained["status"] == "waiting"
    assert retained["attempts"][0]["status"] == "answered"
    assert not asyncio.run(worker.step(START + 31))
    assert worker.get(original["id"]) == retained
    assert len(worker.transport.calls) == 1


def test_grant_replaced_during_admission_never_reserves_an_attempt(workspace):
    worker, _, _ = workspace
    original = worker.enqueue(question(), START)
    admit = worker.transport.admit

    def replaced(role):
        profile = admit(role)
        worker.transport.grant_id = "replacement-pilot-grant"
        return profile

    worker.transport.admit = replaced
    assert not asyncio.run(worker.step(START))
    retained = worker.get(original["id"])
    assert retained["status"] == "waiting" and retained["stage"] == "idea"
    assert retained["attempts"] == [] and worker.transport.calls == []


def test_grant_removal_race_records_bounded_supervisor_wait(workspace):
    worker, _, _ = workspace

    def missing():
        raise OSError("Synthetic private pilot policy temporarily unavailable")

    worker.transport.policy = missing
    asyncio.run(worker._maintain("dependencies", worker.resume_sources))
    supervision = worker.registry.db.execute(
        "SELECT status,retry_at FROM role_supervision WHERE phase='dependencies'"
    ).fetchone()
    assert supervision["status"] == "waiting" and supervision["retry_at"] == START + 30
    assert worker.transport.calls == []
