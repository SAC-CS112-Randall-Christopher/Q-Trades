"""Native saved findings through actual role owners; stub answers are not model evidence."""

import asyncio
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from test_autonomous_lab import bars_at, close_window, make_lab, tick_lab
from test_daily_pattern_analyzer import advance, finish
from test_experiment_registry import plan
from test_paper_pilot_worker import PilotFixture
from test_paper_pilot_worker import question as legacy_question
from test_paper_pilot_worker import workspace as workspace
from test_paper_store import pg_store as pg_store
from test_pattern_comparisons import build_fixture
from test_pattern_scanner import row
from test_role_question_selection import abstention, causal_frame

from trading.autonomous_lab import AutonomousLab, InputWait
from trading.autonomous_spec import LabProposal
from trading.experiment_registry import fingerprint
from trading.lab_role_contract import (
    CAPABILITY_VERSION,
    PATTERN_VERSION,
    TOOL_REQUEST_VERSION,
    VERSION,
    contract_hash,
    packet_json,
    validate,
)
from trading.local_role_model import LocalRoles
from trading.paper_economics import sample
from trading.paper_engine import account
from trading.pattern_comparisons import PatternComparisons
from trading.research_storage import reopen_evidence, save_plan
from trading.role_evidence import outcome_summary, pattern_followup_outcome
from trading.role_worker import PATTERN_QUESTION_POLICY, RoleWorker


class PatternTransport(PilotFixture):
    role_contract = PATTERN_VERSION

    def __init__(self, action="no_change"):
        super().__init__(tokens=65536)
        self.action = action
        self.authority = {
            "question_policy": PATTERN_QUESTION_POLICY,
            "grant_id": self.grant_id,
            "grant_sha": "a" * 64,
            "profile_sha": "b" * 64,
            "contract_version": PATTERN_VERSION,
            "contract_sha": contract_hash(PATTERN_VERSION),
        }

    def selection_authority(self):
        return copy.deepcopy(self.authority)

    def admit(self, role):
        return super().admit(role) | {
            "role_contract": PATTERN_VERSION,
            "contract_sha256": contract_hash(PATTERN_VERSION),
        }

    def preflight(self, role, packet, profile):
        assert packet["contract"] == profile["role_contract"] == PATTERN_VERSION
        assert packet["selection_authority"] == self.authority
        return LocalRoles.preflight(
            role,
            packet,
            profile
            | {
                "options": {"num_ctx": 9000, "num_predict": 1024},
            },
        )

    def infer(self, role, packet, profile):
        self.calls.append((role, copy.deepcopy(packet)))
        if role == "reviewer":
            answer = {
                "action": "exploratory_paper_only",
                "evidence_ids": ["e1", "e3"],
                "issues": [],
                "rationale": "Matched current inputs support exploration, not a proven edge.",
            }
        else:
            answer = abstention(self.action if len(self.calls) == 1 else "no_change")
            answer["evidence_ids"] = ["e2", "e3"] if "e2" in packet["evidence"] else ["e1", "e3"]
            if answer["action"] == "propose_experiment":
                answer["capability"] = "p0"
            elif answer["action"] == "request_data":
                answer["dependency"] = "new_closed_bars"
            elif answer["action"] == "unsupported_capability":
                answer["unsupported_basis"] = {
                    "kind": "analysis_tool",
                    "identifier": "matched_regime_comparison",
                }
        return {
            "complete": True,
            "answer": answer,
            "scope": "Disposable deterministic callback; zero actual model calls",
        }


def build_pattern_worker_fixture(tmp_path, monkeypatch, answer_action="no_change"):
    """Real native32-slot scanner/day/preparation, not full-year/operating acceptance."""
    f, bridge, selection = build_fixture(tmp_path, monkeypatch)
    save_plan(tmp_path, f.plan)
    f.paper.ready_at = f.now - 60
    f.paper._candle_errors = {}
    f.paper.state["last_tick"] = f.now
    f.paper.control_frames = lambda: {"BTCUSD": causal_frame(f.now, f.paper.history["BTCUSD"])}
    worker = RoleWorker(
        f.registry,
        bridge.controller,
        PatternTransport(answer_action),
        f.scanner.storage_owner,
        pattern_comparisons=bridge,
    )
    worker.enabled = True
    worker.paper_admission = lambda: True
    return f, worker, selection


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    f, worker, selection = build_pattern_worker_fixture(tmp_path, monkeypatch)
    try:
        yield f, worker, selection
    finally:
        f.close()


def task(worker):
    rows = worker.registry.db.execute("SELECT id FROM role_tasks").fetchall()
    assert len(rows) == 1
    return worker.get(rows[0]["id"])


def rows(worker, table):
    return [tuple(r) for r in worker.registry.db.execute("SELECT * FROM " + table).fetchall()]


def select(f, worker):
    assert worker.select_fresh_question(f.now) == 1, worker.question_selection_status()
    return task(worker)


