"""Disposable real role archive/retry API; post-commit acknowledgment faults are synthetic."""

import argparse
import asyncio
import copy
import hashlib
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import uvicorn
from fastapi import Header, HTTPException
from starlette.responses import JSONResponse

from trading.api import create_app
from trading.autonomous_spec import LabPolicy, LabProposal, RuleSpec
from trading.config import Settings
from trading.evidence_runtime import EvidenceRecorder
from trading.experiment_registry import fingerprint
from trading.lab_role_contract import VERSION
from trading.research_storage import save_plan
from trading.role_worker import RoleWorker
from trading.venue import PublicVenue


def main():
    if os.environ.get("QTRADES_TEST_DATABASE"):
        raise ValueError("Archive browser QA has no financial database")
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--port", type=int, default=58973)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port in {8780, 5432, 54544}:
        raise ValueError("A separate QA port is required")
    token = os.environ["QTRADES_BROWSER_QA_TOKEN"]
    args.directory.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[2]
    names = [
        "src/trading/api.py",
        "src/trading/role_worker.py",
        "src/trading/role_history.py",
        "src/trading/evidence_runtime.py",
        "src/trading/research_storage.py",
        "apps/web/src/RoleResearchPanel.tsx",
        "tests/browser/role_archive_retry_server.py",
        "tests/browser/role_archive_retry.cjs",
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

    original_hashes = hashes()
    (args.directory / "source-manifest.json").write_text(
        json.dumps(original_hashes, indent=2), encoding="utf-8"
    )
    sys.path.insert(0, str(repo / "tests"))
    from conftest import book
    from test_research_storage import plan_at
    from test_station import runtime

    plan = plan_at(args.directory)
    save_plan(args.directory, plan)
    paper = runtime.__wrapped__(args.directory, book.__wrapped__())
    # The header's normal activity reader must observe absent financial ownership,
    # rather than an incomplete test double or a default database connection.
    paper.store.connection = SimpleNamespace(info=None)
    policy = LabPolicy(request_id="synthetic-archive-browser-policy").model_dump(mode="json")
    paper.state["autonomous_lab"] = {
        "policy": policy,
        "phase": "paused",
        "reason": "Disposable synthetic archive fixture; no autonomous dispatch",
        "next_action_at": None,
        "last_score_at": None,
    }
    original_financial = copy.deepcopy(paper.state)
    identities = {
        "success": "role-" + "a" * 32,
        "lost_ack": "role-" + "b" * 32,
        "delayed": "role-" + "c" * 32,
        "mismatch": "role-" + "d" * 32,
        "other": "role-" + "e" * 32,
    }
    labels = {key: "Synthetic archive " + key.replace("_", " ") for key in identities}
    labels["other"] = "Different selected synthetic question"
    mode = "normal"
    posts, reads = [], []
    entered, release = asyncio.Event(), asyncio.Event()
    held = None
    archived = None
    recorder = None
    initial_attempts = None
    initial_evaluations = {}

    def deny_venue(request):
        raise AssertionError("Archive QA must never dispatch a public venue request")

    app = create_app(
        Settings(),
        args.directory / "monitor.sqlite",
        background=False,
        venue=PublicVenue(transport=httpx.MockTransport(deny_venue)),
        web_dist=args.web_dist,
    )
    original_lifespan = app.router.lifespan_context
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )

    def attempt_rows():
        worker = app.state.lab.roles
        with worker.registry.lock:
            return [
                dict(row)
                for row in worker.registry.db.execute(
                    "SELECT * FROM role_attempts ORDER BY task,stage,attempt"
                )
            ]

    def probe():
        worker = app.state.lab.roles
        return {
            "fixture": "synthetic_failed_archive_tasks_real_api_registry_shared_recorder",
            "identities": identities,
            "labels": labels,
            "posts": posts,
            "reads": reads,
            "held": held,
            "archived": archived,
            "tasks": {key: worker.get(identity) for key, identity in identities.items()},
            "initial_attempts": initial_attempts,
            "attempts": attempt_rows(),
            "original_evaluations": initial_evaluations,
            "financial_state_unchanged": paper.state == original_financial,
            "financial_database": False,
            "model_calls": 0,
            "public_venue_calls": 0,
            "source_before": original_hashes,
            "source_after": hashes(),
        }

    @asynccontextmanager
    async def lifespan(application):
        nonlocal initial_attempts, recorder
        async with original_lifespan(application):
            recorder = EvidenceRecorder(args.directory / "research-evidence.sqlite")
            await recorder.flush()
            application.state.paper = paper
            controller = SimpleNamespace(paper=paper, can_research=lambda: True)
            worker = RoleWorker(
                application.state.lab.registry, controller, storage_owner=recorder.research_store
            )
            application.state.lab.roles = worker
            now = time.time()
            for index, (key, identity) in enumerate(identities.items()):
                context = {
                    "contract": VERSION,
                    "execution_mode": "qualified_roles",
                    "question": {"question": labels[key], "horizon": "short"},
                    "policy": policy,
                    "policy_sha256": fingerprint(policy),
                    "catalog": {},
                    "tool_evidence": {
                        "security": "BTCUSD",
                        "closed_bar_count": 1,
                        "observed_at": now,
                        "source_basis": "Synthetic saved archive fixture",
                        "features": {},
                    },
                }
                evaluation = {
                    "evaluated_at": now,
                    "inputs": [{"synthetic": True, "value": key}],
                    "feature": {"eligible": False, "reason": "Original synthetic input"},
                    "replay": "No financial replay or model dispatch",
                }
                initial_evaluations[key] = evaluation
                proposal = LabProposal(
                    request_id="synthetic-archive-" + key,
                    policy_id=policy["request_id"],
                    kind="independent",
                    strategy=RuleSpec(family="range_reversion"),
                    reference=RuleSpec(),
                    mechanism="Synthetic shared archive preservation",
                    question=labels[key],
                    evidence_bundle_sha256="0" * 64,
                ).model_dump(mode="json")
                with worker.registry.transaction():
                    worker.registry.db.execute(
                        "INSERT INTO role_tasks(id,created,updated,stage,status,context,"
                        "proposal,evaluation,reason) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            identity,
                            now + index / 100,
                            now,
                            "complete" if key == "other" else "archive_evaluation",
                            "done" if key == "other" else "failed",
                            json.dumps(context),
                            json.dumps(proposal),
                            json.dumps(evaluation),
                            "Synthetic retained archive failure",
                        ),
                    )
            with worker.registry.transaction():
                worker.registry.db.execute(
                    "INSERT INTO role_attempts(task,stage,attempt,started,finished,status,"
                    "profile,packet,response,reason,wall_reserved,tokens_reserved) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        identities["success"],
                        "idea",
                        1,
                        now - 2,
                        now - 1,
                        "answered",
                        '{"synthetic":true}',
                        '{"synthetic":true}',
                        '{"synthetic":true,"complete":true,"answer":"Retained fixture answer"}',
                        None,
                        1,
                        2,
                    ),
                )
            initial_attempts = attempt_rows()
            try:
                yield
            finally:
                release.set()
                (args.directory / "shutdown.json").write_text(
                    json.dumps(probe(), indent=2), encoding="utf-8"
                )
                recorder.close()

    app.router.lifespan_context = lifespan

    def authorize(value):
        if value != token:
            raise HTTPException(403, "Disposable QA token required")

    @app.middleware("http")
    async def acknowledgment_faults(request, call_next):
        nonlocal held
        if request.url.path.startswith("/api/lab/roles") and request.method == "GET":
            reads.append({"path": request.url.path, "query": request.url.query})
            if len(reads) > 200:
                return JSONResponse({"detail": "Finite QA read limit"}, status_code=503)
        if request.method != "POST":
            return await call_next(request)
        if request.url.path.startswith("/api/") and not request.url.path.endswith("/retry"):
            return JSONResponse(
                {"detail": "Only one explicit archive retry per fixture task"}, status_code=403
            )
        if not request.url.path.startswith("/api/lab/roles/tasks/"):
            return await call_next(request)
        if any(row["path"] == request.url.path for row in posts):
            return JSONResponse({"detail": "Repeated retry refused by QA fixture"}, status_code=409)
        selected_mode = mode
        response = await call_next(request)
        identity = request.url.path.split("/")[-2]
        posts.append(
            {
                "path": request.url.path,
                "task": identity,
                "mode": selected_mode,
                "local_operator_header": request.headers.get("x-local-operator"),
                "actual_http_status": response.status_code,
                "saved_task": app.state.lab.roles.get(identity),
            }
        )
        if selected_mode == "lost_ack":
            return JSONResponse(
                {"detail": "Synthetic post-commit acknowledgment unavailable"}, status_code=503
            )
        if selected_mode == "mismatch":
            return JSONResponse(app.state.lab.roles.view(identities["other"]))
        if selected_mode == "delayed":
            held = {"task": identity, "committed": response.status_code == 200, "released": False}
            entered.set()
            try:
                await asyncio.wait_for(release.wait(), 5)
            except TimeoutError:
                held["expired"] = True
                return JSONResponse({"detail": "Finite QA response latch expired"}, status_code=503)
            held["released"] = True
        return response

    @app.get("/__qa/probe")
    def observation(x_qa_token: str = Header()):
        authorize(x_qa_token)
        return probe()

    @app.get("/__qa/held")
    async def observe_held(x_qa_token: str = Header()):
        authorize(x_qa_token)
        await asyncio.wait_for(entered.wait(), 2)
        return held

    @app.post("/__qa/{action}")
    async def control(action: str, x_qa_token: str = Header()):
        nonlocal mode, archived
        authorize(x_qa_token)
        if action == "stop":
            release.set()
            server.should_exit = True
            return {"stopping": True}
        if action == "release":
            release.set()
            return {"released": True}
        if action == "archive_success":
            if archived is not None:
                raise HTTPException(409, "Only one archive-only step is permitted")
            worker = app.state.lab.roles
            assert await asyncio.wait_for(worker.step(time.time()), 5)
            task = worker.get(identities["success"])
            assert task["stage"] == "review" and task["status"] == "queued"
            with recorder.research_store(plan) as owner:
                retained = owner.reopen(task["evaluation"]["detail_reference"])
            assert retained["evaluation"] == initial_evaluations["success"]
            archived = {"task": task, "exact_original_evaluation": True}
            return archived
        if action not in {"normal", "lost_ack", "delayed", "mismatch"}:
            raise HTTPException(404)
        mode = action
        return {"mode": mode}

    server.run()


if __name__ == "__main__":
    main()
