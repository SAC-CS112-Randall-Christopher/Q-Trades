"""Independent finite exit, conservative size and observation research. No adapter."""

import math
import time
from copy import deepcopy
from decimal import Decimal as D
from typing import Any

from trading.execution_profiles import execution, floor_step
from trading.execution_replay import hydrated_frames, ordered_state, run_replay, source_hashes
from trading.paper_economics import sample
from trading.paper_engine import PaperEngine
from trading.research_evidence import digest

CONTRACT: dict[str, Any] = {
    "version": "independent-components-v1",
    "component_exit": "Original versus additional thirty-minute exit; matched entries/size",
    "component_size": "Original risk-sized quantity versus filtered, rounded-down half size",
    "observation_priority": "Four extra slots; observed range/costs and activity",
    "records": "Earliest chronological thirty-two permitted decisions, never selected by outcome",
    "size_bands": ["0.25", "0.5", "1"],
    "unsupported": "Memory-informed exits/sizing deferred without qualified entry evidence",
    "authority": "Independent isolated replay/shadow; no financial adapter or promotion",
    "costs": "Original financial engine and cost profiles; net effects already embed fees once",
    "correlation": "Independent account results are never pooled as one capital authority",
}


def size_band(prediction: dict[str, Any] | None) -> D:
    if not prediction or prediction.get("status") != "supported":
        return D(1)  # Missing optional context contributes no additional sizing signal.
    downside = D(str(prediction["downside_bps"]))
    if not downside.is_finite():
        raise ValueError("Invalid uncertainty")
    return D("0.25") if downside < -50 else D("0.5")


class ComponentEngine(PaperEngine):
    def __init__(
        self,
        state: dict[str, Any],
        now: float,
        mode: str,
        entry_schedule: set[tuple[str, str, float]],
    ):
        super().__init__(state, now)
        self.mode = mode
        self.entry_schedule = entry_schedule

    def enter(
        self,
        name: str,
        a: dict[str, Any],
        symbol: str,
        frame: dict[str, Any],
        feature: dict[str, Any],
    ) -> str:
        if (name, symbol, self.now) not in self.entry_schedule:
            return "Matched-entry replay: no recorded baseline entry at this point"
        if self.mode != "component_size":
            return super().enter(name, a, symbol, frame, feature)
        # Ask the existing engine for a valid proposal in a disposable copy first.
        probe = PaperEngine(deepcopy(self.state), self.now)
        reason = probe.enter(name, probe.state["accounts"][name], symbol, frame, feature)
        if reason != "Paper entry reserved; waiting for a later book":
            return reason
        order = deepcopy(probe.state["accounts"][name]["pending"][symbol])
        quantity = floor_step(D(order["quantity"]) * D("0.5"), frame["rules"]["step"])
        if (
            quantity < frame["rules"]["min_qty"]
            or quantity * D(order["limit"]) < frame["rules"]["min_notional"]
        ):
            return "Conservative half size below venue minimum; no risk increase"
        reserve = quantity * D(order["limit"]) * (1 + execution(a).fee(symbol))
        if reserve > D(order["reserved"]):
            raise ValueError("Research sizing cannot exceed original reservation")
        order.update(
            quantity=str(quantity), reserved=str(reserve), reason="Independent half-size research"
        )
        a["pending"][symbol] = order
        self.emit(
            "order_intent",
            name,
            order,
            [self.line("USD", "cash", -reserve), self.line("USD", "reserved", reserve)],
        )
        return "Paper entry reserved; waiting for a later book"

    def exit_position(
        self,
        name: str,
        a: dict[str, Any],
        symbol: str,
        frame: dict[str, Any],
        feature: dict[str, Any],
    ) -> None:
        super().exit_position(
            name, a, symbol, frame, feature
        )  # Stops/failure management remain first.
        if self.mode != "component_exit" or symbol in a["pending"]:
            return
        pos = a["positions"][symbol]
        if self.now - pos["opened_at"] < 1800:
            return
        rules = frame["rules"]
        quantity = D(pos["quantity"])
        limit = max(
            rules["min_price"], floor_step(frame["book"].bids[0][0] * D("0.995"), rules["tick"])
        )
        if quantity < rules["min_qty"] or quantity * limit < rules["min_notional"]:
            pos["exit_blocked"] = "Remaining inventory below venue minimum; no invented fill"
            return
        order = {
            "symbol": symbol,
            "side": "sell",
            "execution_profile": execution(a).id,
            "fee_asset": "USD",
            "quantity": str(quantity),
            "limit": str(limit),
            "reserved": "0",
            "version": pos["version"],
            "created_at": self.now,
            "reason": "Independent thirty-minute exit",
            "book": frame["raw"],
            "model": self.state["model"],
            "observation": {"source": frame.get("source"), "observed": frame["observed"]},
        }
        a["pending"][symbol] = order
        self.emit("order_intent", name, order)