def test_native_finding_selects_exact_fixed_current_comparison_without_dispatch(fixture):
    f, worker, selection = fixture
    before = copy.deepcopy(f.paper.state)
    saved = select(f, worker)
    context = saved["context"]
    motivation = context["pattern_comparison"]
    assert motivation["selection"] == selection.model_dump()
    assert motivation["native_proof"]["recognition_rows"] == 21
    assert motivation["native_proof"]["archive_verified"] is True
    assert len(motivation["coverage"]) == 5
    assert context["question_selection"]["method"] == "p0"
    assert context["contract"] == PATTERN_VERSION and set(context["catalog"]) == {"p0"}
    controls = context["fixed_comparison"]["p0"]
    assert controls["candidate"]["proposal"]["strategy"]["family"] == "breakout-retest-v1"
    assert controls["reference"]["proposal"]["strategy"]["family"] == "cost-breakout-v1"
    assert controls["candidate"]["inapplicable_compatibility_fields"] == {
        "lookback": 10,
        "volume_multiple": "2",
    }
    assert controls["current_inputs"]["count"] == 600
    assert context["tool_evidence"]["closed_bar_sha256"] == controls["current_inputs"]["sha256"]
    original = worker.pattern_comparisons.get(motivation["preparation_request_id"])
    assert original["issued_bundle_sha256"] == context["issued"]["sha256"]
    assert worker.pattern_comparisons.execution_inputs(
        original["evaluation"]["matched_inputs"], original["request_id"]
    )
    _, packet = worker._packet(saved)
    assert packet["tool_inventory"]["strategy_family"] == [
        "breakout-retest-v1",
        "cost-breakout-v1",
    ]
    assert "references" not in packet_json(packet)
    assert f.plan.root not in packet_json(packet)
    assert worker.transport.calls == [] and not rows(worker, "role_attempts")
    assert not rows(worker, "lab_proposals")
    assert f.paper.state == before


def test_actual_v8_packet_fits_unchanged_9000_conservative_context_guard(fixture):
    f, worker, _ = fixture
    saved = select(f, worker)
    role, packet = worker._packet(saved)
    profile = {
        "role_contract": PATTERN_VERSION,
        "contract_sha256": contract_hash(PATTERN_VERSION),
        "options": {"num_ctx": 9000, "num_predict": 1024},
    }
    measured = LocalRoles.preflight(role, packet, profile)
    assert measured["reserved_total"] <= 9000


def restore_scored_body(projected):
    body = copy.deepcopy(projected["body"])
    if "execution_samples" in body:
        samples = body.pop("execution_samples")
        body["candidate_sample"] = samples["common"] | samples["candidate"]
        body["reference_sample"] = samples["common"] | samples["reference"]
    return body


def test_v8_followup_preserves_execution_unknowns_and_exact_method_without_context_mutation(
    fixture,
):
    f, worker, _ = fixture
    worker.transport.action = "propose_experiment"
    selected = select(f, worker)
    assert asyncio.run(worker.step(f.now))
    saved = worker.get(selected["id"])
    # Actual native selection/idea callback supplies the frozen proposal. The
    # following scored body is explicitly a projection fixture, not a trial.
    candidate = account("projection-candidate", f.now)
    reference = account("projection-reference", f.now)
    candidate["fees"], reference["fees"] = "0.12", "0.08"
    reference["valuation_issues"] = {"BTCUSD": "Synthetic missing executable mark"}
    body = {
        "trial_id": "projection-only-trial",
        "proposal_id": saved["proposal"]["request_id"],
        "outcome": "data_blocked",
        "reason": "Incomplete coverage is not economic failure",
        "available_at": f.now + 86400,
        "window_start": f.now,
        "window_end": f.now + 86400,
        "coverage_seconds": 2.0,
        "net_after_operating_usd": {"candidate": None, "reference": None},
        "delta_usd": None,
        "passive_usd": None,
        "cash_usd": None,
        "operating_each_usd": "0.5",
        "candidate_sample": sample(candidate, f.now),
        "reference_sample": sample(reference, f.now),
        "dependence": "Related trials are correlated",
        "qualification": "Exploration only; no promotion",
        "fees_treatment": "Executable equity embeds fees once",
        "additional_unknown": None,
    }
    saved["stage"] = "followup"
    saved["result"] = {"outcome": {"id": 1, "at": body["available_at"], "body": body}}
    original = copy.deepcopy(saved)
    attempts, state = rows(worker, "role_attempts"), copy.deepcopy(f.paper.state)
    role, packet = worker._packet(saved)
    projected = packet["evidence"]["e1"]
    assert packet_json(restore_scored_body(projected)) == packet_json(body)
    assert projected["source_sha256"] == fingerprint(saved["result"]["outcome"])
    controls = packet["fixed_comparison"]["p0"]
    assert controls["candidate"] == "breakout-retest-v1"
    assert controls["reference"] == "cost-breakout-v1"
    assert controls["method_sha256"] == fingerprint(saved["proposal"])
    assert controls["detail_sha256"] == fingerprint(saved["context"]["fixed_comparison"]["p0"])
    assert (
        worker.transport.preflight(role, packet, worker.transport.admit(role))["reserved_total"]
        <= 9000
    )
    answer = abstention()
    answer["evidence_ids"] = ["e1", "e3"]
    assert validate(role, answer, packet, PATTERN_VERSION)
    assert saved == original and worker.get(saved["id"])["context"] == original["context"]
    assert rows(worker, "role_attempts") == attempts and f.paper.state == state
    assert not rows(worker, "lab_proposals") and len(worker.transport.calls) == 1


