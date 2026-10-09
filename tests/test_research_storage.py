import asyncio
import sqlite3
from pathlib import Path

import pytest
from test_paper_store import pg_store as pg_store

from trading.autonomous_spec import RuleSpec, rule_feature
from trading.compact_memory import CompactMemory
from trading.evidence_runtime import EvidenceRecorder
from trading.research_evidence import (
    EvidenceArchive,
    EvidencePlan,
    canonical,
    digest,
    evidence_record,
)
from trading.research_storage import (
    ResearchStorage,
    StoragePlan,
    reopen_evidence,
    save_plan,
    storage_snapshot,
    volume,
)


@pytest.fixture(autouse=True)
def declared_storage_clock(monkeypatch):
    monkeypatch.setattr("trading.research_storage.time.time", lambda: 1_800_000_000)


def plan_at(folder, **changes):
    root = folder / "Q-Trades-Data-qa-test"
    return StoragePlan(
        root=str(root),
        volume_identity=volume(root)["identity"],
        temporary_bytes=8 * 1024**2,
        research_bytes=8 * 1024**2,
        scratch_bytes=256 * 1024,
        segment_bytes=64 * 1024,
        free_reserve_bytes=0,
        temporary_retention_seconds=7200,
        **changes,
    )


def test_finite_capture_defers_only_optional_retention_and_keeps_admission(tmp_path, monkeypatch):
    plan = plan_at(tmp_path)
    store = ResearchStorage(plan)
    calls = []
    monkeypatch.setattr(store, "housekeeping", lambda now, **kwargs: calls.append(kwargs))
    try:
        first = packet(1_800_000_001)
        reference = store.append([first], first["at"], defer_retention=True)[0]
        assert store.reopen(reference)["kind"] == first["kind"]
        assert calls == []
        store.append([packet(1_800_000_002)], 1_800_000_002)
        assert calls == [{"capacity_triggered": False}]
        calls.clear()
        real_bytes = __import__("trading.research_storage", fromlist=["_bytes"])._bytes
        monkeypatch.setattr(
            "trading.research_storage._bytes",
            lambda folder: (
                plan.temporary_bytes - 2 * plan.scratch_bytes + 1
                if folder == store.temporary
                else real_bytes(folder)
            ),
        )
        store.append([packet(1_800_000_003)], 1_800_000_003, defer_retention=True)
        assert calls == [{"capacity_triggered": True}]
        monkeypatch.setattr("trading.research_storage._bytes", real_bytes)
        (store.temporary / "quota-fixture").write_bytes(b"x" * plan.temporary_bytes)
        with pytest.raises(OSError, match="quota"):
            store.append([packet(1_800_000_004)], 1_800_000_004, defer_retention=True)
    finally:
        store.close()


def test_recorder_defers_retention_only_for_a_finite_request(tmp_path, monkeypatch):
    from trading.execution_window import WindowRequest

    config = tmp_path / "coordination"
    save_plan(config, plan_at(tmp_path))
    (config / "execution-window-request.json").write_text(
        WindowRequest(
            request_id="synthetic-writer-priority", not_before=1_800_000_000.0
        ).model_dump_json()
    )
    calls = []
    monkeypatch.setattr(ResearchStorage, "housekeeping", lambda self, *a, **k: calls.append(k))
    recorder = EvidenceRecorder(config / "research-evidence.sqlite")
    recorder.enqueue(packet(1_800_000_000))
    asyncio.run(recorder.flush())
    assert recorder.status["state"] == "recording" and calls == []
    assert (config / "execution-window-status.json").exists()
    recorder.execution_window.fail("Synthetic test finished its finite request")
    recorder.enqueue(packet(1_800_000_001))
    asyncio.run(recorder.flush())
    assert calls  # The ordinary retention path resumes without a new authority.
    recorder._compact.close()
    recorder._storage.close()
    recorder._maturity.close()


