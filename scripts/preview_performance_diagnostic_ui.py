"""Compiled UI against actual disposable owners; synthetic books, no model/venue calls.

Finite QA-only HTTP loss/rejection seams surround the real operator API. Trades,
balances, account creation and the permanent Journal use the actual PaperStore.
This fixture supplies synthetic calm work observations, never capacity proof.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, cast

import httpx
import psycopg
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from trading.api import create_app
from trading.config import Settings
from trading.financial_readback import FinancialReadback
from trading.paper_engine import PaperEngine
from trading.paper_store import PaperStore, load_dsn
from trading.paper_strategy import VARIANTS
from trading.tiered_runtime import TieredPaperRuntime
from trading.venue import PublicVenue

ROOT = Path(__file__).resolve().parents[1]
NAME = "performance-diagnostic"


class NoNetworkVenue(PublicVenue):
    def __init__(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise RuntimeError(f"QA refuses external venue operation: {request.url.path}")

        super().__init__(transport=httpx.MockTransport(refuse))


def main() -> None:
    sys.path.insert(0, str(ROOT / "tests"))
    from financial_monitoring_fixture import monitoring_constrained
    from verify_cp3 import frames

    fixture_frames = cast(Callable[[float, int], dict[str, Any]], frames)

    parser = argparse.ArgumentParser()
    parser.add_argument("--database-config", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=58976)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_relative_to(Path("C:/Projects/outputs/qtrades-performance-66")):
        raise RuntimeError("Use the explicit task-owned performance QA output directory")
    dsn = load_dsn(args.database_config)
    info = conninfo_to_dict(dsn)
    if info.get("host") != "127.0.0.1" or info.get("port") != "54544":
        raise RuntimeError("This fixture requires the verified dedicated disposable QA server")
    directory.mkdir(parents=True, exist_ok=False)
    token = uuid.uuid4().hex
    (directory / "access-token.txt").write_text(token, encoding="utf-8")
    schema = "test_performance_ui_" + uuid.uuid4().hex
    admin = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    admin.execute("SET statement_timeout = '5s'")
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    venue = NoNetworkVenue()
    app = create_app(
        Settings(),
        directory / "monitor.sqlite",
        ROOT / "apps/web/dist",
        background=False,
        venue=venue,
        research_evidence=directory / "absent-model-evidence",
    )
    original_lifespan = app.router.lifespan_context
    loaded_source_files = (
        "src/trading/api.py",
        "src/trading/paper_runtime.py",
        "src/trading/tiered_runtime.py",
        "src/trading/paper_store.py",
        "src/trading/paper_engine.py",
        "src/trading/paper_diagnostics.py",
        "src/trading/account_purpose.py",
        "src/trading/engine_diagnostics.py",
        "scripts/preview_performance_diagnostic_ui.py",
    )
    loaded_source_hashes = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in loaded_source_files
    }
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )
    control: dict[str, Any] = {
        "mode": "healthy",
        "sequence": 0,
        "lost_ack_next_start": False,
        "diagnostic_get_unavailable": False,
        "reject_next_create": False,
        "writes": [],
        "tick_error": None,
    }
    runtime: TieredPaperRuntime | None = None
    reader: FinancialReadback | None = None
    baseline_accounts: dict[str, Any] = {}
    final: dict[str, Any] = {
        "scope": "Actual compiled UI/API/disposable PostgreSQL; synthetic market/work coverage",
        "operating_access": False,
        "model_calls": 0,
        "external_market_calls": 0,
        "schema_dropped": False,
        "completed": False,
        "loaded_source_sha256": loaded_source_hashes,
    }

    def save(name: str, value: Any) -> None:
        (directory / name).write_text(json.dumps(value, indent=2), encoding="utf-8")

    def authorize(request: Request) -> None:
        if request.headers.get("x-qa-token") != token:
            raise HTTPException(403, "QA token required")

    def probe() -> dict[str, Any]:
        assert runtime is not None
        with runtime.store.transaction_lock:
            state = runtime.store.read()
            events = runtime.store.export(0, 1000)
            balance = runtime.store.reconcile()
        account = state["accounts"].get(NAME)
        return {
            "mode": control["mode"],
            "diagnostics": runtime.diagnostic_snapshot(),
            "state": state,
            "events": events,
            "balance": balance,
            "baseline_financial_preserved": all(
                all(
                    state["accounts"][name][key] == original[key]
                    for key in (
                        "cash",
                        "funding",
                        "starting_capital",
                        "fees",
                        "positions",
                        "pending",
                        "risk_policy",
                        "execution_profile",
                        "attempt",
                    )
                )
                for name, original in baseline_accounts.items()
            ),
            "diagnostic_run_count": len(account["diagnostic"]["runs"]) if account else 0,
            "diagnostic_funding_count": sum(
                event["kind"] == "performance_diagnostic_funded" for event in events["records"]
            ),
            "writes": control["writes"],
            "tick_error": control["tick_error"],
        }

    @app.middleware("http")
    async def bounded_http_failures(request: Request, call_next: Any) -> Any:
        path = request.url.path
        if (
            request.method == "GET"
            and path == "/api/paper/diagnostics"
            and control["diagnostic_get_unavailable"]
        ):
            return JSONResponse({"detail": "Synthetic QA unavailable acknowledgment reader"}, 503)
        entry = None
        if request.method == "POST" and path.startswith("/api/paper/diagnostics/"):
            entry = {"path": path, "body": json.loads(await request.body()), "at": time.time()}
            control["writes"].append(entry)
            if path.endswith("/create") and control["reject_next_create"]:
                control["reject_next_create"] = False
                entry.update(status=503, injected="before_actual_handler")
                return JSONResponse({"detail": "Synthetic QA delivery failed before dispatch"}, 503)
        response = await call_next(request)
        if entry is not None:
            entry["status"] = response.status_code
            if (
                path.endswith("/start")
                and control["lost_ack_next_start"]
                and response.status_code == 200
            ):
                control["lost_ack_next_start"] = False
                control["diagnostic_get_unavailable"] = True
                entry.update(delivered_status=503, injected="after_actual_commit")
                return JSONResponse(
                    {"detail": "Synthetic QA lost HTTP acknowledgment after commit"}, 503
                )
        return response

    @app.post("/__qa/mode")
    async def mode(request: Request) -> dict[str, Any]:
        authorize(request)
        assert runtime is not None
        value = (await request.json()).get("mode")
        if value == "reject_next_create":
            control["reject_next_create"] = True
        elif value == "lost_ack_next_start":
            control["lost_ack_next_start"] = True
        elif value == "release_ack":
            control["diagnostic_get_unavailable"] = False
        elif value in {"healthy", "guard_closed", "stale"}:
            control["mode"] = value
            runtime.running = value != "stale"
            runtime.error = "Synthetic QA paper feed unavailable" if value == "stale" else None
            runtime._capture_failure = (
                "Synthetic QA capture guard closed" if value == "guard_closed" else None
            )
        else:
            raise HTTPException(422, "Unsupported QA mode")
        return {"mode": control["mode"]}

    @app.get("/__qa/probe")
    def observed(request: Request) -> dict[str, Any]:
        authorize(request)
        return probe()

    @app.post("/__qa/shutdown")
    async def shutdown(request: Request) -> dict[str, bool]:
        authorize(request)
        server.should_exit = True
        return {"shutdown_requested": True}

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        nonlocal runtime, reader, baseline_accounts
        store = PaperStore(scoped_dsn, owner=True)
        store.initialize(time.time(), execution_profile="paper-rest-ioc-v1")
        runtime = TieredPaperRuntime(store, venue, directory / "paper-stream.sqlite")
        reader = FinancialReadback(store)
        runtime.ready_at = time.time() - 120
        runtime.running = True
        runtime.stream.plan = {"BTCUSD": 100, "ETHUSD": 100}
        runtime.instruments = {
            base + "USD": {
                "symbol": base + "USD",
                "base": base,
                "quote": "USD",
                "venue_status": "TRADING",
                "spot_allowed": True,
                "minimum_notional": "1",
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
                ],
            }
            for base in ("BTC", "ETH")
        }
        baseline_accounts = json.loads(json.dumps(store.read()["accounts"]))

        async def feed() -> None:
            assert runtime is not None and reader is not None
            deadline = time.monotonic() + 360
            try:
                while time.monotonic() < deadline and not server.should_exit:
                    monitoring_constrained(runtime)  # Explicit synthetic calm coverage.
                    if control["mode"] != "stale":
                        now = time.time()
                        control["sequence"] += 1
                        books = fixture_frames(now, control["sequence"])
                        for frame in books.values():
                            frame.update(
                                source="synthetic-performance-ui-fixture",
                                received_mono=time.monotonic(),
                                diagnostic_risk_input_valid=True,
                            )
                        bar_open = (int(now // 60) - 1) * 60000
                        study = {
                            symbol: {
                                version: {
                                    "eligible": False,
                                    "bar_open_ms": bar_open,
                                    "atr": "1",
                                    "reason": "Synthetic current negative strategy signal",
                                    "version": version,
                                    "closed_bars": 400,
                                }
                                for version in VARIANTS
                            }
                            for symbol in books
                        }
                        runtime.books = books
                        runtime.study = study
                        runtime.metadata_at = now
                        runtime._fallback = books
                        allowed = runtime.diagnostic_entries_allowed()

                        def tick(
                            engine: PaperEngine,
                            books: dict[str, Any] = books,
                            study: dict[str, Any] = study,
                            allowed: bool = allowed,
                        ) -> None:
                            engine.state.update(evidence_kind="synthetic_performance_ui_fixture")
                            engine.tick(books, study, diagnostic_allowed=allowed)

                        with store.transaction_lock:
                            runtime._transact_state(now, tick)
                    sampled = reader.sample(audit=True)
                    runtime._accept_financial_audit(sampled)
                    runtime._accept_financial_sample(sampled)
                    await asyncio.sleep(0.25)
            except Exception as exc:
                control["tick_error"] = type(exc).__name__
                runtime.error = "Synthetic QA feed stopped; inspect retained exception"
                save("feed-failure.json", {"type": type(exc).__name__, "message": str(exc)})
                raise
            finally:
                server.should_exit = True

        async with original_lifespan(application):
            application.state.paper = runtime
            feed_task = asyncio.create_task(feed())
            try:
                save(
                    "server-ready.json",
                    {
                        "port": args.port,
                        "pid": os.getpid(),
                        "qa_database": {"host": "127.0.0.1", "port": "54544", "schema": schema},
                        "background_workers": False,
                        "synthetic_calm_work": True,
                        "loaded_source_sha256": loaded_source_hashes,
                        "compiled_index_sha256": hashlib.sha256(
                            (ROOT / "apps/web/dist/index.html").read_bytes()
                        ).hexdigest(),
                    },
                )
                yield
            finally:
                final.update(probe(), completed=control["tick_error"] is None)
                final["loaded_source_unchanged_at_shutdown"] = all(
                    hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
                    for name, digest in loaded_source_hashes.items()
                )
                save("actual-final-financial-receipt.json", final)
                feed_task.cancel()
                with suppress(asyncio.CancelledError):
                    await feed_task
                reader.close()
                await runtime.stream.close()
                store.close()

    app.router.lifespan_context = lifespan
    try:
        server.run()
    finally:
        if schema.startswith("test_performance_ui_") and len(schema) == 52:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            final["schema_dropped"] = True
        admin.close()
        save(
            "cleanup-receipt.json",
            {
                "schema": schema,
                "schema_dropped": final["schema_dropped"],
                "owned_server_finished": True,
                "operating_access": False,
                "model_calls": 0,
            },
        )


if __name__ == "__main__":
    main()