@pytest.mark.parametrize("missing", ["candidate", "reference", "both", "reserved_key"])
def test_v8_followup_keeps_missing_samples_and_existing_scored_fields_literal(missing):
    body = {"outcome": "data_blocked", "dependence": None, "unknown": None}
    if missing != "candidate" and missing != "both":
        body["candidate_sample"] = {"fresh": False, "net_pnl": None}
    if missing != "reference" and missing != "both":
        body["reference_sample"] = None
    if missing == "reserved_key":
        body["reference_sample"] = {"fresh": False, "net_pnl": None}
        body["execution_samples"] = {"original_recorded_field": None}
    original = {"id": 2, "at": 1800000000.0, "body": body}
    saved = copy.deepcopy(original)
    projected = pattern_followup_outcome(original)
    assert projected["body"] == body and original == saved
    assert projected["source_sha256"] == fingerprint(original)


def test_v8_followup_sample_sharing_preserves_json_types_and_absent_fields():
    body = {
        "candidate_sample": {"fresh": False, "value": 1, "only_candidate": None},
        "reference_sample": {"fresh": False, "value": True},
        "outcome": "data_blocked",
    }
    projected = pattern_followup_outcome({"id": 3, "at": 1800000000.0, "body": body})
    assert packet_json(restore_scored_body(projected)) == packet_json(body)
    assert projected["body"]["execution_samples"]["common"] == {"fresh": False}


@pytest.mark.parametrize("version", [VERSION, TOOL_REQUEST_VERSION, CAPABILITY_VERSION])
def test_old_followup_packets_keep_original_outcome_projection(workspace, monkeypatch, version):
    worker, clock, _ = workspace
    worker.transport.role_contract = version
    original = worker.enqueue(legacy_question(), clock[0])
    saved = copy.deepcopy(original)
    saved["stage"] = "followup"
    outcome = {
        "id": 1,
        "at": clock[0],
        "body": {
            "outcome": "data_blocked",
            "candidate_sample": {"fresh": False, "net_pnl": None},
            "reference_sample": None,
            "dependence": "Related trials are correlated",
        },
    }
    saved["result"] = {"outcome": outcome}
    for name in ("pattern_followup_controls", "pattern_followup_outcome"):
        monkeypatch.setattr("trading.role_worker." + name, lambda *a: pytest.fail("v8-only hook"))
    _, packet = worker._packet(saved)
    assert packet["evidence"]["e1"] == outcome_summary(outcome)
    assert "execution_samples" not in packet["evidence"]["e1"]["body"]
    assert worker.get(original["id"]) == original and not rows(worker, "role_attempts")


def test_republished_same_event_identity_ignores_new_daily_snapshot_identity(fixture):
    f, worker, selection = fixture
    finding = worker.pattern_comparisons.describe(selection)["finding"]
    later = copy.deepcopy(finding)
    later["selection"]["daily_id"] = "daily-" + "f" * 24
    later["captured_at"] += 86400
    assert worker._pattern_event_identity(later) == worker._pattern_event_identity(finding)


def test_supported_preparation_recovery_precedes_new_daily_intent(fixture, monkeypatch):
    f, worker, _ = fixture
    advance(f, 86400 + 12 * 3600)
    publish_native_event(f)
    enqueue = worker.enqueue
    monkeypatch.setattr(
        worker,
        "enqueue",
        lambda *a, **k: (_ for _ in ()).throw(InputWait("Publication interrupted")),
    )
    assert worker.select_fresh_question(f.now) == 0
    original = rows(worker, "pattern_comparison_requests")
    assert len(original) == 1
    advance(f, 86400 - f.now % 86400 + 1)
    snapshot = finish(f)
    assert snapshot["picks"][0]["basis"] == "recognized_setup"
    f.paper.history["BTCUSD"] = bars_at(f.now - 400 * 60)[-200:] + bars_at(f.now)
    f.paper.state["last_tick"] = f.now
    monkeypatch.setattr(worker, "enqueue", enqueue)
    assert worker.select_fresh_question(f.now) == 1
    assert rows(worker, "pattern_comparison_requests") == original
    assert task(worker)["context"]["pattern_comparison"]["selection"]["daily_id"] != snapshot["id"]
    assert not rows(worker, "role_attempts")


def publish_native_event(f):
    """Real continuing native rows; the fixture schedules daily capture after ingestion."""
    cutoff = int(f.now * 1000) // 300000 * 300000

    def native(at, interval):
        if at < cutoff - 32 * 300000:
            return None  # The actual native response preserves this missing interval.
        value = row(at, interval, volume="10")
        if at == cutoff - 5 * 300000:
            value[2] = "103"
        elif at >= cutoff - 2 * 300000:
            value[2:6] = ["105", "99", "104", "20"]
        return value

    f.generator = native
    daily_work = f.scanner._daily_work
    f.scanner._daily_work = lambda now: False

    async def process():
        for _ in range(64):
            await f.scanner.step()
            if f.state("5m")["cursor_ms"] >= cutoff:
                return
        raise AssertionError("Declared native 32-slot fixture did not finish")

    try:
        asyncio.run(process())
    finally:
        f.scanner._daily_work = daily_work
    snapshot = finish(f)
    assert snapshot["picks"][0]["basis"] == "recognized_setup"
    f.paper.history["BTCUSD"] = bars_at(f.now - 400 * 60)[-200:] + bars_at(f.now)
    f.paper.state["last_tick"] = f.now
    return snapshot


