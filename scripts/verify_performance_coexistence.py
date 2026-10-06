"""Finite real-wall native paper/capture workload around one caller-owned model dispatch.

Import run_coexistence from a private driver. The async model_dispatch callback must
yield (run the existing blocking model runner in its normal worker thread), honor
stop_requested, and return its retained receipt. This helper never dispatches a model.
"""

import asyncio
import hashlib
import json
import math
import shutil
import sqlite3
import time
import uuid
from collections import deque
from collections.abc import Callable, Coroutine
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from verify_performance_diagnostics import (
    DISK_RESERVE_BYTES,
    ROOT,
    SYMBOLS,
    distribution,
    events,
    fixture,
    source_hashes,
)

from trading.compact_memory import linked_events
from trading.engine_diagnostics import PRESSURE_POLICY_VERSION, EngineWorkPressurePolicy
from trading.evidence_runtime import EvidenceRecorder, compact_prefix, plain, state_snapshot
from trading.execution_window import diagnostic_admission
from trading.paper_diagnostics import (
    create_diagnostic,
    diagnostic_snapshot,
    start_diagnostic,
    stop_diagnostic,
)
from trading.paper_engine import PaperEngine
from trading.paper_store import PaperStore, load_dsn
from trading.research_evidence import EvidenceArchive, EvidencePlan, canonical, digest

TICK_SECONDS = 0.5
WARMUP_LIMIT_SECONDS = 20
BASELINE_SECONDS = 30
MODEL_LIMIT_SECONDS = 600
RECOVERY_SECONDS = 30
DRAIN_SECONDS = 5
WALL_LIMIT_SECONDS = 700
MAX_TICKS = 1400
CLEANUP_LIMIT_SECONDS = 20
DIAGNOSTIC = "performance-diagnostic"
COUNTS = ("order_intent", "fill", "partial_fill", "order_cancelled", "trade_closed")
ModelDispatch = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


def frozen_source() -> dict[str, str]:
    result = source_hashes()
    result["engine_diagnostics.py"] = hashlib.sha256(
        (ROOT / "src" / "trading" / "engine_diagnostics.py").read_bytes()
    ).hexdigest()
    result["coexistence_verifier"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical(plain(value)), encoding="utf-8")
    temporary.replace(path)


def write_live_status(output: Path, value: dict[str, Any], omissions: int) -> int:
    """A Windows reader may hold the optional projection; durable receipts stay strict."""
    try:
        write_json(output / "live.json", dict(value, live_status_omissions=omissions))
    except PermissionError as error:
        if getattr(error, "winerror", None) not in {5, 32, 33}:
            raise
        omissions += 1
        with (output / "live-status-errors.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(
                canonical(
                    {
                        "kind": "optional_live_projection_omitted",
                        "tick": value.get("tick"),
                        "wall_at": time.time(),
                        "omission_count": omissions,
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "winerror": error.winerror,
                        "financial_and_capture_records_retained": True,
                    }
                )
                + "\n"
            )
            stream.flush()
    return omissions


def close_capture(recorder: EvidenceRecorder) -> None:
    for resource in (recorder._archive, recorder._compact, recorder._maturity, recorder._storage):
        if resource is not None:
            resource.close()


async def finish_callback(
    task: asyncio.Task[dict[str, Any]] | None,
    stop_requested: asyncio.Event,
    deadline_mono: float,
) -> dict[str, Any]:
    """Wait for caller-owned cooperative cleanup; never cancel its worker indirectly."""
    stop_requested.set()
    if task is None:
        return {"status": "not_dispatched", "callback_finished": True}
    timeout = max(0.0, min(CLEANUP_LIMIT_SECONDS, deadline_mono - time.monotonic()))
    if not task.done():
        await asyncio.wait({task}, timeout=timeout)
    if not task.done():
        return {
            "status": "unresolved",
            "callback_finished": False,
            "wait_limit_seconds": timeout,
            "owned_child_cleanup_verified": False,
        }
    try:
        receipt = task.result()
    except BaseException as error:
        receipt = {
            "status": "failed",
            "error_type": type(error).__name__,
            "error": str(error),
        }
    return {
        "status": "callback_finished",
        "callback_finished": True,
        "wait_limit_seconds": timeout,
        "model_receipt": receipt,
        "owned_child_cleanup_verified": receipt.get("owned_child_cleanup_verified") is True,
    }


