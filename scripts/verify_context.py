"""Finite native local context checks; synthetic fixtures, no provider calls."""

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


def benchmark(output):
    with tempfile.TemporaryDirectory(prefix="cp13-finite-") as directory:
        lab = ExperimentLab(Path(directory) / "experiments.sqlite3", None, lambda: True)
        results = []
        plan, rows = memory_fixture()
        for i, mode in enumerate(("context_regime", "order_flow")):
            # Separate consumed windows: two predeclared independent fixtures.
            shift = i * 42000
            shifted = json.loads(json.dumps(rows))
            for row in shifted:
                for key in ("cutoff", "start_at", "horizon_at", "expires_at"):
                    row["descriptor"][key] -= shift
                row["executable_label"]["available_at"] -= shift
            p = plan.model_copy(
                update={
                    "request_id": "context-qa-" + mode.replace("_", "-"),
                    "experiment_mode": mode,
                    "test_start": plan.test_start - shift,
                    "test_end": plan.test_start + 39000 - shift,
                }
            )
            lab.registry.reserve(p, code_fingerprint())
            lab.registry.inputs(
                p.request_id, {"rows": shifted, "records": [], "source_files": source_hashes()}
            )
            asyncio.run(lab.run_once())
            job = lab.registry.get(p.request_id)
            assert job["status"] == "completed"
            events = [
                json.loads(e["body"]) for e in job["events"] if e["kind"] == "worker_resources"
            ]
            resources = events[-1]
            resources.pop("supervised_pid", None)
            assert resources["wall_seconds"] < 25
            assert resources["peak_rss_bytes"] < 256 * 1024**2
            assert not job["result"]["eligible_for_forward_review"]
            results.append({"mode": mode, "resources": resources, "result": job["result"]})
        receipt = {
            "scope": "Native bounded synthetic local comparisons; no market or provider proof",
            "source_sha256": code_fingerprint(),
            "results": results,
            "paid_usd": "0",
            "whole_account_advantage": None,
        }
        output.write_text(json.dumps(receipt, indent=2), encoding="utf-8", newline="\n")
        print(json.dumps([{"mode": r["mode"], "resources": r["resources"]} for r in results]))
        lab.registry.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["benchmark", "serve"])
    parser.add_argument("--output", type=Path, default=Path("data/cp13-native.json"))
    parser.add_argument("--port", type=int, default=8796)
    args = parser.parse_args()
    benchmark(args.output) if args.mode == "benchmark" else serve(args.port, research=True)
