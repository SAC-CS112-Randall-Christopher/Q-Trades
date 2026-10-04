"""Shared scoped evidence dispatch and information-use protection; no financial mutation."""

import copy
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg.conninfo import make_conninfo

from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore
from trading.research_storage import load_plan
from trading.station import execute_tool, validate_symbol
from trading.strategy_diagnosis import cost_diagnosis, input_coverage, interval_start
from trading.tiered_runtime import TieredPaperRuntime


@contextmanager
def reader(runtime: PaperRuntime) -> Iterator[PaperStore]:
    info = runtime.store.connection.info
    view = PaperStore(make_conninfo(info.dsn, password=info.password, connect_timeout=3))
    try:
        with view.connection.transaction():
            view.connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            yield view
    finally:
        view.close()


def run(
    runtime: TieredPaperRuntime,
    tool: str,
    symbol: str,
    account: str,
    request_id: str,
    *,
    start: float = 0,
) -> dict[str, Any]:
    began = time.perf_counter()
    cutoff = time.time()
    validate_symbol(symbol, runtime)
    diagnostic = tool in {"input_diagnosis", "cost_diagnosis"}
    if diagnostic:
        start = interval_start(start, cutoff)
    outcomes = None
    # All IO executes in the API worker pool, using a separate authenticated connection.
    # Disposable read-only unit stubs explicitly expose no permanent journal.
    if isinstance(runtime.store, PaperStore):
        with reader(runtime) as view:
            snapshot = view.research_account(account)
            cutoff = snapshot["cutoff"]
            saved = snapshot["state"]
            if tool in {"outcome_review", "cost_diagnosis"}:
                if diagnostic:
                    view.connection.execute("SET LOCAL statement_timeout=1500")
                outcomes = view.research_outcomes(snapshot, symbol, start=start)
                if tool == "cost_diagnosis":
                    outcomes["original_cost_groups"] = view.research_cost_groups(
                        snapshot, symbol, start=start
                    )
    else:
        saved = copy.deepcopy(runtime.state["accounts"].get(account))
        snapshot = {
            "account": account,
            "revision": runtime.state.get("revision"),
            "cutoff": cutoff,
            "archived": False,
            "maximum_event_id": None,
            "trial_id": saved.get("lab_trial") if saved else None,
        }
    if saved is None:
        raise ValueError("Selected account is unavailable; no primary fallback")
    if tool == "input_diagnosis":
        result = {
            "tool": tool,
            "version": "strategy-diagnosis-v1",
            "observed_at": cutoff,
            "result": input_coverage(
                load_plan(runtime.capture_path.parent), symbol, account, start, cutoff
            ),
        }
    elif tool == "cost_diagnosis":
        if outcomes is None:
            raise ValueError("Durable accounting reader unavailable; no rolling-trade substitute")
        result = {
            "tool": tool,
            "version": "strategy-diagnosis-v1",
            "observed_at": cutoff,
            "result": cost_diagnosis(outcomes),
        }
    else:
        result = execute_tool(runtime, tool, symbol, account, saved, outcomes)
    retrieved = time.time()
    if diagnostic:
        result["result"]["current_request_counts"] = runtime.public_request_counts()
        result["result"]["unresolved"].append(
            "Current request counters cannot reconstruct transport totals at older recorded ticks"
        )
    snapshot = {key: value for key, value in snapshot.items() if key != "state"}
    spec = saved.get("rule_spec", {})
    decision = saved["last_decision"].get(symbol)
    available = decision.get("at") if decision else None
    if tool == "market_evidence":
        detail = result["result"]["detail"]
        # Baseline comparison and primary rolling events have their own views/scopes.
        detail["experiments"] = {"scope": "Separate baseline comparison in Strategy Lab"}
        detail["paper_events"] = []
        quote = next(iter(result["result"]["live"]["markets"]), None)
        available = (
            retrieved - quote["received_age_ms"] / 1000
            if (quote and quote.get("received_age_ms") is not None)
            else None
        )
    elif tool in {"outcome_review", "cost_diagnosis"} and outcomes:
        available = max((event["at"] for event in outcomes["events"]), default=None)
    elif tool == "input_diagnosis":
        available = max(
            (
                r["source_available_at"]
                for r in result["result"]["rows"]
                if r["source_available_at"]
            ),
            default=None,
        )
    result["envelope"] = {
        "schema": "scoped-tool-envelope-v1",
        "request_id": request_id,
        "actor": "local_operator",
        "task_id": None,
        "account": account,
        "trial_id": snapshot["trial_id"],
        "family": spec.get("family"),
        "security": symbol,
        "timeframe": "1m",
        "venue": "binance.us",
        "horizon": spec.get("holding_horizon"),
        "maximum_hold_seconds": spec.get("exit_seconds"),
        "interval": {"start": start, "end": cutoff},
        "observation_cutoff": retrieved,
        "source_available_at": available,
        "retrieved_at": retrieved,
        "snapshot": snapshot,
        "status": result["result"].get("status", "available"),
        "facts_basis": "Decimal strings, frozen cost assumptions and exact recorded decisions",
        "disclosure_start": min(start, saved.get("admitted_at", cutoff)),
        "query_seconds": time.perf_counter() - began,
        "receipt_limit_bytes": 131072,
        "model_tokens": None,
        "token_basis": "No model tokenizer was executed",
        "references": [
            {"type": "paper-state-revision", "id": snapshot["revision"], "account": account}
        ],
    }
    if tool == "market_evidence":
        detail = result["result"]["detail"]
        result["envelope"]["coverage"] = {
            "saved_trades": len(result["result"]["live"]["trades"]),
            "saved_candles": len(detail["candles"]),
            "saved_indicator_points": len(detail["indicators"]["points"]),
            "calculation_history_bars": detail["indicators"]["calculation_history_bars"],
            "points_omitted": detail["indicators"]["points_omitted"],
            "candle_gaps": len(detail["candle_gaps"]),
        }
    return result


def disclose(registry: ExperimentRegistry, receipt: dict[str, Any]) -> None:
    """Record every saved/detail/cache disclosure before response serialization."""
    result = receipt.get("result")
    if not result:
        return
    envelope = result.get("envelope")
    if envelope:
        start, end = envelope["disclosure_start"], envelope["observation_cutoff"]
    else:
        # Legacy evidence has no precise membership window. Consume conservatively.
        start, end = 0, receipt.get("finished") or receipt["started"]
    identity = "tool-disclosure:" + fingerprint(
        {"id": receipt["id"], "sha": receipt["result_sha256"], "start": start, "end": end}
    )
    with registry.transaction():
        registry.db.execute(
            "INSERT OR IGNORE INTO evidence_windows VALUES(?,?,?,'tool outcome disclosure')",
            (identity, start, end),
        )


def outcome_page(
    runtime: TieredPaperRuntime, receipt: dict[str, Any], before: int
) -> dict[str, Any]:
    snapshot = receipt["result"]["envelope"]["snapshot"]
    with reader(runtime) as view:
        return view.research_events(
            receipt["account"],
            receipt["symbol"],
            snapshot["cutoff"],
            snapshot["maximum_event_id"],
            before=before,
            start=receipt["result"]["envelope"]["interval"]["start"],
        )
