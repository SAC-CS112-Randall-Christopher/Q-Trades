"""CP10 disposable evidence workflow and finite Windows synthetic timing, no live inputs."""

import argparse
import asyncio
import copy
import hashlib
import json
import platform
import subprocess
import tempfile
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import uvicorn
from psycopg.conninfo import conninfo_to_dict
from verify_cp3 import disposable, frames, rss_bytes

from trading.api import create_app
from trading.config import Settings
from trading.evidence_runtime import EvidenceRecorder, frozen_bars, plain
from trading.paper_campaigns import CampaignSpec, create_campaign
from trading.paper_engine import PaperEngine
from trading.paper_store import load_dsn
from trading.paper_strategy import VARIANTS, Bar, features
from trading.research_evidence import EvidenceArchive
from trading.tiered_runtime import TieredPaperRuntime

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = {
    "fixture": "Synthetic sequenced visible books and closed-bar inputs; no market latency claim",
    "accounts": [1, 10, 20],
    "ticks_per_case": 120,
    "ticks_per_second": 4,
    "symbols": ["BTCUSD", "ETHUSD"],
    "full_bundle_each_tick": True,
    "commit_p95_limit_ms": 250,
    "loop_p95_limit_ms": 100,
    "rss_limit_mib": 512,
    "rss_growth_limit_mib": 64,
    "archive_budget_bytes": 64 * 1024 * 1024,
    "queue_limit": 8,
    "snapshot_copy_repetitions": 200,
    "duration_clock": "perf_counter high-resolution monotonic; first coarse-clock red retained",
    "purpose": "Evidence/financial software behavior; no strategy advantage or live authority",
}


def verify_database():
    info = conninfo_to_dict(load_dsn(ROOT / "data/paper-database.json"))
    if info.get("host") != "127.0.0.1" or info.get("port") != "55633":
        raise RuntimeError("This acceptance requires the dedicated disposable local test cluster")


