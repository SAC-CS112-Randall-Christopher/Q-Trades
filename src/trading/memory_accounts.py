"""Full declared-period A/B/C account research through the existing deterministic engine."""

import json
import time
from copy import deepcopy
from decimal import Decimal as D
from typing import Any

from trading.execution_replay import (
    balanced,
    checked_packet,
    data_mode,
    financial_chain,
    hydrated_frames,
    ordered_state,
    source_hashes,
)
from trading.memory_quality import evaluate_memory, filtered_feature, validate_artifact
from trading.paper_economics import benchmark_tick, new_benchmark, sample
from trading.paper_engine import PaperEngine, account, initial_state
from trading.pattern_memory import descriptor
from trading.research_evidence import book_features, digest
from trading.research_timing import prediction_time

VERSION = "memory-paired-accounts-v1"


def compare_accounts(
    records: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    plan: Any,
    frozen_source: dict[str, str],
    *,
    fit_cpu: dict[str, float] | None = None,
) -> dict[str, Any]:
    """No original or counterfactual account is reset between selected observations."""
    if not 2 <= len(records) <= 512:
        raise ValueError("A complete account interval needs two to 512 decision bundles")
    if len(json.dumps(records, sort_keys=True, allow_nan=False).encode()) > 8 * 1024**2:
        raise ValueError("Declared account interval exceeds eight MiB; no prefix substituted")
    if frozen_source != source_hashes() or set(artifacts) != {"B", "C"}:
        raise ValueError("Frozen source and both memory arms are required")
    for arm, artifact in artifacts.items():
        validate_artifact(artifact)
        if artifact["arm"] != arm or artifact["calibration_end"] > plan.test_start:
            raise ValueError("Memory must be fitted and calibrated before the account interval")
    previous: dict[str, Any] | None = None
    prior_books: dict[str, tuple[float, int, str]] = {}
    packets: list[dict[str, Any]] = []
    # Verify every source receipt before evaluating changed accounts. A partial prefix is a refusal.
    for record in records:
        p = checked_packet(record, frozen_source)
        if not plan.test_start <= p["at"] <= plan.test_end:
            raise ValueError("Decision outside the declared interval")
        if packets and (not 0 < p["at"] - packets[-1]["at"] <= 30):
            raise ValueError("Missing or reordered decisions; complete interval unavailable")
        if data_mode(p) not in {"synthetic", "paper_observations"} or (
            packets and data_mode(p) != data_mode(packets[0])
        ):
            raise ValueError("Unknown or mixed data mode")
        if previous is not None and financial_chain(previous) != financial_chain(p["state_before"]):
            raise ValueError("Unrecorded financial transition; complete interval unavailable")
        for symbol, f in p["frames"].items():
            observed, sequence, sha = f["observed"], f["raw"]["lastUpdateId"], digest(f["raw"])
            prior = prior_books.get(symbol)
            if prior and (
                observed < prior[0]
                or sequence < prior[1]
                or (sequence == prior[1] and sha != prior[2])
            ):
                raise ValueError("Book chronology conflict")
            prior_books[symbol] = (observed, sequence, sha)
        source = PaperEngine(ordered_state(p), p["at"])
        source.tick(hydrated_frames(p), deepcopy(p["study"]))
        if (
            digest(source.state) != p["after_tick_sha256"]
            or source.events != p["events"]
            or not balanced(source.events)
        ):
            raise ValueError("Source state/events do not reconcile")
        previous = source.state
        packets.append(p)
    start, end = packets[0]["at"], packets[-1]["at"]
    if start - plan.test_start > 5 or plan.test_end - end > 5:
        raise ValueError("Declared start/end observations unavailable")
    original = packets[0]["state_before"]["accounts"].get("primary")
    if not original or original.get("numerical_artifact") or original["version"] != "breakout-v1":
        raise ValueError(
            "The existing breakout baseline is required; do not substitute an incumbent"
        )
    profile = original["execution_profile"]
    state = initial_state(start, plan.starting_cash, profile)
    state["accounts"] = {"A": account("breakout-v1", start, plan.starting_cash, profile)}
    # Freeze the strategy; the original engine manages positions and every risk limit.
    state["next_review"] = plan.test_end + 1
    for arm, artifact in artifacts.items():
        a = account("numeric-" + artifact["sha256"][:24], start, plan.starting_cash, profile)
        a.update(numerical_artifact=deepcopy(artifact), memory_entry_contract="memory-entry-v1")
        state["accounts"][arm] = a
    for a in state["accounts"].values():
        a.update(
            symbols=["BTCUSD"],
            benchmark_symbols=["BTCUSD"],
            operating_daily_usd=plan.common_daily_usd,
        )
    passive = new_benchmark(plan.starting_cash, profile, start, ("BTCUSD",))
    pending: dict[str, dict[str, Any]] = {}
    cpu = {arm: 0.0 for arm in artifacts}
    wall = {arm: 0.0 for arm in artifacts}
    actions: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ("A", "B", "C")}
    fills: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ("A", "B", "C")}
    exposure = {arm: D(0) for arm in actions}
    last_exposure = {arm: D(0) for arm in actions}
    last_at = start
    all_fresh = True
    passive_fills = []
    for p in packets:
        now = p["at"]
        frames = hydrated_frames(p)
        if "BTCUSD" not in frames or now - frames["BTCUSD"]["observed"] > 5:
            raise ValueError("Fresh BTC books required throughout the account interval")
        base = deepcopy(p["study"].get("BTCUSD", {}).get("breakout-v1", {}))
        study = {"BTCUSD": {"breakout-v1": base}}
        for arm, artifact in artifacts.items():
            current = pending.get(arm)
            if current is None or current["bar"] != base.get("bar_open_ms"):
                origin = p["feature_origin"]["BTCUSD"]
                available = max(
                    frames["BTCUSD"]["observed"], origin["available_at"], origin["computed_at"]
                )
                stored = [
                    t
                    for t in (
                        p.get("episode", {}).get("available_at"),
                        (p.get("financial_commit") or {}).get("committed_at"),
                    )
                    if t is not None
                ]
                if stored:
                    available = max(available, *stored)
                else:
                    available = float("inf")
                d = descriptor(
                    p["bars"]["BTCUSD"],
                    now,
                    {"book": book_features(p["frames"]["BTCUSD"], now), "closed_bar": base},
                    data_mode(p),
                )
                row = {"descriptor": d, "available_at": available}
                begun, c = time.perf_counter(), time.process_time()
                feature = filtered_feature(base, d, artifact, prediction_time(row))
                elapsed, used = time.perf_counter() - begun, time.process_time() - c
                wall[arm] += elapsed
                cpu[arm] += used
                current = {
                    "bar": base.get("bar_open_ms"),
                    "feature": feature,
                    "available_at": prediction_time(row) + elapsed,
                    "expires_at": d.get("expires_at", now),
                    "cutoff": now,
                }
                pending[arm] = current
            feature = deepcopy(current["feature"])
            if now > current["expires_at"]:
                feature = deepcopy(base)  # Expired research supplies no additional signal.
            elif now < current["available_at"]:
                feature.pop("bar_open_ms", None)  # No decision credited before the result exists.
            else:
                feature["memory_evidence"]["earliest_action_at"] = current["available_at"]
            study["BTCUSD"][state["accounts"][arm]["version"]] = feature
        engine = PaperEngine(state, now)
        engine.tick(frames, study)
        if not balanced(engine.events):
            raise ValueError("Account research journal did not balance")
        for event in engine.events:
            arm = event["account"]
            if arm not in actions:
                continue
            if event["kind"] == "decision":
                b = event["body"]
                evidence = b["features"].get("memory_evidence", {})
                actions[arm].append(
                    {
                        "bar": b["bar"],
                        "at": now,
                        "entry_proposed": b["reason"]
                        == "Paper entry reserved; waiting for a later book",
                        "reason": b["reason"],
                        "memory_action": evidence.get("action", "baseline"),
                        "status": evidence.get("status", "baseline"),
                        "available_at": evidence.get("earliest_action_at"),
                        "prediction": evidence,
                    }
                )
            elif event["kind"] == "fill":
                fills[arm].append({"at": now, **event["body"]})
        for arm, a in state["accounts"].items():
            exposure[arm] += last_exposure[arm] * D(str(now - last_at))
            s = sample(a, now)
            all_fresh = all_fresh and s["fresh"]
            last_exposure[arm] = max(D(0), D(s["equity"]) - D(s["cash"]))
        last_at = now
        passive_fills.extend(benchmark_tick(passive, frames, now))
    duration = D(str(plan.test_end - plan.test_start))
    common = (
        D(plan.common_daily_usd) * duration / 86400 if plan.common_daily_usd is not None else None
    )
    accounts = {}
    for arm, a in state["accounts"].items():
        daily = (
            "0"
            if arm == "A"
            else plan.numerical_daily_usd
            if arm == "B"
            else plan.contextual_daily_usd
        )
        component = D(daily) * duration / 86400 if daily is not None else None
        setup_cpu = (fit_cpu or {}).get(arm, 0.0)
        compute = (
            D(str(cpu.get(arm, 0) + setup_cpu)) * D(plan.cpu_hour_usd) / 3600
            if plan.cpu_hour_usd is not None
            else None
        )
        if arm == "A":
            compute = D(0)
        incremental = component + compute if component is not None and compute is not None else None
        s = sample(a, end)
        trading = D(s["equity"]) - D(plan.starting_cash) if all_fresh else None
        net = (
            trading - common - incremental
            if trading is not None and common is not None and incremental is not None
            else None
        )
        accounts[arm] = {
            "sample": s,
            "positions": deepcopy(a["positions"]),
            "pending": deepcopy(a["pending"]),
            "trading_net_usd": str(trading) if trading is not None else None,
            "common_operating_usd": str(common) if common is not None else None,
            "incremental_operating_usd": str(incremental) if incremental is not None else None,
            "component_operating_usd": str(component) if component is not None else None,
            "compute_usd": str(compute) if compute is not None else None,
            "net_account_usd": str(net) if net is not None else None,
            "cpu_seconds": cpu.get(arm, 0),
            "fit_cpu_seconds": setup_cpu,
            "inference_seconds": wall.get(arm, 0),
            "fills": fills[arm],
            "decisions": actions[arm],
            "turnover_usd": str(sum((D(f["gross"]) for f in fills[arm]), D(0))),
            "mean_exposure_usd": str(exposure[arm] / duration),
            "drawdown": a["max_drawdown"],
            "closed_trades": a["closed"],
        }
    contributions = []
    for left, right in (("A", "B"), ("B", "C")):
        a, b = accounts[left], accounts[right]
        effect = (
            D(b["net_account_usd"]) - D(a["net_account_usd"])
            if a["net_account_usd"] is not None and b["net_account_usd"] is not None
            else None
        )
        marginal = (
            D(b["incremental_operating_usd"]) - D(a["incremental_operating_usd"])
            if a["incremental_operating_usd"] is not None
            and b["incremental_operating_usd"] is not None
            else None
        )
        by_bar = {d["bar"]: d for d in actions[left]}
        paired = [(by_bar[d["bar"]], d) for d in actions[right] if d["bar"] in by_bar]
        contributions.append(
            {
                "from": left,
                "to": right,
                "paired_account_effect": str(effect) if effect is not None else None,
                "marginal_cost_usd": str(marginal) if marginal is not None else None,
                "changed_decisions": sum(
                    x["reason"] != y["reason"] or x["at"] != y["at"] for x, y in paired
                ),
                "paired_decisions": len(paired),
                "forecast_coverage": sum(d["status"] == "supported" for d in actions[right]),
                "opportunity_denominator": len(actions[right]),
                "mean_exposure_usd": b["mean_exposure_usd"],
                "turnover_usd": b["turnover_usd"],
                "conclusion": "unavailable"
                if effect is None
                else "unfavorable"
                if effect <= 0
                else "favorable_in_declared_scenario",
                "uncertainty": "One interval; statistical and forward qualification unverified",
            }
        )
    complete = all_fresh and passive["fresh"] and passive["coverage"]
    return {
        "version": VERSION,
        "status": "complete" if complete else "incomplete_valuation",
        "period": {
            "declared_start": plan.test_start,
            "declared_end": plan.test_end,
            "first_observation": start,
            "last_observation": end,
            "records": len(records),
            "boundary_tolerance_seconds": 5,
        },
        "data_mode": data_mode(packets[0]),
        "source_reconciled_records": len(records),
        "financial_authority": False,
        "accounts": accounts,
        "contributions": contributions,
        "passive_benchmark": {
            "kind": "Continuous buy-once, hold through entire declared interval",
            "state": passive,
            "entry_fills": passive_fills,
            "net_trading_usd": str(D(passive["equity"]) - D(plan.starting_cash))
            if passive["fresh"]
            else None,
            "operating_cost_usd": str(common) if common is not None else None,
            "net_account_usd": str(D(passive["equity"]) - D(plan.starting_cash) - common)
            if passive["fresh"] and common is not None
            else None,
            "equity_basis": "Executable liquidation mark; entry and liquidation fees embedded once",
        },
        "cash_control": {
            "capital": plan.starting_cash,
            "net_account_usd": str(-common) if common is not None else None,
        },
        "cost_contract": {
            "kind": "Declared operating-cost scenario with measured inference CPU",
            "common_daily_usd": plan.common_daily_usd,
            "numerical_daily_usd": plan.numerical_daily_usd,
            "contextual_daily_usd": plan.contextual_daily_usd,
            "cpu_hour_usd": plan.cpu_hour_usd,
            "daily_allocation_scope": (
                "Declared collection, storage and routine host allocation; "
                "common charged once per arm, component increments separately"
            ),
            "provider_paid_usd": "0",
            "actual_host_bill": "Unavailable; declared rates are assumptions",
            "fit_cost": "This experiment charges measured fitting CPU once, plus inference CPU",
            "fees": "Embedded in cash/fills and executable final marks; never deducted again",
        },
        "timing_contract": (
            "Historical counterfactual; required stored-input availability plus measured local "
            "inference delay, applied only on a subsequent permitted book; no instantaneous arm"
        ),
        "reset_exposure_control": "Four-hour reset control is separate from continuous hold",
        "qualification": "Exploratory only; 28-day policy and human approval unchanged",
    }


