"""Finite synthetic capacity/soak measurements in generated disposable PostgreSQL schemas."""

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import platform
import queue
import subprocess
import sys
import sysconfig
import threading
import time
import uuid
from pathlib import Path

import httpx
from lab_fixtures import synthetic_rows
from verify_cp3 import disposable, features, frames, rss_bytes, summary

from trading.numerical_candidates import evaluate_families
from trading.numerical_resources import constrain_child, own_limits
from trading.paper_campaigns import CampaignSpec, create_campaign
from trading.paper_runtime import PaperRuntime
from trading.venue import PublicVenue

ROOT = Path(__file__).resolve().parents[1]
SLOS = {
    "commit_p95_ms": 100,
    "commit_p99_ms": 250,
    "commit_max_ms": 2000,
    "queue_lag_p99_ms": 250,
    "queue_peak": 2,
    "parent_rss_mib": 512,
    "parent_rss_growth_mib": 64,
    "child_rss_mib": 256,
    "parent_cpu_one_core_percent": 50,
    "journal_balanced": True,
}


def host_times():
    if os.name != "nt":
        return None
    values = [ctypes.c_ulonglong() for _ in range(3)]
    if not ctypes.windll.kernel32.GetSystemTimes(*(ctypes.byref(x) for x in values)):
        raise OSError("Cannot measure host CPU")
    return [x.value for x in values]


def busy_worker(seconds, output):
    # Repeated synthetic fits measure capacity; they are not new research attempts
    # or independence claims. No financial connection, signing key or LLM is passed.
    constrain_child(os.getpid())
    rows = synthetic_rows()
    began, cpu = time.monotonic(), time.process_time()
    fits, peak = 0, rss_bytes()
    while time.monotonic() - began < seconds:
        evaluate_families(rows, rows[850]["at"], rows[-1]["at"], rows[-1]["at"])
        fits += 3
        peak = max(peak, rss_bytes())
    output.write_text(
        json.dumps(
            {
                "fits": fits,
                "cpu_seconds": time.process_time() - cpu,
                "wall_seconds": time.monotonic() - began,
                "peak_rss_mib": peak / 1024**2,
                "paid_usd": "0",
                "worker_identity": own_limits(),
            }
        )
    )


def setup(engine, count):
    engine.universe_experiment(["BTCUSD", "ETHUSD"])
    configs = [
        {
            "label": f"Synthetic load {i + 1}",
            "starting_cash": "100",
            "strategy": ["breakout-v1", "responsive-v1", "selective-v1"][i % 3],
            "execution_profile": "paper-rest-ioc-v1",
            "operating_daily_usd": "0",
        }
        for i in range(14 if count == 20 else 10)
    ]
    spec = CampaignSpec.model_validate(
        {
            "request_id": "qa-load-" + uuid.uuid4().hex,
            "name": "Synthetic capacity",
            "accounts": configs,
        }
    )
    members = create_campaign(engine, spec)["campaign"]["accounts"]
    if count != 20:
        # Only the disposable load projection is limited; no operating history is touched.
        names = ["primary", *members[: count - 1]]
        engine.state["accounts"] = {n: engine.state["accounts"][n] for n in names}