def verify_captures(path: Path, expected: dict[int, dict[str, Any]]) -> dict[str, Any]:
    seen: set[int] = set()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        for payload, sha256 in connection.execute(
            "SELECT payload,sha256 FROM evidence_records WHERE kind='decision' ORDER BY id"
        ):
            packet = json.loads(payload)
            assert digest(packet) == sha256
            receipt = packet["financial_commit"]
            revision = receipt["revision"]
            assert revision in expected and revision not in seen
            recorded = expected[revision]
            assert packet["after_tick_sha256"] == recorded["projection_sha256"]
            assert [r["event_id"] for r in receipt["events"]] == recorded["event_ids"]
            assert diagnostic_admission(packet) is recorded["diagnostic_allowed"]
            assert packet["receipt_to_dispatch_ms"] == recorded["receipt_to_dispatch_ms"]
            assert all(
                math.isfinite(value) and value >= 0
                for value in packet["receipt_to_dispatch_ms"].values()
            )
            seen.add(revision)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    assert seen == set(expected) and integrity == "ok"
    return {
        "decision_packets": len(seen),
        "hashes_and_financial_references_match": True,
        "recorded_admission_and_monotonic_timing_verified": True,
        "reopened_integrity": integrity,
        "full_causal_feature_replay_verified": False,
    }


