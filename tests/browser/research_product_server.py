"""Compiled product over native owners and owned PG, with explicit synthetic inputs.

No network acquisition, tokenizer, model, training or operating resources. The
finite background driver calls the real worker/controller; reads never tick it.
"""

import argparse
import asyncio
import copy
import hashlib
import json
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import psycopg
import pytest
import uvicorn
from fastapi import Header, HTTPException
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from starlette.responses import JSONResponse

from trading import autonomous_finance as finance
from trading.api import create_app
from trading.autonomous_lab import AutonomousLab
from trading.autonomous_spec import LabPolicy
from trading.config import Settings
from trading.engine_diagnostics import EngineWorkPressurePolicy
from trading.experiment_registry import ExperimentRegistry
from trading.financial_readback import FinancialReadback
from trading.local_role_model import LocalRoles, development_latency_observation
from trading.paper_store import load_dsn
from trading.pattern_comparisons import PatternComparisons
from trading.peft_role_model import PeftPaperPilotRoles, local_role_transport
from trading.research_notices import ResearchNotices
from trading.role_worker import RoleWorker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--database-config", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--port", type=int, default=58996)
    args = parser.parse_args()
    if args.port in {8780, 5432, 54544} or not 1024 <= args.port <= 65535:
        raise ValueError("Separate disposable QA port required")
    token = os.environ["QTRADES_BROWSER_QA_TOKEN"]
    dsn = load_dsn(args.database_config)
    address = conninfo_to_dict(dsn)
    if address.get("host") != "127.0.0.1" or address.get("port") != "54544":
        raise ValueError("Explicit task-owned loopback PostgreSQL required")
    args.directory.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "tests"))
    from test_autonomous_lab import bars_at, close_window
    from test_daily_pattern_analyzer import advance
    from test_development_latency_measurement import protected_status
    from test_pattern_next_method_worker import MethodTransport
    from test_pattern_role_worker import build_pattern_worker_fixture, publish_native_event
    from test_peft_development import declared
    from test_role_question_selection import causal_frame

    monkeypatch = pytest.MonkeyPatch()
    f, worker, _ = build_pattern_worker_fixture(args.directory / "source", monkeypatch)
    profile_root = args.directory / "profile"
    profile_root.mkdir()
    development, *_ = declared.__wrapped__(profile_root, monkeypatch)
    monkeypatch.setattr(
        LocalRoles,
        "development_latency_guard",
        lambda _: development_latency_observation(protected_status()),
    )
    worker.transport = LocalRoles(f.registry.path.parent)
    worker.enabled = False
    callback = MethodTransport()
    schema = "test_product_" + uuid.uuid4().hex
    admin = psycopg.connect(dsn, autocommit=True)
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    config = args.directory / "paper-database.json"
    config.write_text(json.dumps({"dsn": make_conninfo(dsn, options=f"-c search_path={schema}")}))
    app = create_app(
        Settings(),
        args.directory / "monitor.sqlite",
        background=False,
        venue=f.venue,
        web_dist=args.web_dist,
        paper_database=config,
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )
    state = {
        "driver_cycles": 0,
        "financial_ticks": 0,
        "errors": [],
        "hold": False,
        "inflight": False,
        "matured": False,
    }
    reads, posts = [], []
    mode, outage = "normal", False
    initial_records = []
    original_done, successor = None, None
    before_archive = None
    names = (
        [
            "src/trading/" + name
            for name in (
                "api.py",
                "research_overview.py",
                "role_worker.py",
                "role_history.py",
                "pattern_comparisons.py",
                "peft_role_model.py",
                "autonomous_lab.py",
                "autonomous_finance.py",
                "paper_engine.py",
                "paper_store.py",
                "paper_learning.py",
                "paper_runtime.py",
                "paper_challengers.py",
            )
        ]
        + [
            "apps/web/src/" + name
            for name in (
                "main.tsx",
                "ResearchOverview.tsx",
                "ResearchSetup.tsx",
                "ResearchConnection.tsx",
                "RetainedComparison.tsx",
                "RoleResearchPanel.tsx",
                "LearningPanel.tsx",
                "WorkspaceViews.tsx",
                "TradeHistory.tsx",
                "productNavigation.ts",
                "theme.css",
            )
        ]
        + ["tests/browser/research_product_server.py", "tests/browser/research_product.cjs"]
    )

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
    (args.directory / "source-manifest.json").write_text(json.dumps(before, indent=2))

    def attach_model():
        model = local_role_transport(f.registry.path.parent)
        if not isinstance(model, PeftPaperPilotRoles):
            raise ValueError("Reviewed paused configuration required before QA owner reload")
        # Keep native profile/admission/preflight and permanent attempt reservations.
        # Only the inference response is a labeled deterministic software callback.
        model.infer = callback.infer
        worker.transport = model
        worker.enabled = model.policy()["enabled"]

    def financial_tick():
        paper = app.state.paper
        paper.universe.metadata_at = paper.universe.scanned_at = f.now
        paper.history["BTCUSD"] = bars_at(f.now - 400 * 60)[-200:] + bars_at(f.now)
        paper.books = paper.control_frames()
        paper._transact_state(f.now, lambda engine: engine.tick(paper.books, {}))
        state["financial_ticks"] += 1
        # QA resource measurements are procedural, not model-coexistence evidence.
        pressure = EngineWorkPressurePolicy()
        now = time.monotonic()
        for offset in range(20):
            pressure.observe(20, now - (19 - offset) * 0.55)
        paper._work_pressure = pressure
        reader = FinancialReadback(paper.store)
        try:
            receipt = reader.sample(audit=True)
            paper._accept_financial_audit(receipt)
            paper._accept_financial_sample(receipt)
        finally:
            reader.close()

    async def drive():
        while state["driver_cycles"] < 1600:
            try:
                state["inflight"] = True
                if not state["hold"]:
                    f.now += 1
                    await worker._owned(financial_tick)
                    model = worker.transport
                    worker.enabled = (
                        isinstance(model, PeftPaperPilotRoles) and model.policy()["enabled"]
                    )
                    if worker.enabled:
                        await worker._maintain("followups", worker.select_followups)
                        await worker._maintain("questions", worker.select_fresh_question)
                        await worker._maintain("dispatch", worker.step, thread=False)
                        controller = worker.controller
                        recording = f.storage.snapshot() | {"receipt_at": f.now}
                        (f.registry.path.parent / "research-storage-status.json").write_text(
                            json.dumps(recording)
                        )
                        current = controller.paper.state["autonomous_lab"]
                        active = [t for t in current["trials"].values() if t["status"] == "active"]
                        if active or not state["matured"]:
                            await worker._owned(controller.step, f.now)
                            if not active and current.get("next_action_at", 0) > f.now:
                                f.now = current["next_action_at"]
                state["driver_cycles"] += 1
            except Exception as exc:
                state["errors"].append({"type": type(exc).__name__, "error": str(exc)[:2000]})
                state["hold"] = True
            finally:
                state["inflight"] = False
            await asyncio.sleep(0.5)
        state["errors"].append({"type": "FiniteDeadline", "error": "QA driver bound reached"})

    def probe():
        paper = app.state.paper
        records = paper.store.export(0, 10000)
        tasks = worker.page()["tasks"]
        return {
            "scope": "Native PG/role/scanner owners; synthetic inputs, clock, "
            "model callbacks and resource observations",
            "schema": schema,
            "profile_directory": str(development.directory),
            "state": state,
            "reads": reads,
            "posts": posts,
            "tasks": tasks,
            "trials": paper.state["autonomous_lab"]["trials"],
            "accounts": paper.state["accounts"],
            "original_done": original_done,
            "successor": successor,
            "before_archive": before_archive,
            "model_calls": 0,
            "tokenizer_calls": 0,
            "software_callbacks": len(callback.calls),
            "attempts": [dict(row) for row in f.registry.db.execute("SELECT * FROM role_attempts")],
            "prefix_preserved": not records["has_more"]
            and records["records"][: len(initial_records)] == initial_records,
            "balanced": paper.store.reconcile()["balanced"],
            "source_hashes_unchanged": hashes() == before,
        }

    old_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        nonlocal initial_records
        async with old_lifespan(application):
            paper, lab = application.state.paper, application.state.lab
            old_registry, old_controller, old_roles, old_notices = (
                lab.registry,
                lab.autonomous,
                lab.roles,
                lab.notices,
            )
            scanner_reads = f.paper
            paper.universe, paper.history = (
                scanner_reads.universe,
                copy.deepcopy(scanner_reads.history),
            )
            paper.control_frames = lambda: {"BTCUSD": causal_frame(f.now, paper.history["BTCUSD"])}
            paper.memory_book, paper.constrained = lambda symbol: None, lambda *args: False
            paper.ready_at, paper.disk_free = f.now - 60, 10 * 1024**3
            paper.running = True

            def setup(engine):
                engine.state["evidence_kind"] = "synthetic_qa_continuous"
                engine.universe_experiment(["BTCUSD", "ETHUSD"])
                finance.start(
                    engine,
                    LabPolicy(request_id="product-browser-policy", holding_horizons=("medium",)),
                )
                finance.control(engine, "pause_proposals")
                engine.tick(paper.control_frames(), {})

            paper._transact_state(f.now, setup)
            f.paper = f.scanner.paper = paper
            controller = AutonomousLab(f.registry, paper, lambda: True)
            worker.controller = controller
            worker.pattern_comparisons = PatternComparisons(f.scanner, controller)
            lab.registry, lab.autonomous, lab.roles = f.registry, controller, worker
            lab.notices = ResearchNotices(f.registry)
            lab.notice_error = None
            lab.pattern_scanner = application.state.pattern_scanner = f.scanner
            initial_records = copy.deepcopy(paper.store.export(0, 10000)["records"])
            task = asyncio.create_task(drive())
            try:
                yield
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                (args.directory / "shutdown.json").write_text(json.dumps(probe(), indent=2))
                lab.registry, lab.autonomous, lab.roles, lab.notices = (
                    old_registry,
                    old_controller,
                    old_roles,
                    old_notices,
                )

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def qa_receipts(request, call_next):
        nonlocal mode
        route = request.url.path
        if route.startswith("/api/"):
            reads.append({"method": request.method, "path": route, "query": str(request.url.query)})
            if len(reads) > 2000:
                return JSONResponse({"detail": "Finite QA request bound"}, status_code=503)
            if outage and route == "/api/research/overview":
                return JSONResponse(
                    {"detail": "Synthetic current-operation outage"}, status_code=503
                )
            if request.method == "POST":
                fixture = mode
                mode = "normal"
                if fixture == "refuse":
                    posts.append({"path": route, "fixture": fixture, "status": 409})
                    return JSONResponse(
                        {"detail": "Synthetic precommit refusal; no write"}, status_code=409
                    )
                response = await call_next(request)
                posts.append(
                    {"path": route, "fixture": fixture, "actual_status": response.status_code}
                )
                if fixture == "lost_ack" and response.status_code == 200:
                    return JSONResponse(
                        {"detail": "Synthetic acknowledgment lost after native commit"},
                        status_code=503,
                    )
                return response
        return await call_next(request)

    def authorize(value):
        if value != token:
            raise HTTPException(403, "Owned disposable QA token required")

    async def pause_driver():
        state["hold"] = True
        for _ in range(1000):
            if not state["inflight"]:
                return
            await asyncio.sleep(0.02)
        raise HTTPException(503, "Owned QA driver did not drain within its bound")

    @app.get("/__qa/probe")
    def read_probe(x_qa_token: str = Header()):
        authorize(x_qa_token)
        return probe()

    @app.post("/__qa/{action}")
    async def control(action: str, x_qa_token: str = Header()):
        nonlocal mode, outage, original_done, successor, before_archive, worker
        authorize(x_qa_token)
        if action in {"normal", "refuse", "lost_ack"}:
            mode = action
        elif action in {"outage", "restore"}:
            outage = action == "outage"
        elif action == "restart-model":
            attach_model()
        elif action == "mature":
            await pause_driver()
            active = [
                t
                for t in app.state.paper.state["autonomous_lab"]["trials"].values()
                if t["status"] == "active"
            ]
            if len(active) != 1:
                raise HTTPException(409, "Exactly one native comparison required")
            score = await asyncio.to_thread(
                close_window, worker.controller, active[0], "low_information"
            )
            f.now = score["available_at"] + 2
            state["matured"] = True
            state["hold"] = False
        elif action == "archive-restart-successor":
            await pause_driver()
            done = [row for row in worker.page()["tasks"] if row["status"] == "done"]
            if len(done) != 1:
                raise HTTPException(409, "One original completed investigation required")
            original_done = worker.get(done[0]["id"])
            # A completed answer still has an app-owned lesson-selection handoff.
            # Drain it through its owner before selecting independent later work.
            await asyncio.to_thread(worker.select_followups)
            advance(f, 86400 + 600)
            await asyncio.to_thread(financial_tick)
            await asyncio.to_thread(publish_native_event, f)
            assert worker.select_fresh_question(f.now) == 1
            successor = max(worker.page()["tasks"], key=lambda row: row["created"])["id"]
            before_archive = copy.deepcopy(worker.get(successor))
            monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
            worker.history.rollover()
            path = f.registry.path
            f.registry.close()
            f.registry = ExperimentRegistry(path)
            f.scanner.registry = f.registry
            controller = AutonomousLab(f.registry, app.state.paper, lambda: True)
            bridge = PatternComparisons(f.scanner, controller)
            worker = RoleWorker(
                f.registry,
                controller,
                worker.transport,
                f.scanner.storage_owner,
                pattern_comparisons=bridge,
            )
            worker.paper_admission, worker.enabled = lambda: True, True
            app.state.lab.registry, app.state.lab.roles, app.state.lab.autonomous = (
                f.registry,
                worker,
                controller,
            )
            app.state.lab.notices = ResearchNotices(f.registry)
            assert worker.get(original_done["id"])["result"] == original_done["result"]
            assert worker.get(original_done["id"])["archive_reference"]
            assert worker.get(successor)["context"] == before_archive["context"]
            await worker.step(f.now)
            state["hold"] = False
        elif action == "stop":
            server.should_exit = True
        else:
            raise HTTPException(404, "Unknown owned QA action")
        return {"action": action, "synthetic_qa_only": True}

    try:
        server.run()
    finally:
        f.close()
        monkeypatch.undo()
        assert schema.startswith("test_product_") and len(schema) == 45
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


if __name__ == "__main__":
    main()
