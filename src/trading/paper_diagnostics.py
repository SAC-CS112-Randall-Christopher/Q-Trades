"""Finite performance-only paper workload inside the existing financial writer."""

import hashlib
import math
import re
from copy import deepcopy
from decimal import Decimal as D
from typing import TYPE_CHECKING, Any

from trading.account_purpose import (
    PERFORMANCE_DIAGNOSTIC_ACCOUNT,
    PERFORMANCE_DIAGNOSTIC_PURPOSE,
    PERFORMANCE_DIAGNOSTIC_VERSION,
    is_performance_diagnostic,
)

if TYPE_CHECKING:
    from trading.paper_engine import PaperEngine

FAKE_CAPITAL = "1000000"
NOTIONAL_CAP = D("1000")
MAX_ACTIONS_PER_TICK = 8
CONTRACT: dict[str, Any] = {
    "version": "performance-diagnostic-workload-v1",
    "symbols": ["BTCUSD", "ETHUSD"],
    "notional_cap_usd": str(NOTIONAL_CAP),
    "symbol_cooldown_seconds": 1,
    "hold_seconds": [1, 2, 3, 4],
    "max_actions_per_tick": MAX_ACTIONS_PER_TICK,
    "execution_profile": "paper-rest-ioc-v1",
    "randomness": "sha256-seed-sequence-v1",
}


def _request_id(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-zA-Z0-9-]{12,64}", value) is None:
        raise ValueError("Use a twelve-to-sixty-four-character diagnostic request identity")


def _clock(engine: "PaperEngine") -> None:
    if (
        not isinstance(engine.now, (int, float))
        or isinstance(engine.now, bool)
        or not math.isfinite(engine.now)
    ):
        raise ValueError("A diagnostic workload requires a finite financial clock")


def _account(state: dict[str, Any]) -> dict[str, Any]:
    a: dict[str, Any] | None = state["accounts"].get(PERFORMANCE_DIAGNOSTIC_ACCOUNT)
    if not a or not is_performance_diagnostic(a, PERFORMANCE_DIAGNOSTIC_ACCOUNT):
        raise ValueError("Create the Performance Diagnostic account first")
    if (
        a["version"] != PERFORMANCE_DIAGNOSTIC_VERSION
        or a.get("purpose") != PERFORMANCE_DIAGNOSTIC_PURPOSE
        or a.get("starting_capital") != FAKE_CAPITAL
        or a.get("funding") != FAKE_CAPITAL
        or a.get("risk_policy") != "cash-spot-hard-stop-v1"
        or a.get("execution_profile") != CONTRACT["execution_profile"]
        or a.get("diagnostic", {}).get("contract") != CONTRACT
    ):
        raise ValueError("The frozen Performance Diagnostic configuration needs inspection")
    return a


def current_run(a: dict[str, Any]) -> dict[str, Any] | None:
    diagnostic = a["diagnostic"]
    run: dict[str, Any] | None = diagnostic["runs"].get(diagnostic.get("active_request_id"))
    return run


def diagnostic_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    a = state["accounts"].get(PERFORMANCE_DIAGNOSTIC_ACCOUNT)
    run = current_run(a) if a and "diagnostic" in a else None
    summary = deepcopy(run)
    if summary:
        summary["remaining"] = max(0, summary["max_actions"] - summary["attempted"])
    return {
        "created": a is not None,
        "account_name": PERFORMANCE_DIAGNOSTIC_ACCOUNT,
        "purpose": PERFORMANCE_DIAGNOSTIC_PURPOSE,
        "fake_capital": FAKE_CAPITAL,
        "account": deepcopy(a),
        "run": summary,
        "create_request_id": a.get("create_request_id") if a else None,
        "last_control_request_id": a.get("last_control_request_id") if a else None,
        "applied_request_ids": (
            [a["create_request_id"], *a["diagnostic"]["runs"], *a["diagnostic"]["stop_requests"]]
            if a and "diagnostic" in a
            else []
        ),
    }


def _result(
    engine: "PaperEngine",
    status: str,
    action: str,
    request_id: str,
    run_request_id: str | None = None,
    receipt_status: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        **diagnostic_snapshot(engine.state),
        "requested_receipt": {
            "action": action,
            "request_id": request_id,
            "run_request_id": run_request_id,
            "status": receipt_status or status,
        },
    }


