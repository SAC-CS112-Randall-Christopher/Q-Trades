"""Matched disposable native financial/capture QA; synthetic inputs, no market/model proof."""

import argparse
import asyncio
import hashlib
import json
import math
import shutil
import sqlite3
import time
import uuid
from collections import deque
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from trading.compact_memory import linked_events
from trading.evidence_runtime import EvidenceRecorder, compact_prefix, plain, state_snapshot
from trading.execution_window import diagnostic_admission
from trading.market import parse_book
from trading.paper_diagnostics import create_diagnostic, diagnostic_snapshot, start_diagnostic
from trading.paper_engine import PaperEngine
from trading.paper_store import PaperStore, load_dsn
from trading.paper_strategy import VARIANTS, Bar
from trading.research_evidence import EvidenceArchive, EvidencePlan, canonical, digest

ROOT = Path(__file__).resolve().parents[1]
START = 1_800_000_000.0
SYMBOLS = ("BTCUSD", "ETHUSD")
WALL_LIMIT_SECONDS = 600
DISK_RESERVE_BYTES = 5 * 1024**3


def source_hashes() -> dict[str, str]:
    names = (
        "paper_engine.py",
        "paper_diagnostics.py",
        "account_purpose.py",
        "paper_store.py",
        "evidence_runtime.py",
        "research_evidence.py",
        "compact_memory.py",
        "paper_economics.py",
        "execution_profiles.py",
        "execution_window.py",
        "market.py",
        "paper_strategy.py",
    )
    result = {
        name: hashlib.sha256((ROOT / "src" / "trading" / name).read_bytes()).hexdigest()
        for name in names
    }
    result["verifier"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def distribution(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "samples": len(values),
        "p50_ms": ordered[math.ceil(len(ordered) * 0.50) - 1],
        "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "p99_ms": ordered[math.ceil(len(ordered) * 0.99) - 1],
        "maximum_ms": ordered[-1],
    }


def fixture(at: float, sequence: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The marker and ATR are explicitly synthetic; no runtime eligibility is inferred."""
    frames, studies, histories = {}, {}, {}
    end = int(at // 60) * 60000
    for symbol, price, shallow_quantity in (("BTCUSD", "100", "1"), ("ETHUSD", "50", "2")):
        quantity = shallow_quantity if sequence % 17 == 0 else "100000"
        p = D(price)
        raw = {
            "lastUpdateId": sequence,
            "bids": [[price, quantity]],
            "asks": [[str(p + D("0.02")), quantity]],
        }
        frames[symbol] = {
            "book": parse_book(raw),
            "raw": raw,
            "observed": at,
            "base": symbol[:-3],
            "instrument": {"symbol": symbol},
            "source": "synthetic-performance-diagnostic-native-qa",
            "received_mono": time.monotonic(),
            "entry_allowed": True,
            "diagnostic_risk_input_valid": True,
            "evidence_kind": "synthetic_qa",
            "rules": {
                "step": D("0.00001"),
                "tick": D("0.01"),
                "min_qty": D("0.00001"),
                "max_qty": D(10000),
                "min_notional": D(1),
                "min_price": D("0.01"),
                "max_price": D(1_000_000),
            },
        }
        studies[symbol] = {
            version: {
                "eligible": False,
                "bar_open_ms": end - 60000,
                "atr": "1",
                "reason": "Synthetic signal-negative fixture",
                "version": version,
                "evidence_kind": "synthetic_qa",
            }
            for version in VARIANTS
        }
        histories[symbol] = [
            Bar(end - (16 - i) * 60000, p, p + 1, p - 1, p, D(100), end - (15 - i) * 60000 - 1)
            for i in range(16)
        ]
    return frames, studies, histories


def events(store: PaperStore) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    after = 0
    for _ in range(100):
        page = store.export(after, 250)
        result.extend(page["records"])
        if not page["has_more"]:
            return result
        after = page["next_after"]
    raise RuntimeError("Disposable history exceeded twenty-five thousand events")


def verify_capture(path: Path, expected: dict[int, dict[str, Any]]) -> dict[str, Any]:
    seen = set()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        for payload, sha256 in connection.execute(
            "SELECT payload,sha256 FROM evidence_records WHERE kind='decision' ORDER BY id"
        ):
            packet = json.loads(payload)
            assert digest(packet) == sha256, "Reopened capture payload hash differs"
            receipt = packet["financial_commit"]
            revision = receipt["revision"]
            assert revision not in seen and revision in expected
            assert packet["after_tick_sha256"] == expected[revision]["projection_sha256"]
            assert [r["event_id"] for r in receipt["events"]] == expected[revision]["event_ids"]
            assert diagnostic_admission(packet) is True
            assert packet["receipt_to_dispatch_ms"] == expected[revision]["receipt_to_dispatch_ms"]
            assert all(
                math.isfinite(ms) and ms >= 0 for ms in packet["receipt_to_dispatch_ms"].values()
            )
            seen.add(revision)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    assert seen == set(expected) and integrity == "ok"
    return {
        "decision_packets": len(seen),
        "hashes_and_financial_references_match": True,
        "recorded_diagnostic_admission_verified": True,
        "receipt_to_dispatch_monotonic_verified": True,
        "full_causal_feature_replay_verified": False,
        "reopened_integrity": integrity,
    }


async def case(
    dsn: str,
    mode: str,
    directory: Path,
    ticks: int,
    deadline: float,
) -> dict[str, Any]:
    directory.mkdir()
    schema = f"pdiagqa_{mode}_{uuid.uuid4().hex}"
    test_dsn = make_conninfo(dsn, options=f"-c search_path={schema}", connect_timeout=5)
    expected: dict[int, dict[str, Any]] = {}
    samples: dict[str, list[float]] = {"whole_work": [], "transaction": [], "capture_and_flush": []}
    path = directory / "research-evidence.sqlite"
    counts: dict[str, int] = {
        "order_intent": 0,
        "fill": 0,
        "partial_fill": 0,
        "order_cancelled": 0,
        "trade_closed": 0,
    }
    max_positions = max_pending = 0
    store: PaperStore | None = None
    admin = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    verified = False
    recorder: EvidenceRecorder | None = None
    began = time.perf_counter()
    try:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        store = PaperStore(test_dsn, owner=True)
        store.initialize(START)

        def setup_fixture(engine: PaperEngine) -> None:
            engine.state["evidence_kind"] = "synthetic_qa"
            engine.universe_experiment(list(SYMBOLS))

        store.transact(START, setup_fixture)
        original_accounts = deepcopy(store.read()["accounts"])
        original_prefix = events(store)
        assert len(original_accounts) == 6
        if mode == "diagnostic":

            def create_account(engine: PaperEngine) -> None:
                create_diagnostic(engine, "native-diagnostic-create")

            def start_workload(engine: PaperEngine) -> None:
                start_diagnostic(engine, "native-diagnostic-start", 1)

            store.transact(START, create_account)
            assert {
                n: a for n, a in store.read()["accounts"].items() if n != "performance-diagnostic"
            } == original_accounts
            assert events(store)[: len(original_prefix)] == original_prefix
            store.transact(START, start_workload)
        # A declared disposable capacity is persisted before the normal recorder
        # opens it. Operating research storage and its frozen plan are untouched.
        with_archive = EvidenceArchive(path, EvidencePlan(max_bytes=128 * 1024**2))
        with_archive.close()
        recorder = EvidenceRecorder(path)
        for index in range(ticks):
            if time.monotonic() >= deadline:
                raise TimeoutError("Ten-minute native verifier wall budget exhausted")
            at = START + index * 0.5
            work_start = time.perf_counter()
            frames, studies, histories = fixture(at, index + 1)
            packet = recorder.prepare(
                at,
                frames,
                studies,
                histories,
                dict.fromkeys(SYMBOLS, at),
                START - 120,
                {},
                {},
                [],
                {s: deque() for s in SYMBOLS},
                {"coverage": "Explicit synthetic matched native QA; no operating feed"},
                feature_timing={s: {"available_at": at} for s in SYMBOLS},
                input_eligibility={s: {"status": "synthetic_qa_valid"} for s in SYMBOLS},
            )
            measured: dict[str, Any] = {}

            def apply(
                engine: PaperEngine,
                packet: dict[str, Any] = packet,
                frames: dict[str, Any] = frames,
                studies: dict[str, Any] = studies,
                measured: dict[str, Any] = measured,
            ) -> None:
                measured["dispatch_mono"] = time.monotonic()
                packet["state_before"] = state_snapshot(engine.state)
                packet["diagnostic_allowed"] = True
                engine.evidence_trace = []
                engine.tick(frames, studies, diagnostic_allowed=packet["diagnostic_allowed"])
                measured.update(events=engine.events, traces=engine.evidence_trace or [])

            commit_start = time.perf_counter()
            after, receipt = store.transact_with_receipt(at, apply, capture_projection=True)
            committed = time.perf_counter()
            assert receipt is not None
            transaction_ms = (committed - commit_start) * 1000
            recorder.complete(
                packet,
                measured["events"],
                after,
                measured["traces"],
                {"transaction": transaction_ms},
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
            actual_disk_ok = shutil.disk_usage(directory).free >= DISK_RESERVE_BYTES
            await asyncio.wait_for(recorder.flush(actual_disk_ok), timeout=10)
            finished = time.perf_counter()
            samples["whole_work"].append((finished - work_start) * 1000)
            samples["transaction"].append(transaction_ms)
            samples["capture_and_flush"].append((finished - committed) * 1000)
            expected[receipt["revision"]] = {
                "projection_sha256": receipt["projection_sha256"],
                "event_ids": [r["event_id"] for r in receipt["events"]],
                "receipt_to_dispatch_ms": {
                    symbol: max(0, (measured["dispatch_mono"] - frame["received_mono"]) * 1000)
                    for symbol, frame in frames.items()
                },
            }
            for event in measured["events"]:
                if event["account"] != "performance-diagnostic":
                    continue
                if event["kind"] in counts:
                    counts[event["kind"]] += 1
                if event["kind"] == "fill" and event["body"]["partial"]:
                    counts["partial_fill"] += 1
            max_positions = max(
                max_positions, sum(len(a["positions"]) for a in after["accounts"].values())
            )
            max_pending = max(
                max_pending, sum(len(a["pending"]) for a in after["accounts"].values())
            )
            if (index + 1) % 100 == 0:
                print(f"{mode}: {index + 1}/{ticks} native ticks completed", flush=True)
        capture_status = recorder.snapshot()
        assert capture_status["queue"] == capture_status["queue_dropped"] == 0
        assert capture_status["compact_memory"]["queue"] == 0
        assert capture_status["compact_memory"]["omitted"] == 0
        full_history = events(store)
        assert full_history[: len(original_prefix)] == original_prefix
        final = store.read()
        assert store.reconcile()["balanced"]
        (directory / "final-financial-state.json").write_text(canonical(final), encoding="utf-8")
        with (directory / "financial-history.jsonl").open("w", encoding="utf-8") as stream:
            for event in full_history:
                stream.write(json.dumps(event, sort_keys=True, default=str) + "\n")
        store.close()
        store = None
        for resource in (
            recorder._archive,
            recorder._compact,
            recorder._maturity,
            recorder._storage,
        ):
            if resource is not None:
                resource.close()
        recorder = None
        with_view = PaperStore(test_dsn)
        try:
            assert with_view.read() == final and with_view.reconcile()["balanced"]
            assert events(with_view) == full_history
        finally:
            with_view.close()
        captured = verify_capture(path, expected)
        snapshot = diagnostic_snapshot(final)
        if mode == "diagnostic":
            assert counts["fill"] > 0 and counts["trade_closed"] > 0 and counts["partial_fill"] > 0
            assert snapshot["run"]["status"] == "completed", (
                "Known inventory did not finish draining"
            )
            assert snapshot["run"]["attempted"] == 1000
        verified = True
        return {
            "mode": mode,
            "ticks": ticks,
            "fixture_seconds": (ticks - 1) * 0.5,
            "actual_wall_seconds": time.perf_counter() - began,
            "native_timings": {name: distribution(values) for name, values in samples.items()},
            "raw_timing_samples_ms": samples,
            "diagnostic_event_counts": counts,
            "diagnostic_run": snapshot["run"],
            "max_positions": max_positions,
            "max_pending": max_pending,
            "retained_financial_events": len(full_history),
            "original_prefix_preserved": True,
            "original_prefix_sha256": digest(plain(original_prefix)),
            "original_accounts_preserved_at_creation": True,
            "native_reopen_balanced": True,
            "capture": captured,
            "capture_status": capture_status,
            "baseline_final_accounts": {
                n: a for n, a in final["accounts"].items() if n != "performance-diagnostic"
            },
            "retired_owned_schema": schema,
        }
    finally:
        if store is not None:
            store.close()
        if recorder is not None:
            for resource in (
                recorder._archive,
                recorder._compact,
                recorder._maturity,
                recorder._storage,
            ):
                if resource is not None:
                    resource.close()
        if verified:
            assert schema.startswith(f"pdiagqa_{mode}_") and len(schema.rsplit("_", 1)[1]) == 32
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        else:
            (directory / "retained-failed-schema.json").write_text(
                json.dumps(
                    {
                        "schema": schema,
                        "verified": False,
                        "mode": mode,
                        "completed_ticks": len(samples["whole_work"]),
                        "timings_ms": samples,
                        "counts": counts,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        admin.close()


async def run(database_config: Path, output: Path, ticks: int) -> dict[str, Any]:
    if not 550 <= ticks <= 600:
        raise ValueError("The matched volume verifier uses five hundred fifty to six hundred ticks")
    dsn = load_dsn(database_config)
    info = conninfo_to_dict(dsn)
    if info.get("host") != "127.0.0.1" or info.get("port") != "54544":
        raise ValueError("Use the explicitly owned disposable QA PostgreSQL on loopback 54544")
    output.mkdir(parents=True, exist_ok=False)
    declaration = {
        "evidence_kind": "synthetic_native_performance_workload",
        "declared_at": time.time(),
        "ticks_per_case": ticks,
        "fixture_step_seconds": 0.5,
        "seed": 1,
        "diagnostic_fake_cash": "1000000",
        "max_actions": 1000,
        "duration_seconds": 600,
        "max_wall_seconds_total": WALL_LIMIT_SECONDS,
        "same_inputs": "Sequenced BTC/ETH books; deep except each seventeenth shallow book",
        "fixture_clock": "Accelerated fixture clock; operating and replay clocks untouched",
        "whole_work_scope": (
            "Fixture build, capture prepare, native SQL transaction, "
            "full/compact completion and flush"
        ),
        "capture_flush_timeout_seconds": 10,
        "operating_resource_admission_verified": False,
        "actual_market_or_model_coexistence_verified": False,
        "mature_feedback_or_strategy_value_verified": False,
        "source_sha256": source_hashes(),
    }
    (output / "declaration.json").write_text(json.dumps(declaration, indent=2), encoding="utf-8")
    deadline = time.monotonic() + WALL_LIMIT_SECONDS
    try:
        baseline = await case(dsn, "baseline", output / "baseline", ticks, deadline)
        (output / "baseline-receipt.json").write_text(
            json.dumps(baseline, indent=2), encoding="utf-8"
        )
        diagnostic = await case(dsn, "diagnostic", output / "diagnostic", ticks, deadline)
        (output / "diagnostic-receipt.json").write_text(
            json.dumps(diagnostic, indent=2), encoding="utf-8"
        )
        assert baseline["baseline_final_accounts"] == diagnostic["baseline_final_accounts"]
        assert source_hashes() == declaration["source_sha256"], (
            "Measured source changed during the run"
        )
        result = {
            "status": "passed",
            "declaration": declaration,
            "cases": [baseline, diagnostic],
            "matched_baseline_accounts_equal": True,
            "limitation": (
                "Two sequential native synthetic cases; host interference "
                "and real-feed/model overlap are unproven"
            ),
        }
        (output / "receipt.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    except BaseException as error:
        (output / "failed-receipt.json").write_text(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "declaration": declaration,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ticks", type=int, default=600)
    args = parser.parse_args()
    completed = asyncio.run(run(args.database_config, args.output, args.ticks))
    print(
        json.dumps(
            {
                "status": completed["status"],
                "matched_baseline_accounts_equal": True,
                "cases": [
                    {
                        "mode": c["mode"],
                        "native_timings": c["native_timings"],
                        "counts": c["diagnostic_event_counts"],
                    }
                    for c in completed["cases"]
                ],
            }
        )
    )
