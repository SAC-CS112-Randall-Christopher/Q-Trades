"""Bounded causal replay in a disposable child; never a second financial engine."""

import math
import time
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
from typing import Any, cast

from trading.evidence_runtime import feature_reproduction
from trading.execution_profiles import PROFILES
from trading.market import parse_book
from trading.paper_economics import sample
from trading.paper_engine import PaperEngine
from trading.research_evidence import VERSION as EVIDENCE_VERSION
from trading.research_evidence import digest

VERSION = "causal-execution-replay-v1"
SCENARIOS = ("recorded", "delay-3s-v1", "condition-cost-v1")
MAX_RECORDS = 32
MAX_INPUT_BYTES = 16 * 1024**2
MAX_RESULT_BYTES = 512 * 1024
CONTRACT = {
    "version": VERSION,
    "records_max": MAX_RECORDS,
    "result_bytes_max": MAX_RESULT_BYTES,
    "scenarios": SCENARIOS,
    "delayed": "At least three seconds before later-book acceptance; expiry remains 15 seconds",
    "condition_cost": (
        "If any currently observed book spread >=10 bps or either side visible depth <100 USD, "
        "all profiles for that tick use at least 5 bps adverse slippage "
        "and at most 5% participation"
    ),
    "cost_basis": "Existing engine embeds fees/spread/depth once; no deduction from net labels",
    "continuity": "Exact recorded state chain, allowing only recorded study_bars/book_sequences",
    "gap": "Never insert observations, assume intra-gap fills, or reset to the recorded account",
    "limits": "One child, two processors, IDLE priority, 256 MiB, 25 seconds, eight queued runs",
    "fee_source": "https://www.binance.us/fees",
    "venue_contract": "https://docs.binance.us/",
    "checked_at": "2026-09-30",
    "assumptions": "Delay/condition thresholds are modeled stresses, not measured venue behavior",
    "unsupported": "Maker queue, base/BNB fees, hidden liquidity and own market impact",
}


def source_hashes() -> dict[str, str]:
    import hashlib

    return {
        name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
        for name in (
            "paper_engine.py",
            "paper_strategy.py",
            "execution_profiles.py",
            "numerical_candidates.py",
            "memory_quality.py",
            "execution_replay.py",
            "market.py",
            "paper_economics.py",
            "replay_lab.py",
            "replay_worker.py",
            "research_acquisition.py",
        )
    }


def hydrated_frames(packet: dict[str, Any]) -> dict[str, Any]:
    at = packet["at"]
    if not isinstance(at, (int, float)) or isinstance(at, bool) or not math.isfinite(at):
        raise ValueError("Invalid decision time")
    result = {}
    for symbol, original in packet["frames"].items():
        frame = deepcopy(original)
        observed = frame.get("observed")
        if (
            not isinstance(observed, (int, float))
            or isinstance(observed, bool)
            or not math.isfinite(observed)
            or observed > at
        ):
            raise ValueError("A book was not available at the decision cutoff")
        frame["book"] = parse_book(frame["raw"], limit=1000)
        frame["rules"] = {k: D(v) for k, v in frame["rules"].items()}
        if any(not value.is_finite() or value < 0 for value in frame["rules"].values()) or any(
            frame["rules"][key] <= 0 for key in ("step", "tick", "max_qty", "max_price")
        ):
            raise ValueError("Invalid recorded precision or order rules")
        result[symbol] = frame
    return result


def financial_chain(state: dict[str, Any]) -> str:
    return digest({k: v for k, v in state.items() if k not in {"study_bars", "book_sequences"}})


def data_mode(packet: dict[str, Any]) -> str:
    sources = [str(f.get("source", "")) for f in packet["frames"].values()]
    synthetic = ["synthetic" in source for source in sources]
    if synthetic and all(synthetic):
        return "synthetic"
    if any(synthetic):
        return "mixed"
    return "paper_observations" if sources and all(sources) else "unknown"


def ordered_state(packet: dict[str, Any]) -> dict[str, Any]:
    state = deepcopy(packet["state_before"])
    order = packet.get("dispatch_accounts")
    if order is not None:
        if (
            not isinstance(order, list)
            or len(order) != len(set(order))
            or set(order) != set(state["accounts"])
        ):
            raise ValueError("Recorded account dispatch membership is invalid")
        state["accounts"] = {name: state["accounts"][name] for name in order}
    return cast(dict[str, Any], state)