def create_diagnostic(engine: "PaperEngine", request_id: str) -> dict[str, Any]:
    from trading.autonomous_finance import slots
    from trading.paper_engine import account

    _request_id(request_id)
    _clock(engine)
    existing = engine.state["accounts"].get(PERFORMANCE_DIAGNOSTIC_ACCOUNT)
    if existing:
        _account(engine.state)
        if existing.get("create_request_id") != request_id:
            raise ValueError("The single diagnostic account already exists; no funding was added")
        return _result(engine, "already_applied", "create", request_id, receipt_status="created")
    capacity = slots(engine.state)
    if capacity["available"] < 1 or capacity["used"] >= 20:
        raise ValueError("Twenty managed/reserved account slots are full")
    # The normal research-account factory still only accepts $50/$100. This
    # separate, fixed-purpose account has one frozen hypothetical funding amount.
    a = account(PERFORMANCE_DIAGNOSTIC_VERSION, engine.now, "100", "paper-rest-ioc-v1")
    for key in ("starting_capital", "cash", "funding", "equity", "risk_peak", "units", "day_start"):
        a[key] = FAKE_CAPITAL
    a.update(
        purpose=PERFORMANCE_DIAGNOSTIC_PURPOSE,
        label="Performance Diagnostic",
        create_request_id=request_id,
        last_control_request_id=request_id,
        symbols=list(CONTRACT["symbols"]),
        operating_daily_usd="0",
        entries_paused=False,
        control_version=0,
        diagnostic={"contract": deepcopy(CONTRACT), "runs": {}, "stop_requests": {}},
    )
    a["attempt"]["outcome"] = "performance_only"
    engine.state["accounts"][PERFORMANCE_DIAGNOSTIC_ACCOUNT] = a
    amount = D(FAKE_CAPITAL)
    engine.emit(
        "performance_diagnostic_funded",
        PERFORMANCE_DIAGNOSTIC_ACCOUNT,
        {
            "request_id": request_id,
            "amount": FAKE_CAPITAL,
            "currency": "USD",
            "purpose": PERFORMANCE_DIAGNOSTIC_PURPOSE,
            "version": PERFORMANCE_DIAGNOSTIC_VERSION,
            "contract": deepcopy(CONTRACT),
            "hypothetical_only": True,
        },
        [engine.line("USD", "cash", amount), engine.line("USD", "fake_funding", -amount)],
    )
    engine.assert_invariants()
    return _result(engine, "created", "create", request_id)


def start_diagnostic(
    engine: "PaperEngine",
    request_id: str,
    seed: int,
    max_actions: int = 1000,
    duration_seconds: int = 600,
) -> dict[str, Any]:
    _request_id(request_id)
    _clock(engine)
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("Use an unsigned thirty-two-bit diagnostic seed")
    if type(max_actions) is not int or not 1 <= max_actions <= 1000:
        raise ValueError("A diagnostic workload has one to one thousand actions")
    if type(duration_seconds) is not int or not 1 <= duration_seconds <= 600:
        raise ValueError("A diagnostic workload lasts one to six hundred seconds")
    a = _account(engine.state)
    diagnostic = a["diagnostic"]
    config = {"seed": seed, "max_actions": max_actions, "duration_seconds": duration_seconds}
    previous = diagnostic["runs"].get(request_id)
    if previous:
        if any(previous[key] != value for key, value in config.items()):
            raise ValueError("This diagnostic start request already has different limits")
        return _result(
            engine, "already_applied", "start", request_id, request_id, previous["status"]
        )
    run = current_run(a)
    if run and run["status"] in {"running", "draining"}:
        raise ValueError("The previous diagnostic workload is still running or draining")
    if len(diagnostic["runs"]) >= 16:
        raise ValueError(
            "Sixteen diagnostic workload receipts are retained; no history was removed"
        )
    if (
        a.get("fault")
        or a.get("execution_uncertain")
        or a["failure_pending"]
        or a["drawdown_pause"]
        or a["daily_pause"]
    ):
        raise ValueError("Diagnostic risk/fault stops must remain in force")
    run = {
        "request_id": request_id,
        **config,
        "status": "running",
        "started_at": engine.now,
        "ends_at": engine.now + duration_seconds,
        "attempted": 0,
        "intents": 0,
        "fills": 0,
        "cancels": 0,
        "errors": 0,
        "completed": 0,
        "last_books": {},
        "last_tick_at": None,
        "reason": "Finite performance-only workload running",
    }
    diagnostic["runs"][request_id] = run
    diagnostic["active_request_id"] = request_id
    a["last_control_request_id"] = request_id
    engine.emit("performance_diagnostic_started", PERFORMANCE_DIAGNOSTIC_ACCOUNT, deepcopy(run))
    return _result(engine, "started", "start", request_id, request_id)


