"""Real disposable archive/daily/Lab owners; no financial DB, venue, or model calls."""

import asyncio
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, RLock

import pytest
from pydantic import ValidationError
from test_autonomous_lab import bars_at
from test_daily_pattern_analyzer import advance, enable, finish
from test_paper_engine import frame
from test_pattern_scanner import Fixture, row

from trading.autonomous_lab import AutonomousLab
from trading.autonomous_spec import LabPolicy, LabProposal
from trading.evidence_runtime import EvidenceRecorder
from trading.pattern_comparisons import (
    PatternComparisonCommand,
    PatternComparisons,
    PatternFindingSelection,
)
from trading.research_evidence import digest
from trading.research_storage import reopen_evidence, save_plan


def build_fixture(
    tmp_path, monkeypatch, kind="resistance_breakout", prior_volume="10", event_volume="20"
):
    """Shared real source fixture for API tests; declares 32 native slots, not a year."""
    f = Fixture(tmp_path, monkeypatch)
    f.frames = {"5m"}
    enable(f)
    finish(f)  # Genuine first pending daily enrollment through the scanner owner.
    step = 300000
    cutoff = int(f.now * 1000) // step * step

    def native(at, interval):
        value = row(at, interval, volume=prior_volume)
        if at == cutoff - (8 if kind == "breakout_retest" else 5) * step:
            value[2] = "103"
        if kind == "breakout_retest":
            if at == cutoff - 4 * step:
                value[2:6] = ["105", "99", "104", event_volume]
            elif at == cutoff - 3 * step:
                value[1:6] = ["104", "106", "104", "105", prior_volume]
            elif at >= cutoff - 2 * step:
                value[1:6] = ["103.5", "105", "103.1", "104", event_volume]
        elif at >= cutoff - 2 * step:
            value[2:6] = ["105", "99", "104", event_volume]
        return value

    f.generator = native
    for saved in f.registry.db.execute("SELECT body FROM pattern_progress").fetchall():
        state = json.loads(saved[0])
        if state["timeframe"] == "5m":
            state.update(
                requested_start_ms=cutoff - 32 * step,
                cursor_ms=cutoff - 32 * step,
                expected_bars=32,
            )
        else:
            state["retry_at"] = f.now + 86400
        f.scanner._save(f.campaign, state)

    async def process():
        for _ in range(32):
            await f.scanner.step()
            if f.state("5m")["status"] == "monitoring":
                return
        raise AssertionError("Declared 32-native-bar fixture did not complete")

    asyncio.run(process())
    advance(f, 86400 - f.now % 86400 + 1)
    snapshot = finish(f)
    pick = snapshot["picks"][0]
    assert pick["basis"] == "recognized_setup"
    event = next(e for e in pick["evidence"] if e["body"]["kind"] == kind)
    selection = PatternFindingSelection(
        daily_id=snapshot["id"],
        symbol="BTCUSD",
        timeframe="5m",
        event_kind=event["kind"],
        event_seq=event["seq"],
    )
    f.paper.state["autonomous_lab"] = {
        "policy": LabPolicy(
            request_id="comparison-fixture-policy", holding_horizons=("medium",)
        ).model_dump(),
        "trials": {},
        "proposals_paused": False,
    }
    f.paper.state["paused"] = False
    f.paper.history = {"BTCUSD": bars_at(f.now - 400 * 60)[-200:] + bars_at(f.now)}
    f.paper.control_frames = lambda: {"BTCUSD": frame(f.now)}
    f.paper.memory_book = lambda symbol: None
    controller = AutonomousLab(f.registry, f.paper, lambda: True)
    bridge = PatternComparisons(f.scanner, controller)
    f.original = copy.deepcopy(f.paper.state)
    return f, bridge, selection


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    f, bridge, selection = build_fixture(tmp_path, monkeypatch)
    try:
        yield f, bridge, selection
    finally:
        f.close()


def command(bridge, selection, request="pattern-comparison-0001"):
    return PatternComparisonCommand(
        **selection.model_dump(),
        request_id=request,
        expected_finding_sha256=bridge.describe(selection)["finding_sha256"],
    )


