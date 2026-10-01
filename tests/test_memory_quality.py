import copy
import json
import time

import pytest

from scripts.memory_fixtures import memory_fixture
from trading.experiment_registry import ExperimentRegistry
from trading.experiment_worker import code_fingerprint, evaluate
from trading.memory_dataset import corpus_snapshot, executable_label
from trading.memory_quality import evaluate_memory, filtered_feature, predict, validate_artifact
from trading.paper_challengers import admit
from trading.paper_engine import PaperEngine, initial_state
from trading.research_evidence import EvidenceArchive, digest


def fitted():
    plan, rows = memory_fixture()
    result = evaluate_memory(rows, plan)
    return plan, rows, result, result["candidate_group"][0]["artifact"]


def test_frozen_artifact_scores_protected_predictions_without_claiming_account_value():
    plan, rows, result, artifact = fitted()
    validate_artifact(artifact)
    assert result["status"] == "inconclusive"
    assert not result["eligible_for_forward_review"] and result["whole_account_effect"] is None
    assert result["resources"]["marginal_operating_usd"] is None
    assert len(result["candidate_group"]) == 2
    p = predict(rows[-1]["descriptor"], artifact, rows[-1]["descriptor"]["cutoff"])
    assert p["status"] == "supported" and len(p["neighbors"]) == 5
    assert p["costs_already_embedded"] and p["recognition_confidence"] is None
    assert p["maximum_weight"] == 0.2
    assert p["economic_evidence"].startswith("Matched whole-account")
    assert len(p["illustrations"]["favorable"]) + len(p["illustrations"]["unfavorable"]) <= 2
    assert artifact["calibration_end"] < plan.test_start


def test_post_cutoff_labels_order_and_opaque_ids_do_not_change_matches_or_frozen_training():
    plan, rows, original, artifact = fitted()
    changed = copy.deepcopy(rows)
    changed[-1]["executable_label"]["net_bps"] = -9000
    changed.reverse()
    replay = evaluate_memory(changed, plan)
    assert replay["candidate_group"][0]["artifact"] == artifact
    query = rows[-1]["descriptor"]
    first = predict(query, artifact, query["cutoff"])
    second_artifact = copy.deepcopy(artifact)
    for row in second_artifact["library"]:
        row["episode"] = "opaque-" + row["episode"]
    second_artifact.pop("sha256")
    second_artifact["sha256"] = digest(second_artifact)
    second = predict(query, second_artifact, query["cutoff"])
    assert [x["distance"] for x in first["neighbors"]] == [
        x["distance"] for x in second["neighbors"]
    ]
    assert first["expected_net_bps"] == second["expected_net_bps"]
    assert original["candidate_group"][0]["metrics"] != replay["candidate_group"][0]["metrics"]


def test_unfamiliar_missing_late_or_corrupt_memory_preserves_baseline_fallback():
    _, rows, _, artifact = fitted()
    d = copy.deepcopy(rows[-1]["descriptor"])
    d["returns_bps"] = [10000.0] * 10
    assert predict(d, artifact, d["cutoff"])["status"] == "unfamiliar"
    base = {"eligible": True, "atr": "1", "bar_open_ms": 123}
    assert filtered_feature(base, d, artifact, d["cutoff"])["eligible"]
    assert predict(d, artifact, d["expires_at"] + 1)["status"] == "result_too_late"
    corrupt = copy.deepcopy(artifact)
    corrupt["means"][0] += 1
    assert filtered_feature(base, rows[-1]["descriptor"], corrupt, d["cutoff"])["eligible"]
    missing = copy.deepcopy(rows[-1]["descriptor"])
    missing.pop("returns_bps")
    assert predict(missing, artifact, missing["cutoff"])["status"] == "invalid_input"
    # Recognition errors never become an instruction to close an existing position.
    assert base == {"eligible": True, "atr": "1", "bar_open_ms": 123}


def test_sparse_duplicate_and_zero_variance_history_cannot_manufacture_support():
    plan, rows = memory_fixture()
    duplicate = copy.deepcopy(rows)
    for row in duplicate[:12]:
        row["descriptor"]["start_at"] = duplicate[0]["descriptor"]["start_at"]
    result = evaluate_memory(duplicate, plan)
    assert "artifact" not in result["candidate_group"][0]
    flat = copy.deepcopy(rows)
    for row in flat[:12]:
        row["descriptor"]["returns_bps"] = [1.0] * 10
    result = evaluate_memory(flat, plan)
    assert "artifact" not in result["candidate_group"][0]
    for row in rows:
        row["executable_label"] = {"status": "unavailable"}
    result = evaluate_memory(rows, plan)
    assert result["target_coverage"]["unknown"] == 26
    assert result["status"] == "insufficient_data"


