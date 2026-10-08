"""Explicit next-method permission, with synthetic metadata and no model execution."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from test_peft_development import declared as declared
from test_peft_paper_pilot import pilot as pilot
from test_peft_pattern_learning import learning as learning
from test_peft_pattern_selection import select_pattern_grant

from trading.lab_role_contract import (
    PATTERN_METHOD_QUESTION_POLICY,
    PATTERN_METHODS,
    PATTERN_VERSION,
    contract_hash,
    pattern_method_policy_sha,
)
from trading.peft_profile import PROFILE, digest
from trading.peft_role_model import (
    PAPER_PILOT_PATTERN_METHOD_FORMAT,
    PATTERN_LEARNING_QUESTION_POLICY,
    PeftDevelopmentRoles,
    PeftPaperPilotRoles,
    local_role_transport,
)


@pytest.fixture
def methods(pilot):
    model, old, profile = select_pattern_grant(pilot)
    grant = old | {
        "format": PAPER_PILOT_PATTERN_METHOD_FORMAT,
        "grant_id": "fixture-pattern-method-8",
        "question_policy": PATTERN_METHOD_QUESTION_POLICY,
        "method_policy_sha256": pattern_method_policy_sha(),
    }
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    return model, grant, profile, old


def marked_packet(model):
    return {
        "contract": PATTERN_VERSION,
        "question": "Consider an independent mechanism using the retained original outcome.",
        "selection_authority": model.selection_authority(),
    }


def test_explicit_methods_keep_existing_profile_grammar_transport_and_resource_limits(
    methods, pilot
):
    model, grant, profile, old = methods
    original = model.policy_path.read_bytes()
    assert type(local_role_transport(model.policy_path.parent)) is PeftPaperPilotRoles
    assert len(grant) == len(old) + 1 == 11
    assert PATTERN_METHODS == {
        "p0": ("breakout-retest-v1", "cost-breakout-v1"),
        "p1": ("trend-pullback-v1", "cost-breakout-v1"),
    }
    assert contract_hash(PATTERN_VERSION) == (
        "29077a8b31cf5e287cff69024d1df513006245459ef6d746802c0ff8a7f67303"
    )
    assert model.role_contract == PATTERN_VERSION
    assert model.declaration()[2] == profile
    assert model.admit("researcher") == model.admit("reviewer") == profile
    assert all(profile[key] == value for key, value in PROFILE.items())
    assert profile == pilot[2].declaration()[2] | {
        "role_contract": PATTERN_VERSION,
        "contract_sha256": contract_hash(PATTERN_VERSION),
    }
    assert model.selection_authority() == {
        "question_policy": PATTERN_METHOD_QUESTION_POLICY,
        "grant_id": grant["grant_id"],
        "grant_sha": digest(grant),
        "profile_sha": digest(profile),
        "contract_version": PATTERN_VERSION,
        "contract_sha": contract_hash(PATTERN_VERSION),
        "method_policy_sha256": pattern_method_policy_sha(),
    }
    assert model.finite_test() is None
    with pytest.raises(ValueError, match="explicit finite grant"):
        with model.finite_operation({}):
            pytest.fail("Next-method permission cannot transfer finite authority")
    readiness = model.readiness()
    assert readiness["ready"] and readiness["experimental"]
    assert not readiness["qualified"] and not readiness["qualification_valid"]
    assert model.policy_path.read_bytes() == original


@pytest.mark.parametrize(
    "change",
    [
        {"method_policy_sha256": "0" * 64},
        {"method_policy_sha256": None},
        {"method_policy_sha256": True},
        {"question_policy": PATTERN_LEARNING_QUESTION_POLICY},
        {"role_contract": "reviewed-rule-role-v7"},
        {"format": "qtrades-peft-paper-pilot-v7"},
        {"finite_test": {}},
        {"extra": "permission"},
        {"enabled": 1},
    ],
)
def test_wrong_or_undeclared_method_permission_refuses_before_child(methods, monkeypatch, change):
    model, grant, profile, _ = methods
    packet = marked_packet(model)
    model.policy_path.write_text(json.dumps(grant | change), encoding="utf-8")
    original = model.policy_path.read_bytes()
    execute, child = Mock(), Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    assert not model.readiness()["ready"]
    with pytest.raises(ValueError, match="grant"):
        model.selection_authority()
    with pytest.raises(ValueError):
        model.infer("researcher", packet, profile)
    assert model.policy_path.read_bytes() == original
    execute.assert_not_called()
    child.assert_not_called()


@pytest.mark.parametrize("key", ["question_policy", "role_contract", "method_policy_sha256"])
def test_method_permission_is_never_implicitly_supplied(methods, key):
    model, grant, *_ = methods
    del grant[key]
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(ValueError, match="grant"):
        model.selection_authority()


@pytest.mark.parametrize("mutation", ["policy_sha", "authority_extra", "grant", "profile"])
def test_dispatch_requires_exact_full_method_authority(methods, monkeypatch, mutation):
    model, grant, profile, _ = methods
    packet = marked_packet(model)
    if mutation == "policy_sha":
        packet["selection_authority"]["method_policy_sha256"] = "0" * 64
    elif mutation == "authority_extra":
        packet["selection_authority"]["method_id"] = "p1"
    elif mutation == "grant":
        model.policy_path.write_text(json.dumps(grant | {"grant_id": "other"}), encoding="utf-8")
    else:
        profile = profile | {"seed": profile["seed"] + 1}
    execute = Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()


def test_missing_method_authority_refuses_both_preflight_and_captured_dispatch(
    methods, monkeypatch
):
    model, _, profile, _ = methods
    packet = marked_packet(model)
    del packet["selection_authority"]
    execute, preflight = Mock(), Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    monkeypatch.setattr(model, "preflight", preflight)
    with pytest.raises(ValueError, match="exact current v8 authority"):
        model.instance_preflight("researcher", packet, profile)
    with pytest.raises(ValueError, match="exact current v8 authority"):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()
    preflight.assert_not_called()


@pytest.mark.parametrize("old_version", [5, 7])
def test_grant_upgrade_after_preflight_cannot_dispatch_an_unmarked_packet(
    methods, monkeypatch, old_version
):
    model, grant, profile, old = methods
    if old_version == 7:
        old = old | {
            "format": "qtrades-peft-paper-pilot-v7",
            "question_policy": PATTERN_LEARNING_QUESTION_POLICY,
        }
    model.policy_path.write_text(json.dumps(old), encoding="utf-8")
    packet = {"contract": PATTERN_VERSION, "question": "Unmarked original request."}
    original_packet = deepcopy(packet)
    original = model.instance_preflight

    def switch_after_preflight(role, value, selected):
        if old_version == 5:
            original(role, value, selected)
        # Unmarked v7 already refuses in real preflight. Its case simulates a
        # skipped preflight to prove the independent captured-dispatch check.
        model.policy_path.write_text(json.dumps(grant), encoding="utf-8")

    monkeypatch.setattr(model, "instance_preflight", switch_after_preflight)
    execute, child = Mock(), Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    with pytest.raises(ValueError, match="exact current v8 authority"):
        model.infer("researcher", packet, profile)
    assert packet == original_packet
    execute.assert_not_called()
    child.assert_not_called()
    assert model._request_lock.acquire(blocking=False)
    model._request_lock.release()


def test_current_method_table_change_invalidates_original_grant(methods, monkeypatch):
    model, _, profile, _ = methods
    packet = marked_packet(model)
    monkeypatch.setitem(PATTERN_METHODS, "p1", ("vwap-reclaim-v1", "cost-breakout-v1"))
    execute = Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="grant"):
        model.selection_authority()
    with pytest.raises(ValueError):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()


def test_exact_method_dispatch_uses_existing_owner_and_pause_remains_latched(methods, monkeypatch):
    model, _, profile, _ = methods
    packet = marked_packet(model)
    answer = {"decision": "wait", "reason": "The prior outcome does not support this hypothesis."}
    execute = Mock(return_value=answer)
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    assert model.infer("researcher", packet, profile) is answer
    execute.assert_called_once_with("researcher", packet, profile)
    model.cancel()
    with pytest.raises(ValueError, match="paused or cancelled"):
        model.infer("researcher", packet, profile)
    assert execute.call_count == 1


def test_method_grant_change_during_dispatch_retains_existing_guard(methods, monkeypatch):
    model, grant, profile, _ = methods
    packet = marked_packet(model)

    def execute(*args):
        model.policy_path.write_text(
            json.dumps(grant | {"grant_id": "changed-during-dispatch"}), encoding="utf-8"
        )
        return model._paper_guard("during_inference")

    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="paper_pilot_grant_changed"):
        model.infer("researcher", packet, profile)
    assert not model._pilot_active
    assert model._request_lock.acquire(blocking=False)
    model._request_lock.release()


def test_previous_learning_grant_and_packet_are_not_upgraded(methods, learning, monkeypatch):
    model, _, profile, _ = methods
    _, old, _, _ = learning
    model.policy_path.write_text(json.dumps(old), encoding="utf-8")
    packet = marked_packet(model)
    assert len(packet["selection_authority"]) == 6
    assert packet["selection_authority"]["question_policy"] == PATTERN_LEARNING_QUESTION_POLICY
    assert "method_policy_sha256" not in packet["selection_authority"]
    assert model.declaration()[2] == profile
    grant = old | {"method_policy_sha256": pattern_method_policy_sha()}
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    execute = Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="grant"):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()
