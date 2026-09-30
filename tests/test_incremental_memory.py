import copy
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from memory_fixtures import memory_fixture  # noqa: E402

from trading.experiment_registry import ExperimentRegistry  # noqa: E402
from trading.incremental_memory import LearningJournal, evaluate_incremental  # noqa: E402


def fixture(tmp_path):
    plan, rows = memory_fixture()
    return (
        plan.model_copy(update={"experiment_mode": "growing_memory"}),
        rows,
        ExperimentRegistry(tmp_path / "registry.sqlite"),
    )


def test_prediction_precedes_scoring_and_frozen_batch_ablation(tmp_path):
    plan, rows, registry = fixture(tmp_path)
    journal = LearningJournal(registry)
    result = evaluate_incremental(rows, plan, journal)
    assert result["journal"] == {"prediction": 24, "score": 24, "update": 9}
    assert [result["metrics"][a]["updates"] for a in ("frozen", "batch", "incremental")] == [
        0,
        1,
        8,
    ]
    assert not result["eligible_for_forward_review"] and result["whole_account_effect"] is None
    allrows = registry.db.execute("SELECT * FROM learning_stages ORDER BY seq").fetchall()
    for r in allrows:
        b = json.loads(r["body"])
        if r["kind"] == "score":
            assert b["prediction_at"] < b["outcome_available_at"] <= b["scored_at"]
        if r["kind"] == "update":
            assert all(x["available_at"] <= b["updated_at"] for x in b["model"]["library"])
    with pytest.raises(sqlite3.IntegrityError):
        registry.db.execute("DELETE FROM learning_stages")
    registry.close()


@pytest.mark.parametrize("stage", ["predict", "update"])
def test_crash_restart_duplicates_reordering_do_not_double_train(tmp_path, stage):
    plan, rows, registry = fixture(tmp_path)
    with pytest.raises(RuntimeError):
        evaluate_incremental(rows, plan, LearningJournal(registry), stage)
    registry.close()
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    journal = LearningJournal(registry)
    result = evaluate_incremental(list(reversed(rows)), plan, journal)
    before = registry.db.execute("SELECT count(*) FROM learning_stages").fetchone()[0]
    again = evaluate_incremental(rows, plan, journal)
    assert registry.db.execute("SELECT count(*) FROM learning_stages").fetchone()[0] == before
    assert again["metrics"] == result["metrics"] and again["comparisons"] == result["comparisons"]
    registry.close()


def test_future_endings_change_scores_not_original_forecasts_and_missing_stays_pending(tmp_path):
    plan, rows, registry = fixture(tmp_path)
    first = evaluate_incremental(rows, plan, LearningJournal(registry))
    registry.close()
    changed = copy.deepcopy(rows)
    changed[-1]["executable_label"]["net_bps"] = 5000
    changed[-2]["executable_label"] = None
    registry = ExperimentRegistry(tmp_path / "second.sqlite")
    second = evaluate_incremental(changed, plan, LearningJournal(registry))
    assert second["unknown_outcomes"] == 1
    for a, b in zip(first["comparisons"], second["comparisons"], strict=True):
        assert a["evidence"]["arms"]["frozen"] == b["evidence"]["arms"]["frozen"]
    assert first["comparisons"][-2]["evidence"] == second["comparisons"][-2]["evidence"]
    registry.close()


def test_cold_start_and_premature_labels_cannot_train(tmp_path):
    plan, rows, registry = fixture(tmp_path)
    result = evaluate_incremental(rows[-2:], plan, LearningJournal(registry))
    assert result["status"] == "cold_start" and result["journal"].get("update", 0) == 0
    registry.close()
    registry = ExperimentRegistry(tmp_path / "premature.sqlite")
    rows[-1]["executable_label"]["available_at"] = rows[-1]["descriptor"]["cutoff"] + 60
    with pytest.raises(ValueError):
        evaluate_incremental(rows, plan, LearningJournal(registry))
    registry.close()


def test_delayed_label_scores_original_late_result_without_relabeling_recognition(tmp_path):
    plan, rows, registry = fixture(tmp_path)
    rows[-1]["available_at"] = rows[-1]["descriptor"]["cutoff"] + 91
    rows[-1]["executable_label"]["available_at"] += 5000
    result = evaluate_incremental(rows, plan, LearningJournal(registry))
    p = result["comparisons"][-1]["evidence"]["arms"]["incremental"]["prediction"]
    assert p["status"] == "result_too_late"
    assert p["action"] == "no_additional_signal"
    assert (
        LearningJournal(registry).get(plan.request_id, rows[-1]["episode"] + ":incremental:score")[
            "residual_bps"
        ]
        is None
    )
    registry.close()
