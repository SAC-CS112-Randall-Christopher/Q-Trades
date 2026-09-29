"""Predeclared synthetic large-history receipt/read and financial-write comparison."""

import argparse
import hashlib
import json
import platform
import subprocess
import tempfile
import time
import tracemalloc
from pathlib import Path

from verify_cp3 import disposable, summary
from verify_lab import setup

from trading.experiment_registry import ExperimentPlan, ExperimentRegistry
from trading.paper_learning import retain_report

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = {
    "registry_reads": 30,
    "financial_transactions": 24,
    "accounts": 20,
    "retained_reports": 32,
    "discarded_windows_per_report": 512,
    "input": "Synthetic bounded maximum-history projection and 12,000-row frozen input",
    "authority": "Software efficiency only; no profitability or market timing claim",
}


def measure(output):
    receipt = {
        "contract": CONTRACT,
        "declared_at": time.time(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "implementation_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                ROOT / "src/trading/experiment_registry.py",
                ROOT / "src/trading/paper_learning.py",
                ROOT / "src/trading/paper_store.py",
            ]
        },
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    now = time.time()
    with tempfile.TemporaryDirectory(prefix="qtrades-efficiency-") as folder:
        registry = ExperimentRegistry(Path(folder) / "research.sqlite")
        plan = ExperimentPlan(
            request_id="efficiency-fixture-0001",
            name="Synthetic size fixture",
            mechanism="Synthetic resource fixture without a market hypothesis",
            falsification="No financial or scientific authority from this fixture",
            test_start=now - 3600,
            test_end=now - 60,
            as_of=now,
        )
        registry.reserve(plan, "0" * 64)
        snapshot = {
            "manifest": {
                "rows": 12000,
                "older_rows_omitted": False,
                "evidence_kind": "synthetic_qa",
            },
            "rows": [
                {
                    "id": i,
                    "at": now - 720000 + i * 60,
                    "body": {"symbol": "BTCUSD", "minute": i, "synthetic_depth_detail": "x" * 470},
                }
                for i in range(12000)
            ],
        }
        registry.inputs(plan.request_id, snapshot)
        input_bytes = len(json.dumps(snapshot, sort_keys=True).encode())
        del snapshot
        timings = []
        for _ in range(CONTRACT["registry_reads"]):
            start = time.perf_counter()
            value = registry.get(plan.request_id)
            timings.append((time.perf_counter() - start) * 1000)
            assert "snapshot" not in value and value["manifest"]["rows"] == 12000
        tracemalloc.start()
        registry.get(plan.request_id)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        receipt["registry"] = {
            "input_bytes": input_bytes,
            "get_ms": summary(timings),
            "single_read_allocation_peak_bytes": peak,
        }
        registry.close()
    with disposable() as store:
        store.transact(now, lambda e: setup(e, 20))

        def history(engine):
            for i in range(CONTRACT["retained_reports"]):
                report = {
                    "candidate": "primary",
                    "control": None,
                    "decision": "no_promotion",
                    "created_at": now,
                    "evidence_kind": "synthetic_qa",
                    "reasons": ["Synthetic maximum-history storage fixture"],
                    "daily_blocks": [{"day": d, "incumbent_excess": 0} for d in range(80)],
                    "discarded_windows": [
                        {
                            "start": now - j * 14400,
                            "end": now - (j - 1) * 14400,
                            "reason": (
                                "Synthetic unqualified or previously consumed information; "
                                "retain the entire rejected history"
                            ),
                        }
                        for j in range(512)
                    ],
                    "source_event_ids": list(range(512)),
                }
                retain_report(engine, f"efficiency-report-{i:04}", report)

        store.transact(now, history)
        state_bytes = len(json.dumps(store.read()).encode())
        commits = []
        for _ in range(CONTRACT["financial_transactions"]):
            start = time.perf_counter()
            store.transact(now, lambda e: None)
            commits.append((time.perf_counter() - start) * 1000)
        receipt["large_history_financial_state"] = {
            "state_bytes": state_bytes,
            "commit_ms": summary(commits),
            "reconciliation": store.reconcile(),
        }
        assert receipt["large_history_financial_state"]["reconciliation"]["balanced"]
    receipt["finished_at"] = time.time()
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "registry_p95_ms": receipt["registry"]["get_ms"]["p95"],
                "state_bytes": state_bytes,
                "commit_p95_ms": summary(commits)["p95"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    measure(parser.parse_args().output)
