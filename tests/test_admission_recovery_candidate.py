"""Offline policy comparison. No operating requests, inference or guard substitution."""

from collections import deque

import httpx
import pytest

from trading.engine_diagnostics import EngineWorkDiagnostics, ModerateRecoveryCandidate
from trading.local_role_model import LocalRoles
from trading.tiered_runtime import TieredPaperRuntime


def current_policy():
    runtime = object.__new__(TieredPaperRuntime)
    runtime._loop_ms = deque(maxlen=1000)
    runtime._constrained_until = 0.0
    runtime._work_diagnostics = EngineWorkDiagnostics()
    runtime._notice_queue = []
    return runtime


def observe_both(current, candidate, values, start=1000.0, step=0.5):
    for i, value in enumerate(values):
        now = start + i * step
        current.observe_engine_work(value, now)
        candidate.observe(value, now)
    return now


def warm(candidate, start=1000.0):
    for i in range(21):
        candidate.observe(50, start + i * 0.5)
    assert candidate.evaluate(start + 10).pressure_would_allow
    return start + 10


def test_normal_work_startup_requires_measured_count_and_coverage():
    current, candidate = current_policy(), ModerateRecoveryCandidate()
    assert current._constrained_until == 0
    assert not candidate.evaluate(1000).pressure_would_allow
    now = observe_both(current, candidate, [50] * 20, step=0.1)
    assert current._constrained_until == 0
    assert not candidate.evaluate(now).pressure_would_allow
    # Merely waiting without new observations cannot supply measured coverage.
    assert not candidate.evaluate(now + 10).pressure_would_allow
    now = observe_both(current, candidate, [50] * 101, start=now + 0.1, step=0.1)
    assert candidate.evaluate(now).pressure_would_allow
    assert len(candidate._window) == 20
    assert candidate.evaluate(now).clean_samples == 20


def test_moderate_burst_has_earlier_hypothetical_recovery_without_threshold_change():
    current, candidate = current_policy(), ModerateRecoveryCandidate()
    now = observe_both(current, candidate, [50] * 21)
    now = observe_both(current, candidate, [150] * 4, start=now + 0.5)
    trigger = now
    assert current._constrained_until == trigger + 300
    assert not candidate.evaluate(now).pressure_would_allow
    now = observe_both(current, candidate, [50] * 20, start=now + 0.5)
    assert not candidate.evaluate(now).pressure_would_allow  # Only 9.5s calm coverage.
    now = observe_both(current, candidate, [50], start=now + 0.5)
    assert now - trigger == 10.5
    assert candidate.evaluate(now).pressure_would_allow
    assert current._constrained_until - now == 289.5
    assert current._work_diagnostics.triggers == 1  # Fast work never renews recovery.


@pytest.mark.parametrize("duration", [100.0, 100.001, 999.999])
def test_isolated_jitter_does_not_create_a_new_moderate_trigger(duration):
    current, candidate = current_policy(), ModerateRecoveryCandidate()
    now = observe_both(current, candidate, [50] * 21)
    now = observe_both(current, candidate, [duration], start=now + 0.5)
    assert current._constrained_until == 0
    assert candidate.evaluate(now).pressure_would_allow


def test_sustained_pressure_never_recovers_and_current_policy_keeps_renewing():
    current, candidate = current_policy(), ModerateRecoveryCandidate()
    now = observe_both(current, candidate, [150] * 200)
    assert current._constrained_until == now + 300
    assert current._work_diagnostics.triggers == 181
    assert not candidate.evaluate(now).pressure_would_allow
    assert candidate.evaluate(now).clean_samples == 0


def test_severe_hold_survives_calm_and_requires_fresh_work_after_full_300_seconds():
    current, candidate = current_policy(), ModerateRecoveryCandidate()
    now = observe_both(current, candidate, [1000], start=1000)
    now = observe_both(current, candidate, [50] * 599, start=now + 0.5)
    assert now == 1299.5
    assert not candidate.evaluate(now).pressure_would_allow
    assert candidate.evaluate(now).severe_remaining_seconds == 0.5
    # Calendar expiry cannot release a candidate before a fresh completed work observation.
    assert not candidate.evaluate(1300).pressure_would_allow
    now = observe_both(current, candidate, [50], start=1300)
    assert candidate.evaluate(now).pressure_would_allow
    assert current._constrained_until == now


def test_moderate_pressure_during_severe_recovery_cannot_downgrade_or_shorten_hold():
    current, candidate = current_policy(), ModerateRecoveryCandidate()
    now = observe_both(current, candidate, [50] * 21)
    now = observe_both(current, candidate, [1000], start=now + 0.5)
    now = observe_both(current, candidate, [150] * 4, start=now + 0.5)
    assert candidate.evaluate(now).severe_remaining_seconds == 300
    assert current._constrained_until == now + 300
    now = observe_both(current, candidate, [50] * 21, start=now + 0.5)
    assert not candidate.evaluate(now).pressure_would_allow
    assert "severe_recovery_hold" in candidate.evaluate(now).reasons
    candidate.observe(2000, now + 0.5)
    assert candidate.evaluate(now + 0.5).severe_remaining_seconds == 300


