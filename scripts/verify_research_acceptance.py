"""Predeclare and run finite existing native drivers on the exact owned QA cluster."""

import json
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import psycopg
from psycopg.conninfo import conninfo_to_dict
from verify_lab import benchmark
from verify_scoped_tools import verify

from trading.lab_role_contract import contract_hash
from trading.paper_store import load_dsn

ROOT = Path(__file__).resolve().parents[1]
CLUSTER = Path("C:/Projects/Q-Trades-cp17-tools/data/qa-pg").resolve()


def main():
    dsn = load_dsn(ROOT / "data/paper-database.json")
    info = conninfo_to_dict(dsn)
    if info.get("host") != "127.0.0.1" or info.get("port") != "55641":
        raise ValueError("Requires owned QA cluster; no operating connection")
    with psycopg.connect(dsn) as connection:
        if Path(connection.execute("SHOW data_directory").fetchone()[0]).resolve() != CLUSTER:
            raise ValueError("Actual QA cluster identity differs")
    folder = ROOT / "data" / ("cp23-native-" + uuid.uuid4().hex)
    folder.mkdir()
    declaration = {
        "declared_at": time.time(),
        "source": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "contract_sha256": contract_hash(),
        "plan": "docs/CP23_ACCEPTANCE_PLAN.md",
        "workloads": "6 existing 30-second idle/numerical cases + 2 scoped-read cases",
        "qualification": "Not established; actual LLM busy workload excluded while guard blocks",
        "economic_value": "Insufficient prospective matched observation",
    }
    (folder / "declaration.json").write_text(json.dumps(declaration, indent=2))
    sample = httpx.get("http://127.0.0.1:8780/api/status", timeout=8, trust_env=False).json()[
        "paper"
    ]
    guard = {
        k: sample.get(k)
        for k in ("running", "error", "stale", "research_constrained", "performance")
    }
    (folder / "native-role-blocker.json").write_text(json.dumps(guard, indent=2))
    benchmark(folder / "account-load.json", retired_events=1103)
    verify(folder / "scoped-tools.json", CLUSTER)
    print(json.dumps({"receipt_directory": str(folder)}, indent=2))


if __name__ == "__main__":
    main()