def test_empty_capacity_retry_cannot_report_new_capture_and_recovers_with_real_space(tmp_path):
    config = tmp_path / "coordination"
    plan = plan_at(tmp_path)
    save_plan(config, plan)
    recorder = EvidenceRecorder(config / "research-evidence.sqlite")
    first = packet(1_800_000_000)
    recorder.enqueue(first)
    asyncio.run(recorder.flush())
    reference = recorder.storage_status["latest_reference"]
    captured = recorder.storage_status["last_capture"]
    used = recorder.storage_status["temporary_bytes"]
    # A small empty-pass request fits, but the declined real input does not.
    fixture = Path(plan.root) / "temporary" / "owned-quota-fixture"
    fixture.write_bytes(b"x" * (plan.temporary_bytes - used - plan.scratch_bytes - 131072))
    refused = packet(1_800_000_001, sample="x" * 500000)
    recorder.enqueue(refused)
    asyncio.run(recorder.flush())
    assert recorder.status["state"] == "unavailable"
    assert recorder.dropped == 1
    assert recorder.storage_status["full_omitted"] == 1
    recorder.enqueue(packet(1_800_000_001.5))  # Admission still refuses under pressure.
    assert recorder.dropped == 2
    for _ in range(3):
        asyncio.run(recorder.flush())
        assert recorder.status["state"] == "unavailable"
        assert "quota" in recorder.storage_status["reason"]
        assert recorder.storage_status["last_capture"] == captured
        assert recorder.storage_status["latest_reference"] == reference
        assert recorder.maturity_status["state"] == "observed"
        assert recorder.dropped == 2
        assert storage_snapshot(config)["full_omitted"] == 2
    assert reopen_evidence(plan, reference)["at"] == first["at"]
    recorder = EvidenceRecorder(config / "research-evidence.sqlite")
    assert recorder.dropped == 2  # Restart cannot erase durably reported omissions.
    asyncio.run(recorder.flush())
    resumed = storage_snapshot(config)
    assert resumed["state"] == "unavailable" and resumed["full_omitted"] == 2
    assert resumed["last_capture"] == captured and resumed["latest_reference"] == reference
    # Removing only the owned pressure fixture restores space without changing
    # quotas, clocks, accounts or retained evidence. Real acquisition can resume.
    fixture.unlink()
    asyncio.run(recorder.flush())
    assert recorder.status["state"] == "recording"
    recorder.enqueue(packet(1_800_000_002))
    asyncio.run(recorder.flush())
    assert recorder.storage_status["last_capture"] == 1_800_000_002
    assert recorder.storage_status["latest_reference"] != reference
    assert reopen_evidence(plan, reference)["at"] == first["at"]
    recorder._compact.close()
    recorder._storage.close()
    recorder._maturity.close()


def packet(at, kind="decision", **changes):
    return {
        "schema": "causal-evidence-v1",
        "kind": kind,
        "at": at,
        "sample": "bounded" * 1500,
        **changes,
    }


def test_rollovers_reopen_pending_and_two_hour_continuation(tmp_path):
    plan = plan_at(tmp_path)
    store = ResearchStorage(plan)
    now = 1_800_000_000
    values = [packet(now + i, "rejected" if i % 2 else "no_trade") for i in range(18)]
    refs = []
    for start in range(0, len(values), 6):
        refs.extend(store.append(values[start : start + 6], now))
    store.protect(refs[0], now + 4 * 86400, "Pending multi-day label")
    for cycle in range(1, 6):
        store.housekeeping(now + cycle * 7200, capacity_triggered=True)
    assert len(list(store.research.glob("segment-*.jsonl.gz"))) > 2
    assert store._path(1).exists()  # Multi-day dependency survives several cycles.
    assert store.snapshot()["last_success"] == now + 5 * 7200
    for ref, value in zip(refs, values, strict=True):
        assert reopen_evidence(plan, ref) == value
    store.housekeeping(now + 5 * 86400, capacity_triggered=True)
    assert not store._path(1).exists()
    assert store.reopen(refs[0]) == values[0]
    count = store.snapshot()["rows"]
    assert store.append([values[0]], now + 6 * 86400) == refs[:1]
    assert store.snapshot()["rows"] == count
    store.close()
    reopened = ResearchStorage(plan)
    assert reopened.reopen(refs[-1]) == values[-1]
    reopened.close()


def test_failed_transfer_last_source_checksum_and_recovery(tmp_path, monkeypatch):
    store = ResearchStorage(plan_at(tmp_path))
    value = packet(1_800_000_000)
    ref = store.append([value], value["at"])[0]
    original = __import__("os").replace

    def interrupted(source, target):
        raise OSError("Simulated USB disconnect during transfer")

    monkeypatch.setattr("trading.research_storage.os.replace", interrupted)
    with pytest.raises(OSError, match="disconnect"):
        store.housekeeping(value["at"] + 7200, capacity_triggered=True)
    assert store._path(1).exists()
    assert store.snapshot()["last_success"] is None
    monkeypatch.setattr("trading.research_storage.os.replace", original)
    store.housekeeping(value["at"] + 14400, capacity_triggered=True)
    retained = next(store.research.glob("segment-*.jsonl.gz"))
    retained.write_bytes(b"corrupt-copy")
    with pytest.raises(ValueError, match="differs"):
        store.housekeeping(value["at"] + 21600, capacity_triggered=True)
    assert store._path(1).exists()
    assert store.reopen(ref) == value
    store.close()