def bars_at(at, shift="0"):
    end = int(at // 60) * 60000
    result = []
    for i in range(400):
        start = end - (400 - i) * 60000
        p = D(100) + D(shift) + D(i) / 100
        result.append(
            Bar(
                start,
                p,
                p + D(".005"),
                p - D(".01"),
                p,
                D(30) if i == 399 else D(10),
                start + 59999,
            )
        )
    return result


def percentiles(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return {
        "p50": ordered[int((len(ordered) - 1) * 0.5)],
        "p95": ordered[int((len(ordered) - 1) * 0.95)],
        "p99": ordered[int((len(ordered) - 1) * 0.99)],
        "max": ordered[-1],
    }


def recorded_tick(store, recorder, at, sequence, *, validate=True):
    started = time.perf_counter()
    receipt_mono = time.monotonic()
    f = frames(at, sequence)
    book_batch_ms = (time.perf_counter() - started) * 1000
    for value in f.values():
        value["received_mono"] = receipt_mono
        value["source"] = "cp10-synthetic-acceptance"
    bars = bars_at(at)
    feature_timing, study = {}, {}
    feature_start = time.perf_counter()
    for symbol in f:
        compute_start = time.perf_counter()
        study[symbol] = {v: features(bars, at, v) for v in VARIANTS}
        feature_timing[symbol] = {
            "available_at": time.time(),
            "available_mono": time.perf_counter(),
            "compute_ms": (time.perf_counter() - compute_start) * 1000,
        }
    feature_batch_ms = (time.perf_counter() - feature_start) * 1000
    histories = dict.fromkeys(f, bars)
    decision_at = max(at, time.time())
    packet = recorder.prepare(
        decision_at,
        f,
        study,
        histories,
        dict.fromkeys(f, at),
        0,
        {},
        {},
        [],
        dict.fromkeys(f, deque()),
        {"coverage": "Synthetic acceptance only"},
        feature_timing=feature_timing,
    )
    measured = {}

    def apply(engine):
        packet["state_before"] = plain(engine.state)
        engine.evidence_trace = []
        engine.tick(f, study)
        measured.update(
            events=engine.events,
            after=plain(engine.state),
            traces=list(engine.evidence_trace),
        )

    before_commit = time.perf_counter()
    store.transact(decision_at, apply)
    committed = time.perf_counter()
    stages = {
        "book_batch_validation": book_batch_ms,
        "feature_batch_compute": feature_batch_ms,
        "prepare": (before_commit - started) * 1000,
        "transaction": (committed - before_commit) * 1000,
    }
    recorder.complete(
        packet,
        measured["events"],
        measured["after"],
        measured["traces"],
        stages,
        receipt_mono,
        store.last_commit_receipt,
    )
    asyncio.run(recorder.flush())
    finished = time.perf_counter()
    if validate:
        original = PaperEngine(copy.deepcopy(packet["state_before"]), decision_at)
        original.tick(f, study)
        assert original.state == measured["after"] and original.events == measured["events"]
    return {
        **stages,
        "evidence_write": (finished - committed) * 1000,
        "total_before_validation": (finished - started) * 1000,
        "queue_wait": packet.get("queue_wait_ms", 0),
    }


def benchmark(output):
    verify_database()
    receipt = {
        "contract": CONTRACT,
        "declared_at": time.time(),
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_files": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                ROOT / "src/trading/evidence_runtime.py",
                ROOT / "src/trading/research_evidence.py",
                ROOT / "src/trading/paper_engine.py",
            ]
        },
        "host": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cases": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    bars, available = bars_at(time.time()), time.time()
    old_times, new_times = [], []
    for _ in range(CONTRACT["snapshot_copy_repetitions"]):
        started = time.perf_counter()
        original = plain([{**asdict(b), "available_at": available} for b in bars])
        old_times.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        copied = frozen_bars(bars, available)
        new_times.append((time.perf_counter() - started) * 1000)
        assert copied == original
    receipt["paired_snapshot_copy"] = {
        "identical_values": True,
        "input_sha256": hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest(),
        "scope": "Same 400 immutable bars; old asdict/JSON copy versus explicit scalar copy",
        "baseline_ms": percentiles(old_times),
        "optimized_ms": percentiles(new_times),
    }
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    for count in CONTRACT["accounts"]:
        with disposable() as store, tempfile.TemporaryDirectory(prefix="cp10-evidence-") as folder:
            spec = CampaignSpec.model_validate(
                {
                    "request_id": f"evidence-case-{count}",
                    "name": "Synthetic CP10 load",
                    "accounts": [
                        {
                            "label": f"Evidence QA {i}",
                            "starting_cash": "100",
                            "strategy": "breakout-v1",
                            "execution_profile": "paper-rest-ioc-v1",
                            "operating_daily_usd": "0",
                        }
                        for i in range(14)
                    ],
                }
            )

            def setup(engine, spec=spec, count=count):
                engine.universe_experiment(["BTCUSD", "ETHUSD"])
                members = create_campaign(engine, spec)["campaign"]["accounts"]
                if count < 20:
                    engine.state["accounts"] = {
                        n: engine.state["accounts"][n] for n in members[:count]
                    }
                assert len(engine.state["accounts"]) == count

            at = time.time()
            store.transact(at, setup)
            recorder = EvidenceRecorder(Path(folder) / "research-evidence.sqlite")
            measured, dispatch_lag = [], []
            usage_before = store.storage_usage()
            rss_before = rss_bytes()
            cpu_before = time.process_time()
            started = time.perf_counter()
            for i in range(CONTRACT["ticks_per_case"]):
                target = started + i / CONTRACT["ticks_per_second"]
                time.sleep(max(0, target - time.perf_counter()))
                dispatch_lag.append(max(0, time.perf_counter() - target) * 1000)
                measured.append(recorded_tick(store, recorder, at + i / 4, i + 1))
            elapsed = time.perf_counter() - started
            archive = recorder.snapshot()
            result = {
                "accounts": count,
                "actual_accounts": len(store.read()["accounts"]),
                "elapsed_seconds": elapsed,
                "completed_ticks": len(measured),
                "scope": "Synthetic scheduled ticks; CPU includes matched engine validation",
                "stage_ms": {k: percentiles([row[k] for row in measured]) for k in measured[0]},
                "dispatcher_lag_ms": percentiles(dispatch_lag),
                "cpu_percent_one_core": (time.process_time() - cpu_before) / elapsed * 100,
                "rss_before_mib": rss_before / 1024**2,
                "rss_after_mib": rss_bytes() / 1024**2,
                "archive": archive,
                "postgres_before": usage_before,
                "postgres_after": store.storage_usage(),
                "matched_financial_state_and_events": True,
                "journal_balanced": store.reconcile()["balanced"],
            }
            result["passed"] = (
                result["stage_ms"]["transaction"]["p95"] <= 250
                and result["stage_ms"]["total_before_validation"]["p95"] <= 100
                and result["rss_after_mib"] <= 512
                and result["rss_after_mib"] - result["rss_before_mib"] <= 64
                and archive["physical_bytes"] <= CONTRACT["archive_budget_bytes"]
                and archive["queue_dropped"] == 0
                and archive["dropped"] == 0
                and result["journal_balanced"]
                and result["actual_accounts"] == count
            )
            recorder._archive.close()
            receipt["cases"].append(result)
            output.write_text(json.dumps(receipt, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "accounts": count,
                        "passed": result["passed"],
                        "commit_ms": result["stage_ms"]["transaction"],
                        "loop_ms": result["stage_ms"]["total_before_validation"],
                    }
                ),
                flush=True,
            )
    if not all(case["passed"] for case in receipt["cases"]):
        raise SystemExit("Original finite workload receipt retained: at least one criterion failed")


