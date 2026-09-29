"""Repeatable CP3 browser fixture / bounded load check, always in disposable schemas."""

import argparse
import asyncio
import contextlib
import ctypes
import json
import os
import platform
import queue
import statistics
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import psycopg
import uvicorn
from fastapi import Request
from fastapi.responses import HTMLResponse
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from trading.api import create_app
from trading.config import Settings
from trading.market import parse_book
from trading.paper_campaigns import CampaignSpec, create_campaign
from trading.paper_store import PaperStore, load_dsn
from trading.paper_strategy import VARIANTS
from trading.tiered_runtime import TieredPaperRuntime

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def disposable():
    dsn = load_dsn(ROOT / "data/paper-database.json")
    schema = "cp3qa_" + uuid.uuid4().hex
    admin = psycopg.connect(dsn, autocommit=True)
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    store = PaperStore(make_conninfo(dsn, options=f"-c search_path={schema}"), owner=True)
    store.initialize(time.time())
    try:
        yield store
    finally:
        store.close()
        assert schema.startswith("cp3qa_") and len(schema) == 38
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


def frames(now, sequence, price="100"):
    result = {}
    for base in ("BTC", "ETH"):
        raw = {
            "lastUpdateId": sequence,
            "bids": [[price, "100"]],
            "asks": [[str(D(price) + D("0.02")), "100"]],
        }
        result[base + "USD"] = {
            "book": parse_book(raw),
            "raw": raw,
            "observed": now,
            "base": base,
            "source": "cp3-synthetic-qa",
            "instrument": {"symbol": base + "USD"},
            "rules": {
                "step": D("0.00001"),
                "tick": D("0.01"),
                "min_qty": D("0.00001"),
                "max_qty": D(100),
                "min_notional": D(1),
                "min_price": D("0.01"),
                "max_price": D(1_000_000),
            },
        }
    return result


def features(bar, eligible):
    return {
        s: {
            v: {
                "eligible": eligible,
                "bar_open_ms": bar,
                "atr": "1",
                "reason": "Synthetic QA observation",
                "version": v,
            }
            for v in VARIANTS
        }
        for s in ("BTCUSD", "ETHUSD")
    }