async def run_coexistence(
    database_config: Path,
    output: Path,
    model_dispatch: ModelDispatch,
    *,
    baseline_seconds: float = BASELINE_SECONDS,
    model_limit_seconds: float = MODEL_LIMIT_SECONDS,
    recovery_seconds: float = RECOVERY_SECONDS,
    model_evidence_kind: str = "caller_owned_unverified",
) -> dict[str, Any]:
    """Measure one diagnostic run and capture; caller owns its single model attempt.

    Callback inputs include the real owned store, detached committed state/current
    synthetic inputs, live pressure owner, and a cooperative asyncio stop event.
    Finite phase/live/controller files permit independent monitoring and stopping.
    """
    began = time.monotonic()
    deadline = began + WALL_LIMIT_SECONDS
    if any(
        type(value) not in (float, int) or not math.isfinite(value) or value < 2
        for value in (baseline_seconds, model_limit_seconds, recovery_seconds)
    ):
        raise ValueError("Phase durations must be finite and at least two seconds")
    if (
        baseline_seconds > BASELINE_SECONDS
        or model_limit_seconds > MODEL_LIMIT_SECONDS
        or recovery_seconds > RECOVERY_SECONDS
    ):
        raise ValueError("Phase durations cannot exceed the frozen finite bounds")
    if model_evidence_kind not in {
        "caller_owned_unverified",
        "actual_local_model",
        "procedural_fake_callback",
    }:
        raise ValueError("Declare the callback evidence scope explicitly")
    dsn = load_dsn(database_config)
    info = conninfo_to_dict(dsn)
    if info.get("host") != "127.0.0.1" or info.get("port") != "54544":
        raise ValueError("Use the explicitly owned loopback 54544 disposable QA database")
    output.mkdir(parents=True, exist_ok=False)
    source = frozen_source()
    declaration = {
        "evidence_kind": "synthetic_native_financial_actual_model_coexistence",
        "financial_inputs": (
            "Explicit synthetic current BTC/ETH books and valid synthetic risk bars"
        ),
        "clock": "Actual wall timestamps and monotonic pacing; no accelerated fixture/replay clock",
        "tick_seconds": TICK_SECONDS,
        "warmup_limit_seconds": WARMUP_LIMIT_SECONDS,
        "baseline_seconds": baseline_seconds,
        "model_limit_seconds": model_limit_seconds,
        "recovery_seconds": recovery_seconds,
        "final_drain_seconds": DRAIN_SECONDS,
        "model_evidence_kind": model_evidence_kind,
        "procedural_only": model_evidence_kind == "procedural_fake_callback",
        "wall_limit_seconds": WALL_LIMIT_SECONDS,
        "maximum_ticks": MAX_TICKS,
        "callback_cleanup_limit_seconds": CLEANUP_LIMIT_SECONDS,
        "diagnostic": {
            "fake_capital": "1000000",
            "seed": 1,
            "max_actions": 1000,
            "duration_seconds": 600,
            "restarts": 0,
        },
        "pressure_policy": PRESSURE_POLICY_VERSION,
        "source_sha256": source,
        "measurement_scope": (
            "Fixture/capture preparation, native SQL commit, full/compact capture flush, "
            "SQL balance and storage readback"
        ),
        "operating_market_or_installed_runtime_verified": False,
    }
    write_json(output / "declaration.json", declaration)
    write_json(output / "controller.json", {"stop_requested": False})
    schema = f"pdiagcoexist_{uuid.uuid4().hex}"
    test_dsn = make_conninfo(dsn, options=f"-c search_path={schema}", connect_timeout=5)
    pressure = EngineWorkPressurePolicy()
    stop_requested = asyncio.Event()
    model_task: asyncio.Task[dict[str, Any]] | None = None
    model_receipt: dict[str, Any] | None = None
    model_finished_at: float | None = None
    model_timed_out = False
    expected: dict[int, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    phase_events: list[dict[str, Any]] = []
    store: PaperStore | None = None
    recorder: EvidenceRecorder | None = None
    admin = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    phase = "warmup"
    phase_started = began
    next_tick = began
    workload_started = False
    drain_started = False
    drain_started_mono: float | None = None
    archive_path = output / "research-evidence.sqlite"
    counts = dict.fromkeys(COUNTS, 0)
    live_status_omissions = 0

    def mark(value: str) -> None:
        nonlocal phase, phase_started
        phase, phase_started = value, time.monotonic()
        record = {
            "phase": value,
            "wall_at": time.time(),
            "mono_at": phase_started,
            "elapsed_seconds": phase_started - began,
            "completed_ticks": len(rows),
        }
        phase_events.append(record)
        write_json(output / "phase.json", record)
        with (output / "phases.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(canonical(record) + "\n")

    def record_model_start(details: dict[str, Any]) -> None:
        admission = pressure.evaluate(time.monotonic())
        if not admission.pressure_allows or stop_requested.is_set():
            stop_requested.set()
            write_json(
                output / "root-model-admission-closed.json",
                {
                    "wall_at": time.time(),
                    "mono_at": time.monotonic(),
                    "pressure": asdict(admission),
                    "details": details,
                    "model_dispatch_authorized_by_qa": False,
                },
            )
            raise RuntimeError("Measured QA pressure admission closed before model dispatch")
        write_json(
            output / "root-model-start.json",
            {
                "wall_at": time.time(),
                "mono_at": time.monotonic(),
                "details": details,
                "helper_model_boundary_mono": phase_started,
                "scope": (
                    "Caller-reported existing runner dispatch; "
                    "child start belongs to its retained receipt"
                ),
            },
        )

    try:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        store = PaperStore(test_dsn, owner=True)
        initialized_at = time.time()
        store.initialize(initialized_at)

        def setup(engine: PaperEngine) -> None:
            engine.state["evidence_kind"] = "synthetic_qa"
            engine.universe_experiment(list(SYMBOLS))

        store.transact(initialized_at, setup)
        originals = deepcopy(store.read()["accounts"])
        prefix = events(store)
        assert len(originals) == 6
        EvidenceArchive(archive_path, EvidencePlan(max_bytes=128 * 1024**2)).close()
        recorder = EvidenceRecorder(archive_path)
        after = store.read()
        frames: dict[str, Any] = {}
        studies: dict[str, Any] = {}
        histories: dict[str, Any] = {}
        packet: dict[str, Any] = {}
        mark("warmup")
        with (output / "financial-work.jsonl").open("a", encoding="utf-8") as stream:
            while True:
                now_mono = time.monotonic()
                if now_mono >= deadline or len(rows) >= MAX_TICKS:
                    raise TimeoutError("Finite native coexistence wall/tick budget exhausted")
                if (
                    json.loads((output / "controller.json").read_text(encoding="utf-8-sig")).get(
                        "stop_requested"
                    )
                    is True
                ):
                    stop_requested.set()
                elapsed_phase = now_mono - phase_started
                if phase == "warmup":
                    if pressure.evaluate(now_mono).pressure_allows:
                        before_creation = deepcopy(store.read()["accounts"])
                        creation_prefix = events(store)

                        def start(engine: PaperEngine) -> None:
                            create_diagnostic(engine, "coexistence-diagnostic-create")
                            start_diagnostic(engine, "coexistence-diagnostic-start", 1)

                        store.transact(time.time(), start)
                        assert {
                            n: a for n, a in store.read()["accounts"].items() if n != DIAGNOSTIC
                        } == before_creation
                        assert events(store)[: len(creation_prefix)] == creation_prefix
                        workload_started = True
                        mark("baseline")
                    elif elapsed_phase >= WARMUP_LIMIT_SECONDS:
                        raise TimeoutError("Measured native work never established calm admission")
                elif phase == "baseline" and elapsed_phase >= baseline_seconds:
                    mark("model")
                    latest = rows[-1]
                    handoff = {
                        "store": store,
                        "state": deepcopy(after),
                        "frames": deepcopy(frames),
                        "studies": deepcopy(studies),
                        "histories": deepcopy(histories),
                        "packet": deepcopy(packet),
                        "pressure_policy": pressure,
                        "stop_requested": stop_requested,
                        "output": output,
                        "phase": phase,
                        "last_native_work": latest,
                        "source_sha256": source,
                        "model_deadline_mono": min(deadline, phase_started + model_limit_seconds),
                        "model_deadline_wall": time.time() + model_limit_seconds,
                        "record_model_start": record_model_start,
                    }
                    write_json(
                        output / "model-handoff.json",
                        {
                            key: value
                            for key, value in handoff.items()
                            if key
                            not in {
                                "store",
                                "pressure_policy",
                                "stop_requested",
                                "record_model_start",
                            }
                        },
                    )
                    model_task = asyncio.create_task(model_dispatch(handoff))
                elif phase == "model":
                    assert model_task is not None
                    if model_task.done():
                        model_finished_at = time.monotonic()
                        try:
                            model_receipt = model_task.result()
                        except BaseException as error:
                            model_receipt = {
                                "status": "failed",
                                "error_type": type(error).__name__,
                                "error": str(error),
                            }
                        write_json(output / "model-receipt.json", model_receipt)
                        mark("recovery")
                    elif elapsed_phase >= model_limit_seconds or stop_requested.is_set():
                        model_timed_out = elapsed_phase >= model_limit_seconds
                        stop_requested.set()
                        mark("recovery")
                elif phase == "recovery":
                    if elapsed_phase >= recovery_seconds and not drain_started:

                        def stop(engine: PaperEngine) -> None:
                            stop_diagnostic(engine, "coexistence-diagnostic-stop")

                        store.transact(time.time(), stop)
                        drain_started = True
                        drain_started_mono = time.monotonic()
                    if (
                        drain_started
                        and diagnostic_snapshot(store.read())["run"]["status"] == "completed"
                    ):
                        break
                    if (
                        drain_started_mono is not None
                        and now_mono - drain_started_mono >= DRAIN_SECONDS
                    ):
                        raise TimeoutError(
                            "Known diagnostic inventory did not drain within the final five seconds"
                        )
                if stop_requested.is_set() and phase in {"warmup", "baseline"}:
                    raise RuntimeError("Controller stopped before the single model dispatch")
                scheduled_mono = next_tick
                await asyncio.sleep(
                    max(0, min(next_tick - time.monotonic(), deadline - time.monotonic()))
                )
                tick_mono = time.monotonic()
                evaluation = pressure.evaluate(tick_mono)
                at = time.time()
                work_start = time.perf_counter()
                frames, studies, histories = fixture(at, len(rows) + 1)
                packet = recorder.prepare(
                    at,
                    frames,
                    studies,
                    histories,
                    dict.fromkeys(SYMBOLS, at),
                    initialized_at - 120,
                    {},
                    {},
                    [],
                    {symbol: deque() for symbol in SYMBOLS},
                    {"coverage": "Synthetic native workload; actual local model owned by caller"},
                    feature_timing={symbol: {"available_at": at} for symbol in SYMBOLS},
                    input_eligibility={
                        symbol: {"status": "synthetic_qa_valid"} for symbol in SYMBOLS
                    },
                )
                measured: dict[str, Any] = {}

                def apply(
                    engine: PaperEngine,
                    packet: dict[str, Any] = packet,
                    frames: dict[str, Any] = frames,
                    studies: dict[str, Any] = studies,
                    measured: dict[str, Any] = measured,
                    diagnostic_allowed: bool = evaluation.pressure_allows,
                ) -> None:
                    measured["dispatch_mono"] = time.monotonic()
                    packet["state_before"] = state_snapshot(engine.state)
                    packet["diagnostic_allowed"] = diagnostic_allowed
                    engine.evidence_trace = []
                    engine.tick(frames, studies, diagnostic_allowed=diagnostic_allowed)
                    measured.update(events=engine.events, traces=engine.evidence_trace or [])

                commit_start = time.perf_counter()
                after, receipt = store.transact_with_receipt(at, apply, capture_projection=True)
                committed = time.perf_counter()
                assert receipt is not None
                recorder.complete(
                    packet,
                    measured["events"],
                    after,
                    measured["traces"],
                    {"transaction": (committed - commit_start) * 1000},
                    measured["dispatch_mono"],
                    receipt,
                )
                recorder.compact(
                    {
                        "at": at,
                        "collected_at": at,
                        "fresh": True,
                        "prefix": compact_prefix(
                            at,
                            frames["BTCUSD"],
                            histories["BTCUSD"],
                            at,
                            studies["BTCUSD"]["breakout-v1"],
                            "synthetic_qa",
                        ),
                        "events": linked_events(measured["events"], receipt),
                    }
                )
                await asyncio.wait_for(
                    recorder.flush(shutil.disk_usage(output).free >= DISK_RESERVE_BYTES),
                    timeout=max(0.001, min(10, deadline - time.monotonic())),
                )
                capture_finished = time.perf_counter()
                balance = store.reconcile()
                storage = store.storage_usage()
                assert balance["balanced"], (
                    "Actual native journal/projection readback is unbalanced"
                )
                finished = time.perf_counter()
                whole_ms = (finished - work_start) * 1000
                observed_mono = time.monotonic()
                pressure.observe(whole_ms, observed_mono)
                pressure_after = pressure.evaluate(observed_mono)
                if phase == "model" and not pressure_after.pressure_allows:
                    stop_requested.set()
                    write_json(
                        output / "guard-stop.json",
                        {
                            "wall_at": time.time(),
                            "mono_at": observed_mono,
                            "reason": (
                                "Actual native EngineWorkPressurePolicy closed during model overlap"
                            ),
                            "pressure": asdict(pressure_after),
                        },
                    )
                delta = dict.fromkeys(COUNTS, 0)
                for event in measured["events"]:
                    if event["account"] == DIAGNOSTIC:
                        if event["kind"] in delta:
                            delta[event["kind"]] += 1
                        if event["kind"] == "fill" and event["body"]["partial"]:
                            delta["partial_fill"] += 1
                for kind in COUNTS:
                    counts[kind] += delta[kind]
                snapshot = diagnostic_snapshot(after)
                positions = sum(len(account["positions"]) for account in after["accounts"].values())
                pending = sum(len(account["pending"]) for account in after["accounts"].values())
                row = {
                    "tick": len(rows) + 1,
                    "phase": phase,
                    "wall_at": at,
                    "mono_at": tick_mono,
                    "elapsed_seconds": tick_mono - began,
                    "schedule_lateness_ms": max(0, (tick_mono - scheduled_mono) * 1000),
                    "whole_work_ms": whole_ms,
                    "transaction_ms": (committed - commit_start) * 1000,
                    "capture_and_flush_ms": (capture_finished - committed) * 1000,
                    "readback_ms": (finished - capture_finished) * 1000,
                    "diagnostic_allowed": evaluation.pressure_allows,
                    "pressure_before": asdict(evaluation),
                    "pressure_after": asdict(pressure_after),
                    "positions": positions,
                    "pending": pending,
                    "diagnostic_run": snapshot["run"],
                    "event_counts": delta,
                    "events": measured["events"],
                    "financial_commit": receipt,
                    "sql_balance": balance,
                    "sql_storage": storage,
                    "capture_status": recorder.snapshot(),
                    "draining_final_phase": drain_started,
                    "model_pending": model_task is not None and not model_task.done(),
                    "live_status_omissions_before_tick": live_status_omissions,
                }
                rows.append(row)
                assert (
                    row["capture_status"]["dropped"] == row["capture_status"]["queue_dropped"] == 0
                )
                assert row["capture_status"]["compact_memory"]["omitted"] == 0
                stream.write(canonical(plain(row)) + "\n")
                stream.flush()
                live_status_omissions = write_live_status(
                    output,
                    {key: value for key, value in row.items() if key != "events"},
                    live_status_omissions,
                )
                expected[receipt["revision"]] = {
                    "projection_sha256": receipt["projection_sha256"],
                    "event_ids": [ref["event_id"] for ref in receipt["events"]],
                    "diagnostic_allowed": evaluation.pressure_allows,
                    "receipt_to_dispatch_ms": {
                        symbol: max(0, (measured["dispatch_mono"] - frame["received_mono"]) * 1000)
                        for symbol, frame in frames.items()
                    },
                }
                next_tick = max(next_tick + TICK_SECONDS, observed_mono)
        if model_task is not None and model_task.done() and model_receipt is None:
            model_finished_at = time.monotonic()
            try:
                model_receipt = model_task.result()
            except BaseException as error:
                model_receipt = {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            write_json(output / "model-receipt.json", model_receipt)
        assert model_task is not None
        callback_cleanup = await finish_callback(model_task, stop_requested, deadline)
        write_json(output / "callback-cleanup.json", callback_cleanup)
        assert callback_cleanup["callback_finished"], (
            "Caller-owned model cleanup remains unresolved"
        )
        if model_receipt is None:
            model_receipt = callback_cleanup["model_receipt"]
            write_json(output / "model-receipt.json", model_receipt)
        final = store.read()
        history = events(store)
        assert history[: len(prefix)] == prefix
        assert workload_started
        assert history[: len(creation_prefix)] == creation_prefix
        for name, original in originals.items():
            assert all(
                final["accounts"][name][field] == original[field]
                for field in ("cash", "funding", "fees", "starting_capital", "positions", "pending")
            )
        assert diagnostic_snapshot(final)["run"]["status"] == "completed"
        status = recorder.snapshot()
        assert status["dropped"] == status["queue_dropped"] == status["queue"] == 0
        assert status["compact_memory"]["omitted"] == status["compact_memory"]["queue"] == 0
        write_json(output / "final-financial-state.json", final)
        with (output / "financial-history.jsonl").open("w", encoding="utf-8") as stream:
            for event in history:
                stream.write(canonical(plain(event)) + "\n")
        store.close()
        store = None
        close_capture(recorder)
        recorder = None
        view = PaperStore(test_dsn)
        try:
            assert view.read() == final and view.reconcile()["balanced"]
            assert events(view) == history
            final_storage = view.storage_usage()
        finally:
            view.close()
        captured = verify_captures(archive_path, expected)
        assert frozen_source() == source, "Measured source changed during coexistence"
        summaries = {}
        for name in ("warmup", "baseline", "model", "recovery"):
            selected = [row for row in rows if row["phase"] == name]
            if selected:
                summaries[name] = {
                    "ticks": len(selected),
                    "whole_work": distribution([row["whole_work_ms"] for row in selected]),
                    "draining_ticks": sum(row["draining_final_phase"] for row in selected),
                    "event_counts": {
                        kind: sum(row["event_counts"][kind] for row in selected) for kind in COUNTS
                    },
                    "admitted_ticks": sum(row["diagnostic_allowed"] for row in selected),
                    "active_inventory_or_orders_ticks": sum(
                        bool(row["positions"] or row["pending"]) for row in selected
                    ),
                    "running_workload_ticks": sum(
                        row["diagnostic_run"] is not None
                        and row["diagnostic_run"]["status"] == "running"
                        for row in selected
                    ),
                    "model_pending_ticks": sum(row["model_pending"] for row in selected),
                }
        result = {
            "status": "passed",
            "declaration": declaration,
            "phases": phase_events,
            "phase_summaries": summaries,
            "actual_wall_seconds": time.monotonic() - began,
            "ticks": len(rows),
            "counts": counts,
            "live_status_omissions": live_status_omissions,
            "diagnostic_run": diagnostic_snapshot(final)["run"],
            "model_receipt": model_receipt,
            "callback_cleanup": callback_cleanup,
            "model_finished_mono": model_finished_at,
            "model_timed_out": model_timed_out,
            "native_financial_and_capture_verified": True,
            "capture": captured,
            "capture_status": status,
            "final_sql_storage": final_storage,
            "original_prefix_preserved": True,
            "original_prefix_sha256": digest(plain(prefix)),
            "full_precreation_prefix_preserved": True,
            "precreation_prefix_sha256": digest(plain(creation_prefix)),
            "original_accounts_preserved_at_creation": True,
            "baseline_accounts_final": {
                name: account for name, account in final["accounts"].items() if name != DIAGNOSTIC
            },
            "native_reopen_balanced": True,
            "retired_owned_schema": schema,
            "limitation": (
                "Synthetic financial inputs with caller-owned callback overlap; "
                "complete installed market/runtime/UI admission remains unverified. "
                "Active workload may end before the model; per-tick records disclose "
                "its exact overlap. A fake callback is procedural proof only."
            ),
        }
        assert (
            schema.startswith("pdiagcoexist_") and len(schema.removeprefix("pdiagcoexist_")) == 32
        )
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        mark("finished")
        write_json(output / "receipt.json", result)
        return result
    except BaseException as error:
        callback_cleanup = await finish_callback(model_task, stop_requested, deadline)
        write_json(output / "callback-cleanup.json", callback_cleanup)
        write_json(
            output / "failed-receipt.json",
            {
                "status": "failed",
                "error_type": type(error).__name__,
                "error": str(error),
                "declaration": declaration,
                "phase": phase,
                "completed_ticks": len(rows),
                "counts": counts,
                "live_status_omissions": live_status_omissions,
                "retained_schema": schema,
                "model_task_pending": model_task is not None and not model_task.done(),
                "callback_cleanup": callback_cleanup,
            },
        )
        raise
    finally:
        if store is not None:
            store.close()
        if recorder is not None:
            close_capture(recorder)
        admin.close()


if __name__ == "__main__":
    raise SystemExit(
        "No default model dispatcher. Import run_coexistence from the authorized "
        "private driver and supply its single existing-runner callback."
    )
