"""Finite native estimator checks. Synthetic target fixtures are not execution proof."""

import argparse
import asyncio
import hashlib
import json
import tempfile
import time
from pathlib import Path

from memory_fixtures import memory_fixture
from verify_evidence import serve

from trading.execution_replay import source_hashes
from trading.experiment_lab import ExperimentLab
from trading.experiment_worker import code_fingerprint
from trading.memory_quality import CONTRACT, predict


def benchmark(output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="cp12-finite-") as directory:
        lab = ExperimentLab(Path(directory) / "experiments.sqlite3", None, lambda: True)
        plan, rows = memory_fixture()
        lab.registry.reserve(plan, code_fingerprint())
        lab.registry.inputs(
            plan.request_id, {"rows": rows, "records": [], "source_files": source_hashes()}
        )
        asyncio.run(lab.run_once())
        job = lab.registry.get(plan.request_id)
        assert job and job["status"] == "completed"
        result = job["result"]
        assert (
            result["evidence_kind"] == "synthetic_qa" and not result["eligible_for_forward_review"]
        )
        artifact = result["candidate_group"][0]["artifact"]
        latencies = []
        for _ in range(200):
            started = time.perf_counter()
            predict(rows[-1]["descriptor"], artifact, rows[-1]["descriptor"]["cutoff"])
            latencies.append((time.perf_counter() - started) * 1000)
        latencies.sort()
        events = [json.loads(e["body"]) for e in job["events"] if e["kind"] == "worker_resources"]
        resources = events[-1]
        resources.pop("supervised_pid", None)
        identities = [
            json.loads(e["body"]) for e in job["events"] if e["kind"] == "worker_identity"
        ]
        identity = identities[-1]
        identity.pop("pid", None)
        receipt = {
            "scope": "Native two-processor child; synthetic labels; linked fills tested separately",
            "checked_at": "2026-09-30",
            "contract": CONTRACT,
            "source_sha256": code_fingerprint(),
            "fixtures_sha256": hashlib.sha256(
                Path(__file__).with_name("memory_fixtures.py").read_bytes()
            ).hexdigest(),
            "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "resources": resources,
            "os_identity": identity,
            "inference_ms": {
                "p50": latencies[99],
                "p95": latencies[189],
                "p99": latencies[197],
                "max": latencies[-1],
            },
            "checks": {
                "completed": True,
                "synthetic_cannot_qualify": True,
                "wall_budget": resources["wall_seconds"] < 25,
                "memory_budget": resources["peak_rss_bytes"] < 256 * 1024**2,
                "processors": identity["processors_allowed"] <= 2,
            },
            "result": result,
            "limits": "Repeated inference adds no market samples; monetary effects unknown",
        }
        output.write_text(json.dumps(receipt, indent=2), encoding="utf-8", newline="\n")
        print(
            json.dumps(
                {
                    "checks": receipt["checks"],
                    "resources": resources,
                    "inference_ms": receipt["inference_ms"],
                }
            ),
            flush=True,
        )
        lab.registry.close()
        assert all(receipt["checks"].values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["benchmark", "serve"])
    parser.add_argument("--output", type=Path, default=Path("data/cp12-native.json"))
    parser.add_argument("--port", type=int, default=8795)
    args = parser.parse_args()
    if args.mode == "serve":
        serve(args.port, research=True)
    else:
        benchmark(args.output)