@pytest.mark.parametrize("archive", [False, True])
def test_exact_data_wait_successor_no_change_allows_only_distinct_mature_native_event(
    fixture, monkeypatch, archive
):
    f, worker, _ = fixture
    worker.transport.action = "request_data"
    first = select(f, worker)
    assert asyncio.run(worker.step(f.now))
    waiting = worker.get(first["id"])
    assert waiting["stage"] == "data_wait" and waiting["result"]["action"] == "request_data"
    original_answer = copy.deepcopy(waiting["result"])
    advance(f, 120)
    f.paper.history["BTCUSD"] = bars_at(f.now - 400 * 60)[-200:] + bars_at(f.now)
    assert worker.resume_sources(f.now) == 1
    successor = next(r for r in worker.page()["tasks"] if r["id"] != first["id"])
    assert asyncio.run(worker.step(f.now))
    terminal = worker.get(successor["id"])
    assert terminal["status"] == "done" and terminal["result"]["action"] == "no_change"
    if archive:
        monkeypatch.setattr("trading.role_history.ROLLOVER_BYTES", 0)
        worker.history.rollover()
        stub = f.registry.db.execute(
            "SELECT context,archive_reference FROM role_tasks WHERE id=?", (terminal["id"],)
        ).fetchone()
        assert stub["archive_reference"]
        assert json.loads(stub["context"])["predecessor_task"] == first["id"]
        assert worker.get(terminal["id"])["result"] == terminal["result"]
    assert worker.get(first["id"])["result"] == original_answer
    assert worker.select_fresh_question(f.now) == 0
    spent = rows(worker, "role_attempts")
    advance(f, 86400 + 600)
    later = publish_native_event(f)
    assert later["picks"][0]["evidence"]
    assert worker.select_fresh_question(f.now) == 1
    assert rows(worker, "role_attempts") == spent
    assert len(rows(worker, "role_question_selections")) == 2
    assert worker.get(first["id"])["result"] == original_answer


def test_actual_disposable_engine_trial_outcome_and_followup_without_model(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    f, worker, _ = build_pattern_worker_fixture(
        tmp_path / "native", monkeypatch, "propose_experiment"
    )
    (tmp_path / "financial").mkdir()
    financial = make_lab(
        store, tmp_path / "financial", now=f.now, holding_horizons=("medium",), horizon_seconds=3600
    )
    financial.registry.close()
    paper = financial.paper
    paper.universe = f.paper.universe
    paper.history = copy.deepcopy(f.paper.history)
    paper.ready_at = f.now - 60
    paper._candle_errors = {}
    paper.memory_book = lambda symbol: None
    paper.constrained = lambda: False
    paper.control_frames = lambda: {"BTCUSD": causal_frame(f.now, paper.history["BTCUSD"])}
    f.paper = paper
    f.scanner.paper = paper
    controller = AutonomousLab(f.registry, paper, lambda: True)
    worker.controller = controller
    worker.pattern_comparisons = PatternComparisons(f.scanner, controller)
    original_controls = {
        key: {
            name: copy.deepcopy(account.get(name))
            for name in ("funding", "risk_policy", "rule_spec", "admitted_at")
        }
        for key, account in paper.state["accounts"].items()
    }
    try:
        saved = select(f, worker)
        for _ in range(5):
            assert asyncio.run(worker.step(f.now)), worker.get(saved["id"])
            f.now += 1
            paper.state["last_tick"] = f.now
        submitted = worker.get(saved["id"])
        assert submitted["stage"] == "outcome"
        assert len(rows(worker, "lab_proposals")) == 1
        # A configured archive has to publish an observed recording receipt;
        # preparation alone grants no trial admission. Exercise that refusal.
        tick_lab(controller, f.now)
        assert controller.step(f.now) is False
        blocked = paper.state["autonomous_lab"]
        assert blocked["phase"] == "capture_blocked"
        assert not blocked["trials"]
        f.now = max(f.now + 2, blocked["next_action_at"])
        for _ in range(32):
            tick_lab(controller, f.now)
            # The disposable archive is the actual already-initialized owner.
            # Publish its measured snapshot using the recorder's cached shape,
            # without inventing coverage or bypassing the admission guard.
            recording = f.storage.snapshot()
            assert recording["state"] == "recording"
            assert recording["plan"] == f.plan.model_dump()
            (f.registry.path.parent / "research-storage-status.json").write_text(
                json.dumps(recording | {"receipt_at": f.now}), encoding="utf-8"
            )
            worked = controller.step(f.now)
            active = [
                t
                for t in paper.state["autonomous_lab"]["trials"].values()
                if t["status"] == "active"
            ]
            if active:
                break
            assert not controller.last_error, controller.last_error
            f.now = (
                f.now + 2
                if worked
                else max(f.now + 2, paper.state["autonomous_lab"]["next_action_at"])
            )
        assert len(active) == 1, {
            "error": controller.last_error,
            "lab": paper.state["autonomous_lab"],
            "inbox": controller.inbox.page(),
        }
        trial = active[0]
        assert trial["contract"]["proposal"]["strategy"]["family"] == "breakout-retest-v1"
        assert trial["contract"]["proposal"]["reference"]["family"] == "cost-breakout-v1"
        assert trial["review_at"] - trial["started_at"] >= 24 * 3600
        outcome = close_window(controller, trial, "data_blocked")
        f.now = outcome["available_at"] + 2
        assert asyncio.run(worker.step(f.now))
        original_outcome = copy.deepcopy(worker.get(saved["id"])["result"]["outcome"])
        f.now += 1
        assert asyncio.run(worker.step(f.now)), worker.get(saved["id"])
        completed = worker.get(saved["id"])
        assert completed["status"] == "done" and completed["stage"] == "complete"
        assert completed["result"]["outcome"]["body"]["outcome"] == "data_blocked"
        assert completed["result"]["followup"]["action"] == "no_change"
        assert completed["result"]["outcome"] == original_outcome
        followup_packet = worker.transport.calls[-1][1]
        assert packet_json(restore_scored_body(followup_packet["evidence"]["e1"])) == packet_json(
            original_outcome["body"]
        )
        assert completed["context"] == saved["context"]
        assert len(rows(worker, "role_attempts")) == 3  # Three deterministic software callbacks.
        assert rows(worker, "research_lessons")
        assert worker.select_followups()["selected"] == 0
        assert store.reconcile()["balanced"] is True
        for key, controls in original_controls.items():
            assert {name: paper.state["accounts"][key].get(name) for name in controls} == controls
        assert len(rows(worker, "lab_proposals")) == 1
    finally:
        f.close()


def test_repeated_ticks_restart_and_four_concurrent_selectors_publish_once(fixture):
    f, worker, _ = fixture
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(lambda _: worker.select_fresh_question(f.now), range(4)))
    assert sum(result) == 1
    original = task(worker)
    restarted = RoleWorker(
        f.registry,
        worker.controller,
        PatternTransport(),
        f.scanner.storage_owner,
        pattern_comparisons=PatternComparisons(f.scanner, worker.controller),
    )
    restarted.enabled = True
    restarted.paper_admission = lambda: True
    f.now += 61
    f.paper.state["last_tick"] = f.now
    assert restarted.select_fresh_question(f.now) == 0
    assert restarted.get(original["id"]) == original
    assert len(rows(worker, "role_question_selections")) == 1
    assert len(rows(worker, "pattern_comparison_requests")) == 1