def scanner(snapshot: dict[str, Any] | None, plan: Any) -> dict[str, Any]:
    unavailable: dict[str, Any] = {
        "status": "unavailable",
        "reason": "Point-in-time universe unavailable",
        "baseline": [],
        "challenger": [],
        "useful_future_coverage": None,
    }
    try:
        if not snapshot:
            return unavailable
        at = snapshot["scanned_at"]
        if not plan.test_start <= at <= plan.test_end <= plan.as_of:
            raise ValueError(
                "Current universe cannot substitute for the historical comparison window"
            )
        if not 0 < snapshot["metadata_at"] <= at:
            raise ValueError("Point-in-time eligibility metadata unavailable")
        rows = snapshot["rows"]
        held = set(snapshot["held_pending"])
        extras = sorted(held - {"BTCUSD", "ETHUSD"})
        if len(rows) > 2000 or len(extras) > 6:
            raise ValueError("Declared market/subscription budget exceeded")
        count = max(4, len(extras))
        baseline = list(extras)
        challenger = list(extras)
        ranked = []
        eligible = [r for r in rows if r.get("eligible") is True and r.get("confirmed") is True]
        for r in sorted(
            eligible,
            key=lambda r: (abs(D(r["change_percent"])), D(r["quote_volume"])),
            reverse=True,
        ):
            if (
                len(baseline) < count
                and r["symbol"] not in baseline
                and r["symbol"] not in {"BTCUSD", "ETHUSD"}
            ):
                baseline.append(r["symbol"])
        for r in eligible:
            spread, range_bps, volume = (
                D(r["spread_bps"]),
                D(r["range_percent"]) * 100,
                D(r["quote_volume"]),
            )
            if (
                not all(x.is_finite() for x in (spread, range_bps, volume))
                or min(spread, range_bps) < 0
                or volume <= 0
            ):
                continue
            activity = r["trades"]
            if type(activity) is not int or activity <= 0:
                continue
            # Fixed observed-range/cost score; not a future trading-return forecast.
            costs = spread + D(40)
            proximity = (
                snapshot.get("signal_proximity", {}).get(r["symbol"])
                if snapshot.get("signal_available_at", {}).get(r["symbol"], math.inf) <= at
                else None
            )
            score = float(range_bps / costs) + math.log10(float(volume)) + math.log10(activity)
            if proximity is True:
                score += 1
            ranked.append(
                {
                    "symbol": r["symbol"],
                    "score": score,
                    "observed_spread_bps": str(spread),
                    "cost_floor_bps": "40",
                    "signal_proximity": proximity,
                    "depth_and_replenishment": "unavailable",
                    "subsequent_opportunity": None,
                }
            )
        for r in sorted(ranked, key=lambda r: (-r["score"], r["symbol"])):
            if (
                len(challenger) < count
                and r["symbol"] not in challenger
                and r["symbol"] not in {"BTCUSD", "ETHUSD"}
            ):
                challenger.append(r["symbol"])
        return {
            "status": "attention_shadow_only",
            "baseline": baseline,
            "challenger": challenger,
            "held_pending_priority": extras,
            "ranked": ranked,
            "same_extra_slot_budget": count,
            "useful_future_coverage": None,
            "unobserved_outcomes": len(rows),
            "reason": "Attention comparison only; all subsequent market outcomes remain unknown",
            "input_sha256": digest(snapshot),
        }
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        return dict(unavailable, reason=str(exc))


