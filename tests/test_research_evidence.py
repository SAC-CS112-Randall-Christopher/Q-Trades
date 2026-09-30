import asyncio
import copy
import sqlite3
import time
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from test_paper_engine import frame

from trading.api import create_app
from trading.config import Settings
from trading.evidence_runtime import EvidenceRecorder, feature_reproduction, frozen_bars, plain
from trading.paper_engine import PaperEngine
from trading.research_evidence import (
    EvidenceArchive,
    EvidencePlan,
    book_features,
    evidence_page,
    evidence_record,
)


def test_restart_capacity_and_pins_never_evict_required_inputs(tmp_path):
    path = tmp_path / "archive.sqlite"
    archive = EvidenceArchive(path, EvidencePlan(max_rows=2))
    archive.append(
        [
            {"at": 1.0, "kind": "decision", "value": "original"},
            {"at": 2.0, "kind": "decision", "value": "later"},
        ]
    )
    original = evidence_record(path, 1)
    archive.pin("frozen-experiment", 1, original["sha256"])
    archive.append([{"at": 3.0, "kind": "decision", "value": "overflow"}])
    assert archive.snapshot()["state"] == "capacity"
    archive.close()
    reopened = EvidenceArchive(path)
    reopened.append([{"at": 4.0, "kind": "decision", "value": "restart cannot evict"}])
    assert evidence_record(path, 1) == original
    assert reopened.snapshot()["rows"] == 2 and reopened.snapshot()["dropped"] == 2
    with pytest.raises(ValueError, match="redirected"):
        reopened.pin("frozen-experiment", 2, evidence_record(path, 2)["sha256"])
    reopened.close()
    with pytest.raises(ValueError, match="Frozen retention"):
        EvidenceArchive(path, EvidencePlan(max_rows=3))


def test_disk_pressure_preserves_prior_data_and_resumes_only_optional_work(tmp_path):
    archive = EvidenceArchive(tmp_path / "archive.sqlite")
    archive.append([{"at": 1.0, "kind": "summary"}])
    archive.append([{"at": 2.0, "kind": "summary"}], disk_available=False)
    assert archive.snapshot()["state"] == "disk_pressure"
    assert archive.snapshot()["rows"] == 1
    archive.append([{"at": 3.0, "kind": "summary"}])
    assert archive.snapshot()["rows"] == 2 and archive.snapshot()["dropped"] == 1
    archive.close()


def test_disk_pressure_skips_optional_lookup_and_empty_flush_resumes(tmp_path, monkeypatch):
    archive = EvidenceArchive(tmp_path / "archive.sqlite")

    def forbidden(packet):
        raise AssertionError("Optional lookup must not run under disk pressure")

    monkeypatch.setattr(archive, "_describe", forbidden)
    archive.append(
        [{"schema": "causal-evidence-v1", "kind": "decision", "at": 1.0}], disk_available=False
    )
    assert archive.snapshot()["rows"] == 0 and archive.snapshot()["state"] == "disk_pressure"
    archive.append([])
    assert archive.snapshot()["state"] == "recording"
    archive.close()


def test_corrupt_content_and_incomplete_metadata_are_not_repaired_silently(tmp_path):
    path = tmp_path / "archive.sqlite"
    archive = EvidenceArchive(path)
    archive.append([{"at": 1.0, "kind": "decision", "value": "immutable"}])
    archive.close()
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE evidence_records SET payload='{}'")
    with pytest.raises(ValueError, match="corrupt"):
        evidence_record(path, 1)
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM evidence_meta")
    with pytest.raises(ValueError, match="metadata"):
        EvidenceArchive(path)


def test_invalid_packet_rolls_back_whole_batch(tmp_path):
    archive = EvidenceArchive(tmp_path / "archive.sqlite")
    with pytest.raises(ValueError):
        archive.append([{"at": 1.0, "kind": "summary"}, {"at": float("nan"), "kind": "summary"}])
    assert archive.snapshot()["rows"] == 0
    archive.close()


def test_pagination_conserves_membership_without_wires_hiding_decisions(tmp_path):
    path = tmp_path / "archive.sqlite"
    archive = EvidenceArchive(path)
    archive.append([{"at": float(i), "kind": "wire" if i % 2 else "decision"} for i in range(12)])
    first = evidence_page(path, limit=3)
    second = evidence_page(path, before=first["next_before"], limit=3)
    assert len({r["id"] for r in first["records"] + second["records"]}) == 6
    assert first["has_more"] and not second["has_more"]
    assert all(r["kind"] == "decision" for r in first["records"] + second["records"])
    archive.close()


def test_recorded_feature_inputs_do_not_change_with_later_revisions(decision_packet):
    recorder, packet, frames, study = decision_packet
    frames["BTCUSD"]["raw"]["bids"][0][0] = "999"
    study["BTCUSD"]["breakout-v1"]["reason"] = "later revision"
    recorder.enqueue(packet)
    asyncio.run(recorder.flush())
    restored = evidence_record(recorder.path, 1)["payload"]
    reproduction = feature_reproduction(restored)
    assert reproduction["book_features_match"]
    assert all(r["matched"] for r in reproduction["closed_bar_features"].values())
    assert restored["frames"]["BTCUSD"]["raw"]["bids"][0][0] != "999"
    recorder._archive.close()


