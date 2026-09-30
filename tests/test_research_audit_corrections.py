"""Regressions for issue #1's integrated-source audit, using disposable evidence."""

import copy
import sqlite3
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_execution_replay import slices

from scripts.memory_fixtures import memory_fixture
from trading.api import create_app
from trading.compact_memory import CompactMemory, compact_snapshot
from trading.config import Settings
from trading.context_flow import context_neighbors, evaluate_context
from trading.experiment_registry import ExperimentRegistry
from trading.incremental_memory import LearningJournal, evaluate_incremental, updated
from trading.memory_dataset import corpus_snapshot
from trading.memory_quality import evaluate_memory, predict
from trading.research_evidence import EvidenceArchive, digest


def test_late_test_inputs_never_become_actionable_in_memory_or_context():
    plan, rows = memory_fixture()
    rows = copy.deepcopy(rows)
    test_rows = [r for r in rows if r["descriptor"]["cutoff"] >= plan.test_start]
    for row in test_rows:
        row["available_at"] = row["descriptor"]["expires_at"] + 1
        row["descriptor"]["context"]["book"]["spread_bps"] = "15"
    memory = evaluate_memory(rows, plan)
    for candidate in memory["candidate_group"]:
        assert candidate["metrics"]["supported"] == 0
        assert all(q["prediction"]["status"] == "result_too_late" for q in candidate["predictions"])
        assert all(
            q["prediction"]["action"] == "no_additional_signal" for q in candidate["predictions"]
        )
    context = evaluate_context(
        rows, [], plan.model_copy(update={"experiment_mode": "context_regime"})
    )
    assert len(context["comparisons"]) == 8 and context["changed_decisions"] == 0
    assert all(q["action"] == "no_additional_signal" for q in context["comparisons"])
    assert all(
        not s["changes_entry"] for q in context["comparisons"] for s in q["latency_sensitivity"]
    )


def test_late_calibration_inputs_do_not_enter_probability_bins():
    plan, rows = memory_fixture()
    calibration_start = plan.test_start - 7 * 86400
    for row in rows:
        d = row["descriptor"]
        if calibration_start <= d["cutoff"] < plan.test_start:
            row["available_at"] = d["expires_at"] + 1
    result = evaluate_memory(rows, plan)
    for candidate in result["candidate_group"]:
        assert all(
            b["count"] == 0 and b["probability"] is None
            for b in candidate["artifact"]["calibration"]
        )


def test_compact_and_full_evidence_collision_reopens_exact_typed_reference(tmp_path):
    at = time.time() - 3000
    descriptor = {
        "status": "available",
        "cutoff": at,
        "horizon_at": at + 2700,
        "start_at": at - 660,
        "data_mode": "synthetic",
        "returns_bps": [1.0] * 10,
    }
    memory = CompactMemory(tmp_path / "memory-episodes.sqlite")
    with patch("trading.compact_memory.time.time", return_value=at + 1):
        memory.append(
            {"at": at, "collected_at": at, "fresh": True, "prefix": descriptor, "events": []}
        )
    row = compact_snapshot(memory.path, at + 2)["rows"][0]
    memory.close()
    raw = EvidenceArchive(tmp_path / "research-evidence.sqlite")
    raw.append([{"kind": "summary", "at": at - 1, "coverage": "Unrelated older summary"}])
    raw.close()
    assert row["record_id"] == 1
    with TestClient(
        create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    ) as client:
        # Legacy full-archive reads remain explicit full reads.
        assert client.get("/api/evidence/1").json()["payload"]["kind"] == "summary"
        reference = row["evidence_reference"]
        assert reference["archive"] == "compact"
        response = client.get(
            f"/api/evidence/compact/{row['episode']}", params={"sha256": reference["sha256"]}
        )
        assert response.status_code == 200
        detail = response.json()
        assert detail["episode"] == row["episode"]
        assert detail["sha256"] == digest(descriptor)
        assert detail["descriptor"] == descriptor
        assert (
            client.get(
                f"/api/evidence/compact/{row['episode']}", params={"sha256": "0" * 64}
            ).status_code
            == 409
        )
        assert (
            client.get("/api/evidence/compact/missing", params={"sha256": "0" * 64}).status_code
            == 404
        )
        # A fingerprint mismatch never silently falls through to a coincident raw ID.
        assert (
            client.get("/api/evidence/1", params={"sha256": digest(descriptor)}).status_code == 409
        )


