"""Actual compiled API/registry/UI with disposable paper SQL and a synthetic model.

The fake transport is explicit: this proves normal queue/status/recovery surfaces,
not trained-model inference, installed acceptance, strategy value or capacity.
"""

import argparse
import asyncio
import copy
import hashlib
import importlib
import json
import os
import sys
import threading
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

from trading import autonomous_finance as finance
from trading.api import create_app
from trading.autonomous_lab import AutonomousLab
from trading.autonomous_spec import LabPolicy
from trading.config import Settings
from trading.paper_engine import PaperEngine
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore, load_dsn
from trading.paper_strategy import Bar
from trading.role_worker import RoleWorker
from trading.venue import PublicVenue

ROOT = Path(__file__).resolve().parents[1]


class PilotUiFixture:
    paper_pilot = True

    def __init__(self, folder: Path) -> None:
        self.path = folder / "synthetic-pilot-policy.json"
        self.path.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "approved": True,
                    "grant_id": "synthetic-ui-grant",
                }
            ),
            encoding="utf-8",
        )
        self.protected = True
        self.calls: list[dict[str, Any]] = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def policy(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("approved") is not True:
            raise ValueError("Synthetic QA pilot grant revoked; saved history remains available")
        return value

    def can_research(self) -> bool:
        try:
            return bool(self.policy()["enabled"] and self.protected)
        except ValueError:
            return False

    def set_enabled(self, enabled: bool) -> None:
        value: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        if enabled:
            self.policy()
            if not self.protected:
                raise ValueError("Synthetic QA protected financial admission refused")
        value["enabled"] = enabled
        self.path.write_text(json.dumps(value), encoding="utf-8")
        if not enabled:
            self.release.set()

    def readiness(self) -> dict[str, Any]:
        try:
            value = self.policy()
            reason = None if value["enabled"] else "Paper research pilot paused; history retained"
            approved = True
        except ValueError as exc:
            reason, approved = str(exc), False
        return {
            "ready": self.can_research(),
            "qualified": False,
            "enabled": self.can_research(),
            **({"configured_enabled": value["enabled"]} if approved else {}),
            "qualification_valid": False,
            "model": "Synthetic pilot UI fixture (no model execution)",
            "reason": reason,
            "profile": {"purpose": "synthetic UI fixture", "qualified": False},
            "stages": {
                "policy": {
                    "state": "declared" if approved else "unavailable",
                    "next_action": "Synthetic QA prior grant" if approved else str(reason),
                },
                "runtime": {"state": "synthetic", "next_action": "No actual model is called"},
                "activation": {
                    "state": "enabled"
                    if self.can_research()
                    else "paused"
                    if approved
                    else "revoked",
                    "next_action": reason or "Use the bounded approved paper pilot",
                },
            },
        }

    def admit(self, role: str) -> dict[str, Any]:
        if not self.can_research():
            raise ValueError("Synthetic QA pilot protected admission refused")
        return {
            "timeout_seconds": 30,
            "hourly_wall_seconds": 120,
            "hourly_tokens": 65536,
            "token_allowance": 8192,
        }

    def infer(self, role: str, packet: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"role": role, "packet": copy.deepcopy(packet), "profile": profile})
        self.entered.set()
        if not self.release.wait(20):
            raise RuntimeError("Finite synthetic callback was not released")
        return {
            "complete": True,
            "answer": {
                "action": "request_data",
                "capability": None,
                "evidence_ids": ["e2"],
                "mechanism": "Observe another closed bar before comparing reviewed methods.",
                "falsification": "Reject benefit without a matched mature comparison.",
                "rationale": "This synthetic fixture has no mature evidence of strategy benefit.",
                "dependency": "new_closed_bars",
            },
            "scope": "Synthetic UI transport; no actual local model execution",
        }


