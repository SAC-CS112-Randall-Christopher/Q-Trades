"""Finite CP17 measurement on an owned disposable database; no operating writes."""

import argparse
import hashlib
import json
import platform
import subprocess
import threading
import time
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from verify_cp3 import disposable, features, frames, rss_bytes
from verify_evidence import bars_at, percentiles
from verify_lab import setup

from trading.paper_store import load_dsn
from trading.research_storage import StoragePlan, volume
from trading.scoped_tools import run
from trading.tiered_runtime import TieredPaperRuntime
from trading.tool_journal import ToolJournal, encoded

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = {
    "fixture": "Synthetic twenty-account financial ticks and 1103 permanent outcome events",
    "seconds_per_case": 30,
    "ticks_per_second": 4,
    "cases": ["idle", "scoped_reads"],
    "loop_p95_limit_ms": 100,
    "rss_limit_mib": 512,
    "rss_growth_limit_mib": 64,
    "scope": "Disposable software evidence; no live-market, model or economic claim",
}


def verify(output=None, qa_cluster=None):
    dsn = load_dsn(ROOT / "data/paper-database.json")
    info = conninfo_to_dict(dsn)
    if info.get("host") != "127.0.0.1" or info.get("port") != "55641":
        raise ValueError("Requires owned QA PostgreSQL on 55641")
    with psycopg.connect(dsn) as admin:
        directory = Path(admin.execute("SHOW data_directory").fetchone()[0]).resolve()
        if directory != (qa_cluster or ROOT / "data/qa-pg").resolve():
            raise ValueError("Disposable database ownership differs")
    output = output or ROOT / "data/cp17-native.json"
    receipt = {
        "contract": CONTRACT,
        "declared_at": time.time(),
        "cases": [],
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__), *sorted((ROOT / "src/trading").glob("*.py"))]
        },
        "platform": platform.platform(),
        "python": platform.python_version(),
        "tier_bytes": 100_000_000_000,
        "limits": "Finite small actual bytes, not full 100-GB throughput",
    }
    output.write_text(json.dumps(receipt, indent=2))
    for mode in CONTRACT["cases"]:
        with disposable() as store:

            def seed(engine):
                setup(engine, 20)
                for _ in range(1103):
                    engine.emit(
                        "trade_closed",
                        "primary",
                        {
                            "symbol": "BTCUSD",
                            "pnl": "-0.13",
                            "fees": "0.10",
                            "opened_at": time.time(),
                            "reason": "Synthetic read-model receipt",
                        },
                    )

            store.transact(time.time(), seed)
            runtime = TieredPaperRuntime(store, None, ROOT / "data/cp17-bench-capture.sqlite3")
            runtime.running = True
            runtime.history["BTCUSD"] = bars_at(time.time())
            runtime.stream.plan = {"BTCUSD": 100}
            runtime.universe.selected = ["BTCUSD"]
            runtime.instruments["BTCUSD"] = {
                "base": "BTC",
                "quote": "USD",
                "venue_status": "TRADING",
                "spot_allowed": True,
                "minimum_notional": "1",
                "filters": [
                    {
                        "filterType": "PRICE_FILTER",
                        "tickSize": "0.01",
                        "minPrice": "0.01",
                        "maxPrice": "1000000",
                    },
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": "0.00001",
                        "minQty": "0.00001",
                        "maxQty": "100",
                        "minimum_notional": "1",
                    },
                ],
            }

            def observed_frames(now, sequence):
                return {
                    key: dict(value, received_mono=time.monotonic())
                    for key, value in frames(now, sequence).items()
                }

            runtime._fallback = observed_frames(time.time(), 1)
            research = Path("G:/Projects") / ("Q-Trades-Data-qa-cp17-bench-" + uuid.uuid4().hex)
            plan = StoragePlan(
                root=str(research),
                volume_identity=volume(research)["identity"],
            )
            journal = ToolJournal(ROOT / "data" / ("cp17-bench-" + mode + ".sqlite3"), plan)
            stop, errors = threading.Event(), []
            query, serialization, sizes = [], [], []
            overview_sizes = []

            def reads(
                stop=stop,
                runtime=runtime,
                query=query,
                sizes=sizes,
                serialization=serialization,
                journal=journal,
                errors=errors,
                overview_sizes=overview_sizes,
            ):
                tools = ["market_evidence", "cost_hurdle", "strategy_evidence", "outcome_review"]
                i = 0
                while not stop.is_set():
                    try:
                        result = run(runtime, tools[i % 4], "BTCUSD", "primary", f"native-read-{i}")
                        query.append(result["envelope"]["query_seconds"] * 1000)
                        began = time.perf_counter()
                        sizes.append(len(encoded(result).encode()))
                        serialization.append((time.perf_counter() - began) * 1000)
                        run_id = journal.start(tools[i % 4], "BTCUSD")
                        journal.finish(run_id, result, None)
                        assert journal.get(run_id)["status"] == "completed"
                        overview_sizes.append(len(encoded(journal.get(run_id)["result"]).encode()))
                        i += 1
                    except Exception as exc:
                        errors.append(type(exc).__name__ + ": " + str(exc))
                        return
                    stop.wait(0.25)

            worker = threading.Thread(target=reads)
            if mode == "scoped_reads":
                worker.start()
            commits, memory = [], []
            began = time.perf_counter()
            try:
                for i in range(120):
                    time.sleep(max(0, began + i / 4 - time.perf_counter()))
                    now = time.time()
                    runtime._fallback = observed_frames(now, i + 2)
                    runtime.metadata_at = now
                    started = time.perf_counter()
                    store.transact(
                        now,
                        lambda e, i=i, now=now: e.tick(frames(now, i + 2), features(i // 20, True)),
                    )
                    commits.append((time.perf_counter() - started) * 1000)
                    memory.append(rss_bytes() / 1024**2)
                stop.set()
                if worker.is_alive():
                    worker.join(timeout=5)
                assert not worker.is_alive() and not errors, errors
                case = {
                    "mode": mode,
                    "accounts": len(store.read()["accounts"]),
                    "ticks": 120,
                    "financial_transaction_ms": percentiles(commits),
                    "query_ms": percentiles(query),
                    "serialization_ms": percentiles(serialization),
                    "result_utf8_bytes": percentiles(sizes),
                    "overview_utf8_bytes": percentiles(overview_sizes),
                    "reads": len(query),
                    "peak_rss_mib": max(memory),
                    "rss_growth_mib": max(memory) - memory[0],
                    "balanced": store.reconcile()["balanced"],
                    "errors": errors,
                }
                assert case["accounts"] == 20 and case["balanced"]
                assert case["financial_transaction_ms"]["p95"] < 100
                assert max(memory) < 512 and case["rss_growth_mib"] < 64
                receipt["cases"].append(case)
                output.write_text(json.dumps(receipt, indent=2))
            finally:
                stop.set()
                if worker.is_alive():
                    worker.join(timeout=5)
                journal.close()
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--qa-cluster", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.output, args.qa_cluster)))
