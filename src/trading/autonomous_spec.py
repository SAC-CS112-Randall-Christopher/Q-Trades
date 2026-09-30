"""Bounded configurations over reviewed local components, never executable proposals."""

import math
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading.execution_profiles import LEGACY_EXECUTION, PROFILES
from trading.experiment_registry import fingerprint
from trading.paper_strategy import Bar, features

ORIGINALS = frozenset(
    {
        "primary",
        "breakout-v1",
        "responsive-v1",
        "selective-v1",
        "universe-control-v1",
        "universe-wide-v1",
    }
)
TIMING = {
    "short": {
        "feature_seconds": 60,
        "warmup_minutes": 305,
        "maximum_hold": 2700,
        "progress": 600,
        "outcome": 2700,
        "review": 3600,
    },
    "medium": {
        "feature_seconds": 300,
        "warmup_minutes": 1525,
        "maximum_hold": 21600,
        "progress": 7200,
        "outcome": 21600,
        "review": 86400,
    },
    "long": {
        "feature_seconds": 900,
        "warmup_minutes": 4575,
        "maximum_hold": 259200,
        "progress": 86400,
        "outcome": 259200,
        "review": 604800,
    },
}


class LabPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    version: Literal["continuous-paper-lab-v1"] = "continuous-paper-lab-v1"
    slots: int = Field(default=20, ge=10, le=20)
    family_slots: int = Field(default=6, ge=2, le=10)
    independent_slots: int = Field(default=4, ge=2, le=8)
    starting_cash: Literal["50", "100"] = "100"
    execution_profile: str = LEGACY_EXECUTION
    daily_operating_usd: str = "0"
    horizon_seconds: int = Field(default=14400, ge=3600, le=604800)
    coverage_fraction: float = Field(default=0.9, ge=0.8, le=1)
    daily_trials: int = Field(default=8, ge=1, le=24)
    hourly_steps: int = Field(default=120, ge=4, le=240)
    hourly_compute_seconds: int = Field(default=30, ge=1, le=60)
    registry_mib: int = Field(default=512, ge=32, le=512)
    minimum_disk_gib: int = Field(default=5, ge=1, le=20)
    cooldown_seconds: int = Field(default=300, ge=60, le=3600)
    paid_usd: Literal["0"] = "0"
    holding_horizons: tuple[Literal["short", "medium", "long"], ...] = ("short",)

    @model_validator(mode="after")
    def safe(self) -> Self:
        try:
            daily = Decimal(self.daily_operating_usd)
        except InvalidOperation as exc:
            raise ValueError("Operating cost must be a decimal USD amount") from exc
        if not daily.is_finite() or not 0 <= daily <= 10:
            raise ValueError("Declare a finite nonnegative per-account daily cost, at most $10")
        if self.execution_profile not in PROFILES:
            raise ValueError("Use a reviewed execution-cost profile")
        if self.family_slots + self.independent_slots > self.slots - 6:
            raise ValueError(
                "Family and independent allocation must fit around protected originals"
            )
        if not self.holding_horizons or len(set(self.holding_horizons)) != len(
            self.holding_horizons
        ):
            raise ValueError("Declare one to three distinct holding horizons")
        return self


class RuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal["reviewed-lab-rules-v2"] = "reviewed-lab-rules-v2"
    family: Literal["breakout", "range_reversion"] = "breakout"
    lookback: int = Field(default=10, ge=5, le=30)
    volume_multiple: Literal["2"] = "2"
    stop_atr: Literal["1.5"] = "1.5"
    symbol: Literal["BTCUSD"] = "BTCUSD"
    input_version: Literal["closed-minute-bars-v1"] = "closed-minute-bars-v1"
    risk_envelope: Literal["existing-cash-only-hard-stop-v1"] = "existing-cash-only-hard-stop-v1"
    exit_seconds: int = 2700
    progress_seconds: int = 600
    holding_horizon: Literal["short", "medium", "long"] = "short"

    @model_validator(mode="before")
    @classmethod
    def defaults(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("holding_horizon", "short") in TIMING:
            value = dict(value)
            timing = TIMING[value.get("holding_horizon", "short")]
            value.setdefault("exit_seconds", timing["maximum_hold"])
            value.setdefault("progress_seconds", timing["progress"])
        return value

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (
            self.exit_seconds != self.timing["maximum_hold"]
            or self.progress_seconds != self.timing["progress"]
        ):
            raise ValueError("Hold and progress must match the complete frozen horizon preset")
        return self

    @property
    def timing(self) -> dict[str, int]:
        # The original short-term fields retain their literal compatibility. New
        # horizon behavior is versioned by this frozen preset, not independently
        # adjustable hold/progress knobs.
        return dict(TIMING[self.holding_horizon])


class LabProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    policy_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    source: Literal["deterministic", "external"] = "external"
    kind: Literal["independent", "variation", "replication"]
    strategy: RuleSpec
    reference: RuleSpec
    parent_trial: str | None = Field(default=None, max_length=100)
    parent_strategy_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    replication_of: str | None = Field(default=None, max_length=100)
    mechanism: str = Field(min_length=10, max_length=500)
    question: str = Field(min_length=10, max_length=500)
    evidence_bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def semantics(self) -> Self:
        changed = changes(self.reference, self.strategy)
        if self.reference.holding_horizon != self.strategy.holding_horizon:
            raise ValueError("Matched controls require the same coherent holding horizon")
        if self.kind == "variation":
            if not self.parent_trial or self.parent_strategy_sha256 != fingerprint(
                self.reference.model_dump()
            ):
                raise ValueError("A child must identify its exact frozen parent trial and strategy")
            if set(changed) != {"lookback"} or self.strategy.family != self.reference.family:
                raise ValueError("The reviewed child changes exactly one lookback setting")
        elif self.kind == "replication":
            if not self.replication_of or changed:
                raise ValueError("An exact replication must be labelled and match its reference")
        elif self.strategy.family == self.reference.family:
            raise ValueError("Independent exploration must test a genuinely distinct mechanism")
        return self


class LabControl(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal[
        "pause_proposals",
        "resume_proposals",
        "pause_entries",
        "resume_entries",
        "protect",
        "unprotect",
        "retire",
    ]
    target: str | None = Field(default=None, max_length=100)


def changes(parent: RuleSpec, child: RuleSpec) -> dict[str, Any]:
    a, b = parent.model_dump(), child.model_dump()
    return {k: {"from": a[k], "to": b[k]} for k in a if a[k] != b[k]}


def contract(proposal: LabProposal, policy: LabPolicy) -> dict[str, Any]:
    strategy = proposal.strategy.model_dump()
    return {
        "proposal": proposal.model_dump(),
        "changed": changes(proposal.reference, proposal.strategy),
        "unchanged": {
            k: v
            for k, v in strategy.items()
            if k not in changes(proposal.reference, proposal.strategy)
        },
        "inputs": (
            "Contiguous observed closed minute candles, valid metadata and subsequent fresh book"
        ),
        "entry": "Closed-bar breakout with volume/uptrend"
        if proposal.strategy.family == "breakout"
        else "Negative excursion inside the reviewed range gate above modeled round-trip costs",
        "exit": {
            "protection": "Immediate original ATR/trailing and cash hard stops",
            **proposal.strategy.timing,
        },
        "sizing": "Original cash/venue precision, 2.5% entry and 5% aggregate risk ceilings",
        "no_trade": (
            "Unknown/stale/noncontiguous inputs, costs, limits and hard stops remain no-entry"
        ),
        "evaluation": {
            "seconds": max(policy.horizon_seconds, proposal.strategy.timing["review"]),
            "coverage": policy.coverage_fraction,
            "review": "One fixed subsequent window; missing evidence is not failure",
        },
        "costs": {
            "profile": policy.execution_profile,
            "daily_usd": policy.daily_operating_usd,
            "funding_each": policy.starting_cash,
            "fees": "Embedded once in executable equity",
        },
        "criteria": (
            "Positive after-cost account value versus cash, matched "
            "reference and full-period passive: promising; negative value: "
            "unsuccessful; adequate but no economic distinction: "
            "inconclusive; no executed exposure in either account: low information; "
            "gaps/unknown marks: data blocked; hard stop: "
            "risk stopped"
        ),
        "qualification": "Exploratory paper only; CP7 28-day/human role policy unchanged",
    }


def rule_feature(bars: list[Bar], now: float, spec: RuleSpec, profile: str) -> dict[str, Any]:
    timing = spec.timing
    latest = bars[-1].close_ms / 1000 if bars else None
    if timing["feature_seconds"] > 60:
        interval = timing["feature_seconds"] * 1000
        groups: dict[int, list[Bar]] = {}
        for bar in bars[-9000:]:
            groups.setdefault(bar.open_ms // interval, []).append(bar)
        bars = [
            Bar(
                key * interval,
                rows[0].open,
                max(b.high for b in rows),
                min(b.low for b in rows),
                rows[-1].close,
                sum((b.volume for b in rows), Decimal(0)),
                key * interval + interval - 1,
            )
            for key, rows in groups.items()
            if len(rows) == interval // 60000
            and all(b.open_ms - a.open_ms == 60000 for a, b in zip(rows, rows[1:], strict=False))
            and rows[0].open_ms == key * interval
        ]
    base = features(
        bars,
        now,
        "breakout-v1",
        rules={
            "lookback": spec.lookback,
            "volume_multiple": spec.volume_multiple,
            "stop_atr": spec.stop_atr,
            "bar_seconds": timing["feature_seconds"],
        },
    )
    if spec.family == "range_reversion" and "atr" in base and len(bars) >= 305:
        from trading.numerical_candidates import feature_value

        quotes = [
            {"minute": b.open_ms // 60000, "mid": float(b.close), "at": b.close_ms / 1000}
            for b in bars[-spec.lookback - 1 :]
        ]
        excursion = feature_value(quotes, "range_reversion", lookback=spec.lookback)
        cost = float(
            2 * (PROFILES[profile].fee("BTCUSD") + Decimal(PROFILES[profile].slippage)) * 10000
        )
        usable = (
            excursion is not None
            and math.isfinite(excursion)
            and excursion > cost
            and 0 < now * 1000 - bars[-1].close_ms <= max(90000, timing["feature_seconds"] * 1000)
            and all(
                b.open_ms - a.open_ms == timing["feature_seconds"] * 1000
                for a, b in zip(bars, bars[1:], strict=False)
            )
        )
        base = {
            **base,
            "eligible": usable,
            "reason": "Range-conditioned excursion clears modeled costs"
            if usable
            else "No supported after-cost range excursion",
            "excursion_bps": excursion,
            "modeled_hurdle_bps": cost,
        }
    base["version"] = "lab-rule-" + fingerprint(spec.model_dump())[:24]
    base["input_available_at"] = latest
    # A fresh minute observation must confirm that no unobserved tail or future
    # candle is being used, even when the feature candle spans fifteen minutes.
    if latest is None or not 0 < now - latest <= 90:
        base.update(eligible=False, reason="Current minute coverage is stale or unavailable")
    base["timing"] = timing
    if spec.holding_horizon != "short":
        base["ema20_trend"] = base.pop("ema20_5m", None)
        base["trend_seconds"] = timing["feature_seconds"] * 5
        base["reason"] = (
            base.get("reason", "")
            .replace("Five-minute", "Aggregated trend")
            .replace("five-minute", "aggregated trend")
        )
    return base