@pytest.mark.parametrize("missing", [None, -1.0, float("nan"), float("inf"), True])
def test_missing_or_invalid_duration_discards_recovery_evidence(missing):
    candidate = ModerateRecoveryCandidate()
    now = warm(candidate)
    candidate.observe(missing, now + 0.5)
    assert not candidate.evaluate(now + 0.5).pressure_would_allow
    for i in range(20):
        candidate.observe(50, now + 1 + i * 0.5)
    assert not candidate.evaluate(now + 10.5).pressure_would_allow
    candidate.observe(50, now + 11)
    assert candidate.evaluate(now + 11).pressure_would_allow


def test_gaps_cannot_join_disconnected_calm_runs_and_severe_hold_is_retained():
    candidate = ModerateRecoveryCandidate()
    now = warm(candidate)
    assert not candidate.evaluate(now + 2.001).pressure_would_allow
    candidate.observe(50, now + 2.001)
    assert candidate.evaluate(now + 2.001).clean_samples == 1
    assert not candidate.evaluate(now + 2.001).pressure_would_allow
    candidate.observe(1000, now + 3)
    candidate.observe(None, now + 4)
    candidate.observe(50, now + 30)
    assert candidate.evaluate(now + 30).severe_remaining_seconds == 273


@pytest.mark.parametrize("bad_clock", [1010.0, 1009.0, float("nan"), float("inf"), True])
def test_untrusted_clock_cannot_discard_a_known_severe_stall(bad_clock):
    candidate = ModerateRecoveryCandidate()
    now = warm(candidate)
    candidate.observe(2000, bad_clock)
    assert "unanchored_severe_work" in candidate.evaluate(now).reasons
    candidate.observe(50, now + 0.5)
    assert candidate.evaluate(now + 0.5).severe_remaining_seconds == 300
    for i in range(21):
        candidate.observe(50, now + 1 + i * 0.5)
    assert not candidate.evaluate(now + 11).pressure_would_allow


@pytest.mark.parametrize("clock", [1009.0, float("nan"), float("inf"), True])
def test_invalid_evaluation_clock_never_reports_admission(clock):
    candidate = ModerateRecoveryCandidate()
    warm(candidate)
    result = candidate.evaluate(clock)
    assert not result.pressure_would_allow
    assert "invalid_or_regressed_clock" in result.reasons
    assert result.severe_remaining_seconds is None


def test_repeated_oscillation_cannot_pool_calm_samples_across_interruptions():
    current, candidate = current_policy(), ModerateRecoveryCandidate()
    now = observe_both(current, candidate, [50] * 21)
    now = observe_both(current, candidate, [150] * 4, start=now + 0.5)
    for _ in range(10):
        now = observe_both(current, candidate, [50] * 19, start=now + 0.5)
        assert not candidate.evaluate(now).pressure_would_allow
        now = observe_both(current, candidate, [150], start=now + 0.5)
        assert not candidate.evaluate(now).pressure_would_allow
    # Each recovered epoch must acquire its own complete calm run.
    now = observe_both(current, candidate, [50] * 21, start=now + 0.5)
    assert candidate.evaluate(now).pressure_would_allow
    now = observe_both(current, candidate, [150] * 4, start=now + 0.5)
    assert not candidate.evaluate(now).pressure_would_allow


@pytest.mark.parametrize(
    "fault", ["imbalance", "missing", "expired", "error", "refresh", "disk", "recording"]
)
def test_hypothetical_pressure_recovery_cannot_remove_other_runtime_blocks(monkeypatch, fault):
    candidate = ModerateRecoveryCandidate()
    warm(candidate)
    assert candidate.evaluate(1010).pressure_would_allow
    runtime = current_policy()
    runtime.disk_free = 10 * 1024**3
    runtime._capture_failure = None
    runtime._readback_error = None
    runtime._readback_sample = None
    runtime._readback_audit_mono = 1000
    runtime.receipts = {"balanced": True}
    monkeypatch.setattr("trading.tiered_runtime.time.monotonic", lambda: 1010)
    assert not runtime.constrained()
    if fault == "imbalance":
        runtime.receipts["balanced"] = False
    elif fault == "missing":
        runtime._readback_audit_mono = None
    elif fault == "expired":
        runtime._readback_audit_mono = 890  # Exactly120s closes the financial monitor.
    elif fault == "error":
        runtime._readback_error = "unavailable"
    elif fault == "refresh":
        runtime._readback_sample = {"refresh_errors": {"recent": "unavailable"}}
    elif fault == "disk":
        runtime.disk_free = 5 * 1024**3 - 1
    elif fault == "recording":
        runtime._capture_failure = "append unavailable"
    assert runtime.constrained()


@pytest.mark.parametrize(
    "change",
    [{"running": False}, {"error": "unavailable"}, {"stale": True}, {"research_constrained": True}],
)
def test_offline_candidate_does_not_change_complete_local_roles_guard(
    tmp_path, monkeypatch, change
):
    candidate = ModerateRecoveryCandidate()
    warm(candidate)
    assert candidate.evaluate(1010).pressure_would_allow
    paper = {"running": True, "error": None, "stale": False, "research_constrained": False}
    paper.update(change)
    real_client = httpx.Client
    requests = []

    def dispatch(request):
        requests.append(str(request.url))
        return httpx.Response(200, json={"paper": paper})

    monkeypatch.setattr(
        "trading.local_role_model.httpx.Client",
        lambda **kw: real_client(transport=httpx.MockTransport(dispatch), **kw),
    )
    with pytest.raises(ValueError):
        LocalRoles(tmp_path).paper_guard()
    assert requests == ["http://127.0.0.1:8780/api/status"]  # Mocked; no HTTP reaches a service.
