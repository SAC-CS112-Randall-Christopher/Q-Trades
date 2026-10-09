"""Real saved-pattern selector/task API with disposable synthetic native inputs."""

import argparse
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
        raise ValueError("Pattern evidence browser QA has no financial database")
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--port", type=int, default=58975)
    parser.add_argument("--audit-recovery", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port in {8780, 5432, 54544}:
        raise ValueError("A separate disposable QA port is required")
    token = os.environ["QTRADES_BROWSER_QA_TOKEN"]
    args.directory.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[2]
    names = [
        "src/trading/api.py",
        "src/trading/role_worker.py",
        "src/trading/role_history.py",
        "src/trading/role_evidence.py",
        "src/trading/lab_role_contract.py",
        "src/trading/local_role_model.py",
        "src/trading/peft_role_model.py",
        "src/trading/pattern_comparisons.py",
        "src/trading/pattern_scanner.py",
        "src/trading/pattern_charts.py",
        "src/trading/autonomous_lab.py",
        "src/trading/paper_learning.py",
        "src/trading/autonomous_spec.py",
        "src/trading/redesign_strategy.py",
        "src/trading/rule_components.py",
        "src/trading/research_storage.py",
        "src/trading/research_evidence.py",
        "src/trading/evidence_runtime.py",
        "src/trading/experiment_registry.py",
        "tests/test_pattern_role_worker.py",
        "tests/test_pattern_next_method_worker.py",
        "tests/test_pattern_comparisons.py",
        "tests/test_pattern_scanner.py",
        "tests/test_daily_pattern_analyzer.py",
        "tests/test_paper_pilot_worker.py",
        "tests/test_role_question_selection.py",
        "tests/test_station.py",
        "tests/conftest.py",
        "tests/test_research_storage.py",
        "tests/browser/role_pattern_evidence_server.py",
        "tests/browser/role_pattern_evidence.cjs",
        "tests/browser/completed_get.cjs",
        "apps/web/src/RoleResearchPanel.tsx",
        "apps/web/src/LearningPanel.tsx",
        "apps/web/src/PatternComparisonPanel.tsx",
        "apps/web/src/ScannerWorkspace.tsx",
        "apps/web/src/DailyAnalyzer.tsx",
        "apps/web/src/CandleWorkspace.tsx",
        "apps/web/src/MarketStation.tsx",
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
    from test_pattern_role_worker import build_pattern_worker_fixture
    from test_role_question_selection import SelectionFixture
    from test_station import runtime

    monkeypatch = pytest.MonkeyPatch()
    source = args.directory / "source"
    source.mkdir()
    f, worker, selection = build_pattern_worker_fixture(source, monkeypatch)
    if args.audit_recovery:
        from test_pattern_next_method_worker import MethodTransport

        worker.transport = MethodTransport()
        bars = f.paper.history["BTCUSD"]
        f.paper.history["BTCUSD"] = []
        assert worker.select_fresh_question(f.now) == 0
        f.paper.history["BTCUSD"] = bars
        f.now += 61
        f.paper.state["last_tick"] = f.now
    pattern_transport = worker.transport
    financial_before = copy.deepcopy(f.paper.state)
    assert worker.select_fresh_question(f.now) == 1
    with f.registry.lock:
        identities = f.registry.db.execute("SELECT id FROM role_tasks").fetchall()
    assert len(identities) == 1
    identity = identities[0]["id"]
    task = worker.view(identity)
    assert task["context"]["pattern_comparison"]["selection"] == selection.model_dump()
    original_preparation = worker.pattern_comparisons.get(
        task["context"]["pattern_comparison"]["preparation_request_id"]
    )
    assert original_preparation is not None
    auxiliary = args.directory / "dashboard"
    auxiliary.mkdir()
    paper = runtime.__wrapped__(auxiliary, book.__wrapped__())
    if args.audit_recovery:
        from trading.autonomous_spec import RuleSpec

        candidate = copy.deepcopy(paper.state["accounts"]["primary"])
        candidate.update(
            rule_spec=RuleSpec().model_dump(),
            campaign_id="autonomous-lab",
            lab_role="candidate",
            lab_trial="qa-synthetic-scored-rule",
            label="Synthetic rule QA",
        )
        paper.state["accounts"]["qa-rule"] = candidate
        paper.state["autonomous_lab"] = {
            "trials": {"qa-synthetic-scored-rule": {"score": {"outcome": "promising"}}}
        }
    dashboard_before = copy.deepcopy(paper.state)
    calls_before = copy.deepcopy(f.calls)
    reads, posts = [], []
    role_status_unavailable = False
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

    def probe():
        with f.registry.lock:
            attempts = [dict(row) for row in f.registry.db.execute("SELECT * FROM role_attempts")]
            inbox = f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0]
        return {
            "scope": (
                "Actual native scanner/preparation/selector with synthetic inputs; GET-only UI"
            ),
            "task_id": identity,
            "question": task["context"]["question"]["question"],
            "task": worker.view(identity),
            "original_preparation": original_preparation,
            "selection": selection.model_dump(),
            "reads": reads,
            "posts": posts,
            "attempts": attempts,
            "inbox_count": inbox,
            "financial_state_unchanged": f.paper.state == financial_before,
            "dashboard_state_unchanged": paper.state == dashboard_before,
            "native_calls_unchanged": f.calls == calls_before,
            "native_calls_at_ui_start": calls_before,
            "stub_inference_callbacks": len(worker.transport.calls),
            "current_contract": worker._contract_version(),
            "role_status_unavailable": role_status_unavailable,
            "financial_database": False,
            "audit_recovery": args.audit_recovery,
            "model_calls": 0,
            "source_hashes": before,
            "source_hashes_after": hashes(),
        }

    @asynccontextmanager
    async def lifespan(application):
        nonlocal calls_before
        async with old_lifespan(application):
            lab = application.state.lab
            old_registry, old_controller, old_roles = lab.registry, lab.autonomous, lab.roles
            application.state.paper = paper
            application.state.pattern_scanner = f.scanner
            lab.pattern_scanner = f.scanner
            lab.registry = f.registry
            lab.autonomous = worker.controller
            lab.roles = worker
            calls_before = copy.deepcopy(f.calls)
            try:
                yield
            finally:
                (args.directory / "shutdown.json").write_text(
                    json.dumps(probe(), indent=2), encoding="utf-8"
                )
                lab.registry, lab.autonomous, lab.roles = old_registry, old_controller, old_roles

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def read_only_fixture(request, call_next):
        if request.url.path.startswith("/api/"):
            if len(reads) >= 400:
                return JSONResponse({"detail": "Finite QA request bound"}, status_code=503)
            record = {
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
            }
            reads.append(record)
            if request.method != "GET":
                posts.append(record)
                return JSONResponse(
                    {"detail": "This fixture allows API reads only"}, status_code=403
                )
            if request.url.path in {
                "/api/research/activity",
                "/api/autonomous",
                "/api/autonomous/history",
            }:
                return JSONResponse(
                    {"detail": "Disposable GET-only pattern fixture has no financial store"},
                    status_code=503,
                )
            if request.url.path == "/api/lab/roles" and role_status_unavailable:
                return JSONResponse({"detail": "Synthetic role status outage"}, status_code=503)
        return await call_next(request)

    def authorize(value):
        if value != token:
            raise HTTPException(403, "Disposable QA token required")

    @app.get("/__qa/probe")
    def read_probe(x_qa_token: str = Header()):
        authorize(x_qa_token)
        return probe()

    @app.post("/__qa/stop")
    def stop(x_qa_token: str = Header()):
        authorize(x_qa_token)
        server.should_exit = True
        return {"stopping": True}

    @app.post("/__qa/profile/{kind}")
    def fixture_profile(kind: str, x_qa_token: str = Header()):
        authorize(x_qa_token)
        if kind == "legacy":
            worker.transport = SelectionFixture()
        elif kind == "pattern":
            worker.transport = pattern_transport
        else:
            raise HTTPException(404, "Unknown synthetic profile")
        return {"synthetic_profile_only": True, "current_contract": worker._contract_version()}

    @app.post("/__qa/role_status/{mode}")
    def fixture_role_status(mode: str, x_qa_token: str = Header()):
        nonlocal role_status_unavailable
        authorize(x_qa_token)
        if mode not in {"unavailable", "restore"}:
            raise HTTPException(404, "Unknown synthetic role status mode")
        role_status_unavailable = mode == "unavailable"
        return {"synthetic_status_only": True, "unavailable": role_status_unavailable}

    try:
        server.run()
    finally:
        f.close()
        monkeypatch.undo()


if __name__ == "__main__":
    main()
