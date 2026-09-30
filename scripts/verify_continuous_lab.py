"""Predeclared native soak and browser harness; disposable synthetic state only."""

import argparse
import asyncio
import json
import math
import platform
import sys
import tempfile
import time
from contextlib import asynccontextmanager, suppress
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

import uvicorn
from fastapi import Request
from verify_cp3 import disposable, frames, rss_bytes
from verify_evidence import percentiles, verify_database

from trading import autonomous_finance as finance
from trading.api import create_app
from trading.autonomous_lab import AutonomousLab
from trading.config import Settings
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore
from trading.paper_strategy import VARIANTS, Bar, features
from trading.tiered_runtime import TieredPaperRuntime

ROOT = Path(__file__).resolve().parents[1]
REAL_TIME = time.time
CONTRACT = {
    "seconds": 60,
    "ticks_per_second": 4,
    "restart_at_seconds": 30,
    "peak_slots": 20,
    "loop_p95_ms": 100,
    "feature_p95_ms": 100,
    "rss_mib": 512,
    "growth_mib": 64,
    "queue": 4,
    "scope": "Synthetic software/controller continuity; no 24/7 or market-profit claim",
    "history": "36 scored trials plus 72 archived accounts; active projection remains bounded",
}


def stable_bars(at):
    end = int(at // 60) * 60000
    result = []
    for start in range(end - 400 * 60000, end, 60000):
        minute = start // 60000
        price = D("103.99") + D(str(round(math.sin(minute / 20) * 0.5, 5)))
        result.append(
            Bar(
                start,
                price,
                price + D(".03"),
                price - D(".03"),
                price,
                D(30) if minute % 6 == 0 else D(10),
                start + 59999,
            )
        )
    return result


def fixture_helpers():
    # Reuse the tested synthetic lifecycle fixture, never an operating database.
    sys.path.insert(0, str(ROOT / "tests"))
    from test_autonomous_lab import admit, close_window, make_lab, tick_lab

    return admit, close_window, make_lab, tick_lab


def soak(output):
    verify_database()
    admit, close_window, make_lab, tick_lab = fixture_helpers()
    receipt = {
        "contract": CONTRACT,
        "declared_at": REAL_TIME(),
        "platform": platform.platform(),
        "synthetic": True,
    }
    output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="continuous-native-") as folder, disposable() as store:
        # The fixture begins at the real present; accelerated outcomes advance an
        # explicit synthetic clock. The finite soak measures actual monotonic time.
        clock = {"offset": 0.0}
        now = REAL_TIME()
        with patch("time.time", lambda: REAL_TIME() + clock["offset"]):
            lab = make_lab(
                store,
                Path(folder),
                now=now,
                horizon_seconds=3600,
                family_slots=10,
                daily_trials=24,
                hourly_compute_seconds=60,
            )
            at = now
            for i in range(36):
                trial = admit(lab, at)
                close_window(lab, trial, "economically_unsuccessful" if i % 2 else "inconclusive")
                at = trial["review_at"] + 4
            clock["offset"] = at - REAL_TIME()
            # Fill all capacity with explicitly labelled, validated replications.
            from trading.autonomous_spec import LabProposal, RuleSpec

            prior = lab.inbox.get(lab.inbox.page()["proposals"][0]["request_id"])
            range_spec = RuleSpec.model_validate(prior["body"]["strategy"])
            for i in range(7):
                current = time.time()
                tick_lab(lab, current)
                issued = lab.bundle(current)
                spec = RuleSpec() if i < 5 else range_spec
                proposal = LabProposal(
                    request_id=f"native-replication-{i}",
                    policy_id="continuous-test-policy",
                    kind="replication",
                    source="external",
                    strategy=spec,
                    reference=spec,
                    replication_of="reviewed-breakout-v1" if i < 5 else prior["request_id"],
                    mechanism="Explicit correlated replication for bounded native workload",
                    question="Can concurrent execution retain history and native limits?",
                    evidence_bundle_sha256=issued["sha256"],
                )
                accepted = lab.submit(proposal, current)
                assert accepted["status"] == "evaluated", accepted["reason"]
                reservation = store.lab_reserve(current, proposal)
                store.transact(current, lambda e, t=reservation["trial_id"]: finance.fund(e, t))
                lab.inbox.update(proposal.request_id, "funded", reservation["trial_id"])
                lab.paper.state = store.read()
            rows, peaks, gaps, queue = [], [], [], []
            began, initial_rss = time.perf_counter(), rss_bytes()
            previous, restarted, reopened = None, False, None
            try:
                for i in range(CONTRACT["seconds"] * CONTRACT["ticks_per_second"]):
                    target = began + i / CONTRACT["ticks_per_second"]
                    time.sleep(max(0, target - time.perf_counter()))
                    actual = time.time()
                    if not restarted and time.perf_counter() - began >= 30:
                        before = store.read()["autonomous_lab"]
                        dsn = store.connection.info.dsn
                        store.close()
                        reopened = PaperStore(dsn, owner=True)
                        store = reopened
                        paper = PaperRuntime(store, None)
                        paper.running = True
                        recovered = AutonomousLab(lab.registry, paper, lambda: True)
                        assert store.read()["autonomous_lab"] == before
                        lab = recovered
                        restarted = True
                    started = time.perf_counter()
                    tick_lab(lab, actual)
                    commit = (time.perf_counter() - started) * 1000
                    feature_started = time.perf_counter()
                    study = {
                        "BTCUSD": {
                            v: features(lab.paper.history["BTCUSD"], actual, v) for v in VARIANTS
                        }
                    }
                    lab.paper.numerical_study(actual, study)
                    feature_ms = (time.perf_counter() - feature_started) * 1000
                    research_started = time.perf_counter()
                    lab.step(actual)
                    research_ms = (time.perf_counter() - research_started) * 1000
                    rows.append(
                        {
                            "financial_loop_ms": commit,
                            "features_ms": feature_ms,
                            "research_step_ms": research_ms,
                        }
                    )
                    peaks.append(finance.slots(store.read())["used"])
                    queue.append(
                        sum(
                            r["count"]
                            for r in lab.inbox.page()["counts"]
                            if r["status"] in {"evaluated", "reserved"}
                        )
                    )
                    if previous is not None:
                        gaps.append(actual - previous)
                    previous = actual
                state = store.read()
                receipt.update(
                    wall_seconds=time.perf_counter() - began,
                    ticks=len(rows),
                    restarted=restarted,
                    peak_slots=max(peaks),
                    peak_queue=max(queue),
                    stage_ms={key: percentiles([r[key] for r in rows]) for key in rows[0]},
                    largest_observed_interval=max(gaps),
                    rss_mib=rss_bytes() / 1024**2,
                    rss_growth_mib=(rss_bytes() - initial_rss) / 1024**2,
                    history_trials=state["autonomous_lab"]["historical_trials"],
                    archived_accounts=state["autonomous_lab"]["retired_count"],
                    active_projection_bytes=len(json.dumps(state).encode()),
                    registry_bytes=sum(
                        p.stat().st_size for p in Path(folder).glob("experiments.sqlite3*")
                    ),
                    postgres=store.storage_usage(),
                    balanced=store.reconcile()["balanced"],
                    budget=state["autonomous_lab"]["budget"],
                )
                receipt["passed"] = (
                    restarted
                    and receipt["peak_slots"] == 20
                    and receipt["peak_queue"] <= 4
                    and receipt["balanced"]
                    and receipt["archived_accounts"] == 72
                    and receipt["history_trials"] == 43
                    and receipt["stage_ms"]["financial_loop_ms"]["p95"] <= 100
                    and receipt["stage_ms"]["features_ms"]["p95"] <= 100
                    and receipt["rss_mib"] <= 512
                    and receipt["rss_growth_mib"] <= 64
                )
                output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
                print(json.dumps(receipt, indent=2), flush=True)
                assert receipt["passed"], "Retain failed finite receipt"
            finally:
                lab.registry.close()
                if reopened:
                    reopened.close()