def serve(port, lab_qa=False, candidates_qa=False):
    app = create_app(
        Settings(),
        ROOT / "data/cp3-browser-monitor.sqlite3",
        ROOT / "apps/web/dist",
        background=False,
        research_evidence=ROOT / "data/cp3-empty-evidence",
    )
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        with disposable() as store:
            async with original(app):
                runtime = TieredPaperRuntime(store, None, ROOT / "data/cp3-qa-capture.sqlite3")
                runtime.instruments = {
                    base + "USD": {
                        "base": base,
                        "quote": "USD",
                        "venue_status": "TRADING",
                        "spot_allowed": True,
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "stepSize": "0.00001",
                                "minQty": "0.00001",
                                "maxQty": "100",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "tickSize": "0.01",
                                "minPrice": "0.01",
                                "maxPrice": "1000000",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "1"},
                        ],
                    }
                    for base in ("BTC", "ETH")
                }
                runtime.running = True
                app.state.paper = runtime
                lab_task = None
                if lab_qa:
                    from trading.experiment_registry import PREFLIGHT_END, ExperimentRegistry

                    # Only this fixture's generated schema receives these synthetic copies.
                    rows = json.loads(
                        (
                            ROOT / "docs/evidence/numeric-preflight-20260928T113855Z.quotes.json"
                        ).read_text()
                    )["rows"]
                    shift = int((time.time() - 3600 - PREFLIGHT_END) // 60) * 60
                    for row in rows:
                        row["at"] += shift
                        row["body"]["last_observed_at"] += shift
                        row["body"]["minute"] += shift // 60
                        row["body"]["synthetic_qa"] = True
                    if candidates_qa:
                        from lab_fixtures import synthetic_rows

                        rows = synthetic_rows(start=int(time.time() // 60) * 60 - 1200 * 60)
                    store.connection.cursor().executemany(
                        "INSERT INTO paper_events(revision,at,kind,account,body) "
                        "VALUES (1,%s,'market_minute','synthetic-qa',%s)",
                        [(r["at"], Jsonb(r["body"])) for r in rows],
                    )
                    lab = app.state.lab
                    lab.registry.close()
                    lab.registry = ExperimentRegistry(
                        ROOT / "data" / ("labqa_" + uuid.uuid4().hex + ".sqlite3")
                    )
                    from trading.experiment_worker import code_fingerprint
                    from trading.research_campaigns import ResearchCampaigns

                    lab.campaigns = ResearchCampaigns(lab.registry, lab.enqueue, code_fingerprint)
                    lab.dsn = store.connection.info.dsn
                    lab.can_research = lambda: runtime.running
                    original_result = json.loads(
                        (ROOT / "docs/evidence/numeric-preflight-20260928T113855Z.json").read_text()
                    )["result"]
                    print(
                        json.dumps(
                            {
                                "qa_test_start": rows[850]["at"]
                                if candidates_qa
                                else original_result["split_at"] + shift,
                                "qa_test_end": rows[-1]["at"]
                                if candidates_qa
                                else PREFLIGHT_END + shift,
                            }
                        ),
                        flush=True,
                    )
                    lab_task = asyncio.create_task(lab.run())

                async def feed():
                    seq = 0
                    while True:
                        if runtime.running:
                            now, seq = time.time(), seq + 1
                            runtime.books = frames(now, seq)
                            runtime.metadata_at = now
                            runtime._fallback = {
                                s: {**f, "received_mono": time.monotonic()}
                                for s, f in runtime.books.items()
                            }
                            runtime.state = store.transact(
                                now,
                                lambda e, seq=seq: (
                                    e.universe_experiment(["BTCUSD", "ETHUSD"]),
                                    e.tick(runtime.books, features(seq // 20, False)),
                                ),
                            )
                            runtime.recent = store.recent()
                            runtime.receipts = store.reconcile()
                        await asyncio.sleep(0.25)

                task = asyncio.create_task(feed())
                try:
                    yield
                finally:
                    if lab_task:
                        lab_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await lab_task
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    app.state.paper = None

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def fixture_label(request, call_next):
        if request.url.path == "/":
            html = (ROOT / "apps/web/dist/index.html").read_text()
            banner = (
                '<div style="padding:12px;background:#663d00;color:white">'
                "QA · SYNTHETIC OBSERVATIONS · DISPOSABLE DATABASE</div>"
            )
            return HTMLResponse(html.replace("<body>", "<body>" + banner))
        return await call_next(request)

    @app.post("/qa/scenario")
    def scenario(request: Request, body: dict[str, Any]):
        runtime = request.app.state.paper
        if body["action"] == "shutdown":
            server.should_exit = True
        elif body["action"] == "worker_unavailable":
            runtime.running = False
        elif body["action"] == "worker_available":
            runtime.running = True
        else:

            def apply(e):
                name = next(iter(e.state["campaigns"].values()))["accounts"][0]
                a = e.state["accounts"][name]
                if body["action"] == "fault":
                    a.update(
                        fault={
                            "at": e.now,
                            "code": "ValueError",
                            "reason": "Synthetic QA processing failure; retry recovery.",
                        },
                        valuation_fresh=False,
                        control_version=a["control_version"] + 1,
                    )
                    a.pop("last_control", None)
                    e.emit("account_fault", name, a["fault"])
                elif body["action"] == "hard_stop":
                    loss = D(a["cash"]) - D("30")
                    a.update(cash="30", realized=str(D(a["realized"]) - loss))
                    e.emit(
                        "qa_loss",
                        name,
                        {"reason": "Synthetic QA loss"},
                        [e.line("USD", "cash", -loss), e.line("USD", "realized_pnl", loss)],
                    )
                else:
                    raise ValueError("Unknown QA scenario")

            runtime.state = runtime.store.transact(time.time(), apply)
        return {"qa_only": True}

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    server.run()


def rss_bytes():
    if os.name != "nt":
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (k, ctypes.c_size_t)
            for k in (
                "peak_rss",
                "rss",
                "peak_pool",
                "pool",
                "peak_nonpool",
                "nonpool",
                "pagefile",
                "peak_pagefile",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess
    process.restype = ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
    ]
    if not ctypes.windll.psapi.GetProcessMemoryInfo(process(), ctypes.byref(counters), counters.cb):
        raise OSError("Process working-set measurement failed")
    return counters.rss


def summary(values):
    ordered = sorted(values)
    return {
        "mean": statistics.mean(values),
        "p95": ordered[int((len(values) - 1) * 0.95)],
        "p99": ordered[int((len(values) - 1) * 0.99)],
        "max": max(values),
    }


def benchmark(output):
    contract = {
        "accounts": [1, 10],
        "ticks_per_case": 120,
        "ticks_per_second": 4,
        "symbols": ["BTCUSD", "ETHUSD"],
        "commit_p95_limit_ms": 250,
        "commit_max_limit_ms": 2000,
        "rss_limit_mib": 512,
        "rss_growth_limit_mib": 64,
        "queue_peak_limit": 2,
    }
    receipt = {
        "contract": contract,
        "fixture": "Synthetic shared books; accelerated bar signals",
        "host": platform.node(),
        "platform": platform.platform(),
        "logical_processors": os.cpu_count(),
        "python": platform.python_version(),
        "observed_at": time.time(),
        "cases": [],
    }
    for count in contract["accounts"]:
        with disposable() as store:
            spec = CampaignSpec.model_validate(
                {
                    "request_id": "benchmark-" + uuid.uuid4().hex,
                    "name": "Synthetic load fixture",
                    "accounts": [
                        {
                            "label": f"QA {i + 1}",
                            "starting_cash": "100",
                            "strategy": "breakout-v1",
                            "execution_profile": "paper-rest-ioc-v1",
                            "operating_daily_usd": "0",
                        }
                        for i in range(10)
                    ],
                }
            )

            def setup(e, spec=spec, count=count):
                members = create_campaign(e, spec)["campaign"]["accounts"][:count]
                # Synthetic load projections contain exactly one or ten accounts.
                # Original and unused fixture funding rows remain in the QA journal.
                e.state["accounts"] = {n: e.state["accounts"][n] for n in members}

            store.transact(time.time(), setup)
            usage_before = store.storage_usage()
            state_bytes_before = len(json.dumps(store.read()).encode())
            q = queue.Queue(maxsize=1024)
            queue_peak, lags, commit_ms, decision_ms, memory = 0, [], [], [], []
            start, cpu_before = time.perf_counter(), time.process_time()

            def produce(start=start, q=q):
                for i in range(contract["ticks_per_case"]):
                    deadline = start + i / contract["ticks_per_second"]
                    time.sleep(max(0, deadline - time.perf_counter()))
                    stamp = time.time()
                    q.put((time.perf_counter(), stamp, i + 1, frames(stamp, i + 1)))

            producer = threading.Thread(target=produce)
            producer.start()
            try:
                for _ in range(contract["ticks_per_case"]):
                    queue_peak = max(queue_peak, q.qsize())
                    queued, now, seq, observations = q.get(timeout=10)
                    lags.append((time.perf_counter() - queued) * 1000)
                    times = []

                    def apply(e, observations=observations, seq=seq, times=times):
                        began = time.perf_counter()
                        e.tick(observations, features(seq // 20, True))
                        times.append((time.perf_counter() - began) * 1000)

                    began = time.perf_counter()
                    store.transact(now, apply)
                    commit_ms.append((time.perf_counter() - began) * 1000)
                    decision_ms.extend(times)
                    memory.append(rss_bytes() / 1024**2)
            finally:
                producer.join(timeout=10)
            elapsed = time.perf_counter() - start
            usage_after = store.storage_usage()
            result = {
                "accounts": count,
                "elapsed_seconds": elapsed,
                "cpu_seconds": time.process_time() - cpu_before,
                "process_cpu_one_core_percent": (time.process_time() - cpu_before) / elapsed * 100,
                "rss_mib": summary(memory),
                "rss_growth_mib": memory[-1] - memory[0],
                "decision_ms": summary(decision_ms),
                "transaction_commit_ms": summary(commit_ms),
                "queue_lag_ms": summary(lags),
                "queue_peak_observed": queue_peak,
                "postgres_connections": 2,
                "market_connections": 0,
                "shared_observations": 2 * contract["ticks_per_case"],
                "state_growth_bytes": len(json.dumps(store.read()).encode()) - state_bytes_before,
                "storage_growth": {k: usage_after[k] - v for k, v in usage_before.items()},
                "reconciliation": store.reconcile(),
            }
            result["passed"] = (
                result["reconciliation"]["balanced"]
                and result["transaction_commit_ms"]["p95"] <= contract["commit_p95_limit_ms"]
                and result["transaction_commit_ms"]["max"] <= contract["commit_max_limit_ms"]
                and result["rss_mib"]["max"] <= contract["rss_limit_mib"]
                and result["rss_growth_mib"] <= contract["rss_growth_limit_mib"]
                and queue_peak <= contract["queue_peak_limit"]
            )
            receipt["cases"].append(result)
            print(
                json.dumps(
                    {
                        "accounts": count,
                        "passed": result["passed"],
                        "commit_p95_ms": result["transaction_commit_ms"]["p95"],
                    }
                ),
                flush=True,
            )
    output.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["serve", "benchmark"])
    parser.add_argument("--port", type=int, default=8793)
    parser.add_argument("--lab", action="store_true")
    parser.add_argument("--candidates", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/reviews/cp3-paper-campaigns/benchmark.json"
    )
    args = parser.parse_args()
    if args.mode == "serve":
        serve(args.port, args.lab, args.candidates)
    else:
        benchmark(args.output)
