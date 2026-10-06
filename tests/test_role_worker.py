"""Disposable orchestration proof; model stubs are never role qualification."""

import asyncio
import copy
import threading

import pytest
from test_autonomous_lab import close_window, tick_lab
from test_autonomous_lab import make_lab as base_lab
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_research_storage import plan_at

from trading.evidence_runtime import EvidenceRecorder
from trading.lab_role_contract import TOOL_REQUEST_VERSION, VERSION, validate
from trading.research_storage import save_plan
from trading.role_worker import Question, RoleWorker


def make_lab(store, directory, **policy):
    lab = base_lab(store, directory, **policy)
    lab.paper.state = store.transact(
        START, lambda e: e.state.update(evidence_kind="synthetic-role-software-fixture")
    )
    return lab


class ModelStub:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.slow = False

    def admit(self, role):
        return {
            "timeout_seconds": 5,
            "hourly_wall_seconds": 60,
            "hourly_tokens": 65536,
            "token_allowance": 8192,
        }

    def readiness(self):
        return {"qualified": False, "scope": "Disposable orchestration stub only"}

    def infer(self, role, packet, profile):
        self.calls.append(role)
        if self.slow:
            self.entered.set()
            assert self.release.wait(5)
        if role == "reviewer":
            assert "inputs" not in packet["evidence"]["e1"]
            answer = {
                "action": "exploratory_paper_only",
                "evidence_ids": ["e0", "e1"],
                "issues": [],
                "rationale": "The supported method permits only a prospective paper comparison.",
            }
        else:
            followup = "e1" in packet["evidence"]
            answer = {
                "action": "no_change" if followup else "propose_experiment",
                "evidence_ids": ["e1"] if followup else ["e0"],
                "capability": None if followup else "r0",
                "mechanism": "Compare the reviewed baseline using identical costs.",
                "falsification": "Reject unsupported benefit in the matched subsequent outcome.",
                "rationale": "This is one uncertain comparison and cannot qualify an incumbent.",
                "dependency": None,
            }
            if getattr(self, "role_contract", VERSION) == TOOL_REQUEST_VERSION:
                answer.update(unsupported_basis=None, tool_request=None)
                if followup and getattr(self, "request_tool_after_outcome", False):
                    answer.update(
                        action="request_tool",
                        tool_request={
                            "kind": "analysis_tool",
                            "identifier": "matched_regime_comparison",
                            "purpose": (
                                "Compare the retained negative result across causal regimes."
                            ),
                            "required_inputs": ["The original matched comparison outcome"],
                            "acceptance_checks": [
                                "Retain contrary and inconclusive after-cost results."
                            ],
                        },
                    )
        return {"answer": answer, "scope": "Synthetic software stub; no actual model inference"}


