"""Explicit finite development override fixtures; no model, services or database calls."""

from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest
from test_peft_development import declared as declared

from trading.local_role_model import LocalRoles, development_latency_observation
from trading.peft_profile import PROFILE, digest
from trading.peft_role_model import PeftDevelopmentRoles


def protected_status():
    return {
        "generated_at": "Explicit isolated fixture",
        "paper": {
            "running": True,
            "stale": False,
            "error": None,
            "research_constrained": True,
            "journal": {
                "available": True,
                "balanced": True,
                "status": "balanced",
                "error": None,
                "audit_age_seconds": 3,
                "imbalanced_events": 0,
                "projection_errors": [],
                "revision": 42,
            },
            "performance": {
                "financial_readback": {
                    "available": True,
                    "status": "balanced",
                    "error": None,
                    "audit_age_seconds": 3,
                },
                "resource_guard": {
                    "policy_version": "engine-work-pressure-v3",
                    "blocking_conditions": ["engine_work_recovery"],
                    "pressure_recovery": {
                        "pressure_allows": False,
                        "reasons": ["severe_recovery_hold"],
                        "severe_remaining_seconds": 250,
                    },
                    "last_trigger": {"sample": {"elapsed_ms": 1403, "thread_cpu_ms": 31.25}},
                },
            },
            "storage": {"disk_free_gib": 48, "capture_error": None},
            "research_evidence": {
                "state": "recording",
                "queue_dropped": 140214,
                "storage": {
                    "state": "recording",
                    "free_bytes": 300_000_000_000,
                    "temporary_bytes": 140_000_000_000,
                    "research_bytes": 20_000_000_000,
                    "plan": {
                        "version": "research-tiers-v2",
                        "temporary_bytes": 400_000_000_000,
                        "research_bytes": 100_000_000_000,
                        "free_reserve_bytes": 5 * 1024**3,
                        "scratch_bytes": 128 * 1024**2,
                    },
                },
            },
        },
    }


def diagnostic_packet():
    return {
        "question": "Performance measurement only",
        "evidence": {"e2": {"purpose": "performance_diagnostic", "research_eligible": False}},
    }


@pytest.mark.parametrize("reason", ["severe_recovery_hold", "insufficient_consecutive_sub500_work"])
def test_latency_only_is_observed_and_removed_without_spoofing_original_guard(reason):
    original = protected_status()
    original["paper"]["performance"]["resource_guard"]["pressure_recovery"]["reasons"] = [reason]
    before = deepcopy(original)
    observed = development_latency_observation(original)
    assert observed["admitted"] is True and observed["research_constrained"] is True
    assert observed["effective_latency_block_removed"] is True
    assert observed["latency_blockers_removed"] == ["engine_work_recovery"]
    assert observed["resource_guard"]["pressure_recovery"]["reasons"] == [reason]
    assert original == before


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("paper", "running"), False),
        (("paper", "stale"), True),
        (("paper", "error"), "feed failed"),
        (("paper", "journal", "balanced"), False),
        (("paper", "journal", "available"), False),
        (("paper", "journal", "audit_age_seconds"), 120),
        (("paper", "journal", "audit_age_seconds"), None),
        (("paper", "journal", "projection_errors"), ["mismatch"]),
        (("paper", "performance", "financial_readback", "status"), "unavailable"),
        (
            ("paper", "performance", "resource_guard", "blocking_conditions"),
            ["engine_work_recovery", "local_capture_disk_space"],
        ),
        (
            ("paper", "performance", "resource_guard", "blocking_conditions"),
            ["unknown_future_guard"],
        ),
        (("paper", "performance", "resource_guard", "blocking_conditions"), None),
        (("paper", "performance", "resource_guard", "policy_version"), "unknown-policy"),
        (("paper", "storage", "capture_error"), "raw capture failed"),
        (("paper", "storage", "disk_free_gib"), 4.9),
        (("paper", "research_evidence", "state"), "unavailable"),
        (("paper", "research_evidence", "storage", "state"), "paused"),
        (("paper", "research_evidence", "storage", "free_bytes"), 5 * 1024**3),
        (("paper", "research_evidence", "storage", "temporary_bytes"), 400_000_000_000),
        (("paper", "research_evidence", "storage", "research_bytes"), 100_000_000_000),
        (("paper", "research_evidence", "storage", "plan", "temporary_bytes"), 500_000_000_000),
    ],
)
def test_nonlatency_or_missing_protection_refuses(path, value):
    status = protected_status()
    target = status
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    observed = development_latency_observation(status)
    assert observed["admitted"] is False and observed["reasons"]


def test_actual_status_http_boundary_preserves_default_latency_veto(tmp_path, monkeypatch):
    calls = []
    real_client = httpx.Client

    def dispatch(request):
        calls.append((request.method, str(request.url)))
        return httpx.Response(200, json=protected_status())

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["timeout"] == 8
        return real_client(transport=httpx.MockTransport(dispatch), **kwargs)

    monkeypatch.setattr("trading.local_role_model.httpx.Client", client)
    model = LocalRoles(tmp_path)
    with pytest.raises(ValueError, match="constrains optional"):
        model.paper_guard()
    assert model.development_latency_guard()["admitted"] is True
    assert calls == [("GET", "http://127.0.0.1:8780/api/status")] * 2
    assert model.policy() == {"enabled": False}