def test_retained_btc_candidate_survives_newer_eth_only_shortlist_with_age_bound(fixture):
    f, bridge, selection = fixture
    original = bridge.candidate(f.now)
    assert original is not None
    day = copy.deepcopy(f.scanner.daily_snapshot(selection.daily_id))
    day.update(id="daily-" + "e" * 24, generated_at=f.now + 86400)
    day["picks"] = [dict(day["picks"][0], symbol="ETHUSD")]
    with f.registry.transaction():
        f.registry.db.execute(
            "INSERT INTO pattern_daily_days(id,campaign,day,body) VALUES(?,?,?,?)",
            (day["id"], day["campaign_id"], int((f.now + 86400) // 86400), json.dumps(day)),
        )
    candidates = bridge.candidates(f.now + 86400)
    assert original in candidates and all(item.symbol == "BTCUSD" for item in candidates)
    assert bridge.candidates(f.now + 7 * 86400) == []
    assert len(candidates) <= 32


def test_real_native_daily_preparation_and_separate_existing_lab_submission(fixture):
    f, bridge, selection = fixture
    described = bridge.describe(selection)
    original = described["finding"]
    assert original["native_proof"]["recognition_rows"] == 21
    assert original["native_proof"]["archive_verified"] is True
    assert original["coverage"][0]["observed_bars"] == 32
    assert len(f.calls) == 1 and f.calls[0]["interval"] == "5m"
    receipt = bridge.prepare(command(bridge, selection), f.now)
    assert receipt["status"] == "supported", receipt["evaluation"]
    assert receipt["submitted"] is False and receipt["financial_authority"] is False
    assert f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 0
    proof = receipt["evaluation"]["matched_inputs"]
    rows = []
    for ref in proof["references"]:
        packet = reopen_evidence(f.plan, ref)
        assert len(packet["rows"]) <= 500
        rows.extend(packet["rows"])
    assert len(rows) == 600 and digest(rows) == proof["sha256"]
    assert len(proof["references"]) == 2
    controls = receipt["evaluation"]["controls"]["candidate"]
    assert controls["inapplicable_compatibility_fields"] == {"lookback": 10, "volume_multiple": "2"}
    assert "lookback" not in controls["unchanged"]
    for label in ("candidate", "reference"):
        control_proposal = receipt["evaluation"]["controls"][label]["proposal"]
        assert LabProposal.model_validate(control_proposal)
        assert control_proposal["evidence_bundle_sha256"] == receipt["issued_bundle_sha256"]
    saved_bundle = json.loads(
        f.registry.db.execute(
            "SELECT body FROM lab_bundles WHERE sha256=?", (receipt["issued_bundle_sha256"],)
        ).fetchone()[0]
    )
    assert "proposal" not in saved_bundle
    assert "evidence_bundle_sha256" not in saved_bundle["proposal_without_bundle_digest"]
    assert "0" * 64 not in json.dumps(saved_bundle)
    assert set(receipt["mapping"]["source_sha256"]) == {
        "redesign_strategy.py",
        "autonomous_spec.py",
        "rule_components.py",
    }
    assert f.paper.state == f.original
    # Explicit QA-only submit is separate; the existing gate/owner executes it.
    proposal = LabProposal.model_validate(receipt["proposal"])
    submitted = bridge.controller.submit(proposal, f.now)
    assert submitted["status"] == "evaluated"
    assert submitted["body"]["strategy"]["family"] == "breakout-retest-v1"
    assert submitted["body"]["reference"]["family"] == "cost-breakout-v1"
    assert submitted["evaluation"]["inputs"] == rows
    assert f.paper.state == f.original
    assert bridge.controller.submit(proposal, f.now) == submitted
    assert f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 1


def test_restart_lost_ack_returns_original_before_mutable_sources(fixture, monkeypatch):
    f, bridge, selection = fixture
    intent = command(bridge, selection)
    receipt = bridge.prepare(intent, f.now)
    reopened = PatternComparisons(f.scanner, None)
    monkeypatch.setattr(reopened, "describe", lambda *a: pytest.fail("Recovery read new sources"))
    f.paper.history.clear()
    f.paper.running = False
    f.scanner.plan = None
    assert reopened.get(intent.request_id) == receipt
    assert reopened.prepare(intent, f.now + 2000) == receipt
    with pytest.raises(ValueError, match="cannot be rewritten"):
        reopened.prepare(intent.model_copy(update={"event_seq": intent.event_seq + 1}), f.now)


def test_original_wait_is_immutable_when_policy_or_input_becomes_ready(fixture):
    f, bridge, selection = fixture
    bridge.controller = None
    intent = command(bridge, selection)
    wait = bridge.prepare(intent, f.now)
    assert wait["status"] == "waiting" and wait["proposal"] is None
    bridge.controller = AutonomousLab(f.registry, f.paper, lambda: True)
    assert bridge.prepare(intent, f.now + 1) == wait
    later = bridge.prepare(command(bridge, selection, "pattern-comparison-0002"), f.now)
    assert later["status"] == "supported"
    assert f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 0


def test_concurrent_identical_preparation_one_immutable_bundle(fixture):
    f, bridge, selection = fixture
    intent = command(bridge, selection)
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: bridge.prepare(intent, f.now), range(4)))
    assert all(r == receipts[0] for r in receipts)
    assert (
        f.registry.db.execute("SELECT count(*) FROM pattern_comparison_requests").fetchone()[0] == 1
    )
    assert f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        f.registry.db.execute("UPDATE pattern_comparison_requests SET intent_sha256='bad'")
    assert f.paper.state == f.original