def _drain(engine: "PaperEngine", a: dict[str, Any], reason: str) -> None:
    run = current_run(a)
    if run and run["status"] == "running":
        run.update(status="draining", reason=reason)
        engine.emit(
            "performance_diagnostic_draining",
            PERFORMANCE_DIAGNOSTIC_ACCOUNT,
            {"request_id": run["request_id"], "reason": reason},
        )
    for symbol, order in list(a["pending"].items()):
        if (
            order["side"] == "buy"
            and not order.get("uncertain")
            and not a.get("execution_uncertain")
        ):
            engine.cancel(PERFORMANCE_DIAGNOSTIC_ACCOUNT, a, symbol, reason)


def stop_diagnostic(engine: "PaperEngine", request_id: str) -> dict[str, Any]:
    _request_id(request_id)
    _clock(engine)
    a = _account(engine.state)
    diagnostic = a["diagnostic"]
    if request_id in diagnostic["stop_requests"]:
        return _result(
            engine,
            "already_applied",
            "stop",
            request_id,
            diagnostic["stop_requests"][request_id],
            "stopped",
        )
    if len(diagnostic["stop_requests"]) >= 32:
        raise ValueError("Thirty-two diagnostic stop receipts are retained")
    run = current_run(a)
    diagnostic["stop_requests"][request_id] = run["request_id"] if run else None
    a["last_control_request_id"] = request_id
    _drain(engine, a, "Operator stopped the Performance Diagnostic workload")
    _finish(engine, a)
    engine.emit(
        "performance_diagnostic_stopped",
        PERFORMANCE_DIAGNOSTIC_ACCOUNT,
        {"request_id": request_id, "run_request_id": run["request_id"] if run else None},
    )
    return _result(engine, "stopped", "stop", request_id, run["request_id"] if run else None)


def _finish(engine: "PaperEngine", a: dict[str, Any]) -> None:
    run = current_run(a)
    if (
        run
        and run["status"] == "draining"
        and not a["positions"]
        and not a["pending"]
        and not a.get("execution_uncertain")
    ):
        run.update(status="completed", completed_at=engine.now)
        engine.emit(
            "performance_diagnostic_completed",
            PERFORMANCE_DIAGNOSTIC_ACCOUNT,
            {
                "request_id": run["request_id"],
                "attempted": run["attempted"],
                "fills": run["fills"],
                "reason": run["reason"],
            },
        )


def prepare_tick(engine: "PaperEngine", a: dict[str, Any]) -> None:
    _account(engine.state)
    run = current_run(a)
    if run and run["status"] == "running":
        if engine.now >= run["ends_at"]:
            _drain(engine, a, "Finite diagnostic time budget ended")
        elif run["attempted"] >= run["max_actions"]:
            _drain(engine, a, "Finite diagnostic action budget ended")
        elif a["failure_pending"] or a["drawdown_pause"] or a["daily_pause"]:
            _drain(engine, a, "Existing diagnostic account risk stop")
        elif a.get("execution_uncertain") or any(o.get("uncertain") for o in a["pending"].values()):
            _drain(engine, a, "Diagnostic execution uncertain; no new orders")
    if not engine.diagnostic_allowed:
        for symbol, order in list(a["pending"].items()):
            if (
                order["side"] == "buy"
                and not order.get("uncertain")
                and not a.get("execution_uncertain")
            ):
                engine.cancel(
                    PERFORMANCE_DIAGNOSTIC_ACCOUNT,
                    a,
                    symbol,
                    "Diagnostic admission constrained; exits continue",
                )