@pytest.mark.parametrize(
    "missing", ["risk", "entry", "clock", "error", "bars", "gap", "bootstrap", "admission"]
)
def test_protected_missing_or_stale_input_never_creates_task_or_attempt(fixture, missing):
    f, worker, _ = fixture
    frames = f.paper.control_frames()
    f.paper.control_frames = lambda: frames
    if missing in {"risk", "entry"}:
        frames["BTCUSD"].pop(
            "diagnostic_risk_input_valid" if missing == "risk" else "entry_allowed"
        )
    elif missing == "clock":
        f.paper.state["last_tick"] = f.now - 11
    elif missing == "error":
        f.paper.error = "Synthetic capture/input unavailable"
    elif missing == "bars":
        f.paper.history["BTCUSD"] = f.paper.history["BTCUSD"][-304:]
    elif missing == "gap":
        f.paper.history["BTCUSD"].pop(-20)
    elif missing == "bootstrap":
        f.paper.ready_at = f.now + 60
    else:
        worker.paper_admission = lambda: False
    assert worker.select_fresh_question(f.now) == 0
    assert not rows(worker, "role_tasks") and not rows(worker, "role_attempts")
    assert worker.transport.calls == []


def test_waiting_original_preparation_is_not_reobserved_for_preferred_ready_answer(fixture):
    f, worker, _ = fixture
    f.paper.history["BTCUSD"] = f.paper.history["BTCUSD"][-304:]
    assert worker.select_fresh_question(f.now) == 0
    old = rows(worker, "pattern_comparison_requests")
    assert len(old) == 1
    f.paper.history["BTCUSD"] = bars_at(f.now - 400 * 60)[-200:] + bars_at(f.now)
    f.now += 61
    f.paper.state["last_tick"] = f.now
    assert worker.select_fresh_question(f.now) == 0
    assert rows(worker, "pattern_comparison_requests") == old
    assert not rows(worker, "role_tasks")


def test_live_admission_and_frame_tick_advances_do_not_rewrite_causal_cutoff(fixture):
    f, worker, _ = fixture
    policy = f.paper.state["autonomous_lab"]["policy"]
    causal_now = f.now
    bars = list(f.paper.history["BTCUSD"])

    def admitted():
        f.now += 0.1
        f.paper.state["last_tick"] = f.now
        return True

    def frames():
        f.now += 0.1
        return {"BTCUSD": causal_frame(f.now, bars)}

    worker.paper_admission = admitted
    f.paper.control_frames = frames
    worker._pattern_ready(policy, causal_now)
    assert f.now > causal_now
    assert f.paper.history["BTCUSD"] == bars