@pytest.mark.parametrize("missing", ["history", "gap", "eligibility", "protection", "policy"])
def test_current_unavailable_is_retained_wait_not_ready(fixture, missing):
    f, bridge, selection = fixture
    intent = command(bridge, selection)
    if missing == "history":
        f.paper.history["BTCUSD"] = f.paper.history["BTCUSD"][-20:]
    elif missing == "gap":
        del f.paper.history["BTCUSD"][-50]
    elif missing == "eligibility":
        f.paper.universe.scanned_at -= 121
    elif missing == "protection":
        f.paper.constrained = lambda: True
    else:
        f.paper.state.pop("autonomous_lab")
    receipt = bridge.prepare(intent, f.now)
    assert receipt["status"] == "waiting"
    assert receipt["evaluation"]["reason"]
    assert f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 0


def test_changed_finding_digest_refused_without_preparation(fixture):
    f, bridge, selection = fixture
    intent = command(bridge, selection).model_copy(update={"expected_finding_sha256": "0" * 64})
    with pytest.raises(ValueError, match="identity differs"):
        bridge.prepare(intent, f.now)
    assert (
        f.registry.db.execute("SELECT count(*) FROM pattern_comparison_requests").fetchone()[0] == 0
    )


@pytest.mark.parametrize("which", ["foreign_seq", "native_hash", "pivot_hash", "missing_ref"])
def test_altered_or_missing_original_source_refused(fixture, monkeypatch, which):
    f, bridge, selection = fixture
    if which == "foreign_seq":
        selection = selection.model_copy(update={"event_seq": selection.event_seq + 999})
    else:
        original = bridge._original(selection)
        if which == "native_hash":
            original["original_event"]["input_window_sha256"] = "0" * 64
        elif which == "pivot_hash":
            original["original_level"]["input_window_sha256"] = "0" * 64
        else:
            original["original_event"]["source_references"] = ["capture-v2:999:999:" + "0" * 64]
        monkeypatch.setattr(bridge, "_original", lambda _: original)
    with pytest.raises((ValueError, LookupError, FileNotFoundError)):
        bridge.describe(selection)


@pytest.mark.parametrize("holdout", ["evidence", "prospective"])
def test_protected_input_overlap_refuses_without_publication(fixture, holdout):
    f, bridge, selection = fixture
    intent = command(bridge, selection)
    start = f.paper.history["BTCUSD"][0].open_ms / 1000
    end = f.now
    if holdout == "evidence":
        f.registry.db.execute(
            "INSERT INTO evidence_windows VALUES('sealed',?,?, 'sealed holdout')", (start, end)
        )
    else:
        f.registry.db.execute("CREATE TABLE prospective_plans(start REAL,end REAL)")
        f.registry.db.execute("INSERT INTO prospective_plans VALUES(?,?)", (start, end))
    with pytest.raises(ValueError, match="Protected"):
        bridge.prepare(intent, f.now)
    assert (
        f.registry.db.execute("SELECT count(*) FROM pattern_comparison_requests").fetchone()[0] == 0
    )
    assert f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0] == 0


def test_current_chart_progress_drift_does_not_change_original_finding(fixture):
    f, bridge, selection = fixture
    described = bridge.describe(selection)
    state = f.state("5m")
    state["cursor_ms"] += 300000
    state["source_sha256"] = "a" * 64
    f.scanner._save(f.campaign, state)
    assert bridge.describe(selection) == described


