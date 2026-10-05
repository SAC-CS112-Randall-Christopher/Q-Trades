"""Disposable loopback API/UI fixture, never an installed-state acceptance run.

Requires an explicit disposable PostgreSQL config, QA directory and access token.
R63-1 transitions run the actual producer, owned child and runtime loop. Optional
query controls and presentation liveness are synthetic. The original seven-state
compatibility fixture additionally injects explicit failure/expiry presentation.
"""

import argparse
import asyncio
import copy
import json
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
import uvicorn
from fastapi import Header, HTTPException
from psycopg import sql
from psycopg.conninfo import make_conninfo

from trading.api import create_app
from trading.config import Settings
from trading.financial_readback import FinancialReadback
from trading.paper_store import load_dsn
from trading.research_notices import operational_conditions


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from financial_monitoring_fixture import FinancialMonitoringFixture

    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--database-config", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--port", type=int, default=58960)
    args = parser.parse_args()
    token = os.environ["QTRADES_BROWSER_QA_TOKEN"]
    args.directory.mkdir(parents=True, exist_ok=False)
    schema = "test_monitoring_" + uuid.uuid4().hex
    admin = psycopg.connect(load_dsn(args.database_config), autocommit=True)
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    config = args.directory / "paper-database.json"
    config.write_text(
        json.dumps(
            {
                "dsn": make_conninfo(
                    admin.info.dsn, password=admin.info.password, options=f"-c search_path={schema}"
                )
            }
        )
    )
    app = create_app(
        Settings(),
        args.directory / "monitor.sqlite",
        background=False,
        web_dist=args.web_dist,
        paper_database=config,
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )
    controller = None
    retained_history = None
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def qa_lifespan(application):
        async with original_lifespan(application):
            try:
                yield
            finally:
                if controller is not None:
                    await controller.stop()

    app.router.lifespan_context = qa_lifespan

    def authorize(x_qa_token):
        if x_qa_token != token:
            raise HTTPException(403)

    def present():
        # Isolate the monitoring prerequisite from synthetic paper/feed liveness
        # and workstation capture reserve. No financial work or model is run.
        paper = app.state.paper
        paper.running = True
        paper.disk_free = 10 * 1024**3
        paper.state["last_tick"] = time.time()
        paper.state["evidence_kind"] = "synthetic_browser_fixture"

    def observe_notices():
        present()
        now = time.time()
        app.state.lab.notices.observe(operational_conditions(app.state.paper, now), now)

    def probe():
        paper, lab = app.state.paper, app.state.lab
        return {
            "journal": paper.journal_status(),
            "research_ready": lab.can_research(),
            "producer": operational_conditions(paper, time.time()),
            "registry_changes": lab.registry.db.total_changes,
            "experiments": lab.registry.db.execute(
                "SELECT count(*) FROM experiments"
            ).fetchone()[0],
            "history_retained": retained_history is None or paper.recent == retained_history,
            "history_count": len(paper.recent),
            "fixture": controller.snapshot() if controller is not None else None,
            "sample": paper._readback_sample,
        }

    @app.get("/__qa/r63-1/probe")
    async def transition_probe(x_qa_token: str = Header()):
        authorize(x_qa_token)
        present()
        return probe()

    @app.post("/__qa/r63-1/{mode}")
    async def transition(mode: str, x_qa_token: str = Header()):
        nonlocal controller, retained_history
        authorize(x_qa_token)
        present()
        if mode == "start":
            if controller is not None:
                raise HTTPException(409, "The owned QA reader is already started")
            controller = FinancialMonitoringFixture(app.state.paper)
            await controller.start()
            await controller.wait_sample()
            retained_history = copy.deepcopy(app.state.paper.recent)
        elif controller is None:
            raise HTTPException(409, "Start the isolated transition fixture first")
        elif mode == "confirm":
            # Real distinct observations preserve the registry's existing 3s
            # confirmation requirement without changing a producer timestamp.
            await asyncio.sleep(3.1)
        elif mode == "stop":
            await controller.stop()
            controller = None
            return {"stopped": True, "shutdown": app.state.paper._readback_shutdown}
        else:
            previous_sample, previous_audit = controller.completed_at, controller.audit_at
            if mode in {"fail-recent", "fail-storage_usage", "fail-both"}:
                names = ("recent", "storage_usage") if mode == "fail-both" else (mode[5:],)
                controller.fail(*names)
                if "storage_usage" in names:
                    controller.make_audit_due()
                await controller.wait_sample(previous_sample)
            elif mode == "routine-hold":
                controller.hold("recent")
                await controller.wait_held("recent")
            elif mode == "routine-release":
                controller.release("recent")
                await controller.wait_sample(previous_sample)
            elif mode in {"hold-recent", "hold-storage_usage", "timeout-hold"}:
                name = "recent" if mode == "timeout-hold" else mode[5:]
                if mode == "timeout-hold":
                    controller.recover(name)
                controller.hold(name)
                await controller.wait_held(name)
                await controller.wait_audit(previous_audit)
            elif mode in {"repeat-recent", "repeat-storage_usage"}:
                controller.release(mode[7:])
                await controller.wait_sample(previous_sample)
            elif mode in {"recover-recent", "recover-storage_usage", "recover-both"}:
                names = ("recent", "storage_usage") if mode == "recover-both" else (mode[8:],)
                controller.recover(*names)
                for name in names:
                    controller.release(name)
                await controller.wait_sample(previous_sample)
            elif mode == "timeout-complete":
                async with asyncio.timeout(22):
                    while (
                        app.state.paper._readback_error
                        != "Financial readback operation deadline exceeded"
                        or app.state.paper._readback_shutdown is None
                    ):
                        if controller.task.done():
                            controller.task.result()
                        await asyncio.sleep(0.01)
            else:
                raise HTTPException(404)
        observe_notices()
        return probe()

    @app.post("/__qa/monitoring/{mode}")
    def fixture(mode: str, x_qa_token: str = Header()):
        authorize(x_qa_token)
        paper = app.state.paper
        if mode == "stop":
            server.should_exit = True
            return {"stopping": True}
        if mode == "pending":
            paper.receipts = {}
            paper._readback_audit_mono, paper._readback_error = None, None
        elif mode == "failure":
            paper._readback_error = "Synthetic monitoring connection outage"
        elif mode == "expired":
            paper._readback_error = None
            paper._readback_audit_mono = time.monotonic() - 121
        elif mode in {"balanced", "imbalanced"}:
            if mode == "imbalanced":
                paper.store.transact(
                    time.time(), lambda e: e.state["accounts"]["primary"].update(cash="90")
                )
            reader = FinancialReadback(paper.store)
            try:
                receipt = reader.sample(audit=True)
                try:
                    paper._accept_financial_audit(receipt)
                    paper._accept_financial_sample(receipt)
                except RuntimeError as exc:
                    paper.error = str(exc)
            finally:
                reader.close()
        else:
            raise HTTPException(404)
        paper.running = mode != "imbalanced"
        paper.state["last_tick"] = time.time()
        paper.state["evidence_kind"] = "synthetic_browser_fixture"
        return paper.snapshot()["journal"]

    try:
        server.run()
    finally:
        assert schema.startswith("test_monitoring_") and len(schema) == 48
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


if __name__ == "__main__":
    main()
