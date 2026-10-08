"""Explicit lesson-conditioned authority; synthetic metadata, no model or operating calls."""

import json
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_peft_development import declared as declared
from test_peft_paper_pilot import pilot as pilot
from test_peft_pattern_selection import select_pattern_grant

from trading.lab_role_contract import CAPABILITY_VERSION, PATTERN_VERSION, contract_hash
from trading.peft_profile import PROFILE, digest
from trading.peft_role_model import (
    PAPER_PILOT_PATTERN_LEARNING_FORMAT,
    PATTERN_LEARNING_QUESTION_POLICY,
    PATTERN_QUESTION_POLICY,
    PeftDevelopmentRoles,
    PeftPaperPilotRoles,
    local_role_transport,
)


@pytest.fixture
def learning(pilot):
    model, old, profile = select_pattern_grant(pilot)
    grant = old | {
        "format": PAPER_PILOT_PATTERN_LEARNING_FORMAT,
        "grant_id": "fixture-pattern-learning-7",
        "question_policy": PATTERN_LEARNING_QUESTION_POLICY,
    }
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    return model, grant, profile, old


def marked_packet(model):
    return {
        "contract": PATTERN_VERSION,
        "question": "A distinct native finding is considered with its retained mature lesson.",
        "selection_authority": model.selection_authority(),
    }


def test_explicit_v7_keeps_v8_profile_resources_and_existing_transport(learning, pilot):
    model, grant, profile, old = learning
    before = model.policy_path.read_bytes()
    assert type(local_role_transport(model.policy_path.parent)) is PeftPaperPilotRoles
    assert len(grant) == len(old) == 10
    assert model.role_contract == PATTERN_VERSION
    assert model.declaration()[2] == profile
    assert model.admit("researcher") == model.admit("reviewer") == profile
    assert all(profile[key] == value for key, value in PROFILE.items())
    assert profile == pilot[2].declaration()[2] | {
        "role_contract": PATTERN_VERSION,
        "contract_sha256": contract_hash(PATTERN_VERSION),
    }
    assert model.selection_authority() == {
        "question_policy": PATTERN_LEARNING_QUESTION_POLICY,
        "grant_id": grant["grant_id"],
        "grant_sha": digest(grant),
        "profile_sha": digest(profile),
        "contract_version": PATTERN_VERSION,
        "contract_sha": contract_hash(PATTERN_VERSION),
    }
    authority = model.selection_authority()
    assert len(authority) == 6 and all(type(value) is str for value in authority.values())
    authority["grant_id"] = "caller mutation"
    assert model.selection_authority()["grant_id"] == grant["grant_id"]
    assert model.finite_test() is None
    with pytest.raises(ValueError, match="explicit finite grant"):
        with model.finite_operation({}):
            pytest.fail("Nonfinite v7 cannot acquire finite financial authority")
    readiness = model.readiness()
    assert readiness["ready"] and readiness["experimental"]
    assert not readiness["qualified"] and not readiness["qualification_valid"]
    assert model.policy_path.read_bytes() == before


@pytest.mark.parametrize(
    "change",
    [
        {"question_policy": PATTERN_QUESTION_POLICY},
        {"question_policy": "evidence-question-selection-v1"},
        {"question_policy": None},
        {"question_policy": True},
        {"role_contract": CAPABILITY_VERSION},
        {"role_contract": "unreviewed-rule-role-v9"},
        {"extra": "permission"},
        {"finite_test": {}},
        {"format": "qtrades-peft-paper-pilot-v5"},
        {"enabled": 1},
    ],
)
def test_new_format_refuses_wrong_policy_contract_or_keys_before_dispatch(
    learning, monkeypatch, change
):
    model, grant, profile, _ = learning
    packet = marked_packet(model)
    model.policy_path.write_text(json.dumps(grant | change), encoding="utf-8")
    before = model.policy_path.read_bytes()
    execute, child = Mock(), Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    assert not model.readiness()["ready"]
    with pytest.raises(ValueError, match="grant"):
        model.selection_authority()
    with pytest.raises(ValueError):
        model.infer("researcher", packet, profile)
    assert model.policy_path.read_bytes() == before
    execute.assert_not_called()
    child.assert_not_called()


@pytest.mark.parametrize("key", ["question_policy", "role_contract"])
def test_learning_permission_is_never_defaulted(learning, key):
    model, grant, *_ = learning
    del grant[key]
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(ValueError, match="grant"):
        model.selection_authority()


