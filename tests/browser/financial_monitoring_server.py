"""Disposable loopback API/UI fixture, never an installed-state acceptance run.

Requires an explicit disposable PostgreSQL config, QA directory and access token.
The only injected fields are monitoring failures/age and presentation liveness.
Balanced/imbalanced receipts come from the actual financial reader and journal.
"""

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
from psycopg.conninfo import make_conninfo

from trading.api import create_app
from trading.config import Settings
from trading.financial_readback import FinancialReadback
from trading.paper_store import load_dsn


def main():
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

    @app.post("/__qa/monitoring/{mode}")
    def fixture(mode: str, x_qa_token: str = Header()):
        if x_qa_token != token:
            raise HTTPException(403)
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