@pytest.mark.parametrize(
    "contract_version,request_tool_after_outcome",
    [(VERSION, False), (TOOL_REQUEST_VERSION, False), (TOOL_REQUEST_VERSION, True)],
)
def test_worker_ordinary_inbox_outcome_and_supported_followup(
    pg_store, tmp_path, monkeypatch, contract_version, request_tool_after_outcome
):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    save_plan(tmp_path, plan_at(tmp_path))
    recorder = EvidenceRecorder(tmp_path / "research-evidence.sqlite")
    recorder.enqueue({"kind": "wire", "at": START, "source": "synthetic-role-lifecycle"})
    asyncio.run(recorder.flush())
    model = ModelStub()
    model.role_contract = contract_version
    model.request_tool_after_outcome = request_tool_after_outcome
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    original = copy.deepcopy(lab.paper.state["accounts"]["primary"])
    question = Question(question="Does the reviewed matched baseline reproduce its cost behavior?")
    task = worker.enqueue(question, START)
    assert worker.enqueue(question, START + 1)["id"] == task["id"]
    for _ in range(5):
        assert asyncio.run(worker.step(START))
    assert worker.get(task["id"])["stage"] == "outcome"
    # Existing controller reserves/funds through its sole writer, with no manual SQL.
    for i in range(1, 5):
        tick_lab(lab, START + i * 2)
        lab.step(START + i * 2)
    trial = next(
        (
            t
            for t in lab.paper.state["autonomous_lab"]["trials"].values()
            if t["proposal_id"] == "role-proposal-" + task["id"][5:]
        ),
        None,
    )
    assert trial is not None, {
        "lab": lab.paper.state["autonomous_lab"]["reason"],
        "inbox": lab.inbox.page(),
        "task": worker.get(task["id"])["result"],
    }
    assert trial["status"] == "active"
    assert {
        k: v for k, v in lab.paper.state["accounts"]["primary"].items() if k != "valuation_at"
    } == {k: v for k, v in original.items() if k != "valuation_at"}
    score = close_window(lab, trial, "inconclusive")
    assert asyncio.run(worker.step(score["available_at"] + 1))
    assert asyncio.run(worker.step(score["available_at"] + 2))
    result = worker.get(task["id"])
    assert result["result"]["outcome"]["body"] == score
    if request_tool_after_outcome:
        assert result["stage"] == "tool_wait" and result["status"] == "waiting"
        assert result["result"]["tool_request"]["identifier"] == "matched_regime_comparison"
        assert not asyncio.run(worker.step(score["available_at"] + 3))
        assert worker.get(task["id"])["result"]["outcome"]["body"] == score
    else:
        assert result["status"] == "done"
        assert result["result"]["followup"]["action"] == "no_change"
    assert model.calls == ["researcher", "reviewer", "researcher"]
    assert len(result["attempts"]) == 3 and store.reconcile()["balanced"]
    # Training export uses the actual retained input/answer, not a regenerated packet.
    before_export = copy.deepcopy(store.read())
    if contract_version == TOOL_REQUEST_VERSION:
        with pytest.raises(ValueError, match="different role contract"):
            worker.training_candidate(task["id"], "followup", 1)
        assert store.read() == before_export and len(model.calls) == 3
        lab.registry.close()
        return  # New research inputs do not silently change teaching/dataset eligibility.
    candidate = worker.training_candidate(task["id"], "followup", 1)
    assert candidate["review"] is None and candidate["target"] is None
    assert candidate["candidate"]["original_answer"]["action"] == "no_change"
    assert candidate["candidate"]["packet"]["evidence"]["e1"]
    assert store.read() == before_export and len(model.calls) == 3
    assert (
        lab.registry.db.execute(
            "SELECT count(*) FROM evidence_windows WHERE origin='role outcome disclosure'"
        ).fetchone()[0]
        == 1
    )
    lab.registry.close()