@pytest.mark.parametrize("change", [{"enabled": False}, {"profile_sha256": "0" * 64}])
def test_paused_or_mismatched_profile_refuses_before_model(learning, monkeypatch, change):
    model, grant, profile, _ = learning
    packet = marked_packet(model)
    model.policy_path.write_text(json.dumps(grant | change), encoding="utf-8")
    execute = Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()


@pytest.mark.parametrize("mutation", ["policy", "grant", "authority_extra", "profile"])
def test_packet_requires_exact_current_full_authority(learning, monkeypatch, mutation):
    model, grant, profile, _ = learning
    packet = marked_packet(model)
    if mutation == "policy":
        packet["selection_authority"]["question_policy"] = PATTERN_QUESTION_POLICY
    elif mutation == "grant":
        model.policy_path.write_text(
            json.dumps(grant | {"grant_id": "different-explicit-grant"}), encoding="utf-8"
        )
    elif mutation == "authority_extra":
        packet["selection_authority"]["lesson_authority"] = "unapproved"
    else:
        profile = profile | {"seed": profile["seed"] + 1}
    execute = Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()


def test_learning_packet_cannot_omit_its_explicit_policy_authority(learning, monkeypatch):
    model, _, profile, _ = learning
    packet = marked_packet(model)
    del packet["selection_authority"]
    execute, preflight = Mock(), Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    monkeypatch.setattr(model, "preflight", preflight)
    with pytest.raises(ValueError, match="exact current v7 authority"):
        model.instance_preflight("researcher", packet, profile)
    with pytest.raises(ValueError, match="exact current v7 authority"):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()
    preflight.assert_not_called()


def test_old_to_learning_grant_race_after_preflight_refuses_before_dispatch(learning, monkeypatch):
    model, grant, profile, old = learning
    model.policy_path.write_text(json.dumps(old), encoding="utf-8")
    packet = {"contract": PATTERN_VERSION, "question": "Original unmarked pattern packet."}
    before = deepcopy(packet)
    original = model.instance_preflight

    def switch_after_preflight(role, value, selected):
        original(role, value, selected)
        model.policy_path.write_text(json.dumps(grant), encoding="utf-8")

    monkeypatch.setattr(model, "instance_preflight", switch_after_preflight)
    execute, child = Mock(), Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    with pytest.raises(ValueError, match="exact current v7 authority"):
        model.infer("researcher", packet, profile)
    assert packet == before
    execute.assert_not_called()
    child.assert_not_called()
    assert model._request_lock.acquire(blocking=False)
    model._request_lock.release()


def test_exact_learning_dispatch_uses_existing_owner_and_pause_stays_latched(learning, monkeypatch):
    model, _, profile, _ = learning
    packet = marked_packet(model)
    answer = {"decision": "wait", "reason": "Original mature outcome does not justify a change."}
    execute = Mock(return_value=answer)
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    assert model.infer("researcher", packet, profile) is answer
    execute.assert_called_once_with("researcher", packet, profile)
    model.cancel()
    with pytest.raises(ValueError, match="paused or cancelled"):
        model.infer("researcher", packet, profile)
    assert execute.call_count == 1


def test_valid_grant_change_during_dispatch_is_refused_by_existing_guard(learning, monkeypatch):
    model, grant, profile, _ = learning
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


def test_grant_change_between_admission_and_dispatch_does_not_transfer_authority(
    learning, monkeypatch
):
    model, grant, profile, _ = learning
    model.admit("researcher")
    model.policy_path.write_text(
        json.dumps(grant | {"grant_id": "changed-after-admission"}), encoding="utf-8"
    )
    packet = marked_packet(model)
    execute = Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="between admission and dispatch"):
        model.infer("researcher", packet, profile)
    execute.assert_not_called()


def test_grant_change_during_declaration_cannot_publish_selection_authority(learning, monkeypatch):
    model, grant, profile, _ = learning

    def declaration():
        model.policy_path.write_text(
            json.dumps(grant | {"grant_id": "changed-during-declaration"}), encoding="utf-8"
        )
        return {}, {}, profile

    monkeypatch.setattr(model, "declaration", declaration)
    with pytest.raises(ValueError, match="changed while verifying authority"):
        model.selection_authority()


