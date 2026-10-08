"""Compiled dashboard + actual disposable writer; synthetic workload, no market/model calls."""

import argparse
import json
import os
import time
import uuid
from pathlib import Path

import psycopg
import uvicorn
from fastapi import Header, HTTPException
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from starlette.responses import JSONResponse

from trading.api import create_app
from trading.config import Settings
from trading.engine_diagnostics import EngineWorkPressurePolicy
from trading.financial_readback import FinancialReadback
from trading.paper_store import load_dsn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--database-config", type=Path, required=True)
    parser.add_argument("--web-dist", type=Path, required=True)
    parser.add_argument("--port", type=int, default=58966)
    args = parser.parse_args()
    token = os.environ["QTRADES_BROWSER_QA_TOKEN"]
    dsn = load_dsn(args.database_config)
    identity = conninfo_to_dict(dsn)
    if identity.get("host") != "127.0.0.1" or identity.get("port") != "54544":
        raise ValueError("Explicit local disposable QA address required")
    args.directory.mkdir(parents=True, exist_ok=False)
    schema = "test_redesign_" + uuid.uuid4().hex
    admin = psycopg.connect(dsn, autocommit=True)
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    config = args.directory / "paper-database.json"
    config.write_text(json.dumps({"dsn": make_conninfo(dsn, options=f"-c search_path={schema}")}))
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
    mode = "normal"
    posts = []
    prefix = None
    audit_at = 0.0

    def present():
        nonlocal prefix, audit_at
        paper = app.state.paper
        # Execute an actual no-market tick so valuation is currently observed;
        # setting last_tick alone would falsely freshen expired account marks.
        paper._transact_state(time.time(), lambda engine: engine.tick({}, {}))
        if prefix is None:
            prefix = paper.store.export(0, 1000)["records"]
        paper.running = True
        paper.state["evidence_kind"] = "synthetic_redesign_browser_fixture"
        paper.disk_free = 10 * 1024**3
        now = time.monotonic()
        paper._work_pressure = EngineWorkPressurePolicy()
        for offset in range(20):
            paper._work_pressure.observe(20, now - (19 - offset) * 0.55)
        if now - audit_at > 30:
            reader = FinancialReadback(paper.store)
            try:
                receipt = reader.sample(audit=True)
                paper._accept_financial_audit(receipt)
                paper._accept_financial_sample(receipt)
                audit_at = now
            finally:
                reader.close()

    @app.middleware("http")
    async def qa_state(request, call_next):
        nonlocal mode
        if request.url.path.startswith("/api/"):
            present()
        if request.method == "POST" and request.url.path.endswith("/strategy"):
            body = await request.json()
            selected_mode, mode = mode, "normal"
            if selected_mode == "refuse":
                posts.append({"body": body, "fixture": "precommit_refusal", "status": 409})
                return JSONResponse(
                    {"detail": "Synthetic precommit refusal; no change committed"}, status_code=409
                )
            response = await call_next(request)
            posts.append(
                {"body": body, "fixture": selected_mode, "actual_status": response.status_code}
            )
            if selected_mode == "lost_ack" and response.status_code == 200:
                return JSONResponse(
                    {"detail": "Synthetic acknowledgment lost after actual native commit"},
                    status_code=503,
                )
            return response
        return await call_next(request)

    def authorize(value):
        if value != token:
            raise HTTPException(403)

    @app.get("/__qa/probe")
    def probe(x_qa_token: str = Header()):
        authorize(x_qa_token)
        present()
        paper = app.state.paper
        records = paper.store.export(0, 1000)["records"]
        return {
            "accounts": paper.store.read()["accounts"],
            "posts": posts,
            "prefix_preserved": records[: len(prefix)] == prefix,
            "strategy_events": [r for r in records if r["kind"] == "account_strategy_changed"],
            "balanced": paper.store.reconcile()["balanced"],
            "schema": schema,
            "evidence_kind": "synthetic_workload_actual_native_writer",
        }

    @app.post("/__qa/{action}")
    def control(action: str, x_qa_token: str = Header()):
        nonlocal mode
        authorize(x_qa_token)
        if action == "stop":
            server.should_exit = True
            return {"stopping": True}
        if action not in {"normal", "refuse", "lost_ack"}:
            raise HTTPException(404)
        mode = action
        return {"next_post_fixture": mode}

    try:
        server.run()
    finally:
        # Only this newly generated, explicitly owned disposable schema is removed.
        assert schema.startswith("test_redesign_") and len(schema) == 46
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


if __name__ == "__main__":
    main()
