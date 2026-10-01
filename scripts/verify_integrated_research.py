"""Finite CP16 actual-host synthetic capture and bounded research-load measurements."""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sysconfig
import tempfile
import threading
import time
import uuid
from pathlib import Path

from memory_fixtures import memory_fixture
from verify_cp3 import disposable, rss_bytes
from verify_evidence import percentiles, recorded_tick, serve, verify_database

from trading.context_flow import evaluate_context
from trading.evidence_runtime import EvidenceRecorder
from trading.numerical_resources import constrain_child, own_limits
from trading.paper_campaigns import CampaignSpec, create_campaign
from trading.research_storage import StoragePlan, save_plan, volume

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = {
    "accounts": [1, 10, 20],
    "research": [False, True],
    "seconds_per_case": 30,
    "ticks_per_second": 4,
    "commit_p95_ms": 100,
    "commit_p99_ms": 250,
    "loop_p95_ms": 100,
    "dispatch_p99_ms": 250,
    "rss_mib": 512,
    "growth_mib": 64,
    "parent_cpu_one_core_percent": 50,
    "child_rss_mib": 256,
    "scope": "Full replay bundle plus compact memory; synthetic books, not network/GIS latency",
    "authority": "Disposable schemas only; no provider/GPU or original-account mutation",
}


def worker(seconds, output):
    constrain_child(os.getpid())
    plan, rows = memory_fixture()
    plan = plan.model_copy(update={"experiment_mode": "context_regime"})
    began, cpu, peak, fits = time.perf_counter(), time.process_time(), rss_bytes(), 0
    while time.perf_counter() - began < seconds:
        evaluate_context(rows, [], plan)
        fits += 1
        peak = max(peak, rss_bytes())
    output.write_text(
        json.dumps(
            {
                "wall_seconds": time.perf_counter() - began,
                "cpu_seconds": time.process_time() - cpu,
                "peak_rss_mib": peak / 1024**2,
                "fits": fits,
                "limits": own_limits(),
                "paid_usd": "0",
            }
        ),
        encoding="utf-8",
    )