def test_nonfinite_learning_cannot_use_reserved_finite_dispatch(learning, monkeypatch):
    model, _, profile, _ = learning
    packet = marked_packet(model)
    execute = Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="explicit finite grant"):
        model.infer_reserved("researcher", packet, profile, {})
    execute.assert_not_called()


def test_old_pattern_packet_is_not_reinterpreted_as_learning_authority(learning, monkeypatch):
    model, _, profile, old = learning
    old_packet = {
        "contract": PATTERN_VERSION,
        "question": "Original pattern question without a mature-lesson policy.",
        "selection_authority": {
            "question_policy": PATTERN_QUESTION_POLICY,
            "grant_id": old["grant_id"],
            "grant_sha": digest(old),
            "profile_sha": digest(profile),
            "contract_version": PATTERN_VERSION,
            "contract_sha": contract_hash(PATTERN_VERSION),
        },
    }
    before = deepcopy(old_packet)
    execute = Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError):
        model.infer("researcher", old_packet, profile)
    assert old_packet == before
    execute.assert_not_called()
    model.policy_path.write_text(json.dumps(old), encoding="utf-8")
    assert model.selection_authority() == old_packet["selection_authority"]
    assert model.declaration()[2] == profile


def legacy_grant(version):
    grant = {
        "format": f"qtrades-peft-paper-pilot-v{version}",
        "enabled": True,
        "grant_id": f"fixture-legacy-grant-{version}",
        "development_directory": "C:/synthetic/development",
        "profile_sha256": "c" * 64,
        "roles": ["researcher", "reviewer"],
        "latency_admission": "advisory",
        "scope": "prospective-paper-only",
    }
    if version >= 2:
        grant["role_contract"] = (
            f"reviewed-rule-role-v{6 if version == 2 else 7 if version <= 4 else 8}"
        )
    if version >= 4:
        grant["question_policy"] = (
            "evidence-question-selection-v1" if version == 4 else "pattern-question-selection-v1"
        )
    if version == 6:
        grant["finite_test"] = {
            "not_before": 999.0,
            "expires_at": 2000.0,
            "max_requests": 3,
            "selection": {
                "daily_id": "daily-" + "a" * 24,
                "symbol": "BTCUSD",
                "timeframe": "5m",
                "event_kind": "patterns",
                "event_seq": 1,
            },
            "finding_sha256": "b" * 64,
        }
    return grant


LEGACY_DIGESTS = {
    1: "51e70596909f7950baaf03909e8901d495b3869470a0c7622a5c485235d79f95",
    2: "5e5f90968b11fe0e907f4e3aafb4d971869ed9c54beb338dbcee9cb0ed043796",
    3: "98a18c433fe192585e7a72c0092c11564056d6fb73cab0a220b0a7fa7812f0db",
    4: "2f2b18c0892286ac6d21a163016119cad0091232e1c809283d0bcde6be5790b1",
    5: "4c7841d69aa1bf52ccb905cc2823904ab977f9a3d434af040502af060021301b",
    6: "abaa8840721988c29bcba274065531e64f779ea9ee2506c27a4ef13fd96c6ac0",
}


@pytest.mark.parametrize("version", range(1, 7))
def test_all_original_grant_schemas_digests_and_authorities_remain_exact(
    pilot, monkeypatch, version
):
    model = pilot[0]
    grant = legacy_grant(version)
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    before = model.policy_path.read_bytes()
    monkeypatch.setattr(model, "declaration", lambda: ({}, {}, {}))
    monkeypatch.setattr(
        "trading.peft_role_model.time",
        SimpleNamespace(time=lambda: 1000.0, perf_counter=time.perf_counter),
    )
    assert model._grant() == grant
    assert digest(model._grant()) == LEGACY_DIGESTS[version]
    if version < 4:
        assert model.selection_authority() is None
    else:
        assert model.selection_authority() == {
            "question_policy": grant["question_policy"],
            "grant_id": grant["grant_id"],
            "grant_sha": LEGACY_DIGESTS[version],
            "profile_sha": grant["profile_sha256"],
            "contract_version": grant["role_contract"],
            "contract_sha": contract_hash(grant["role_contract"]),
        }
    finite = model.finite_test()
    assert (finite is not None) == (version == 6)
    if finite:
        assert finite["finite_test"] == grant["finite_test"]
    assert model.policy_path.read_bytes() == before
    grant["question_policy"] = PATTERN_LEARNING_QUESTION_POLICY
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(ValueError, match="grant"):
        model._grant()
