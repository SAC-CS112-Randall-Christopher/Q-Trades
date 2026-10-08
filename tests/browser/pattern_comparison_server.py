"""Disposable actual API/preparation owners with synthetic native/current inputs."""

import argparse
import asyncio
import copy
import hashlib
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import uvicorn
from fastapi import Header, HTTPException
from starlette.responses import JSONResponse

from trading.api import create_app
from trading.config import Settings


def main():
    if os.environ.get("QTRADES_TEST_DATABASE"):
        raise ValueError("This disposable browser fixture has no financial database")
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--port", type=int, default=58974)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port in {8780, 5432, 54544}:
        raise ValueError("A separate disposable QA port is required")
    token = os.environ["QTRADES_BROWSER_QA_TOKEN"]
    args.directory.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[2]
    names = [
        "src/trading/api.py",
        "src/trading/pattern_comparisons.py",
        "src/trading/pattern_scanner.py",
        "src/trading/pattern_charts.py",
        "src/trading/candle_history.py",
        "src/trading/candle_patterns.py",
        "src/trading/autonomous_lab.py",
        "src/trading/autonomous_spec.py",
        "src/trading/redesign_strategy.py",
        "src/trading/rule_components.py",
        "src/trading/research_storage.py",
        "src/trading/research_evidence.py",
        "src/trading/experiment_registry.py",
        "tests/test_pattern_comparisons.py",
        "tests/test_pattern_scanner.py",
        "tests/test_daily_pattern_analyzer.py",
        "tests/browser/pattern_comparison_server.py",
        "tests/browser/pattern_comparison.cjs",
        "apps/web/src/PatternComparisonPanel.tsx",
        "apps/web/src/DailyAnalyzer.tsx",
        "apps/web/src/ScannerWorkspace.tsx",
        "apps/web/src/scanner-workspace.css",
        "apps/web/src/MarketStation.tsx",
        "apps/web/src/CandleWorkspace.tsx",
        "apps/web/src/useEvidenceRead.ts",
    ]

    def hashes():
        result = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in names}
        result.update(
            {
                "compiled/" + file.relative_to(args.web_dist).as_posix(): hashlib.sha256(
                    file.read_bytes()
                ).hexdigest()
                for file in args.web_dist.rglob("*")
                if file.is_file()
            }
        )
        return result

    before = hashes()
    (args.directory / "source-manifest.json").write_text(
        json.dumps(before, indent=2), encoding="utf-8"
    )
    sys.path.insert(0, str(repo / "tests"))
    from conftest import book
    from test_pattern_comparisons import build_fixture
    from test_station import runtime

    source_folder = args.directory / "source"
    source_folder.mkdir()
    monkeypatch = pytest.MonkeyPatch()
    f, bridge, selection = build_fixture(source_folder, monkeypatch)
    original = copy.deepcopy(f.paper.state)
    original_history = copy.deepcopy(f.paper.history)
    original_plan = f.scanner.plan
    auxiliary = args.directory / "dashboard"
    auxiliary.mkdir()
    paper = runtime.__wrapped__(auxiliary, book.__wrapped__())
    auxiliary_state = copy.deepcopy(paper.state)
    app = create_app(
        Settings(),
        args.directory / "monitor.sqlite",
        background=False,
        venue=f.venue,
        web_dist=args.web_dist,
        paper_database=None,
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )
    old_lifespan = app.router.lifespan_context
    mode = "normal"
    posts, reads = [], []
    delayed = None
    release = asyncio.Event()

    def probe():
        with f.registry.lock:
            retained = [
                dict(row)
                for row in f.registry.db.execute(
                    "SELECT request_id,intent_sha256,bundle_sha256 "
                    "FROM pattern_comparison_requests "
                    "ORDER BY request_id"
                )
            ]
            inbox_count = f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0]
        return {
            "fixture": "real_native_finding_and_current_lab_check_synthetic_inputs",
            "selection": selection.model_dump(),
            "campaign_id": f.campaign,
            "daily_snapshots": f.scanner.daily_pages(),
            "posts": posts,
            "reads": reads,
            "retained_preparations": retained,
            "delayed": delayed,
            "native_calls": f.calls,
            "financial_state_unchanged": f.paper.state == original,
            "auxiliary_dashboard_state_unchanged": paper.state == auxiliary_state,
            "lab_inbox_count": inbox_count,
            "model_calls": 0,
            "financial_database": False,
            "source_hashes": before,
            "source_hashes_after": hashes(),
        }

    @asynccontextmanager
    async def lifespan(application):
        async with old_lifespan(application):
            lab = application.state.lab
            old_registry, old_controller = lab.registry, lab.autonomous
            application.state.paper = paper
            application.state.pattern_scanner = f.scanner
            lab.pattern_scanner = f.scanner
            lab.registry, lab.autonomous = f.registry, bridge.controller
            try:
                yield
            finally:
                (args.directory / "shutdown.json").write_text(
                    json.dumps(probe(), indent=2), encoding="utf-8"
                )
                lab.registry, lab.autonomous = old_registry, old_controller

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def acknowledgment_fixture(request, call_next):
        nonlocal delayed
        route = request.url.path
        if route.startswith("/api/"):
            if len(reads) >= 1200:
                return JSONResponse({"detail": "Finite QA request bound"}, status_code=503)
            reads.append({"method": request.method, "path": route, "query": str(request.url.query)})
        if request.method != "POST" or route != "/api/research/pattern-scanner/comparisons":
            return await call_next(request)
        if len(posts) >= 12:
            return JSONResponse({"detail": "Finite QA preparation bound"}, status_code=503)
        command = await request.json()
        selected_mode = mode
        if selected_mode == "unknown":
            posts.append({"command": command, "mode": selected_mode, "saved": False, "status": 503})
            return JSONResponse(
                {"detail": "Synthetic unknown outcome without saved acknowledgment"},
                status_code=503,
            )
        response = await call_next(request)
        saved = await asyncio.to_thread(bridge.get, command["request_id"])
        posts.append(
            {
                "command": command,
                "mode": selected_mode,
                "saved": saved is not None,
                "actual_status": response.status_code,
            }
        )
        if selected_mode == "delay_ack" and response.status_code == 200:
            delayed = {"request_id": command["request_id"], "committed": saved is not None}
            release.clear()
            try:
                await asyncio.wait_for(release.wait(), timeout=12)
            except TimeoutError:
                return JSONResponse(
                    {"detail": "Synthetic delayed acknowledgment expired"}, status_code=503
                )
        if selected_mode == "lost_ack" and response.status_code == 200:
            return JSONResponse(
                {"detail": "Synthetic lost acknowledgment after real commit"}, status_code=503
            )
        if selected_mode == "corrupt_ack" and response.status_code == 200:
            corrupt = {**saved, "request_id": "different-original-identity"}
            return JSONResponse(corrupt)
        return response

    def authorize(value):
        if value != token:
            raise HTTPException(403, "Disposable QA token required")

    @app.get("/__qa/probe")
    def read_probe(x_qa_token: str = Header()):
        authorize(x_qa_token)
        return probe()

    @app.post("/__qa/{action}")
    async def qa_control(action: str, x_qa_token: str = Header()):
        nonlocal mode
        authorize(x_qa_token)
        if action == "stop":
            server.should_exit = True
            return {"stopping": True}
        if action == "release_ack":
            release.set()
            return {"released": True, "original": delayed}
        if action == "source_drift":
            f.scanner.plan = None
            f.paper.history.clear()
            app.state.lab.autonomous = None
            return {
                "synthetic_current_inputs_unavailable": True,
                "original_immutable_receipts_retained": True,
            }
        if action == "restore_source":
            f.scanner.plan = original_plan
            f.paper.history = copy.deepcopy(original_history)
            app.state.lab.autonomous = bridge.controller
            return {"restored_original_fixture_inputs": True}
        if action == "waiting_inputs":
            app.state.lab.autonomous = None
            return {"current_controller_unavailable": True, "original_findings_retained": True}
        if action in {"normal", "lost_ack", "corrupt_ack", "delay_ack", "unknown"}:
            mode = action
            return {"mode": mode}
        raise HTTPException(404, "Unknown disposable fixture control")

    try:
        server.run()
    finally:
        f.close()
        monkeypatch.undo()


if __name__ == "__main__":
    main()
