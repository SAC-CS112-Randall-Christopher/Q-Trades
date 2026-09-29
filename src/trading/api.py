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
from pydantic import BaseModel, ConfigDict, Field

from trading.config import Settings
from trading.experiment_lab import ExperimentLab
from trading.experiment_registry import ExperimentPlan
from trading.model_trials import ModelTrials
from trading.options_runtime import OptionsRuntime
from trading.options_store import OptionsStore
from trading.ownership import CollectorLock
from trading.paper_campaigns import CampaignSpec
from trading.paper_engine import LEGACY_POLICY, policy
from trading.paper_store import PaperStore, load_dsn
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
    family: Literal["slow_trend", "volatility_breakout", "range_reversion"]
    starting_cash: Literal["50", "100"]
    operating_daily_usd: str | None = Field(default=None, pattern=r"^\d{1,4}(\.\d{1,6})?$")


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
                    return bool(paper and paper.running and not paper.error
                                and time.time() - paper.state["last_tick"] < 10
                                and not paper.constrained())

                try:
                    lab = ExperimentLab(
                        database.parent / "experiments.sqlite3",
                        load_dsn(paper_database) if paper_database else None, research_ready,
                    )
                except (sqlite3.Error, OSError):
                    app.state.lab_error = "Research storage unavailable; paper management continues"
                app.state.lab = lab
                lab_task = asyncio.create_task(lab.run()) if background and lab else None
                yield
            finally:
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

    app = FastAPI(title="Trading Research · Public Monitor", lifespan=lifespan)
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

    @app.get("/api/research/trials")
    def research_trials() -> dict[str, Any]:
        # Runs in FastAPI's worker pool, outside the trading event loop.
        return model_trials.snapshot()

    def lab_operator(request: Request) -> ExperimentLab:
        origin = request.headers.get("origin")
        if request.headers.get("x-local-operator") != "1" or (origin and (
            urlsplit(origin).scheme != "http"
            or urlsplit(origin).netloc != request.headers.get("host")
        )):
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

    @app.post("/api/lab/experiments")
    def research_launch(plan: ExperimentPlan, request: Request) -> dict[str, Any]:
        lab = lab_operator(request)
        try:
            return lab.enqueue(plan)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/lab/experiments/{request_id}")
    def research_result(request_id: str, request: Request) -> dict[str, Any]:
        lab: ExperimentLab | None = request.app.state.lab
        if lab is None:
            raise HTTPException(503, "Research registry unavailable")
        result = lab.registry.get(request_id)
        if result is None:
            raise HTTPException(404, "Experiment not found")
        return result

    @app.post("/api/lab/experiments/{request_id}/cancel")
    def research_cancel(request_id: str, request: Request) -> dict[str, Any]:
        lab = lab_operator(request)
        if lab.registry.status(request_id) is None:
            raise HTTPException(404, "Experiment not found")
        lab.registry.cancel(request_id)
        return {"status": lab.registry.status(request_id)}

    @app.post("/api/lab/experiments/{request_id}/forward")
    async def research_forward(request_id: str, admission: ForwardAdmission,
                               request: Request) -> dict[str, Any]:
        lab = lab_operator(request)
        paper = campaign_operator(request)
        experiment = lab.registry.get(request_id)
        if not experiment or experiment["status"] != "completed" or not experiment["result"]:
            raise HTTPException(409, "A completed fitted result is required")
        candidate = next((c for c in experiment["result"].get("candidate_group", [])
                          if c["family"] == admission.family), None)
        if not candidate or not candidate.get("artifact"):
            raise HTTPException(409, "This family has no frozen fitted artifact")
        try:
            return paper.forward_admit(request_id, candidate["artifact"], admission.starting_cash,
                                       admission.operating_daily_usd)
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