def test_unsupported_native_timeframe_and_symbol_are_not_remapped(fixture):
    f, bridge, selection = fixture
    with pytest.raises(ValueError):
        bridge.describe(selection.model_copy(update={"timeframe": "4h"}))
    with pytest.raises(ValueError):
        bridge.describe(selection.model_copy(update={"symbol": "ETHUSD"}))
    with pytest.raises(ValidationError):
        PatternComparisonCommand(
            **selection.model_dump(), request_id="short", expected_finding_sha256="0" * 64
        )
    with pytest.raises(ValidationError):
        PatternFindingSelection(**{**selection.model_dump(), "event_seq": 9223372036854775808})
    with pytest.raises(ValueError):
        bridge.get("bad/request_id")
    assert f.paper.state == f.original


def test_missing_issued_bundle_is_unavailable_not_new_work(fixture, monkeypatch):
    f, bridge, selection = fixture
    intent = command(bridge, selection)
    receipt = bridge.prepare(intent, f.now)
    # Deliberate corruption only in disposable QA; original index remains present.
    f.registry.db.execute("DROP TRIGGER lab_bundle_retained")
    f.registry.db.execute(
        "DELETE FROM lab_bundles WHERE sha256=?", (receipt["issued_bundle_sha256"],)
    )
    monkeypatch.setattr(
        bridge, "describe", lambda *a: pytest.fail("Missing issued bundle was replaced")
    )
    with pytest.raises(OSError, match="unavailable"):
        bridge.get(intent.request_id)
    with pytest.raises(OSError, match="unavailable"):
        bridge.prepare(intent, f.now)


def test_actual_native_retest_mapping_is_supported(tmp_path, monkeypatch):
    f, bridge, selection = build_fixture(tmp_path, monkeypatch, "breakout_retest")
    try:
        receipt = bridge.prepare(command(bridge, selection), f.now)
        assert receipt["finding"]["original_event"]["kind"] == "breakout_retest"
        assert receipt["status"] == "supported"
        assert f.paper.state == f.original
    finally:
        f.close()


def test_used_rule_gate_is_retained_wait_with_existing_inbox(fixture):
    f, bridge, selection = fixture
    first = bridge.prepare(command(bridge, selection), f.now)
    bridge.controller.submit(LabProposal.model_validate(first["proposal"]), f.now)
    second = bridge.prepare(command(bridge, selection, "pattern-comparison-0002"), f.now)
    assert second["status"] == "waiting"
    assert "used-rule" in second["reason"]
    assert f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 1


def test_fractional_native_ratio_reproduces_exact_scanner_decimal_context(tmp_path, monkeypatch):
    f, bridge, selection = build_fixture(tmp_path, monkeypatch, prior_volume="3", event_volume="10")
    try:
        receipt = bridge.prepare(command(bridge, selection), f.now)
        assert receipt["finding"]["original_event"]["volume_ratio"] == (
            "3.3333333333333333333333333333333333333"
        )
        assert receipt["status"] == "supported"
    finally:
        f.close()


def test_held_real_recorder_borrow_does_not_hold_registry_or_async_scanner(fixture, tmp_path):
    f, bridge, selection = fixture
    intent = command(bridge, selection)
    f.scanner.control(
        {
            "action": "daily_pause",
            "campaign_id": f.campaign,
            "request_id": "comparison-fixture-pause",
        },
        f.now,
    )
    # Attach the existing initialized disposable store to the real borrow method;
    # no second recovery constructor or recorder process is started.
    save_plan(tmp_path, f.plan)
    recorder = EvidenceRecorder.__new__(EvidenceRecorder)
    recorder.path = tmp_path / "evidence.sqlite3"
    recorder._storage_lock = RLock()
    recorder._closed = False
    recorder._storage = f.storage
    held, release, attempting = Event(), Event(), Event()

    def hold():
        with recorder.research_store(f.plan):
            held.set()
            assert release.wait(3), "Finite recorder holder release did not arrive"

    @contextmanager
    def borrow(plan):
        attempting.set()
        with recorder.research_store(plan) as store:
            yield store

    f.scanner.storage_owner = borrow

    async def responsive():
        assert await asyncio.to_thread(attempting.wait, 2)
        with f.registry.lock:
            assert f.scanner.snapshot()["enabled"] is False
        assert await asyncio.wait_for(f.scanner.step(), 1) is False
        ticks = 0
        for _ in range(3):
            await asyncio.sleep(0)
            ticks += 1
        assert ticks == 3 and not release.is_set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(hold)
        assert held.wait(2)
        preparation = pool.submit(bridge.prepare, intent, f.now)
        try:
            asyncio.run(responsive())
            assert not preparation.done()
        finally:
            release.set()
            holder.result(timeout=3)
            receipt = preparation.result(timeout=3)
    assert receipt["status"] == "supported" and f.paper.state == f.original