def main() -> None:
    sys.path.insert(0, str(ROOT / "tests"))
    bars_at = cast(
        Callable[[float], list[Bar]], importlib.import_module("test_autonomous_lab").bars_at
    )
    frame = cast(
        Callable[[float], dict[str, Any]], importlib.import_module("test_paper_engine").frame
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--database-config", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=58978)
    args = parser.parse_args()
    folder = args.directory.resolve()
    if not folder.is_relative_to(Path("C:/Projects/outputs/qtrades-operating-pilot-66")):
        raise RuntimeError("Use the explicit task-owned pilot QA output directory")
    dsn = load_dsn(args.database_config)
    info = conninfo_to_dict(dsn)
    if info.get("host") != "127.0.0.1" or info.get("port") != "54544":
        raise RuntimeError("Only the verified dedicated disposable QA server is permitted")
    folder.mkdir(parents=True, exist_ok=False)
    token = uuid.uuid4().hex
    (folder / "access-token.txt").write_text(token, encoding="utf-8")
    schema = "test_pilot_ui_" + uuid.uuid4().hex
    admin = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    admin.execute("SET statement_timeout = '5s'")
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped = make_conninfo(dsn, options=f"-c search_path={schema}")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"No external QA venue operation: {request.url.path}")

    venue = PublicVenue(transport=httpx.MockTransport(refuse))
    app = create_app(
        Settings(),
        folder / "monitor.sqlite",
        ROOT / "apps/web/dist",
        background=False,
        venue=venue,
    )
    original = app.router.lifespan_context
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )
    transport = PilotUiFixture(folder)
    worker: RoleWorker | None = None
    store: PaperStore | None = None
    paper: PaperRuntime | None = None
    dispatch: asyncio.Task[bool] | None = None
    mode = "healthy"
    lost_ack = False
    writes: list[dict[str, Any]] = []
    baseline: dict[str, Any] = {}
    source_names = (
        "src/trading/api.py",
        "src/trading/role_worker.py",
        "src/trading/role_history.py",
        "src/trading/peft_role_model.py",
        "apps/web/src/RoleResearchPanel.tsx",
        "apps/web/src/ResearchQualityPanel.tsx",
        "scripts/preview_paper_pilot_ui.py",
    )
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_names}

    def save(name: str, value: Any) -> None:
        (folder / name).write_text(json.dumps(value, indent=2), encoding="utf-8")

    def authorize(request: Request) -> None:
        if request.headers.get("x-qa-token") != token:
            raise HTTPException(403, "Task-owned QA token required")

    def accounts_preserved() -> bool:
        assert store is not None
        return {
            name: {k: v for k, v in account.items() if k != "valuation_at"}
            for name, account in store.read()["accounts"].items()
        } == baseline

    @app.middleware("http")
    async def retain_posts(request: Request, call_next: Any) -> Any:
        nonlocal lost_ack
        entry = None
        if request.method == "POST" and request.url.path.startswith("/api/lab/roles/"):
            entry = {"path": request.url.path, "body": json.loads(await request.body())}
            writes.append(entry)
        response = await call_next(request)
        if entry is not None:
            entry["status"] = response.status_code
        if (
            lost_ack
            and request.url.path == "/api/lab/roles/control"
            and response.status_code == 200
        ):
            lost_ack = False
            return JSONResponse(
                {"detail": "Synthetic lost control acknowledgment after commit"}, 503
            )
        return response

    @app.post("/__qa/mode")
    async def set_mode(request: Request) -> dict[str, Any]:
        nonlocal mode, lost_ack, dispatch
        authorize(request)
        assert worker is not None and paper is not None
        value = (await request.json()).get("mode")
        if value == "dispatch":
            if dispatch is not None:
                raise HTTPException(409, "One synthetic callback only")
            dispatch = asyncio.create_task(worker.step())
        elif value == "release":
            transport.release.set()
            if dispatch is not None:
                await dispatch
        elif value == "lost_ack":
            lost_ack = True
        elif value == "revoked":
            transport.path.write_text(json.dumps({"enabled": False, "approved": False}))
            worker.enabled = False
            mode = value
        elif value in {"healthy", "protected", "stale"}:
            mode = value
            transport.protected = value != "protected"
            paper.error = "Synthetic QA stale paper feed" if value == "stale" else None
        else:
            raise HTTPException(422, "Unsupported bounded QA mode")
        return {"mode": mode}

    @app.get("/__qa/probe")
    def probe(request: Request) -> dict[str, Any]:
        authorize(request)
        assert worker is not None and worker.controller is not None and store is not None
        return {
            "scope": "Actual API/registry/SQL with synthetic transport and market fixture",
            "model_calls": 0,
            "synthetic_callbacks": len(transport.calls),
            "synthetic_callback_entered": transport.entered.is_set(),
            "roles": worker.page(),
            "writes": writes,
            "balance": store.reconcile(),
            "financial_accounts_preserved": accounts_preserved(),
            "shared_research_admission": worker.controller.can_research(),
            "attempts": [
                dict(r) for r in worker.registry.db.execute("SELECT * FROM role_attempts")
            ],
            "source_sha256": hashes,
        }

    @app.post("/__qa/shutdown")
    def shutdown(request: Request) -> dict[str, bool]:
        authorize(request)
        transport.release.set()
        server.should_exit = True
        return {"shutdown_requested": True}

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        nonlocal worker, paper, store, baseline
        store = PaperStore(scoped, owner=True)
        now = time.time()
        store.initialize(now)

        def prepare(engine: PaperEngine) -> None:
            engine.universe_experiment(["BTCUSD", "ETHUSD"])
            finance.start(engine, LabPolicy(request_id="synthetic-pilot-ui-policy"))
            engine.state.update(evidence_kind="synthetic_pilot_ui_fixture")
            engine.tick({"BTCUSD": frame(now)}, {})

        store.transact(now, prepare)
        paper = PaperRuntime(store, venue)
        paper.running = True
        paper.history = {"BTCUSD": bars_at(now)}
        paper.books = {"BTCUSD": frame(now)}
        baseline = {
            name: {k: copy.deepcopy(v) for k, v in account.items() if k != "valuation_at"}
            for name, account in store.read()["accounts"].items()
        }
        async with original(application):
            application.state.paper = paper
            lab = application.state.lab
            lab.autonomous = AutonomousLab(lab.registry, paper, lambda: False)
            worker = RoleWorker(lab.registry, lab.autonomous, transport)
            worker.activation = lambda: bool(transport.policy()["enabled"])
            worker.enabled = True
            worker.paper_admission = transport.can_research
            lab.roles = worker

            async def freshness() -> None:
                assert paper is not None
                deadline = time.monotonic() + 240
                while not server.should_exit and time.monotonic() < deadline:
                    if mode != "stale":
                        at = time.time()
                        paper.books = {"BTCUSD": frame(at)}
                        paper.history = {"BTCUSD": bars_at(at)}
                        with paper.store.transaction_lock:
                            paper._transact_state(at, lambda engine: engine.tick(paper.books, {}))
                    await asyncio.sleep(0.5)
                server.should_exit = True

            task = asyncio.create_task(freshness())
            save(
                "server-ready.json",
                {
                    "port": args.port,
                    "pid": os.getpid(),
                    "schema": schema,
                    "database_host": "127.0.0.1",
                    "database_port": "54544",
                    "model_calls": 0,
                    "source_sha256": hashes,
                    "compiled_index_sha256": hashlib.sha256(
                        (ROOT / "apps/web/dist/index.html").read_bytes()
                    ).hexdigest(),
                },
            )
            try:
                yield
            finally:
                transport.release.set()
                if dispatch is not None:
                    await dispatch
                save(
                    "source-final-receipt.json",
                    {
                        "balance": store.reconcile(),
                        "accounts_preserved": accounts_preserved(),
                        "writes": writes,
                        "roles": worker.page(),
                        "model_calls": 0,
                        "synthetic_callbacks": len(transport.calls),
                        "source_unchanged": all(
                            hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == h
                            for n, h in hashes.items()
                        ),
                    },
                )
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        store.close()

    app.router.lifespan_context = lifespan
    try:
        server.run()
    finally:
        assert schema.startswith("test_pilot_ui_") and len(schema) == 46
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()
        save("cleanup-receipt.json", {"schema": schema, "schema_dropped": True, "model_calls": 0})


if __name__ == "__main__":
    main()
