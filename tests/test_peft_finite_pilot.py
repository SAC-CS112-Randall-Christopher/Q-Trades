"""Finite transport fences with synthetic declarations; no model/provider/financial DB."""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_peft_development import declared as declared
from test_peft_paper_pilot import pilot as pilot
from test_peft_pattern_selection import select_pattern_grant
from test_peft_question_selection import select_question_grant
from test_role_tool_transport import select_tool_grant

from trading.lab_role_contract import CAPABILITY_VERSION, PATTERN_VERSION, TOOL_REQUEST_VERSION
from trading.ownership import CollectorLock
from trading.peft_profile import PROFILE, digest
from trading.peft_role_model import (
    PAPER_PILOT_FINITE_FORMAT,
    DevelopmentTransportFailure,
    PeftDevelopmentRoles,
)


@pytest.fixture
def finite(pilot, monkeypatch):
    model, old, profile = select_pattern_grant(pilot)
    clock = [1000.0]
    monkeypatch.setattr(
        "trading.peft_role_model.time",
        SimpleNamespace(time=lambda: clock[0], perf_counter=time.perf_counter),
    )
    grant = old | {
        "format": PAPER_PILOT_FINITE_FORMAT,
        "grant_id": "fixture-finite-pattern-6",
        "finite_test": {
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
        },
    }
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    packet = {
        "contract": PATTERN_VERSION,
        "question": "One exact native finding motivates a fixed paper comparison.",
        "selection_authority": model.selection_authority(),
    }
    reservation = {
        "grant_id": grant["grant_id"],
        "grant_sha": digest(grant),
        "root_task": "role-" + "c" * 32,
        "task": "role-" + "c" * 32,
        "stage": "idea",
        "attempt": 1,
        "packet_sha256": digest(packet),
        "expires_at": grant["finite_test"]["expires_at"],
        "finite_test_sha": digest(grant["finite_test"]),
    }
    return model, grant, profile, packet, reservation, clock


def scope(model):
    authority = model.finite_test()
    finite = authority.pop("finite_test")
    return authority | {
        "finite_test_sha": digest(finite),
        "not_before": finite["not_before"],
        "expires_at": finite["expires_at"],
    }


def test_finite_identity_is_cheap_detached_and_keeps_six_string_packet_authority(
    finite, monkeypatch
):
    model, grant, profile, packet, _, _ = finite
    before = model.policy_path.read_bytes()
    expensive = Mock(side_effect=AssertionError("No declaration/resource/HTTP read here"))
    monkeypatch.setattr(model, "declaration", expensive)
    monkeypatch.setattr(model, "_protected", expensive)
    authority = model.finite_test()
    assert authority == packet["selection_authority"] | {"finite_test": grant["finite_test"]}
    assert len(packet["selection_authority"]) == 6
    assert all(type(value) is str for value in packet["selection_authority"].values())
    assert authority["profile_sha"] == digest(profile)
    authority["finite_test"]["selection"]["symbol"] = "ETHUSD"
    assert model.finite_test()["finite_test"]["selection"]["symbol"] == "BTCUSD"
    assert model.policy_path.read_bytes() == before
    expensive.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"not_before": True},
        {"not_before": "999"},
        {"not_before": 0},
        {"not_before": float("nan")},
        {"expires_at": float("inf")},
        {"expires_at": 10**400},
        {"expires_at": 999},
        {"expires_at": 999 + 30 * 3600 + 1},
        {"max_requests": True},
        {"max_requests": 3.0},
        {"max_requests": 4},
        {"finding_sha256": "B" * 64},
        {"finding_sha256": "not-a-hash"},
        {"extra": "permission"},
        {"selection": None},
    ],
)
def test_finite_bounds_reject_unknown_unbounded_or_coerced_values(finite, change):
    model, grant, *_ = finite
    grant["finite_test"] |= change
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(ValueError):
        model.finite_test()