@pytest.mark.parametrize("delta", [0.1, 4.0])
def test_future_and_stale_receipts_cannot_supply_features(delta):
    value = frame(10.0)
    value.pop("book")
    at = 10.0 - delta if delta < 1 else 10.0 + delta
    assert book_features(value, at)["status"] == "unavailable"


def test_unavailable_origin_is_an_explicit_gap(decision_packet):
    _, packet, _, _ = decision_packet
    packet["feature_origin"].clear()
    result = feature_reproduction(packet)
    assert result["closed_bar_features"]["BTCUSD"]["status"] == "unavailable"


def test_late_feature_availability_cannot_backdate_its_result(decision_packet):
    _, packet, _, _ = decision_packet
    packet["feature_origin"]["BTCUSD"]["available_at"] = packet["at"] + 1
    result = feature_reproduction(packet)
    assert result["closed_bar_features"]["BTCUSD"]["reason"].startswith("Feature computation")


def test_queue_reserves_decisions_and_rejects_oversized_packets(tmp_path):
    recorder = EvidenceRecorder(tmp_path / "archive.sqlite")
    for i in range(8):
        recorder.enqueue({"at": float(i), "kind": "wire"})
    assert len(recorder.pending) == 6
    recorder.enqueue({"at": 9.0, "kind": "decision"})
    assert len(recorder.pending) == 7
    recorder.enqueue({"at": 10.0, "kind": "decision", "body": "x" * (2 * 1024 * 1024)})
    assert len(recorder.pending) == 7 and recorder.dropped == 3


def test_rolled_back_attempts_are_not_linked_as_committed_actions(decision_packet):
    recorder, packet, frames, study = decision_packet
    engine = PaperEngine(copy.deepcopy(packet["state_before"]), packet["at"])
    engine.evidence_trace = []
    engine.tick(frames, study)
    erased = engine.events.pop()
    recorder.complete(
        packet, engine.events, engine.state, engine.evidence_trace, {}, time.monotonic()
    )
    assert any(t.get("committed_action") is False for t in packet["event_timing"])
    assert all("_event" not in t for t in packet["event_timing"])
    assert erased not in packet["events"]


def test_trace_does_not_change_financial_results(decision_packet):
    _, packet, frames, study = decision_packet
    ordinary = PaperEngine(copy.deepcopy(packet["state_before"]), packet["at"])
    traced = PaperEngine(copy.deepcopy(packet["state_before"]), packet["at"])
    traced.evidence_trace = []
    ordinary.tick(frames, study)
    traced.tick(frames, study)
    assert ordinary.state == traced.state and ordinary.events == traced.events
    assert traced.evidence_trace and all(r["mono"] > 0 for r in traced.evidence_trace)
    assert any(r["phase"] == "decision_evaluation_start" for r in traced.evidence_trace)


def test_queue_overflow_is_counted_and_bounded(tmp_path):
    recorder = EvidenceRecorder(tmp_path / "archive.sqlite")
    for i in range(15):
        recorder.enqueue({"at": float(i), "kind": "decision"})
    assert len(recorder.pending) == 8 and recorder.snapshot()["queue_dropped"] == 7
    asyncio.run(recorder.flush())
    assert recorder.snapshot()["rows"] == 8
    recorder._archive.close()


def test_selection_freezes_ordinary_and_no_trade_windows():
    plan = EvidencePlan()
    assert plan.selected(300.0) and plan.selected(309.99)
    assert not plan.selected(310.0) and plan.selected(600.0)


def test_faster_snapshot_copy_preserves_every_original_scalar(decision_packet):
    from dataclasses import asdict

    from trading.paper_strategy import Bar

    _, packet, _, _ = decision_packet
    rows = packet["bars"]["BTCUSD"]
    bars = [
        Bar(
            r["open_ms"],
            D(r["open"]),
            D(r["high"]),
            D(r["low"]),
            D(r["close"]),
            D(r["volume"]),
            r["close_ms"],
        )
        for r in rows
    ]
    expected = plain([{**asdict(b), "available_at": packet["at"]} for b in bars])
    assert frozen_bars(bars, packet["at"]) == expected


def test_readonly_normal_api_reopen_and_corruption_failure(tmp_path, decision_packet):
    _, packet, _, _ = decision_packet
    path = tmp_path / "research-evidence.sqlite"
    archive = EvidenceArchive(path)
    archive.append([packet])
    archive.close()
    with TestClient(
        create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    ) as client:
        listing = client.get("/api/evidence").json()
        assert listing["records"][0]["sha256"]
        value = client.get("/api/evidence/1")
        assert value.status_code == 200 and value.json()["reproduction"]["book_features_match"]
        assert client.get("/api/evidence/900").status_code == 404
        assert client.get("/api/evidence?limit=5000").status_code == 422
        assert client.get("/api/evidence?kind=unknown").status_code == 422
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE evidence_records SET payload='{}'")
        assert client.get("/api/evidence/1").status_code == 409


def test_failed_optional_writer_exposes_failure_instead_of_stopping_finance(tmp_path):
    path = tmp_path / "corrupt.sqlite"
    path.write_bytes(b"not sqlite")
    original = path.read_bytes()
    recorder = EvidenceRecorder(path)
    recorder.enqueue({"at": 1.0, "kind": "summary"})

    async def run():
        task = asyncio.create_task(recorder.run(lambda: True))
        await asyncio.sleep(0.1)
        assert not task.done()
        assert recorder.snapshot()["state"] == "unavailable"
        assert recorder.snapshot()["queue_dropped"] == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert path.read_bytes() == original
