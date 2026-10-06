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

from trading.lab_role_contract import TOOL_REQUEST_VERSION, VERSION, contract_hash, prompt, schema
from trading.local_role_model import LocalRoles, check_role_contract
from trading.peft_profile import PROFILE, digest
from trading.peft_role_model import (
    PAPER_PILOT_FORMAT,
    PAPER_PILOT_TOOL_FORMAT,
    DevelopmentTransportFailure,
    PeftDevelopmentRoles,
    PeftPaperPilotRoles,
    local_role_transport,
)


def tool_profile(original):
    return original | {
        "role_contract": TOOL_REQUEST_VERSION,
        "contract_sha256": contract_hash(TOOL_REQUEST_VERSION),
    }


def select_tool_grant(pilot):
    model, grant, development, *_ = pilot
    profile = tool_profile(development.declaration()[2])
    updated = grant | {
        "format": PAPER_PILOT_TOOL_FORMAT,
        "role_contract": TOOL_REQUEST_VERSION,
        "grant_id": "fixture-paper-tools-2",
        "profile_sha256": digest(profile),
    }
    model.policy_path.write_text(json.dumps(updated), encoding="utf-8")
    return model, updated, profile


def test_original_contract_and_v1_profile_are_preserved_exactly(pilot):
    model, grant, development, *_ = pilot
    assert contract_hash() == "71f90342b3781819e690cf9bb8890a750e97a34b3818fb1a8d04b2324682b7f5"
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


def test_v6_local_wire_uses_only_explicit_selected_prompt_and_schema(tmp_path, monkeypatch):
    model = LocalRoles(tmp_path)
    profile = tool_profile(local_policy())
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
    model.infer("researcher", {"contract": TOOL_REQUEST_VERSION}, profile)
    assert calls[0]["system"] == prompt("researcher", TOOL_REQUEST_VERSION)
    assert calls[0]["format"] == schema("researcher", TOOL_REQUEST_VERSION)
    assert calls[0]["system"] != prompt("researcher")


def test_v6_peft_request_preserves_runner_settings_and_uses_selected_system_without_model(
    pilot, monkeypatch
):
    model, _, profile = select_tool_grant(pilot)
    captured = []

    def refuse_child(args, **kwargs):
        job = Path(args[-1])
        captured.append(json.loads((job / "request.json").read_text(encoding="utf-8")))
        raise OSError("Procedural dispatch stop; no model child")

    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", refuse_child)
    with pytest.raises(DevelopmentTransportFailure):
        model.infer("researcher", {"contract": TOOL_REQUEST_VERSION}, profile)
    assert len(captured) == 1
    request = captured[0]
    assert request["system"] == prompt("researcher", TOOL_REQUEST_VERSION)
    assert request["settings"] == PROFILE
    assert request["runner_sha256"] == profile["runner_sha256"]
    assert json.loads(request["packet_json"])["contract"] == TOOL_REQUEST_VERSION
    assert "role_contract" not in request["settings"]


def test_v2_still_refuses_retrieval_and_diagnostic_requests(pilot):
    model, _, profile = select_tool_grant(pilot)
    for extra in (
        {"knowledge": {}},
        {"retrieval_contract": "unapproved"},
        {"evidence": {"e2": {"purpose": "performance_diagnostic"}}},
    ):
        with pytest.raises(ValueError):
            model.preflight(
                "researcher", {"contract": TOOL_REQUEST_VERSION} | deepcopy(extra), profile
            )
