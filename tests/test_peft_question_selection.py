"""Explicit question-production authority; synthetic declarations and no model calls."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from test_peft_development import declared as declared
from test_peft_paper_pilot import pilot as pilot
from test_role_tool_transport import select_tool_grant

from trading.lab_role_contract import (
    CAPABILITY_VERSION,
    TOOL_REQUEST_VERSION,
    VERSION,
    contract_hash,
)
from trading.peft_profile import PROFILE, digest
from trading.peft_role_model import (
    PAPER_PILOT_CAPABILITY_FORMAT,
    PAPER_PILOT_FORMAT,
    PAPER_PILOT_SELECTION_FORMAT,
    PAPER_PILOT_TOOL_FORMAT,
    QUESTION_SELECTION_POLICY,
    PeftDevelopmentRoles,
    PeftPaperPilotRoles,
    local_role_transport,
)


def select_question_grant(pilot):
    model, old, profile = select_tool_grant(pilot, CAPABILITY_VERSION)
    grant = old | {
        "format": PAPER_PILOT_SELECTION_FORMAT,
        "grant_id": "fixture-evidence-questions-4",
        "question_policy": QUESTION_SELECTION_POLICY,
    }
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    return model, grant, profile


def marked_packet(model):
    return {
        "contract": CAPABILITY_VERSION,
        "question": "Synthetic new causal evidence; keep original comparisons frozen.",
        "selection_authority": model.selection_authority(),
    }


@pytest.mark.parametrize("version", [VERSION, TOOL_REQUEST_VERSION, CAPABILITY_VERSION])
def test_existing_grants_have_no_automatic_question_permission(pilot, version):
    model, old, development, *_ = pilot
    if version != VERSION:
        model, old, _ = select_tool_grant(pilot, version)
    before = model.policy_path.read_bytes()
    assert model.selection_authority() is None
    assert model.policy_path.read_bytes() == before
    assert "question_policy" not in model.policy()
    original = development.declaration()[2]
    assert model.declaration()[2] == (
        original
        if version == VERSION
        else original | {"role_contract": version, "contract_sha256": contract_hash(version)}
    )
    assert len(old) == (8 if version == VERSION else 9)


def test_explicit_v4_binds_same_v7_profile_and_returns_detached_public_authority(pilot):
    original = pilot[2].declaration()[2]
    model, grant, profile = select_question_grant(pilot)
    assert len(grant) == 10
    assert type(local_role_transport(model.policy_path.parent)) is PeftPaperPilotRoles
    assert model.role_contract == CAPABILITY_VERSION
    assert model.admit("researcher") == profile
    authority = model.selection_authority()
    assert authority == {
        "question_policy": QUESTION_SELECTION_POLICY,
        "grant_id": grant["grant_id"],
        "grant_sha": digest(grant),
        "profile_sha": digest(profile),
        "contract_version": CAPABILITY_VERSION,
        "contract_sha": contract_hash(CAPABILITY_VERSION),
    }
    assert "development_directory" not in authority
    authority["grant_id"] = "caller-mutated-copy"
    assert model.selection_authority()["grant_id"] == grant["grant_id"]
    assert profile == original | {
        "role_contract": CAPABILITY_VERSION,
        "contract_sha256": contract_hash(CAPABILITY_VERSION),
    }
    for field, value in PROFILE.items():
        assert profile[field] == value
    ready = model.readiness()
    assert ready["ready"] and ready["experimental"] and not ready["qualified"]
    assert not ready["qualification_valid"]


@pytest.mark.parametrize(
    "change",
    [
        {"question_policy": None},
        {"question_policy": True},
        {"question_policy": "unreviewed-selection"},
        {"role_contract": VERSION},
        {"role_contract": TOOL_REQUEST_VERSION},
        {"format": PAPER_PILOT_CAPABILITY_FORMAT},
        {"extra": "permission"},
    ],
)
def test_invalid_selection_grant_remains_optional_and_cannot_dispatch(pilot, monkeypatch, change):
    model, grant, profile = select_question_grant(pilot)
    packet = marked_packet(model)
    model.policy_path.write_text(json.dumps(grant | change), encoding="utf-8")
    child, execute = Mock(), Mock()
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    assert not model.readiness()["ready"]
    with pytest.raises(ValueError, match="grant"):
        model.selection_authority()
    with pytest.raises(ValueError, match="grant"):
        model.infer("researcher", packet, profile)
    child.assert_not_called()
    execute.assert_not_called()


def test_missing_selection_policy_is_not_defaulted(pilot):
    model, grant, _ = select_question_grant(pilot)
    del grant["question_policy"]
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(ValueError, match="grant"):
        model.selection_authority()


@pytest.mark.parametrize(
    "grant_format", [PAPER_PILOT_FORMAT, PAPER_PILOT_TOOL_FORMAT, PAPER_PILOT_CAPABILITY_FORMAT]
)
def test_old_formats_cannot_opt_in_by_adding_question_policy(pilot, grant_format):
    model, grant, _ = select_question_grant(pilot)
    grant["format"] = grant_format
    if grant_format == PAPER_PILOT_FORMAT:
        del grant["role_contract"]
    elif grant_format == PAPER_PILOT_TOOL_FORMAT:
        grant["role_contract"] = TOOL_REQUEST_VERSION
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(ValueError, match="grant"):
        model.selection_authority()


@pytest.mark.parametrize("version", [VERSION, TOOL_REQUEST_VERSION, CAPABILITY_VERSION])
def test_marked_packet_refused_under_old_grants_before_transport_or_child(
    pilot, monkeypatch, version
):
    model, _, profile = select_question_grant(pilot)
    packet = marked_packet(model)
    if version == VERSION:
        original = pilot[1]
        model.policy_path.write_text(json.dumps(original), encoding="utf-8")
    else:
        select_tool_grant(pilot, version)
    child, execute = Mock(), Mock()
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="exact current v4 authority"):
        model.instance_preflight("researcher", packet, profile)
    with pytest.raises(ValueError, match="exact current v4 authority"):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()
    child.assert_not_called()


@pytest.mark.parametrize(
    "mutation",
    [
        "null",
        "list",
        "extra",
        "missing",
        "grant_id",
        "grant_sha",
        "profile_sha",
        "contract_sha",
        "integer",
    ],
)
def test_selection_packet_must_match_all_exact_authority_fields(pilot, mutation):
    model, _, profile = select_question_grant(pilot)
    packet = marked_packet(model)
    authority = packet["selection_authority"]
    if mutation == "null":
        packet["selection_authority"] = None
    elif mutation == "list":
        packet["selection_authority"] = list(authority)
    elif mutation == "extra":
        authority["extra"] = "permission"
    elif mutation == "missing":
        del authority["question_policy"]
    elif mutation == "integer":
        authority["grant_sha"] = 0
    else:
        authority[mutation] = "wrong"
    with pytest.raises(ValueError, match="exact current v4 authority"):
        model.instance_preflight("researcher", packet, profile)


def test_selection_profile_changes_refused_before_dispatch(pilot, monkeypatch):
    model, _, profile = select_question_grant(pilot)
    child = Mock()
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    for changed in (profile | {"timeout_seconds": 1}, profile | {"contract_sha256": "0" * 64}):
        with pytest.raises(ValueError, match="exact current v4 authority"):
            model.infer("researcher", marked_packet(model), changed)
    child.assert_not_called()


@pytest.mark.parametrize("cancelled", [False, True])
def test_paused_or_cancelled_selection_permission_cannot_dispatch(pilot, monkeypatch, cancelled):
    model, grant, profile = select_question_grant(pilot)
    packet = marked_packet(model)
    if cancelled:
        model.cancel()
    else:
        model.policy_path.write_text(json.dumps(grant | {"enabled": False}), encoding="utf-8")
        packet = marked_packet(model)
    execute = Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="paused or cancelled"):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()


def test_same_grant_id_policy_replacement_cannot_adopt_selected_packet(pilot, monkeypatch):
    model, grant, profile = select_question_grant(pilot)
    packet = marked_packet(model)
    grant.pop("question_policy")
    grant["format"] = PAPER_PILOT_CAPABILITY_FORMAT
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    execute = Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    assert model.policy()["grant_id"] == packet["selection_authority"]["grant_id"]
    with pytest.raises(ValueError, match="exact current v4 authority"):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()


def test_grant_drift_while_validating_selection_authority_is_refused(pilot, monkeypatch):
    model, grant, _ = select_question_grant(pilot)
    original = model.declaration

    def declaration_then_change():
        declared = original()
        model.policy_path.write_text(
            json.dumps(grant | {"grant_id": "new-evidence-selection-4"}), encoding="utf-8"
        )
        return declared

    monkeypatch.setattr(model, "declaration", declaration_then_change)
    with pytest.raises(ValueError, match="changed while verifying authority"):
        model.selection_authority()


def test_grant_drift_after_instance_preflight_cannot_reach_existing_dispatch(pilot, monkeypatch):
    model, grant, profile = select_question_grant(pilot)
    packet = marked_packet(model)
    original = model.instance_preflight

    def preflight_then_change(*args):
        original(*args)
        model.policy_path.write_text(
            json.dumps(grant | {"grant_id": "new-evidence-selection-4"}), encoding="utf-8"
        )

    execute = Mock()
    monkeypatch.setattr(model, "instance_preflight", preflight_then_change)
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="changed before dispatch"):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()
    assert not model._pilot_active and not model._request_lock.locked()


def test_valid_selection_stages_reuse_existing_owned_guard_and_sequential_transport(
    pilot, monkeypatch
):
    model, grant, profile = select_question_grant(pilot)
    packet = marked_packet(model)
    observations = []
    calls = []

    def execute(self, role, passed, declared):
        assert declared == profile and passed["selection_authority"] == model.selection_authority()
        for phase in ("before_dispatch", "during_inference", "after_response"):
            observations.append(self._paper_guard(phase))
        calls.append(role)
        return {"complete": True, "scope": "Synthetic transport delegation only"}

    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    for role in ("researcher", "reviewer"):
        assert model.admit(role) == profile
        model.instance_preflight(role, packet, profile)
        assert model.infer(role, packet, profile)["complete"]
    assert calls == ["researcher", "reviewer"]
    assert all(row["admitted"] and row["grant_sha256"] == digest(grant) for row in observations)
    assert not model._pilot_active and not model._request_lock.locked()
    assert model.policy()["experimental"] and not model.policy()["qualified"]


def test_current_v4_grant_remains_pinned_during_inference(pilot, monkeypatch):
    model, grant, profile = select_question_grant(pilot)
    packet = marked_packet(model)

    def execute(self, *_):
        model.policy_path.write_text(json.dumps(grant | {"enabled": False}), encoding="utf-8")
        self._paper_guard("during_inference")

    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="paper_pilot_paused|paper_pilot_grant_changed"):
        model.infer("researcher", packet, profile)
    assert not model._pilot_active and not model._request_lock.locked()


def test_existing_manual_packet_and_static_contract_preflight_are_unchanged(pilot, monkeypatch):
    model, _, profile = select_tool_grant(pilot, CAPABILITY_VERSION)
    packet = {"contract": CAPABILITY_VERSION, "question": "Existing manual v7 fixture"}
    original = deepcopy(packet)
    PeftPaperPilotRoles.preflight("researcher", packet, profile)
    model.instance_preflight("researcher", packet, profile)
    execute = Mock(return_value={"complete": True})
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    assert model.infer("researcher", packet, profile)["complete"]
    assert packet == original
    execute.assert_called_once()