def benchmark(output, soak=False):
    seconds = 300 if soak else 30
    contract = {
        "seconds_per_case": seconds,
        "ticks_per_second": 4,
        "accounts": [20] if soak else [1, 10, 20],
        "research": ["busy"] if soak else ["idle", "busy"],
        "slos": SLOS,
        "input": "Shared synthetic executable BTC/ETH books; accelerated signals",
        "cpu_scope": "Parent and fixed fit child separately; host includes all other work",
        "gpu": "No GPU calls; numerical path is CPU-only",
        "authority": "Synthetic QA only; paid $0; no market/24x7 inference",
    }
    receipt = {
        "contract": contract,
        "declared_at": time.time(),
        "host": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "logical_processors": os.cpu_count(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
        ),
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                ROOT / "scripts/verify_cp3.py",
                ROOT / "scripts/lab_fixtures.py",
                *sorted((ROOT / "src/trading").glob("*.py")),
            ]
        },
        "cases": [],
    }
    # Persist predeclaration before observing any case.
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    for count in contract["accounts"]:
        for research in contract["research"]:
            with disposable() as store:
                store.transact(time.time(), lambda e, count=count: setup(e, count))
                # The actual account/economics status projection, with network disabled.
                venue = PublicVenue(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
                runtime = PaperRuntime(store, venue)
                runtime.running = True
                before = store.storage_usage()
                ticks = seconds * 4
                q = queue.Queue(maxsize=1024)
                commits, decisions, lags, memory, reads = [], [], [], [], []
                queue_peak = 0
                child = None
                child_path = ROOT / "data" / ("busy_" + uuid.uuid4().hex + ".json")
                if research == "busy":
                    env = {
                        k: v
                        for k, v in os.environ.items()
                        if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}
                    }
                    env["PYTHONPATH"] = os.pathsep.join(
                        [str(ROOT / "src"), sysconfig.get_paths()["purelib"]]
                    )
                    env["PYTHONNOUSERSITE"] = "1"
                    flags = (
                        subprocess.CREATE_NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS
                        if os.name == "nt"
                        else 0
                    )
                    child = subprocess.Popen(
                        [
                            str(Path(getattr(sys, "_base_executable", sys.executable)).resolve()),
                            __file__,
                            "worker",
                            "--seconds",
                            str(seconds),
                            "--output",
                            str(child_path),
                        ],
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=flags,
                    )
                began, cpu, host_before = time.perf_counter(), time.process_time(), host_times()

                def produce(began=began, q=q, ticks=ticks):
                    for i in range(ticks):
                        time.sleep(max(0, began + i / 4 - time.perf_counter()))
                        now = time.time()
                        q.put((time.perf_counter(), now, i + 1, frames(now, i + 1)))

                producer = threading.Thread(target=produce, daemon=True)
                producer.start()
                try:
                    for i in range(ticks):
                        queue_peak = max(queue_peak, q.qsize())
                        queued, now, seq, books = q.get(timeout=10)
                        lags.append((time.perf_counter() - queued) * 1000)

                        def tick(e, books=books, seq=seq, decisions=decisions):
                            started = time.perf_counter()
                            e.tick(books, features(seq // 20, True))
                            decisions.append((time.perf_counter() - started) * 1000)

                        started = time.perf_counter()
                        store.transact(now, tick)
                        commits.append((time.perf_counter() - started) * 1000)
                        memory.append(rss_bytes() / 1024**2)
                        if i % 20 == 0:
                            started = time.perf_counter()
                            runtime.state = store.read()
                            json.dumps(runtime.snapshot())
                            reads.append((time.perf_counter() - started) * 1000)
                finally:
                    producer.join(timeout=10)
                    if child:
                        try:
                            child.wait(timeout=max(1, seconds + 5 - (time.perf_counter() - began)))
                        except subprocess.TimeoutExpired:
                            child.terminate()
                            child.wait(timeout=3)
                    asyncio.run(venue.close())
                elapsed = time.perf_counter() - began
                host_after = host_times()
                child_receipt = json.loads(child_path.read_text()) if child_path.exists() else None
                after = store.storage_usage()
                case = {
                    "accounts": count,
                    "research": research,
                    "ticks": ticks,
                    "elapsed_seconds": elapsed,
                    "parent_cpu_seconds": time.process_time() - cpu,
                    "parent_cpu_one_core_percent": (time.process_time() - cpu) / elapsed * 100,
                    "parent_rss_mib": summary(memory),
                    "parent_rss_growth_mib": memory[-1] - memory[0],
                    "commit_ms": summary(commits),
                    "decision_ms": summary(decisions),
                    "queue_lag_ms": summary(lags),
                    "queue_peak": queue_peak,
                    "ui_state_read_ms": summary(reads),
                    "ui_read_scope": (
                        "PostgreSQL state read plus actual PaperRuntime account/economics status "
                        "and JSON serialization; no network/paint timing"
                    ),
                    "child": child_receipt,
                    "child_supervised_pid": child.pid if child else None,
                    "storage_growth_bytes": {k: after[k] - v for k, v in before.items()},
                    "reconciliation": store.reconcile(),
                    "host_cpu_percent": None,
                    "paper_connections": 2,
                    "market_connections": 0,
                    "paid_usd": "0",
                }
                if host_before and host_after:
                    idle, kernel, user = [
                        b - a for a, b in zip(host_before, host_after, strict=True)
                    ]
                    case["host_cpu_percent"] = (kernel + user - idle) / (kernel + user) * 100
                case["passed"] = (
                    case["reconciliation"]["balanced"]
                    and case["commit_ms"]["p95"] <= SLOS["commit_p95_ms"]
                    and case["commit_ms"]["p99"] <= SLOS["commit_p99_ms"]
                    and case["commit_ms"]["max"] <= SLOS["commit_max_ms"]
                    and case["queue_lag_ms"]["p99"] <= SLOS["queue_lag_p99_ms"]
                    and queue_peak <= SLOS["queue_peak"]
                    and max(memory) <= SLOS["parent_rss_mib"]
                    and case["parent_rss_growth_mib"] <= SLOS["parent_rss_growth_mib"]
                    and case["parent_cpu_one_core_percent"] <= SLOS["parent_cpu_one_core_percent"]
                    and (
                        research == "idle"
                        or bool(
                            child_receipt
                            and child_receipt["peak_rss_mib"] <= SLOS["child_rss_mib"]
                            and child_receipt["worker_identity"]["pid"] == child.pid
                            and child_receipt["worker_identity"]["processors_allowed"] is not None
                            and 1 <= child_receipt["worker_identity"]["processors_allowed"] <= 2
                            and (
                                os.name != "nt"
                                or child_receipt["worker_identity"]["priority_class"] == 0x40
                            )
                        )
                    )
                )
                receipt["cases"].append(case)
                output.write_text(json.dumps(receipt, indent=2) + "\n")
                print(
                    json.dumps(
                        {
                            "accounts": count,
                            "research": research,
                            "passed": case["passed"],
                            "commit_p95_ms": case["commit_ms"]["p95"],
                        }
                    ),
                    flush=True,
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["benchmark", "soak", "worker"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=30)
    args = parser.parse_args()
    if args.mode == "worker":
        busy_worker(args.seconds, args.output)
    else:
        benchmark(args.output, args.mode == "soak")
