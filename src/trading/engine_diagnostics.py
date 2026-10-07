"""Bounded evidence for the existing engine resource gate; no scheduling authority."""

import os
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from math import isfinite
from threading import RLock
from typing import Any

PRESSURE_POLICY_VERSION = "engine-work-pressure-v3"


@dataclass(frozen=True)
class PressureRecoveryEvaluation:
    """The engine-work component only, never a complete research admission."""

    pressure_allows: bool
    reasons: tuple[str, ...]
    clean_samples: int
    clean_span_seconds: float
    severe_remaining_seconds: float | None
    target_exceedances: int
    observed_samples: int
    blocking_exceedances: int
    last_observed_mono: float | None
    observed_repeated: bool
    observed_severe: bool


class EngineWorkPressurePolicy:
    """Bounded pressure state used by the existing runtime resource owner.

    The 100ms target is advisory. New >=500ms work blocks when at least four of
    the latest twenty observations are >=500ms. Moderate pressure can recover
    with 20 consecutive <500ms observations spanning at least 10 seconds.
    Startup, missing observations, >2s gaps and clock rollback discard recovery
    evidence. Any >=1000ms work retains the 300-second severe hold, including
    renewal by new qualifying repeated pressure during that hold.

    These are user-directed, uncalibrated policy parameters; they do not prove
    financial execution deadlines or safe model coexecution.
    Completed work can share a coarse monotonic timestamp. Nondecreasing times
    count distinct observations; the measured span still bounds recovery.
    Callers must supply explicit monotonic observations; retained wall-clock
    snapshots alone cannot establish an uninterrupted recovery sequence.
    """

    def __init__(self) -> None:
        # The runtime's synchronous controls read this same existing owner.
        self.lock = RLock()
        self._window: deque[float] = deque(maxlen=20)
        self._last_mono: float | None = None
        self._clean_since: float | None = None
        self._clean_count = 0
        self._severe_until = 0.0
        self._recovering = True
        self._pending_severe = False
        self._observed_repeated = False
        self._observed_severe = False

    def _discard_calm(self) -> None:
        self._clean_since = None
        self._clean_count = 0

    def observe(self, elapsed_ms: float | None, now_mono: float) -> None:
        with self.lock:
            self._observed_repeated = False
            self._observed_severe = False
            known_severe = (
                elapsed_ms is not None
                and type(elapsed_ms) in (float, int)
                and isfinite(elapsed_ms)
                and elapsed_ms >= 1000
            )
            if (
                type(now_mono) not in (float, int)
                or not isfinite(now_mono)
                or (self._last_mono is not None and now_mono < self._last_mono)
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
            blocking = elapsed_ms >= 500
            repeated = (
                blocking
                and len(self._window) == 20
                and sum(value >= 500 for value in self._window) >= 4
            )
            severe = elapsed_ms >= 1000
            self._observed_repeated = repeated
            self._observed_severe = severe
            if repeated or severe:
                self._recovering = True
            if severe or (repeated and now_mono < self._severe_until):
                self._severe_until = now_mono + 300
            if blocking:
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
        with self.lock:
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
                reasons.append("insufficient_consecutive_sub500_work")
            if self._pending_severe:
                reasons.append("unanchored_severe_work")
            if remaining is not None and remaining > 0:
                reasons.append("severe_recovery_hold")
            return PressureRecoveryEvaluation(
                not reasons,
                tuple(reasons),
                self._clean_count,
                span,
                remaining,
                sum(value > 100 for value in self._window),
                len(self._window),
                sum(value >= 500 for value in self._window),
                self._last_mono,
                self._observed_repeated,
                self._observed_severe,
            )


class EngineWorkDiagnostics:
    def __init__(self, observation_epoch: str | None = None) -> None:
        self.samples: deque[dict[str, Any]] = deque(maxlen=20)
        self.observation_epoch = observation_epoch or uuid.uuid4().hex
        self.work_observations = 0
        self.triggers = 0
        self.queued_receipts = 0
        self.last_trigger: dict[str, Any] | None = None
        self._last_notice_mono: float | None = None
        self._unreported = 0
        self._peak: dict[str, Any] | None = None

    def record(
        self, sample: dict[str, Any], now_mono: float, *, repeated: bool, severe: bool
    ) -> dict[str, Any] | None:
        self.work_observations += 1
        sample = {
            **sample,
            "work_number": self.work_observations,
            "observed_mono": now_mono,
            "observation_epoch": self.observation_epoch,
            "policy_version": PRESSURE_POLICY_VERSION,
        }
        self.samples.append(sample)
        if not (repeated or severe):
            return None
        self.triggers += 1
        self._unreported += 1
        if self._peak is None or sample["elapsed_ms"] > self._peak["elapsed_ms"]:
            self._peak = sample
        self.last_trigger = {
            "diagnostic_version": "engine-work-v2",
            "policy_version": PRESSURE_POLICY_VERSION,
            "at": sample["at"],
            "trigger_number": self.triggers,
            "repeated_slow_work": repeated,
            "severe_stall": severe,
            "sample": sample,
            "window_samples": len(self.samples),
            "slow_window": [s for s in self.samples if s["elapsed_ms"] > 100],
            "blocking_window": [s for s in self.samples if s["elapsed_ms"] >= 500],
        }
        # One permanent diagnostic receipt per minute at most. All trade records
        # retain their existing policy; only repetitive diagnostic notices coalesce.
        if self._last_notice_mono is not None and now_mono - self._last_notice_mono < 60:
            return None
        notice = {
            **self.last_trigger,
            "triggers_since_receipt": self._unreported,
            "peak_since_receipt": self._peak,
            "severe_cooldown_seconds": 300,
            "moderate_recovery": "20 consecutive <500ms work samples spanning at least 10s",
        }
        self._last_notice_mono = now_mono
        self._unreported, self._peak = 0, None
        self.queued_receipts += 1
        return notice

    def snapshot(self, pressure: PressureRecoveryEvaluation) -> dict[str, Any]:
        return {
            "diagnostic_version": "engine-work-v2",
            "policy_version": PRESSURE_POLICY_VERSION,
            "observation_epoch": self.observation_epoch,
            "observer_pid": os.getpid(),
            "work_observations": self.work_observations,
            "cooldown_remaining_seconds": (
                round(pressure.severe_remaining_seconds, 3)
                if pressure.severe_remaining_seconds is not None
                else None
            ),
            "cooldown_scope": "Severe hold only; moderate recovery requires fresh work evidence",
            "pressure_recovery": asdict(pressure),
            "trigger_count": self.triggers,
            "queued_receipts": self.queued_receipts,
            "unreported_triggers": self._unreported,
            "unreported_peak": self._peak,
            "last_trigger": self.last_trigger,
            "latest_work": self.samples[-1] if self.samples else None,
            "current_window": list(self.samples),
            "retention": "Latest 20 work samples in memory; coalesced trigger receipts in journal",
        }

    def known_latency_window(self, pressure: PressureRecoveryEvaluation, now_mono: float) -> bool:
        """Coverage for finite operator setup only; ordinary admission is unchanged."""
        rows = list(self.samples)
        if (
            len(rows) != 20
            or pressure.observed_samples != 20
            or set(pressure.reasons)
            - {"insufficient_consecutive_sub500_work", "severe_recovery_hold"}
        ):
            return False
        previous: float | None = None
        for index, row in enumerate(rows):
            at, elapsed = row.get("observed_mono"), row.get("elapsed_ms")
            if (
                row.get("observation_epoch") != self.observation_epoch
                or row.get("policy_version") != PRESSURE_POLICY_VERSION
                or type(row.get("work_number")) is not int
                or row["work_number"] != self.work_observations - 19 + index
                or not isinstance(at, (float, int))
                or isinstance(at, bool)
                or not isfinite(at)
                or not isinstance(elapsed, (float, int))
                or isinstance(elapsed, bool)
                or not isfinite(elapsed)
                or elapsed < 0
                or (previous is not None and not 0 <= at - previous <= 2)
            ):
                return False
            previous = at
        if (
            type(now_mono) not in (float, int)
            or not isfinite(now_mono)
            or previous is None
            or not 0 <= now_mono - previous <= 2
            or previous != pressure.last_observed_mono
        ):
            return False
        if pressure.pressure_allows:
            return True
        trigger = self.last_trigger
        sample = trigger.get("sample", {}) if trigger else {}
        elapsed = sample.get("elapsed_ms")
        return bool(
            trigger
            and trigger.get("policy_version") == PRESSURE_POLICY_VERSION
            and sample.get("observation_epoch") == self.observation_epoch
            and type(sample.get("work_number")) is int
            and 0 < sample["work_number"] <= self.work_observations
            and isinstance(elapsed, (float, int))
            and not isinstance(elapsed, bool)
            and isfinite(elapsed)
            and (
                (trigger.get("severe_stall") is True and elapsed >= 1000)
                or (trigger.get("repeated_slow_work") is True and elapsed >= 500)
            )
        )
