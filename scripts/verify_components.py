"""Finite native CP15 synthetic component proof; original source accounts untouched."""

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path

from verify_cp3 import disposable
from verify_evidence import recorded_tick, serve, verify_database

from trading.evidence_runtime import EvidenceRecorder
from trading.execution_replay import source_hashes
from trading.experiment_lab import ExperimentLab
from trading.experiment_registry import ExperimentPlan
from trading.experiment_worker import code_fingerprint
from trading.paper_campaigns import CampaignSpec, create_campaign
from trading.research_evidence import digest, evidence_page, evidence_record


def benchmark(output):
    verify_database()
    with tempfile.TemporaryDirectory(prefix="cp15-finite-") as directory, disposable() as store:
        path = Path(directory)

        def setup(engine):
            engine.universe_experiment(["BTCUSD", "ETHUSD"])
            spec = CampaignSpec.model_validate(
                {
                    "request_id": "cp15-native-20",
                    "name": "Synthetic component QA",
                    "accounts": [
                        {
                            "label": f"Component QA {i}",
                            "starting_cash": "100",
                            "strategy": "breakout-v1",
                            "execution_profile": "paper-rest-ioc-v1",
                            "operating_daily_usd": "0",
                        }
                        for i in range(14)
                    ],
                }
            )
            create_campaign(engine, spec)

        store.transact(time.time(), setup)
        recorder = EvidenceRecorder(path / "research-evidence.sqlite")
        for i in range(16):
            recorded_tick(store, recorder, time.time(), i + 1)
            time.sleep(0.25)
        original = digest(store.read())
        ids = sorted(r["id"] for r in evidence_page(recorder.path, limit=50)["records"])
        records = [evidence_record(recorder.path, i) for i in ids]
        for r in records:
            r["at"] = r["payload"]["at"]
        cases = []
        for mode in ("component_exit", "component_size", "observation_priority"):
            # Same synthetic source, separate disposable registries; no market inference.
            lab = ExperimentLab(path / (mode + ".sqlite"), None, lambda: True)
            try:
                plan = ExperimentPlan(
                    request_id=mode.replace("_", "-") + "-native-fixture",
                    name="Synthetic component QA",
                    mechanism="One frozen component may change finite modeled execution.",
                    falsification="Retain unknown or negative evidence without promotion.",
                    experiment_mode=mode,
                    horizon_minutes=45,
                    evidence_kind="synthetic_qa",
                    as_of=time.time(),
                    test_start=records[0]["at"] - 1,
                    test_end=records[-1]["at"] + 0.001,
                )
                snapshot = {"rows": [], "records": records, "source_files": source_hashes()}
                if mode == "observation_priority":
                    snapshot["point_in_time_universe"] = {
                        "scanned_at": records[-1]["at"],
                        "metadata_at": records[0]["at"] - 1,
                        "captured_at": time.time(),
                        "held_pending": ["HELDUSD"],
                        "rows": [
                            {
                                "symbol": f"QA{i}USD",
                                "eligible": True,
                                "confirmed": True,
                                "change_percent": str(i),
                                "quote_volume": "1000000",
                                "spread_bps": "2",
                                "range_percent": str(10 - i),
                                "trades": 1000,
                            }
                            for i in range(6)
                        ],
                    }
                lab.registry.reserve(plan, code_fingerprint())
                lab.registry.inputs(plan.request_id, snapshot)
                asyncio.run(lab.run_once())
                job = lab.registry.get(plan.request_id)
                assert job["status"] == "completed", job["reason"]
                if mode != "observation_priority":
                    evidence = job["result"]["comparisons"][0]["evidence"]
                    assert evidence["requested_decisions"] == 16
                    assert evidence["status"] == "matched_finite_replay", evidence["reason"]
                resources = next(
                    json.loads(e["body"])
                    for e in reversed(job["events"])
                    if e["kind"] == "worker_resources"
                )
                resources.pop("supervised_pid", None)
                assert (
                    resources["wall_seconds"] < 25 and resources["peak_rss_bytes"] < 256 * 1024**2
                )
                cases.append({"mode": mode, "resources": resources, "result": job["result"]})
            finally:
                lab.registry.close()
        assert digest(store.read()) == original and store.reconcile()["balanced"]
        receipt = {
            "scope": "Native twenty-account, sixteen-decision synthetic component slices",
            "source_sha256": code_fingerprint(),
            "actual_accounts": len(store.read()["accounts"]),
            "checks": {"source_financial_state_preserved": True, "journal_balanced": True},
            "cases": cases,
        }
        output.write_text(json.dumps(receipt, indent=2), encoding="utf-8", newline="\n")
        print(
            json.dumps(
                {
                    "checks": receipt["checks"],
                    "cases": [{"mode": c["mode"], "resources": c["resources"]} for c in cases],
                }
            )
        )
        recorder._archive.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["benchmark", "serve"])
    parser.add_argument("--output", type=Path, default=Path("data/cp15-native.json"))
    parser.add_argument("--port", type=int, default=8798)
    args = parser.parse_args()
    benchmark(args.output) if args.mode == "benchmark" else serve(args.port, research=True)