def test_slow_model_releases_financial_and_registry_locks(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    model = ModelStub()
    model.slow = True
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    worker.enqueue(Question(question="Investigate a supported prospective rule comparison."), START)

    async def check():
        pending = asyncio.create_task(worker.step(START))
        assert await asyncio.to_thread(model.entered.wait, 5)
        tick_lab(lab, START + 2)
        assert lab.paper.state["last_tick"] == START + 2 and not pending.done()
        with lab.registry.transaction():
            lab.registry.event("other-research", "continued_while_inference", {})
        model.release.set()
        assert await pending

    asyncio.run(check())
    assert store.reconcile()["balanced"]
    lab.registry.close()


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "Change the stop to 99 ATR even though only the entry capability is offered.",
        "Charge zero maker fees for all crossing fills and use a different cost control.",
        "Substitute a later book for the original tick and call it original-input reconciliation.",
    ],
)
def test_model_prose_cannot_replace_server_method_or_original_evidence(
    pg_store, tmp_path, monkeypatch, unsafe_text
):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    model = ModelStub()
    original_infer = model.infer

    def infer(role, packet, profile):
        result = original_infer(role, packet, profile)
        # Deliberately semantic-invalid but schema-valid software input. The model
        # is not qualified by acceptance of its prose into an archived proposal.
        result["answer"]["mechanism"] = unsafe_text
        result["answer"]["falsification"] = unsafe_text
        result["answer"]["rationale"] = unsafe_text
        return result

    model.infer = infer
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True  # Disposable stub only; no operating-model activation.
    task = worker.enqueue(
        Question(question="Test the issued method without financial overrides."), START
    )
    original_accounts = copy.deepcopy(lab.paper.state["accounts"])
    issued = worker.get(task["id"])["context"]
    expected = worker._capability(issued["catalog"]["r0"])
    assert asyncio.run(worker.step(START))
    result = worker.get(task["id"])
    assert result["stage"] == "evaluate"
    proposal = result["proposal"]
    for key, value in expected.items():
        assert proposal[key] == value
    assert proposal["evidence_bundle_sha256"] == issued["issued"]["sha256"]
    assert proposal["mechanism"] == unsafe_text  # Retained for review, never parsed as policy.
    assert lab.paper.state["accounts"] == original_accounts
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_lost_submission_ack_reconciles_stable_proposal_without_second_effect(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    worker = RoleWorker(lab.registry, lab, ModelStub())
    save_plan(tmp_path, plan_at(tmp_path))
    worker.enabled = True
    task = worker.enqueue(
        Question(question="Reproduce a reviewed ordinary matched paper trial."), START
    )
    for _ in range(4):
        assert asyncio.run(worker.step(START))
    submit = lab.submit

    def lost(*args, **kwargs):
        submit(*args, **kwargs)
        raise SystemExit("Injected crash after ordinary inbox commit")

    monkeypatch.setattr(lab, "submit", lost)
    with pytest.raises(SystemExit, match="inbox commit"):
        asyncio.run(worker.step(START))
    replacement = RoleWorker(lab.registry, lab, ModelStub())
    replacement.enabled = True
    # Advancing an explicit synthetic recovery clock expires the owned lease.
    assert asyncio.run(replacement.step(START + 631))
    assert replacement.get(task["id"])["stage"] == "outcome"
    assert lab.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 1
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_strict_capability_membership_and_contradictory_approval():
    packet = {"evidence": {"e0": {}}, "capabilities": {"r0": {}}}
    valid = {
        "action": "propose_experiment",
        "evidence_ids": ["e0"],
        "capability": "r0",
        "mechanism": "Test a supported reviewed method.",
        "falsification": "Reject unsupported matched outcomes.",
        "rationale": "The permitted rule supports only paper exploration.",
        "dependency": None,
    }
    for change in (
        {"evidence_ids": ["invented"]},
        {"capability": "ridge_to_breakout"},
        {"starting_cash": "1000"},
        {"risk": "unlimited"},
    ):
        with pytest.raises(ValueError):
            validate("researcher", valid | change, packet)
    with pytest.raises(ValueError, match="contradicts"):
        validate(
            "reviewer",
            {
                "action": "exploratory_paper_only",
                "evidence_ids": ["e0"],
                "issues": ["unequal_costs"],
                "rationale": "Different costs invalidate this comparison.",
            },
            packet,
        )


def test_disabled_worker_persists_specific_wait_without_attempts(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    worker = RoleWorker(lab.registry, lab)
    task = worker.enqueue(
        Question(question="Investigate the permitted evidence with a local model."), START
    )
    assert not asyncio.run(worker.step(START))
    result = worker.get(task["id"])
    assert result["status"] == "waiting" and "disabled" in result["reason"]
    assert result["attempts"] == []
    lab.registry.close()


def test_completed_answer_survives_crash_before_dispatch(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    model = ModelStub()
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    task = worker.enqueue(
        Question(question="Compare this supported causal research question."), START
    )
    update = worker._update

    def crash(*args, **kw):
        raise SystemExit("Injected crash after completed answer persistence")

    monkeypatch.setattr(worker, "_update", crash)
    with pytest.raises(SystemExit, match="answer persistence"):
        asyncio.run(worker.step(START))
    monkeypatch.setattr(worker, "_update", update)
    replacement = RoleWorker(lab.registry, lab, model)
    replacement.enabled = True
    assert asyncio.run(replacement.step(START + 631))
    assert replacement.get(task["id"])["stage"] == "evaluate"
    assert model.calls == ["researcher"]
    assert len(replacement.get(task["id"])["attempts"]) == 1
    lab.registry.close()


def test_operational_retry_retains_failed_allowance_and_cannot_retry_a_verdict(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    model = ModelStub()
    original = model.infer
    monkeypatch.setattr(
        model,
        "infer",
        lambda *args: (_ for _ in ()).throw(TimeoutError("Unknown model completion")),
    )
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    task = worker.enqueue(
        Question(question="Evaluate the supported reviewed paper capability."), START
    )
    assert not asyncio.run(worker.step(START))
    assert worker.get(task["id"])["status"] == "failed"
    assert not asyncio.run(worker.step(START + 100))  # Never an implicit request.
    worker.retry(task["id"])
    monkeypatch.setattr(model, "infer", original)
    assert asyncio.run(worker.step(START))
    attempts = worker.get(task["id"])["attempts"]
    assert len(attempts) == 2 and attempts[0]["reason"] == "Unknown model completion"
    assert sum(a["wall_reserved"] for a in attempts) == 10
    with pytest.raises(ValueError):
        worker.retry(task["id"])
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_unavailable_reviewer_and_allowance_waits_do_not_dispatch_or_starve(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    model = ModelStub()
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    admit = model.admit
    monkeypatch.setattr(model, "admit", lambda role: admit(role) | {"hourly_tokens": 8192})
    first = worker.enqueue(
        Question(question="Investigate the first supported reviewed mechanism."), START
    )
    second = worker.enqueue(
        Question(question="Investigate a different supported reviewed mechanism."), START
    )
    assert asyncio.run(worker.step(START))
    for _ in range(4):
        asyncio.run(worker.step(START))
        if worker.get(second["id"])["status"] == "waiting":
            break
    waiting = worker.get(second["id"])
    assert waiting["status"] == "waiting" and not waiting["attempts"]
    assert "allowance" in waiting["reason"]
    tick_lab(lab, START + 2)
    assert store.reconcile()["balanced"] and lab.paper.state["last_tick"] == START + 2
    assert worker.get(first["id"])["stage"] in {"evaluate", "archive_evaluation"}
    lab.registry.close()


def test_question_ack_reconciles_across_new_bar_and_changed_body_rejected(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path)
    worker = RoleWorker(lab.registry, lab)
    q = Question(
        question="Investigate a supported causal baseline comparison.",
        request_id="stable-question-request",
    )
    task = worker.enqueue(q, START)
    tick_lab(lab, START + 120)
    assert worker.enqueue(q, START + 120)["id"] == task["id"]
    with pytest.raises(ValueError, match="rewritten"):
        worker.enqueue(
            q.model_copy(
                update={"question": "A changed question under the same request identity."}
            ),
            START + 120,
        )
    distinct = worker.enqueue(q.model_copy(update={"request_id": None}), START + 120)
    assert distinct["id"] != task["id"]
    lab.registry.close()


def test_role_api_is_readonly_by_default_and_operator_mutations_are_scoped(tmp_path):
    from fastapi.testclient import TestClient

    from trading.api import create_app
    from trading.config import Settings

    with TestClient(
        create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    ) as client:
        status = client.get("/api/lab/roles").json()
        assert status["enabled"] is False and status["readiness"]["qualified"] is False
        body = {"question": "Investigate a supported scoped paper comparison."}
        assert client.post("/api/lab/roles/questions", json=body).status_code == 403
        assert (
            client.post(
                "/api/lab/roles/questions",
                json=body,
                headers={"X-Local-Operator": "1", "Origin": "http://untrusted.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/lab/roles/questions", json=body, headers={"X-Local-Operator": "1"}
            ).status_code
            == 409
        )