def seed_memory(recorder, now):
    """Adversarial UI fixture only: simulated chronology, mixed later market paths."""
    if recorder._archive is None:
        recorder._archive = EvidenceArchive(recorder.path)
    steps = [
        (0, "0"),
        (2701, "1"),
        (3600, "-.5"),
        (6301, "-3"),
        (7200, "0"),
        (9901, "2"),
        (10800, "0"),
    ]
    for offset, shift in steps:
        at = now - 4 * 3600 + offset
        books, bars = frames(at, 100 + offset), bars_at(at, shift)
        for book in books.values():
            book["source"] = "cp10-synthetic-clock-fixture"
        study = {s: {v: features(bars, at, v) for v in VARIANTS} for s in books}
        packet = recorder.prepare(
            at,
            books,
            study,
            dict.fromkeys(books, bars),
            dict.fromkeys(books, at),
            0,
            {},
            {},
            [],
            {},
            {},
        )
        packet.update(
            scope="Synthetic fixture on a simulated clock; no live outcome or ledger action",
            coverage="Declared mixed-result fixture; not a representative market sample",
            events=[],
            financial_commit=None,
        )
        simulated = SimpleNamespace(
            time=lambda at=at: at + 0.01, monotonic=time.monotonic, perf_counter=time.perf_counter
        )
        with patch("trading.research_evidence.time", simulated):
            recorder._archive.append([packet])
    recorder.status = recorder._archive.snapshot()


def serve(port, *, replay=False):
    verify_database()
    with tempfile.TemporaryDirectory(prefix="cp10-ui-") as folder:
        data = Path(folder)
        app = create_app(
            Settings(),
            data / "monitor.sqlite",
            ROOT / "apps/web/dist",
            background=False,
            research_evidence=data / "empty-qualification",
        )
        original = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(app):
            with disposable() as store:
                async with original(app):
                    runtime = TieredPaperRuntime(store, None, data / "stream.sqlite")
                    runtime.running = True
                    runtime.ready_at = 0
                    runtime.evidence = EvidenceRecorder(data / "research-evidence.sqlite")
                    now = time.time()
                    store.transact(
                        now, lambda engine: engine.universe_experiment(["BTCUSD", "ETHUSD"])
                    )
                    await asyncio.to_thread(seed_memory, runtime.evidence, now)
                    await asyncio.to_thread(recorded_tick, store, runtime.evidence, now, 1)
                    runtime.state = store.read()
                    runtime.books = frames(now, 1)
                    runtime.receipts = store.reconcile()
                    app.state.paper = runtime

                    async def feed():
                        sequence = 2
                        while True:
                            await asyncio.sleep(1)
                            at = time.time()
                            work = asyncio.create_task(
                                asyncio.to_thread(
                                    recorded_tick, store, runtime.evidence, at, sequence
                                )
                            )
                            try:
                                await asyncio.shield(work)
                            except asyncio.CancelledError:
                                await work
                                raise
                            runtime.state = store.read()
                            runtime.books = frames(at, sequence)
                            runtime.receipts = store.reconcile()
                            sequence += 1

                    worker = asyncio.create_task(feed())
                    replay_worker = asyncio.create_task(app.state.replay.run()) if replay else None
                    print(
                        json.dumps({"qa_only": True, "port": port, "evidence_path": str(data)}),
                        flush=True,
                    )
                    try:
                        yield
                    finally:
                        if replay_worker:
                            replay_worker.cancel()
                            try:
                                await replay_worker
                            except asyncio.CancelledError:
                                pass
                        worker.cancel()
                        try:
                            await worker
                        except asyncio.CancelledError:
                            pass
                        runtime.evidence._archive.close()

        app.router.lifespan_context = lifespan
        uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")).run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["benchmark", "serve"])
    parser.add_argument("--output", type=Path, default=ROOT / "data/cp10-benchmark.json")
    parser.add_argument("--port", type=int, default=8793)
    args = parser.parse_args()
    benchmark(args.output) if args.mode == "benchmark" else serve(args.port)