def checked_packet(record: dict[str, Any], current: dict[str, str]) -> dict[str, Any]:
    packet = record["payload"]
    if digest(packet) != record["sha256"]:
        raise ValueError("Input hash differs; replay cannot substitute evidence")
    if packet.get("schema") != EVIDENCE_VERSION or packet.get("kind") != "decision":
        raise ValueError("A recorded decision bundle is required")
    required = {"paper_engine.py", "paper_strategy.py", "execution_profiles.py"}
    if any(a.get("numerical_artifact") for a in packet["state_before"]["accounts"].values()):
        required.add("numerical_candidates.py")
    if any(a.get("memory_entry_contract") for a in packet["state_before"]["accounts"].values()):
        required.add("memory_quality.py")
    if any(packet["source_files"].get(name) != current[name] for name in required):
        raise ValueError(
            "Recorded engine/artifact source differs; original-version replay required"
        )
    if len(packet["state_before"]["accounts"]) > 20:
        raise ValueError("Recorded account cap exceeded")
    reproduced = feature_reproduction(packet)
    if not reproduced.get("book_features_match") or any(
        r.get("matched") is not True for r in reproduced["closed_bar_features"].values()
    ):
        raise ValueError("Causal features cannot be reproduced; no execution result inferred")
    hydrated_frames(packet)
    if not packet.get("after_tick_sha256") or not isinstance(packet.get("events"), list):
        raise ValueError("Recorded financial outcome is missing")
    return cast(dict[str, Any], packet)


def balanced(events: list[dict[str, Any]]) -> bool:
    for event in events:
        sums: dict[str, D] = defaultdict(D)
        for line in event["lines"]:
            sums[line["asset"]] += D(line["amount"])
        if any(value != 0 for value in sums.values()):
            return False
    return True


def stress_profiles(scenario: str, frames: dict[str, Any], originals: dict[str, Any]) -> bool:
    """Called only in the dedicated child, never in the server/financial writer."""
    condition = any(
        D(f["book"].metrics()["spread_bps"]) >= 10
        or min(D(f["book"].metrics()[k]) for k in ("bid_depth_quote", "ask_depth_quote")) < 100
        for f in frames.values()
    )
    PROFILES.clear()
    for key, p in originals.items():
        if scenario == "delay-3s-v1":
            p = replace(p, latency_seconds=max(3, p.latency_seconds))
        elif scenario == "condition-cost-v1" and condition:
            p = replace(
                p,
                slippage=str(max(D(p.slippage), D(".0005"))),
                participation=str(min(D(p.participation), D(".05"))),
            )
        PROFILES[key] = p
    return condition and scenario == "condition-cost-v1"


