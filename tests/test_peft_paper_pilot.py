"""Explicit paper-pilot authority fixtures; no model, services or database calls."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from unittest.mock import Mock

import httpx
import pytest
from test_development_latency_measurement import protected_status
from test_peft_development import declared as declared

from trading.local_role_model import LocalRoles, development_latency_observation
from trading.peft_profile import PROFILE, digest
from trading.peft_role_model import (
    PAPER_PILOT_FORMAT,
    PeftDevelopmentRoles,
    PeftPaperPilotRoles,
    local_role_transport,
)


@pytest.fixture
def pilot(declared, tmp_path, monkeypatch):
    development, candidate, source = declared
    directory = tmp_path / "operating"
    directory.mkdir()
    grant = {
        "format": PAPER_PILOT_FORMAT,
        "enabled": True,
        "grant_id": "fixture-paper-pilot-1",
        "development_directory": str(development.directory),
        "profile_sha256": digest(development.declaration()[2]),
        "roles": ["researcher", "reviewer"],
        "latency_admission": "advisory",
        "scope": "prospective-paper-only",
    }
    (directory / "role-policy.json").write_text(json.dumps(grant), encoding="utf-8")
    monkeypatch.setattr(
        "trading.peft_role_model.LocalRoles.development_latency_guard",
        lambda _: development_latency_observation(protected_status()),
    )
    return PeftPaperPilotRoles(directory), grant, development, candidate, source


def write_grant(pilot, **changed):
    model, grant, *_ = pilot
    updated = grant | changed
    model.policy_path.write_text(json.dumps(updated), encoding="utf-8")
    return updated


def test_default_factory_preserves_local_qualified_owner(tmp_path):
    assert type(local_role_transport(tmp_path)) is LocalRoles
    (tmp_path / "role-policy.json").write_text('{"enabled": false}', encoding="utf-8")
    assert type(local_role_transport(tmp_path)) is LocalRoles


@pytest.mark.parametrize("bad", ["malformed", "oversize", "unknown", "missing_pointer"])
def test_optional_bad_config_remains_queryable_without_startup_or_child_failure(pilot, bad):
    model, grant, *_ = pilot
    if bad == "malformed":
        model.policy_path.write_text("{", encoding="utf-8")
    elif bad == "oversize":
        model.policy_path.write_text(" " * 16385, encoding="utf-8")
    else:
        write_grant(
            pilot,
            **(
                {"format": "unknown"}
                if bad == "unknown"
                else {"development_directory": str(model.policy_path.parent / "offline")}
            ),
        )
    optional = local_role_transport(model.policy_path.parent)
    assert isinstance(optional, PeftPaperPilotRoles)
    ready = optional.readiness()
    assert not ready["ready"] and not ready["enabled"] and not ready["qualified"]
    assert "configured_enabled" not in ready
    assert ready["stages"]["policy"]["state"] == "unavailable"
    assert optional.can_research() is False
    assert grant["enabled"] is True


def test_redirected_policy_validation_is_lazy_and_optional(pilot, monkeypatch):
    model, *_ = pilot
    from trading.peft_role_model import regular

    def refuse_policy(path):
        if path.name == "role-policy.json":
            raise ValueError("Serving refuses redirected private paths")
        return regular(path)

    monkeypatch.setattr("trading.peft_role_model.regular", refuse_policy)
    optional = local_role_transport(model.policy_path.parent)
    assert isinstance(optional, PeftPaperPilotRoles)
    assert optional.readiness()["stages"]["policy"]["state"] == "unavailable"


def test_exact_profile_and_unqualified_pilot_are_distinct_from_development(pilot):
    model, grant, development, *_ = pilot
    assert isinstance(local_role_transport(model.policy_path.parent), PeftPaperPilotRoles)
    original = development.declaration()[2]
    for role in ("researcher", "reviewer"):
        assert model.admit(role) == original
    assert digest(original) == grant["profile_sha256"] and original["development_only"]
    ready = model.readiness()
    assert ready["ready"] and ready["enabled"] and ready["configured_enabled"]
    assert ready["experimental"] and not ready["qualified"] and not ready["qualification_valid"]
    assert ready["profile"] == original and ready["grant_id"] == grant["grant_id"]
    assert ready["stages"]["qualification"]["state"] == "unqualified"
    with pytest.raises(ValueError, match="Unsupported"):
        model.admit("external_reviewer")
    with pytest.raises(ValueError, match="reinterpret"):
        model.development_admit("researcher")


@pytest.mark.parametrize(
    "phase", ["admission", "before_dispatch", "during_inference", "after_response"]
)
def test_every_pilot_guard_observes_severe_latency_without_hidden_default_veto(
    pilot, monkeypatch, phase
):
    model, *_ = pilot
    strict = Mock(side_effect=ValueError("Default latency veto remains closed"))
    monkeypatch.setattr("trading.peft_role_model.LocalRoles.paper_guard", strict)
    observed = model._paper_guard(phase)
    assert observed["admitted"] and observed["research_constrained"]
    assert observed["effective_latency_block_removed"]
    assert observed["resource_guard"]["last_trigger"]["sample"]["elapsed_ms"] == 1403
    strict.assert_not_called()


@pytest.mark.parametrize("condition", ["imbalance", "stale", "recording", "unknown", "memory"])
def test_nonlatency_protection_refuses_before_any_child(pilot, monkeypatch, condition):
    model, *_ = pilot
    status = protected_status()
    if condition == "imbalance":
        status["paper"]["journal"]["balanced"] = False
    elif condition == "stale":
        status["paper"]["stale"] = True
    elif condition == "recording":
        status["paper"]["research_evidence"]["state"] = "paused"
    elif condition == "unknown":
        status["paper"]["performance"]["resource_guard"]["blocking_conditions"] = ["unknown"]
    else:
        monkeypatch.setattr("trading.peft_role_model.available_memory", lambda: 31 * 1024**3)
    monkeypatch.setattr(
        "trading.peft_role_model.LocalRoles.development_latency_guard",
        lambda _: development_latency_observation(status),
    )
    child = Mock()
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    assert not model.can_research() and not model.readiness()["ready"]
    with pytest.raises(ValueError, match="Protected"):
        model.admit("researcher")
    with pytest.raises(ValueError, match="Protected"):
        model.infer("researcher", {"question": "fixture"}, model.declaration()[2])
    child.assert_not_called()


@pytest.mark.parametrize("error", [httpx.ReadTimeout("fixture"), httpx.ConnectError("fixture")])
def test_unavailable_status_remains_queryable_and_refuses_resume_or_dispatch(
    pilot, monkeypatch, error
):
    model, *_ = pilot
    unavailable = Mock(side_effect=error)
    monkeypatch.setattr("trading.peft_role_model.LocalRoles.development_latency_guard", unavailable)
    assert model.can_research() is False
    ready = model.readiness()
    assert ready["configured_enabled"] and ready["enabled"] and not ready["ready"]
    with pytest.raises(ValueError, match="observation_unavailable"):
        model.admit("researcher")
    assert model._pending_admission["observation_error_type"] == type(error).__name__
    model.set_enabled(False)
    assert model.readiness()["configured_enabled"] is False
    with pytest.raises(ValueError, match="Protected"):
        model.set_enabled(True)
    assert not model.policy()["enabled"]


@pytest.mark.parametrize("change", ["source", "candidate", "profile", "scope", "roles"])
def test_changed_frozen_identity_or_grant_scope_fails_closed(pilot, change):
    model, grant, _, candidate, source = pilot
    if change == "source":
        source.write_text("# changed fixture source", encoding="utf-8")
    elif change == "candidate":
        candidate.write_text("{}", encoding="utf-8")
    else:
        write_grant(
            pilot,
            **{
                "profile": {"profile_sha256": "0" * 64},
                "scope": {"scope": "financial-operator"},
                "roles": {"roles": ["researcher", "external_reviewer"]},
            }[change],
        )
    assert not model.can_research() and not model.readiness()["ready"]
    with pytest.raises(ValueError, match="authority_unavailable"):
        model.admit("researcher")
    assert grant["roles"] == ["researcher", "reviewer"]


@pytest.mark.parametrize(
    "addition",
    [
        {"knowledge": {}},
        {"retrieval_contract": None},
        {"evidence": {"e2": {"purpose": "performance_diagnostic"}}},
    ],
)
def test_unsupported_retrieval_and_diagnostic_inputs_never_reinterpret_pilot(pilot, addition):
    model, *_ = pilot
    with pytest.raises(ValueError, match="retrieval|outside paper research"):
        model.preflight("researcher", {"question": "fixture"} | addition, model.declaration()[2])


def test_cancel_before_dispatch_is_latched_until_explicit_protected_resume(pilot, monkeypatch):
    model, *_ = pilot
    profile = model.admit("researcher")
    child = Mock()
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    model.cancel()
    assert model.policy()["configured_enabled"] and not model.policy()["enabled"]
    with pytest.raises(ValueError, match="cancellation remains latched"):
        model.infer("researcher", {"question": "fixture"}, profile)
    child.assert_not_called()
    model.set_enabled(True)
    assert model.policy()["enabled"] and model.can_research()


def test_admission_grant_change_refuses_dispatch_without_consuming_original_authorization(
    pilot, monkeypatch
):
    model, _, development, *_ = pilot
    profile = model.admit("researcher")
    write_grant(pilot, grant_id="fixture-paper-pilot-2")
    execute = Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="between admission and dispatch"):
        model.infer("researcher", {"question": "fixture"}, profile)
    execute.assert_not_called()
    assert not development._latency_used and development._latency_authorization is None


def test_sequential_requests_reset_only_observations_and_retain_redacted_identity(
    pilot, monkeypatch, tmp_path
):
    model, grant, *_ = pilot
    profile = model.admit("researcher")
    observations = []

    def execute(self, role, packet, passed):
        assert passed == profile
        self._paper_guard("before_dispatch")
        self._guard_log = tmp_path / (packet["question"] + ".jsonl")
        self._paper_guard("during_inference")
        self._paper_guard("after_response")
        result = {"answer": {"action": "abstain"}, "complete": True} | self._guard_authority()
        observations.append(deepcopy(self.guard_observations()))
        return result

    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    for role, question in (("researcher", "first"), ("reviewer", "second")):
        model.admit(role)
        result = model.infer(role, {"question": question}, profile)
        assert result["paper_pilot_grant"]["sha256"] == digest(grant)
        assert grant["development_directory"] not in json.dumps(result)
        assert not model._pilot_active and model._guard_log is None
        assert len((tmp_path / (question + ".jsonl")).read_text().splitlines()) == 2
    assert len(observations) == 2 and all(len(items) == 4 for items in observations)
    assert model._latency_mode is False and model._latency_authorization is None


def test_same_owner_blocks_concurrency_pause_signals_cleanup_and_resume_is_explicit(
    pilot, monkeypatch
):
    model, *_ = pilot
    profile = model.admit("researcher")
    entered, finish = Event(), Event()

    def execute(self, *_):
        entered.set()
        assert finish.wait(5)
        assert self._cancelled.is_set()
        return {"complete": False}

    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(model.infer, "researcher", {"question": "fixture"}, profile)
        assert entered.wait(5)
        try:
            with pytest.raises(ValueError, match="already owns"):
                model.infer("reviewer", {"question": "other"}, profile)
            model.set_enabled(False)
            assert model.policy()["configured_enabled"] is False
            with pytest.raises(ValueError, match="still stopping"):
                model.set_enabled(True)
        finally:
            finish.set()
        assert active.result(timeout=5) == {"complete": False}
    assert not model.policy()["enabled"]
    model.set_enabled(True)
    assert model.policy()["enabled"]


def test_grant_replacement_during_owned_request_is_retained_and_refused(pilot, monkeypatch):
    model, *_ = pilot
    profile = model.admit("researcher")

    def execute(self, *_):
        write_grant(pilot, grant_id="fixture-paper-pilot-2")
        return self._paper_guard("during_inference")

    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="grant_changed"):
        model.infer("researcher", {"question": "fixture"}, profile)
    assert model.guard_observations()[-1]["reasons"] == ["paper_pilot_grant_changed"]
    assert not model._pilot_active


def test_cancel_pause_does_not_change_frozen_limits(pilot):
    model, *_ = pilot
    before = model.declaration()[2]
    model.set_enabled(False)
    model.set_enabled(True)
    assert model.declaration()[2] == before
    assert all(before[key] == value for key, value in PROFILE.items())


def test_control_write_lost_acknowledgment_remains_unknown_not_definitive_refusal(
    pilot, monkeypatch
):
    model, *_ = pilot
    original = model._grant
    calls = 0

    def grant():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("Fixture unreadable acknowledgment after actual replacement")
        return original()

    monkeypatch.setattr(model, "_grant", grant)
    with pytest.raises(OSError, match="acknowledgment unknown"):
        model.set_enabled(False)
    assert json.loads(model.policy_path.read_text())["enabled"] is False
    assert model._cancelled.is_set()
