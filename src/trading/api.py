"""Loopback operator API and compiled dashboard. No order routes exist."""

import asyncio
import hashlib
import json
import re
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg.conninfo import make_conninfo
from pydantic import BaseModel, ConfigDict, Field

from trading.autonomous_spec import LabControl, LabPolicy, LabProposal
from trading.compact_memory import compact_evidence
from trading.config import Settings
from trading.evidence_runtime import feature_reproduction
from trading.experiment_lab import ExperimentLab
from trading.experiment_registry import ExperimentPlan
from trading.model_trials import ModelTrials
from trading.options_runtime import OptionsRuntime
from trading.options_store import OptionsStore
from trading.ownership import CollectorLock
from trading.paper_campaigns import CampaignSpec
from trading.paper_engine import LEGACY_POLICY, policy
from trading.paper_store import PaperStore, load_dsn
from trading.prospective_review import ProspectiveSpec
from trading.replay_lab import ReplayLab, ReplayPlan
from trading.research_campaigns import ResearchCampaignSpec
from trading.research_evidence import evidence_page, evidence_record
from trading.research_storage import (
    StoragePlan,
    compact_path,
    load_plan,
    reopen_evidence,
    save_plan,
    storage_snapshot,
    volume,
)
from trading.runtime import Monitor
from trading.station import TOOLS, execute_tool, market_detail, market_live
from trading.storage import MonitorStore
from trading.tiered_runtime import TieredPaperRuntime as PaperRuntime
from trading.tool_journal import ToolJournal
from trading.venue import PublicVenue


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["pause", "resume"]


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
            replay_lab = None
            replay_task = None
            try:
                app.state.tool_busy = False
                app.state.last_tool_at = 0.0
                app.state.tool_error = None
                try:
                    tool_journal = ToolJournal(database.parent / "research-tools.sqlite3")
                except (sqlite3.Error, OSError):
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
                if lab:

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

                        lab.autonomous = AutonomousLab(
                            lab.registry, app.state.paper, lambda: lab.can_research()
                        )
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
        dsn = paper.store.connection.info.dsn if paper else None
        return activity_view.snapshot(dsn, paper, request.app.state.lab)

    @app.get("/api/research/storage")
    def research_storage_status() -> dict[str, Any]:
        return storage_snapshot(database.parent)

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
    async def autonomous_proposal(request: Request, request_id: str) -> dict[str, Any]:
        try:
            controller = autonomous(request)
            result = dict(controller.inbox.get(request_id))
            with controller.registry.lock:
                row = controller.registry.db.execute(
                    "SELECT body FROM lab_bundles WHERE sha256=?",
                    (result["body"]["evidence_bundle_sha256"],),
                ).fetchone()
            result["issued_bundle"] = json.loads(row["body"]) if row else None
            return result
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

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
        request: Request, symbol: str = Query("BTCUSD", pattern=r"^[A-Z0-9]{3,24}$")
    ) -> dict[str, Any]:
        paper: PaperRuntime | None = request.app.state.paper
        if paper is None:
            raise HTTPException(409, "Paper experiment is not enabled")
        try:
            return market_detail(paper, symbol)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/research/tools")
    async def research_tools(request: Request) -> dict[str, Any]:
        journal: ToolJournal | None = request.app.state.tool_journal
        return {
            "tools": [{"id": key, **value} for key, value in TOOLS.items()],
            "authority": "Read-only evidence; no financial or model authority",
            "agents_enabled": False,
            "error": request.app.state.tool_error,
            **(await asyncio.to_thread(journal.recent) if journal else {"runs": [], "total": 0}),
        }

    @app.get("/api/research/tools/runs/{run_id}")
    async def tool_run(request: Request, run_id: int) -> dict[str, Any]:
        journal: ToolJournal | None = request.app.state.tool_journal
        result = await asyncio.to_thread(journal.get, run_id) if journal else None
        if result is None:
            raise HTTPException(404, "Tool receipt not found")
        return result

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
            or not paper.running
            or paper.error
            or not journal
            or time.time() - paper.state["last_tick"] > 10
        ):
            raise HTTPException(503, "Paper worker or tool receipt storage is unavailable")
        if paper.disk_free < 5 * 1024**3:
            raise HTTPException(503, "Optional tools are waiting for free disk space")
        if request.app.state.tool_busy or time.monotonic() - request.app.state.last_tool_at < 1:
            raise HTTPException(429, "One bounded tool run at a time; wait before retrying")
        request.app.state.tool_busy = True
        request.app.state.last_tool_at = time.monotonic()
        try:
            run_id = await asyncio.to_thread(journal.start, command.tool, command.symbol)
            result = None
            error = None
            try:
                result = execute_tool(paper, command.tool, command.symbol)
            except (ValueError, KeyError, ArithmeticError) as exc:
                error = str(exc)
            await asyncio.to_thread(journal.finish, run_id, result, error)
            saved = await asyncio.to_thread(journal.get, run_id)
            assert saved is not None
            return saved
        except (sqlite3.Error, OSError, ValueError) as exc:
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
        request: Request, before: int = Query(0, ge=0),
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
                result = reader.trade_history(before=before, limit=limit, account=account,
                                              status=status, frames=frames, now=now)
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
        return {
            "service": "running",
            "mode": "paper",
            "code_commit": code_commit,
            "paper_fresh": bool(
                paper and paper.running and time.time() - paper.state["last_tick"] < 10
            ),
            "journal_balanced": paper.receipts.get("balanced") if paper else None,
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