@pytest.mark.parametrize(
    "change",
    [
        {"symbol": "ETHUSD"},
        {"timeframe": "15m"},
        {"event_seq": True},
        {"event_seq": "1"},
        {"event_seq": 0},
        {"event_kind": "other"},
        {"daily_id": "unknown"},
        {"extra": "permission"},
    ],
)
def test_finite_finding_uses_exact_existing_strict_selection_schema(finite, change):
    model, grant, *_ = finite
    grant["finite_test"]["selection"] |= change
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(ValueError):
        model.finite_test()


@pytest.mark.parametrize(
    "key", ["selection", "max_requests", "finding_sha256", "not_before", "expires_at"]
)
def test_no_finite_bound_is_defaulted(finite, key):
    model, grant, *_ = finite
    del grant["finite_test"][key]
    model.policy_path.write_text(json.dumps(grant), encoding="utf-8")
    with pytest.raises(ValueError):
        model.finite_test()


def test_original_start_deadline_and_resume_never_renew_window(finite, monkeypatch):
    model, grant, _, _, _, clock = finite
    clock[0] = 998.999
    with pytest.raises(ValueError, match="original start"):
        model.finite_test()
    clock[0] = 999
    assert model.finite_test()["finite_test"] == grant["finite_test"]
    model.set_enabled(False)
    clock[0] = 2000
    expensive = Mock(side_effect=AssertionError("Expired resume must refuse first"))
    monkeypatch.setattr(model, "declaration", expensive)
    with pytest.raises(ValueError, match="deadline expired"):
        model.set_enabled(True)
    assert json.loads(model.policy_path.read_text())["finite_test"] == grant["finite_test"]
    assert json.loads(model.policy_path.read_text())["enabled"] is False
    expensive.assert_not_called()


@pytest.mark.parametrize(
    "version", ["v1", TOOL_REQUEST_VERSION, CAPABILITY_VERSION, "v4", PATTERN_VERSION]
)
def test_old_grants_remain_exact_and_have_no_finite_authority(pilot, monkeypatch, version):
    model = pilot[0]
    if version == "v4":
        model, old, profile = select_question_grant(pilot)
    elif version == PATTERN_VERSION:
        model, old, profile = select_pattern_grant(pilot)
    elif version != "v1":
        model, old, profile = select_tool_grant(pilot, version)
    else:
        old, profile = pilot[1], model.declaration()[2]
    original = model.policy_path.read_bytes()
    original_authority = model.selection_authority()
    assert model.finite_test() is None
    assert model.declaration()[2] == profile
    assert model.selection_authority() == original_authority
    assert model.policy_path.read_bytes() == original
    assert digest(json.loads(original)) == digest(old)
    old["finite_test"] = {"max_requests": 3}
    model.policy_path.write_text(json.dumps(old), encoding="utf-8")
    with pytest.raises(ValueError, match="grant"):
        model.finite_test()


def test_finite_operation_has_no_registry_or_expensive_reads_and_no_exit_recheck(
    finite, monkeypatch
):
    model, _, _, _, _, clock = finite
    expected = scope(model)
    expensive = Mock(side_effect=AssertionError("No registry/model/HTTP in financial fence"))
    model.finite_request_verifier = expensive
    monkeypatch.setattr(model, "declaration", expensive)
    monkeypatch.setattr(model, "_protected", expensive)
    committed = []
    with model.finite_operation(expected) as guard:
        guard()
        committed.append("already-admitted synthetic commit")
        clock[0] = 2000  # Commit drain is retained, not misreported as rollback.
    assert committed == ["already-admitted synthetic commit"]
    with pytest.raises(ValueError, match="deadline expired"):
        with model.finite_operation(expected):
            pytest.fail("No new operation after expiry")
    expensive.assert_not_called()


@pytest.mark.parametrize(
    "key",
    [
        "grant_id",
        "grant_sha",
        "profile_sha",
        "contract_version",
        "contract_sha",
        "question_policy",
        "finite_test_sha",
        "not_before",
        "expires_at",
    ],
)
def test_finite_operation_requires_every_original_scope_field(finite, key):
    model = finite[0]
    expected = scope(model)
    expected[key] = 0 if key in {"not_before", "expires_at"} else "changed"
    with pytest.raises(ValueError, match="scope changed"):
        with model.finite_operation(expected):
            pytest.fail("Wrong scope cannot enter")