def benchmark(output, research_root=None, async_capture=False):
    verify_database()
    receipt = {
        "contract": CONTRACT,
        "declared_at": time.time(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": [],
        "asynchronous_capture": async_capture,
    }
    output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    for count in CONTRACT["accounts"]:
        for busy in CONTRACT["research"]:
            with (
                tempfile.TemporaryDirectory(prefix="cp16-finite-") as folder,
                disposable() as store,
            ):
                path = Path(folder)
                if research_root is not None:
                    owned = research_root / ("Q-Trades-Data-qa-" + uuid.uuid4().hex)
                    save_plan(
                        path,
                        StoragePlan(
                            root=str(owned),
                            volume_identity=volume(owned)["identity"],
                            temporary_bytes=512 * 1024**2,
                            research_bytes=512 * 1024**2,
                            scratch_bytes=64 * 1024**2,
                        ),
                    )

                def setup(engine, count=count):
                    engine.universe_experiment(["BTCUSD", "ETHUSD"])
                    create_campaign(
                        engine,
                        CampaignSpec.model_validate(
                            {
                                "request_id": "integrated-native-20",
                                "name": "Synthetic finite load",
                                "accounts": [
                                    {
                                        "label": f"QA {i}",
                                        "starting_cash": "100",
                                        "strategy": "breakout-v1",
                                        "execution_profile": "paper-rest-ioc-v1",
                                        "operating_daily_usd": "0",
                                    }
                                    for i in range(14)
                                ],
                            }
                        ),
                    )
                    if count < 20:
                        engine.state["accounts"] = dict(
                            list(engine.state["accounts"].items())[:count]
                        )

                store.transact(time.time(), setup)
                recorder = EvidenceRecorder(path / "research-evidence.sqlite")
                if research_root is not None:
                    recorder._write_batch([], [], True)
                    archive = recorder._storage
                    assert archive is not None
                    payload = "".join(
                        hashlib.sha256(str(i).encode()).hexdigest() for i in range(2048)
                    )
                    for batch in range(65):
                        archive.append(
                            [
                                {
                                    "at": time.time() - 86400 + batch * 8 + i,
                                    "kind": "synthetic_history",
                                    "sample": payload,
                                    "nonce": batch * 8 + i,
                                }
                                for i in range(8)
                            ],
                            time.time(),
                        )
                    maintenance_started = time.perf_counter()
                    while archive.db.execute(
                        "SELECT count(*) FROM storage_segments WHERE state IN ('active','sealed')"
                    ).fetchone()[0]:
                        archive.housekeeping(time.time(), capacity_triggered=True)
                    archived_history = archive.snapshot()
                    archived_history["preload_maintenance_wall_seconds"] = (
                        time.perf_counter() - maintenance_started
                    )
                child = None
                if busy:
                    native_python = Path(sysconfig.get_path("scripts")) / "python.exe"
                    child = subprocess.Popen(
                        [
                            str(native_python),
                            str(Path(__file__).resolve()),
                            "worker",
                            "--seconds",
                            "32",
                            "--output",
                            str(path / "worker.json"),
                        ],
                        cwd=ROOT,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                rows, lags = [], []
                capture_stop = threading.Event()
                capture_errors = []
                capture_times = []
                capture_thread = None
                if async_capture:

                    def capture_worker(
                        recorder=recorder,
                        capture_stop=capture_stop,
                        capture_errors=capture_errors,
                        capture_times=capture_times,
                    ):
                        try:
                            while (
                                not capture_stop.is_set()
                                or recorder.pending
                                or recorder.compact_pending
                            ):
                                began = time.perf_counter()
                                asyncio.run(recorder.flush())
                                capture_times.append((time.perf_counter() - began) * 1000)
                                capture_stop.wait(
                                    0 if recorder.pending or recorder.compact_pending else 0.25
                                )
                        except Exception as exc:
                            capture_errors.append(str(exc))

                    capture_thread = threading.Thread(target=capture_worker, daemon=True)
                    capture_thread.start()
                peak_queue = 0
                started, cpu, rss = time.perf_counter(), time.process_time(), rss_bytes()
                try:
                    for i in range(120):
                        target = started + i / 4
                        time.sleep(max(0, target - time.perf_counter()))
                        lags.append(max(0, time.perf_counter() - target) * 1000)
                        rows.append(
                            recorded_tick(
                                store,
                                recorder,
                                time.time(),
                                i + 1,
                                compact=True,
                                flush=not async_capture,
                            )
                        )
                        peak_queue = max(
                            peak_queue, len(recorder.pending), len(recorder.compact_pending)
                        )
                    elapsed = time.perf_counter() - started
                    drain_started = time.perf_counter()
                    if capture_thread:
                        capture_stop.set()
                        capture_thread.join(timeout=30)
                    result = {
                        "accounts": len(store.read()["accounts"]),
                        "research_busy": busy,
                        "ticks": len(rows),
                        "wall_seconds": elapsed,
                        "stage_ms": {k: percentiles([r[k] for r in rows]) for k in rows[0]},
                        "dispatch_lag_ms": percentiles(lags),
                        "rss_mib": rss_bytes() / 1024**2,
                        "rss_growth_mib": (rss_bytes() - rss) / 1024**2,
                        "parent_cpu_one_core_percent": (time.process_time() - cpu) / elapsed * 100,
                        "raw_archive": recorder.snapshot(),
                        "compact": recorder._compact.snapshot(),
                        "compact_bytes": sum(
                            p.stat().st_size
                            for p in recorder._compact.path.parent.glob(
                                recorder._compact.path.name + "*"
                            )
                        ),
                        "postgres": store.storage_usage(),
                        "balanced": store.reconcile()["balanced"],
                        "queue_peak": peak_queue,
                        "capture_errors": capture_errors,
                        "capture_batch_ms": percentiles(capture_times) if capture_times else None,
                        "capture_drain_seconds": time.perf_counter() - drain_started,
                        "capture_drained": not capture_thread or not capture_thread.is_alive(),
                    }
                    if research_root is not None:
                        result["preexisting_synthetic_history"] = archived_history
                    if child:
                        out, err = child.communicate(timeout=12)
                        assert child.returncode == 0, err.decode(errors="replace")
                        result["child"] = json.loads(
                            (path / "worker.json").read_text(encoding="utf-8")
                        )
                    stages = result["stage_ms"]
                    result["passed"] = (
                        result["accounts"] == count
                        and result["balanced"]
                        and stages["transaction"]["p95"] <= CONTRACT["commit_p95_ms"]
                        and stages["transaction"]["p99"] <= CONTRACT["commit_p99_ms"]
                        and stages["total_before_validation"]["p95"] <= CONTRACT["loop_p95_ms"]
                        and result["dispatch_lag_ms"]["p99"] <= CONTRACT["dispatch_p99_ms"]
                        and result["rss_mib"] <= CONTRACT["rss_mib"]
                        and result["rss_growth_mib"] <= CONTRACT["growth_mib"]
                        and result["queue_peak"] <= 8
                        and not result["capture_errors"]
                        and result["capture_drained"]
                        and recorder.dropped == 0
                        and recorder.compact_dropped == 0
                        and result["parent_cpu_one_core_percent"]
                        <= CONTRACT["parent_cpu_one_core_percent"]
                        and (
                            not child
                            or result["child"]["peak_rss_mib"] <= CONTRACT["child_rss_mib"]
                        )
                    )
                    receipt["cases"].append(result)
                    output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
                    print(
                        json.dumps(
                            {
                                "accounts": count,
                                "busy": busy,
                                "passed": result["passed"],
                                "loop_ms": stages["total_before_validation"],
                                "compact_bytes": result["compact_bytes"],
                            }
                        ),
                        flush=True,
                    )
                finally:
                    capture_stop.set()
                    if capture_thread:
                        capture_thread.join(timeout=30)
                    if child and child.poll() is None:
                        child.terminate()
                        child.wait(timeout=10)
                    if recorder._archive:
                        recorder._archive.close()
                    if recorder._compact:
                        recorder._compact.close()
                    if recorder._storage:
                        recorder._storage.close()
                    if recorder._maturity:
                        recorder._maturity.close()
                    if research_root is not None:
                        resolved = owned.resolve()
                        assert (
                            resolved.parent == research_root.resolve()
                            and resolved.name.startswith("Q-Trades-Data-qa-")
                        )
                        assert (resolved / "owned.json").is_file()
                        __import__("shutil").rmtree(resolved)
    assert all(c["passed"] for c in receipt["cases"]), "Retain failed finite receipt"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["benchmark", "worker", "serve"])
    parser.add_argument("--output", type=Path, default=ROOT / "data/cp16-native.json")
    parser.add_argument("--seconds", type=int, default=32)
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--research-root", type=Path)
    parser.add_argument("--async-capture", action="store_true")
    args = parser.parse_args()
    if args.mode == "worker":
        worker(args.seconds, args.output)
    elif args.mode == "serve":
        serve(args.port, research=True, compact=True)
    else:
        benchmark(args.output, args.research_root, args.async_capture)
