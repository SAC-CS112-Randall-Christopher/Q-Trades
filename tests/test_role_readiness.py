"""Procedural readiness/recovery checks; no model calls or qualification claims."""

import json
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from test_local_roles import declared

from trading.api import create_app
from trading.config import Settings
from trading.experiment_registry import ExperimentRegistry
from trading.local_role_model import LocalRoles
from trading.role_worker import RoleWorker


def test_absent_policy_is_actionable_and_never_opens_runtime(tmp_path, monkeypatch):
    roles = LocalRoles(tmp_path)
    monkeypatch.setattr(roles, "observe", lambda p: pytest.fail("No undeclared runtime IO"))
    result = roles.readiness()
    assert result["enabled"] is False and result["qualified"] is False
    assert result["stages"]["policy"]["state"] == "absent"
    assert result["stages"]["runtime"]["state"] == "unverified"
    assert "exact approved" in result["stages"]["policy"]["next_action"]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("receipt_valid", [True, False])
def test_stopped_runtime_preserves_independent_qualification_and_identity(
    tmp_path, monkeypatch, receipt_valid
):
    (tmp_path / "role-policy.json").write_text(json.dumps(declared()))
    roles = LocalRoles(tmp_path)

    def qualification(role, profile):
        if not receipt_valid:
            raise ValueError("Incomplete current role qualification")

    def unavailable(profile):
        raise httpx.ConnectError("Dedicated CPU listener stopped")

    monkeypatch.setattr(roles, "qualification", qualification)
    monkeypatch.setattr(roles, "observe", unavailable)
    result = roles.readiness()
    assert result["qualified"] is False and result["enabled"] is False
    assert result["model"] == "qwen3.5:4b"
    assert all(r["qualified"] == receipt_valid for r in result["roles"].values())
    assert result["stages"]["runtime"]["state"] == "unavailable"
    assert result["stages"]["qualification"]["state"] == (
        "qualified" if receipt_valid else "unqualified"
    )


def test_runtime_mismatch_is_not_a_semantic_model_failure(tmp_path, monkeypatch):
    (tmp_path / "role-policy.json").write_text(json.dumps(declared()))
    roles = LocalRoles(tmp_path)

    def mismatch(profile):
        raise ValueError("Approved model digest changed; qualification stale")

    monkeypatch.setattr(roles, "observe", mismatch)
    result = roles.readiness()
    assert result["stages"]["runtime"]["state"] == "mismatch"
    assert result["stages"]["qualification"]["state"] == "unqualified"
    assert result["profile"]["model_digest"] == "synthetic-digest"


@pytest.mark.parametrize(
    ("running", "age", "error", "constrained", "expected"),
    [
        (False, 0, None, False, "unavailable"),
        (True, 0, "fault", False, "unhealthy"),
        (True, 11, None, False, "stale"),
        (True, 0, None, True, "refused"),
        (True, 0, None, False, "available"),
    ],
)
def test_normal_api_exposes_guard_without_inference_or_activation(
    tmp_path, running, age, error, constrained, expected
):
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    paper = SimpleNamespace(
        running=running,
        error=error,
        state={"last_tick": time.time() - age},
        constrained=lambda: constrained,
    )
    roles = RoleWorker(registry, SimpleNamespace(paper=paper), LocalRoles(tmp_path))
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    try:
        with TestClient(app) as client:
            app.state.lab = SimpleNamespace(roles=roles)
            result = client.get("/api/lab/roles").json()
            assert result["readiness"]["operating_admission"]["state"] == expected
            assert result["readiness"]["enabled"] is False
            assert result["history"]["retained"] == 0
            assert registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 0
    finally:
        registry.close()


def test_malformed_policy_reports_invalid_without_silent_activation(tmp_path):
    path = tmp_path / "role-policy.json"
    path.write_text('{"enabled":true,"model":"qtrades-crypto-researcher-4b-v2"}')
    before = path.read_bytes()
    result = LocalRoles(tmp_path).readiness()
    assert result["stages"]["policy"]["state"] == "invalid"
    assert result["enabled"] is False and result["qualified"] is False
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("qualified", "runtime", "enabled", "guarded", "ready"),
    [
        (True, "unavailable", False, False, False),
        (False, "verified", True, False, False),
        (True, "mismatch", True, False, False),
        (True, "verified", False, False, False),
        (True, "verified", True, True, False),
        (True, "verified", True, False, True),
    ],
)
def test_qualification_runtime_activation_and_admission_have_independent_meanings(
    tmp_path, monkeypatch, qualified, runtime, enabled, guarded, ready
):
    profile = declared()
    profile["enabled"] = enabled
    (tmp_path / "role-policy.json").write_text(json.dumps(profile))
    transport = LocalRoles(tmp_path)

    def qualification(role, profile):
        if not qualified:
            raise ValueError("Current receipt is invalid")

    def observe(profile):
        if runtime == "unavailable":
            raise httpx.ConnectError("Stopped dedicated listener")
        if runtime == "mismatch":
            raise ValueError("Profile drift")
        return {"fixture": "No actual model call"}

    monkeypatch.setattr(transport, "qualification", qualification)
    monkeypatch.setattr(transport, "observe", observe)
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    try:
        paper = SimpleNamespace(
            running=True, error=None, state={"last_tick": time.time()},
            constrained=lambda: guarded,
        )
        result = RoleWorker(registry, SimpleNamespace(paper=paper), transport).readiness()
        assert result["qualification_valid"] is qualified
        assert result["runtime_available"] is (runtime == "verified")
        assert result["ready"] is ready
        if qualified:
            assert "Complete current" not in result["stages"]["qualification"]["next_action"]
        if runtime == "verified":
            assert "Verify the owned" not in result["stages"]["runtime"]["next_action"]
        if enabled:
            assert "requires its separate" not in result["stages"]["activation"]["next_action"]
        assert registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[0] == 0
    finally:
        registry.close()