def test_absence_mapping_access_and_quota_no_spill(tmp_path, monkeypatch):
    config = tmp_path / "coordination"
    plan = plan_at(tmp_path)
    save_plan(config, plan)
    recorder = EvidenceRecorder(config / "research-evidence.sqlite")
    real_volume = volume
    monkeypatch.setattr(
        "trading.research_storage.volume",
        lambda path: {"identity": "wrong-worker-mapping", "free_bytes": 10**12},
    )
    recorder.enqueue(packet(1_800_000_000))
    asyncio.run(recorder.flush())
    assert recorder.status["state"] == "unavailable"
    assert recorder.storage_status["fallback"] is False
    assert not recorder.path.exists()
    assert not (config / "memory-episodes.sqlite").exists()
    monkeypatch.setattr("trading.research_storage.volume", real_volume)
    asyncio.run(recorder.flush())
    recorder.enqueue(packet(1_800_000_001))
    asyncio.run(recorder.flush())
    assert recorder.status["state"] == "recording"
    store = recorder._storage
    assert store is not None
    (store.research / "quota-fixture").write_bytes(b"x" * plan.research_bytes)
    with pytest.raises(OSError, match="quota"):
        store.housekeeping(1_800_010_000, capacity_triggered=True)
    assert store._path(1).exists()
    (store.research / "quota-fixture").unlink()
    monkeypatch.setattr(
        "trading.research_storage.volume",
        lambda path: {"identity": plan.volume_identity, "free_bytes": 0},
    )
    with pytest.raises(OSError, match="reserve"):
        store.append([packet(1_800_000_002)], 1_800_000_002)

    def absent(path):
        raise OSError("Drive absent at startup")

    monkeypatch.setattr("trading.research_storage.volume", absent)
    assert storage_snapshot(config)["state"] == "unavailable"
    with pytest.raises(OSError):
        ResearchStorage(plan)
    monkeypatch.setattr("trading.research_storage.volume", real_volume)
    recorder._compact.close()
    store.close()


