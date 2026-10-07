"""Loopback operator API and compiled dashboard. No order routes exist."""

import asyncio
import hashlib
import json
import re
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg.conninfo import make_conninfo
from pydantic import BaseModel, ConfigDict, Field

from trading.autonomous_spec import LabControl, LabPolicy, LabProposal, OperatorLaunch
from trading.compact_memory import compact_evidence
from trading.config import Settings
from trading.evidence_runtime import feature_reproduction
from trading.experiment_lab import ExperimentLab
from trading.experiment_registry import ExperimentPlan
from trading.knowledge_acquisition import URLImport, acquire
from trading.model_trials import ModelTrials
from trading.options_runtime import OptionsRuntime
from trading.options_store import OptionsStore
from trading.ownership import CollectorLock
from trading.paper_campaigns import CampaignSpec
from trading.paper_engine import LEGACY_POLICY, policy
from trading.paper_store import PaperStore, load_dsn
from trading.peft_role_model import PeftPaperPilotRoles, local_role_transport
from trading.prospective_review import ProspectiveSpec
from trading.replay_lab import ReplayLab, ReplayPlan
from trading.research_actors import ActorAnswer, ActorClaim, ActorGrant, ActorTask, ResearchActors
from trading.research_campaigns import ResearchCampaignSpec
from trading.research_evidence import evidence_page, evidence_record
from trading.research_knowledge import (
    DocumentImport,
    KnowledgeDisposition,
    KnowledgeQuery,
    ResearchKnowledge,
    SourceImport,
)
from trading.research_mcp import PROTOCOLS, LocalMCPClient, ResearchMCP
from trading.research_notices import operational_conditions
from trading.research_quality import quality_report
from trading.research_reviews import (
    ResearchReviews,
    ReviewDecision,
    ReviewerPolicy,
    ReviewReconcile,
)
from trading.research_storage import (
    ResearchStorage,
    StoragePlan,
    compact_path,
    load_plan,
    reopen_evidence,
    save_plan,
    storage_snapshot,
    volume,
)
from trading.reviewer_provider import ResponsesReviewer
from trading.role_worker import Question, RoleWorker
from trading.runtime import Monitor
from trading.scoped_tools import disclose, outcome_page, reader
from trading.scoped_tools import run as scoped_tool
from trading.station import HISTORICAL_TOOLS, TOOLS, market_detail, market_live
from trading.stock_research import StockQuestion, StockResearch
from trading.storage import MonitorStore
from trading.tiered_runtime import TieredPaperRuntime as PaperRuntime
from trading.tool_journal import ToolJournal
from trading.training_workflow import (
    DatasetSelection,
    Retirement,
    ReviewSave,
    SourceSelection,
    TrainingWorkflow,
)
from trading.venue import PublicVenue


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["pause", "resume"]


class NoticePresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(max_length=64)
    action: Literal["acknowledge", "snooze", "clear_presentation"]
    seconds: Literal[0, 300, 900] = 0