@pytest.mark.parametrize("change", ["stale", "risk", "empty"])
def test_actual_final_archived_frame_is_checked_before_frozen_packet(fixture, monkeypatch, change):
    f, worker, _ = fixture
    bridge = worker.pattern_comparisons
    original = bridge.execution_inputs
    frames = f.paper.control_frames()
    f.paper.control_frames = lambda: frames

    def reopen(*args):
        value = original(*args)
        if change == "stale":
            frames["BTCUSD"]["observed"] = f.now - 60
        elif change == "risk":
            frames["BTCUSD"]["diagnostic_risk_input_valid"] = False
        else:
            frames.clear()
        return value

    monkeypatch.setattr(bridge, "execution_inputs", reopen)
    assert worker.select_fresh_question(f.now) == 0
    assert not rows(worker, "role_tasks") and not rows(worker, "role_attempts")


def test_final_archive_completion_clock_advance_freezes_that_same_fresh_frame(fixture, monkeypatch):
    f, worker, _ = fixture
    bridge = worker.pattern_comparisons
    original = bridge.execution_inputs

    def reopen(*args):
        result = original(*args)
        f.now += 0.1
        f.paper.state["last_tick"] = f.now
        return result

    monkeypatch.setattr(bridge, "execution_inputs", reopen)
    saved = select(f, worker)
    frozen = saved["context"]["tool_evidence"]["executable_book"]
    assert frozen["observed"] == f.now
    assert frozen["entry_allowed"] is True and frozen["diagnostic_risk_input_valid"] is True


@pytest.mark.parametrize("change", ["eligibility", "used_rule", "capacity"])
def test_changed_admission_after_archive_refuses_publication(fixture, monkeypatch, change):
    f, worker, _ = fixture
    bridge = worker.pattern_comparisons
    reopen = bridge.execution_inputs

    def changed(*args):
        result = reopen(*args)
        if change == "eligibility":
            f.paper.universe.scanned_at = f.now - 121
        elif change == "capacity":
            monkeypatch.setattr(worker.controller.inbox, "has_capacity", lambda: False)
        else:
            receipt = bridge.get(args[1])
            worker.controller.submit(LabProposal.model_validate(receipt["proposal"]), f.now)
        return result

    monkeypatch.setattr(bridge, "execution_inputs", changed)
    assert worker.select_fresh_question(f.now) == 0
    assert not rows(worker, "role_tasks") and not rows(worker, "role_attempts")


@pytest.mark.parametrize("change", ["eligibility", "used_rule"])
def test_changed_admission_before_attempt_keeps_original_and_spends_nothing(fixture, change):
    f, worker, _ = fixture
    saved = select(f, worker)
    if change == "eligibility":
        f.paper.universe.scanned_at = f.now - 121
    else:
        original = worker.pattern_comparisons.get(
            saved["context"]["pattern_comparison"]["preparation_request_id"]
        )
        worker.controller.submit(LabProposal.model_validate(original["proposal"]), f.now)
    assert not asyncio.run(worker.step(f.now))
    retained = worker.get(saved["id"])
    assert retained["context"] == saved["context"] and retained["stage"] == "idea"
    assert not rows(worker, "role_attempts") and worker.transport.calls == []


@pytest.mark.parametrize("phase", ["publication", "attempt"])
def test_protected_interval_appearing_after_verification_refuses_without_attempt(
    fixture, monkeypatch, phase
):
    f, worker, _ = fixture

    def protect():
        bar = f.paper.history["BTCUSD"][-50]
        with f.registry.transaction():
            f.registry.db.execute(
                "INSERT INTO evidence_windows VALUES(?,?,?,'holdout')",
                ("qa-protected-race", bar.open_ms / 1000, bar.close_ms / 1000),
            )

    if phase == "publication":
        old = worker.pattern_comparisons.execution_inputs

        def reopen(*args):
            value = old(*args)
            protect()
            return value

        monkeypatch.setattr(worker.pattern_comparisons, "execution_inputs", reopen)
        with pytest.raises(ValueError, match="Protected evaluation"):
            worker.select_fresh_question(f.now)
        assert not rows(worker, "role_tasks")
    else:
        saved = select(f, worker)
        protect()
        assert not asyncio.run(worker.step(f.now))
        assert worker.get(saved["id"])["context"] == saved["context"]
    assert not rows(worker, "role_attempts") and worker.transport.calls == []


@pytest.mark.parametrize("action", ["no_change", "unsupported_capability", "request_data"])
def test_original_answer_and_spent_attempt_never_retry_or_spawn_same_native_event(fixture, action):
    f, worker, _ = fixture
    worker.transport.action = action
    original = select(f, worker)
    assert asyncio.run(worker.step(f.now))
    completed = worker.get(original["id"])
    attempts = rows(worker, "role_attempts")
    assert len(attempts) == 1 and attempts[0][5] == "answered"
    f.now += 61
    f.paper.state["last_tick"] = f.now
    assert worker.select_fresh_question(f.now) == 0
    assert worker.get(original["id"]) == completed
    assert rows(worker, "role_attempts") == attempts
    assert len(worker.transport.calls) == 1


