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
from trading.autonomous_spec import LabProposal
from trading.config import Settings
from trading.pattern_comparisons import PatternComparisonCommand
from trading.research_storage import save_plan
from trading.role_worker import RoleWorker


def main():
    if os.environ.get("QTRADES_TEST_DATABASE"):
        raise ValueError("This disposable browser fixture has no financial database")
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--port", type=int, default=58974)
    parser.add_argument("--research-observation-check", action="store_true")
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
        "src/trading/role_worker.py",
        "src/trading/lab_role_contract.py",
        "src/trading/role_evidence.py",
        "tests/test_pattern_comparisons.py",
        "tests/test_pattern_next_method_comparison.py",
        "tests/test_pattern_next_method_worker.py",
        "tests/test_pattern_role_worker.py",
        "tests/test_pattern_research_learning.py",
        "tests/test_role_question_selection.py",
        "tests/test_pattern_scanner.py",
        "tests/test_daily_pattern_analyzer.py",
        "tests/browser/pattern_comparison_server.py",
        "tests/browser/pattern_comparison.cjs",
        "apps/web/src/PatternComparisonPanel.tsx",
        "apps/web/src/RoleResearchPanel.tsx",
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
    original_controller = bridge.controller
    original = copy.deepcopy(f.paper.state)
    original_history = copy.deepcopy(f.paper.history)
    original_plan = f.scanner.plan
    observation_setup = None
    observation_worker = None
    if args.research_observation_check:

        def preparation(number):
            return PatternComparisonCommand(
                **selection.model_dump(),
                request_id=f"10000000-0000-4000-8000-{number:012d}",
                expected_finding_sha256=bridge.describe(selection)["finding_sha256"],
            )

        normal = bridge.prepare(preparation(1), f.now)
        marker = original_controller.submit(LabProposal.model_validate(normal["proposal"]), f.now)
        assert marker["status"] == "evaluated"
        readonly = bridge.prepare(preparation(2), f.now, research_only=True)
        assert readonly["status"] == "research_only" and readonly["proposal"] is None
        f.paper.history["BTCUSD"] = f.paper.history["BTCUSD"][-20:]
        waiting = bridge.prepare(preparation(3), f.now, research_only=True)
        assert waiting["status"] == "waiting" and waiting["research_only"] is True
        f.paper.history = copy.deepcopy(original_history)
        from test_pattern_next_method_worker import MethodTransport
        from test_role_question_selection import causal_frame

        save_plan(source_folder, f.plan)
        f.paper.ready_at = f.now - 60
        f.paper._candle_errors = {}
        f.paper.state["last_tick"] = f.now
        f.paper.control_frames = lambda: {"BTCUSD": causal_frame(f.now, f.paper.history["BTCUSD"])}
        observation_worker = RoleWorker(
            f.registry,
            original_controller,
            MethodTransport(),
            f.scanner.storage_owner,
            pattern_comparisons=bridge,
        )
        observation_worker.enabled = True
        observation_worker.paper_admission = lambda: True
        assert observation_worker.select_fresh_question(f.now) == 1
        selected = f.registry.db.execute("SELECT id FROM role_tasks").fetchone()["id"]
        selected_task = observation_worker.view(selected)
        assert selected_task["context"]["pattern_method"]["method_id"] == "p1"
        assert set(selected_task["context"]["fixed_comparison"]) == {"p1"}
        assert not observation_worker.transport.calls
        observation_worker.enabled = False
        next_method = bridge.prepare(preparation(4), f.now, method_id="p1")
        next_marker = original_controller.submit(
            LabProposal.model_validate(next_method["proposal"]), f.now
        )
        assert next_marker["status"] == "evaluated"
        next_readonly = bridge.prepare(preparation(5), f.now, method_id="p1", research_only=True)
        assert next_readonly["status"] == "research_only"
        f.paper.history["BTCUSD"] = f.paper.history["BTCUSD"][-20:]
        next_waiting = bridge.prepare(preparation(6), f.now, method_id="p1", research_only=True)
        assert next_waiting["status"] == "waiting" and next_waiting["research_only"] is True
        f.paper.history = copy.deepcopy(original_history)
        next_ordinary_wait = bridge.prepare(preparation(7), f.now, method_id="p1")
        assert next_ordinary_wait["status"] == "waiting"
        observation_setup = {
            "ordinary_request_id": normal["request_id"],
            "research_request_id": readonly["request_id"],
            "waiting_request_id": waiting["request_id"],
            "next_method_request_id": next_method["request_id"],
            "next_research_request_id": next_readonly["request_id"],
            "next_waiting_request_id": next_waiting["request_id"],
            "next_ordinary_waiting_request_id": next_ordinary_wait["request_id"],
            "next_task_id": selected,
            "next_task_preparation_id": selected_task["context"]["pattern_comparison"][
                "preparation_request_id"
            ],
            "setup_inbox_markers": 2,
            "setup_preparations": 8,
            "setup_role_tasks": 1,
            "model_callbacks": 0,
        }
        original = copy.deepcopy(f.paper.state)
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
            role_tasks = f.registry.db.execute("SELECT count(*) FROM role_tasks").fetchone()[0]
            role_attempts = f.registry.db.execute("SELECT count(*) FROM role_attempts").fetchone()[
                0
            ]
            task_context_hashes = {
                row["id"]: hashlib.sha256(row["context"].encode()).hexdigest()
                for row in f.registry.db.execute("SELECT id,context FROM role_tasks")
            }
        lab = app.state.lab
        worker = lab.roles
        owner = worker.pattern_comparisons
        result = {
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
            "role_tasks": role_tasks,
            "role_attempts": role_attempts,
            "task_context_hashes": task_context_hashes,
            "stub_inference_callbacks": 0
            if worker.transport is None
            else len(worker.transport.calls),
            "comparison_owner": {
                "same_bridge": owner is bridge,
                "scanner_matches": owner.scanner is app.state.pattern_scanner,
                "registry_matches": owner.registry is lab.registry is worker.registry,
                "controller_matches": owner.controller is lab.autonomous is worker.controller,
                "worker_enabled": worker.enabled,
                "transport_configured": worker.transport is not None,
            },
            "financial_database": False,
            "source_hashes": before,
            "source_hashes_after": hashes(),
        }
        if observation_setup is not None:
            result["research_observation"] = observation_setup
        return result

    @asynccontextmanager
    async def lifespan(application):
        async with old_lifespan(application):
            lab = application.state.lab
            old_registry, old_controller = lab.registry, lab.autonomous
            old_worker, old_lab_scanner = lab.roles, lab.pattern_scanner
            old_paper, old_scanner = application.state.paper, application.state.pattern_scanner
            worker = observation_worker or RoleWorker(
                f.registry,
                original_controller,
                storage_owner=f.scanner.storage_owner,
                pattern_comparisons=bridge,
            )
            application.state.paper = paper
            application.state.pattern_scanner = f.scanner
            lab.pattern_scanner = f.scanner
            lab.registry, lab.autonomous = f.registry, original_controller
            lab.roles = worker
            try:
                yield
            finally:
                try:
                    (args.directory / "shutdown.json").write_text(
                        json.dumps(probe(), indent=2), encoding="utf-8"
                    )
                finally:
                    bridge.controller = original_controller
                    lab.registry, lab.autonomous = old_registry, old_controller
                    lab.roles, lab.pattern_scanner = old_worker, old_lab_scanner
                    application.state.paper, application.state.pattern_scanner = (
                        old_paper,
                        old_scanner,
                    )

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def acknowledgment_fixture(request, call_next):
        nonlocal delayed
        route = request.url.path
        if route.startswith("/api/"):
            if len(reads) >= 1200:
                return JSONResponse({"detail": "Finite QA request bound"}, status_code=503)
            reads.append({"method": request.method, "path": route, "query": str(request.url.query)})
            if args.research_observation_check and request.method != "GET":
                return JSONResponse({"detail": "Read-only observation fixture"}, status_code=405)
            if args.research_observation_check and route in {
                "/api/research/activity",
                "/api/autonomous",
                "/api/autonomous/history",
            }:
                return JSONResponse(
                    {"detail": "Disposable GET-only pattern fixture has no financial store"},
                    status_code=503,
                )
        if (
            args.research_observation_check
            and request.method == "GET"
            and route.startswith("/api/research/pattern-scanner/comparisons/")
            and mode in {"corrupt_method", "corrupt_method_sha"}
        ):
            saved = await asyncio.to_thread(bridge.get, route.rsplit("/", 1)[-1])
            if saved is not None and saved.get("method_id") == "p1":
                corrupt = copy.deepcopy(saved)
                if mode == "corrupt_method":
                    corrupt["method_id"] = corrupt["mapping"]["method_id"] = "p2"
                else:
                    corrupt["method_policy_sha256"] = "0" * 64
                    corrupt["mapping"]["method_policy_sha256"] = "0" * 64
                # Deliberately corrupted delivery; the real immutable bundle is untouched.
                return JSONResponse(corrupt)
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
            bridge.controller = app.state.lab.roles.controller = None
            return {
                "synthetic_current_inputs_unavailable": True,
                "original_immutable_receipts_retained": True,
            }
        if action == "restore_source":
            f.scanner.plan = original_plan
            f.paper.history = copy.deepcopy(original_history)
            bridge.controller = app.state.lab.roles.controller = original_controller
            app.state.lab.autonomous = original_controller
            return {"restored_original_fixture_inputs": True}
        if action == "waiting_inputs":
            app.state.lab.autonomous = None
            bridge.controller = app.state.lab.roles.controller = None
            return {"current_controller_unavailable": True, "original_findings_retained": True}
        if action in {
            "normal",
            "lost_ack",
            "corrupt_ack",
            "delay_ack",
            "unknown",
            "corrupt_method",
            "corrupt_method_sha",
        }:
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
