"""Real API/registry controls with synthetic transports; no inference or activation."""

import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_paper_pilot_worker import workspace as workspace

from trading.api import create_app
from trading.config import Settings
from trading.local_role_model import LocalRoles


class ControlledPilot:
    paper_pilot = True

    def __init__(self):
        self.grant = {
            "enabled": True,
            "grant_id": "synthetic-ui-grant",
            "profile_sha256": "synthetic-ui-profile",
        }
        self.revoked = False
        self.protected = True
        self.controls = []

    def policy(self):
        if self.revoked:
            raise ValueError("Approved pilot grant was revoked; nothing resumed")
        return copy.deepcopy(self.grant)

    def can_research(self):
        return not self.revoked and self.grant["enabled"] and self.protected

    def readiness(self):
        return {
            "ready": self.can_research(),
            "qualified": False,
            "model": "Synthetic API fixture; no model execution",
            "profile": {"digest": self.grant["profile_sha256"]},
            "reason": "Approved pilot grant revoked" if self.revoked else None,
        }

    def set_enabled(self, enabled):
        if enabled:
            self.policy()
            if not self.protected:
                raise ValueError("Protected financial admission refused")
        self.controls.append(enabled)
        self.grant["enabled"] = enabled


def test_lifespan_selects_pilot_owner_and_keeps_shared_admission_closed(tmp_path, monkeypatch):
    pilot = ControlledPilot()
    monkeypatch.setattr("trading.api.PeftPaperPilotRoles", ControlledPilot)
    monkeypatch.setattr("trading.api.local_role_transport", lambda directory: pilot)
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        worker = app.state.lab.roles
        assert worker.transport is pilot and worker.activation() is True
        assert worker.paper_admission() is True
        assert app.state.lab.can_research() is False
        result = client.get("/api/lab/roles").json()
        assert result["paper_pilot"] is True and result["experimental"] is True
        assert result["readiness"]["qualified"] is False
        assert result["readiness"]["operating_admission"]["state"] == "unavailable"
        assert result["readiness"]["ready"] is False
        assert result["history"]["retained"] == 0


def test_default_lifespan_preserves_disabled_existing_transport(tmp_path):
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        assert isinstance(app.state.lab.roles.transport, LocalRoles)
        result = client.get("/api/lab/roles").json()
        assert not result["paper_pilot"] and not result["enabled"]
        assert app.state.lab.roles.paper_admission is None
        response = client.post(
            "/api/lab/roles/control",
            json={"action": "resume"},
            headers={"X-Local-Operator": "1"},
        )
        assert response.status_code == 409
        assert not (tmp_path / "role-policy.json").exists()


@pytest.mark.parametrize("body", ["{", " " * 16385], ids=["malformed", "oversize"])
def test_optional_invalid_pilot_policy_keeps_actual_api_startup_queryable(
    tmp_path, monkeypatch, body
):
    path = tmp_path / "role-policy.json"
    path.write_text(body, encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(
        "trading.peft_role_model.subprocess.Popen",
        lambda *a, **k: pytest.fail("Unready optional policy cannot launch a child"),
    )
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        response = client.get("/api/lab/roles")
        assert response.status_code == 200
        state = response.json()
        assert state["paper_pilot"] is True and state["enabled"] is False
        assert state["readiness"]["ready"] is False
        assert state["readiness"]["qualified"] is False
        assert state["readiness"]["stages"]["policy"]["state"] == "unavailable"
        assert "configured_enabled" not in state["readiness"]
        assert state["current_task"] is None and state["history"]["retained"] == 0
        assert path.read_bytes() == before


@pytest.fixture
def api(workspace):
    worker, _, folder = workspace
    pilot = ControlledPilot()
    worker.transport = pilot
    worker.activation = lambda: bool(pilot.policy().get("enabled", False))
    worker.paper_admission = pilot.can_research
    app = create_app(Settings(), folder / "api-monitor.sqlite", background=False)
    with TestClient(app) as client:
        app.state.lab = SimpleNamespace(roles=worker)
        yield client, worker, pilot


@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        ({}, {"action": "pause"}, 403),
        ({"X-Local-Operator": "1", "Origin": "http://other.example"}, {"action": "pause"}, 403),
        ({"X-Local-Operator": "1", "Origin": "https://testserver"}, {"action": "pause"}, 403),
        ({"X-Local-Operator": "1"}, {"action": "activate"}, 422),
        ({"X-Local-Operator": "1"}, {"action": "resume", "paper_pilot": {}}, 422),
        ({"X-Local-Operator": "1", "Authorization": "Bearer actor"}, {"action": "pause"}, 403),
    ],
)
def test_control_rejects_foreign_or_expanded_authority_before_mutation(api, headers, body, status):
    client, worker, pilot = api
    before = worker.registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0]
    response = client.post("/api/lab/roles/control", json=body, headers=headers)
    assert response.status_code == status
    assert pilot.controls == [] and pilot.grant["enabled"] is True
    assert worker.registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == before