def serve(port):
    verify_database()
    _, _, _, tick_lab = fixture_helpers()
    clock = {"offset": 0.0}
    with tempfile.TemporaryDirectory(prefix="continuous-ui-") as folder:
        data = Path(folder)
        from trading.research_storage import StoragePlan, save_plan, volume

        qa_root = data / "Q-Trades-Data-qa-ui"
        save_plan(
            data,
            StoragePlan(
                root=str(qa_root),
                volume_identity=volume(qa_root)["identity"],
                temporary_bytes=64 * 1024**2,
                research_bytes=64 * 1024**2,
                scratch_bytes=1024**2,
                segment_bytes=256 * 1024,
                free_reserve_bytes=0,
            ),
        )
        app = create_app(
            Settings(),
            data / "monitor.sqlite",
            ROOT / "apps/web/dist",
            background=False,
            research_evidence=data / "no-model-evaluations",
        )
        original = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(app):
            with disposable() as store:
                async with original(app):
                    runtime = TieredPaperRuntime(store, None, data / "stream.sqlite")
                    runtime.running = True
                    runtime.ready_at = 0
                    runtime.stream.plan = {"BTCUSD": 100, "ETHUSD": 100}
                    runtime.instruments = {
                        base + "USD": {
                            "base": base,
                            "quote": "USD",
                            "venue_status": "TRADING",
                            "spot_allowed": True,
                            "minimum_notional": "1",
                            "filters": [
                                {
                                    "filterType": "LOT_SIZE",
                                    "stepSize": ".00001",
                                    "minQty": ".00001",
                                    "maxQty": "100",
                                },
                                {
                                    "filterType": "PRICE_FILTER",
                                    "tickSize": ".01",
                                    "minPrice": ".01",
                                    "maxPrice": "1000000",
                                },
                                {"filterType": "MIN_NOTIONAL", "minNotional": "1"},
                            ],
                        }
                        for base in ("BTC", "ETH")
                    }
                    app.state.paper = runtime
                    lab = app.state.lab
                    lab.autonomous = AutonomousLab(lab.registry, runtime, lambda: True)
                    lab.can_research = lambda: True

                    async def feed():
                        seq = 0
                        persisted = {}
                        while True:
                            at, seq = time.time(), seq + 1
                            runtime.history = {s: stable_bars(at) for s in ("BTCUSD", "ETHUSD")}
                            runtime.books = frames(
                                at, seq, str(runtime.history["BTCUSD"][-1].close)
                            )
                            runtime.metadata_at = at
                            runtime.universe.scanned_at = at
                            runtime.universe.selected = ["BTCUSD", "ETHUSD"]
                            runtime.universe.rows = [
                                {
                                    "symbol": s,
                                    "eligible": True,
                                    "change_pct": "0",
                                    "quote_volume": "1000000",
                                    "synthetic": True,
                                }
                                for s in runtime.books
                            ]
                            runtime._fallback = {
                                s: {**f, "received_mono": time.monotonic()}
                                for s, f in runtime.books.items()
                            }
                            runtime.study = {
                                s: {v: features(runtime.history[s], at, v) for v in VARIANTS}
                                for s in runtime.books
                            }
                            runtime.numerical_study(at, runtime.study)

                            def apply(engine):
                                engine.universe_experiment(["BTCUSD", "ETHUSD"])
                                engine.state["evidence_kind"] = "synthetic_qa_continuous"
                                engine.tick(runtime.books, runtime.study)

                            runtime.state = store.transact(at, apply)
                            for s, bars in runtime.history.items():
                                if persisted.get(s) == bars[-1].open_ms:
                                    continue
                                selected = bars if s not in persisted else bars[-1:]
                                raw = [
                                    [
                                        b.open_ms,
                                        str(b.open),
                                        str(b.high),
                                        str(b.low),
                                        str(b.close),
                                        str(b.volume),
                                        b.close_ms,
                                    ]
                                    for b in selected
                                ]
                                store.bars(s, raw, at, bootstrap=True)
                                persisted[s] = bars[-1].open_ms
                            runtime.recent = store.recent()
                            runtime.receipts = store.reconcile()
                            runtime.evidence.summary(at, runtime.books, {})
                            await asyncio.sleep(0.25)

                    feed_task = asyncio.create_task(feed())
                    worker = asyncio.create_task(lab.run())
                    storage_task = asyncio.create_task(runtime.evidence.run(lambda: True))
                    try:
                        yield
                    finally:
                        for task in (feed_task, worker, storage_task):
                            task.cancel()
                            with suppress(asyncio.CancelledError):
                                await task

        app.router.lifespan_context = lifespan

        @app.post("/qa/complete-window")
        async def complete(request: Request):
            if request.client.host != "127.0.0.1" or request.headers.get("X-QA-Fixture") != "1":
                return {"qa_only": True, "applied": False}
            controller = request.app.state.lab.autonomous
            trial = next(
                t
                for t in controller.paper.state["autonomous_lab"]["trials"].values()
                if t["status"] == "active"
            )
            body = await request.json()
            # The live browser feed has already observed part of this synthetic
            # window. Never rewind its financial clock to a trial's earlier start.
            wanted = body.get("outcome", "inconclusive")
            base = int(max(time.time(), controller.paper.state["last_tick"]) // 60) * 60 + 62
            if base + 125 >= trial["review_at"]:
                return {
                    "qa_only": True,
                    "applied": False,
                    "reason": "Insufficient future synthetic window",
                }
            with controller.paper.store.transaction_lock:
                if wanted in {"promising", "economically_unsuccessful"}:
                    entry_price = "90" if wanted == "promising" else "100"
                    tick_lab(controller, base, entry_price, True)
                    tick_lab(controller, base + 2, entry_price, True)
                    price = "110" if wanted == "promising" else "99"
                    tick_lab(controller, base + 5, price)
                    tick_lab(controller, base + 7, price)
                else:
                    price = "100"
                clock["offset"] = trial["review_at"] - REAL_TIME()
                tick_lab(controller, trial["review_at"], price, coverage=wanted != "data_blocked")
                assert controller.step(trial["review_at"]), controller.last_error
                result = controller.paper.store.connection.execute(
                    "SELECT body FROM paper_events WHERE kind='lab_trial_scored' "
                    "AND body->>'trial_id'=%s",
                    (trial["id"],),
                ).fetchone()["body"]
                assert result["outcome"] == wanted, result
                tick_lab(controller, trial["review_at"] + 2, price)
                clock["offset"] = trial["review_at"] + 4 - REAL_TIME()
            return {"qa_only": True, "accelerated_clock": True, "score": result}

        @app.post("/qa/shutdown")
        async def stop(request: Request):
            if request.headers.get("X-QA-Fixture") == "1":
                server.should_exit = True
            return {"qa_only": True}

        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        print(json.dumps({"qa_only": True, "synthetic": True, "port": port}), flush=True)
        with patch("time.time", lambda: REAL_TIME() + clock["offset"]):
            server.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["soak", "serve"])
    parser.add_argument("--port", type=int, default=8798)
    parser.add_argument("--output", type=Path, default=ROOT / "data/continuous-native.json")
    args = parser.parse_args()
    if args.mode == "soak":
        soak(args.output)
    else:
        serve(args.port)