class RiskControl(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["adopt_hard_stop", "resume_hard_stop"]
    stop_id: int = Field(default=0, ge=0)


class EconomicsControl(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    execution_profile: str = Field(min_length=1, max_length=80)
    operating_daily_usd: str | None = Field(default=None, pattern=r"^\d{1,5}(\.\d{1,6})?$")
    expected_version: int = Field(ge=0)


class AccountControl(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["pause", "resume", "recover"]
    expected_version: int = Field(ge=0)


class DiagnosticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{12,64}$")


class DiagnosticStart(DiagnosticRequest):
    seed: int = Field(ge=0, le=2**32 - 1)
    max_actions: int = Field(default=1000, ge=1, le=1000)
    duration_seconds: int = Field(default=600, ge=1, le=600)


class ForwardAdmission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    family: Literal["slow_trend", "volatility_breakout", "range_reversion", "memory_entry"]
    arm: Literal["B", "C"] | None = None
    starting_cash: Literal["50", "100"]
    operating_daily_usd: str | None = Field(default=None, pattern=r"^\d{1,4}(\.\d{1,6})?$")


class LearningReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{12,48}$")
    candidate: str = Field(pattern=r"^forward-[a-z0-9]{24}$")


class LearningRole(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["designate", "rollback"]
    expected_version: int = Field(ge=0)
    report_id: str = Field(default="", max_length=48)
    report_sha256: str = Field(default="", max_length=64)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool: str = Field(min_length=1, max_length=64)
    symbol: str = Field(min_length=3, max_length=24, pattern=r"^[A-Z0-9]+$")
    account: str = Field(
        default="primary", min_length=1, max_length=96, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    request_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9-]{12,64}$")
    start: float = Field(default=0, ge=0, allow_inf_nan=False)


def create_app(
    settings: Settings,
    database: Path,
    web_dist: Path | None = None,
    *,
    background: bool = True,
    venue: PublicVenue | None = None,
    paper_database: Path | None = None,
    research_evidence: Path | None = None,
) -> FastAPI:
    code_commit: str | None
    try:
        marker = database.parent / "installed-commit.txt"
        code_commit = marker.read_text().strip() if marker.stat().st_size <= 48 else ""
        code_commit = code_commit if re.fullmatch(r"[0-9a-f]{40}", code_commit) else None
    except (OSError, UnicodeError):
        code_commit = None
    model_trials = ModelTrials(
        research_evidence
        if research_evidence is not None
        else Path(__file__).resolve().parents[2] / "docs/evidence"
    )
    from trading.research_activity import ResearchActivity

    activity_view = ResearchActivity(database.parent)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ownership = CollectorLock(database.with_suffix(".collector.lock"))
        ownership.acquire()
        try:
            store = MonitorStore(database, settings.retained_observations)
            public_venue = venue or PublicVenue(settings.request_timeout_seconds)
            task = None
            paper_task = None
            options_task = None
            options_store = None
            paper_store = None
            paper_venue = None
            tool_journal = None
            lab = None
            lab_task = None
            role_task = None
            replay_lab = None
            replay_task = None
            review_task = None
            knowledge_storage = None
            try:
                app.state.tool_busy = False
                app.state.last_tool_at = 0.0
                app.state.tool_error = None
                try:
                    tool_journal = ToolJournal(
                        database.parent / "research-tools.sqlite3", load_plan(database.parent)
                    )
                except (sqlite3.Error, OSError, ValueError):
                    app.state.tool_error = (
                        "Tool receipt storage unavailable; paper operation continues"
                    )
                app.state.tool_journal = tool_journal
                store.set("config:" + settings.fingerprint, settings.model_dump())
                app.state.monitor = Monitor(settings, store, public_venue)
                task = asyncio.create_task(app.state.monitor.run()) if background else None
                app.state.paper = None
                app.state.options = None
                app.state.options_error = None
                if paper_database is not None:
                    paper_store = PaperStore(load_dsn(paper_database), owner=True)
                    paper_store.initialize(time.time())
                    if not paper_store.reconcile()["balanced"]:
                        raise RuntimeError("Paper journal reconciliation failed at startup")
                    paper_venue = PublicVenue(3)
                    app.state.paper = PaperRuntime(
                        paper_store, paper_venue, database.parent / "paper-stream.sqlite"
                    )
                    paper_task = asyncio.create_task(app.state.paper.run()) if background else None
                    # Fresh CP1 experiments are spot-only. Existing options history stays
                    # under its original policy; no migration or new account is implied.
                    legacy = policy(paper_store.read()["accounts"]["primary"]) == LEGACY_POLICY
                    existing_options = paper_store.connection.execute(
                        "SELECT to_regclass('options_paper.paper_state') AS relation"
                    ).fetchone()
                    if legacy or (existing_options and existing_options["relation"]):
                        try:
                            options_store = OptionsStore(load_dsn(paper_database))
                            options_store.initialize(time.time())
                            if not options_store.reconcile()["balanced"]:
                                raise RuntimeError("Options journal reconciliation failed")
                            app.state.options = OptionsRuntime(options_store)
                            options_task = (
                                asyncio.create_task(app.state.options.run()) if background else None
                            )
                        except Exception:
                            app.state.options_error = (
                                "Options account needs attention; spot trading continues"
                            )

                def research_ready() -> bool:
                    paper = app.state.paper
                    return bool(
                        paper
                        and paper.running
                        and not paper.error
                        and time.time() - paper.state["last_tick"] < 10
                        and not paper.constrained()
                    )

                try:
                    lab = ExperimentLab(
                        database.parent / "experiments.sqlite3",
                        load_dsn(paper_database) if paper_database else None,
                        research_ready,
                    )
                except (sqlite3.Error, OSError):
                    app.state.lab_error = "Research storage unavailable; paper management continues"
                app.state.lab = lab
                app.state.knowledge = None
                app.state.manual_review_task = None
                app.state.reviews = None
                app.state.research_mcp = None
                app.state.knowledge_error = "Configure the existing owned research storage first"
                if lab:
                    lab.notice_source = lambda: operational_conditions(app.state.paper, time.time())

                    def research_universe() -> dict[str, Any]:
                        paper = app.state.paper
                        universe = getattr(paper, "universe", None)
                        if universe is None:
                            return {"status": "unavailable"}
                        value: dict[str, Any] = json.loads(
                            json.dumps(universe.snapshot(), default=str)
                        )
                        value["captured_at"] = time.time()
                        value["held_pending"] = sorted(
                            {
                                symbol
                                for a in paper.state["accounts"].values()
                                for symbol in set(a["positions"]) | set(a["pending"])
                            }
                        )
                        value["source"] = "Current observed universe; no historical substitution"
                        return value

                    lab.market_snapshot = research_universe
                    if app.state.paper is not None:
                        from trading.autonomous_lab import AutonomousLab

                        def operator_setup_admission(exception: bool) -> dict[str, Any]:
                            result = dict(app.state.paper.operator_launch_admission(exception))
                            for name, active in (
                                ("replay_worker_active", bool(replay_lab and replay_lab.busy)),
                                ("numerical_worker_active", bool(lab and lab.child is not None)),
                            ):
                                if active:
                                    result["admitted"] = False
                                    result["blocking_conditions"] = [
                                        *result["blocking_conditions"],
                                        name,
                                    ]
                                    result["raw_blocking_conditions"] = [
                                        *result["raw_blocking_conditions"],
                                        name,
                                    ]
                            return result

                        lab.autonomous = AutonomousLab(
                            lab.registry,
                            app.state.paper,
                            lambda: lab.can_research(),
                            operator_setup_admission,
                        )
                    local_roles = local_role_transport(database.parent)
                    lab.roles = RoleWorker(lab.registry, lab.autonomous, local_roles)
                    lab.roles.activation = lambda: bool(local_roles.policy().get("enabled", False))
                    if isinstance(local_roles, PeftPaperPilotRoles):
                        lab.roles.paper_admission = local_roles.can_research
                    plan = load_plan(database.parent)
                    if plan is not None:
                        try:
                            knowledge_storage = ResearchStorage(plan)
                            knowledge = ResearchKnowledge(knowledge_storage)
                            reviews = ResearchReviews(lab.roles, knowledge)
                            research_actors = ResearchActors(lab.roles)
                            reviews.transport = ResponsesReviewer(
                                database.parent, research_actors, app
                            )
                            lab.roles.knowledge = knowledge
                            lab.roles.reviews = reviews
                            app.state.knowledge, app.state.reviews = knowledge, reviews
                            app.state.research_mcp = ResearchMCP(research_actors, reviews)
                            app.state.knowledge_error = None
                            review_task = asyncio.create_task(reviews.run()) if background else None
                        except (OSError, ValueError, sqlite3.Error):
                            app.state.knowledge_error = (
                                "Knowledge storage unavailable; inspect owned volume/quota/index"
                            )
                    role_task = asyncio.create_task(lab.roles.run()) if background else None
                lab_task = asyncio.create_task(lab.run()) if background and lab else None
                app.state.replay = None
                try:
                    replay_lab = ReplayLab(
                        database.parent / "execution-replay.sqlite",
                        database.parent / "research-evidence.sqlite",
                        lambda: research_ready() and not (lab and lab.child),
                    )
                    app.state.replay = replay_lab
                    if lab:
                        lab.can_research = lambda: (
                            research_ready() and not (replay_lab and replay_lab.busy)
                        )
                    replay_task = asyncio.create_task(replay_lab.run()) if background else None
                except (sqlite3.Error, OSError):
                    app.state.replay_error = (
                        "Replay storage unavailable; paper management continues"
                    )
                yield
            finally:
                if review_task:
                    review_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await review_task
                if knowledge_storage:
                    manual_review = app.state.manual_review_task
                    if manual_review and not manual_review.done():
                        manual_review.cancel()
                        with suppress(asyncio.CancelledError):
                            await manual_review
                    knowledge_storage.close()
                if role_task:
                    role_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await role_task
                if replay_task:
                    replay_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await replay_task
                if replay_lab:
                    replay_lab.registry.close()
                if lab_task:
                    lab_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await lab_task
                if lab:
                    lab.registry.close()
                if tool_journal:
                    tool_journal.close()
                if options_task:
                    options_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await options_task
                if options_store:
                    options_store.close()
                if paper_task:
                    paper_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await paper_task
                if paper_venue:
                    await paper_venue.close()
                if paper_store:
                    paper_store.close()
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                await public_venue.close()
                store.close()
        finally:
            ownership.release()

    app = FastAPI(title="Trading Research Â· Public Monitor", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )

    @app.middleware("http")
    async def local_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(sqlite3.Error)
    async def storage_failure(request: Request, exc: sqlite3.Error) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "Observation storage is unavailable. "
                    "Check disk space and restart the local service."
                )
            },
        )

    @app.get("/api/status")
    async def status(request: Request) -> dict[str, Any]:
        monitor: Monitor = request.app.state.monitor
        snapshot = monitor.snapshot()
        paper: PaperRuntime | None = request.app.state.paper
        snapshot["paper"] = paper.snapshot() if paper else {"enabled": False}
        options: OptionsRuntime | None = request.app.state.options
        snapshot["options"] = (
            options.snapshot()
            if options
            else {
                "enabled": False,
                "error": request.app.state.options_error,
            }
        )
        if paper:
            snapshot["execution"]["paper_available"] = True
            for market in snapshot["markets"]:
                market["entry_reason"] = "Monitor only; see separate Tier 3 paper engine status"
        return snapshot

    @app.get("/api/paper/quotes")
    async def paper_quotes(request: Request) -> dict[str, Any]:
        paper: PaperRuntime | None = request.app.state.paper
        return paper.quotes() if paper else {"enabled": False, "markets": []}

    @app.get("/api/readiness")
    def live_readiness(request: Request) -> JSONResponse:
        from trading.live_readiness import packet

        paper: PaperRuntime | None = request.app.state.paper
        return JSONResponse(
            packet(paper.state if paper else None), headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/research/trials")
    def research_trials() -> dict[str, Any]:
        # Runs in FastAPI's worker pool, outside the trading event loop.
        return model_trials.snapshot()

    @app.get("/api/research/activity")
    def research_activity(request: Request) -> dict[str, Any]:
        paper = request.app.state.paper
        info = paper.store.connection.info if paper else None
        dsn = make_conninfo(info.dsn, password=info.password, connect_timeout=3) if info else None
        return activity_view.snapshot(dsn, paper, request.app.state.lab)

    @app.get("/api/research/storage")
    def research_storage_status() -> dict[str, Any]:
        return storage_snapshot(database.parent)

    @app.get("/api/research/notices")
    def research_notices(request: Request) -> dict[str, Any]:
        lab = request.app.state.lab
        if lab is None:
            raise HTTPException(503, "Research notice registry unavailable")
        result = lab.notices.snapshot(time.time())
        result["detector_error"] = lab.notice_error
        return dict(result)

    @app.get("/api/research/notices/{key}")
    def research_notice_detail(request: Request, key: str) -> dict[str, Any]:
        lab = request.app.state.lab
        if lab is None:
            raise HTTPException(503, "Research notice registry unavailable")
        if len(key) > 64:
            raise HTTPException(400, "Notice key exceeds its bound")
        try:
            return dict(lab.notices.detail(key))
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/research/notices/presentation")
    def notice_presentation(request: Request, command: NoticePresentation) -> dict[str, Any]:
        lab = lab_operator(request)
        try:
            return dict(
                lab.notices.present(command.key, command.action, time.time(), command.seconds)
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/research/storage/target")
    def research_storage_target(
        root: str = Query(r"G:\Projects\Q-Trades-Data", max_length=300),
    ) -> dict[str, Any]:
        try:
            return volume(Path(root))
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/research/storage/plan")
    def research_storage_plan(request: Request, plan: StoragePlan) -> dict[str, Any]:
        lab_operator(request)
        try:
            save_plan(database.parent, plan)
            return {
                "state": "declared",
                "plan": plan.model_dump(),
                "activation": (
                    "Worker startup reads the frozen plan; no automatic restart o"
                    "r historical relocation"
                ),
            }
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/research/storage/evidence")
    def research_storage_evidence(reference: str = Query(max_length=160)) -> dict[str, Any]:
        try:
            plan = load_plan(database.parent)
            if plan is None:
                raise ValueError("External research storage is not configured")
            packet = reopen_evidence(plan, reference)
            return {
                "reference": reference,
                "payload": packet,
                "reproduction": feature_reproduction(packet),
            }
        except (ValueError, OSError, LookupError, sqlite3.Error) as exc:
            raise HTTPException(409, str(exc)) from exc

    def lab_operator(request: Request) -> ExperimentLab:
        origin = request.headers.get("origin")
        if request.headers.get("x-local-operator") != "1" or (
            origin
            and (
                urlsplit(origin).scheme != "http"
                or urlsplit(origin).netloc != request.headers.get("host")
            )
        ):
            raise HTTPException(403, "Local operator request required")
        lab: ExperimentLab | None = request.app.state.lab
        if lab is None:
            raise HTTPException(503, "Research registry unavailable; paper management continues")
        return lab

    @app.middleware("http")
    async def bounded_training_input(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method == "POST" and (
            request.url.path.startswith("/api/lab/training/")
            or request.url.path.startswith("/api/research/knowledge/")
            or request.url.path.startswith("/api/research/reviews/")
            or request.url.path == "/api/research/mcp"
        ):
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 262144:
                    return JSONResponse(
                        {"detail": "Training request exceeds 256 KiB; nothing was saved"},
                        status_code=413,
                        headers={"Cache-Control": "no-store"},
                    )
                chunks.append(chunk)
            # Starlette's cached request supplies these bounded bytes to the JSON validator.
            request._body = b"".join(chunks)
        return await call_next(request)

    @app.middleware("http")
    async def scoped_actor_route(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # A narrow future transport must preserve this credential and allowlist.
        # A bearer credential never authorizes operator/dashboard/financial APIs.
        if request.headers.get("authorization", "").startswith("Bearer ") and not (
            request.url.path.startswith("/api/research/actors/tasks/")
            or request.url.path.startswith("/api/research/actors/claims/")
            or request.url.path == "/api/research/actors/answers"
            or request.url.path == "/api/research/mcp"
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Research credential cannot access operator or unrelated routes"
                },
            )
        return await call_next(request)

    def actors(request: Request) -> ResearchActors:
        lab = request.app.state.lab
        if lab is None or lab.roles is None:
            raise HTTPException(503, "Scoped research registry unavailable")
        return ResearchActors(lab.roles)

    def actor_token(request: Request) -> str:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise HTTPException(403, "Scoped research bearer credential required")
        return authorization[7:]

    def knowledge_owner(request: Request) -> ResearchKnowledge:
        owner = request.app.state.knowledge
        if owner is None:
            raise HTTPException(503, request.app.state.knowledge_error)
        return owner  # type: ignore[no-any-return]

    @app.exception_handler(RequestValidationError)
    async def private_validation(request: Request, exc: RequestValidationError) -> Response:
        if request.url.path.startswith(("/api/research/knowledge", "/api/research/reviews")):
            return JSONResponse(
                {"detail": "Research input is invalid; check the declared fields"}, status_code=422
            )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def optional_storage_failure(request: Request, exc: Exception) -> Response:
        if request.url.path.startswith(
            ("/api/research/knowledge", "/api/research/reviews", "/api/research/mcp")
        ):
            return JSONResponse(
                {
                    "detail": "Research storage/dependency unavailable; "
                    "inspect owned volume, quota or index and retry"
                },
                status_code=503,
            )
        raise exc

    def review_owner(request: Request) -> ResearchReviews:
        owner = request.app.state.reviews
        if owner is None:
            raise HTTPException(503, request.app.state.knowledge_error)
        return owner  # type: ignore[no-any-return]

    @app.get("/api/research/knowledge")
    def knowledge_list(
        request: Request, before: str = Query(default="", max_length=64)
    ) -> dict[str, Any]:
        return knowledge_owner(request).list(before)

    @app.post("/api/research/knowledge/import")
    def knowledge_import(request: Request, source: SourceImport) -> dict[str, Any]:
        lab_operator(request)
        try:
            return knowledge_owner(request).ingest(source)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/research/knowledge/search")
    def knowledge_search(request: Request, query: KnowledgeQuery) -> dict[str, Any]:
        lab_operator(request)
        try:
            return knowledge_owner(request).retrieve(query)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/research/knowledge/document")
    def knowledge_document(request: Request, document: DocumentImport) -> dict[str, Any]:
        lab_operator(request)
        try:
            return knowledge_owner(request).ingest_document(document)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/research/knowledge/acquire")
    def knowledge_acquire(request: Request, command: URLImport) -> dict[str, object]:
        lab_operator(request)
        try:
            return acquire(knowledge_owner(request), command)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/research/knowledge/sources/{source}/{revision}")
    def knowledge_source(request: Request, source: str, revision: int) -> dict[str, Any]:
        try:
            return knowledge_owner(request).read(
                source, revision, cutoff=time.time(), operator=True
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/research/knowledge/sources/{source}/disposition")
    def knowledge_disposition(
        request: Request, source: str, decision: KnowledgeDisposition
    ) -> dict[str, Any]:
        lab_operator(request)
        try:
            return knowledge_owner(request).disposition(source, decision)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/research/knowledge/sources/{source}/{revision}/document")
    def knowledge_original_document(request: Request, source: str, revision: int) -> Response:
        try:
            raw = knowledge_owner(request).document(source, revision)
            return Response(
                raw,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": 'attachment; filename="knowledge-source.pdf"',
                    "X-Content-Type-Options": "nosniff",
                    "Content-Security-Policy": "sandbox",
                },
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/research/knowledge/receipts/{identity}")
    def knowledge_receipt(request: Request, identity: str) -> dict[str, Any]:
        try:
            return knowledge_owner(request).receipt(identity)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/research/knowledge/reindex")
    def knowledge_reindex(request: Request) -> dict[str, Any]:
        lab_operator(request)
        return knowledge_owner(request).reindex()

    @app.post("/api/research/knowledge/backup")
    def knowledge_backup(request: Request) -> dict[str, Any]:
        lab_operator(request)
        return knowledge_owner(request).backup()

    class KnowledgeRestore(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        backup: str = Field(pattern=r"^knowledge-backup-\d{10,24}\.sqlite$")
        sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @app.post("/api/research/knowledge/restore")
    def knowledge_restore(request: Request, command: KnowledgeRestore) -> dict[str, Any]:
        lab_operator(request)
        try:
            return knowledge_owner(request).restore(command.backup, command.sha256)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/research/knowledge/restored/{library}/{source}/{revision}")
    def knowledge_restored(
        request: Request, library: str, source: str, revision: int
    ) -> dict[str, Any]:
        owner = knowledge_owner(request)
        try:
            if (
                not re.fullmatch(r"knowledge-restore-\d{10,24}\.sqlite", library)
                or not (owner.storage.research / library).is_file()
            ):
                raise ValueError("Owned restored snapshot unavailable")
            return ResearchKnowledge(owner.storage, name=library).read(
                source, revision, cutoff=time.time(), operator=True
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/research/reviews")
    def review_status(request: Request, before: str | None = None) -> dict[str, Any]:
        try:
            return review_owner(request).snapshot(before)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/research/reviews/connection-test")
    async def review_connection_test(request: Request) -> dict[str, Any]:
        lab_operator(request)
        owner = review_owner(request)
        with owner.registry.lock:
            row = owner.registry.db.execute(
                "SELECT id,task FROM scheduled_reviews ORDER BY created DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise HTTPException(409, "Await a retained review packet to test scoped discovery/read")
        actors = request.app.state.research_mcp.actors
        grant = actors.grant(
            ActorGrant(
                actor="operator-scoped-connection-test",
                tasks=[row["task"]],
                lifetime_seconds=60,
                requests=4,
                output_bytes=131072,
                processing_location="App-local connection test; no external provider request",
            )
        )
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=request.app),
                base_url="http://localhost",
                timeout=8,
                trust_env=False,
                follow_redirects=False,
            ) as local:
                client = LocalMCPClient(local, grant["token"])
                await client.initialize()
                discovered = await client.rpc("tools/list", {})
                await client.call("review_get_packet", {"review": row["id"]})
            return {
                "status": "passed",
                "tools": [t["name"] for t in discovered["tools"]],
                "scope": "App-local authenticated discovery and permitted frozen-packet read",
                "provider": "External model/tunnel/account access remains unqualified",
                "credential": "Temporary claim revoked; no API credential used or returned",
            }
        except (ValueError, httpx.HTTPError):
            raise HTTPException(
                409, "Scoped connection refused; inspect current source permissions"
            ) from None
        finally:
            actors.revoke(grant["id"])

    @app.get("/api/research/reviews/results/{identity}")
    def review_result(request: Request, identity: str) -> dict[str, Any]:
        try:
            owner = review_owner(request)
            return owner.get(identity) | {"delivered_knowledge": owner.delivered_passages(identity)}
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    class ReviewerConfiguration(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        expected_revision: int = Field(ge=0)
        policy: ReviewerPolicy

    @app.post("/api/research/reviews/configure")
    def review_configure(request: Request, config: ReviewerConfiguration) -> dict[str, Any]:
        lab_operator(request)
        try:
            return review_owner(request).configure(config.policy, config.expected_revision)
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/research/reviews/pause")
    def review_pause(request: Request) -> dict[str, Any]:
        lab_operator(request)
        return review_owner(request).pause()

    @app.post("/api/research/reviews/run")
    async def review_run(request: Request) -> dict[str, Any]:
        lab_operator(request)
        owner = review_owner(request)
        pending = request.app.state.manual_review_task
        if pending is None or pending.done():
            request.app.state.manual_review_task = asyncio.create_task(owner.once())
        return review_owner(request).snapshot()

    @app.post("/api/research/reviews/results/{identity}/decision")
    def review_decision(
        request: Request, identity: str, decision: ReviewDecision
    ) -> dict[str, Any]:
        lab_operator(request)
        try:
            return review_owner(request).decide(identity, decision)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/research/reviews/results/{identity}/reconcile")
    def review_reconcile(
        request: Request, identity: str, command: ReviewReconcile
    ) -> dict[str, Any]:
        lab_operator(request)
        try:
            return review_owner(request).reconcile(identity, command)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/research/reviews/credential")
    async def review_credential(request: Request) -> dict[str, Any]:
        lab_operator(request)
        # No Pydantic validation echo containing a secret; no renderer persistence.
        try:
            body = await request.json()
            if (
                not isinstance(body, dict)
                or set(body) != {"credential"}
                or not isinstance(body["credential"], str)
            ):
                raise ValueError("Invalid credential request")
            review_owner(request).transport.credential.save(body["credential"])
        except (ValueError, OSError):
            raise HTTPException(
                409, "Protected credential was not saved; repair local setup"
            ) from None
        return {"saved": True, "protection": "Current Windows user; no secret returned"}

    @app.post("/api/research/reviews/disconnect")
    def review_disconnect(request: Request) -> dict[str, Any]:
        lab_operator(request)
        owner = review_owner(request)
        owner.pause()
        owner.transport.credential.revoke()
        return owner.snapshot()

    @app.post("/api/research/mcp")
    async def research_mcp(request: Request) -> Response:
        origin = request.headers.get("origin")
        if origin and origin != "http://" + request.headers.get("host", ""):
            raise HTTPException(403, "MCP origin is outside the local trust boundary")
        if request.headers.get("mcp-protocol-version", "2025-03-26") not in PROTOCOLS:
            raise HTTPException(400, "Unsupported MCP protocol version")
        if not all(
            t in request.headers.get("accept", "")
            for t in ("application/json", "text/event-stream")
        ):
            raise HTTPException(406, "MCP client must accept JSON and event stream")
        adapter = request.app.state.research_mcp
        if adapter is None:
            raise HTTPException(503, "Research MCP unavailable; local paper operation continues")
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("One JSON-RPC object required")
            result = await asyncio.to_thread(adapter.rpc, actor_token(request), body)
            return JSONResponse(result) if result is not None else Response(status_code=202)
        except ValueError:
            raise HTTPException(
                403, "Research MCP request outside permitted scope or allowance"
            ) from None

    @app.get("/api/research/mcp")
    def research_mcp_stream() -> Response:
        return Response(status_code=405)  # Stateless JSON; no SSE/unsolicited notifications.

    @app.get("/api/research/actors/grants")
    def actor_grants(request: Request) -> dict[str, Any]:
        lab_operator(request)
        return actors(request).snapshot()

    @app.post("/api/research/actors/grants")
    def actor_grant(request: Request, grant: ActorGrant) -> dict[str, Any]:
        lab_operator(request)
        try:
            return actors(request).grant(grant)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/research/actors/grants/{identity}/revoke")
    def actor_revoke(request: Request, identity: str) -> dict[str, str]:
        lab_operator(request)
        try:
            actors(request).revoke(identity)
            return {
                "status": "revoked",
                "effect": "Completed receipts, paper positions and history preserved",
            }
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/research/actors/tasks/claim")
    def actor_claim(request: Request, command: ActorTask) -> dict[str, Any]:
        try:
            return actors(request).claim(actor_token(request), command.task)
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/research/actors/claims/renew")
    def actor_renew(request: Request, command: ActorClaim) -> dict[str, Any]:
        try:
            return actors(request).renew(actor_token(request), command.claim)
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/research/actors/claims/release")
    def actor_release(request: Request, command: ActorClaim) -> dict[str, str]:
        try:
            actors(request).release(actor_token(request), command.claim)
            return {
                "status": "released",
                "next": "Unknown completion retained; one explicit local retry allowed",
            }
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/research/actors/answers")
    def actor_answer(request: Request, command: ActorAnswer) -> dict[str, Any]:
        try:
            return actors(request).answer(actor_token(request), command)
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.get("/api/research/actors/tasks/{identity}/result")
    def actor_result(request: Request, identity: str) -> dict[str, Any]:
        try:
            return actors(request).result(actor_token(request), identity)
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.get("/api/research/actors/tasks/maintenance")
    def actor_maintenance(request: Request) -> dict[str, Any]:
        try:
            return actors(request).maintenance(actor_token(request))
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.get("/api/lab")
    def research_lab(request: Request, before: int = Query(0, ge=0)) -> dict[str, Any]:
        lab: ExperimentLab | None = request.app.state.lab
        if lab is None:
            raise HTTPException(503, "Research registry unavailable; paper management continues")
        return lab.snapshot(before)

    def autonomous(request: Request) -> Any:
        lab = request.app.state.lab
        if lab is None or lab.autonomous is None:
            raise HTTPException(503, "Autonomous lab requires the paper service and registry")
        return lab.autonomous

    @app.get("/api/lab/roles")
    def role_status(
        request: Request,
        before: float = Query(0, ge=0, allow_inf_nan=False),
        before_id: str = Query("", max_length=100),
        search: str = Query("", max_length=100),
    ) -> dict[str, Any]:
        lab = request.app.state.lab
        if lab is None or lab.roles is None:
            raise HTTPException(503, "Local role registry unavailable; paper management continues")
        return dict(lab.roles.page(before, before_id, search))

    @app.post("/api/lab/roles/questions")
    def role_question(request: Request, question: Question) -> dict[str, Any]:
        lab = lab_operator(request)
        try:
            identity = lab.roles.enqueue(question)["id"]
        except ValueError as exc:
            receipt = lab.roles.reject(question, str(exc))
            raise HTTPException(503 if receipt["outcome"] == "created" else 409, receipt) from exc
        try:
            return dict(lab.roles.view(identity))
        except (ValueError, OSError, LookupError) as exc:
            # A detail/disclosure failure after commit is a positive creation receipt.
            # Never tell the form this already-saved intent was rejected.
            receipt = lab.roles.reject(
                question, "Question saved; detail is temporarily unavailable"
            )
            raise HTTPException(503, receipt) from exc

    @app.post("/api/lab/roles/control")
    def role_pilot_control(request: Request, control: Control) -> dict[str, Any]:
        lab = lab_operator(request)
        roles = lab.roles
        if roles is None:
            raise HTTPException(503, "Local role registry unavailable")
        transport = roles.transport
        if getattr(transport, "paper_pilot", False) is not True:
            raise HTTPException(409, "An existing approved paper pilot is required")
        try:
            transport.set_enabled(control.action == "resume")
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                503, "Pilot control acknowledgment unavailable; refresh its current status"
            ) from exc
        try:
            return dict(roles.page())
        except (OSError, sqlite3.Error, LookupError) as exc:
            raise HTTPException(
                503, "Pilot control saved; current status unavailable. Refresh before retrying"
            ) from exc

    @app.get("/api/lab/roles/tasks/{identity}")
    def role_detail(request: Request, identity: str) -> dict[str, Any]:
        lab = request.app.state.lab
        if lab is None or lab.roles is None:
            raise HTTPException(503, "Local role registry unavailable")
        try:
            return dict(lab.roles.view(identity))
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/lab/roles/tasks/{identity}/training-candidate")
    def role_training_candidate(
        request: Request,
        identity: str,
        stage: str = Query(pattern="^(idea|review|followup)$"),
        attempt: int = Query(ge=1, le=100),
    ) -> JSONResponse:
        lab = lab_operator(request)
        if lab.roles is None:
            raise HTTPException(503, "Local role registry unavailable")
        try:
            result = lab.roles.training_candidate(identity, stage, attempt)
            return JSONResponse(
                result,
                headers={
                    "Cache-Control": "no-store",
                    "Content-Disposition": 'attachment; filename="qtrades-training-candidate.json"',
                    "X-Content-Type-Options": "nosniff",
                },
            )
        except (ValueError, OSError, LookupError) as exc:
            raise HTTPException(
                409,
                "Selected original attempt cannot be exported; "
                "it remains retained. Reopen its details and retry.",
            ) from exc

    def training(request: Request) -> TrainingWorkflow:
        lab = lab_operator(request)
        return TrainingWorkflow(lab.registry, lab.roles, request.app.state.monitor.store)

    def teaching_error(exc: Exception) -> HTTPException:
        return HTTPException(409, str(exc)[:1000])

    @app.get("/api/lab/training")
    def teaching_sources(request: Request) -> JSONResponse:
        return JSONResponse(training(request).sources(), headers={"Cache-Control": "no-store"})

    @app.post("/api/lab/training/candidates")
    def teaching_select(request: Request, source: SourceSelection) -> dict[str, Any]:
        try:
            return training(request).select(source)
        except (ValueError, OSError, LookupError) as exc:
            raise teaching_error(exc) from exc

    @app.get("/api/lab/training/examples/{identity}")
    def teaching_detail(
        request: Request, identity: str, revision: int | None = Query(None, ge=1)
    ) -> JSONResponse:
        try:
            return JSONResponse(
                training(request).detail(identity, revision), headers={"Cache-Control": "no-store"}
            )
        except (ValueError, OSError, LookupError) as exc:
            raise teaching_error(exc) from exc

    @app.post("/api/lab/training/examples/{identity}/review")
    def teaching_save(request: Request, identity: str, body: ReviewSave) -> dict[str, Any]:
        try:
            return training(request).save(identity, body)
        except (ValueError, OSError, LookupError) as exc:
            raise teaching_error(exc) from exc

    @app.post("/api/lab/training/preflight")
    def teaching_preflight(request: Request, body: DatasetSelection) -> dict[str, Any]:
        try:
            return training(request).preflight(body)
        except (ValueError, OSError, LookupError) as exc:
            raise teaching_error(exc) from exc

    @app.post("/api/lab/training/prepare")
    def teaching_prepare(request: Request, body: DatasetSelection) -> dict[str, Any]:
        try:
            return training(request).build(body)
        except (ValueError, OSError, LookupError) as exc:
            raise teaching_error(exc) from exc

    @app.get("/api/lab/training/results/{identity}")
    def teaching_result(request: Request, identity: str) -> JSONResponse:
        try:
            return JSONResponse(
                training(request).result(identity), headers={"Cache-Control": "no-store"}
            )
        except (ValueError, OSError, LookupError) as exc:
            raise teaching_error(exc) from exc

    @app.post("/api/lab/training/results/{identity}/retry")
    def teaching_retry(request: Request, identity: str) -> dict[str, Any]:
        try:
            return training(request).retry(identity)
        except (ValueError, OSError, LookupError) as exc:
            raise teaching_error(exc) from exc

    @app.post("/api/lab/training/retire-evaluation")
    def teaching_retire(request: Request, body: Retirement) -> dict[str, Any]:
        try:
            return training(request).retire(body)
        except (ValueError, OSError, LookupError) as exc:
            raise teaching_error(exc) from exc

    @app.get("/api/lab/training/historical/{identity}")
    def teaching_comparison(request: Request, identity: str) -> JSONResponse:
        try:
            return JSONResponse(
                training(request).comparison(identity), headers={"Cache-Control": "no-store"}
            )
        except (ValueError, OSError, LookupError) as exc:
            raise teaching_error(exc) from exc

    @app.post("/api/lab/roles/tasks/{identity}/retry")
    def role_retry(request: Request, identity: str) -> dict[str, Any]:
        lab = lab_operator(request)
        try:
            return dict(lab.roles.retry(identity))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/lab/roles/tasks/{identity}/components/{capability}")
    def role_component_detail(
        request: Request, identity: str, capability: str, offset: int = Query(0, ge=0, le=128)
    ) -> dict[str, Any]:
        lab = request.app.state.lab
        if lab is None or lab.roles is None:
            raise HTTPException(503, "Local role registry unavailable")
        try:
            return dict(lab.roles.component_detail(identity, capability, offset))
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/research/lessons")
    def lesson_search(
        request: Request,
        before: int = Query(0, ge=0),
        text: str = "",
        family: str = "",
        parent: str = "",
        horizon: str = "",
        outcome: str = "",
        cost_sha: str = "",
        data_basis: str = "",
    ) -> dict[str, Any]:
        lab = request.app.state.lab
        if lab is None or lab.roles is None:
            raise HTTPException(503, "Research lesson registry unavailable")
        try:
            return dict(
                lab.roles.lessons.retrieve(
                    before=before,
                    text=text,
                    family=family,
                    parent=parent,
                    horizon=horizon,
                    outcome=outcome,
                    cost_sha=cost_sha,
                    data_basis=data_basis,
                )
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/research/lessons/{identity}")
    def lesson_detail(request: Request, identity: str) -> dict[str, Any]:
        lab = request.app.state.lab
        if lab is None or lab.roles is None:
            raise HTTPException(503, "Research lesson registry unavailable")
        try:
            return dict(lab.roles.lessons.get(identity))
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/research/selection")
    def selection_metrics(request: Request) -> dict[str, Any]:
        lab = request.app.state.lab
        if lab is None or lab.roles is None:
            raise HTTPException(503, "Research selector unavailable")
        return dict(lab.roles.selection_metrics())

    @app.get("/api/research/quality")
    def research_quality(request: Request) -> dict[str, Any]:
        lab = request.app.state.lab
        if lab is None or lab.roles is None:
            raise HTTPException(503, "Research metrics unavailable")
        return quality_report(lab.roles)

    @app.post("/api/research/stocks/investigations")
    def stock_investigate(request: Request, question: StockQuestion) -> dict[str, Any]:
        lab = lab_operator(request)
        try:
            return StockResearch(lab.registry).investigate(question)
        except (ValueError, httpx.HTTPError) as exc:
            raise HTTPException(409, str(exc)[:300]) from exc

    @app.post("/api/research/stocks/market-study")
    def stock_market_study(request: Request, question: StockQuestion) -> dict[str, Any]:
        lab = lab_operator(request)
        try:
            return StockResearch(lab.registry).market_study(question)
        except (ValueError, httpx.HTTPError) as exc:
            raise HTTPException(409, str(exc)[:300]) from exc

    @app.get("/api/research/stocks/studies/{identity}")
    def stock_study(request: Request, identity: str) -> dict[str, Any]:
        lab = request.app.state.lab
        if lab is None:
            raise HTTPException(503, "Research registry unavailable")
        try:
            return StockResearch(lab.registry).get(identity)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/research/stocks/studies/{identity}/section")
    def stock_section(
        request: Request,
        identity: str,
        phrase: str = Query(min_length=3, max_length=100),
        index: int = Query(0, ge=0, le=1),
        compare: bool = False,
    ) -> dict[str, Any]:
        lab = lab_operator(request)
        try:
            research = StockResearch(lab.registry)
            return (
                research.compare_filings(identity, phrase)
                if compare
                else research.section(identity, index, phrase)
            )
        except (ValueError, httpx.HTTPError) as exc:
            raise HTTPException(409, str(exc)[:300]) from exc

    @app.get("/api/autonomous")
    async def autonomous_snapshot(request: Request) -> dict[str, Any]:
        return dict(autonomous(request).snapshot())

    @app.post("/api/autonomous/start")
    async def autonomous_start(request: Request, policy: LabPolicy) -> dict[str, Any]:
        lab_operator(request)
        try:
            return dict(autonomous(request).start(policy))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/autonomous/control")
    async def autonomous_control(request: Request, body: LabControl) -> dict[str, Any]:
        lab_operator(request)
        try:
            return dict(autonomous(request).control(body.action, body.target))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/autonomous/bundle")
    async def autonomous_bundle(request: Request) -> dict[str, Any]:
        return dict(autonomous(request).bundle(time.time()))

    @app.post("/api/autonomous/proposals")
    async def autonomous_submit(request: Request, proposal: LabProposal) -> dict[str, Any]:
        lab_operator(request)
        try:
            return dict(autonomous(request).submit(proposal))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/autonomous/proposals/{request_id}")
    def autonomous_proposal(request: Request, request_id: str) -> dict[str, Any]:
        try:
            controller = autonomous(request)
            result = dict(controller.inbox.get(request_id))
            with controller.registry.lock:
                row = controller.registry.db.execute(
                    "SELECT body FROM lab_bundles WHERE sha256=?",
                    (result["body"]["evidence_bundle_sha256"],),
                ).fetchone()
            result["issued_bundle"] = json.loads(row["body"]) if row else None
            result["financial_outcome"] = controller.paper.store.lab_proposal_outcome(request_id)
            return result
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/autonomous/proposals/{request_id}/launch")
    def autonomous_operator_launch(
        request: Request, request_id: str, body: OperatorLaunch
    ) -> dict[str, Any]:
        lab_operator(request)
        try:
            return dict(autonomous(request).launch_existing(request_id, body))
        except (psycopg.Error, sqlite3.Error, OSError) as exc:
            raise HTTPException(
                503,
                "Setup acknowledgment unknown; reopen the same proposal identity before retrying",
            ) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)[:300]) from exc

    @app.get("/api/autonomous/history")
    async def autonomous_history(request: Request, before: int = Query(0, ge=0)) -> dict[str, Any]:
        return dict(autonomous(request).paper.store.lab_history(before))

    @app.get("/api/autonomous/accounts/{name}")
    async def autonomous_account(request: Request, name: str) -> dict[str, Any]:
        store = autonomous(request).paper.store
        archived = store.archived_account(name)
        if archived:
            return dict(archived)
        active = autonomous(request).paper.state["accounts"].get(name)
        if active:
            return {"account": name, "state": active, "retired_at": None}
        raise HTTPException(404, "Unknown retained account")

    @app.get("/api/autonomous/export")
    async def autonomous_export(
        request: Request, after: int = Query(0, ge=0), account: str | None = None
    ) -> dict[str, Any]:
        return dict(autonomous(request).paper.store.export(after, 500, account))

    @app.post("/api/lab/experiments")
    def research_launch(plan: ExperimentPlan, request: Request) -> dict[str, Any]:
        lab = lab_operator(request)
        try:
            return lab.enqueue(plan)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/lab/prospective")
    def prospective_plans(request: Request) -> dict[str, Any]:
        lab = request.app.state.lab
        if lab is None:
            raise HTTPException(503, "Research registry unavailable")
        paper = request.app.state.paper
        return {
            "plans": lab.prospective.plans(),
            "candidates": lab.prospective.candidates(paper.state) if paper else [],
            "financial_authority": False,
        }

    @app.post("/api/lab/prospective")
    def prospective_freeze(spec: ProspectiveSpec, request: Request) -> dict[str, Any]:
        lab = lab_operator(request)
        paper = request.app.state.paper
        if paper is None:
            raise HTTPException(409, "Paper experiment unavailable")
        try:
            return lab.prospective.freeze(spec, paper.state)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/lab/prospective/{request_id}/inspect")
    def prospective_inspect(request_id: str, request: Request) -> dict[str, Any]:
        lab = lab_operator(request)
        paper = request.app.state.paper
        if paper is None:
            raise HTTPException(409, "Paper experiment unavailable")
        try:
            now = time.time()
            return lab.prospective.report(
                request_id, paper.state, paper.store.forward_windows(now), now
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    def replay_operator(request: Request, *, writing: bool = False) -> ReplayLab:
        if writing:
            lab_operator(request)
        replay: ReplayLab | None = request.app.state.replay
        if not replay:
            raise HTTPException(503, "Execution replay unavailable; paper management continues")
        return replay

    @app.get("/api/replays")
    def replay_history(request: Request, before: int = Query(0, ge=0)) -> dict[str, Any]:
        return replay_operator(request).snapshot(before)

    @app.get("/api/replays/{request_id}")
    def replay_receipt(request: Request, request_id: str) -> dict[str, Any]:
        try:
            receipt = replay_operator(request).registry.get(request_id)
            if receipt is None:
                raise HTTPException(404, "Execution replay receipt missing")
            return receipt
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/replays")
    def replay_launch(request: Request, plan: ReplayPlan) -> dict[str, Any]:
        try:
            return replay_operator(request, writing=True).enqueue(plan)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/lab/campaigns")
    def research_campaign(request: Request, spec: ResearchCampaignSpec) -> dict[str, Any]:
        lab = lab_operator(request)
        try:
            return lab.campaigns.create(spec)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/lab/campaigns/{request_id}")
    def research_campaign_receipt(request: Request, request_id: str) -> dict[str, Any]:
        lab: ExperimentLab | None = request.app.state.lab
        if not lab:
            raise HTTPException(503, "Research registry unavailable")
        try:
            return lab.campaigns.receipt(request_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/lab/campaigns/{request_id}/cancel")
    def research_campaign_cancel(request: Request, request_id: str) -> dict[str, Any]:
        lab = lab_operator(request)
        try:
            lab.campaigns.cancel(request_id)
            return {"status": "cancelled", "history_retained": True}
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/lab/experiments/{request_id}")
    def research_result(request_id: str, request: Request) -> dict[str, Any]:
        lab: ExperimentLab | None = request.app.state.lab
        if lab is None:
            raise HTTPException(503, "Research registry unavailable")
        result = lab.registry.get(request_id)
        if result is None:
            raise HTTPException(404, "Experiment not found")
        return result

    @app.get("/api/lab/experiments/{request_id}/learning")
    def learning_history(
        request_id: str, request: Request, before: int = Query(0, ge=0)
    ) -> dict[str, Any]:
        from trading.incremental_memory import LearningJournal

        lab: ExperimentLab | None = request.app.state.lab
        if lab is None:
            raise HTTPException(503, "Research registry unavailable")
        if lab.registry.status(request_id) is None:
            raise HTTPException(404, "Saved research reference unavailable")
        try:
            with lab.registry.lock:
                return LearningJournal(lab.registry).page(request_id, before)
        except ValueError as exc:
            raise HTTPException(
                409, "Learning snapshot verification failed; evidence preserved"
            ) from exc

    @app.post("/api/lab/experiments/{request_id}/cancel")
    def research_cancel(request_id: str, request: Request) -> dict[str, Any]:
        lab = lab_operator(request)
        if lab.registry.status(request_id) is None:
            raise HTTPException(404, "Experiment not found")
        lab.registry.cancel(request_id)
        return {"status": lab.registry.status(request_id)}

    @app.post("/api/lab/experiments/{request_id}/forward")
    async def research_forward(
        request_id: str, admission: ForwardAdmission, request: Request
    ) -> dict[str, Any]:
        lab = lab_operator(request)
        paper = campaign_operator(request)
        experiment = lab.registry.get(request_id)
        if not experiment or experiment["status"] != "completed" or not experiment["result"]:
            raise HTTPException(409, "A completed fitted result is required")
        candidate = next(
            (
                c
                for c in experiment["result"].get("candidate_group", [])
                if c["family"] == admission.family
                and (admission.family != "memory_entry" or c.get("arm") == admission.arm)
            ),
            None,
        )
        if not candidate or not candidate.get("artifact"):
            raise HTTPException(409, "This family has no frozen fitted artifact")
        if admission.family == "memory_entry" and (
            experiment["result"].get("evidence_kind") == "synthetic_qa"
            or not experiment["result"].get("eligible_for_exploratory_paper")
            or experiment["result"].get("account_comparison", {}).get("status") != "complete"
        ):
            raise HTTPException(
                409,
                "Complete observed paired-account costs required for exploratory paper admission",
            )
        try:
            receipt = paper.forward_admit(
                request_id,
                candidate["artifact"],
                admission.starting_cash,
                admission.operating_daily_usd,
            )
            if admission.family == "memory_entry":
                receipt["matched_control"] = paper.forward_control(receipt["account"])
            return receipt
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except psycopg.Error as exc:
            raise HTTPException(
                503, "Admission unconfirmed; retry the same artifact and funding"
            ) from exc

    @app.get("/api/station/live")
    async def station_live(
        request: Request, symbol: str = Query("BTCUSD", pattern=r"^[A-Z0-9]{3,24}$")
    ) -> dict[str, Any]:
        paper: PaperRuntime | None = request.app.state.paper
        return market_live(paper, symbol) if paper else {"enabled": False, "markets": []}

    @app.get("/api/station/detail")
    async def station_detail(
        request: Request,
        symbol: str = Query("BTCUSD", pattern=r"^[A-Z0-9]{3,24}$"),
        account: str = Query("primary", pattern=r"^[a-zA-Z0-9_-]{1,96}$"),
    ) -> dict[str, Any]:
        paper: PaperRuntime | None = request.app.state.paper
        if paper is None:
            raise HTTPException(409, "Paper experiment is not enabled")
        try:

            def selected_detail() -> dict[str, Any]:
                saved = None
                if isinstance(paper.store, PaperStore):
                    with reader(paper) as view:
                        saved = view.research_account(account)["state"]
                return market_detail(paper, symbol, account, saved)

            return await asyncio.to_thread(selected_detail)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except psycopg.Error as exc:
            raise HTTPException(
                503, "Selected evidence is unavailable; retry when connected"
            ) from exc

    @app.get("/api/research/tools")
    async def research_tools(
        request: Request, cursor: str | None = Query(None, max_length=2048)
    ) -> dict[str, Any]:
        journal: ToolJournal | None = request.app.state.tool_journal
        try:
            history = (
                await asyncio.to_thread(journal.recent, cursor)
                if journal
                else {"runs": [], "total": 0}
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(503, "Tool history is waiting for configured storage") from exc
        return {
            "tools": [{"id": key, **value} for key, value in TOOLS.items()],
            "authority": "Read-only evidence; no financial or model authority",
            "agents_enabled": False,
            "error": request.app.state.tool_error,
            "capabilities": {
                "coverage": {"method": "GET", "path": "/api/research/activity"},
                "prior_experiments": {"method": "GET", "path": "/api/lab"},
                "historical_analogues": {
                    "method": "GET",
                    "path": "/api/research/analogues/{record_id}",
                },
                "prior_paper_trials": {"method": "GET", "path": "/api/autonomous/history"},
                "proposal_bundle": {"method": "GET", "path": "/api/autonomous/bundle"},
                "proposal_submit": {"method": "POST", "path": "/api/autonomous/proposals"},
                "proposal_result": {
                    "method": "GET",
                    "path": "/api/autonomous/proposals/{request_id}",
                },
                "experiment_submit": {
                    "method": "POST",
                    "path": "/api/lab/experiments",
                    "result": "durable asynchronous request_id",
                },
                "experiment_result": {"method": "GET", "path": "/api/lab/experiments/{request_id}"},
            },
            **history,
        }

    def disclose_tool(request: Request, receipt: dict[str, Any]) -> None:
        lab: ExperimentLab | None = request.app.state.lab
        if receipt.get("result") and lab is None:
            raise HTTPException(
                503, "Evidence disclosure authority unavailable; retry when connected"
            )
        if lab:
            disclose(lab.registry, receipt)

    @app.get("/api/research/analogues/{record_id}")
    def historical_analogues(request: Request, record_id: int) -> dict[str, Any]:
        try:
            saved = evidence_record(database.parent / "research-evidence.sqlite", record_id)
            episode = saved["payload"].get("episode")
            if not isinstance(episode, dict) or not episode.get("retrieval"):
                raise LookupError("This captured record has no causal analogue lookup")
            if saved["payload"]["at"] > time.time():
                raise ValueError("Captured analogue is not yet available")
            result = {
                "source": {
                    "type": "full-evidence-record",
                    "id": record_id,
                    "sha256": saved["sha256"],
                },
                "lookup": episode["retrieval"],
                "query_descriptor": episode["descriptor"],
                "scope": "Captured causal lookup; neighbors do not estimate outcome frequencies",
            }
            if len(json.dumps(result).encode()) > 131072:
                raise ValueError("Analogue lookup exceeds bounded response capacity")
            lab = request.app.state.lab
            if lab is None:
                raise HTTPException(503, "Analogue disclosure authority unavailable")
            # The existing capture may include old neighbor outcomes. Consume its
            # entire past conservatively before revealing these saved values.
            with lab.registry.transaction():
                lab.registry.db.execute(
                    "INSERT OR IGNORE INTO evidence_windows "
                    "VALUES(?,?,?,'analogue tool disclosure')",
                    ("analogue:" + saved["sha256"], 0, saved["payload"]["at"]),
                )
            return result
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, KeyError, TypeError, sqlite3.Error, OSError) as exc:
            raise HTTPException(
                409, "Captured analogue unavailable; no current-data substitute"
            ) from exc

    @app.get("/api/research/tools/accounts")
    async def tool_accounts(
        request: Request, before: str = Query("", max_length=96)
    ) -> dict[str, Any]:
        paper = request.app.state.paper
        if paper is None:
            raise HTTPException(503, "Paper identities are unavailable")

        def identities() -> dict[str, Any]:
            active = [
                {"account": name, "label": a.get("label", name), "archived": False}
                for name, a in paper.state["accounts"].items()
            ]
            archived: list[dict[str, Any]] = []
            if isinstance(paper.store, PaperStore):
                with reader(paper) as view:
                    archived = list(
                        view.connection.execute(
                            "SELECT account,state->>'label' AS label,true AS archived "
                            "FROM paper_lab_archives WHERE (%s='' OR account>%s) "
                            "ORDER BY account LIMIT 21",
                            (before, before),
                        ).fetchall()
                    )
            return {
                "accounts": active + archived[:20],
                "has_more": len(archived) > 20,
                "next_before": archived[19]["account"] if len(archived) > 20 else None,
            }

        try:
            return await asyncio.to_thread(identities)
        except psycopg.Error as exc:
            raise HTTPException(503, "Account identities are unavailable; retry") from exc

    @app.get("/api/research/tools/runs/{run_id}")
    async def tool_run(request: Request, run_id: int) -> dict[str, Any]:
        journal: ToolJournal | None = request.app.state.tool_journal
        try:
            result = await asyncio.to_thread(journal.get, run_id) if journal else None
            if result:
                await asyncio.to_thread(disclose_tool, request, result)
        except (ValueError, LookupError, OSError, sqlite3.Error) as exc:
            raise HTTPException(
                503, "Exact saved receipt unavailable; no current-data substitute"
            ) from exc
        if result is None:
            raise HTTPException(404, "Tool receipt not found")
        return result

    @app.get("/api/research/tools/runs/{run_id}/detail")
    async def tool_detail(
        request: Request, run_id: int, cursor: str | None = Query(None, max_length=4096)
    ) -> dict[str, Any]:
        journal: ToolJournal | None = request.app.state.tool_journal
        if journal is None:
            raise HTTPException(503, "Tool storage is unavailable")
        try:
            receipt = await asyncio.to_thread(journal.get, run_id)
            if receipt is None:
                raise HTTPException(404, "Tool receipt not found")
            await asyncio.to_thread(disclose_tool, request, receipt)
            if receipt["tool"] == "outcome_review" and receipt["result"].get("envelope"):
                facts = (await asyncio.to_thread(journal.detail, run_id))["facts"]
                before = 0
                identity = {
                    "run_id": run_id,
                    "sha256": receipt["result_sha256"],
                    "account": receipt["account"],
                    "query": receipt["query"],
                }
                if cursor:
                    claims = journal.claims(cursor, kind="outcomes")
                    if any(claims.get(k) != v for k, v in identity.items()):
                        raise ValueError("Outcome cursor belongs to a different receipt/snapshot")
                    before = int(claims["before"])
                paper = request.app.state.paper
                page = (
                    await asyncio.to_thread(outcome_page, paper, receipt, before)
                    if before
                    else {k: facts.get(k) for k in ("events", "has_more", "next_before")}
                )
                return {
                    "scope": identity,
                    **page,
                    "next_cursor": journal.cursor(
                        dict(identity, kind="outcomes", before=page["next_before"])
                    )
                    if page["has_more"]
                    else None,
                }
            return await asyncio.to_thread(journal.detail, run_id, cursor)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (LookupError, OSError, sqlite3.Error, psycopg.Error) as exc:
            raise HTTPException(
                503, "Captured detail is unavailable; retry when connected"
            ) from exc

    @app.post("/api/research/tools/run")
    async def run_tool(command: ToolRequest, request: Request) -> dict[str, Any]:
        origin = request.headers.get("origin")
        if request.headers.get("x-local-operator") != "1" or (
            origin
            and (
                urlsplit(origin).scheme != "http"
                or urlsplit(origin).netloc != request.headers.get("host")
            )
        ):
            raise HTTPException(403, "Local operator request required")
        paper: PaperRuntime | None = request.app.state.paper
        journal: ToolJournal | None = request.app.state.tool_journal
        if (
            paper is None
            or not journal
            or command.tool not in HISTORICAL_TOOLS
            and (not paper.running or paper.error or time.time() - paper.state["last_tick"] > 10)
        ):
            raise HTTPException(503, "Paper worker or tool receipt storage is unavailable")
        if paper.disk_free < 5 * 1024**3:
            raise HTTPException(503, "Optional tools are waiting for free disk space")
        if request.app.state.tool_busy or time.monotonic() - request.app.state.last_tool_at < 1:
            raise HTTPException(429, "One bounded tool run at a time; wait before retrying")
        request.app.state.tool_busy = True
        request.app.state.last_tool_at = time.monotonic()
        try:
            request_id = command.request_id or str(uuid.uuid4())
            run_id = await asyncio.to_thread(
                journal.start,
                command.tool,
                command.symbol,
                account=command.account,
                request_id=request_id,
                query=command.model_dump(exclude={"request_id"}),
            )
            existing = await asyncio.to_thread(journal.get, run_id)
            if existing and existing["status"] != "running":
                await asyncio.to_thread(disclose_tool, request, existing)
                return existing
            result = None
            error = None
            try:
                if command.start > time.time():
                    raise ValueError(
                        "Outcome interval begins after the available observation cutoff"
                    )
                result = await asyncio.to_thread(
                    scoped_tool,
                    paper,
                    command.tool,
                    command.symbol,
                    command.account,
                    request_id,
                    start=command.start,
                )
            except (ValueError, KeyError, ArithmeticError) as exc:
                error = str(exc)
            except Exception as exc:
                # A failed optional read has a terminal receipt, including unexpected
                # snapshot/driver failures. Never expose driver text or credentials.
                error = f"Evidence read failed ({type(exc).__name__}); retry this bounded read"
            await asyncio.to_thread(journal.finish, run_id, result, error)
            saved = await asyncio.to_thread(journal.get, run_id)
            assert saved is not None
            await asyncio.to_thread(disclose_tool, request, saved)
            return saved
        except (sqlite3.Error, OSError, ValueError, psycopg.Error) as exc:
            raise HTTPException(
                503, "Tool receipt could not be saved; inspect local storage"
            ) from exc
        finally:
            request.app.state.tool_busy = False

    @app.post("/api/paper/entries")
    async def paper_entries(control: Control, request: Request) -> dict[str, bool]:
        origin = request.headers.get("origin")
        if request.headers.get("x-local-operator") != "1":
            raise HTTPException(403, "Local operator header required")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.netloc != request.headers.get("host"):
                raise HTTPException(403, "Cross-origin operator commands are not allowed")
        paper: PaperRuntime | None = request.app.state.paper
        if paper is None:
            raise HTTPException(409, "Paper experiment is not enabled")
        paper.set_paused(control.action == "pause")
        return {"paused": paper.state["paused"]}

    @app.post("/api/paper/accounts/{account}/risk-control")
    async def paper_risk_control(
        account: str, control: RiskControl, request: Request
    ) -> dict[str, Any]:
        origin = request.headers.get("origin")
        if request.headers.get("x-local-operator") != "1" or (
            origin
            and (
                urlsplit(origin).scheme != "http"
                or urlsplit(origin).netloc != request.headers.get("host")
            )
        ):
            raise HTTPException(403, "Local operator request required")
        paper: PaperRuntime | None = request.app.state.paper
        if paper is None:
            raise HTTPException(409, "Paper experiment is not enabled")
        if account not in paper.state["accounts"]:
            raise HTTPException(404, "Paper account not found")
        try:
            # The existing single writer transaction is the authority, not browser values.
            return paper.risk_control(account, control.action, control.stop_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except psycopg.Error as exc:
            raise HTTPException(503, "Risk control was not saved; refresh before retrying") from exc

    @app.post("/api/paper/accounts/{account}/economics-settings")
    async def paper_economics_settings(
        account: str, control: EconomicsControl, request: Request
    ) -> dict[str, Any]:
        origin = request.headers.get("origin")
        if request.headers.get("x-local-operator") != "1" or (
            origin
            and (
                urlsplit(origin).scheme != "http"
                or urlsplit(origin).netloc != request.headers.get("host")
            )
        ):
            raise HTTPException(403, "Local operator request required")
        paper: PaperRuntime | None = request.app.state.paper
        if paper is None:
            raise HTTPException(409, "Paper experiment is not enabled")
        if account not in paper.state["accounts"]:
            raise HTTPException(404, "Paper account not found")
        try:
            return paper.economics_control(
                account,
                control.execution_profile,
                control.operating_daily_usd,
                control.expected_version,
            )
        except (ValueError, ArithmeticError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except psycopg.Error as exc:
            raise HTTPException(
                503, "Cost assumptions were not saved; refresh before retrying"
            ) from exc

    def campaign_operator(request: Request) -> PaperRuntime:
        origin = request.headers.get("origin")
        if request.headers.get("x-local-operator") != "1" or (
            origin
            and (
                urlsplit(origin).scheme != "http"
                or urlsplit(origin).netloc != request.headers.get("host")
            )
        ):
            raise HTTPException(403, "Local operator request required")
        paper: PaperRuntime | None = request.app.state.paper
        if paper is None:
            raise HTTPException(409, "Paper experiment is not enabled")
        return paper

    @app.post("/api/paper/campaigns")
    async def paper_campaign(spec: CampaignSpec, request: Request) -> dict[str, Any]:
        paper = campaign_operator(request)
        try:
            return paper.campaign_create(spec)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except psycopg.Error as exc:
            raise HTTPException(503, "Launch not confirmed; retry the same request") from exc

    @app.get("/api/paper/diagnostics")
    def paper_diagnostics(request: Request) -> dict[str, Any]:
        paper: PaperRuntime | None = request.app.state.paper
        if paper is None:
            return {"enabled": False, "created": False, "account": None, "run": None}
        try:
            return {"enabled": True, **paper.diagnostic_snapshot()}
        except psycopg.Error as exc:
            raise HTTPException(
                503, "Diagnostic outcome is unavailable; retain the request"
            ) from exc

    @app.post("/api/paper/diagnostics/create")
    def paper_diagnostic_create(spec: DiagnosticRequest, request: Request) -> dict[str, Any]:
        paper = campaign_operator(request)
        try:
            return paper.diagnostic_create(spec.request_id)
        except (ValueError, ArithmeticError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except psycopg.Error as exc:
            raise HTTPException(503, "Creation not confirmed; retry the same request") from exc

    @app.post("/api/paper/diagnostics/start")
    def paper_diagnostic_start(spec: DiagnosticStart, request: Request) -> dict[str, Any]:
        paper = campaign_operator(request)
        try:
            return paper.diagnostic_start(
                spec.request_id, spec.seed, spec.max_actions, spec.duration_seconds
            )
        except (ValueError, ArithmeticError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except psycopg.Error as exc:
            raise HTTPException(503, "Start not confirmed; retry the same request") from exc

    @app.post("/api/paper/diagnostics/stop")
    def paper_diagnostic_stop(spec: DiagnosticRequest, request: Request) -> dict[str, Any]:
        paper = campaign_operator(request)
        try:
            return paper.diagnostic_stop(spec.request_id)
        except (ValueError, ArithmeticError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except psycopg.Error as exc:
            raise HTTPException(503, "Stop not confirmed; retry the same request") from exc

    @app.post("/api/paper/accounts/{account}/control")
    async def paper_account_control(
        account: str, control: AccountControl, request: Request
    ) -> dict[str, Any]:
        paper = campaign_operator(request)
        if account not in paper.state["accounts"]:
            raise HTTPException(404, "Paper account not found")
        try:
            return paper.account_control(account, control.action, control.expected_version)
        except (ValueError, ArithmeticError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except psycopg.Error as exc:
            raise HTTPException(
                503, "Account control not confirmed; refresh before retrying"
            ) from exc

    @app.post("/api/paper/learning/control/{candidate}")
    async def matched_forward_control(request: Request, candidate: str) -> dict[str, Any]:
        lab_operator(request)
        paper = campaign_operator(request)
        try:
            return paper.forward_control(candidate)
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/paper/learning/reports")
    async def forward_learning_report(request: Request, spec: LearningReport) -> dict[str, Any]:
        lab = lab_operator(request)
        paper = campaign_operator(request)
        try:
            return paper.learning_report(spec.request_id, spec.candidate, lab.registry)
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/paper/learning/role")
    async def forward_learning_role(request: Request, spec: LearningRole) -> dict[str, Any]:
        lab_operator(request)
        paper = campaign_operator(request)
        try:
            return paper.learning_role(
                spec.action, spec.expected_version, spec.report_id, spec.report_sha256
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/paper/learning/reports/{request_id}")
    def forward_learning_export(request: Request, request_id: str) -> dict[str, Any]:
        paper: PaperRuntime | None = request.app.state.paper
        try:
            result = paper.retained_learning_report(request_id) if paper else None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if result is None:
            raise HTTPException(404, "Learning report not found")
        return dict(result)

    @app.get("/api/paper/journal")
    async def paper_journal(
        request: Request,
        after: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        account: str | None = Query(None, max_length=100),
    ) -> dict[str, Any]:
        paper: PaperRuntime | None = request.app.state.paper
        if paper is None:
            raise HTTPException(409, "Paper experiment is not enabled")
        if account is not None and account not in paper.state["accounts"]:
            raise HTTPException(404, "Paper account not found")
        return paper.store.export(after, limit, account)

    @app.get("/api/paper/trades")
    def paper_trades(
        request: Request,
        before: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        account: str | None = Query(None, min_length=1, max_length=100),
        status: Literal["all", "open", "closed"] = "all",
    ) -> JSONResponse:
        paper: PaperRuntime | None = request.app.state.paper
        if paper is None:
            raise HTTPException(409, "Paper experiment is not enabled")
        from trading.paper_engine import filters, fresh_frame

        # Runs in the worker pool, with a separate read-only connection. This
        # view never uses control_frames(), which updates feed bookkeeping.
        frames = {}
        now = time.time()
        if paper.running and not paper.error:
            symbols = {s for a in paper.state["accounts"].values() for s in a["positions"]}
            for symbol in symbols:
                book = paper.memory_book(symbol)
                instrument = paper.instruments.get(symbol)
                previous = paper._previous_books.get(symbol)
                if book and instrument and fresh_frame(book, now):
                    if previous and book["book"].update_id < previous[0]:
                        continue
                    try:
                        frames[symbol] = {**book, "rules": filters(instrument)}
                    except (KeyError, ValueError, ArithmeticError):
                        continue
        reader = None
        try:
            # info.dsn is intentionally redacted; reconnect with the existing
            # credential in memory, never in a response or diagnostic log.
            info = paper.store.connection.info
            reader = PaperStore(make_conninfo(info.dsn, password=info.password))
            with reader.connection.transaction():
                reader.connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                result = reader.trade_history(
                    before=before,
                    limit=limit,
                    account=account,
                    status=status,
                    frames=frames,
                    now=now,
                )
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except KeyError as exc:
            raise HTTPException(404, "Paper account not found") from exc
        except psycopg.Error as exc:
            raise HTTPException(503, "Trade history could not load; retry when connected") from exc
        finally:
            if reader is not None:
                reader.close()

    @app.post("/api/collector")
    async def collector(control: Control, request: Request) -> dict[str, bool]:
        origin = request.headers.get("origin")
        if request.headers.get("x-local-operator") != "1":
            raise HTTPException(403, "Local operator header required")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.netloc != request.headers.get("host"):
                raise HTTPException(403, "Cross-origin operator commands are not allowed")
        request.app.state.monitor.set_paused(control.action == "pause")
        return {"paused": request.app.state.monitor.paused}

    @app.post("/api/options/entries")
    async def options_entries(control: Control, request: Request) -> dict[str, bool]:
        if request.headers.get("x-local-operator") != "1":
            raise HTTPException(403, "Local operator header required")
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != "http" or parsed.netloc != request.headers.get("host"):
                raise HTTPException(403, "Cross-origin operator commands are not allowed")
        options: OptionsRuntime | None = request.app.state.options
        if options is None:
            raise HTTPException(409, "Options account unavailable")
        options.set_paused(control.action == "pause")
        return {"paused": options.state["paused"]}

    @app.get("/api/options/journal")
    async def options_journal(
        request: Request, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)
    ) -> dict[str, Any]:
        options: OptionsRuntime | None = request.app.state.options
        if options is None:
            raise HTTPException(409, "Options account unavailable")
        return options.store.export(after, limit)

    @app.get("/api/evidence")
    def evidence_list(
        before: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=50),
        kind: Literal["decision", "summary", "wire", "outcome", "all"] = "decision",
    ) -> dict[str, Any]:
        return evidence_page(database.parent / "research-evidence.sqlite", before, limit, kind)

    @app.get("/api/evidence/{record_id}")
    def decision_evidence(
        record_id: int,
        sha256: str | None = Query(None, pattern=r"^[0-9a-f]{64}$"),
        episode: str | None = Query(None, max_length=128),
    ) -> dict[str, Any]:
        try:
            record = evidence_record(database.parent / "research-evidence.sqlite", record_id)
            if sha256 is not None and record["sha256"] != sha256:
                raise ValueError("Requested full-archive fingerprint differs")
            if episode is not None:
                original = record.get("original_episode", record["payload"].get("episode"))
                identity = original.get("episode") if isinstance(original, dict) else original
                if identity != episode:
                    raise ValueError("Requested full-archive episode differs")
            return {**record, "reproduction": feature_reproduction(record["payload"])}
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(
                409, "Evidence unavailable or corrupt; no replacement inferred"
            ) from exc

    @app.get("/api/evidence/compact/{episode}")
    def compact_prefix_evidence(
        episode: str,
        sha256: str = Query(pattern=r"^[0-9a-f]{64}$"),
    ) -> dict[str, Any]:
        try:
            return compact_evidence(compact_path(database.parent), episode, sha256)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            raise HTTPException(
                409, "Compact evidence differs or is corrupt; no substitute inferred"
            ) from exc

    @app.get("/api/capture")
    async def capture(request: Request) -> Response:
        content = json.dumps(request.app.state.monitor.store.export(), indent=2).encode()
        return Response(
            content,
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="public-market-capture.json"',
                "X-Content-SHA256": hashlib.sha256(content).hexdigest(),
            },
        )

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        monitor = request.app.state.monitor
        paper: PaperRuntime | None = request.app.state.paper
        status_reader = getattr(paper, "journal_status", None)
        journal = status_reader() if callable(status_reader) else {}
        return {
            "service": "running",
            "mode": "paper",
            "code_commit": code_commit,
            "paper_fresh": bool(
                paper and paper.running and time.time() - paper.state["last_tick"] < 10
            ),
            "journal_balanced": journal.get("balanced") if journal.get("available") else None,
            "journal_last_balanced": paper.receipts.get("balanced") if paper else None,
            "journal_monitoring": journal,
            "paper_error_reported": paper.error is not None if paper else None,
            "feed": monitor.snapshot()["runtime_state"],
            "paper": "running" if paper and paper.running else "stopped",
            "options": "running"
            if request.app.state.options and request.app.state.options.running
            else "stopped",
        }

    if web_dist and (web_dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(web_dist / "index.html")
    else:

        @app.get("/")
        async def build_required() -> JSONResponse:
            return JSONResponse({"detail": "Build the dashboard: npm --prefix apps/web run build"})

    return app
