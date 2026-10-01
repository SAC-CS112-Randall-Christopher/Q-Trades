"""Bounded disposable SCRAM reader verification; refuses the installed database."""

import hashlib
import json
import secrets
import time
import uuid
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from trading.api import create_app
from trading.config import Settings
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore, load_dsn

ROOT = Path(__file__).resolve().parents[1]


def verify() -> dict[str, object]:
    dsn = load_dsn(ROOT / "data/paper-database.json")
    params = conninfo_to_dict(dsn)
    if params.get("host") != "127.0.0.1" or params.get("port") not in {"55633", "55641"}:
        raise ValueError("Requires separately owned QA PostgreSQL on port 55633 or 55641")
    directory = ROOT / "data" / ("trade-history-auth-" + uuid.uuid4().hex)
    directory.mkdir()
    token = uuid.uuid4().hex
    role, schema = "history_auth_" + token, "history_auth_case_" + token
    password = secrets.token_urlsafe(32) + " ' \\ QA"
    admin = psycopg.connect(dsn, autocommit=True)
    store = None
    created_role = created_schema = changed_hba = False
    receipt: dict[str, object] = {}
    try:
        data = Path(admin.execute("SHOW data_directory").fetchone()[0]).resolve()
        hba = Path(admin.execute("SHOW hba_file").fetchone()[0]).resolve()
        if data != (ROOT / "data/qa-pg").resolve() or hba != data / "pg_hba.conf":
            raise ValueError("QA cluster ownership differs; no authentication change applied")
        original = hba.read_bytes()
        (directory / "pg_hba.original").write_bytes(original)
        rule = f"host all {role} 127.0.0.1/32 scram-sha-256\n".encode()
        changed = rule + original
        admin.execute("SET password_encryption = 'scram-sha-256'")
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        created_role = True
        admin.execute(
            sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        created_schema = True
        hba.write_bytes(changed)
        changed_hba = True
        assert admin.execute("SELECT pg_reload_conf()").fetchone()[0]
        login = make_conninfo(
            dsn, user=role, password=password, connect_timeout=3, options=f"-c search_path={schema}"
        )
        store = PaperStore(login, owner=True)
        store.initialize(1790000000)
        # SIGHUP is asynchronous. Require an actually rejected redacted login;
        # trust authentication must never satisfy this acceptance check.
        for _ in range(5):
            try:
                stripped = PaperStore(store.connection.info.dsn)
            except psycopg.OperationalError:
                receipt["redacted_login_rejected"] = True
                break
            else:
                stripped.close()
                time.sleep(0.2)
        assert receipt.get("redacted_login_rejected"), "SCRAM rejection not observed"
        state, events = store.read(), store.export(0, 1000)
        runtime = PaperRuntime(store, None)
        with TestClient(create_app(Settings(), directory / "monitor", background=False)) as client:
            client.app.state.paper = runtime
            response = client.get("/api/paper/trades?status=closed")
            assert response.status_code == 200 and response.json()["records"] == []
            assert password not in response.text
        assert state == store.read() and events == store.export(0, 1000)
        assert store.reconcile()["balanced"]
        from trading.scoped_tools import reader

        with reader(runtime) as view:
            snapshot = view.research_account("primary", time.time())
            scoped = view.research_outcomes(snapshot, "BTCUSD")
            assert scoped["market_totals"]["trades"] == 0
            assert (
                view.connection.execute("SHOW transaction_read_only").fetchone()[
                    "transaction_read_only"
                ]
                == "on"
            )
        assert state == store.read() and events == store.export(0, 1000)
        receipt.update(
            auth="scram-sha-256",
            api_status=200,
            financial_state_and_events_preserved=True,
            credential_in_response=False,
            scoped_outcome_password_reader=True,
            repeatable_read_only=True,
        )
    finally:
        if store is not None:
            store.close()
        try:
            if changed_hba:
                if hba.read_bytes() != changed:
                    raise RuntimeError("QA HBA changed concurrently; preserve backup and inspect")
                hba.write_bytes(original)
                assert admin.execute("SELECT pg_reload_conf()").fetchone()[0]
                assert hba.read_bytes() == original
                receipt["qa_hba_restored_sha256"] = hashlib.sha256(original).hexdigest()
            if created_schema:
                admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            if created_role:
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
            receipt["generated_role_and_schema_removed"] = True
        finally:
            admin.close()
            (directory / "receipt.json").write_text(json.dumps(receipt, indent=2))
    return receipt


if __name__ == "__main__":
    print(json.dumps(verify()))