def test_actual_worker_numerical_archive_review_and_existing_inbox_no_financial_effect(fixture):
    f, worker, _ = fixture
    worker.transport.action = "propose_experiment"
    before = copy.deepcopy(f.paper.state)
    original = select(f, worker)
    for expected in ("evaluate", "archive_evaluation", "review", "submit", "outcome"):
        assert asyncio.run(worker.step(f.now)), (expected, worker.get(original["id"])["reason"])
        saved = worker.get(original["id"])
        assert saved["stage"] == expected, saved["reason"]
    evaluation = saved["evaluation"]
    assert evaluation["input_count"] == 600 and evaluation["input_sha256"]
    assert evaluation["reference"]["financial_authority"] is False
    assert reopen_evidence(f.plan, evaluation["detail_reference"])["kind"] == "role_evaluation"
    assert len(rows(worker, "lab_proposals")) == 1
    submitted = worker.controller.inbox.get(saved["proposal"]["request_id"])
    assert submitted["body"]["strategy"]["family"] == "breakout-retest-v1"
    assert len(worker.transport.calls) == 2 and len(rows(worker, "role_attempts")) == 2
    assert worker.controller.inbox.get(saved["proposal"]["request_id"])
    assert f.paper.state == before


def fresh_numerical_task(f, worker):
    worker.transport.action = "propose_experiment"
    original = select(f, worker)
    assert asyncio.run(worker.step(f.now))
    assert worker.get(original["id"])["stage"] == "evaluate"
    old_end = f.paper.history["BTCUSD"][-1].close_ms / 1000
    advance(f, 120)
    f.paper.history["BTCUSD"] = bars_at(f.now - 400 * 60)[-200:] + bars_at(f.now)
    return original, old_end


def test_fresh_numerical_tail_is_disclosed_atomically_and_cannot_become_holdout(
    fixture, monkeypatch
):
    f, worker, _ = fixture
    original, old_end = fresh_numerical_task(f, worker)
    state, attempts = copy.deepcopy(f.paper.state), rows(worker, "role_attempts")
    assert asyncio.run(worker.step(f.now)), worker.get(original["id"])["reason"]
    saved = worker.get(original["id"])
    assert saved["stage"] == "archive_evaluation"
    evaluation = saved["evaluation"]
    disclosure = evaluation["input_disclosure"]
    assert disclosure["input_sha256"] == fingerprint(evaluation["inputs"])
    assert disclosure["input_count"] == 600 and disclosure["observed_at"] == f.now
    start = evaluation["inputs"][0]["open_ms"] / 1000
    end = (evaluation["inputs"][-1]["close_ms"] + 1) / 1000
    assert end > old_end + 60 and disclosure["intervals"][-1] == [start, end]
    for identity, interval in zip(disclosure["window_ids"], disclosure["intervals"], strict=True):
        window = f.registry.db.execute(
            "SELECT start,end,origin FROM evidence_windows WHERE request_id=?", (identity,)
        ).fetchone()
        assert tuple(window) == (*interval, "Pattern comparison preparation disclosure")
        assert disclosure["input_sha256"] in identity
    # The holdout's protection prefix covers only the newly evaluated minute tail.
    test_start = old_end + 0.001 + 300
    with monkeypatch.context() as clock:
        clock.setattr(
            "trading.experiment_registry.time", SimpleNamespace(time=lambda: test_start + 3601)
        )
        with pytest.raises(ValueError, match="consumed information"):
            f.registry.reserve(
                plan(
                    "fresh-tail-holdout",
                    as_of=test_start + 3601,
                    test_start=test_start,
                    test_end=test_start + 3600,
                    evidence_kind="synthetic_qa",
                ),
                "a" * 64,
            )
    assert asyncio.run(worker.step(f.now))
    archived = worker.get(original["id"])["evaluation"]
    packet = reopen_evidence(f.plan, archived["detail_reference"])
    assert packet["evaluation"]["input_disclosure"] == disclosure
    assert fingerprint(packet["evaluation"]["inputs"]) == disclosure["input_sha256"]
    assert rows(worker, "role_attempts") == attempts and len(worker.transport.calls) == 1
    assert not rows(worker, "lab_proposals") and f.paper.state == state
    assert worker.get(original["id"])["context"] == original["context"]


@pytest.mark.parametrize("protected", ["holdout", "prospective"])
def test_new_protection_during_actual_evaluation_refuses_publication_and_archive(
    fixture, monkeypatch, protected
):
    f, worker, _ = fixture
    original, old_end = fresh_numerical_task(f, worker)
    before_windows = rows(worker, "evidence_windows")
    attempts = rows(worker, "role_attempts")
    evaluate = worker.controller.evaluate
    calls = []

    def changed(proposal, now):
        value = evaluate(proposal, now)
        calls.append(proposal.strategy.family)
        if len(calls) == 2:
            with f.registry.transaction():
                if protected == "holdout":
                    f.registry.db.execute(
                        "INSERT INTO evidence_windows VALUES(?,?,?,'holdout')",
                        ("qa-numerical-tail-race", old_end + 0.001, f.now),
                    )
                else:
                    f.registry.db.execute("CREATE TABLE prospective_plans(start REAL,end REAL)")
                    f.registry.db.execute(
                        "INSERT INTO prospective_plans VALUES(?,?)", (old_end + 0.001, f.now)
                    )
        return value

    monkeypatch.setattr(worker.controller, "evaluate", changed)
    assert not asyncio.run(worker.step(f.now))
    saved = worker.get(original["id"])
    assert saved["stage"] == "evaluate" and saved["status"] == "failed"
    assert "Protected" in saved["reason"] and saved["evaluation"] is None
    assert calls == ["breakout-retest-v1", "cost-breakout-v1"]
    windows = rows(worker, "evidence_windows")
    assert windows == before_windows + (
        [("qa-numerical-tail-race", old_end + 0.001, f.now, "holdout")]
        if protected == "holdout"
        else []
    )
    assert rows(worker, "role_attempts") == attempts and len(worker.transport.calls) == 1
    assert saved["context"] == original["context"] and not rows(worker, "lab_proposals")


