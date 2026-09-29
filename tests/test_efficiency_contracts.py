import copy
import json
import sqlite3
import time

import pytest
from test_experiment_registry import plan, shifted_inputs
from test_numerical_candidates import fixture_artifact
from test_paper_engine import START, frame
from test_paper_learning import candidate_state, windows
from test_paper_store import pg_store as _pg_store

from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.numerical_candidates import signal, validate_artifact
from trading.paper_challengers import admit
from trading.paper_engine import PaperEngine, initial_state
from trading.paper_learning import comparison, designate, retain_report
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore

pg_store = _pg_store


def test_legacy_registry_manifest_migration_preserves_full_inputs_and_hash(tmp_path, monkeypatch):
    path = tmp_path / "registry.sqlite"
    registry = ExperimentRegistry(path)
    registry.reserve(plan(), "0" * 64)
    registry.inputs(plan().request_id, shifted_inputs())
    before = dict(registry.db.execute("SELECT * FROM experiments").fetchone())
    registry.db.execute("DROP TRIGGER immutable_input_manifest")
    registry.db.execute("ALTER TABLE experiments DROP COLUMN manifest")
    registry.close()
    reopened = ExperimentRegistry(path)
    parsed = []
    original_loads = json.loads

    def bounded_loads(value, *args, **kwargs):
        parsed.append(len(value))
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", bounded_loads)
    receipt = reopened.get(plan().request_id)
    assert receipt["manifest"] == original_loads(before["snapshot"])["manifest"]
    assert "snapshot" not in receipt and "lease" not in receipt
    assert max(parsed) < len(before["snapshot"])
    raw = reopened.db.execute("SELECT snapshot,snapshot_sha256 FROM experiments").fetchone()
    assert (
        raw["snapshot"] == before["snapshot"]
        and raw["snapshot_sha256"] == before["snapshot_sha256"]
    )
    assert reopened.get(plan().request_id, inputs=True)["snapshot"] == original_loads(
        before["snapshot"]
    )
    with pytest.raises(sqlite3.IntegrityError, match="permanent"):
        reopened.db.execute("UPDATE experiments SET manifest='{}'")
    reopened.close()


def test_report_projection_migrates_without_losing_any_immutable_receipt(pg_store):
    store, dsn = pg_store
    result = {}
    report = {
        "candidate": "primary",
        "decision": "no_promotion",
        "created_at": time.time(),
        "daily_blocks": [{"day": i} for i in range(30)],
        "discarded_windows": [{"reason": "Inspected"}] * 512,
        "source_event_ids": list(range(512)),
    }
    store.transact(
        time.time(), lambda e: result.update(retain_report(e, "migration-report-0001", report))
    )
    pointer = store.read()["learning"]["reports"][result["request_id"]]
    assert pointer["daily_block_count"] == 30 and "discarded_windows" not in pointer
    assert store.learning_report(result["request_id"], result["sha256"]) == result
    runtime = PaperRuntime(store, None)
    # A manual export may overlap writer work, but must not enlist its SELECT in
    # the writer transaction or leave an extra reader connection open.
    with pytest.raises(RuntimeError, match="rollback fixture"):
        with store.connection.transaction():
            assert runtime.retained_learning_report(result["request_id"]) == result
            raise RuntimeError("rollback fixture")
    # Simulate the previously shipped full receipt projection with the same journal.
    store.transact(
        time.time(),
        lambda e: e.state["learning"]["reports"].update(
            {result["request_id"]: copy.deepcopy(result)}
        ),
    )
    before = store.read()
    journal = store.export(0, 1000)
    store.transact(time.time(), lambda e: None)
    after = store.read()
    assert after["accounts"] == before["accounts"] and store.export(0, 1000) == journal
    assert after["learning"]["reports"][result["request_id"]] == pointer
    reader = PaperStore(dsn)
    try:
        assert reader.learning_report(result["request_id"], result["sha256"]) == result
        with pytest.raises(ValueError, match="fingerprint"):
            reader.learning_report(result["request_id"], "0" * 64)
    finally:
        reader.close()
    assert store.reconcile()["balanced"]


def test_approval_verifies_full_receipt_instead_of_trusting_projection():
    engine, name, control = candidate_state()
    engine.now = START + 30 * 86400
    receipt = retain_report(
        engine,
        "approval-report-0001",
        comparison(engine.state, name, windows(engine, name, control), engine.now, START),
    )
    forged = dict(receipt, candidate="primary")
    before = copy.deepcopy(engine.state)
    with pytest.raises(ValueError, match="fingerprint"):
        designate(engine, receipt["request_id"], receipt["sha256"], 0, forged)
    assert engine.state == before
    assert (
        designate(engine, receipt["request_id"], receipt["sha256"], 0, receipt)["incumbent"] == name
    )


def test_changed_summary_cannot_turn_an_immutable_rejection_into_authority():
    engine, name, _ = candidate_state()
    receipt = retain_report(
        engine, "rejection-report-0001", comparison(engine.state, name, [], engine.now, START)
    )
    assert receipt["decision"] == "no_promotion"
    engine.state["learning"]["reports"][receipt["request_id"]]["decision"] = (
        "eligible_for_paper_designation"
    )
    before = copy.deepcopy(engine.state)
    with pytest.raises(ValueError, match="immutable report does not permit"):
        designate(engine, receipt["request_id"], receipt["sha256"], 0, receipt)
    assert engine.state == before and engine.state["learning"]["incumbent"] == "primary"


@pytest.mark.parametrize(
    "field,value",
    [
        ("maximum_hold_seconds", 1000000),
        ("progress_seconds", False),
        ("risk_envelope", "unbounded"),
        ("fees_per_side", "0"),
        ("horizon_minutes", 5),
        ("entry_prediction_bps", -100.0),
        ("mean", True),
    ],
)
def test_recomputed_hash_cannot_expand_frozen_timing_cost_or_risk(field, value):
    artifact = fixture_artifact()
    artifact[field] = value
    artifact["sha256"] = fingerprint({k: v for k, v in artifact.items() if k != "sha256"})
    with pytest.raises(ValueError):
        validate_artifact(artifact)
    with pytest.raises(ValueError):
        signal([], START, artifact, START)


def test_invalid_artifact_keeps_a_bounded_risk_reducing_exit():
    engine = PaperEngine(initial_state(START), START)
    engine.seed()
    name = admit(engine, "exit-risk-fixture", fixture_artifact(), "50", "0")["account"]
    a = engine.state["accounts"][name]
    engine.value(a, {"BTCUSD": frame()})
    assert "reserved" in engine.enter(
        name,
        a,
        "BTCUSD",
        frame(),
        {"eligible": True, "atr": "1", "bar_open_ms": 1, "reason": "Synthetic contract"},
    )
    engine.now += 2
    book = frame(engine.now, sequence=2)
    engine.fill(name, a, "BTCUSD", book, {"BTCUSD": book})
    a["numerical_artifact"]["maximum_hold_seconds"] = "invalid"
    engine.exit_position(name, a, "BTCUSD", frame(engine.now, sequence=3), {})
    assert a["pending"]["BTCUSD"]["side"] == "sell"
    assert a["pending"]["BTCUSD"]["reason"] == "Invalid frozen numerical artifact; risk reduction"
    engine.assert_invariants()
