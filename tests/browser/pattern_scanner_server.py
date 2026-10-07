"""Isolated real scanner API/registry/worker; native source and admission are synthetic."""

import argparse
import asyncio
import copy
import hashlib
import json
import os
import sys
import time
from contextlib import asynccontextmanager, nullcontext
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import uvicorn
from fastapi import Header, HTTPException
from starlette.responses import JSONResponse

from trading import pattern_scanner as scanner_module
from trading.api import create_app
from trading.candle_history import INTERVALS
from trading.config import Settings
from trading.pattern_scanner import PatternScanner
from trading.research_storage import ResearchStorage, save_plan
from trading.venue import PublicVenue


def main():
    if os.environ.get("QTRADES_TEST_DATABASE"):
        raise ValueError("The scanner browser fixture has no financial database")
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--port", type=int, default=58969)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port in {8780, 5432, 54544, 58968}:
        raise ValueError("A separate isolated QA port is required")
    token = os.environ["QTRADES_BROWSER_QA_TOKEN"]
    args.directory.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[2]
    names = [
        "src/trading/api.py",
        "src/trading/pattern_scanner.py",
        "src/trading/candle_history.py",
        "src/trading/candle_patterns.py",
        "src/trading/research_storage.py",
        "src/trading/evidence_runtime.py",
        "src/trading/venue.py",
        "apps/web/src/ScannerWorkspace.tsx",
        "apps/web/src/scanner-workspace.css",
        "apps/web/src/MarketStation.tsx",
        "tests/browser/pattern_scanner_server.py",
    ]
    hashes = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in names}
    hashes.update(
        {
            "compiled/" + file.relative_to(args.web_dist).as_posix(): hashlib.sha256(
                file.read_bytes()
            ).hexdigest()
            for file in args.web_dist.rglob("*")
            if file.is_file()
        }
    )
    (args.directory / "source-manifest.json").write_text(
        json.dumps(hashes, indent=2), encoding="utf-8"
    )
    sys.path.insert(0, str(repo / "tests"))
    from conftest import book
    from test_paper_runtime import instrument
    from test_research_storage import plan_at
    from test_station import runtime

    plan = plan_at(args.directory).model_copy(update={"temporary_bytes": 128 * 1024**2})
    save_plan(args.directory, plan)
    paper = runtime.__wrapped__(args.directory, book.__wrapped__())
    symbols = ["BTCUSD", "ETHUSD", *[f"QA{index:02d}USD" for index in range(24)], "THINUSD"]
    paper.instruments = {symbol: instrument(symbol[:-3]) for symbol in symbols}
    paper.universe.instruments = paper.instruments
    mode = "normal"
    blocked = False
    clock_offset = 0
    prospective_cutoff = None
    calls, posts, advances = [], [], []
    scanner_module.time = SimpleNamespace(
        time=lambda: time.time() + clock_offset, perf_counter=time.perf_counter
    )

    def tick():
        now = time.time() + clock_offset
        paper.state["last_tick"] = now
        paper.metadata_at = now
        paper.universe.metadata_at = now
        paper.universe.screen(
            [
                {
                    "symbol": symbol,
                    "bidPrice": "100",
                    "askPrice": "100.1",
                    "quoteVolume": "1" if symbol == "THINUSD" else "1000000",
                    "lowPrice": "99",
                    "highPrice": "101",
                    "priceChangePercent": "0",
                    "count": 1000,
                    "closeTime": int(now * 1000),
                }
                for symbol in symbols
            ],
            now,
            set(),
        )
        paper._fallback["BTCUSD"]["observed"] = now
        paper._fallback["BTCUSD"]["received_mono"] = time.monotonic()

    # Explicitly synthetic resource admission; this is UI/worker behavior, not
    # financial-health, operating-guard, market-capacity or profitability proof.
    paper.constrained = lambda *_: blocked
    tick()
    original = copy.deepcopy(paper.state)

    def native(request):
        if request.url.path != "/api/v3/klines":
            raise AssertionError("The QA fixture permits native historical GET only")
        query = request.url.params
        calls.append(dict(query))
        if mode == "source_fail":
            raise httpx.ReadError("Synthetic native source unavailable", request=request)
        step = INTERVALS[query["interval"]] * 1000
        start, end = int(query["startTime"]), int(query["endTime"])
        if mode in {"sparse_4h", "future_4h"} and query["interval"] != "4h":
            return httpx.Response(200, json=[])
        rows = []
        for at in list(range(start, end + 1, step))[: int(query["limit"])]:
            if mode == "gap" and at == start + step:
                continue
            index = (at // step) % 1000
            # Recurring causal support visits, with drift inside the frozen zone;
            # actual scanner rules create both pivots and bounce observations.
            base = Decimal(100) + Decimal(index // 6) / 40
            phase = index % 6
            high = base + (Decimal(2) if phase == 4 else Decimal("0.3"))
            low = base - (Decimal(2) if phase == 2 else Decimal("0.3"))
            volume = Decimal(30) if phase in {2, 4} else Decimal(10)
            close = base + (Decimal("0.1") if phase == 2 else Decimal(0))
            if mode in {"sparse_4h", "future_4h"}:
                base, high, low, close, volume = map(Decimal, (100, 101, 99, 100, 10))
                if at == prospective_cutoff - 4 * step:
                    high = Decimal(103)
                if at == prospective_cutoff:
                    high, close, volume = map(Decimal, (105, 104, 20))
            rows.append(
                [
                    at,
                    str(base),
                    str(high),
                    str(low),
                    str(close),
                    str(volume),
                    at + step - 1,
                    "1000",
                    1,
                    "5",
                    "500",
                    "0",
                ]
            )
        return httpx.Response(200, json=rows)

    venue = PublicVenue(transport=httpx.MockTransport(native))
    app = create_app(
        Settings(),
        args.directory / "monitor.sqlite",
        background=False,
        venue=venue,
        web_dist=args.web_dist,
    )
    old_lifespan = app.router.lifespan_context
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )

    def financial_unchanged():
        current = copy.deepcopy(paper.state)
        current["last_tick"] = original["last_tick"]
        return current == original

    @asynccontextmanager
    async def lifespan(application):
        async with old_lifespan(application):
            application.state.paper = paper
            # One disposable shared writer, borrowed without per-page recovery.
            storage = ResearchStorage(plan)

            def storage_owner(declared):
                if declared != plan:
                    raise ValueError("Disposable storage identity differs")
                return nullcontext(storage)

            application.state.scanner_storage_owner = storage_owner
            application.state.pattern_scanner = PatternScanner(
                application.state.lab.registry, paper, venue, plan, storage_owner
            )
            application.state.lab.pattern_scanner = application.state.pattern_scanner
            try:
                yield
            finally:
                (args.directory / "shutdown.json").write_text(
                    json.dumps(
                        {
                            "fixture": (
                                "synthetic_native_source_and_admission_actual_scanner_api_registry"
                            ),
                            "financial_database": False,
                            "model_calls": 0,
                            "financial_state_preserved_except_fixture_tick": financial_unchanged(),
                            "posts": posts,
                            "native_requests": calls,
                            "advances": advances,
                            "source_hashes": hashes,
                            "source_hashes_after": {
                                name: hashlib.sha256((repo / name).read_bytes()).hexdigest()
                                for name in names
                            },
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                storage.close()

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def failures(request, call_next):
        if mode == "status_outage" and request.url.path == "/api/research/pattern-scanner":
            return JSONResponse({"detail": "Synthetic status outage"}, status_code=503)
        if mode == "receipt_outage" and request.url.path.startswith(
            "/api/research/pattern-scanner/requests/"
        ):
            return JSONResponse({"detail": "Synthetic exact-receipt outage"}, status_code=503)
        if request.method == "POST" and request.url.path == "/api/research/pattern-scanner/control":
            body = await request.json()
            selected_mode = mode
            if selected_mode == "delay_start" and body["action"] == "start":
                await asyncio.sleep(2)
            response = await call_next(request)
            saved = app.state.pattern_scanner.request(body["request_id"])
            posts.append(
                {
                    "body": body,
                    "fixture": selected_mode,
                    "http_status": response.status_code,
                    "saved_receipt": saved,
                }
            )
            if selected_mode == "lost_ack" and response.status_code == 200:
                return JSONResponse(
                    {"detail": "Synthetic acknowledgment lost after actual control commit"},
                    status_code=503,
                )
            return response
        return await call_next(request)

    def authorize(value):
        if value != token:
            raise HTTPException(403)

    @app.get("/__qa/probe")
    def probe(x_qa_token: str = Header()):
        authorize(x_qa_token)
        scanner = app.state.pattern_scanner
        with scanner.registry.lock:
            levels = [
                dict(row)
                for row in scanner.registry.db.execute(
                    "SELECT campaign,symbol,timeframe,count(*) AS total FROM pattern_levels "
                    "GROUP BY campaign,symbol,timeframe"
                )
            ]
            events = [
                dict(row)
                for row in scanner.registry.db.execute(
                    "SELECT campaign,symbol,timeframe,kind,count(*) AS total FROM pattern_events "
                    "GROUP BY campaign,symbol,timeframe,kind"
                )
            ]
        return {
            "posts": posts,
            "native_requests": calls,
            "advances": advances,
            "levels": levels,
            "events": events,
            "state": scanner.snapshot(),
            "financial_database": False,
            "model_calls": 0,
            "synthetic_clock_offset_seconds": clock_offset,
            "financial_state_preserved_except_fixture_tick": financial_unchanged(),
            "source_hashes": hashes,
        }

    @app.post("/__qa/advance")
    async def advance(x_qa_token: str = Header()):
        authorize(x_qa_token)
        scanner = app.state.pattern_scanner
        steps = 0
        async with asyncio.timeout(25):
            for _ in range(600 if mode in {"sparse_4h", "future_4h"} else 300):
                tick()
                await scanner.step()
                steps += 1
                with scanner.registry.lock:
                    maximum = scanner.registry.db.execute(
                        "SELECT max(n) FROM (SELECT count(*) n FROM pattern_levels "
                        "GROUP BY campaign,symbol,timeframe)"
                    ).fetchone()[0]
                    completed_pages = scanner.registry.db.execute(
                        "SELECT max(CAST(json_extract(body,'$.pages') AS INTEGER)) "
                        "FROM pattern_progress"
                    ).fetchone()[0]
                    prospective = scanner.registry.db.execute(
                        "SELECT count(*) FROM pattern_events WHERE kind='alerts'"
                    ).fetchone()[0]
                scopes = scanner.snapshot()["progress"]
                if mode == "sparse_4h" and all(row["status"] == "monitoring" for row in scopes):
                    break
                if mode == "future_4h" and prospective:
                    break
                if mode not in {"sparse_4h", "future_4h"} and maximum and maximum > 105:
                    break
                if blocked:
                    break
        result = {
            "steps": steps,
            "maximum_levels": maximum,
            "completed_pages": completed_pages,
            "actual_native_requests": len(calls),
        }
        advances.append(result)
        return result

    @app.post("/__qa/{action}")
    def control(action: str, x_qa_token: str = Header()):
        nonlocal mode, blocked, clock_offset, prospective_cutoff
        authorize(x_qa_token)
        if action == "stop":
            server.should_exit = True
            return {"stopping": True}
        if action == "restart_owner":
            app.state.pattern_scanner = PatternScanner(
                app.state.lab.registry, paper, venue, plan, app.state.scanner_storage_owner
            )
            app.state.lab.pattern_scanner = app.state.pattern_scanner
            return {
                "existing_owner_reconstructed": True,
                "state": app.state.pattern_scanner.snapshot(),
            }
        if action in {"block", "unblock"}:
            blocked = action == "block"
            return {"synthetic_admission_blocked": blocked}
        if action == "sparse_4h":
            prospective_cutoff = int(time.time() * 1000) // 14400000 * 14400000
        if action == "future_4h":
            if prospective_cutoff is None:
                raise HTTPException(409, "An actual historical preparation is required")
            clock_offset = 14400
            tick()
        if action not in {
            "normal",
            "gap",
            "source_fail",
            "lost_ack",
            "receipt_outage",
            "status_outage",
            "delay_start",
            "sparse_4h",
            "future_4h",
        }:
            raise HTTPException(404)
        mode = action
        return {"fixture": mode}

    server.run()


if __name__ == "__main__":
    main()