def run_replay(records: list[dict[str, Any]], frozen_source: dict[str, str]) -> dict[str, Any]:
    if not records or len(records) > MAX_RECORDS:
        raise ValueError("Replay requires one to thirty-two frozen records")
    if source_hashes() != frozen_source:
        raise ValueError("Replay source changed after reservation")
    started, cpu_started = time.perf_counter(), time.process_time()
    original_profiles = dict(PROFILES)
    baseline: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    boundary = None
    previous = None
    prior_books: dict[str, dict[str, Any]] = {}
    try:
        for record in records:
            try:
                packet = checked_packet(record, frozen_source)
                if accepted and packet["at"] <= accepted[-1]["at"]:
                    raise ValueError("Decision observations must be strictly chronological")
                if data_mode(packet) == "mixed" or (
                    accepted and data_mode(packet) != data_mode(accepted[0])
                ):
                    raise ValueError("Incompatible synthetic/observed data modes; slice stopped")
                for symbol, frame in packet["frames"].items():
                    prior = prior_books.get(symbol)
                    sequence, observed = frame["raw"]["lastUpdateId"], frame["observed"]
                    if prior and (
                        observed < prior["observed"]
                        or sequence < prior["sequence"]
                        or (
                            sequence == prior["sequence"]
                            and digest(frame["raw"]) != prior["sha256"]
                        )
                    ):
                        raise ValueError("Book chronology or same-sequence content conflicts")
                    prior_books[symbol] = {
                        "observed": observed,
                        "sequence": sequence,
                        "sha256": digest(frame["raw"]),
                    }
            except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                if not accepted:
                    raise
                boundary = {"record_id": record["id"], "reason": str(exc)}
                break
            if previous is not None and financial_chain(previous) != financial_chain(
                packet["state_before"]
            ):
                boundary = {
                    "record_id": record["id"],
                    "reason": "Unrecorded state transition; slice stopped before it",
                }
                break
            engine = PaperEngine(ordered_state(packet), packet["at"])
            engine.tick(hydrated_frames(packet), deepcopy(packet["study"]))
            receipt = {
                "record_id": record["id"],
                "input_sha256": record["sha256"],
                "at": packet["at"],
                "state_matches": digest(engine.state) == packet["after_tick_sha256"],
                "events_match": engine.events == packet["events"],
                "balanced": balanced(engine.events),
                "journal_revision": (packet.get("financial_commit") or {}).get("revision"),
                "journal_events": (packet.get("financial_commit") or {}).get("events", []),
            }
            baseline.append(receipt)
            if not all(receipt[k] for k in ("state_matches", "events_match", "balanced")):
                return {
                    "status": "reconciliation_failed",
                    "data_mode": data_mode(packet),
                    "baseline": baseline,
                    "scenarios": [],
                    "possible_causes": [
                        "Captured inputs/state",
                        "Feature/source/profile version",
                        "Runtime dispatch or external state transition",
                    ],
                    "residual": "Unresolved; changed scenarios were withheld",
                    "financial_authority": False,
                }
            previous = engine.state
            accepted.append(packet)

        scenarios = []
        for scenario in SCENARIOS:
            state = ordered_state(accepted[0])
            beginning = {n: sample(a, accepted[0]["at"]) for n, a in state["accounts"].items()}
            fills, closes, actions = [], [], []
            paths: dict[str, dict[str, Any]] = {}
            stressed_ticks, all_balanced = 0, True
            for packet, record in zip(accepted, records, strict=False):
                at = packet["at"]
                frames = hydrated_frames(packet)
                stressed_ticks += int(stress_profiles(scenario, frames, original_profiles))
                for key in ("study_bars", "book_sequences"):
                    if key in packet["state_before"]:
                        state[key] = deepcopy(packet["state_before"][key])
                engine = PaperEngine(state, at)
                before_positions = {
                    name: deepcopy(a["positions"]) for name, a in state["accounts"].items()
                }
                engine.tick(frames, deepcopy(packet["study"]))
                all_balanced = all_balanced and balanced(engine.events)
                for index, event in enumerate(engine.events):
                    body, name, kind = event["body"], event["account"], event["kind"]
                    if kind in {
                        "decision",
                        "order_intent",
                        "fill",
                        "trade_closed",
                        "order_cancelled",
                        "observation_gap",
                    }:
                        actions.append(
                            {
                                "record_id": record["id"],
                                "event_index": index,
                                "kind": kind,
                                "account": name,
                                "symbol": body.get("symbol"),
                                "reason": body.get("reason"),
                                "at": at,
                            }
                        )
                    if kind == "fill":
                        fills.append(
                            {
                                "record_id": record["id"],
                                "account": name,
                                **{
                                    k: body[k]
                                    for k in (
                                        "symbol",
                                        "side",
                                        "filled_quantity",
                                        "gross",
                                        "fee",
                                        "fee_asset",
                                        "vwap",
                                        "partial",
                                        "unfilled_cancelled",
                                        "embedded_execution_drag_usd",
                                    )
                                },
                            }
                        )
                    if kind == "trade_closed":
                        closes.append(
                            {
                                "record_id": record["id"],
                                "account": name,
                                "holding_seconds": at - body["opened_at"],
                                **body,
                            }
                        )
                # Observed bid marks only. OHLC extrema cannot decide a stop/target order.
                for name, a in state["accounts"].items():
                    observed_positions = {**before_positions[name], **a["positions"]}
                    for symbol, pos in observed_positions.items():
                        if symbol not in frames or at - frames[symbol]["observed"] > 5:
                            continue
                        key = f"{name}:{symbol}:{pos['opened_at']}"
                        move = (frames[symbol]["book"].bids[0][0] / D(pos["entry"]) - 1) * 10000
                        p = paths.setdefault(
                            key,
                            {
                                "account": name,
                                "symbol": symbol,
                                "opened_at": pos["opened_at"],
                                "first_observed_at": at,
                                "complete_from_open": at == pos["opened_at"],
                                "favorable_bps": "0",
                                "adverse_bps": "0",
                                "last_move_bps": str(move),
                            },
                        )
                        p.update(
                            last_observed_at=at,
                            observed_holding_seconds=at - p["first_observed_at"],
                            favorable_bps=str(max(D(p["favorable_bps"]), move)),
                            adverse_bps=str(min(D(p["adverse_bps"]), move)),
                            last_move_bps=str(move),
                        )
                        if symbol not in a["positions"]:
                            p["closed_at"] = at
            end = {n: sample(a, accepted[-1]["at"]) for n, a in state["accounts"].items()}
            accounts = []
            for name, final in end.items():
                start = beginning[name]
                accounts.append(
                    {
                        "account": name,
                        "starting": start,
                        "ending": final,
                        "slice_net_pnl": str(
                            D(final["equity"])
                            - D(start["equity"])
                            - (D(final["funding"]) - D(start["funding"]))
                        )
                        if start["fresh"] and final["fresh"]
                        else None,
                        "additional_fees_usd": str(D(final["fees"]) - D(start["fees"])),
                        "embedded_drag_usd": str(
                            D(final["execution_drag"]) - D(start["execution_drag"])
                        ),
                        "pending_orders": len(state["accounts"][name]["pending"]),
                        "open_positions": len(state["accounts"][name]["positions"]),
                    }
                )
            for path in paths.values():
                path["observed_giveback_bps"] = str(
                    D(path["favorable_bps"]) - D(path["last_move_bps"])
                )
                path["coverage"] = (
                    "Observed bid marks in retained slice; "
                    "missing between-book extrema and market impact"
                )
            scenarios.append(
                {
                    "scenario": scenario,
                    "evidence_type": "reproduced paper"
                    if scenario == "recorded"
                    else "modeled counterfactual",
                    "balanced": all_balanced,
                    "condition_stressed_ticks": stressed_ticks,
                    "accounts": accounts,
                    "fills": fills,
                    "closed_trades": closes,
                    "observed_paths": list(paths.values()),
                    "actions": actions[:160],
                    "actions_omitted": max(0, len(actions) - 160),
                    "net_labels_already_include_execution_costs": True,
                }
            )
        episode = accepted[0].get("episode")
        lookup = episode.get("retrieval", {}) if isinstance(episode, dict) else {}
        usable = (
            lookup.get("earliest_action_at")
            if lookup.get("status") == "matches_available"
            else None
        )
        expiry = (
            episode.get("descriptor", {}).get("expires_at") if isinstance(episode, dict) else None
        )
        actionable = [
            p
            for p in accepted
            if usable is not None
            and expiry is not None
            and usable <= p["at"] <= expiry
            and "BTCUSD" in p["frames"]
        ]
        remaining: dict[str, Any] = {
            "status": "unavailable",
            "reason": "No supported books at actionable point; no earlier move credited",
        }
        if actionable:
            remaining = {
                "status": "partial_observed_path",
                "earliest_action_at": usable,
                "first_supported_book_at": actionable[0]["at"],
                "horizon_return": None,
                "reason": "Finite slice does not establish continuous horizon/action coverage",
            }
        elapsed = time.perf_counter() - started
        return {
            "version": VERSION,
            "data_mode": data_mode(accepted[0]),
            "status": "reconciled",
            "contract": CONTRACT,
            "source_files": frozen_source,
            "input_references": [{"id": r["id"], "sha256": r["sha256"]} for r in records],
            "baseline": baseline,
            "scenarios": scenarios,
            "financial_authority": False,
            "coverage": {
                "requested": len(records),
                "supported": len(accepted),
                "boundary": boundary,
                "start": accepted[0]["at"],
                "end": accepted[-1]["at"],
                "market_sample_increment": 0,
            },
            "remaining_opportunity": remaining,
            "attribution": {
                "measured": "Recorded books/features and matching paper state/events",
                "modeled": "Delay/cost stress; interacting sizing/execution responses",
                "unavailable": (
                    "Unique causal decomposition, full horizon, queue/impact/private commissions"
                ),
                "residual": "Multiple possible causes; no single-factor advantage inferred",
            },
            "resources": {
                "elapsed_seconds": elapsed,
                "cpu_seconds": time.process_time() - cpu_started,
                "supported_ticks_per_second": len(accepted) / max(elapsed, 1e-9),
                "paid_usd": "0",
            },
        }
    finally:
        PROFILES.clear()
        PROFILES.update(original_profiles)