def test_financial_fence_serializes_pause_ack_without_registry_lock(finite):
    model = finite[0]
    expected = scope(model)
    entered, acknowledged = Event(), Event()

    def pause():
        entered.set()
        changed = model.set_enabled(False)
        acknowledged.set()
        return changed

    with ThreadPoolExecutor(max_workers=1) as pool:
        with model.finite_operation(expected) as guard:
            future = pool.submit(pause)
            assert entered.wait(2)
            assert not acknowledged.wait(0.05)
            guard()
        assert future.result(timeout=2)["enabled"] is False
    assert acknowledged.is_set()


def test_direct_finite_infer_and_missing_worker_verifier_cannot_dispatch(finite, monkeypatch):
    model, _, profile, packet, reservation, _ = finite
    execute, child = Mock(), Mock()
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    with pytest.raises(ValueError, match="reserved worker attempt"):
        model.infer("researcher", packet, profile)
    with pytest.raises(ValueError, match="reservation verifier"):
        model.infer_reserved("researcher", packet, profile, reservation)
    execute.assert_not_called()
    child.assert_not_called()


@pytest.mark.parametrize(
    "key",
    ["grant_id", "grant_sha", "packet_sha256", "expires_at", "finite_test_sha", "stage", "attempt"],
)
def test_reserved_binding_mismatch_never_reaches_worker_claim_or_child(finite, monkeypatch, key):
    model, _, profile, packet, reservation, _ = finite
    verifier, execute = Mock(), Mock()
    model.finite_request_verifier = verifier
    reservation[key] = 0 if key in {"expires_at", "attempt"} else "changed"
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="reserved worker attempt"):
        model.infer_reserved("researcher", packet, profile, reservation)
    verifier.assert_not_called()
    execute.assert_not_called()


def test_worker_hook_is_outside_policy_mutex_and_wait_cannot_age_authority(finite, monkeypatch):
    model, _, profile, packet, reservation, clock = finite
    execute = Mock()

    def verifier(*_, claim=False):
        assert not claim
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(model.finite_test).result(timeout=2)
        clock[0] = 2000  # Actual hook completion observed after original expiry.

    model.finite_request_verifier = verifier
    monkeypatch.setattr(PeftDevelopmentRoles, "infer", execute)
    with pytest.raises(ValueError, match="deadline expired"):
        model.infer_reserved("researcher", packet, profile, reservation)
    execute.assert_not_called()


def test_expiry_after_collector_acquisition_retains_failure_and_releases_owner(finite, monkeypatch):
    model, _, profile, packet, reservation, clock = finite
    verifier, child = Mock(), Mock()
    model.finite_request_verifier = verifier
    acquire = CollectorLock.acquire

    def acquire_then_expire(lock):
        acquire(lock)
        clock[0] = 2000

    monkeypatch.setattr(CollectorLock, "acquire", acquire_then_expire)
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    with pytest.raises(DevelopmentTransportFailure) as failure:
        model.infer_reserved("researcher", packet, profile, reservation)
    assert failure.value.receipt["cleanup_complete"]
    assert failure.value.receipt["private_job"] is None
    assert failure.value.receipt["finite_request"] == reservation
    assert failure.value.receipt["finite_dispatch_claimed"] is False
    child.assert_not_called()
    lock = CollectorLock(model.directory / "research-inference.lock")
    acquire(lock)
    lock.release()


def test_expiry_immediately_before_child_does_not_claim_or_launch(finite, monkeypatch):
    model, _, profile, packet, reservation, clock = finite
    claims, child = [], Mock()
    model.finite_request_verifier = lambda *_, claim=False: claims.append(claim)
    original = model._dispatch_checkpoint

    def expire_before_child(phase):
        if phase == "before_child":
            clock[0] = 2000
        original(phase)

    monkeypatch.setattr(model, "_dispatch_checkpoint", expire_before_child)
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", child)
    with pytest.raises(DevelopmentTransportFailure) as failure:
        model.infer_reserved("researcher", packet, profile, reservation)
    receipt = failure.value.receipt
    assert receipt["cleanup_complete"] and receipt["private_dispatch_retained"]
    assert receipt["finite_dispatch_claimed"] is False
    assert True not in claims
    child.assert_not_called()


