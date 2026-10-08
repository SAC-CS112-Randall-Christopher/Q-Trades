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

from trading import pattern_charts as charts_module
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
    parser.add_argument("--chart-check", action="store_true")
    parser.add_argument("--daily-check", action="store_true")
    args = parser.parse_args()
    if args.chart_check and args.daily_check:
        raise ValueError("Choose one explicit disposable workflow")
    if not 1024 <= args.port <= 65535 or args.port in {8780, 5432, 54544, 58968}:
        raise ValueError("A separate isolated QA port is required")
    token = os.environ["QTRADES_BROWSER_QA_TOKEN"]
    args.directory.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[2]
    names = [
        "src/trading/api.py",
        "src/trading/pattern_scanner.py",
        "src/trading/pattern_charts.py",
        "src/trading/candle_history.py",
        "src/trading/candle_patterns.py",
        "src/trading/research_storage.py",
        "src/trading/evidence_runtime.py",
        "src/trading/venue.py",
        "apps/web/src/ScannerWorkspace.tsx",
        "apps/web/src/scanner-workspace.css",
        "apps/web/src/MarketStation.tsx",
        "apps/web/src/CandleWorkspace.tsx",
        "apps/web/src/WorkspaceViews.tsx",
        "apps/web/src/candle-workspace.css",
        "tests/browser/pattern_scanner_server.py",
    ]
    if args.daily_check:
        names.append("apps/web/src/DailyAnalyzer.tsx")

    def current_hashes():
        source = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in names}
        source.update(
            {
                "compiled/" + file.relative_to(args.web_dist).as_posix(): hashlib.sha256(
                    file.read_bytes()
                ).hexdigest()
                for file in args.web_dist.rglob("*")
                if file.is_file()
            }
        )
        return source

    hashes = current_hashes()
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
    chart_setup = None
    daily_roster_changed = False
    daily_roster_unavailable = False
    held_start = None
    held_start_event = None
    held_start_entered = asyncio.Event()
    calls, posts, advances, reads, setup_controls = [], [], [], [], []
    scanner_module.time = SimpleNamespace(
        time=lambda: time.time() + clock_offset, perf_counter=time.perf_counter
    )
    if args.chart_check or args.daily_check:
        # The synthetic prospective close clock belongs to both the scanner and
        # its read projection. Global and financial runtime clocks stay real.
        charts_module.time = SimpleNamespace(time=lambda: time.time() + clock_offset)

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
                    "quoteVolume": "1"
                    if symbol == "THINUSD" or daily_roster_changed and symbol == "BTCUSD"
                    else "2000000"
                    if daily_roster_changed and symbol == "ETHUSD"
                    else "1000000",
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
        if daily_roster_unavailable:
            paper.universe.metadata_at = now - 901

    # Explicitly synthetic resource admission; this is UI/worker behavior, not
    # financial-health, operating-guard, market-capacity or profitability proof.
    paper.constrained = lambda *_: blocked
    tick()
    if args.chart_check:
        # Explicit synthetic account projection for the Accounts presentation
        # check only; no financial DB, funding or archived-account proof.
        for role in ("candidate", "reference"):
            saved = copy.deepcopy(paper.state["accounts"]["primary"])
            saved.update(campaign_id="autonomous-lab", label="QA lab " + role)
            paper.state["accounts"]["qa-lab-" + role] = saved
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
        if args.daily_check and query["interval"] != "4h":
            return httpx.Response(200, json=[])
        if mode in {"sparse_4h", "future_4h"} and query["interval"] != "4h":
            return httpx.Response(200, json=[])
        rows = []
        row_limit = int(query["limit"])
        if args.chart_check and mode == "normal":
            # This chart fixture deliberately observes only 360 native candles
            # from each requested 1,000-slot slice; the scanner records the
            # other slots as missing. Default scanner QA remains unchanged.
            row_limit = min(row_limit, 360)
        for at in list(range(start, end + 1, step))[:row_limit]:
            daily_cutoff = int((time.time() + clock_offset) * 1000) // step * step
            if args.daily_check and at < daily_cutoff - 32 * step:
                # A genuine sparse synthetic year: older requested slots are
                # absent, explicitly counted by the unchanged scanner.
                continue
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
            if args.daily_check:
                base, high, low, close, volume = map(Decimal, (100, 101, 99, 100, 10))
                if at == daily_cutoff - 5 * step:
                    high = Decimal(103)
                if at >= daily_cutoff - 2 * step:
                    high, close, volume = map(Decimal, (105, 104, 20))
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
        paper_database=None,
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
                            "daily_check": args.daily_check,
                            "financial_state_preserved_except_fixture_tick": financial_unchanged(),
                            "posts": posts,
                            "setup_controls": setup_controls,
                            "chart_setup": chart_setup,
                            "held_start": held_start,
                            "reads": reads,
                            "synthetic_lab_account_projection": args.chart_check,
                            "native_requests": calls,
                            "advances": advances,
                            "source_hashes": hashes,
                            "source_hashes_after": current_hashes(),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                storage.close()

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def failures(request, call_next):
        nonlocal held_start, held_start_event
        if args.daily_check:
            tick()  # Explicitly synthetic current paper/screen, not operating health.
        if args.chart_check and request.method == "GET" and request.url.path.startswith("/api/"):
            reads.append({"path": request.url.path, "query": str(request.url.query)})
            if len(reads) > 2000:
                return JSONResponse({"detail": "Finite QA read bound reached"}, status_code=503)
            if request.url.path == "/api/research/pattern-scanner/chart":
                if (
                    mode == "chart_window_fail"
                    and request.query_params.get("timeframe") == "5m"
                    and "before_ms" in request.query_params
                ):
                    return JSONResponse(
                        {"detail": "Synthetic changed saved window unavailable"}, status_code=503
                    )
                if mode == "chart_frame_fail" and request.query_params.get("timeframe") == "30m":
                    return JSONResponse(
                        {"detail": "Synthetic saved frame read unavailable"}, status_code=503
                    )
                if mode == "chart_slow_btc" and request.query_params.get("symbol") == "BTCUSD":
                    await asyncio.sleep(1)
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
                if held_start is not None:
                    return JSONResponse(
                        {"detail": "Only one QA Start may be held"}, status_code=503
                    )
                held_start_event = asyncio.Event()
                held_start = {
                    "request_id": body["request_id"],
                    "expected_revision": body["expected_revision"],
                    "entered_at_ms": int(time.time() * 1000),
                    "status": "held",
                }
                held_start_entered.set()
                try:
                    await asyncio.wait_for(held_start_event.wait(), timeout=10)
                except TimeoutError:
                    held_start["status"] = "expired"
                    return JSONResponse(
                        {"detail": "Finite QA Start barrier expired before acknowledged Pause"},
                        status_code=503,
                    )
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
            if (
                body["action"] == "pause"
                and response.status_code == 200
                and saved is not None
                and saved.get("action") == "pause"
                and saved.get("applied") is True
                and held_start_event is not None
                and held_start is not None
                and held_start["status"] == "held"
            ):
                held_start.update(
                    status="released_after_acknowledged_pause",
                    pause_request_id=body["request_id"],
                    pause_revision=saved["revision"],
                    released_at_ms=int(time.time() * 1000),
                )
                held_start_event.set()
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

    @app.get("/__qa/held_start")
    async def held_start_identity(x_qa_token: str = Header()):
        authorize(x_qa_token)
        try:
            await asyncio.wait_for(held_start_entered.wait(), timeout=2)
        except TimeoutError as error:
            raise HTTPException(409, "No original QA Start entered its finite barrier") from error
        return {"held_start": held_start, "synthetic_fixture_only": True}

    @app.get("/__qa/probe")
    def probe(x_qa_token: str = Header()):
        authorize(x_qa_token)
        scanner = app.state.pattern_scanner
        with scanner.registry.lock:
            recognition_hashes = {}
            if args.chart_check:
                for table in ("pattern_levels", "pattern_events", "pattern_pages"):
                    for row in scanner.registry.db.execute(
                        f"SELECT campaign,body FROM {table} ORDER BY campaign,body"
                    ):
                        value = recognition_hashes.setdefault(row["campaign"], hashlib.sha256())
                        value.update(table.encode("ascii") + b"\0")
                        value.update(row["body"].encode("utf-8") + b"\0")
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
            "daily_check": args.daily_check,
            "synthetic_clock_offset_seconds": clock_offset,
            "financial_state_preserved_except_fixture_tick": financial_unchanged(),
            "source_hashes": hashes,
            "reads": reads,
            "setup_controls": setup_controls,
            "chart_setup": chart_setup,
            "held_start": held_start,
            "synthetic_lab_account_projection": args.chart_check,
            "saved_recognition_sha256": {
                campaign: value.hexdigest() for campaign, value in recognition_hashes.items()
            },
        }

    def fixture_control(scanner, action, campaign=None, symbols=None):
        command = {"action": action, "request_id": "qa-chart-" + str(len(setup_controls))}
        if action == "prepare":
            command["symbols"] = symbols
        else:
            command["campaign_id"] = campaign
            if action == "start":
                command["expected_revision"] = scanner.snapshot()["revision"]
        receipt = scanner.control(command)
        setup_controls.append({"command": command, "receipt": receipt})
        return receipt

    @app.post("/__qa/daily_advance")
    async def daily_advance(x_qa_token: str = Header()):
        authorize(x_qa_token)
        if not args.daily_check:
            raise HTTPException(409, "Explicit daily workflow required")
        scanner = app.state.pattern_scanner
        steps = 0
        started = time.monotonic()
        async with asyncio.timeout(12):
            for _ in range(120):
                tick()
                if not await scanner.step():
                    break
                steps += 1
                if time.monotonic() - started >= 5:
                    break
        result = {
            "synthetic_fixture_only": True,
            "steps": steps,
            "state": scanner.snapshot(),
            "native_requests": len(calls),
        }
        advances.append({"daily": True, "steps": steps, "native_requests": len(calls)})
        return result

    @app.post("/__qa/chart_setup")
    async def prepare_charts(x_qa_token: str = Header()):
        nonlocal chart_setup, mode
        authorize(x_qa_token)
        if not args.chart_check or chart_setup is not None:
            raise HTTPException(409, "One explicit isolated chart setup is required")
        chart_setup = {"status": "preparing", "synthetic_source": True}
        scanner = app.state.pattern_scanner
        mode = "normal"
        tick()
        prepared = fixture_control(scanner, "prepare", symbols=["BTCUSD", "ETHUSD"])
        campaign = prepared["campaign_id"]
        fixture_control(scanner, "start", campaign)
        steps = 0
        async with asyncio.timeout(40):
            for _ in range(1200):
                tick()
                await scanner.step()
                steps += 1
                progress = scanner.snapshot()["progress"]
                if len(progress) == 10 and all(row["observed_bars"] >= 260 for row in progress):
                    break
            else:
                raise ValueError("Finite chart setup did not observe all ten source scopes")
        fixture_control(scanner, "pause", campaign)
        chart_setup = {
            "status": "prepared",
            "campaign_id": campaign,
            "steps": steps,
            "progress": scanner.snapshot()["progress"],
            "full_year_complete": False,
            "synthetic_source": True,
            "native_fixture_page": {
                "requested_slots": 1000,
                "maximum_observed_candles": 360,
                "unobserved_slots_per_dense_request": 640,
                "full_requested_slice_observed": False,
            },
        }
        return chart_setup

    @app.post("/__qa/chart_alert_setup")
    async def prepare_alert_charts(x_qa_token: str = Header()):
        nonlocal chart_setup, mode, clock_offset, prospective_cutoff
        authorize(x_qa_token)
        if not args.chart_check or chart_setup is None or chart_setup.get("status") != "prepared":
            raise HTTPException(409, "Original chart fixture preparation is required")
        chart_setup["status"] = "preparing_alert"
        scanner = app.state.pattern_scanner
        clock_offset = 0
        prospective_cutoff = int(time.time() * 1000) // 14400000 * 14400000
        mode = "sparse_4h"
        tick()
        prepared = fixture_control(scanner, "prepare", symbols=["BTCUSD"])
        campaign = prepared["campaign_id"]
        fixture_control(scanner, "start", campaign)
        history_steps, alert_steps = 0, 0
        async with asyncio.timeout(25):
            for _ in range(600):
                tick()
                await scanner.step()
                history_steps += 1
                progress = scanner.snapshot()["progress"]
                if all(row["status"] == "monitoring" for row in progress):
                    break
            else:
                raise ValueError("Finite synthetic four-hour history did not complete")
        historical = scanner.snapshot()["progress"]
        mode = "future_4h"
        clock_offset = 14400
        tick()
        async with asyncio.timeout(25):
            for _ in range(600):
                await scanner.step()
                alert_steps += 1
                if scanner.page("alerts", campaign, "BTCUSD", "4h")["total"]:
                    break
            else:
                raise ValueError("Finite synthetic prospective observation produced no alert")
        fixture_control(scanner, "pause", campaign)
        mode = "normal"
        chart_setup.update(
            status="alert_prepared",
            alert_campaign_id=campaign,
            history_steps=history_steps,
            alert_steps=alert_steps,
            four_hour_history=historical,
            synthetic_clock_offset_seconds=clock_offset,
        )
        return chart_setup

    @app.post("/__qa/chart_advance_saved_scope")
    async def advance_saved_charts(x_qa_token: str = Header()):
        nonlocal mode
        authorize(x_qa_token)
        if (
            not args.chart_check
            or chart_setup is None
            or chart_setup.get("status") != "prepared"
            or "source_advance" in chart_setup
        ):
            raise HTTPException(409, "One original chart fixture advance is permitted")
        scanner = app.state.pattern_scanner
        campaign = chart_setup["campaign_id"]
        original_scope = next(
            row
            for row in scanner.snapshot()["progress"]
            if row["symbol"] == "BTCUSD" and row["timeframe"] == "5m"
        )
        chart_setup["source_advance"] = {"status": "advancing", "synthetic_source": True}
        mode = "normal"
        tick()
        fixture_control(scanner, "start", campaign)
        steps = 0
        async with asyncio.timeout(25):
            for _ in range(600):
                tick()
                await scanner.step()
                steps += 1
                current = next(
                    row
                    for row in scanner.snapshot()["progress"]
                    if row["symbol"] == "BTCUSD" and row["timeframe"] == "5m"
                )
                if current["observed_bars"] > original_scope["observed_bars"]:
                    break
            else:
                raise ValueError("Finite fixture advance did not reach original saved scope")
        fixture_control(scanner, "pause", campaign)
        result = {"status": "advanced", "steps": steps, "before": original_scope, "after": current}
        chart_setup["source_advance"] = result
        return result

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
        nonlocal daily_roster_changed, daily_roster_unavailable
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
        if action in {
            "daily_next_day",
            "daily_roster_change",
            "daily_unavailable",
            "daily_restore",
        }:
            if not args.daily_check:
                raise HTTPException(409, "Explicit daily workflow required")
            if action == "daily_next_day":
                current = time.time() + clock_offset
                clock_offset += (int(current // 86400) + 1) * 86400 - current + 1
            elif action == "daily_roster_change":
                daily_roster_changed = True
            else:
                daily_roster_unavailable = action == "daily_unavailable"
            tick()
            setup_controls.append(
                {
                    "action": action,
                    "synthetic_fixture_only": True,
                    "clock_offset_seconds": clock_offset,
                }
            )
            return {"synthetic_fixture_only": True, "state": app.state.pattern_scanner.snapshot()}
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
            "chart_frame_fail",
            "chart_slow_btc",
            "chart_window_fail",
        }:
            raise HTTPException(404)
        mode = action
        return {"fixture": mode}

    server.run()


if __name__ == "__main__":
    main()
