import asyncio
import copy
import time
from decimal import Decimal
from unittest.mock import patch

import pytest
from test_paper_engine import START, frame

from trading.compact_memory import CompactMemory, compact_snapshot
from trading.evidence_runtime import EvidenceRecorder, compact_prefix
from trading.experiment_registry import ExperimentPlan, ExperimentRegistry
from trading.paper_engine import initial_state
from trading.paper_strategy import Bar
from trading.prospective_review import ProspectiveReview, ProspectiveSpec
from trading.research_evidence import EvidenceArchive, EvidencePlan, digest


def test_prospective_freeze_reopen_no_candidate_no_promotion_and_drift(tmp_path):
    registry = ExperimentRegistry(tmp_path / "lab.sqlite")
    review = ProspectiveReview(registry)
    now = time.time()
    spec = ProspectiveSpec(
        request_id="subsequent-test-001", name="Subsequent system", starts_at=now + 3600
    )
    state = initial_state(now)
    original = copy.deepcopy(state)
    frozen = review.freeze(spec, state)
    assert state == original and frozen["components"] == []
    assert review.freeze(spec, state) == frozen
    report = review.report(spec.request_id, state, {"windows": []}, now)
    assert report["status"] == "waiting" and report["decision"] == "no_promotion"
    registry.close()
    registry = ExperimentRegistry(tmp_path / "lab.sqlite")
    review = ProspectiveReview(registry)
    assert review.plans() == [frozen]
    state["accounts"]["primary"]["funding"] = "999"
    result = review.report(spec.request_id, state, {"windows": []}, frozen["ends_at"] + 1)
    assert "primary" in result["configuration_drift"] and result["whole_account_effect"] is None
    with pytest.raises(Exception, match="frozen"):
        registry.db.execute("UPDATE prospective_plans SET end=end+1")
    registry.close()


def test_prospective_rejects_unsupported_combination_and_protects_subsequent_window(tmp_path):
    registry = ExperimentRegistry(tmp_path / "lab.sqlite")
    review = ProspectiveReview(registry)
    now = time.time()
    spec = ProspectiveSpec(
        request_id="subsequent-test-002",
        name="Subsequent system",
        starts_at=now + 3600,
        component_requests=["missing-result"],
    )
    with pytest.raises(ValueError, match="independently qualified"):
        review.freeze(spec, initial_state(now))
    review.freeze(spec.model_copy(update={"component_requests": []}), initial_state(now))
    # A later clock does not allow an inspected retrospective run inside this reservation.
    with patch("trading.experiment_registry.time.time", return_value=now + 86400):
        plan = ExperimentPlan(
            request_id="overlap-test",
            name="Invalid overlap",
            mechanism="A declared comparison mechanism",
            falsification="Reject insufficient evidence",
            as_of=now + 86400,
            test_start=now + 7200,
            test_end=now + 10800,
        )
        with pytest.raises(ValueError, match="prospective"):
            registry.reserve(plan, "source")
    registry.close()


def test_compact_actual_net_links_first_account_and_availability_never_backdated(tmp_path):
    at = START
    memory = CompactMemory(tmp_path / "memory-episodes.sqlite")
    d = {"status": "available", "cutoff": at, "horizon_at": at + 2700, "data_mode": "synthetic"}

    def event(i, kind, when, body, account="primary"):
        return {
            "reference": {"event_id": i},
            "kind": kind,
            "at": when,
            "account": account,
            "body": body,
            "original_event_sha256": digest(body),
        }

    events = [
        event(1, "order_intent", at, {"side": "buy", "version": "breakout-v1", "created_at": at}),
        event(2, "fill", at + 2, {"side": "buy", "created_at": at}),
        event(
            3,
            "trade_closed",
            at + 10,
            {
                "opened_at": at + 2,
                "closed_at": at + 10,
                "cost": "100",
                "proceeds": "99",
                "pnl": "-1",
            },
        ),
    ]
    with patch("trading.compact_memory.time.time", return_value=at + 11):
        memory.append(
            {"at": at + 11, "collected_at": at + 11, "prefix": d, "events": events, "fresh": True}
        )
    assert (
        compact_snapshot(memory.path, at + 2699)["rows"][0]["executable_label"]["status"]
        == "pending"
    )
    with patch("trading.compact_memory.time.time", return_value=at + 3000):
        memory.append(
            {
                "at": at + 2701,
                "collected_at": at + 2701,
                "prefix": None,
                "events": [],
                "fresh": True,
            }
        )
    assert (
        compact_snapshot(memory.path, at + 2999)["rows"][0]["executable_label"]["status"]
        == "pending"
    )
    label = compact_snapshot(memory.path, at + 3000)["rows"][0]["executable_label"]
    assert label["net_bps"] == -100 and label["available_at"] == at + 3000
    assert label["fees_embedded_once"]
    assert label["version"] == "executed-trade-net-v1"
    with pytest.raises(Exception, match="retained"):
        memory.db.execute("DELETE FROM compact_events")
    original = digest(compact_snapshot(memory.path, at + 3000))
    memory.close()
    memory = CompactMemory(tmp_path / "memory-episodes.sqlite")
    memory.append(
        {"at": at + 4000, "collected_at": at + 4000, "prefix": None, "events": [], "fresh": False},
        disk_available=False,
    )
    assert memory.snapshot()["state"] == "disk_pressure"
    assert digest(compact_snapshot(memory.path, at + 3000)) == original
    memory.close()


def test_runtime_prefix_uses_available_scalar_book_and_compact_survives_raw_capacity(tmp_path):
    at = time.time()
    end = int(at // 60) * 60000
    bars = [
        Bar(
            end - (11 - i) * 60000,
            Decimal(100 + i * i / 100),
            Decimal(101 + i * i / 100),
            Decimal(99 + i * i / 100),
            Decimal(100 + i * i / 100),
            Decimal(1),
            end - (11 - i) * 60000 + 59999,
        )
        for i in range(11)
    ]
    d = compact_prefix(at, frame(at), bars, at - 1, {}, "synthetic")
    assert d["status"] == "available" and d["context"]["book"]["status"] == "available"
    assert compact_prefix(at, frame(at), bars, at + 1, {}, "synthetic")["status"] == "invalid_input"
    recorder = EvidenceRecorder(tmp_path / "research-evidence.sqlite")
    recorder._archive = EvidenceArchive(recorder.path, EvidencePlan(max_rows=1))
    recorder._archive.append([{"kind": "summary", "at": at}])
    recorder._archive.append([{"kind": "summary", "at": at + 1}])
    assert recorder._archive.snapshot()["state"] == "capacity"
    recorder.compact({"at": at, "collected_at": at, "fresh": True, "prefix": d, "events": []})
    asyncio.run(recorder.flush())
    assert recorder.snapshot()["compact_memory"]["prefixes"] == 1
    assert recorder.snapshot()["state"] == "capacity"
    recorder._archive.close()
    recorder._compact.close()