def test_holdout_wins_during_archive_borrow_no_bundle_publication(fixture):
    f, bridge, selection = fixture
    intent = command(bridge, selection)
    original_owner = f.scanner.storage_owner

    @contextmanager
    def raced(plan):
        with original_owner(plan) as store:
            f.registry.db.execute(
                "INSERT INTO evidence_windows VALUES('race',?,?, 'sealed holdout')",
                (f.paper.history["BTCUSD"][0].open_ms / 1000, f.now),
            )
            yield store

    f.scanner.storage_owner = raced
    with pytest.raises(ValueError, match="Protected"):
        bridge.prepare(intent, f.now)
    assert f.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0] == 0
    assert (
        f.registry.db.execute("SELECT count(*) FROM pattern_comparison_requests").fetchone()[0] == 0
    )


def test_preparation_never_writes_original_model_attempt_or_allowance(fixture):
    f, bridge, selection = fixture
    f.registry.db.execute("CREATE TABLE role_attempts(id TEXT,status TEXT,answer TEXT)")
    f.registry.db.execute("CREATE TABLE role_attempt_allowances(id TEXT,charged INTEGER)")
    f.registry.db.execute("INSERT INTO role_attempts VALUES('consumed','answered','unsupported')")
    f.registry.db.execute("INSERT INTO role_attempt_allowances VALUES('consumed',1)")
    before = [tuple(r) for r in f.registry.db.execute("SELECT * FROM role_attempts")]
    receipt = bridge.prepare(command(bridge, selection), f.now)
    assert receipt["submitted"] is False
    assert [tuple(r) for r in f.registry.db.execute("SELECT * FROM role_attempts")] == before
    assert tuple(f.registry.db.execute("SELECT * FROM role_attempt_allowances").fetchone()) == (
        "consumed",
        1,
    )
    assert f.paper.state == f.original


def test_restart_saved_list_recovers_original_wait_and_supported_without_local_hint(fixture):
    f, bridge, selection = fixture
    current = bridge.controller
    bridge.controller = None
    original_wait = bridge.prepare(command(bridge, selection, "pattern-comparison-0001"), f.now)
    bridge.controller = current
    supported = bridge.prepare(command(bridge, selection, "pattern-comparison-0002"), f.now)
    reopened = PatternComparisons(f.scanner, None)
    page = reopened.page()
    assert [item["request_id"] for item in page["items"]] == [
        supported["request_id"],
        original_wait["request_id"],
    ]
    assert [item["status"] for item in page["items"]] == ["supported", "waiting"]
    assert page["next_before"] is None and "not preparation chronology" in page["order"]
    assert reopened.get(page["items"][1]["request_id"]) == original_wait
    assert reopened.get(page["items"][0]["request_id"]) == supported


def test_saved_page_one_select_bounded_cursor_and_no_silent_missing_bundle(fixture):
    f, bridge, selection = fixture
    bridge.controller = None
    for index in range(22):
        bridge.prepare(command(bridge, selection, f"pattern-comparison-{index:04}"), f.now)
    statements = []
    f.registry.db.set_trace_callback(statements.append)
    page = bridge.page()
    f.registry.db.set_trace_callback(None)
    assert len(page["items"]) == 20 and page["next_before"] == "pattern-comparison-0002"
    assert len(statements) == 1 and "LIMIT 21" in statements[0]
    rest = bridge.page(page["next_before"])
    assert len(rest["items"]) == 2 and rest["next_before"] is None
    assert len({r["request_id"] for r in page["items"] + rest["items"]}) == 22
    f.registry.db.execute("DROP TRIGGER lab_bundle_retained")
    f.registry.db.execute(
        "DELETE FROM lab_bundles WHERE sha256=?", (page["items"][0]["issued_bundle_sha256"],)
    )
    with pytest.raises(OSError, match="unavailable"):
        bridge.page()
    with pytest.raises(ValueError):
        bridge.page("invalid/cursor")


def test_bounded_preparation_capacity_refuses_without_dispatch(fixture, monkeypatch):
    from trading import pattern_comparisons

    f, bridge, selection = fixture
    bridge.controller = None
    monkeypatch.setattr(pattern_comparisons, "MAX_REQUESTS", 1)
    first = bridge.prepare(command(bridge, selection, "pattern-comparison-0001"), f.now)
    with pytest.raises(ValueError, match="capacity reached"):
        bridge.prepare(command(bridge, selection, "pattern-comparison-0002"), f.now)
    assert bridge.get(first["request_id"]) == first
    assert f.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 0
