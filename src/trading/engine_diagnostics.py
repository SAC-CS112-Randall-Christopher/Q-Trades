"""Bounded evidence for the existing engine resource gate; no scheduling authority."""

from collections import deque
from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class PressureRecoveryEvaluation:
    """Hypothetical pressure decision, never a complete research admission."""

    pressure_would_allow: bool
    reasons: tuple[str, ...]
    clean_samples: int
    clean_span_seconds: float
    severe_remaining_seconds: float | None


class ModerateRecoveryCandidate:
    """Offline proposal only; no runtime, configuration or dispatch integration.

    Keep the existing 100ms/4-of-20 and 1000ms trigger thresholds. Moderate
    pressure can recover with 20 consecutive <=100ms full-work observations
    spanning at least 10 seconds. Startup, missing observations, >2s gaps and
    clock rollback discard calm evidence. Severe pressure retains the existing
    300-second hold, including renewal by new qualifying pressure during it.

    The 10s/2s recovery bounds are proposed QA parameters, not established
    financial requirements or demonstrated installed coexistence limits.
    Callers must supply explicit monotonic observations; retained wall-clock
    snapshots alone cannot establish an uninterrupted recovery sequence.
    """

    def __init__(self) -> None:
        self._window: deque[float] = deque(maxlen=20)
        self._last_mono: float | None = None
        self._clean_since: float | None = None
        self._clean_count = 0
        self._severe_until = 0.0
        self._recovering = True
        self._pending_severe = False

    def _discard_calm(self) -> None:
        self._clean_since = None
        self._clean_count = 0

    def observe(self, elapsed_ms: float | None, now_mono: float) -> None:
        known_severe = (
            elapsed_ms is not None
            and type(elapsed_ms) in (float, int)
            and isfinite(elapsed_ms)
            and elapsed_ms >= 1000
        )
        if (
            type(now_mono) not in (float, int)
            or not isfinite(now_mono)
            or (self._last_mono is not None and now_mono <= self._last_mono)
        ):
            self._discard_calm()
            self._recovering = True
            # A duration can prove severity even when its clock cannot anchor
            # recovery. The next trusted observation must start the full hold.
            self._pending_severe = self._pending_severe or known_severe
            return
        if self._last_mono is not None and now_mono - self._last_mono > 2:
            self._discard_calm()
            self._recovering = True
        self._last_mono = now_mono
        if self._pending_severe:
            self._severe_until = max(self._severe_until, now_mono + 300)
            self._pending_severe = False
        if (
            elapsed_ms is None
            or type(elapsed_ms) not in (float, int)
            or not isfinite(elapsed_ms)
            or elapsed_ms < 0
        ):
            self._discard_calm()
            self._recovering = True
            return
        self._window.append(elapsed_ms)
        repeated = (
            elapsed_ms > 100
            and len(self._window) == 20
            and sum(value > 100 for value in self._window) >= 4
        )
        severe = elapsed_ms >= 1000
        if repeated or severe:
            self._recovering = True
        if severe or (repeated and now_mono < self._severe_until):
            self._severe_until = now_mono + 300
        if elapsed_ms > 100:
            self._discard_calm()
        else:
            if self._clean_since is None:
                self._clean_since = now_mono
            self._clean_count = min(20, self._clean_count + 1)
            if (
                self._clean_count == 20
                and now_mono - self._clean_since >= 10
                and now_mono >= self._severe_until
            ):
                self._recovering = False

    def evaluate(self, now_mono: float) -> PressureRecoveryEvaluation:
        reasons: list[str] = []
        valid_clock = (
            type(now_mono) in (float, int)
            and isfinite(now_mono)
            and (self._last_mono is None or now_mono >= self._last_mono)
        )
        fresh = valid_clock and self._last_mono is not None and now_mono - self._last_mono <= 2
        # Coverage ends at the last completed work, not at the evaluation time.
        span = (
            self._last_mono - self._clean_since
            if self._last_mono is not None and self._clean_since is not None
            else 0.0
        )
        remaining = max(0.0, self._severe_until - now_mono) if valid_clock else None
        if not valid_clock:
            reasons.append("invalid_or_regressed_clock")
        if not fresh:
            reasons.append("missing_or_stale_work")
        if self._recovering:
            reasons.append("insufficient_consecutive_calm_work")
        if self._pending_severe:
            reasons.append("unanchored_severe_work")
        if remaining is not None and remaining > 0:
            reasons.append("severe_recovery_hold")
        return PressureRecoveryEvaluation(
            not reasons, tuple(reasons), self._clean_count, span, remaining
        )


class EngineWorkDiagnostics:
    def __init__(self) -> None:
        self.samples: deque[dict[str, Any]] = deque(maxlen=20)
        self.triggers = 0
        self.queued_receipts = 0
        self.last_trigger: dict[str, Any] | None = None
        self._last_notice_mono: float | None = None
        self._unreported = 0
        self._peak: dict[str, Any] | None = None

    def record(
        self, sample: dict[str, Any], now_mono: float, *, repeated: bool, severe: bool
    ) -> dict[str, Any] | None:
        self.samples.append(sample)
        if not (repeated or severe):
            return None
        self.triggers += 1
        self._unreported += 1
        if self._peak is None or sample["elapsed_ms"] > self._peak["elapsed_ms"]:
            self._peak = sample
        self.last_trigger = {
            "diagnostic_version": "engine-work-v1",
            "at": sample["at"],
            "trigger_number": self.triggers,
            "repeated_slow_work": repeated,
            "severe_stall": severe,
            "sample": sample,
            "window_samples": len(self.samples),
            "slow_window": [s for s in self.samples if s["elapsed_ms"] > 100],
        }
        # One permanent diagnostic receipt per minute at most. All trade records
        # retain their existing policy; only repetitive diagnostic notices coalesce.
        if self._last_notice_mono is not None and now_mono - self._last_notice_mono < 60:
            return None
        notice = {
            **self.last_trigger,
            "triggers_since_receipt": self._unreported,
            "peak_since_receipt": self._peak,
            "cooldown_seconds": 300,
        }
        self._last_notice_mono = now_mono
        self._unreported, self._peak = 0, None
        self.queued_receipts += 1
        return notice

    def snapshot(self, now_mono: float, constrained_until: float) -> dict[str, Any]:
        return {
            "diagnostic_version": "engine-work-v1",
            "cooldown_remaining_seconds": round(max(0, constrained_until - now_mono), 3),
            "trigger_count": self.triggers,
            "queued_receipts": self.queued_receipts,
            "unreported_triggers": self._unreported,
            "unreported_peak": self._peak,
            "last_trigger": self.last_trigger,
            "latest_work": self.samples[-1] if self.samples else None,
            "current_window": list(self.samples),
            "retention": "Latest 20 work samples in memory; coalesced trigger receipts in journal",
        }