def test_bound_development_request_preserves_profile_and_all_guard_phases(declared, monkeypatch):
    default, _, _ = declared
    frozen_profile = default.declaration()[2]
    model = PeftDevelopmentRoles(default.directory, development_latency_override=True)
    packet = diagnostic_packet()
    observed = Mock(side_effect=lambda: development_latency_observation(protected_status()))
    monkeypatch.setattr("trading.peft_role_model.LocalRoles.development_latency_guard", observed)
    default_guard = Mock(side_effect=AssertionError("Hidden default latency veto"))
    monkeypatch.setattr("trading.peft_role_model.LocalRoles.paper_guard", default_guard)
    with pytest.raises(ValueError, match="unused bound request"):
        model.development_admit("researcher")
    model.authorize_latency_measurement(
        "researcher", packet, request_id="performance-0001", authorized=True
    )
    assert model.development_admit("researcher") == frozen_profile
    assert digest(model.declaration()[2]) == digest(frozen_profile)
    assert PROFILE["max_rss_bytes"] == 24 * 1024**3
    model._consume_latency_authorization("researcher", packet)
    for phase in ("before_dispatch", "during_inference", "after_response"):
        assert model._paper_guard(phase)["admitted"] is True
    assert [row["phase"] for row in model.guard_observations()] == [
        "admission",
        "before_dispatch",
        "during_inference",
        "after_response",
    ]
    default_guard.assert_not_called()
    with pytest.raises(ValueError, match="missing, used or mismatched"):
        model._consume_latency_authorization("researcher", packet)
    with pytest.raises(ValueError, match="no operating qualification"):
        model.admit("researcher")


def test_authorization_is_explicit_diagnostic_exact_packet_and_nonresettable(tmp_path):
    model = PeftDevelopmentRoles(tmp_path, development_latency_override=True)
    packet = diagnostic_packet()
    with pytest.raises(ValueError, match="Explicit single"):
        model.authorize_latency_measurement(
            "researcher", packet, request_id="performance-0001", authorized=False
        )
    with pytest.raises(ValueError, match="Explicit single"):
        model.authorize_latency_measurement(
            "researcher", {"evidence": {}}, request_id="performance-0001", authorized=True
        )
    model.authorize_latency_measurement(
        "researcher", packet, request_id="performance-0001", authorized=True
    )
    with pytest.raises(ValueError, match="missing, used or mismatched"):
        model._consume_latency_authorization("reviewer", packet)
    with pytest.raises(ValueError, match="missing, used or mismatched"):
        model._consume_latency_authorization("researcher", packet | {"question": "changed"})
    with pytest.raises(ValueError, match="replaced or reset"):
        model.authorize_latency_measurement(
            "researcher", packet, request_id="performance-0002", authorized=True
        )
    model._consume_latency_authorization("researcher", packet)


def test_current_nonlatency_failure_during_inference_is_retained_and_refused(tmp_path, monkeypatch):
    model = PeftDevelopmentRoles(tmp_path, development_latency_override=True)
    packet = diagnostic_packet()
    model.authorize_latency_measurement(
        "researcher", packet, request_id="performance-0001", authorized=True
    )
    model._consume_latency_authorization("researcher", packet)
    status = protected_status()
    status["paper"]["journal"]["available"] = False
    monkeypatch.setattr(
        "trading.peft_role_model.LocalRoles.development_latency_guard",
        lambda _: development_latency_observation(status),
    )
    with pytest.raises(ValueError, match="journal_unavailable"):
        model._paper_guard("during_inference")
    retained = model.guard_observations()
    assert retained[-1]["phase"] == "during_inference" and retained[-1]["admitted"] is False
    assert retained[-1]["journal"]["available"] is False
    retained[-1]["journal"]["available"] = True
    assert model.guard_observations()[-1]["journal"]["available"] is False


@pytest.mark.parametrize("failure", ["financial_monitoring", "memory_reserve"])
def test_infer_refuses_protected_failure_before_any_child_or_private_job(
    declared, monkeypatch, failure
):
    default, _, _ = declared
    model = PeftDevelopmentRoles(default.directory, development_latency_override=True)
    packet = diagnostic_packet()
    model.authorize_latency_measurement(
        "researcher", packet, request_id="performance-0001", authorized=True
    )
    profile = model.declaration()[2]
    status = protected_status()
    if failure == "financial_monitoring":
        status["paper"]["performance"]["financial_readback"]["available"] = False
    else:
        monkeypatch.setattr("trading.peft_role_model.available_memory", lambda: 0)
    monkeypatch.setattr(
        "trading.peft_role_model.LocalRoles.development_latency_guard",
        lambda _: development_latency_observation(status),
    )
    launched = Mock(side_effect=AssertionError("No actual or procedural child authorized"))
    monkeypatch.setattr("trading.peft_role_model.subprocess.Popen", launched)
    with pytest.raises(ValueError):
        model.infer("researcher", packet, profile)
    launched.assert_not_called()
    assert not (model.directory / "qtrades-development-inference").exists()
    with pytest.raises(ValueError, match="missing, used or mismatched"):
        model.infer("researcher", packet, profile)
    launched.assert_not_called()
