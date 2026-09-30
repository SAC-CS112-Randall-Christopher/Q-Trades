"""Predeclared shadow update procedure; append-only stages in the research registry."""

import json
import math
import statistics
import time
from copy import deepcopy
from typing import Any

from trading.experiment_registry import ExperimentRegistry
from trading.memory_quality import evaluate_memory, predict, vector
from trading.research_evidence import digest
from trading.research_support import separated
from trading.research_timing import prediction_time

PROCEDURE: dict[str, Any] = {
    "version": "growing-memory-v1",
    "order": "predict -> persist -> mature -> score original prediction -> update",
    "arms": ["frozen", "batch", "incremental"],
    "seed": "CP12 B training/calibration, frozen before the protected window",
    "preprocessing": "Initial training-only normalization and calibration stay frozen",
    "library_max": 128,
    "window": "Most recent 128 distinct matured event groups; full receipts remain retained",
    "batch_groups": 8,
    "same_timestamp": "Persist all predictions before processing labels at that timestamp",
    "cold_start": "No additional signal without an initial valid twelve-group seed",
    "drift": "Three distinct consecutive absolute residuals >50bps trigger diagnosis only",
    "input_drift": "Three distinct mean absolute training z-scores >3 trigger diagnosis only",
    "risk": "Research updates cannot change account strategy, sizing, exits or permissions",
    "journal_max_records": 20000,
}


class LearningJournal:
    def __init__(self, registry: ExperimentRegistry):
        self.registry = registry
        registry.db.executescript("""
            CREATE TABLE IF NOT EXISTS learning_stages (
                seq INTEGER PRIMARY KEY, request_id TEXT NOT NULL, stage_key TEXT NOT NULL,
                at REAL NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL,
                UNIQUE(request_id, stage_key)
            );
            CREATE INDEX IF NOT EXISTS learning_request ON learning_stages(request_id,seq);
            CREATE TRIGGER IF NOT EXISTS immutable_learning_update BEFORE UPDATE ON learning_stages
                BEGIN SELECT RAISE(ABORT, 'Learning receipts are permanent'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_learning_delete BEFORE DELETE ON learning_stages
                BEGIN SELECT RAISE(ABORT, 'Learning receipts are permanent'); END;
        """)

    def get(self, request: str, key: str) -> dict[str, Any] | None:
        row = self.registry.db.execute(
            "SELECT body,sha256 FROM learning_stages WHERE request_id=? AND stage_key=?",
            (request, key),
        ).fetchone()
        if not row:
            return None
        body: dict[str, Any] = json.loads(row["body"])
        if digest(body) != row["sha256"]:
            raise ValueError("Persisted learning stage changed")
        return body

    def put(self, request: str, key: str, at: float, kind: str, body: dict[str, Any]) -> None:
        old = self.get(request, key)
        if old is not None:
            if old != body:
                raise ValueError("Retry changed original prediction/score/model state")
            return
        if self.registry.db.execute("SELECT count(*) FROM learning_stages").fetchone()[0] >= 20000:
            raise ValueError("Learning journal capacity; research stopped without deleting history")
        self.registry.db.execute(
            "INSERT INTO learning_stages VALUES (NULL,?,?,?,?,?,?)",
            (
                request,
                key,
                at,
                kind,
                json.dumps(body, sort_keys=True, allow_nan=False),
                digest(body),
            ),
        )

    def page(self, request: str, before: int = 0) -> dict[str, Any]:
        rows = self.registry.db.execute(
            "SELECT * FROM learning_stages WHERE request_id=? AND (?=0 OR seq<?) "
            "ORDER BY seq DESC LIMIT 21",
            (request, before, before),
        ).fetchall()
        records = []
        for r in rows[:20]:
            body = json.loads(r["body"])
            if digest(body) != r["sha256"]:
                raise ValueError("Learning snapshot fingerprint mismatch")
            records.append(
                {
                    "seq": r["seq"],
                    "at": r["at"],
                    "kind": r["kind"],
                    "body": body,
                    "sha256": r["sha256"],
                }
            )
        counts = {
            r["kind"]: r["n"]
            for r in self.registry.db.execute(
                "SELECT kind,count(*) n FROM learning_stages WHERE request_id=? GROUP BY kind",
                (request,),
            )
        }
        return {
            "records": records,
            "counts": counts,
            "next_cursor": rows[19]["seq"] if len(rows) > 20 else None,
            "financial_authority": False,
            "procedure": PROCEDURE,
        }


def updated(artifact: dict[str, Any], additions: list[dict[str, Any]], at: float) -> dict[str, Any]:
    result = deepcopy(artifact)
    library = {r["group"]: r for r in result["library"]}
    for row in additions:
        d, label = row["descriptor"], row["executable_label"]
        if d["group_id"] in library or not separated(row, list(library.values())):
            continue
        x = vector(d, "B")
        library[d["group_id"]] = {
            "episode": row["episode"],
            "record_id": row.get("record_id"),
            "evidence_reference": row.get("evidence_reference"),
            "group": d["group_id"],
            "x": [
                (v - m) / s for v, m, s in zip(x, result["means"], result["scales"], strict=True)
            ],
            "at": d["cutoff"],
            "start": d["start_at"],
            "end": d["horizon_at"],
            "available_at": label["available_at"],
            "net_bps": label["net_bps"],
        }
    result["library"] = sorted(library.values(), key=lambda r: r["at"])[-128:]
    result["train_end"] = at
    result.pop("sha256")
    result["sha256"] = digest(result)
    return result


