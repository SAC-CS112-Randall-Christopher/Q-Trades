"""Retained tool requests through the actual worker/API; synthetic model callbacks only."""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_paper_pilot_worker import PilotFixture, question
from test_paper_pilot_worker import workspace as workspace

from trading.api import create_app
from trading.config import Settings
from trading.lab_role_contract import TOOL_REQUEST_VERSION, VERSION, contract_hash
from trading.role_worker import RoleWorker


class ToolFixture(PilotFixture):
    role_contract = TOOL_REQUEST_VERSION

    def __init__(self, answer=None):
        super().__init__(tokens=65536)
        self.answer = answer or {
            "action": "request_tool",
            "capability": None,
            "evidence_ids": ["e2"],
            "mechanism": "Compare the reviewed strategy across causal volatility regimes.",
            "falsification": (
                "Reject the proposed regime split if matched after-cost outcomes agree."
            ),
            "rationale": "Current eligibility facts cannot establish regime-specific benefit.",
            "dependency": None,
            "unsupported_basis": None,
            "tool_request": {
                "kind": "analysis_tool",
                "identifier": "matched_regime_comparison",
                "purpose": "Test whether the range mechanism changes across frozen regimes.",
                "required_inputs": ["Closed causal bars", "Matched executable costs"],
                "acceptance_checks": [
                    "Freeze regime thresholds using training-only inputs.",
                    "Retain negative and inconclusive matched after-cost outcomes.",
                ],
            },
        }

    def admit(self, role):
        return super().admit(role) | {
            "role_contract": TOOL_REQUEST_VERSION,
            "contract_sha256": contract_hash(contract_version=TOOL_REQUEST_VERSION),
        }

    def preflight(self, role, packet, profile):
        assert packet["contract"] == profile["role_contract"] == TOOL_REQUEST_VERSION

    def infer(self, role, packet, profile):
        self.calls.append((role, copy.deepcopy(packet)))
        return {
            "complete": True,
            "answer": copy.deepcopy(self.answer),
            "scope": "Synthetic callback; zero actual model requests",
        }


def test_request_reopens_through_api_and_restart_without_dispatch_or_financial_effect(workspace):
    worker, clock, directory = workspace
    model = ToolFixture()
    worker.transport = model
    before = copy.deepcopy(worker.controller.paper.state)
    task = worker.enqueue(question(), clock[0])
    assert worker.page()["activity"]["state"] == "queued"
    assert asyncio.run(worker.step(clock[0]))
    saved = worker.get(task["id"])
    assert saved["stage"] == "tool_wait" and saved["status"] == "waiting"
    assert saved["result"] == model.answer
    assert saved["proposal"] is None and saved["evaluation"] is None
    assert saved["attempts"][0]["status"] == "answered"
    assert json.loads(saved["attempts"][0]["response"])["answer"] == model.answer
    assert worker.enqueue(question(), clock[0] + 1)["id"] == saved["id"]
    assert not asyncio.run(worker.step(clock[0] + 2))
    assert worker.resume_sources() == 0
    assert worker.select_followups()["selected"] == 0
    reopened = RoleWorker(worker.registry, worker.controller, model)
    reopened.enabled = True
    reopened.paper_admission = lambda: True
    assert not asyncio.run(reopened.step(clock[0] + 3))
    assert reopened.get(saved["id"])["result"] == model.answer
    activity = reopened.page()["activity"]
    assert activity["state"] == "waiting" and activity["pending_tools"] == 1
    app = create_app(Settings(), directory / "api-monitor.sqlite", background=False)
    app.state.lab = SimpleNamespace(roles=reopened)
    client = TestClient(app)
    detail = client.get("/api/lab/roles/tasks/" + saved["id"])
    assert detail.status_code == 200 and detail.json()["result"] == model.answer
    assert client.get("/api/lab/roles").json()["activity"] == activity
    assert len(model.calls) == 1 and worker.controller.paper.state == before
    assert worker.registry.db.execute("SELECT count(*) FROM role_requests").fetchone()[0] == 1