def tick_diagnostic(
    engine: "PaperEngine",
    a: dict[str, Any],
    frames: dict[str, dict[str, Any]],
    study: dict[str, Any],
) -> None:
    from trading.paper_engine import fresh_frame

    _finish(engine, a)
    run = current_run(a)
    if not run or run["status"] != "running":
        return
    if a["failure_pending"] or a["drawdown_pause"] or a["daily_pause"]:
        _drain(engine, a, "Existing diagnostic account risk stop")
        _finish(engine, a)
        return
    if not engine.diagnostic_allowed:
        run["reason"] = "Diagnostic admission constrained; position management continues"
        return
    if run["last_tick_at"] is not None and engine.now <= run["last_tick_at"]:
        return
    run["last_tick_at"] = engine.now
    actions = 0
    # A symbol gets at most one generated action per distinct executable book.
    # Normal fills independently reject already-consumed liquidity after restart.
    for symbol in CONTRACT["symbols"]:
        frame = frames.get(symbol)
        if not frame or not fresh_frame(frame, engine.now):
            continue
        sequence = frame["book"].update_id
        if sequence <= run["last_books"].get(symbol, -1):
            continue
        if actions >= MAX_ACTIONS_PER_TICK or run["attempted"] >= run["max_actions"]:
            break
        run["last_books"][symbol] = sequence
        random_value = int.from_bytes(
            hashlib.sha256(f"{run['seed']}:{run['attempted']}".encode("ascii")).digest(), "big"
        )
        run["attempted"] += 1
        actions += 1
        action, reason = "entry", ""
        order = a["pending"].get(symbol)
        if order:
            action = "cancel" if order["side"] == "buy" and random_value % 5 == 0 else "wait"
            if order.get("uncertain") or a.get("execution_uncertain"):
                action = "wait"
            if (
                action == "cancel"
                and not order.get("uncertain")
                and not a.get("execution_uncertain")
            ):
                engine.cancel(
                    PERFORMANCE_DIAGNOSTIC_ACCOUNT,
                    a,
                    symbol,
                    "Seeded Performance Diagnostic cancellation",
                )
            reason = (
                "Existing pending order retained" if action == "wait" else "Diagnostic cancellation"
            )
        elif symbol in a["positions"]:
            action = "exit" if random_value % 3 == 0 else "hold"
            if action == "exit":
                a["positions"][symbol]["diagnostic_exit_requested"] = True
                engine.exit_position(PERFORMANCE_DIAGNOSTIC_ACCOUNT, a, symbol, frame, {})
            reason = "Diagnostic position management"
        else:
            atr = next(
                (
                    row.get("atr")
                    for row in study.get(symbol, {}).values()
                    if isinstance(row, dict) and row.get("atr") is not None
                ),
                None,
            )
            if frame.get("diagnostic_risk_input_valid") is not True:
                reason = "Protected current diagnostic market/risk inputs unavailable"
            elif atr is None:
                reason = "Current closed-bar ATR unavailable; no fabricated risk input"
            else:
                atr_value = D(str(atr))
                if not atr_value.is_finite() or atr_value <= 0:
                    reason = "Current ATR is invalid; no diagnostic entry"
                else:
                    notional = ("25", "50", "100", "250", "500", "1000")[random_value % 6]
                    feature = {
                        "eligible": True,
                        "reason": "Seeded performance-only entry",
                        "atr": str(atr_value),
                        "version": PERFORMANCE_DIAGNOSTIC_VERSION,
                        "diagnostic_notional_usd": notional,
                        "diagnostic_hold_seconds": CONTRACT["hold_seconds"][random_value % 4],
                        "diagnostic_request_id": run["request_id"],
                        "diagnostic_sequence": run["attempted"],
                        "purpose": PERFORMANCE_DIAGNOSTIC_PURPOSE,
                    }
                    reason = engine.enter(PERFORMANCE_DIAGNOSTIC_ACCOUNT, a, symbol, frame, feature)
        run["reason"] = reason
        engine.emit(
            "performance_diagnostic_action",
            PERFORMANCE_DIAGNOSTIC_ACCOUNT,
            {
                "request_id": run["request_id"],
                "sequence": run["attempted"],
                "symbol": symbol,
                "action": action,
                "reason": reason,
                "book_sequence": sequence,
            },
        )
    if run["attempted"] >= run["max_actions"]:
        _drain(engine, a, "Finite diagnostic action budget ended")
        _finish(engine, a)
