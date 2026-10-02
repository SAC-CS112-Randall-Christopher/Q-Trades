"""Bounded evidence for the existing engine resource gate; no scheduling authority."""

from collections import deque
from typing import Any


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
