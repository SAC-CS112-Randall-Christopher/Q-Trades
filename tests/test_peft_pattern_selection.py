"""Explicit native-pattern authority fixtures; no real model or operating calls."""

import json
from unittest.mock import Mock

import pytest
from test_peft_development import declared as declared
from test_peft_paper_pilot import pilot as pilot
from test_peft_question_selection import select_question_grant
from test_role_tool_transport import select_tool_grant

from trading.lab_role_contract import (
    CAPABILITY_VERSION,
    PATTERN_VERSION,
    TOOL_REQUEST_VERSION,
    VERSION,
    contract_hash,
)
from trading.peft_profile import PROFILE, digest
from trading.peft_role_model import (
    PAPER_PILOT_PATTERN_FORMAT,
    PATTERN_QUESTION_POLICY,
    PeftDevelopmentRoles,
    PeftPaperPilotRoles,
    local_role_transport,
)


def select_pattern_grant(pilot):
    model, old, profile = select_tool_grant(pilot, PATTERN_VERSION)
    grant = old | {
        "format": PAPER_PILOT_PATTERN_FORMAT,
        "grant_id": "fixture-native-patterns-5",
        "question_policy": PATTERN_QUESTION_POLICY,
    }
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    return model, grant, profile


def marked_packet(model):
    return {
        "contract": PATTERN_VERSION,
        "question": "Saved native finding motivates one fixed prospective comparison.",
        "selection_authority": model.selection_authority(),
    }


def test_v5_requires_explicit_bound_profile_and_preserves_resources(pilot):
    original = pilot[2].declaration()[2]
    model, grant, profile = select_pattern_grant(pilot)
    assert type(local_role_transport(model.directory)) is PeftPaperPilotRoles
    assert model.role_contract == PATTERN_VERSION
    assert model.admit("researcher") == profile
    assert profile == original | {
        "role_contract": PATTERN_VERSION,
        "contract_sha256": contract_hash(PATTERN_VERSION),
    }
    assert all(profile[key] == value for key, value in PROFILE.items())
    authority = model.selection_authority()
    assert authority == {
        "question_policy": PATTERN_QUESTION_POLICY,
        "grant_id": grant["grant_id"],
        "grant_sha": digest(grant),
        "profile_sha": digest(profile),
        "contract_version": PATTERN_VERSION,
        "contract_sha": contract_hash(PATTERN_VERSION),
    }
    authority["grant_id"] = "mutated caller copy"
    assert model.selection_authority()["grant_id"] == grant["grant_id"]
    assert "development_directory" not in authority
    readiness = model.readiness()
    assert readiness["ready"] and readiness["experimental"]
    assert not readiness["qualified"] and not readiness["qualification_valid"]


@pytest.mark.parametrize("version", [VERSION, TOOL_REQUEST_VERSION, CAPABILITY_VERSION, "v4"])
def test_old_grants_cannot_admit_v8_before_any_model_call(pilot, monkeypatch, version):
    model, _, profile = select_pattern_grant(pilot)
    packet = marked_packet(model)
    if version == VERSION:
        model.policy_path.write_text(json.dumps(pilot[1]), encoding="utf-8")
    elif version == "v4":
        select_question_grant(pilot)
    else:
        select_tool_grant(pilot, version)
    child, execute = Mock(), Mock()
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    before = model.policy_path.read_bytes()
    with pytest.raises(ValueError):
        model.instance_preflight("researcher", packet, profile)
    with pytest.raises(ValueError):
        model.infer("researcher", packet, profile)
    assert model.policy_path.read_bytes() == before
    child.assert_not_called()
    execute.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"question_policy": "evidence-question-selection-v1"},
        {"question_policy": None},
        {"role_contract": CAPABILITY_VERSION},
        {"format": "qtrades-peft-paper-pilot-v4"},
        {"profile_sha256": "0" * 64},
        {"enabled": False},
    ],
)
def test_changed_v5_authority_refuses_before_dispatch(pilot, monkeypatch, change):
    model, grant, profile = select_pattern_grant(pilot)
    packet = marked_packet(model)
    model.policy_path.write_text(json.dumps(grant | change), encoding="utf-8")
    child, execute = Mock(), Mock()
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError):
        model.infer("researcher", packet, profile)
    child.assert_not_called()
    execute.assert_not_called()


def test_exact_v5_dispatch_uses_existing_transport_and_v4_authority_stays_identical(
    pilot, monkeypatch
):
    model, old_grant, old_profile = select_question_grant(pilot)
    old_authority = model.selection_authority()
    model, grant, profile = select_pattern_grant(pilot)
    packet = marked_packet(model)
    execute = Mock(return_value={"decision": "wait", "reason": "Retain missing inputs."})
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    assert model.infer("researcher", packet, profile)["decision"] == "wait"
    execute.assert_called_once()
    assert execute.call_args.args == ("researcher", packet, profile)
    model.policy_path.write_text(json.dumps(old_grant), encoding="utf-8")
    assert model.selection_authority() == old_authority
    assert model.declaration()[2] == old_profile
    assert grant["profile_sha256"] != old_grant["profile_sha256"]