def test_update_and_context_do_not_count_overlapping_buckets_as_separated_support():
    plan, rows = memory_fixture()
    artifact = evaluate_memory(rows, plan)["candidate_group"][0]["artifact"]
    query = rows[-1]["descriptor"]
    additions = []
    for i, at in enumerate((query["cutoff"] - 15000, query["cutoff"] - 11700)):
        row = copy.deepcopy(rows[-1])
        row["episode"] = f"overlapping-addition-{i}"
        d = row["descriptor"]
        d.update(
            cutoff=at,
            start_at=at - 660,
            horizon_at=at + 2700,
            expires_at=at + 90,
            group_id=f"BTCUSD:{int(at // 3300)}",
        )
        row["available_at"] = at
        row["executable_label"]["available_at"] = at + 2701
        additions.append(row)
    new_model = updated(artifact, additions, query["cutoff"] - 4000)
    prediction = predict(query, new_model, query["cutoff"])
    selected = {n["episode"] for n in prediction.get("neighbors", [])}
    assert not {r["episode"] for r in additions} <= selected
    assert not {r["episode"] for r in additions} <= {r["episode"] for r in new_model["library"]}
    matches = context_neighbors(query, additions + rows[:12])["matches"]
    assert not {r["episode"] for r in additions} <= {m["episode"] for m in matches}


def test_requested_dependency_interval_is_selected_before_budget(tmp_path, decision_packet):
    recorder, recorded = slices(decision_packet)
    records = [{**r, "at": r["payload"]["at"]} for r in recorded]
    path = tmp_path / "research-evidence.sqlite"
    archive = EvidenceArchive(path)
    for i in range(9):
        archive.append(
            [{"kind": "decision", "at": records[0]["at"] - 1000 + i, "padding": "x" * (1024**2)}]
        )
    archive.append([r["payload"] for r in records])
    archive.close()
    with sqlite3.connect(path) as db:
        expected = [
            r[0] for r in db.execute("SELECT sha256 FROM evidence_records WHERE id>9 ORDER BY id")
        ]
    plan, _ = memory_fixture()
    plan = plan.model_copy(
        update={
            "experiment_mode": "component_size",
            "test_start": records[0]["at"] - 0.1,
            "test_end": records[-1]["at"] + 0.1,
            "as_of": max(time.time(), records[-1]["at"] + 1),
        }
    )
    snapshot = corpus_snapshot(path, plan.as_of, plan=plan)
    assert len(snapshot["records"]) == len(records)
    assert [r["sha256"] for r in snapshot["records"]] == expected
    assert snapshot["manifest"]["excluded_older_records"] == 9
    oversized = plan.model_copy(update={"test_start": records[0]["at"] - 1001})
    refused = corpus_snapshot(path, plan.as_of, plan=oversized)
    assert refused["records"] == []
    assert "budget" in refused["manifest"]["execution_status"].lower()


def test_learning_summary_measures_actual_paired_filter_changes(tmp_path):
    plan, rows = memory_fixture()
    for i, row in enumerate(rows[-8:]):
        row["executable_label"]["net_bps"] = -1000.0 if i < 3 else 1000.0
    registry = ExperimentRegistry(tmp_path / "learning.sqlite")
    try:
        result = evaluate_incremental(rows, plan, LearningJournal(registry))
        changes = sum(
            q["evidence"]["arms"]["incremental"]["prediction"]["action"]
            != q["evidence"]["arms"]["frozen"]["prediction"]["action"]
            for q in result["comparisons"]
        )
        assert changes > 0
        assert result["changed_decisions"] == changes
    finally:
        registry.close()