def test_legacy_frozen_backup_versioned_limits_and_single_maintenance(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    full = EvidenceArchive(source / "research-evidence.sqlite")
    full.append([packet(1_800_000_000, "wire")])
    full.close()
    old_hash = digest((source / "research-evidence.sqlite").read_bytes().hex())
    compact = CompactMemory(source / "memory-episodes.sqlite")
    compact.db.execute("UPDATE compact_meta SET state='capacity'")
    compact.db.commit()
    compact.close()
    store = ResearchStorage(plan_at(tmp_path))
    store.continue_legacy(source / "research-evidence.sqlite")
    copy = store.continue_compact(source / "memory-episodes.sqlite")
    continued = CompactMemory(copy, storage_bytes=store.plan.research_bytes)
    assert continued.snapshot()["state"] == "recording"
    assert continued.db.execute("SELECT state FROM compact_meta").fetchone()[0] == "capacity"
    assert digest((source / "research-evidence.sqlite").read_bytes().hex()) == old_hash
    with sqlite3.connect(source / "memory-episodes.sqlite") as db:
        assert db.execute("SELECT state FROM compact_meta").fetchone()[0] == "capacity"
    continued.close()
    other = ResearchStorage(store.plan)
    store.db.execute("BEGIN IMMEDIATE")
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        other.housekeeping(1_800_010_000, capacity_triggered=True)
    store.db.rollback()
    other.close()
    store.close()


@pytest.mark.parametrize("complete", [True, False])
def test_blocked_acquisition_matures_due_full_and_compact_without_editing_sources(
    tmp_path, decision_packet, monkeypatch, complete
):
    import copy

    from test_pattern_memory import rows_at

    from trading.compact_memory import compact_evidence, compact_snapshot
    from trading.outcome_continuation import NAME

    source = tmp_path / "legacy"
    source.mkdir()
    _, original, _, _ = decision_packet
    clock = [original["at"] + 0.1]
    monkeypatch.setattr("time.time", lambda: clock[0])
    path = source / "research-evidence.sqlite"
    full = EvidenceArchive(path, EvidencePlan(max_rows=1))
    full.append([original])
    first = evidence_record(path, 1)
    d = first["payload"]["episode"]["descriptor"]
    full.append([{"at": clock[0], "kind": "wire"}])
    assert full.snapshot()["state"] == "capacity"
    full.close()
    compact_source = source / "memory-episodes.sqlite"
    compact = CompactMemory(compact_source)
    events = []
    if complete:
        for i, (kind, at, body) in enumerate(
            [
                (
                    "order_intent",
                    d["cutoff"],
                    {"side": "buy", "version": "breakout-v1", "created_at": d["cutoff"]},
                ),
                ("fill", d["cutoff"] + 1, {"side": "buy", "created_at": d["cutoff"]}),
                (
                    "trade_closed",
                    d["cutoff"] + 60,
                    {
                        "opened_at": d["cutoff"] + 1,
                        "closed_at": d["cutoff"] + 60,
                        "cost": "100",
                        "proceeds": "99",
                        "pnl": "-1",
                        "fees": ".2",
                    },
                ),
            ]
        ):
            events.append(
                {
                    "reference": {"event_id": i + 1},
                    "kind": kind,
                    "at": at,
                    "account": "synthetic",
                    "body": body,
                    "committed_at": at + 0.01,
                }
            )
    compact.append(
        {"at": d["cutoff"], "collected_at": clock[0], "events": events, "prefix": d, "fresh": False}
    )
    compact.db.execute("UPDATE compact_meta SET state='capacity'")
    compact.db.commit()
    compact.close()
    before = {p.name: p.read_bytes() for p in (path, compact_source)}
    plan = plan_at(tmp_path)
    save_plan(source, plan)
    store = ResearchStorage(plan)
    store.continue_legacy(path)
    copy_path = store.continue_compact(compact_source)
    continued = CompactMemory(copy_path, storage_bytes=plan.research_bytes)
    continued.db.execute("UPDATE compact_v2_state SET state='capacity'")
    continued.db.commit()
    # Real acquisition cannot fit; the research tier still has room for delayed receipts.
    (store.temporary / "quota-fixture").write_bytes(b"x" * plan.temporary_bytes)
    recorder = EvidenceRecorder(path)
    recorder._storage, recorder._compact = store, continued
    clock[0] = d["horizon_at"] + 2
    later = copy.deepcopy(original)
    later["at"] = clock[0]
    later["bars"]["BTCUSD"] = rows_at(clock[0], 60, "10") if complete else []
    recorder.enqueue(later)
    asyncio.run(recorder.flush())
    assert recorder.status["state"] == "unavailable"  # acquisition gate stays closed
    assert recorder.maturity_status["state"] == "observed"
    assert recorder.maturity_status["processed_this_pass"] == 2
    episode = digest(d)
    result = compact_evidence(copy_path, episode, episode)
    label = result["outcome"]
    assert label["available_at"] == clock[0] > d["horizon_at"]
    assert label["status"] == ("available" if complete else "unavailable")
    assert label["net_bps"] == (-100 if complete else None)  # retain the actual loss
    assert (
        compact_snapshot(copy_path, clock[0] - 0.01)["rows"][0]["executable_label"]["status"]
        == "pending"
    )
    assert compact_snapshot(copy_path, clock[0])["rows"][0]["executable_label"] == label
    market = evidence_record(path, 1)["subsequent_outcome"]["payload"]
    assert market["status"] == ("available" if complete else "unavailable")
    assert market["realized_pnl"] is None  # a price path remains a price-only label
    assert market["available_at"] == clock[0]
    with sqlite3.connect(copy_path.parent / NAME) as db:
        assert db.execute("SELECT count(*) FROM continued_outcomes").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE continued_outcomes SET available=0")
    clock[0] += 60
    asyncio.run(recorder.flush())  # retry/reopen after acquisition failure
    assert recorder.status["state"] == "unavailable"
    assert "quota" in recorder.storage_status["reason"]
    assert recorder.maturity_status["state"] == "observed"
    assert compact_evidence(copy_path, episode, episode)["outcome"] == label
    assert {p.name: p.read_bytes() for p in (path, compact_source)} == before
    # Persistent acquisition pressure closes optional writer handles on every
    # retry while durable due receipts remain available to read-only consumers.
    for handle in (recorder._compact, recorder._storage, recorder._maturity):
        if handle is not None:
            handle.close()


def test_due_continuation_is_bounded_and_resource_pending_survives_restart(tmp_path, monkeypatch):
    from test_pattern_memory import entry

    from trading.outcome_continuation import OutcomeContinuation, continued_outcome

    path = tmp_path / "memory-episodes.sqlite"
    compact = CompactMemory(path)
    for i in range(20):
        d = entry(6000 + i * 3300, str(i))["descriptor"]
        sha = digest(d)
        compact.db.execute(
            "INSERT INTO compact_prefixes VALUES(NULL,?,?,?,?,?)",
            (sha, d["cutoff"], d["cutoff"] + 0.1, canonical(d), sha),
        )
    compact.db.execute("UPDATE compact_meta SET state='capacity'")
    compact.db.commit()
    compact.close()
    unchanged = path.read_bytes()
    now = 80000
    cont = OutcomeContinuation(tmp_path)

    def blocked(amount):
        raise OSError("Declared outcome disk guard")

    with pytest.raises(OSError, match="disk guard"):
        cont.process(tmp_path / "absent.sqlite", path, [], now, blocked)
    assert cont.db.execute("SELECT count(*) FROM continued_outcomes").fetchone()[0] == 0
    cont.close()

    cont = OutcomeContinuation(tmp_path)
    first = cont.process(tmp_path / "absent.sqlite", path, [], now, lambda _: None)
    assert first["processed_this_pass"] == 16
    second = cont.process(tmp_path / "absent.sqlite", path, [], now + 1, lambda _: None)
    assert second["processed_this_pass"] == 4
    assert cont.db.execute("SELECT count(*) FROM continued_outcomes").fetchone()[0] == 20
    row = cont.db.execute("SELECT * FROM continued_outcomes LIMIT 1").fetchone()
    saved = continued_outcome(tmp_path, "compact", row["episode"], row["source_sha"], now + 100)
    assert saved["status"] == "unavailable" and saved["net_bps"] is None
    assert saved["available_at"] == now
    assert path.read_bytes() == unchanged
    assert (
        cont.process(tmp_path / "absent.sqlite", path, [], now + 60, lambda _: None)[
            "processed_this_pass"
        ]
        == 0
    )
    cont.close()


def test_research_acquisition_quota_leaves_due_receipt_headroom(tmp_path):
    from test_pattern_memory import entry

    from trading.outcome_continuation import OutcomeContinuation

    plan = plan_at(tmp_path)
    plan = plan.model_copy(update={"scratch_bytes": 1024**2})
    store = ResearchStorage(plan)
    compact_path = store.research / "memory-episodes.sqlite"
    compact = CompactMemory(compact_path, storage_bytes=plan.research_bytes)
    d = entry(6000, "due")["descriptor"]
    compact.db.execute(
        "INSERT INTO compact_prefixes VALUES(NULL,?,?,?,?,?)",
        (digest(d), d["cutoff"], d["cutoff"] + 0.1, canonical(d), digest(d)),
    )
    compact.db.execute("UPDATE compact_v2_state SET state='capacity'")
    compact.db.commit()
    compact.close()
    cont = OutcomeContinuation(store.research, plan.research_bytes)
    # Leave exactly normal acquisition's reserved scratch, counting all actual files.
    used = sum(p.stat().st_size for p in store.research.iterdir() if p.is_file())
    padding = store.research / "quota-fixture"
    padding.write_bytes(b"x" * (plan.research_bytes - plan.scratch_bytes - used))
    with pytest.raises(OSError, match="quota"):
        store.admission(65536, "research")
    result = cont.process(
        tmp_path / "absent.sqlite",
        compact_path,
        [],
        9000,
        lambda amount: store.admission(amount, "research", maturity=True),
    )
    assert result["processed_this_pass"] == 1
    assert (
        cont.db.execute("SELECT json_extract(body,'$.status') FROM continued_outcomes").fetchone()[
            0
        ]
        == "unavailable"
    )
    assert (
        sum(p.stat().st_size for p in store.research.iterdir() if p.is_file())
        <= plan.research_bytes
    )
    assert (
        store.snapshot()["maturity_headroom_bytes"] == plan.scratch_bytes - 2 * plan.segment_bytes
    )
    cont.close()
    store.close()


def test_interrupted_segment_ack_recovery_and_consistent_rollups(tmp_path):
    store = ResearchStorage(plan_at(tmp_path))
    now = 1_800_000_000
    value = packet(now, "summary", markets={"BTCUSD": {"mid": 100}}, gaps={})
    refs = store.append([value], now)
    store.db.execute("DELETE FROM storage_records")  # Simulate index acknowledgment loss.
    store.db.execute("UPDATE storage_state SET rows=0,rows_through=0,last_capture=NULL")
    store.db.execute("UPDATE storage_segments SET rows=0,bytes=0")
    store.db.commit()
    store.close()
    store = ResearchStorage(plan_at(tmp_path))
    assert store.snapshot()["rows"] == 1
    assert store.append([value], now) == refs
    assert store.db.execute("SELECT count(*) FROM storage_rollups").fetchone()[0] == 3
    store.close()


def test_coherent_longer_horizons_causal_features():
    from decimal import Decimal as D

    from test_autonomous_lab import bars_at

    from trading.paper_strategy import Bar

    start = 1_800_000_000 // 900 * 900
    for horizon in ("medium", "long"):
        spec = RuleSpec(holding_horizon=horizon)
        assert spec.exit_seconds == spec.timing["outcome"]
        assert spec.progress_seconds > 600
        assert spec.timing["review"] > spec.exit_seconds
        with pytest.raises(ValueError):
            RuleSpec(holding_horizon=horizon, progress_seconds=600)
        assert not rule_feature(bars_at(start), start + 1, spec, "paper-rest-ioc-v1")["eligible"]
        bars = [
            Bar(
                (start - 6000 * 60 + i * 60) * 1000,
                D(100),
                D(102),
                D(99),
                D(100) + D(i) / 10000,
                D(10),
                (start - 6000 * 60 + (i + 1) * 60) * 1000 - 1,
            )
            for i in range(6000)
        ]
        feature = rule_feature(bars, start + 1, spec, "paper-rest-ioc-v1")
        assert "atr" in feature
        assert feature["timing"] == spec.timing
        assert not rule_feature(bars[:-25] + bars[-24:], start + 1, spec, "paper-rest-ioc-v1")[
            "eligible"
        ]


def test_long_trial_matures_only_after_its_declared_week(pg_store, tmp_path):
    from test_autonomous_lab import make_lab, tick_lab
    from test_paper_engine import START

    from trading import autonomous_finance as finance
    from trading.autonomous_spec import LabProposal

    store, _ = pg_store
    lab = make_lab(store, tmp_path, holding_horizons=("short", "long"))
    spec = RuleSpec(holding_horizon="long", family="range_reversion")
    proposal = LabProposal(
        request_id="long-window-test",
        policy_id="continuous-test-policy",
        kind="independent",
        strategy=spec,
        reference=RuleSpec(holding_horizon="long"),
        mechanism="Frozen multi-day range versus breakout",
        question=("Does the subsequent week resolve a distinct long-term hypothesis?"),
        evidence_bundle_sha256=lab.bundle(START)["sha256"],
    )
    receipt = {}
    lab.paper.state = store.transact(
        START + 1, lambda e: receipt.update(finance.reserve(e, proposal))
    )
    trial_id = receipt["trial_id"]
    lab.paper.state = store.transact(START + 2, lambda e: finance.fund(e, trial_id))
    trial = lab.paper.state["autonomous_lab"]["trials"][trial_id]
    assert trial["review_at"] - trial["started_at"] == 7 * 86400
    tick_lab(lab, START + 3600, coverage=True)
    with pytest.raises(ValueError, match="fixed subsequent"):
        store.transact(START + 3601, lambda e: finance.review(e, trial_id))
    tick_lab(lab, START + 3 * 86400, coverage=True)
    assert "sealed" not in lab.paper.state["autonomous_lab"]["trials"][trial_id]
    assert lab.paper.state["accounts"][trial["candidate"]]["risk_peak"] == "100"


def test_long_only_policy_does_not_propose_an_undeclared_short_seed(pg_store, tmp_path):
    from test_autonomous_lab import make_lab
    from test_paper_engine import START

    store, _ = pg_store
    lab = make_lab(store, tmp_path, holding_horizons=("long",))
    proposal = lab.propose(START)
    assert proposal.strategy.holding_horizon == "long"
    assert proposal.reference.holding_horizon == "long"
    with pytest.raises(ValueError, match="contiguous causal"):
        lab.submit(proposal, START)