def test_chronological_calibration_cannot_affect_an_earlier_prediction():
    _, rows, _, artifact = fitted()
    d = rows[12]["descriptor"]
    assert predict(d, artifact, d["cutoff"])["status"] == "invalid_input"


def test_registry_owns_memory_protection_retry_hashes_and_saved_negative_result(tmp_path):
    plan, rows = memory_fixture()
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    assert not registry.reserve(plan, code_fingerprint())["retry"]
    assert registry.reserve(plan, code_fingerprint())["retry"]
    changed = plan.model_copy(update={"request_id": "overlapping-memory-eval"})
    with pytest.raises(ValueError, match="overlaps consumed"):
        registry.reserve(changed, code_fingerprint())
    registry.inputs(
        plan.request_id,
        {
            "rows": rows,
            "records": [],
            "source_files": __import__(
                "trading.execution_replay", fromlist=["source_hashes"]
            ).source_hashes(),
        },
    )
    job = registry.claim()
    assert job
    job = registry.get(plan.request_id, inputs=True)
    assert job
    job["plan"] = json.dumps(job["plan"])
    job["snapshot"] = json.dumps(job["snapshot"])
    # Direct evaluate takes the registry's stored serialized inputs.
    result = evaluate(job)
    assert not result["eligible_for_forward_review"] and result["evidence_kind"] == "synthetic_qa"
    registry.finish(plan.request_id, job["lease"], result, None)
    before = registry.get(plan.request_id)
    registry.close()
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    assert registry.get(plan.request_id)["result"] == before["result"]
    registry.close()


