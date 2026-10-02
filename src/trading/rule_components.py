"""Single causal adapter for the reviewed optional frozen memory entry filter."""

from typing import Any

from trading.autonomous_spec import RuleSpec, rule_feature
from trading.evidence_runtime import frozen_bars
from trading.memory_quality import filtered_feature
from trading.paper_strategy import Bar
from trading.pattern_memory import descriptor
from trading.research_evidence import book_features


def reviewed_feature(
    bars: list[Bar], now: float, spec: RuleSpec, profile: str, frame: dict[str, Any] | None = None
) -> dict[str, Any]:
    base = rule_feature(bars, now, spec, profile)
    component = spec.entry_filter
    if component is None:
        return base
    inputs = {
        "bars": frozen_bars(bars[-11:], now),
        "cutoff": now,
        "context": {"book": book_features(frame, now) if frame else None},
        "data_mode": component.artifact["evidence_kind"],
    }
    d = descriptor(inputs["bars"], now, inputs["context"], inputs["data_mode"])
    result = filtered_feature(base, d, component.artifact, now)
    result.update(memory_input=inputs, memory_descriptor=d, component_version=component.version)
    result["memory_evidence"]["marginal_daily_usd"] = component.marginal_daily_usd
    return result
