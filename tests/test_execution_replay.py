import asyncio
import copy
import sqlite3
import time
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from test_paper_engine import frame, study
from test_research_evidence import replacement_packet

from trading.api import create_app
from trading.config import Settings
from trading.evidence_runtime import plain
from trading.execution_profiles import PROFILES
from trading.execution_replay import run_replay, source_hashes
from trading.paper_engine import PaperEngine
from trading.replay_lab import ReplayLab, ReplayPlan, ReplayRegistry
from trading.research_evidence import digest, evidence_page, evidence_record


def slices(decision_packet, offsets=(2, 4, 6), quantities=("0.5", "100", "100")):
    recorder, template, _, features = decision_packet
    state = copy.deepcopy(template["state_before"])
    at = template["at"]
    initial = PaperEngine(state, at)
    initial.tick({"BTCUSD": frame(at)}, study())
    for index, (offset, quantity) in enumerate(zip(offsets, quantities, strict=True)):
        now = at + offset
        frames = {
            "BTCUSD": {
                **frame(now, sequence=index + 2, quantity=quantity),
                "source": "synthetic-replay-fixture",
            }
        }
        packet = copy.deepcopy(template)
        packet.update(
            at=now,
            frames=plain(
                {s: {k: v for k, v in f.items() if k != "book"} for s, f in frames.items()}
            ),
            state_before=plain(state),
        )
        from trading.research_evidence import book_features

        packet["book_features"] = {s: book_features(f, now) for s, f in packet["frames"].items()}
        engine = PaperEngine(state, now)
        engine.tick(frames, copy.deepcopy(features))
        recorder.complete(packet, engine.events, engine.state, [], {}, time.monotonic())
        asyncio.run(recorder.flush())
    ids = sorted(r["id"] for r in evidence_page(recorder.path, limit=50)["records"])
    return recorder, [evidence_record(recorder.path, i) for i in ids]


def test_baseline_reconciles_and_scenarios_use_original_account_engine(decision_packet):
    recorder, records = slices(decision_packet)
    originals = dict(PROFILES)
    result = run_replay(records, source_hashes())
    assert result["status"] == "reconciled"
    assert result["data_mode"] == "synthetic"
    assert all(
        x["state_matches"] and x["events_match"] and x["balanced"] for x in result["baseline"]
    )
    baseline, delay, costs = result["scenarios"]
    assert baseline["fills"][0]["partial"]
    assert baseline["fills"][0]["unfilled_cancelled"] != "0"
    assert costs["condition_stressed_ticks"] == 1
    assert D(costs["fills"][0]["filled_quantity"]) < D(baseline["fills"][0]["filled_quantity"])
    assert delay["fills"][0]["record_id"] == records[1]["id"]
    assert all(
        s["balanced"] and s["net_labels_already_include_execution_costs"]
        for s in result["scenarios"]
    )
    assert PROFILES == originals
    assert result["remaining_opportunity"]["status"] == "unavailable"
    recorder._archive.close()


def test_financial_mismatch_withholds_all_changed_scenarios(decision_packet):
    recorder, records = slices(decision_packet)
    records[0]["payload"]["after_tick_sha256"] = "0" * 64
    records[0]["sha256"] = digest(records[0]["payload"])
    result = run_replay(records, source_hashes())
    assert result["status"] == "reconciliation_failed" and not result["scenarios"]
    assert result["residual"].startswith("Unresolved")
    recorder._archive.close()


def test_missing_book_or_late_feature_never_creates_fills(decision_packet):
    recorder, records = slices(decision_packet)
    invalid = copy.deepcopy(records[0])
    invalid["payload"]["frames"]["BTCUSD"].pop("raw")
    invalid["sha256"] = digest(invalid["payload"])
    with pytest.raises((ValueError, KeyError)):
        run_replay([invalid], source_hashes())
    invalid = copy.deepcopy(records[0])
    invalid["payload"]["feature_origin"]["BTCUSD"]["available_at"] = invalid["payload"]["at"] + 1
    invalid["sha256"] = digest(invalid["payload"])
    with pytest.raises(ValueError, match="features"):
        run_replay([invalid], source_hashes())
    recorder._archive.close()


def test_future_corruption_reordering_and_state_changes_preserve_original_prefix(decision_packet):
    recorder, records = slices(decision_packet)
    original = run_replay(records[:1], source_hashes())
    cases = []
    future = copy.deepcopy(records[1])
    future["payload"]["frames"]["BTCUSD"]["raw"] = "unavailable later book"
    cases.append(future)
    future = copy.deepcopy(records[1])
    future["payload"]["frames"]["BTCUSD"]["source"] = "observed-forward-book"
    cases.append(future)
    future = copy.deepcopy(records[1])
    future["payload"]["frames"]["BTCUSD"]["raw"]["lastUpdateId"] = 2
    cases.append(future)
    future = copy.deepcopy(records[1])
    future["payload"]["frames"]["BTCUSD"]["raw"]["lastUpdateId"] = 1
    cases.append(future)
    future = copy.deepcopy(records[1])
    future["payload"]["at"] = records[0]["payload"]["at"]
    cases.append(future)
    future = copy.deepcopy(records[1])
    future["payload"]["state_before"]["accounts"]["primary"]["funding"] = "999"
    cases.append(future)
    for future in cases:
        future["sha256"] = digest(future["payload"])
        changed = run_replay([records[0], future], source_hashes())
        assert changed["coverage"]["supported"] == 1 and changed["coverage"]["boundary"]
        assert changed["baseline"] == original["baseline"]
        assert changed["scenarios"] == original["scenarios"]
    recorder._archive.close()


