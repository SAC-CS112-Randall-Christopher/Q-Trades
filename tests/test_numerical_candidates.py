import copy
import math

import pytest
from test_paper_engine import START, frame
from test_paper_store import pg_store as _pg_store

from scripts.lab_fixtures import synthetic_rows
from trading.experiment_registry import fingerprint
from trading.numerical_candidates import FAMILIES, evaluate_families, signal, validate_artifact
from trading.paper_challengers import admit
from trading.paper_engine import PaperEngine, initial_state

pg_store = _pg_store


def fixture_artifact(family="slow_trend"):
    rows = synthetic_rows()
    start = rows[460]["at"]
    report = evaluate_families(rows, start, rows[-1]["at"], rows[-1]["at"])
    return next(c["artifact"] for c in report["candidate_group"] if c["family"] == family)


def test_three_mechanisms_fit_once_with_common_windows_controls_and_retained_trials():
    rows = synthetic_rows()
    report = evaluate_families(rows, rows[460]["at"], rows[-1]["at"], rows[-1]["at"])
    assert len(report["candidate_group"]) == 3
    assert len({c["mechanism"] for c in report["candidate_group"]}) == 3
    assert not report["independent_validation"] and not report["eligible_for_forward_review"]
    for candidate in report["candidate_group"]:
        assert candidate["status"] == "completed"
        artifact = candidate["artifact"]
        validate_artifact(artifact)
        assert artifact["train_end"] < rows[460]["at"] - artifact["horizon_minutes"] * 60
        assert len(candidate["parameter_trials"]) == 3
        assert (
            candidate["metrics"]["nonoverlapping_label_blocks"]
            <= candidate["metrics"]["fitted_selections"]
        )
        assert "Unavailable" in candidate["execution_replay"]


def test_test_labels_cannot_change_training_fit_and_missing_history_does_not_fit():
    rows = synthetic_rows()
    start = rows[460]["at"]
    base = evaluate_families(rows, start, rows[-1]["at"], rows[-1]["at"])
    changed = copy.deepcopy(rows)
    for row in changed[460:]:
        row["body"]["last_depth"]["bid"] = "100000.0"
        row["body"]["last_depth"]["ask"] = "100001.0"
    after = evaluate_families(changed, start, rows[-1]["at"], rows[-1]["at"])
    assert [c["artifact"] for c in base["candidate_group"]] == [
        c["artifact"] for c in after["candidate_group"]
    ]
    short = evaluate_families(rows[:40], start, rows[-1]["at"], rows[-1]["at"])
    assert all(
        c["status"] == "insufficient_data" and "artifact" not in c for c in short["candidate_group"]
    )


@pytest.mark.parametrize("family", list(FAMILIES))
def test_forward_signal_frozen_preprocessing_time_gaps_and_mutation(family):
    artifact = fixture_artifact(family)
    rows = synthetic_rows()[-121:]
    result = signal(rows, rows[-1]["at"], artifact, rows[0]["at"] - 1)
    assert math.isfinite(result["prediction_net_bps"])
    assert result["artifact_sha256"] == artifact["sha256"]
    assert not signal(rows, rows[-1]["at"] + 100, artifact, rows[0]["at"] - 1)["eligible"]
    assert not signal(rows, rows[-1]["at"], artifact, rows[-1]["at"])["eligible"]
    altered = dict(artifact, weight=artifact["weight"] + 1)
    with pytest.raises(ValueError, match="fingerprint"):
        validate_artifact(altered)


def test_explicit_admission_funding_retry_and_cash_risk_are_isolated():
    engine = PaperEngine(initial_state(START), START)
    engine.seed()
    primary = copy.deepcopy(engine.state["accounts"]["primary"])
    artifact = fixture_artifact()
    receipt = admit(engine, "retained-experiment", artifact, "50", "0")
    name = receipt["account"]
    events = copy.deepcopy(engine.events)
    assert admit(engine, "retained-experiment", artifact, "50", "0")["status"] == "already_applied"
    assert engine.events == events and engine.state["accounts"]["primary"] == primary
    with pytest.raises(ValueError, match="different"):
        admit(engine, "retained-experiment", artifact, "100", "0")
    a = engine.state["accounts"][name]
    feature = {"eligible": True, "atr": "1", "bar_open_ms": 1, "reason": "Synthetic signal"}
    book = frame()
    engine.value(a, {"BTCUSD": book})
    assert "reserved" in engine.enter(name, a, "BTCUSD", book, feature)
    assert a["cash"] == "50" and a["pending"]["BTCUSD"]["reserved"] != "0"
    engine.now += 2
    engine.fill(
        name, a, "BTCUSD", frame(START + 2, sequence=2), {"BTCUSD": frame(START + 2, sequence=2)}
    )
    assert a["cash"] != "50" and a["positions"]
    engine.now += artifact["maximum_hold_seconds"]
    engine.exit_position(name, a, "BTCUSD", frame(engine.now, sequence=3), {})
    assert a["pending"]["BTCUSD"]["side"] == "sell"
    engine.assert_invariants()


def test_nonfinite_model_is_rejected_even_with_recomputed_hash():
    artifact = fixture_artifact()
    artifact["scale"] = 0
    artifact["sha256"] = fingerprint({k: v for k, v in artifact.items() if k != "sha256"})
    with pytest.raises(ValueError, match="unavailable"):
        validate_artifact(artifact)


def test_retained_gaps_are_insufficient_without_synthetic_fallback():
    from test_experiment_registry import shifted_inputs

    rows = shifted_inputs()["rows"]
    result = evaluate_families(rows, rows[460]["at"], rows[-1]["at"], rows[-1]["at"])
    slower = next(c for c in result["candidate_group"] if c["family"] == "slow_trend")
    assert slower["status"] == "insufficient_data" and "artifact" not in slower


def test_admission_is_atomic_persisted_and_retry_does_not_refund(pg_store):
    store, dsn = pg_store
    artifact = fixture_artifact()
    before = store.read()

    def failing(engine):
        admit(engine, "database-experiment", artifact, "50", "0")
        raise ValueError("Injected transaction rollback")

    with pytest.raises(ValueError):
        store.transact(START, failing)
    assert store.read() == before
    result = {}
    store.transact(
        START, lambda e: result.update(admit(e, "database-experiment", artifact, "50", "0"))
    )
    after = store.read()
    store.transact(START + 1, lambda e: admit(e, "database-experiment", artifact, "50", "0"))
    assert store.read()["accounts"] == after["accounts"]
    assert store.reconcile()["balanced"]
    events = store.export(0, 1000, result["account"])["records"]
    assert len([e for e in events if e["kind"] == "forward_account_funded"]) == 1
