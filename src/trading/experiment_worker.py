"""One fixed numerical child, without a venue, financial writer, model or shell input."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from trading.context_flow import evaluate_context
from trading.experiment_registry import (
    PREFLIGHT_END,
    ExperimentPlan,
    ExperimentRegistry,
    fingerprint,
)
from trading.incremental_memory import LearningJournal, evaluate_incremental
from trading.memory_dataset import mature_snapshot
from trading.memory_quality import evaluate_memory
from trading.numerical_candidates import evaluate_families
from trading.numerical_resources import constrain_child, own_limits
from trading.research_experiment import run_experiment


def code_fingerprint() -> str:
    root = Path(__file__).parent
    return hashlib.sha256(
        b"".join(
            (root / name).read_bytes().replace(b"\r\n", b"\n")
            for name in (
                "research_experiment.py",
                "experiment_registry.py",
                "experiment_worker.py",
                "numerical_candidates.py",
                "memory_quality.py",
                "memory_dataset.py",
                "context_flow.py",
                "incremental_memory.py",
            )
        )
    ).hexdigest()


def evaluate(job: dict[str, Any]) -> dict[str, Any]:
    if job["code_sha256"] != code_fingerprint():
        raise ValueError("Frozen evaluator source changed; retain this job and declare a new plan")
    plan = ExperimentPlan.model_validate(json.loads(job["plan"]))
    snapshot = json.loads(job["snapshot"])
    if fingerprint(snapshot) != job["snapshot_sha256"]:
        raise ValueError("Frozen input fingerprint mismatch")
    rows = snapshot["rows"]
    synthetic = plan.evidence_kind == "synthetic_qa" or any(
        row.get("body", {}).get("synthetic_qa")
        or row.get("descriptor", {}).get("data_mode") == "synthetic"
        for row in rows
    )
    local_modes = {"memory_entry", "context_regime", "order_flow", "growing_memory"}
    if plan.experiment_mode not in local_modes and any(
        not 0 <= r["at"] <= plan.as_of for r in rows
    ):
        raise ValueError("Input availability exceeds the declared observation cutoff")
    if plan.experiment_mode in local_modes:
        effective_plan = (
            plan.model_copy(update={"evidence_kind": "synthetic_qa"}) if synthetic else plan
        )
        mature = mature_snapshot(snapshot, plan.as_of)
        if plan.experiment_mode == "memory_entry":
            result = evaluate_memory(mature, effective_plan)
        elif plan.experiment_mode == "growing_memory":
            registry = ExperimentRegistry(Path(job["registry_path"]))
            try:
                result = evaluate_incremental(mature, effective_plan, LearningJournal(registry))
            finally:
                registry.close()
        else:
            result = evaluate_context(mature, snapshot["records"], effective_plan)
    elif plan.experiment_mode == "distinct_families":
        result = evaluate_families(rows, plan.test_start, plan.test_end, plan.as_of)
    else:
        result = run_experiment(
            rows,
            plan.feature,
            plan.horizon_minutes,
            PREFLIGHT_END,
            evaluation_start=plan.test_start,
            evaluation_end=plan.test_end,
        )
    result["decision"] = result.get("decision") or (
        "forward_review_only" if result.get("eligible_for_forward_review") else "reject"
    )
    result["evidence_kind"] = "synthetic_qa" if synthetic else plan.evidence_kind
    if synthetic:
        result["eligible_for_forward_review"] = False
        result["decision"] = "reject"
    result["independent_validation"] = False
    result["next_action"] = (
        "Inspect uncertainty and freeze a separate prospective paper comparison"
        if result["decision"] == "forward_review_only"
        else "Retain this rejection; obtain a later untouched window before another evaluation"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--lease", required=True)
    args = parser.parse_args()
    constrain_child(os.getpid())
    registry = ExperimentRegistry(args.registry)
    try:
        job = registry.get(args.request, inputs=True)
        if job is None or job["status"] != "running" or job["lease"] != args.lease:
            return
        with registry.transaction():
            registry.event(args.request, "worker_identity", own_limits())
        # Registry.get exposes parsed objects; the evaluator also verifies their canonical hashes.
        job["plan"] = json.dumps(job["plan"])
        job["snapshot"] = json.dumps(job["snapshot"])
        job["registry_path"] = str(args.registry)
        try:
            result = evaluate(job)
            registry.finish(args.request, args.lease, result, None)
        except (ValueError, KeyError, ArithmeticError, TypeError):
            registry.finish(
                args.request, args.lease, None, "Frozen numerical evaluation failed; inspect inputs"
            )
    finally:
        registry.close()


if __name__ == "__main__":
    main()