def evaluate_incremental(
    rows: list[dict[str, Any]], plan: Any, journal: LearningJournal, crash_after: str | None = None
) -> dict[str, Any]:
    started, cpu = time.perf_counter(), time.process_time()
    if len(rows) > 512 or len({r["episode"] for r in rows}) != len(rows):
        raise ValueError("Duplicate identity or more than 512 frozen opportunities")
    seed_result = evaluate_memory(rows, plan, seed_only=True)
    seed = next(
        (c.get("artifact") for c in seed_result["candidate_group"] if c["arm"] == "B"), None
    )
    models = {arm: deepcopy(seed) for arm in PROCEDURE["arms"]}
    queries = [
        r
        for r in rows
        if plan.test_start <= r["descriptor"]["start_at"]
        and r["descriptor"]["cutoff"] <= plan.test_end
        and r.get("available_at", r["descriptor"]["cutoff"]) <= plan.as_of
    ]
    events = []
    for row in queries:
        d = row["descriptor"]
        prediction_at = prediction_time(row)
        if not math.isfinite(prediction_at):
            raise ValueError("Recorded prediction availability is unavailable")
        events.append((prediction_at, 0, row))
        label = row.get("executable_label") or {}
        if label.get("status") == "available":
            known = label["available_at"]
            if not (d["horizon_at"] <= known and math.isfinite(label["net_bps"])):
                raise ValueError("Final label is premature or invalid")
            if known <= plan.test_end:
                events.append((max(known, prediction_at), 1, row))
    events.sort(key=lambda e: (e[0], e[1], e[2]["descriptor"]["cutoff"]))
    forecasts: dict[str, dict[str, Any]] = {}
    comparisons: dict[str, dict[str, Any]] = {}
    errors: dict[str, list[float]] = {a: [] for a in models}
    update_counts = dict.fromkeys(models, 0)
    independent = set()
    scored_support: list[dict[str, Any]] = []
    pending_batch = []
    alarms = []
    input_errors: list[float] = []
    input_groups: set[str] = set()
    briers: dict[str, list[float]] = {a: [] for a in models}
    procedure_sha = digest(PROCEDURE)
    for at, stage, row in events:
        episode, d = row["episode"], row["descriptor"]
        if stage == 0:
            receipts = {}
            with journal.registry.transaction():
                for arm, model in models.items():
                    key = f"{episode}:{arm}:predict"
                    saved = journal.get(plan.request_id, key)
                    if saved:
                        if (
                            saved["input_sha256"] != digest(d)
                            or saved["procedure_sha256"] != procedure_sha
                        ):
                            raise ValueError("Prediction retry changed permitted inputs/procedure")
                        receipt = saved
                    else:
                        p = (
                            predict(d, model, at)
                            if model
                            else {
                                "status": "cold_start",
                                "action": "no_additional_signal",
                                "profit_probability": None,
                                "recognition_confidence": None,
                            }
                        )
                        try:
                            drift_z = (
                                statistics.mean(
                                    abs((x - m) / s)
                                    for x, m, s in zip(
                                        vector(d, "B"), model["means"], model["scales"], strict=True
                                    )
                                )
                                if model
                                else None
                            )
                        except (ValueError, KeyError, TypeError):
                            drift_z = None
                        receipt = {
                            "prediction": p,
                            "model_before": model["sha256"] if model else None,
                            "input_sha256": digest(d),
                            "procedure_sha256": procedure_sha,
                            "prediction_at": at,
                            "input_drift_z": drift_z,
                        }
                        journal.put(plan.request_id, key, at, "prediction", receipt)
                    receipts[arm] = receipt
            forecasts[episode] = receipts
            if d["group_id"] not in input_groups:
                input_groups.add(d["group_id"])
                z = receipts["frozen"].get("input_drift_z")
                if z is not None:
                    input_errors.append(z)
                    if len(input_errors) >= 3 and all(x > 3 for x in input_errors[-3:]):
                        alarms.append(
                            {
                                "episode": episode,
                                "at": at,
                                "kind": "input",
                                "action": "diagnose_only",
                            }
                        )
            comparisons[episode] = {
                "episode": episode,
                "status": "prediction_persisted",
                "action": "no_additional_signal",
                "later_net_trade_bps": None,
                "evidence": {"arms": receipts, "procedure_sha256": procedure_sha},
            }
            if crash_after == "predict":
                raise RuntimeError("Synthetic crash after prediction commit")
            continue
        label = row["executable_label"]
        current_group = d["group_id"]
        novel = current_group not in independent and separated(row, scored_support)
        independent.add(current_group)
        if novel:
            scored_support.append(row)
            pending_batch.append(row)
        with journal.registry.transaction():
            for arm, model in list(models.items()):
                original = forecasts[episode][arm]
                p = original["prediction"]
                expected = p.get("expected_net_bps") if p["status"] == "supported" else None
                error = label["net_bps"] - expected if expected is not None else None
                score = {
                    "prediction_sha256": digest(original),
                    "prediction_at": original["prediction_at"],
                    "outcome_available_at": label["available_at"],
                    "scored_at": at,
                    "net_bps": label["net_bps"],
                    "residual_bps": error,
                    "execution_cost_error": None,
                    "brier": (p["profit_probability"] - int(label["net_bps"] > 0)) ** 2
                    if p.get("profit_probability") is not None
                    else None,
                    "separated_support": novel,
                }
                journal.put(plan.request_id, f"{episode}:{arm}:score", at, "score", score)
                if score["brier"] is not None and novel:
                    briers[arm].append(score["brier"])
                if error is not None and novel:
                    errors[arm].append(error)
                    if len(errors[arm]) >= 3 and all(abs(e) > 50 for e in errors[arm][-3:]):
                        alarms.append(
                            {
                                "episode": episode,
                                "arm": arm,
                                "action": "diagnose_only",
                                "kind": "residual",
                                "at": at,
                            }
                        )
                additions = (
                    [row]
                    if novel and arm == "incremental"
                    else (list(pending_batch) if arm == "batch" and len(pending_batch) == 8 else [])
                )
                if model and additions:
                    key = f"{episode}:{arm}:update"
                    saved = journal.get(plan.request_id, key)
                    next_model = saved["model"] if saved else updated(model, additions, at)
                    journal.put(
                        plan.request_id,
                        key,
                        at,
                        "update",
                        {
                            "after_score_sha256": digest(score),
                            "model_before": model["sha256"],
                            "model": next_model,
                            "procedure_sha256": procedure_sha,
                            "updated_at": at,
                            "label_episodes": [r["episode"] for r in additions],
                        },
                    )
                    models[arm] = next_model
                    update_counts[arm] += 1
            if len(pending_batch) == 8:
                pending_batch.clear()
        comparisons[episode]["later_net_trade_bps"] = label["net_bps"]
        comparisons[episode]["status"] = "scored_original_prediction"
        if crash_after == "update":
            raise RuntimeError("Synthetic crash after atomic score/update commit")
    scored = sum(q["later_net_trade_bps"] is not None for q in comparisons.values())
    paired_filters = {}
    for arm in models:
        paired_filters[arm] = {
            "baseline": "frozen",
            "unit": "Recorded shadow entry-filter actions on identical queries",
            "changed": sum(
                q["evidence"]["arms"][arm]["prediction"]["action"]
                != q["evidence"]["arms"]["frozen"]["prediction"]["action"]
                for q in comparisons.values()
            ),
            "rejected_vs_unfiltered": sum(
                q["evidence"]["arms"][arm]["prediction"]["action"] == "reject_entry"
                for q in comparisons.values()
            ),
            "missed_positive_taken_trades": sum(
                q["evidence"]["arms"][arm]["prediction"]["action"] == "reject_entry"
                and q["later_net_trade_bps"] is not None
                and q["later_net_trade_bps"] > 0
                for q in comparisons.values()
            ),
        }
    return {
        "version": PROCEDURE["version"],
        "mode": "growing_memory",
        "contract": PROCEDURE,
        "status": "inconclusive" if seed else "cold_start",
        "decision": "reject",
        "eligible_for_forward_review": False,
        "reason": "Research updates retained; account effect unverified",
        "opportunities": len(queries),
        "labeled": scored,
        "unknown_outcomes": len(queries) - scored,
        "changed_decisions": paired_filters["incremental"]["changed"],
        "missed_positive_taken_trades": paired_filters["incremental"][
            "missed_positive_taken_trades"
        ],
        "paired_filter_changes": paired_filters,
        "decision_change_metric": {
            "label": "Changed shadow filters",
            "value": paired_filters["incremental"]["changed"],
            "baseline": "Frozen memory",
            "arm": "incremental",
            "unit": "Identical query actions",
        },
        "comparisons": list(comparisons.values()),
        "whole_account_effect": None,
        "marginal_operating_usd": None,
        "drift_alarms": alarms,
        "metrics": {
            a: {
                "updates": update_counts[a],
                "scored_independent_groups": len(errors[a]),
                "brier": statistics.mean(briers[a]) if briers[a] else None,
                "mean_absolute_net_error_bps": statistics.mean(map(abs, errors[a]))
                if errors[a]
                else None,
                "final_model_sha256": (models.get(a) or {}).get("sha256"),
            }
            for a in models
        },
        "journal": journal.page(plan.request_id)["counts"],
        "limitations": [
            "Historical causal simulation is not a prospective trading run",
            "Multiple arm scores are not independent experiences",
            "Costs in labels counted once",
            "Drift diagnoses cannot promote, reset losses or mutate account strategy",
        ],
        "resources": {
            "elapsed_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "paid_usd": "0",
        },
    }