def evaluate_account_memory(
    rows: list[dict[str, Any]], snapshot: dict[str, Any], plan: Any
) -> dict[str, Any]:
    result = evaluate_memory(rows, plan, seed_only=True)
    artifacts = {c["arm"]: c["artifact"] for c in result["candidate_group"] if c.get("artifact")}
    result["eligible_for_exploratory_paper"] = False
    try:
        comparison = compare_accounts(
            snapshot["records"],
            artifacts,
            plan,
            snapshot["source_files"],
            fit_cpu={
                c["arm"]: c["fit_cpu_seconds"]
                for c in result["candidate_group"]
                if c.get("artifact")
            },
        )
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        result.update(
            status="incomplete_account_comparison",
            reason=str(exc),
            account_comparison={
                "status": "unavailable",
                "reason": str(exc),
                "financial_authority": False,
            },
        )
        return result
    result.update(
        account_comparison=comparison,
        contributions=comparison["contributions"],
        whole_account_effect={
            arm: a["net_account_usd"] for arm, a in comparison["accounts"].items()
        },
        cash_control=comparison["cash_control"],
        exposure_control=comparison["passive_benchmark"],
        status="historical_account_comparison",
        reason="Declared-period account scenario retained; subsequent paper evidence unqualified",
    )
    result["eligible_for_exploratory_paper"] = (
        comparison["status"] == "complete"
        and all(a["net_account_usd"] is not None for a in comparison["accounts"].values())
        and plan.evidence_kind != "synthetic_qa"
        and comparison["data_mode"] == "paper_observations"
    )
    for c in result["candidate_group"]:
        c.update(
            status="frozen_exploratory_artifact", account_outcome=comparison["accounts"][c["arm"]]
        )
    result["decision"] = (
        "exploratory_paper_only" if result["eligible_for_exploratory_paper"] else "retain_research"
    )
    return result