def component_replay(records: list[dict[str, Any]], mode: str, plan: Any) -> dict[str, Any]:
    eligible = sorted(
        (
            r
            for r in records
            if plan.test_start <= r["at"] <= plan.test_end
            and (r["payload"].get("financial_commit") or {}).get("committed_at", math.inf)
            <= plan.as_of
        ),
        key=lambda r: r["at"],
    )
    selected = eligible[
        :32
    ]  # Declared earliest finite slice; remainder stays unknown, never regraded.
    result: dict[str, Any] = {
        "status": "unavailable",
        "reason": "Supported execution slice unavailable",
        "requested_decisions": len(eligible),
        "retained_slice": len(selected),
        "subsequent_decisions_not_evaluated": max(0, len(eligible) - 32),
        "accounts": [],
    }
    if not selected:
        return result
    base = run_replay(selected, source_hashes())
    if base["status"] != "reconciled":
        return dict(result, reason="Baseline reconciliation failed; component effects withheld")
    n = base["coverage"]["supported"]
    packets = [r["payload"] for r in selected[:n]]
    schedule = {
        (e["account"], e["body"]["symbol"], p["at"])
        for p in packets
        for e in p["events"]
        if e["kind"] == "order_intent" and e["body"].get("side") == "buy"
    }
    original_entries = [
        (e["account"], e["body"]["symbol"], p["at"], e["body"]["quantity"])
        for p in packets
        for e in p["events"]
        if e["kind"] == "order_intent" and e["body"].get("side") == "buy"
    ]
    state = ordered_state(packets[0])
    beginning = {name: sample(a, packets[0]["at"]) for name, a in state["accounts"].items()}
    buys: list[tuple[str, str, float, str]] = []
    events = []
    for packet in packets:
        for key in ("study_bars", "book_sequences"):
            if key in packet["state_before"]:
                state[key] = deepcopy(packet["state_before"][key])
        engine = ComponentEngine(state, packet["at"], mode, schedule)
        engine.tick(hydrated_frames(packet), deepcopy(packet["study"]))
        engine.assert_invariants()
        events.extend(engine.events)
        buys.extend(
            (e["account"], e["body"]["symbol"], packet["at"], e["body"]["quantity"])
            for e in engine.events
            if e["kind"] == "order_intent" and e["body"].get("side") == "buy"
        )
    matched = (
        buys == original_entries
        if mode == "component_exit"
        else ([b[:3] for b in buys] == [b[:3] for b in original_entries])
    )
    baseline_accounts = {a["account"]: a for a in base["scenarios"][0]["accounts"]}
    accounts = []
    for name, a in state["accounts"].items():
        final = sample(a, packets[-1]["at"])
        start = beginning[name]
        pnl = (
            (D(final["equity"]) - D(start["equity"]) - (D(final["funding"]) - D(start["funding"])))
            if final["fresh"] and start["fresh"]
            else None
        )
        base_pnl = baseline_accounts[name]["slice_net_pnl"]
        accounts.append(
            {
                "account": name,
                "ending": final,
                "slice_net_pnl": str(pnl) if pnl is not None else None,
                "paired_slice_effect": str(pnl - D(base_pnl))
                if matched and pnl is not None and base_pnl is not None
                else None,
                "max_drawdown": a["max_drawdown"],
                "turnover": a["day_turnover"],
                "open_positions": len(a["positions"]),
                "pending": len(a["pending"]),
                "correlated_exposure": "No cross-account capital aggregation",
                "marginal_operating_usd": None,
            }
        )
    return dict(
        result,
        status="matched_finite_replay" if matched else "unmatched_entries",
        reason="Finite modeled slice; no continuous horizon or prospective advantage",
        accounts=accounts,
        matched_entries=matched,
        events=events,
        baseline_reconciled=True,
        boundary=base["coverage"],
        observed_post_entry_paths=base["scenarios"][0]["observed_paths"],
        fees_already_embedded_once=True,
    )


def evaluate_components(
    rows: list[dict[str, Any]], snapshot: dict[str, Any], plan: Any
) -> dict[str, Any]:
    started, cpu = time.perf_counter(), time.process_time()
    mode = plan.experiment_mode
    evidence = (
        scanner(snapshot.get("point_in_time_universe"), plan)
        if mode == "observation_priority"
        else component_replay(snapshot["records"], mode, plan)
    )
    return {
        "version": CONTRACT["version"],
        "mode": mode,
        "status": "inconclusive",
        "decision": "reject",
        "eligible_for_forward_review": False,
        "reason": "Independent component retained; qualification and prospective proof unavailable",
        "contract": CONTRACT,
        "opportunities": len(rows),
        "labeled": 0,
        "unknown_outcomes": len(rows),
        "changed_decisions": 0,
        "missed_positive_taken_trades": 0,
        "whole_account_effect": None,
        "comparisons": [
            {
                "episode": mode,
                "status": evidence["status"],
                "action": "shadow_only",
                "later_net_trade_bps": None,
                "evidence": evidence,
            }
        ],
        "controls": [
            "unchanged_baseline",
            "remove_only_this_component",
            "matched_cash_unavailable",
        ],
        "limitations": [
            "Exit, size and observation are not combined",
            "No pooled fictitious capital",
            "Memory-informed account controls require separate prior entry evidence",
        ],
        "resources": {
            "elapsed_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "paid_usd": "0",
        },
    }