def test_offered_family_denial_is_retained_invalid_without_tool_or_retry(workspace):
    worker, clock, _ = workspace
    model = ToolFixture()
    model.answer.update(
        action="unsupported_capability",
        tool_request=None,
        unsupported_basis={"kind": "strategy_family", "identifier": "range_reversion"},
    )
    worker.transport = model
    task = worker.enqueue(question(), clock[0])
    before = copy.deepcopy(worker.controller.paper.state)
    assert not asyncio.run(worker.step(clock[0]))
    saved = worker.get(task["id"])
    assert saved["status"] == "failed" and saved["stage"] == "idea"
    assert saved["result"] is None
    assert saved["attempts"][0]["status"] == "failed"
    assert json.loads(saved["attempts"][0]["response"])["answer"] == model.answer
    assert not asyncio.run(worker.step(clock[0] + 1))
    assert worker.page()["activity"]["state"] == "idle"
    assert len(model.calls) == 1 and worker.controller.paper.state == before


def test_incompatible_profile_refuses_before_attempt_or_allowance(workspace):
    worker, clock, _ = workspace
    model = ToolFixture()
    worker.transport = model
    task = worker.enqueue(question(), clock[0])

    def refuse(*args):
        raise ValueError("Tool-request packet requires a separately reviewed profile")

    model.preflight = refuse
    assert not asyncio.run(worker.step(clock[0]))
    saved = worker.get(task["id"])
    assert saved["status"] == "failed" and not saved["attempts"]
    assert not model.calls
    assert (
        worker.registry.db.execute("SELECT count(*) FROM role_attempt_allowances").fetchone()[0]
        == 0
    )


def test_activity_is_authoritative_and_scoped_to_current_grant(workspace):
    worker, clock, _ = workspace
    task = worker.enqueue(question(), clock[0])
    worker._update(task, "tool_wait", "waiting", reason="Synthetic retained tool request")
    assert worker.page()["activity"]["pending_tools"] == 1
    worker.transport.grant_id = "another-current-grant"
    assert worker.page()["activity"]["state"] == "idle"
    assert worker.page()["activity"]["pending_tools"] == 0
    worker.enabled = False
    assert worker.page()["activity"]["state"] == "paused"


def test_invalid_contract_shows_unavailable_without_adopting_retained_task(workspace):
    worker, clock, _ = workspace
    task = worker.enqueue(question(), clock[0])
    worker.transport.role_contract = "unreviewed-contract"
    state = worker.page()
    assert state["activity"]["state"] == "unavailable"
    assert state["contract"] is None
    assert worker.get(task["id"])["context"]["contract"] == VERSION
    view = worker.view(task["id"])
    assert view["contract_applicability"]["state"] == "unavailable"
    assert view["contract_applicability"]["selected_contract"] is None
    assert view["reason"] is None


@pytest.mark.parametrize("error", [OSError("Profile metadata unavailable"), KeyError("contract")])
def test_unreadable_current_contract_reopens_retained_history(workspace, monkeypatch, error):
    worker, clock, _ = workspace
    task = worker.enqueue(question(), clock[0])
    retained = copy.deepcopy(worker.get(task["id"]))

    def unavailable():
        raise error

    monkeypatch.setattr(worker, "_contract_version", unavailable)
    view = worker.view(task["id"])
    assert view["contract_applicability"]["state"] == "unavailable"
    assert view["contract_applicability"]["selected_contract"] is None
    assert view["reason"] == retained["reason"]
    assert worker.get(task["id"]) == retained


def test_version_switch_preserves_old_task_request_identity_and_current_selection(workspace):
    worker, clock, _ = workspace
    old = worker.enqueue(question(), clock[0])
    assert worker.view(old["id"])["contract_applicability"]["state"] == "matching"
    retained = copy.deepcopy(worker.get(old["id"]))
    worker.transport = ToolFixture()
    # Reconciliation of the same already-created intent must never create a new attempt.
    assert worker.enqueue(question(), clock[0])["id"] == old["id"]
    assert worker.page()["activity"]["state"] == "idle"
    assert not asyncio.run(worker.step(clock[0]))
    assert worker.get(old["id"])["status"] == "queued"
    view = worker.view(old["id"])
    assert view["contract_applicability"]["state"] == "different"
    assert "contract changed" in view["contract_applicability"]["reason"]
    assert view["reason"] is None and worker.get(old["id"]) == retained
    newer = worker.enqueue(question().model_copy(update={"request_id": None}), clock[0])
    assert newer["id"] != old["id"]
    assert newer["context"]["contract"] == TOOL_REQUEST_VERSION
    assert worker.page()["activity"]["queued"] == 1
    assert asyncio.run(worker.step(clock[0]))
    assert worker.get(newer["id"])["stage"] == "tool_wait"
    assert worker.get(old["id"])["status"] == "queued"
    assert len(worker.transport.calls) == 1
