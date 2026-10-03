"""Labeled synthetic capture/reconciliation checks; no real-market inference."""

import copy
import json
from collections import deque
from decimal import Decimal as D

import pytest
from test_paper_engine import frame

from trading.evidence_runtime import EvidenceRecorder, plain, state_snapshot
from trading.execution_replay import run_replay, source_hashes
from trading.execution_window import ExecutionWindow, WindowRequest, tick_preamble
from trading.paper_engine import PaperEngine, initial_state
from trading.paper_strategy import VARIANTS, Bar, features
from trading.recorded_window import verify_recorded_window
from trading.research_evidence import digest


def request(tmp_path, at=24001.0):
    value = WindowRequest(request_id="synthetic-window-0001", not_before=at).model_dump()
    (tmp_path / "execution-window-request.json").write_text(json.dumps(value))
    return value


def synthetic_records(tmp_path, *, steps=541):
    first = 24001.0
    request(tmp_path, first)
    recorder = EvidenceRecorder(tmp_path / "evidence.sqlite")
    recorder.status = {"state": "recording"}
    state = initial_state(first)
    for i in range(steps):
        at = first + 5 * i
        last = int(at // 60) - 1
        bars = [
            Bar(
                (last - 399 + j) * 60000,
                D(100),
                D(101),
                D(99),
                D(100),
                D(10),
                (last - 399 + j) * 60000 + 59999,
            )
            for j in range(400)
        ]
        frames = {"BTCUSD": {**frame(at, sequence=i + 1), "source": "synthetic-window-fixture"}}
        study = {"BTCUSD": {v: features(bars, at, v) for v in VARIANTS}}
        packet = recorder.prepare(
            at,
            frames,
            study,
            {"BTCUSD": bars},
            {"BTCUSD": at},
            0,
            {},
            state_snapshot(state),
            [],
            {"BTCUSD": deque()},
            {},
        )
        packet["pre_tick"] = {
            "feed_model": "paper-tiered-feed-ioc-v2",
            "status_changed": i == 0,
            "errors": {},
            "sources": {"BTCUSD": "synthetic-window-fixture"},
            "notices": [],
            "universe_plan": ["BTCUSD"],
            "bars_added": int(i % 12 == 0),
            "book_sequences": {"BTCUSD": [i + 1, digest(frames["BTCUSD"]["raw"])]},
        }
        engine = PaperEngine(copy.deepcopy(state), at)
        tick_preamble(engine, packet["pre_tick"])
        engine.tick(frames, study)
        packet.update(
            events=plain(engine.events),
            after_tick_sha256=digest(engine.state),
            dispatch_accounts=list(state["accounts"]),
            financial_commit={"revision": i + 1, "committed_at": at, "events": []},
        )
        recorder.execution_window.committed(packet)
        state = copy.deepcopy(engine.state)
        yield {"id": "synthetic-" + str(i), "sha256": digest(packet), "payload": packet}


def test_capture_is_disabled_until_a_finite_operator_request(tmp_path):
    window = ExecutionWindow(tmp_path)
    assert window.status["state"] == "disabled" and not window.selected(24001.0)
    with pytest.raises(ValueError):
        WindowRequest(request_id="synthetic-window-0001", not_before=24001.0, horizon_seconds=10)


def test_failed_frame_keeps_original_selection_checks_and_excluded_candle_context(tmp_path):
    record = next(synthetic_records(tmp_path, steps=1))
    recorder = EvidenceRecorder(tmp_path / "diagnostic.sqlite")
    recorder.execution_window.attach(record["payload"], 0)
    assert recorder.execution_window.committed(record["payload"])
    original = record["payload"]["bars"]["BTCUSD"]
    bars = [
        Bar(row["open_ms"], D(100), D(101), D(99), D(100), D(10), row["close_ms"])
        for row in original
    ]
    selection = {
        "observed_at": 24002.0,
        "markets": {
            "BTCUSD": {
                "frame_present": False,
                "reason": "no_fresh_book",
                "stream": {"eligible": False, "reason": "book_stale"},
                "fallback": {"eligible": False, "received_age_seconds": 1.52},
            }
        },
    }
    packet = recorder.prepare(
        24002.0, {}, {}, {"BTCUSD": bars}, {"BTCUSD": 24001.0}, 0, {},
        state_snapshot(initial_state(24001.0)), [], {}, {},
        feature_timing={"BTCUSD": {"available_at": 24001.0}},
        input_eligibility=selection,
    )
    assert "BTCUSD" not in packet["frames"] and "BTCUSD" not in packet["bars"]
    assert packet["candle_input_status"]["BTCUSD"]["retained_bars"] == 400
    failure = recorder.execution_window.status["first_input_failure"]
    assert failure["first_failed_check"] == "btc_frame_present"
    assert failure["input_eligibility"] == selection
    assert failure["candle_input_status"]["continuous"]
    assert recorder.execution_window.status["state"] == "incomplete"
    assert "execution_window" not in packet


@pytest.mark.parametrize(
    "previous", [[], {"request": []}, {"request": {"request_id": "synthetic-window-0001"}}]
)
def test_malformed_optional_status_refuses_capture_without_stopping_startup(tmp_path, previous):
    request(tmp_path)
    (tmp_path / "execution-window-status.json").write_text(json.dumps(previous))
    window = ExecutionWindow(tmp_path)
    assert window.status["state"] == "refused" and not window.selected(24001.0)


def test_pre_tick_replay_keeps_original_operations_and_order(tmp_path):
    records = list(synthetic_records(tmp_path, steps=2))
    result = run_replay(records, source_hashes())
    assert result["status"] == "reconciled"
    assert all(
        r["state_matches"] and r["events_match"] and r["balanced"] for r in result["baseline"]
    )
    assert records[0]["payload"]["events"][0]["kind"] == "feed_model_changed"
    assert result["data_mode"] == "synthetic"


def test_full_synthetic_horizon_retains_no_trade_results_without_fill_proof(tmp_path):
    result = verify_recorded_window(synthetic_records(tmp_path), source_hashes())
    assert result["status"] == "complete_baseline_reconciled"
    assert result["observed_seconds"] == 2700 and result["records_reconciled"] == 541
    assert result["fill_events"] == 0 and result["no_trade_ticks"] == 541
    assert result["data_mode"] == "synthetic" and not result["market_improvement_established"]


@pytest.mark.parametrize("failure", ["commit_gap", "warmup_gap", "future_receipt", "missing_book"])
def test_missing_evidence_cannot_be_bridged_or_backdated(tmp_path, failure):
    records = list(synthetic_records(tmp_path, steps=2))
    p = records[1]["payload"]
    if failure == "commit_gap":
        p["financial_commit"]["revision"] += 1
    elif failure == "warmup_gap":
        p["bars"]["BTCUSD"].pop(10)
    elif failure == "future_receipt":
        p["frames"]["BTCUSD"]["observed"] = p["at"] + 1
    else:
        p["frames"] = {}
    records[1]["sha256"] = digest(p)
    result = verify_recorded_window(records, source_hashes())
    assert result["status"] == "incomplete" and not result["full_horizon_verified"]
    assert result["boundary"]


def test_restart_and_queue_failure_preserve_an_incomplete_request(tmp_path):
    request(tmp_path)
    window = ExecutionWindow(tmp_path)
    window.status.update(state="capturing", first_at=24001.0)
    window.persist()
    assert ExecutionWindow(tmp_path).status["state"] == "incomplete"
    recorder = EvidenceRecorder(tmp_path / "evidence.sqlite")
    recorder.status = {"state": "recording"}
    recorder.execution_window.status["state"] = "capturing"
    recorder.pending.extend([{"kind": "decision"}] * recorder.queue_limit)
    assert not recorder.selected(24002.0, False)
    assert recorder.execution_window.status["state"] == "incomplete"


def test_status_failure_cannot_stop_financial_work_or_claim_completed_capture(
    tmp_path, monkeypatch
):
    request(tmp_path)
    recorder = EvidenceRecorder(tmp_path / "evidence.sqlite")

    def unavailable():
        raise OSError("Synthetic unavailable receipt destination")

    monkeypatch.setattr(recorder.execution_window, "persist", unavailable)
    recorder._write_batch([], [], True)
    assert recorder.execution_window.status["state"] == "incomplete"
    assert recorder.status["state"] == "unavailable"


def test_finite_byte_budget_refuses_the_packet_before_enqueue(tmp_path):
    record = next(synthetic_records(tmp_path, steps=1))
    window = ExecutionWindow(tmp_path)
    window.status.update(
        state="capturing",
        first_at=record["payload"]["at"],
        required_end_at=record["payload"]["at"] + 2700,
        omissions_at_start=0,
        bytes=window.request.max_bytes - 1,
    )
    assert not window.committed(record["payload"])
    assert window.status["state"] == "incomplete" and window.status["records"] == 0


def test_auxiliary_omissions_do_not_replace_required_tick_continuity(tmp_path):
    records = list(synthetic_records(tmp_path, steps=2))
    window = ExecutionWindow(tmp_path)
    for omissions, record in enumerate(records):
        packet = record["payload"]
        window.attach(packet, omissions)
        assert window.committed(packet)
    assert window.status["state"] == "capturing"
    assert window.status["auxiliary_capture_omissions_since_start"] == 1
    assert window.status["records"] == 2
    missing = records[-1]["payload"]
    missing["financial_commit"]["revision"] += 2
    assert not window.committed(missing)
    assert window.status["state"] == "incomplete"


def test_retention_deferral_has_real_time_bounds(tmp_path):
    request(tmp_path)
    window = ExecutionWindow(tmp_path)
    assert not window.defer_retention(1.0)  # A far-future request cannot pause maintenance.
    assert window.defer_retention(24001.0)
    assert not window.defer_retention(24602.0)
    window.status.update(state="capturing", required_end_at=26701.0)
    assert window.defer_retention(26000.0)
    assert not window.defer_retention(26707.0)
    window.fail("Synthetic terminal request")
    assert not window.defer_retention(26000.0)
