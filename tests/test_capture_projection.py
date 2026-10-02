"""Capture preserves complete financial snapshots and their own committed provenance."""

import copy
import json
import time
from decimal import Decimal

import pytest
from test_paper_engine import START, frame, study
from test_paper_store import pg_store as pg_store

from trading.evidence_runtime import EvidenceRecorder, plain, state_snapshot
from trading.paper_engine import PaperEngine, initial_state
from trading.research_evidence import digest


def test_frozen_before_state_survives_subsequent_fills_and_nested_mutation():
    engine = PaperEngine(initial_state(START), START)
    engine.tick({"BTCUSD": frame()}, study())
    original = plain(engine.state)
    snapshot = state_snapshot(engine.state)
    assert snapshot == original and digest(snapshot) == digest(original)
    engine.now = START + 2
    engine.tick({"BTCUSD": frame(START + 2, sequence=2)}, study())
    assert engine.state != original and snapshot == original
    snapshot["accounts"]["primary"]["pending"].clear()
    assert engine.state["accounts"]["primary"]["positions"]


@pytest.mark.parametrize(
    "metadata",
    [
        {"unicode": "Δ 😺", "integer": 2**137, "negative_zero": -0.0},
        {"exact_money": Decimal("0.10000000000000000000000001")},
        {"tuple": ("retained", {"nested": [1, None, False]})},
        {1: "integer key", "1": "original collision behavior"},
        {"bool_key": {True: "true", None: "null"}},
    ],
)
def test_capture_conversion_matches_existing_contract_and_detaches(metadata):
    state = initial_state(START)
    state["capture_metadata"] = metadata
    frozen = state_snapshot(state)
    expected = plain(state)
    assert frozen == expected
    assert json.dumps(frozen, sort_keys=True) == json.dumps(expected, sort_keys=True)
    frozen["accounts"]["primary"]["cash"] = "0.01"
    assert state["accounts"]["primary"]["cash"] == expected["accounts"]["primary"]["cash"]
    assert frozen["accounts"]["primary"]["cash"] != state["accounts"]["primary"]["cash"]


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_capture_still_rejects(value):
    with pytest.raises(ValueError):
        state_snapshot({"unsupported": value})


def test_circular_capture_preserves_existing_rejection():
    value = {}
    value["cycle"] = value
    with pytest.raises(ValueError, match="Circular"):
        state_snapshot(value)


def test_capture_commit_hash_and_events_survive_intervening_commit_and_rollback(pg_store, tmp_path):
    store, _ = pg_store
    before = store.read()
    before.pop("revision")
    expected = PaperEngine(copy.deepcopy(before), START)
    expected.tick({"BTCUSD": frame()}, study())
    committed, receipt = store.transact_with_receipt(
        START,
        lambda engine: engine.tick({"BTCUSD": frame()}, study()),
        capture_projection=True,
    )
    assert committed == expected.state and receipt["projection_sha256"] == digest(committed)
    persisted = store.read()
    persisted.pop("revision")
    assert persisted == committed
    saved_receipt = copy.deepcopy(receipt)
    later = store.transact(
        START + 2,
        lambda engine: engine.tick({"BTCUSD": frame(START + 2, sequence=2)}, study()),
    )
    assert digest(later) != receipt["projection_sha256"]

    def fail(engine):
        engine.emit("synthetic_uncommitted_capture_attempt", "primary", {})
        raise RuntimeError("Rollback before commit")

    with pytest.raises(RuntimeError, match="Rollback"):
        store.transact(START + 3, fail)
    assert store.last_commit_receipt is None and receipt == saved_receipt
    recorder = EvidenceRecorder(tmp_path / "synthetic-capture.sqlite")
    packet = {"at": START, "kind": "decision", "state_before": state_snapshot(before), "frames": {}}
    recorder.complete(packet, expected.events, committed, [], {}, time.perf_counter(), receipt)
    assert packet["after_tick_sha256"] == digest(committed)
    assert packet["financial_commit"] == saved_receipt
    current = store.read()
    current.pop("revision")
    assert current == later and store.reconcile()["balanced"]
    events = store.export(0, 1000)["records"]
    original = [event for event in events if event["revision"] == receipt["revision"]]
    assert [reference["event_id"] for reference in receipt["events"]] == [
        event["id"] for event in original
    ]