def test_source_and_input_hashes_are_frozen(decision_packet):
    recorder, records = slices(decision_packet)
    source = source_hashes()
    source["paper_engine.py"] = "0" * 64
    with pytest.raises(ValueError, match="source changed"):
        run_replay(records, source)
    records[0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash differs"):
        run_replay(records, source_hashes())
    recorder._archive.close()


def test_missing_original_dispatch_order_does_not_guess_from_outcomes(decision_packet):
    recorder, records = slices(decision_packet)
    records[0]["payload"].pop("dispatch_accounts")
    records[0]["sha256"] = digest(records[0]["payload"])
    result = run_replay(records, source_hashes())
    assert result["status"] == "reconciliation_failed" and not result["scenarios"]
    assert not result["baseline"][0]["events_match"]
    recorder._archive.close()


def test_protected_resource_pressure_stops_only_owned_replay_child(decision_packet, tmp_path):
    recorder, records = slices(decision_packet)
    calls = 0

    def allowed():
        nonlocal calls
        calls += 1
        return calls == 1

    lab = ReplayLab(tmp_path / "replays.sqlite", recorder.path, allowed)
    plan = ReplayPlan(request_id="protected-replay-yield", record_id=records[0]["id"], records=3)
    before = evidence_record(recorder.path, records[0]["id"])
    lab.enqueue(plan)
    asyncio.run(lab.run_once())
    job = lab.registry.get(plan.request_id)
    assert job["status"] == "failed" and "resource pressure" in job["error"]
    assert job["resources"]["paid_usd"] == "0" and lab.child is None
    assert evidence_record(recorder.path, records[0]["id"]) == before
    lab.registry.close()
    recorder._archive.close()


def test_gap_keeps_pending_unknown_and_preserves_existing_expiry(decision_packet):
    recorder, records = slices(decision_packet, offsets=(16, 18, 20))
    result = run_replay(records, source_hashes())
    assert not result["scenarios"][0]["fills"]
    assert any(a["kind"] == "order_cancelled" for a in result["scenarios"][0]["actions"])
    recorder._archive.close()


def test_native_child_retains_inputs_limits_and_completed_receipt(decision_packet, tmp_path):
    recorder, records = slices(decision_packet)
    lab = ReplayLab(tmp_path / "replays.sqlite", recorder.path, lambda: True)
    plan = ReplayPlan(request_id="test-native-replay", record_id=records[0]["id"], records=3)
    assert lab.enqueue(plan)["status"] == "queued"
    assert asyncio.run(lab.run_once())
    job = lab.registry.get(plan.request_id)
    assert job["status"] == "completed", job
    assert job["result"]["status"] == "reconciled"
    assert job["resources"]["peak_rss_bytes"] < 256 * 1024**2
    limits = job["result"]["resources"]["child_limits"]
    if limits["processors_allowed"] is not None:
        assert limits["processors_allowed"] <= 2 and limits["priority_class"] == 0x40
    assert lab.enqueue(plan)["retry"] and len(lab.registry.snapshot()["runs"]) == 1
    retained = job["result"]
    lab.registry.close()
    reopened = ReplayRegistry(tmp_path / "replays.sqlite")
    assert reopened.get(plan.request_id)["result"] == retained
    assert (
        not recorder._archive.connection.execute("SELECT count(*) FROM evidence_pins").fetchone()[0]
        == 0
    )
    reopened.close()
    recorder._archive.close()


def test_interrupted_and_failed_attempts_are_not_rewritten_or_evicted(tmp_path):
    path = tmp_path / "replays.sqlite"
    registry = ReplayRegistry(path)
    plan = ReplayPlan(request_id="test-replay-restart", record_id=1)
    registry.reserve(plan)
    registry.inputs(plan.request_id, [{"synthetic": True}])
    registry.claim()
    registry.close()
    registry = ReplayRegistry(path)
    assert registry.get(plan.request_id)["status"] == "interrupted"
    assert registry.reserve(plan)["retry"]
    registry.finish(plan.request_id, {"new": True}, None)
    assert registry.get(plan.request_id)["status"] == "interrupted"
    with pytest.raises(ValueError, match="cannot change"):
        registry.reserve(plan.model_copy(update={"record_id": 2}))
    for i in range(127):
        plan = ReplayPlan(request_id=f"failed-replay-{i:04d}", record_id=1)
        registry.reserve(plan)
        registry.finish(plan.request_id, None, "Inputs missing")
    with pytest.raises(ValueError, match="capacity"):
        registry.reserve(ReplayPlan(request_id="overflow-replay-attempt", record_id=1))
    assert registry.snapshot()["total"] == 128
    current = registry.snapshot()
    ids = []
    while True:
        ids.extend(r["id"] for r in current["runs"])
        if not current["has_more"]:
            break
        current = registry.snapshot(current["next_before"])
    assert len(ids) == 128 and len(set(ids)) == 128
    registry.close()


def test_missing_inputs_and_corrupt_receipts_stay_visible_failures(tmp_path):
    lab = ReplayLab(tmp_path / "replays.sqlite", tmp_path / "missing.sqlite", lambda: True)
    plan = ReplayPlan(request_id="missing-replay-inputs", record_id=1)
    assert lab.enqueue(plan)["status"] == "failed"
    lab.registry.close()
    with sqlite3.connect(tmp_path / "replays.sqlite") as c:
        c.execute("UPDATE replay_runs SET plan='{}'")
    registry = ReplayRegistry(tmp_path / "replays.sqlite")
    with pytest.raises(ValueError, match="corrupt"):
        registry.get(plan.request_id)
    registry.close()


def test_api_only_reserves_local_operator_requests_and_reopens_receipts(tmp_path):
    app = create_app(
        Settings(),
        tmp_path / "monitor.sqlite",
        background=False,
        research_evidence=tmp_path / "no-provider-evidence",
    )
    body = {"request_id": "api-replay-request", "record_id": 1, "records": 1}
    with TestClient(app) as client:
        assert client.post("/api/replays", json=body).status_code == 403
        assert (
            client.post(
                "/api/replays",
                json=body,
                headers={"x-local-operator": "1", "origin": "http://elsewhere"},
            ).status_code
            == 403
        )
        launched = client.post("/api/replays", json=body, headers={"x-local-operator": "1"})
        assert launched.status_code == 200 and launched.json()["status"] == "failed"
        assert client.get("/api/replays").json()["total"] == 1
        assert client.get("/api/replays/api-replay-request").json()["error"]
        assert client.get("/api/replays/unknown").status_code == 404


@pytest.mark.parametrize("v4", [False, True])
def test_recorded_replacement_uses_actual_engine_and_balances_without_mutating_inputs(
    decision_packet, v4
):
    _, record, _ = replacement_packet(decision_packet, "cost-breakout-v1", v4=v4)
    original = copy.deepcopy(record)
    result = run_replay([record], source_hashes())
    assert result["status"] == "reconciled"
    assert result["baseline"][0]["state_matches"] and result["baseline"][0]["events_match"]
    assert all(r["balanced"] for r in result["scenarios"])
    assert record == original


@pytest.mark.parametrize("v4", [False, True])
def test_replacement_missing_source_or_different_method_source_refuses_replay(decision_packet, v4):
    from trading.execution_replay import checked_packet

    _, record, _ = replacement_packet(decision_packet, "cost-breakout-v1", v4=v4)
    for missing in (True, False):
        changed = copy.deepcopy(record)
        if missing:
            changed["payload"]["source_files"].pop("redesign_strategy.py")
        else:
            changed["payload"]["source_files"]["redesign_strategy.py"] = "0" * 64
        changed["sha256"] = digest(changed["payload"])
        with pytest.raises(ValueError, match="source differs"):
            checked_packet(changed, source_hashes())


@pytest.mark.parametrize(
    "source", ["autonomous_spec.py", "rule_components.py", "evidence_runtime.py"]
)
def test_v4_requires_the_explicit_rule_contract_source(decision_packet, source):
    from trading.execution_replay import checked_packet

    _, record, _ = replacement_packet(decision_packet, "cost-breakout-v1", v4=True)
    record["payload"]["source_files"].pop(source)
    record["sha256"] = digest(record["payload"])
    with pytest.raises(ValueError, match="source differs"):
        checked_packet(record, source_hashes())


@pytest.mark.parametrize("v4", [False, True])
def test_altered_replacement_feature_cannot_produce_changed_replay_scenarios(decision_packet, v4):
    _, record, key = replacement_packet(decision_packet, "cost-breakout-v1", v4=v4)
    record["payload"]["study"]["BTCUSD"][key]["eligible"] = False
    record["sha256"] = digest(record["payload"])
    with pytest.raises(ValueError, match="features cannot be reproduced"):
        run_replay([record], source_hashes())


def test_legacy_packet_without_new_source_field_keeps_existing_reproduction(decision_packet):
    from trading.execution_replay import checked_packet

    recorder, packet, frames, features = decision_packet
    engine = PaperEngine(copy.deepcopy(packet["state_before"]), packet["at"])
    engine.tick(frames, features)
    recorder.complete(packet, engine.events, engine.state, [], {}, time.monotonic())
    packet["source_files"].pop("redesign_strategy.py")
    packet["source_files"].pop("evidence_runtime.py")
    record = {"id": 1, "payload": packet, "sha256": digest(packet)}
    assert checked_packet(record, source_hashes()) == packet
