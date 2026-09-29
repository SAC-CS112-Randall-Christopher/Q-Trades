"""Actual process-exit and PostgreSQL backup/restore proof, strictly disposable QA data."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from verify_cp3 import disposable, features, frames

from trading.experiment_registry import fingerprint
from trading.paper_campaigns import CampaignSpec, create_campaign
from trading.paper_store import PaperStore

ROOT = Path(__file__).resolve().parents[1]
PG_BIN = Path(r"C:\Program Files\PostgreSQL\17\bin")


def child(path):
    payload = json.loads(path.read_text())
    store = PaperStore(payload["dsn"], owner=True)
    spec = CampaignSpec.model_validate(payload["spec"])
    store.transact(time.time(), lambda e: create_campaign(e, spec))
    # Simulate a committed request whose caller never gets its acknowledgment.
    os._exit(17)


def verify(output):
    receipt = {
        "fixture": "Generated synthetic PostgreSQL schema/database only",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "started_at": time.time(),
        "checks": [],
    }
    with disposable() as store:
        dsn = store.connection.info.dsn
        schema = store.connection.execute("SELECT current_schema() AS s").fetchone()["s"]
        assert schema.startswith("cp3qa_") and len(schema) == 38
        payload = {
            "dsn": dsn,
            "spec": {
                "request_id": "crash-qa-" + uuid.uuid4().hex,
                "name": "Committed acknowledgment loss",
                "accounts": [
                    {
                        "label": f"Crash QA {i + 1}",
                        "starting_cash": "100",
                        "strategy": "breakout-v1",
                        "execution_profile": "paper-rest-ioc-v1",
                        "operating_daily_usd": "0",
                    }
                    for i in range(10)
                ],
            },
        }
        spec = CampaignSpec.model_validate(payload["spec"])
        before = store.read()
        try:
            competing = PaperStore(dsn, owner=True)
        except RuntimeError:
            receipt["checks"].append(
                {"name": "Exclusive writer rejects contention", "passed": True}
            )
        else:
            competing.close()
            raise AssertionError("Second financial writer unexpectedly acquired ownership")
        intent = ROOT / "data" / ("crash-intent-" + uuid.uuid4().hex + ".json")
        intent.write_text(json.dumps(payload))
        store.close()
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.run(
                [sys.executable, __file__, "child", "--intent", str(intent)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=20,
                creationflags=flags,
            )
            assert process.returncode == 17, "Crash fixture failed before its committed boundary"
            recovered = PaperStore(dsn, owner=True)
            store.connection = recovered.connection
            state, events = store.read(), store.export(0, 1000)
            assert len(state["campaigns"][spec.request_id]["accounts"]) == 10
            store.transact(time.time(), lambda e: create_campaign(e, spec))
            assert store.read()["accounts"] == state["accounts"]
            assert store.export(0, 1000) == events
            assert sum(e["kind"] == "campaign_account_funded" for e in events["records"]) == 10
            assert {n: state["accounts"][n] for n in before["accounts"]} == before["accounts"]
            receipt["checks"].append(
                {
                    "name": "Actual committed child exit/restart cannot double-fund",
                    "passed": store.reconcile()["balanced"],
                    "child_exit": 17,
                }
            )
        finally:
            intent.unlink(missing_ok=True)  # Exact known QA file; never an operating config.
        now = time.time()
        store.transact(now, lambda e: e.tick(frames(now, 1), features(1, True)))
        store.transact(now + 2, lambda e: e.tick(frames(now + 2, 2), {}))
        backup = ROOT / "data" / ("qa-backup-" + uuid.uuid4().hex + ".dump")
        state_hash = fingerprint(store.read())
        journal_hash = fingerprint(store.export(0, 10000))
        subprocess.run(
            [
                str(PG_BIN / "pg_dump.exe"),
                "--dbname",
                dsn,
                "--schema",
                schema,
                "--format",
                "custom",
                "--file",
                str(backup),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        database = "cp8restore_" + uuid.uuid4().hex
        assert database.startswith("cp8restore_") and len(database) == 43
        admin = psycopg.connect(dsn, autocommit=True)
        clone = None
        created = False
        try:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            created = True
            clone_dsn = make_conninfo(dsn, dbname=database)
            subprocess.run(
                [str(PG_BIN / "pg_restore.exe"), "--dbname", clone_dsn, str(backup)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            clone = PaperStore(clone_dsn, owner=True)
            assert fingerprint(clone.read()) == state_hash
            assert fingerprint(clone.export(0, 10000)) == journal_hash
            assert clone.reconcile()["balanced"]
            receipt["checks"].append(
                {
                    "name": "pg_dump/pg_restore retains exact state and journals",
                    "passed": True,
                    "state_sha256": state_hash,
                    "journal_sha256": journal_hash,
                    "backup_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
                    "backup_bytes": backup.stat().st_size,
                }
            )
        finally:
            if clone:
                clone.close()
            if created:
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
            admin.close()
        receipt["reconciliation"] = store.reconcile()
        receipt["postgres_version"] = store.connection.execute("SHOW server_version").fetchone()[
            "server_version"
        ]
    receipt["finished_at"] = time.time()
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps({"checks": receipt["checks"], "balanced": receipt["reconciliation"]["balanced"]})
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["verify", "child"])
    parser.add_argument("--intent", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "child":
        child(args.intent)
    else:
        verify(args.output)