@pytest.mark.parametrize("identity", ["missing", "altered"])
def test_actual_numerical_prefix_requires_both_evaluated_feature_hashes(
    fixture, monkeypatch, identity
):
    f, worker, _ = fixture
    original, _ = fresh_numerical_task(f, worker)
    windows, attempts = rows(worker, "evidence_windows"), rows(worker, "role_attempts")
    evaluate = worker.controller.evaluate

    def changed(proposal, now):
        value = evaluate(proposal, now)
        if identity == "missing":
            value["feature"].pop("input_bars_sha256")
        else:
            value["inputs"][-1]["volume"] = "999"
        return value

    monkeypatch.setattr(worker.controller, "evaluate", changed)
    assert not asyncio.run(worker.step(f.now))
    saved = worker.get(original["id"])
    assert saved["status"] == "failed" and saved["stage"] == "evaluate"
    assert "evaluated feature identity" in saved["reason"] and saved["evaluation"] is None
    assert rows(worker, "evidence_windows") == windows
    assert rows(worker, "role_attempts") == attempts and not rows(worker, "lab_proposals")


def test_lost_lease_during_actual_evaluation_publishes_neither_prefix_nor_disclosure(
    fixture, monkeypatch
):
    f, worker, _ = fixture
    original, _ = fresh_numerical_task(f, worker)
    windows, attempts = rows(worker, "evidence_windows"), rows(worker, "role_attempts")
    evaluate = worker.controller.evaluate
    calls = []

    def changed(proposal, now):
        value = evaluate(proposal, now)
        calls.append(proposal.strategy.family)
        if len(calls) == 2:
            with f.registry.transaction():
                f.registry.db.execute(
                    "UPDATE role_tasks SET owner='qa-replacement-owner' WHERE id=?",
                    (original["id"],),
                )
        return value

    monkeypatch.setattr(worker.controller, "evaluate", changed)
    asyncio.run(worker.step(f.now))
    raw = f.registry.db.execute(
        "SELECT stage,owner,evaluation FROM role_tasks WHERE id=?", (original["id"],)
    ).fetchone()
    assert tuple(raw) == ("evaluate", "qa-replacement-owner", None)
    assert calls == ["breakout-retest-v1", "cost-breakout-v1"]
    assert rows(worker, "evidence_windows") == windows
    assert rows(worker, "role_attempts") == attempts and len(worker.transport.calls) == 1
    assert worker.get(original["id"])["context"] == original["context"]
    assert not rows(worker, "lab_proposals")


def test_full_authority_replacement_prevents_lease_or_attempt_and_keeps_original(fixture):
    f, worker, _ = fixture
    original = select(f, worker)
    worker.transport.authority["profile_sha"] = "c" * 64
    before = rows(worker, "role_tasks")
    assert not asyncio.run(worker.step(f.now))
    assert worker.resume_sources(f.now) == 0
    assert worker.select_followups()["selected"] == 0
    assert rows(worker, "role_tasks") == before
    assert worker.get(original["id"]) == original
    assert not rows(worker, "role_attempts")


def test_old_frozen_contract_hashes_unchanged_and_new_hyphenated_inventory_is_explicit():
    assert (
        contract_hash(VERSION) == "71f90342b3781819e690cf9bb8890a750e97a34b3818fb1a8d04b2324682b7f5"
    )
    assert (
        contract_hash(TOOL_REQUEST_VERSION)
        == "cb4d5c9435720f7c48e85ecbc582658821e01d2ad51d92274cfb54bc1a64e4e3"
    )
    assert (
        contract_hash(CAPABILITY_VERSION)
        == "2e2eb51ff1ea49d65a96032e0c19b107b1780efcef9f65cb8d8d2a31e92aab6e"
    )
    # Old schemas continue rejecting bank identifiers; only the new version accepts them.
    packet = {
        "contract": PATTERN_VERSION,
        "capabilities": {
            "p0": {"family": "breakout-retest-v1", "reference_family": "cost-breakout-v1"}
        },
        "tool_inventory": {
            "strategy_family": ["breakout-retest-v1", "cost-breakout-v1"],
            "feature": [],
            "analysis_tool": [],
        },
        "evidence": {"e2": {}},
    }
    assert validate("researcher", abstention(), packet, PATTERN_VERSION)
    for version in (TOOL_REQUEST_VERSION, CAPABILITY_VERSION):
        packet["contract"] = version
        with pytest.raises(ValueError):
            validate("researcher", abstention(), packet, version)


def test_v8_inventory_cannot_omit_offered_reference_family(fixture):
    f, worker, _ = fixture
    _, packet = worker._packet(select(f, worker))
    packet["tool_inventory"]["strategy_family"].remove("cost-breakout-v1")
    with pytest.raises(ValueError, match="omits"):
        validate("researcher", abstention(), packet, PATTERN_VERSION)