def test_procedural_owned_child_uses_one_exact_claim_and_preserves_raw_answer(finite, monkeypatch):
    model, _, profile, packet, reservation, _ = finite
    original_popen = subprocess.Popen
    claims, children = [], []
    code = """
import pathlib,sys,time
p=pathlib.Path(sys.argv[1])
while not (p/'owner-ready').exists(): time.sleep(.01)
(p/'response.json').write_text(sys.argv[2])
"""

    def verifier(role, passed, declared, binding, *, claim=False):
        assert role == "researcher" and passed == packet and declared == profile
        assert binding == reservation
        if claim and True in claims:
            raise ValueError("Original worker dispatch was already claimed")
        claims.append(claim)

    response = {
        "identity": profile["identity"],
        "settings_sha256": digest(PROFILE),
        "placement": {
            "device": "cpu",
            "precision": "float32",
            "priority_class": 64,
            "processors_allowed": 2,
            "adapter_active": ["default"],
            "adapter_weights_verified": True,
            "trainable_params": 0,
        },
        "complete": True,
        "raw_answer": "procedural finite answer",
        "answer": {},
        "peak_rss_bytes": 1,
    }

    def launch(command, **kwargs):
        job = Path(command[-1])
        request = json.loads((job / "request.json").read_text())
        assert request["packet_json"] == json.dumps(packet, sort_keys=True, separators=(",", ":"))
        value = json.dumps({"request_sha256": digest(request), "response": response})
        child = original_popen([sys.executable, "-c", code, str(job), value], **kwargs)
        children.append(child)
        return child

    model.finite_request_verifier = verifier
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", launch)
    actual = model.infer_reserved("researcher", packet, profile, reservation)
    assert actual["raw_answer"] == "procedural finite answer"
    assert actual["finite_request"] == reservation and actual["finite_dispatch_claimed"]
    assert claims.count(True) == 1 and claims.count(False) >= 3
    assert len(children) == 1 and children[0].poll() == 0
    assert model._finite_dispatch is None
    root = Path(model.declaration()[0]["private_root"]) / "qtrades-development-inference"
    job = next(root.iterdir())
    dispatch = json.loads((job / "dispatch.json").read_text())
    assert dispatch["cleanup_complete"] and dispatch["private_dispatch_retained"]
    assert dispatch["finite_request"] == reservation and dispatch["finite_dispatch_claimed"]
    with pytest.raises(DevelopmentTransportFailure):
        model.infer_reserved("researcher", packet, profile, reservation)
    assert len(children) == 1
    if os.name == "nt":
        assert actual["placement"]["processors_allowed"] == 2


@pytest.mark.parametrize("phase", ["before_resume", "during_inference"])
def test_expiry_after_child_claim_stops_owned_child_and_retains_charge(finite, monkeypatch, phase):
    model, _, profile, packet, reservation, clock = finite
    original_popen = subprocess.Popen
    original_checkpoint = model._dispatch_checkpoint
    claims, children = [], []
    model.finite_request_verifier = lambda *_, claim=False: claims.append(claim)

    def launch(command, **kwargs):
        child = original_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
        children.append(child)
        return child

    def expire(entered):
        if entered == phase:
            clock[0] = 2000
        original_checkpoint(entered)

    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", launch)
    monkeypatch.setattr(model, "_dispatch_checkpoint", expire)
    with pytest.raises(DevelopmentTransportFailure) as failure:
        model.infer_reserved("researcher", packet, profile, reservation)
    receipt = failure.value.receipt
    assert claims.count(True) == 1
    assert receipt["finite_dispatch_claimed"] and receipt["finite_request"] == reservation
    assert receipt["cleanup_complete"] and receipt["private_dispatch_retained"]
    assert len(children) == 1 and children[0].poll() is not None
    assert failure.value.response is None and model._finite_dispatch is None