def test_pause_resume_preserve_identity_and_revocation_blocks_resume(api):
    client, worker, pilot = api
    headers = {"X-Local-Operator": "1", "Origin": "http://testserver"}
    baseline = copy.deepcopy(worker.controller.paper.state)
    pilot.protected = False
    response = client.post("/api/lab/roles/control", json={"action": "pause"}, headers=headers)
    assert response.status_code == 200 and pilot.grant["enabled"] is False
    response = client.post("/api/lab/roles/control", json={"action": "resume"}, headers=headers)
    assert response.status_code == 409 and "Protected" in response.json()["detail"]
    pilot.protected = True
    response = client.post("/api/lab/roles/control", json={"action": "resume"}, headers=headers)
    assert response.status_code == 200 and pilot.grant["enabled"] is True
    pilot.revoked = True
    assert (
        client.post(
            "/api/lab/roles/control",
            json={"action": "resume"},
            headers=headers,
        ).status_code
        == 409
    )
    assert pilot.grant["profile_sha256"] == "synthetic-ui-profile"
    assert worker.controller.paper.state == baseline
    assert worker.registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 0


def test_real_question_api_retains_same_intent_and_reopens_pilot_context(api):
    client, worker, pilot = api
    body = {
        "question": "Is there enough closed-bar evidence for a reviewed paper comparison?",
        "horizon": "short",
        "parent": None,
        "request_id": "pilot-ui-api-1",
    }
    headers = {"X-Local-Operator": "1"}
    first = client.post("/api/lab/roles/questions", json=body, headers=headers)
    assert first.status_code == 200
    task = first.json()
    assert task["context"]["execution_mode"] == "paper_research_pilot"
    assert task["context"]["pilot_grant_id"] == "synthetic-ui-grant"
    assert task["context"]["qualified"] is False and "knowledge" not in task["context"]
    pilot.grant["enabled"] = False
    second = client.post("/api/lab/roles/questions", json=body, headers=headers)
    assert second.status_code == 200 and second.json()["id"] == task["id"]
    assert client.get("/api/lab/roles/tasks/" + task["id"]).json() == second.json()
    assert client.get("/api/lab/roles").json()["history"]["retained"] == 1
    assert worker.registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 0


def test_control_io_error_retains_unknown_acknowledgment(api, monkeypatch):
    client, _, pilot = api

    def fail(enabled):
        raise OSError("Synthetic storage failure")

    monkeypatch.setattr(pilot, "set_enabled", fail)
    response = client.post(
        "/api/lab/roles/control",
        json={"action": "pause"},
        headers={"X-Local-Operator": "1"},
    )
    assert response.status_code == 503 and "refresh" in response.json()["detail"]
    assert pilot.grant["enabled"] is True


def test_committed_control_with_unavailable_page_retains_unknown_acknowledgment(api, monkeypatch):
    client, worker, pilot = api

    def fail():
        raise OSError("Synthetic post-commit page failure")

    monkeypatch.setattr(worker, "page", fail)
    response = client.post(
        "/api/lab/roles/control",
        json={"action": "pause"},
        headers={"X-Local-Operator": "1"},
    )
    assert response.status_code == 503 and "saved" in response.json()["detail"]
    assert pilot.grant["enabled"] is False and pilot.controls == [False]
