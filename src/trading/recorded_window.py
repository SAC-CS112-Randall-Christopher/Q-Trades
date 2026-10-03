"""Streaming baseline-only audit of a finite original recorded execution window.

Uses the same PaperEngine and original inputs. It does not reset counterfactual
accounts in small replay chunks or make a strategy-discovery comparison.
"""

import time
from collections.abc import Iterable
from typing import Any

from trading.execution_replay import (
    balanced,
    checked_packet,
    data_mode,
    financial_chain,
    hydrated_frames,
    ordered_state,
)
from trading.execution_window import replay_tick
from trading.paper_engine import PaperEngine
from trading.research_evidence import digest


def verify_recorded_window(
    records: Iterable[dict[str, Any]],
    current: dict[str, str],
    *,
    max_records: int = 10000,
    max_bytes: int = 16_000_000_000,
    max_seconds: int = 1800,
) -> dict[str, Any]:
    if (
        not 1 <= max_records <= 10000
        or not 1 <= max_bytes <= 16_000_000_000
        or not 1 <= max_seconds <= 1800
    ):
        raise ValueError("Use a finite baseline-audit budget")
    started = time.monotonic()
    previous, prior_at, prior_revision, first, mode, request = None, None, None, None, None, None
    count, size, fills, no_trade = 0, 0, 0, 0
    books: dict[str, tuple[float, int, str]] = {}
    chain = "0" * 64
    horizon, failure = False, None
    for record in records:
        try:
            if count >= max_records or time.monotonic() - started > max_seconds:
                raise ValueError("Finite baseline-audit budget reached")
            packet = checked_packet(record, current)
            window = packet.get("execution_window")
            if not window or "pre_tick" not in packet:
                raise ValueError("The complete-window capture/pre-tick contract is absent")
            at = packet["at"]
            if first is None:
                first, request, mode = at, window["request_id"], data_mode(packet)
                if mode not in {"paper_observations", "synthetic"}:
                    raise ValueError("Unknown or mixed execution source mode")
            if (
                window["request_id"] != request
                or window["first_at"] != first
                or window["required_end_at"] != first + 2700
                or data_mode(packet) != mode
            ):
                raise ValueError("Capture request, horizon or data mode changed")
            if prior_at is not None and not 0 <= at - prior_at <= 5:
                raise ValueError("Unsupported financial observation gap")
            revision = (packet.get("financial_commit") or {}).get("revision")
            if type(revision) is not int or (
                prior_revision is not None and revision != prior_revision + 1
            ):
                raise ValueError("Unrecorded financial commit; no state bridge is inferred")
            frame = packet["frames"].get("BTCUSD")
            rows = packet["bars"].get("BTCUSD", [])
            if (
                frame is None
                or not 0 <= at - frame["observed"] <= 5
                or len(rows) < 305
                or any(
                    b["open_ms"] != a["open_ms"] + 60000
                    for a, b in zip(rows, rows[1:], strict=False)
                )
                or any(r["available_at"] > at or r["close_ms"] >= at * 1000 for r in rows)
                or not 0 <= at * 1000 - rows[-1]["close_ms"] <= 90000
            ):
                raise ValueError("Required causal BTCUSD warmup/book/minute inputs are incomplete")
            for symbol, observed in packet["frames"].items():
                prior = books.get(symbol)
                sequence, received = observed["raw"]["lastUpdateId"], observed["observed"]
                identity = digest(observed["raw"])
                if prior and (
                    received < prior[0]
                    or sequence < prior[1]
                    or (sequence == prior[1] and identity != prior[2])
                ):
                    raise ValueError("Recorded book chronology/content conflict")
                books[symbol] = (received, sequence, identity)
            if previous is not None and financial_chain(previous) != financial_chain(
                packet["state_before"]
            ):
                raise ValueError("Unrecorded state transition; no snapshot reset is allowed")
            engine = PaperEngine(ordered_state(packet), at)
            replay_tick(engine, packet, hydrated_frames(packet))
            if (
                digest(engine.state) != packet["after_tick_sha256"]
                or engine.events != packet["events"]
                or not balanced(engine.events)
            ):
                raise ValueError(
                    "Original state, ordered events or journal accounting did not reconcile"
                )
            from trading.research_evidence import canonical

            size += len(canonical(packet))
            if size > max_bytes:
                raise ValueError("Finite baseline-audit byte budget reached")
            count += 1
            fills += sum(e["kind"] == "fill" for e in engine.events)
            no_trade += int(not any(e["kind"] in {"fill", "order_intent"} for e in engine.events))
            chain = digest(
                {"prior": chain, "id": record["id"], "sha": record["sha256"], "revision": revision}
            )
            previous, prior_at, prior_revision = engine.state, at, revision
            if at >= first + 2700:
                horizon = True
                break
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            failure = {"record_id": record.get("id"), "reason": str(exc)}
            break
    return {
        "status": "complete_baseline_reconciled" if horizon and failure is None else "incomplete",
        "data_mode": mode,
        "request_id": request,
        "records_reconciled": count,
        "input_bytes": size,
        "first_at": first,
        "last_at": prior_at,
        "observed_seconds": max(0, prior_at - first)
        if first is not None and prior_at is not None
        else 0,
        "required_outcome_seconds": 2700,
        "full_horizon_verified": horizon and failure is None,
        "boundary": failure,
        "fill_events": fills,
        "no_trade_ticks": no_trade,
        "fill_accounting_representative": "unproven; inspect actual representative fills"
        if fills
        else "unproven; no fills",
        "chain_sha256": chain,
        "wall_seconds": time.monotonic() - started,
        "market_improvement_established": False,
        "financial_authority": False,
    }
