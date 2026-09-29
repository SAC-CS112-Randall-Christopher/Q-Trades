"""Loopback operator API and compiled dashboard. No order routes exist."""

import asyncio
import hashlib
import json
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from trading.activation_state import verify_startup
from trading.config import Settings
from trading.local_updates import STATUS_NAME, MainUpdates, public_status, source_identity
from trading.model_trials import ModelTrials
from trading.options_runtime import OptionsRuntime
from trading.options_store import OptionsStore
from trading.ownership import CollectorLock
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
    source_root: Path | None = None,
    preserve_existing: bool = False,
) -> FastAPI:
    source = (source_root or Path(__file__).resolve().parents[2]).resolve()
    updates = MainUpdates(source, database.parent)
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
            app.state.source_at_start = await asyncio.to_thread(source_identity, source)
            app.state.update_busy = False
            app.state.last_update_check = -60.0
            store = MonitorStore(database, settings.retained_observations)
            public_venue = venue or PublicVenue(settings.request_timeout_seconds)
            task = None
            paper_task = None
            options_task = None
            options_store = None
            paper_store = None
            paper_venue = None
            tool_journal = None
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
                app.state.paper = None
                app.state.options = None
                app.state.options_error = None
                if paper_database is not None:
                    paper_store = PaperStore(load_dsn(paper_database), owner=True)
                    if preserve_existing:
                        paper_store.read()
                    else:
                        paper_store.initialize(time.time())
                    if not paper_store.reconcile()["balanced"]:
                        raise RuntimeError("Paper journal reconciliation failed at startup")
                    paper_venue = PublicVenue(3)
                    app.state.paper = PaperRuntime(
                        paper_store, paper_venue, database.parent / "paper-stream.sqlite"
                    )
                    try:
                        present = paper_store.connection.execute(
                            "SELECT to_regclass('options_paper.paper_state') IS NOT NULL AS present"
                        ).fetchone()
                        if not preserve_existing or (present and present["present"]):
                            options_store = OptionsStore(load_dsn(paper_database))
                        if options_store is not None:
                            if preserve_existing:
                                options_store.read()
                            else:
                                options_store.initialize(time.time())
                        if options_store and not options_store.reconcile()["balanced"]:
                            raise RuntimeError("Options journal reconciliation failed")
                        if options_store:
                            app.state.options = OptionsRuntime(options_store)
                    except Exception:
                        if preserve_existing:
                            raise
                        app.state.options_error = (
                            "Options account needs attention; spot trading continues"
                        )
                if preserve_existing:
                    if paper_store is None:
                        raise RuntimeError("Managed updates require an existing paper account")
                    verify_startup(
                        source,
                        database.parent.parent,
                        app.state.source_at_start,
                        paper_store,
                        options_store,
                    )
                # The account checkpoint must pass before any feed or financial worker starts.
                if background:
                    task = asyncio.create_task(app.state.monitor.run())
                    if app.state.paper:
                        paper_task = asyncio.create_task(app.state.paper.run())
                    if app.state.options:
                        options_task = asyncio.create_task(app.state.options.run())
                yield
            finally:
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

    @app.get("/api/installation")
    async def installation(request: Request) -> dict[str, Any]:
        return await asyncio.to_thread(
            public_status, request.app.state.source_at_start, database.parent / STATUS_NAME
        )

    @app.post("/api/installation/check")
    async def check_main(request: Request) -> dict[str, Any]:
        origin = request.headers.get("origin")
        if request.headers.get("x-local-operator") != "1" or (
            origin
            and (
                urlsplit(origin).scheme != "http"
                or urlsplit(origin).netloc != request.headers.get("host")
            )
        ):
            raise HTTPException(403, "Local operator request required")
        if (
            request.app.state.update_busy
            or time.monotonic() - request.app.state.last_update_check < 30
        ):
            raise HTTPException(429, "An update check is running or was just completed")
        request.app.state.update_busy = True
        request.app.state.last_update_check = time.monotonic()
        try:
            # Never block the financial event loop on GitHub or invoke an installer here.
            await asyncio.to_thread(updates.check)
        except (RuntimeError, OSError) as exc:
            raise HTTPException(
                503, "Main check unavailable; the running app is unchanged"
            ) from exc
        finally:
            request.app.state.update_busy = False
        return await installation(request)

    @app.get("/api/paper/quotes")
    async def paper_quotes(request: Request) -> dict[str, Any]:
        paper: PaperRuntime | None = request.app.state.paper
        return paper.quotes() if paper else {"enabled": False, "markets": []}

    @app.get("/api/research/trials")
    def research_trials() -> dict[str, Any]:
        # Runs in FastAPI's worker pool, outside the trading event loop.
        return model_trials.snapshot()

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

    @app.get("/api/paper/journal")
    async def paper_journal(
        request: Request, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)
    ) -> dict[str, Any]:
        paper: PaperRuntime | None = request.app.state.paper
        if paper is None:
            raise HTTPException(409, "Paper experiment is not enabled")
        return paper.store.export(after, limit)

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
    async def health(request: Request) -> dict[str, str]:
        monitor = request.app.state.monitor
        paper: PaperRuntime | None = request.app.state.paper
        return {
            "service": "running",
            "mode": "paper",
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
