"""Actual isolated API/journal/storage with synthetic native candles; no financial DB or feed."""

import argparse
import asyncio
import copy
import hashlib
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import Header, HTTPException
from starlette.responses import JSONResponse

from trading.api import create_app
from trading.candle_history import INTERVALS
from trading.config import Settings
from trading.research_storage import save_plan


def main():
    if os.environ.get("QTRADES_TEST_DATABASE"):
        raise ValueError("This candle browser fixture has no financial database")
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--port", type=int, default=58968)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port in {8780, 5432, 54544}:
        raise ValueError("An isolated QA port is required")
    token = os.environ["QTRADES_BROWSER_QA_TOKEN"]
    args.directory.mkdir(parents=True, exist_ok=False)
    repository = Path(__file__).resolve().parents[2]
    source_names = [
        "src/trading/api.py",
        "src/trading/candle_history.py",
        "src/trading/candle_patterns.py",
        "src/trading/tool_journal.py",
        "src/trading/venue.py",
        "src/trading/station.py",
        "apps/web/src/CandleWorkspace.tsx",
        "apps/web/src/MarketStation.tsx",
        "apps/web/src/candle-workspace.css",
        "tests/browser/candle_patterns_server.py",
    ]
    source_hashes = {
        name: hashlib.sha256((repository / name).read_bytes()).hexdigest() for name in source_names
    }
    source_hashes["compiled/index.html"] = hashlib.sha256(
        (args.web_dist / "index.html").read_bytes()
    ).hexdigest()
    (args.directory / "source-manifest.json").write_text(
        json.dumps(source_hashes, indent=2), encoding="utf-8"
    )
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from conftest import book
    from test_candle_patterns import resistance_rows, support_rows
    from test_research_storage import plan_at
    from test_station import runtime

    from trading.venue import PublicVenue

    plan = plan_at(args.directory).model_copy(update={"temporary_bytes": 64 * 1024**2})
    save_plan(args.directory, plan)
    calls, posts = [], []
    mode = "normal"
    support_series = support_rows()
    series = [*support_series, *resistance_rows()]

    def native_response(request):
        if request.url.path != "/api/v3/klines":
            raise AssertionError("The fixture permits native candle retrieval only")
        query = request.url.params
        calls.append(dict(query))
        if mode == "fail":
            raise httpx.ReadError("Synthetic native candle source unavailable", request=request)
        step = INTERVALS[query["interval"]] * 1000
        start, end = int(query["startTime"]), int(query["endTime"])
        times = list(range(start, end + 1, step))[: int(query["limit"])]
        if mode == "gap":
            times = [at for at in times if at != start + step]
        if mode == "gap_warm":
            times = [at for at in times if at != start + 120 * step]
        if mode == "short":
            times = times[:9]
        rows = []
        for at in times:
            position = at // step
            if mode == "gap_warm":
                # Keep the reviewed terminal support visit after SMA100 warmup;
                # advancing wall time must not rotate this fixture precondition.
                position = at // step - end // step + len(support_series) - 1
            source = series[position % len(series)]
            rows.append(
                [
                    at,
                    str(source.open),
                    str(source.high),
                    str(source.low),
                    str(source.close),
                    str(source.volume),
                    at + step - 1,
                    "1000",
                    1,
                    "5",
                    "500",
                    "0",
                ]
            )
        return httpx.Response(200, json=rows)

    venue = PublicVenue(transport=httpx.MockTransport(native_response))
    paper = runtime.__wrapped__(args.directory, book.__wrapped__())
    original = copy.deepcopy(paper.state)
    app = create_app(
        Settings(),
        args.directory / "monitor.sqlite",
        background=False,
        venue=venue,
        web_dist=args.web_dist,
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )
    old_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with old_lifespan(application):
            application.state.paper = paper
            try:
                yield
            finally:
                (args.directory / "shutdown.json").write_text(
                    json.dumps(
                        {
                            "fixture": "synthetic_native_candles_actual_api_journal_storage",
                            "financial_database": False,
                            "model_calls": 0,
                            "financial_state_unchanged": paper.state == original,
                            "posts": posts,
                            "native_requests": calls,
                            "source_hashes": source_hashes,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def fixture(request, call_next):
        nonlocal mode
        if mode == "outage" and (
            request.url.path.startswith("/api/research/tools/runs/")
            or request.url.path.startswith("/api/research/candle-patterns/requests/")
        ):
            return JSONResponse({"detail": "Synthetic saved-receipt outage"}, status_code=503)
        if request.method == "POST" and request.url.path == "/api/research/candle-patterns":
            body = await request.json()
            selected_mode = mode
            app.state.last_tool_at = 0
            if selected_mode == "refuse":
                posts.append({"body": body, "fixture": selected_mode, "http_status": 429})
                return JSONResponse({"detail": "Synthetic pre-journal refusal"}, status_code=429)
            response = await call_next(request)
            saved = await asyncio.to_thread(app.state.tool_journal.find_request, body["request_id"])
            posts.append(
                {
                    "body": body,
                    "fixture": selected_mode,
                    "http_status": response.status_code,
                    "run_id": saved["id"] if saved else None,
                    "saved_status": saved["status"] if saved else None,
                }
            )
            if selected_mode == "late":
                await asyncio.sleep(2)
            if selected_mode == "lost_ack" and response.status_code == 200:
                return JSONResponse(
                    {"detail": "Synthetic lost acknowledgment after real saved receipt"},
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
        return {
            "evidence_kind": "synthetic_native_candles_actual_api_journal_storage",
            "posts": posts,
            "native_requests": calls,
            "runs": app.state.tool_journal.recent(),
            "financial_state_unchanged": paper.state == original,
            "financial_database": False,
            "model_calls": 0,
            "source_hashes": source_hashes,
        }

    @app.post("/__qa/{action}")
    def control(action: str, x_qa_token: str = Header()):
        nonlocal mode
        authorize(x_qa_token)
        if action == "stop":
            server.should_exit = True
            return {"stopping": True}
        if action not in {
            "normal",
            "gap",
            "gap_warm",
            "short",
            "fail",
            "late",
            "lost_ack",
            "refuse",
            "outage",
        }:
            raise HTTPException(404)
        mode = action
        return {"fixture": mode}

    server.run()


if __name__ == "__main__":
    main()
