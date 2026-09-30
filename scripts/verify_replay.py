"""Native finite CP11 proof in disposable schemas; never a real market/account result."""

import argparse
import asyncio
import hashlib
import json
import tempfile
import time
from pathlib import Path

from verify_cp3 import disposable
from verify_evidence import recorded_tick, serve, verify_database

from trading.evidence_runtime import EvidenceRecorder
from trading.execution_replay import CONTRACT, source_hashes
from trading.paper_campaigns import CampaignSpec, create_campaign
from trading.replay_lab import ReplayLab, ReplayPlan
from trading.research_evidence import digest, evidence_page

ROOT = Path(__file__).resolve().parents[1]


def benchmark(output: Path) -> None:
    verify_database()
    receipt = {
        "scope": "Actual native Windows child, disposable PostgreSQL schemas, synthetic books only",
        "contract": CONTRACT,
        "source_files": source_hashes(),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": [],
        "acceptance": {
            "accounts": [1, 10, 20],
            "records": 16,
            "wall_seconds_max": 25,
            "child_rss_mib_max": 256,
            "source_state_preserved": True,
            "original_journal_balanced": True,
            "baseline_state_events_match": True,
        },
        "limits": (
            "Finite synthetic software proof; no real feed latency, edge or horizon acceptance"
        ),
    }
    for count in (1, 10, 20):
        with tempfile.TemporaryDirectory(prefix="cp11-finite-") as directory, disposable() as store:
            path = Path(directory)

            def configure(engine, count=count):
                engine.universe_experiment(["BTCUSD", "ETHUSD"])
                spec = CampaignSpec.model_validate(
                    {
                        "request_id": f"cp11-accounts-{count:02d}",
                        "name": "Synthetic CP11 replay",
                        "accounts": [
                            {
                                "label": f"Replay QA {i}",
                                "starting_cash": "100",
                                "strategy": "breakout-v1",
                                "execution_profile": "paper-rest-ioc-v1",
                                "operating_daily_usd": "0",
                            }
                            for i in range(14)
                        ],
                    }
                )
                members = create_campaign(engine, spec)["campaign"]["accounts"]
                # Disposable QA only: 1/10 project a subset; 20 retains all six originals +14.
                if count < 20:
                    engine.state["accounts"] = {
                        n: engine.state["accounts"][n] for n in members[:count]
                    }
                assert len(engine.state["accounts"]) == count

            store.transact(time.time(), configure)
            recorder = EvidenceRecorder(path / "research-evidence.sqlite")
            for tick in range(16):
                recorded_tick(store, recorder, time.time(), tick + 1)
                time.sleep(0.25)
            before = digest(store.read())
            rows = evidence_page(recorder.path, limit=50)["records"]
            lab = ReplayLab(path / "execution-replay.sqlite", recorder.path, lambda: True)
            plan = ReplayPlan(
                request_id=f"cp11-native-{count:02d}",
                record_id=min(r["id"] for r in rows),
                records=16,
            )
            lab.enqueue(plan)
            asyncio.run(lab.run_once())
            job = lab.registry.get(plan.request_id)
            result = job.get("result") or {}
            actual = len(store.read()["accounts"])
            checks = {
                "completed": job["status"] == "completed",
                "reconciled": result.get("status") == "reconciled",
                "actual_account_count": actual == count,
                "source_state_preserved": digest(store.read()) == before,
                "original_journal_balanced": store.reconcile()["balanced"],
                "complete_slice": result.get("coverage", {}).get("supported") == 16,
                "wall_limit": (job.get("resources") or {}).get("wall_seconds", 26) < 25,
                "memory_limit": (job.get("resources") or {}).get("peak_rss_bytes", 257 * 1024**2)
                < 256 * 1024**2,
            }
            receipt["cases"].append(
                {
                    "requested_accounts": count,
                    "actual_accounts": actual,
                    "checks": checks,
                    "passed": all(checks.values()),
                    "status": job["status"],
                    "error": job["error"],
                    "resources": job.get("resources"),
                    "compute": result.get("resources"),
                    "coverage": result.get("coverage"),
                    "baseline": result.get("baseline"),
                    "scenario_summary": [
                        {
                            "scenario": s["scenario"],
                            "balanced": s["balanced"],
                            "condition_stressed_ticks": s["condition_stressed_ticks"],
                            "fills": len(s["fills"]),
                            "closed_trades": len(s["closed_trades"]),
                            "accounts": s["accounts"],
                        }
                        for s in result.get("scenarios", [])
                    ],
                }
            )
            for case in receipt["cases"]:
                if case["compute"]:
                    case["compute"].get("child_limits", {}).pop("pid", None)
            output.write_text(json.dumps(receipt, indent=2), encoding="utf-8", newline="\n")
            print(
                json.dumps(
                    {
                        "accounts": actual,
                        "passed": all(checks.values()),
                        "resources": job.get("resources"),
                    }
                ),
                flush=True,
            )
            lab.registry.close()
            recorder._archive.close()
    if not all(case["passed"] for case in receipt["cases"]):
        raise SystemExit("Original finite CP11 receipt retained; failed criteria remain failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["benchmark", "serve"])
    parser.add_argument("--output", type=Path, default=ROOT / "data/cp11-native-replay.json")
    parser.add_argument("--port", type=int, default=8794)
    args = parser.parse_args()
    benchmark(args.output) if args.mode == "benchmark" else serve(args.port, replay=True)