def test_actual_linked_net_labels_require_matured_horizon_and_reproduce_engine(tmp_path):
    from collections import deque
    from decimal import Decimal as D

    from test_paper_engine import frame

    from trading.evidence_runtime import EvidenceRecorder, plain
    from trading.paper_strategy import VARIANTS, Bar, features

    recorder = EvidenceRecorder(tmp_path / "labels.sqlite")
    origin = time.time() - 10000
    state = initial_state(origin)
    records = []
    for i, offset in enumerate((0, 2, 610, 612, 2702)):
        at = origin + offset
        end_minute = int(at // 60) * 60000
        bars = [
            Bar(
                end_minute - (400 - j) * 60000,
                D(100) + D(j) / 100,
                D(100) + D(j) / 100 + D(".005"),
                D(100) + D(j) / 100 - D(".01"),
                D(100) + D(j) / 100,
                D(30) if j == 399 else D(10),
                end_minute - (400 - j) * 60000 + 59999,
            )
            for j in range(400)
        ]
        frames = {"BTCUSD": {**frame(at, sequence=i + 1), "source": "synthetic-label-fixture"}}
        study = {"BTCUSD": {v: features(bars, at, v) for v in VARIANTS}}
        packet = recorder.prepare(
            at,
            frames,
            study,
            {"BTCUSD": bars},
            {"BTCUSD": at},
            0,
            {},
            plain(state),
            [],
            {"BTCUSD": deque()},
            {},
        )
        engine = PaperEngine(state, at)
        engine.tick(frames, study)
        recorder.complete(packet, engine.events, state, [], {}, time.perf_counter())
        records.append({"id": i + 1, "sha256": digest(packet), "payload": packet})
    d = {
        "status": "available",
        "cutoff": origin,
        "horizon_at": origin + 2700,
        "data_mode": "synthetic",
    }
    end = records[-1]["payload"]["at"]
    label = executable_label(d, records, end)
    assert label["status"] == "available" and label["fees_embedded_once"]
    assert label["exit"]["body"]["pnl"] != "0"
    assert label["available_at"] == end
    delayed = copy.deepcopy(records)
    delayed[-1]["available_at"] = end + 500
    assert executable_label(d, delayed, end)["status"] == "unavailable"
    assert executable_label(d, delayed, end + 500)["available_at"] == end + 500
    assert executable_label(d, records[:-1], end)["status"] == "unavailable"
    assert executable_label(d, records, d["horizon_at"] - 1)["status"] == "pending"
    broken = copy.deepcopy(records)
    broken[0]["payload"]["after_tick_sha256"] = "0" * 64
    broken[0]["sha256"] = digest(broken[0]["payload"])
    assert executable_label(d, broken, end)["status"] == "unavailable"


def test_corpus_reopens_empty_archive_without_price_label_substitution(tmp_path):
    archive = EvidenceArchive(tmp_path / "evidence.sqlite")
    snapshot = corpus_snapshot(archive.path, time.time())
    assert snapshot["rows"] == [] and snapshot["records"] == []
    archive.close()


def test_memory_artifact_uses_existing_isolated_admission_and_financial_controls():
    _, _, _, artifact = fitted()
    engine = PaperEngine(initial_state(time.time()), time.time())
    original = copy.deepcopy(engine.state["accounts"]["primary"])
    receipt = admit(engine, "memory-shadow-fixture", artifact, "50", "0")
    a = engine.state["accounts"][receipt["account"]]
    assert a["numerical_artifact"] == artifact and a["symbols"] == ["BTCUSD"]
    assert engine.state["accounts"]["primary"] == original
    assert (
        admit(engine, "memory-shadow-fixture", artifact, "50", "0")["status"] == "already_applied"
    )
    engine.assert_invariants()


def test_corrupt_optional_memory_does_not_force_an_exit_or_reset_risk():
    from test_paper_engine import frame

    _, _, _, artifact = fitted()
    now = time.time()
    engine = PaperEngine(initial_state(now), now)
    receipt = admit(engine, "memory-position-fixture", artifact, "50", "0")
    a = engine.state["accounts"][receipt["account"]]
    feature = {"eligible": True, "atr": "1", "bar_open_ms": 123, "reason": "Synthetic entry"}
    studies = {"BTCUSD": {a["version"]: feature}}
    engine.tick({"BTCUSD": frame(now)}, studies)
    PaperEngine(engine.state, now + 2).tick({"BTCUSD": frame(now + 2, sequence=2)}, studies)
    assert a["positions"]
    risk = a["risk_peak"]
    a["numerical_artifact"]["version"] = "damaged-model"
    PaperEngine(engine.state, now + 4).tick({"BTCUSD": frame(now + 4, sequence=3)}, studies)
    assert a["positions"] and not a["pending"] and a["risk_peak"] == risk


def test_optional_memory_input_reproduces_before_execution_and_detects_tampering(tmp_path):
    from collections import deque
    from decimal import Decimal as D

    from test_paper_engine import frame

    from trading.evidence_runtime import EvidenceRecorder, feature_reproduction, plain
    from trading.paper_runtime import PaperRuntime
    from trading.paper_strategy import VARIANTS, Bar, features

    _, _, _, artifact = fitted()
    now = time.time()
    end = int(now // 60) * 60000
    bars = [
        Bar(
            end - (400 - j) * 60000,
            D(100) + D(j) / 100,
            D(100) + D(j) / 100 + D(".005"),
            D(100) + D(j) / 100 - D(".01"),
            D(100) + D(j) / 100,
            D(30) if j == 399 else D(10),
            end - (400 - j) * 60000 + 59999,
        )
        for j in range(400)
    ]
    engine = PaperEngine(initial_state(now - 20), now - 10)
    admit(engine, "memory-reproduction-fixture", artifact, "50", "0")
    runtime = object.__new__(PaperRuntime)
    runtime.state = engine.state
    runtime._numerical_minute = -1
    runtime._numerical_rows = []
    runtime.history = {"BTCUSD": bars}
    runtime.books = {"BTCUSD": frame(now)}
    study = {"BTCUSD": {v: features(bars, now, v) for v in VARIANTS}}
    runtime.numerical_study(now, study)  # No PostgreSQL query for memory-only candidates.
    recorder = EvidenceRecorder(tmp_path / "memory-input.sqlite")
    packet = recorder.prepare(
        time.time(),
        runtime.books,
        study,
        runtime.history,
        {"BTCUSD": now},
        0,
        {},
        plain(engine.state),
        [],
        {"BTCUSD": deque()},
        {},
    )
    assert feature_reproduction(packet)["closed_bar_features"]["BTCUSD"]["memory_matched"]
    version = next(
        a["version"] for a in engine.state["accounts"].values() if a.get("memory_entry_contract")
    )
    packet["study"]["BTCUSD"][version]["memory_input"]["bars"][-1]["close"] = "99999"
    assert not feature_reproduction(packet)["closed_bar_features"]["BTCUSD"]["memory_matched"]
