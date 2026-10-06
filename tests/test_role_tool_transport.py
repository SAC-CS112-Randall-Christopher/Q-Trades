"""Version-bound transport fixtures; no model, operating services or database calls."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from test_local_roles import declared as local_policy
from test_peft_development import declared as declared
from test_peft_paper_pilot import pilot as pilot

from trading.lab_role_contract import (
    CAPABILITY_VERSION,
    TOOL_REQUEST_VERSION,
    VERSION,
    contract_hash,
    prompt,
    schema,
)
from trading.local_role_model import LocalRoles, check_role_contract
from trading.peft_profile import PROFILE, digest
from trading.peft_role_model import (
    PAPER_PILOT_CAPABILITY_FORMAT,
    PAPER_PILOT_FORMAT,
    PAPER_PILOT_TOOL_FORMAT,
    DevelopmentTransportFailure,
    PeftDevelopmentRoles,
    PeftPaperPilotRoles,
    local_role_transport,
)


def tool_profile(original, version=TOOL_REQUEST_VERSION):
    return original | {
        "role_contract": version,
        "contract_sha256": contract_hash(version),
    }


def select_tool_grant(pilot, version=TOOL_REQUEST_VERSION):
    model, grant, development, *_ = pilot
    profile = tool_profile(development.declaration()[2], version)
    updated = grant | {
        "format": PAPER_PILOT_CAPABILITY_FORMAT
        if version == CAPABILITY_VERSION
        else PAPER_PILOT_TOOL_FORMAT,
        "role_contract": version,
        "grant_id": "fixture-paper-capability-3"
        if version == CAPABILITY_VERSION
        else "fixture-paper-tools-2",
        "profile_sha256": digest(profile),
    }
    model.policy_path.write_text(json.dumps(updated), encoding="utf-8")
    return model, updated, profile


def test_original_contract_and_v1_profile_are_preserved_exactly(pilot):
    model, grant, development, *_ = pilot
    assert contract_hash() == "71f90342b3781819e690cf9bb8890a750e97a34b3818fb1a8d04b2324682b7f5"
    assert (
        contract_hash(TOOL_REQUEST_VERSION)
        == "cb4d5c9435720f7c48e85ecbc582658821e01d2ad51d92274cfb54bc1a64e4e3"
    )
    original = development.declaration()[2]
    assert "role_contract" not in original
    assert len(grant) == 8 and grant["format"] == PAPER_PILOT_FORMAT
    assert model.role_contract == development.role_contract == VERSION
    assert model.admit("researcher") == original
    assert model.declaration()[2] == original
    assert digest(original) == grant["profile_sha256"]
    for field, value in PROFILE.items():
        assert original[field] == value


def test_explicit_v2_grant_changes_only_contract_profile_and_keeps_unqualified_status(pilot):
    original = pilot[2].declaration()[2]
    model, grant, profile = select_tool_grant(pilot)
    assert type(local_role_transport(model.policy_path.parent)) is PeftPaperPilotRoles
    assert model.role_contract == TOOL_REQUEST_VERSION
    assert model.admit("researcher") == profile
    assert digest(profile) == grant["profile_sha256"] != digest(original)
    assert {k: v for k, v in profile.items() if k not in {"role_contract", "contract_sha256"}} == {
        k: v for k, v in original.items() if k != "contract_sha256"
    }
    readiness = model.readiness()
    assert readiness["ready"] and readiness["experimental"]
    assert not readiness["qualified"] and not readiness["qualification_valid"]
    assert profile["identity"] == original["identity"]
    with pytest.raises(ValueError, match="reinterpret"):
        model.development_admit("researcher")


@pytest.mark.parametrize(
    "change",
    [
        {"role_contract": TOOL_REQUEST_VERSION},
        {"format": PAPER_PILOT_TOOL_FORMAT},
        {"format": PAPER_PILOT_TOOL_FORMAT, "role_contract": VERSION},
        {"format": PAPER_PILOT_TOOL_FORMAT, "role_contract": "unreviewed-role-v7"},
    ],
)
def test_bad_version_grant_remains_optional_unavailable_before_child(pilot, monkeypatch, change):
    model, grant, *_ = pilot
    model.policy_path.write_text(json.dumps(grant | change), encoding="utf-8")
    child = Mock()
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    assert not local_role_transport(model.policy_path.parent).readiness()["ready"]
    with pytest.raises(ValueError, match="grant"):
        _ = model.role_contract
    child.assert_not_called()


def test_v2_cannot_reuse_the_original_v5_profile_digest(pilot):
    model, grant, *_ = pilot
    model.policy_path.write_text(
        json.dumps(
            grant | {"format": PAPER_PILOT_TOOL_FORMAT, "role_contract": TOOL_REQUEST_VERSION}
        ),
        encoding="utf-8",
    )
    assert model.role_contract == TOOL_REQUEST_VERSION
    assert not model.readiness()["ready"]
    with pytest.raises(ValueError, match="frozen model/profile"):
        model.declaration()
    with pytest.raises(ValueError, match="Protected"):
        model.admit("researcher")


@pytest.mark.parametrize("transport", [LocalRoles, PeftDevelopmentRoles, PeftPaperPilotRoles])
@pytest.mark.parametrize("profile_change", [{}, {"contract_sha256": "0" * 64}])
def test_v6_packet_refused_by_v5_before_runtime_access(transport, profile_change):
    profile = local_policy() | profile_change
    with pytest.raises(ValueError, match="contract"):
        transport.preflight("researcher", {"contract": TOOL_REQUEST_VERSION}, profile)


@pytest.mark.parametrize(
    "profile_change",
    [
        {"role_contract": TOOL_REQUEST_VERSION},
        {"contract_sha256": contract_hash(TOOL_REQUEST_VERSION)},
        {"role_contract": TOOL_REQUEST_VERSION, "contract_sha256": contract_hash()},
        {"role_contract": "unreviewed-role-v7"},
    ],
)
def test_incomplete_or_unknown_tool_profile_never_admits(profile_change):
    with pytest.raises(ValueError, match="contract"):
        check_role_contract({"contract": TOOL_REQUEST_VERSION}, local_policy() | profile_change)


def test_profile_cannot_select_v6_for_an_unversioned_or_v5_packet():
    profile = tool_profile(local_policy())
    for packet in ({}, {"contract": VERSION}, {"contract": None}):
        with pytest.raises(ValueError, match="contract"):
            check_role_contract(packet, profile)
    assert check_role_contract({"contract": TOOL_REQUEST_VERSION}, profile) == TOOL_REQUEST_VERSION


def test_peft_mismatch_refuses_before_private_declaration_child_or_authorization(
    declared, monkeypatch
):
    model, *_ = declared
    profile = model.declaration()[2]
    observed = Mock()
    consumed = Mock()
    child = Mock()
    monkeypatch.setattr(model, "declaration", observed)
    monkeypatch.setattr(model, "_consume_latency_authorization", consumed)
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    with pytest.raises(ValueError, match="contract"):
        model.infer("researcher", {"contract": TOOL_REQUEST_VERSION}, profile)
    observed.assert_not_called()
    consumed.assert_not_called()
    child.assert_not_called()


def test_local_mismatch_refuses_before_http_or_observation(tmp_path, monkeypatch):
    model = LocalRoles(tmp_path)
    observed = Mock()
    client = Mock()
    monkeypatch.setattr(model, "observe", observed)
    monkeypatch.setattr("trading.local_role_model.httpx.Client", client)
    with pytest.raises(ValueError, match="contract"):
        model.infer("researcher", {"contract": TOOL_REQUEST_VERSION}, local_policy())
    observed.assert_not_called()
    client.assert_not_called()


def test_local_policy_version_changes_qualification_identity_without_inventing_qualification(
    tmp_path, monkeypatch
):
    model = LocalRoles(tmp_path)
    monkeypatch.setattr(model, "observe", lambda _: {"scope": "pure fixture"})
    original = local_policy()
    model.path.write_text(json.dumps(original), encoding="utf-8")
    assert model.role_contract == VERSION
    v5 = model.policy()
    assert "role_contract" not in v5 and v5["contract_sha256"] == contract_hash()
    model.path.write_text(
        json.dumps(original | {"role_contract": TOOL_REQUEST_VERSION}), encoding="utf-8"
    )
    v6 = model.policy()
    assert model.role_contract == TOOL_REQUEST_VERSION
    assert v6["contract_sha256"] == contract_hash(TOOL_REQUEST_VERSION)
    assert v6 != v5
    assert not model.readiness()["qualified"]
    model.path.write_text(
        json.dumps(original | {"role_contract": "unreviewed-role-v7"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="contract"):
        _ = model.role_contract


@pytest.mark.parametrize("version", [TOOL_REQUEST_VERSION, CAPABILITY_VERSION])
def test_successor_local_wire_uses_only_explicit_selected_prompt_and_schema(
    tmp_path, monkeypatch, version
):
    model = LocalRoles(tmp_path)
    profile = tool_profile(local_policy(), version)
    calls = []
    real_client = httpx.Client

    def respond(request):
        payload = json.loads(request.content) if request.content else {}
        if payload.get("keep_alive") == 0:
            return httpx.Response(200, json={})
        calls.append(payload)
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(200, json={"done": True, "done_reason": "stop", "response": "{}"})

    monkeypatch.setattr(
        "trading.local_role_model.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr(model, "observe", lambda _: {})
    monkeypatch.setattr(model, "paper_guard", lambda: {"scope": "pure fixture"})
    monkeypatch.setattr("trading.local_role_model.capture_resources", lambda _: {})
    monkeypatch.setattr("trading.local_role_model.cpu_placement_valid", lambda *_: True)
    model.infer("researcher", {"contract": version}, profile)
    assert calls[0]["system"] == prompt("researcher", version)
    assert calls[0]["format"] == schema("researcher", version)
    assert calls[0]["system"] != prompt("researcher")


@pytest.mark.parametrize("version", [TOOL_REQUEST_VERSION, CAPABILITY_VERSION])
def test_successor_peft_request_preserves_runner_settings_and_selected_system_without_model(
    pilot, monkeypatch, version
):
    model, _, profile = select_tool_grant(pilot, version)
    captured = []

    def refuse_child(args, **kwargs):
        job = Path(args[-1])
        captured.append(json.loads((job / "request.json").read_text(encoding="utf-8")))
        raise OSError("Procedural dispatch stop; no model child")

    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", refuse_child)
    with pytest.raises(DevelopmentTransportFailure):
        model.infer("researcher", {"contract": version}, profile)
    assert len(captured) == 1
    request = captured[0]
    assert request["system"] == prompt("researcher", version)
    assert request["settings"] == PROFILE
    assert request["runner_sha256"] == profile["runner_sha256"]
    assert json.loads(request["packet_json"])["contract"] == version
    assert "role_contract" not in request["settings"]


@pytest.mark.parametrize("version", [TOOL_REQUEST_VERSION, CAPABILITY_VERSION])
def test_successor_still_refuses_retrieval_and_diagnostic_requests(pilot, version):
    model, _, profile = select_tool_grant(pilot, version)
    for extra in (
        {"knowledge": {}},
        {"retrieval_contract": "unapproved"},
        {"evidence": {"e2": {"purpose": "performance_diagnostic"}}},
    ):
        with pytest.raises(ValueError):
            model.preflight("researcher", {"contract": version} | deepcopy(extra), profile)


def test_explicit_v3_grant_binds_v7_only_and_preserves_frozen_model_resources(pilot):
    original = pilot[2].declaration()[2]
    v6 = tool_profile(original)
    model, grant, profile = select_tool_grant(pilot, CAPABILITY_VERSION)
    assert grant["format"] == PAPER_PILOT_CAPABILITY_FORMAT and len(grant) == 9
    assert model.role_contract == CAPABILITY_VERSION
    assert model.admit("researcher") == model.admit("reviewer") == profile
    assert profile == original | {
        "role_contract": CAPABILITY_VERSION,
        "contract_sha256": contract_hash(CAPABILITY_VERSION),
    }
    assert digest(profile) == grant["profile_sha256"]
    assert digest(profile) not in {digest(original), digest(v6)}
    for field, value in PROFILE.items():
        assert profile[field] == value
    assert profile["identity"] == original["identity"]
    assert profile["runner_sha256"] == original["runner_sha256"]
    readiness = model.readiness()
    assert readiness["ready"] and readiness["experimental"]
    assert not readiness["qualified"] and not readiness["qualification_valid"]
    with pytest.raises(ValueError, match="reinterpret"):
        model.development_admit("researcher")


@pytest.mark.parametrize(
    "grant_format,version",
    [
        (PAPER_PILOT_FORMAT, CAPABILITY_VERSION),
        (PAPER_PILOT_TOOL_FORMAT, CAPABILITY_VERSION),
        (PAPER_PILOT_CAPABILITY_FORMAT, VERSION),
        (PAPER_PILOT_CAPABILITY_FORMAT, TOOL_REQUEST_VERSION),
    ],
)
def test_v7_cannot_reinterpret_existing_grant_formats_or_older_contracts(
    pilot, monkeypatch, grant_format, version
):
    model, grant, *_ = pilot
    model.policy_path.write_text(
        json.dumps(grant | {"format": grant_format, "role_contract": version}), encoding="utf-8"
    )
    client, child = Mock(), Mock()
    monkeypatch.setattr("trading.local_role_model.httpx.Client", client)
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    assert not model.readiness()["ready"]
    with pytest.raises(ValueError, match="grant"):
        _ = model.role_contract
    client.assert_not_called()
    child.assert_not_called()


@pytest.mark.parametrize("old_version", [VERSION, TOOL_REQUEST_VERSION])
def test_v3_cannot_reuse_a_v5_or_v6_profile_digest(pilot, old_version):
    model, grant, development, *_ = pilot
    original = development.declaration()[2]
    older = original if old_version == VERSION else tool_profile(original)
    model.policy_path.write_text(
        json.dumps(
            grant
            | {
                "format": PAPER_PILOT_CAPABILITY_FORMAT,
                "role_contract": CAPABILITY_VERSION,
                "profile_sha256": digest(older),
            }
        ),
        encoding="utf-8",
    )
    assert model.role_contract == CAPABILITY_VERSION
    assert not model.readiness()["ready"]
    with pytest.raises(ValueError, match="frozen model/profile"):
        model.declaration()


@pytest.mark.parametrize("transport", [LocalRoles, PeftDevelopmentRoles, PeftPaperPilotRoles])
@pytest.mark.parametrize("old_version", [VERSION, TOOL_REQUEST_VERSION])
def test_v7_packet_refused_by_older_preflight_before_runtime_access(transport, old_version):
    original = local_policy()
    profile = original if old_version == VERSION else tool_profile(original)
    with pytest.raises(ValueError, match="contract"):
        transport.preflight("researcher", {"contract": CAPABILITY_VERSION}, profile)


@pytest.mark.parametrize(
    "profile_change",
    [
        {"role_contract": CAPABILITY_VERSION},
        {"contract_sha256": contract_hash(CAPABILITY_VERSION)},
        {"role_contract": CAPABILITY_VERSION, "contract_sha256": "0" * 64},
        {"role_contract": CAPABILITY_VERSION, "contract_sha256": contract_hash()},
        {
            "role_contract": CAPABILITY_VERSION,
            "contract_sha256": contract_hash(TOOL_REQUEST_VERSION),
        },
    ],
)
def test_v7_requires_its_complete_explicit_contract_profile(profile_change):
    with pytest.raises(ValueError, match="contract"):
        check_role_contract({"contract": CAPABILITY_VERSION}, local_policy() | profile_change)


@pytest.mark.parametrize("packet", [{}, {"contract": VERSION}, {"contract": TOOL_REQUEST_VERSION}])
def test_v7_profile_never_accepts_an_unversioned_or_older_packet(packet):
    profile = tool_profile(local_policy(), CAPABILITY_VERSION)
    with pytest.raises(ValueError, match="contract"):
        check_role_contract(packet, profile)
    assert check_role_contract({"contract": CAPABILITY_VERSION}, profile) == CAPABILITY_VERSION


@pytest.mark.parametrize("incoming_version", [TOOL_REQUEST_VERSION, CAPABILITY_VERSION])
def test_v6_pilot_refuses_v7_before_guard_http_child_or_latency_authorization(
    pilot, monkeypatch, incoming_version
):
    model, _, selected = select_tool_grant(pilot)
    incoming = (
        selected
        if incoming_version == TOOL_REQUEST_VERSION
        else tool_profile(selected, CAPABILITY_VERSION)
    )
    guard, client, child = Mock(), Mock(), Mock()
    authorization_before = deepcopy(model._latency_authorization), model._latency_used
    assert model._latency_mode is False
    monkeypatch.setattr(model, "_paper_guard", guard)
    monkeypatch.setattr("trading.local_role_model.httpx.Client", client)
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    with pytest.raises(ValueError, match="contract|profile"):
        model.infer("researcher", {"contract": CAPABILITY_VERSION}, incoming)
    guard.assert_not_called()
    client.assert_not_called()
    child.assert_not_called()
    assert (model._latency_authorization, model._latency_used) == authorization_before


def test_local_v7_mismatch_refuses_before_http_or_observation(tmp_path, monkeypatch):
    model = LocalRoles(tmp_path)
    observed, client = Mock(), Mock()
    monkeypatch.setattr(model, "observe", observed)
    monkeypatch.setattr("trading.local_role_model.httpx.Client", client)
    with pytest.raises(ValueError, match="contract"):
        model.infer("researcher", {"contract": CAPABILITY_VERSION}, tool_profile(local_policy()))
    observed.assert_not_called()
    client.assert_not_called()


def test_local_v7_policy_keeps_model_resources_and_requires_new_qualification(
    tmp_path, monkeypatch
):
    model = LocalRoles(tmp_path)
    monkeypatch.setattr(model, "observe", lambda _: {"scope": "pure fixture"})
    original = local_policy()
    model.path.write_text(
        json.dumps(original | {"role_contract": CAPABILITY_VERSION}), encoding="utf-8"
    )
    selected = model.policy()
    assert model.role_contract == CAPABILITY_VERSION
    assert selected["contract_sha256"] == contract_hash(CAPABILITY_VERSION)
    assert selected["options"] == original["options"]
    assert selected["model_digest"] == original["model_digest"]
    assert not model.readiness()["qualified"]
