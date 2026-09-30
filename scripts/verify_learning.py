"""Finite synthetic growing-memory child/restart checks, no financial writer."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from memory_fixtures import memory_fixture
from verify_evidence import serve

from trading.execution_replay import source_hashes
from trading.experiment_lab import ExperimentLab
from trading.experiment_worker import code_fingerprint
from trading.incremental_memory import LearningJournal


def benchmark(output):
    with tempfile.TemporaryDirectory(prefix="cp14-finite-") as directory:
        lab = ExperimentLab(Path(directory) / "experiments.sqlite3", None, lambda: True)
        try:
            plan, rows = memory_fixture()
            plan = plan.model_copy(update={"experiment_mode": "growing_memory"})
            lab.registry.reserve(plan, code_fingerprint())
            lab.registry.inputs(
                plan.request_id, {"rows": rows, "records": [], "source_files": source_hashes()}
            )
            asyncio.run(lab.run_once())
            job = lab.registry.get(plan.request_id)
            assert job["status"] == "completed", job["reason"]
            resources = next(
                json.loads(e["body"])
                for e in reversed(job["events"])
                if e["kind"] == "worker_resources"
            )
            resources.pop("supervised_pid", None)
            assert resources["wall_seconds"] < 25 and resources["peak_rss_bytes"] < 256 * 1024**2
            counts = LearningJournal(lab.registry).page(plan.request_id)["counts"]
            assert counts == {"prediction": 24, "score": 24, "update": 9}
            lab.registry.close()
            from trading.experiment_registry import ExperimentRegistry

            lab.registry = ExperimentRegistry(Path(directory) / "experiments.sqlite3")
            assert LearningJournal(lab.registry).page(plan.request_id)["counts"] == counts
            receipt = {
                "scope": "Native synthetic incremental procedure; not prospective market evidence",
                "source_sha256": code_fingerprint(),
                "resources": resources,
                "counts_after_reopen": counts,
                "result": job["result"],
                "financial_state_changed": False,
            }
            output.write_text(json.dumps(receipt, indent=2), encoding="utf-8", newline="\n")
            print(json.dumps({"resources": resources, "counts_after_reopen": counts}))
        finally:
            lab.registry.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["benchmark", "serve"])
    parser.add_argument("--output", type=Path, default=Path("data/cp14-native.json"))
    parser.add_argument("--port", type=int, default=8797)
    args = parser.parse_args()
    benchmark(args.output) if args.mode == "benchmark" else serve(args.port, research=True)
