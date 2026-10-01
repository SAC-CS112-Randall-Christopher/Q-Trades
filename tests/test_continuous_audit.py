"""Disposable regressions for the six independent PR24 findings; no market qualification."""

import copy
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from threading import Barrier

import pytest
from test_autonomous_lab import admit, close_window, make_lab, tick_lab
from test_paper_engine import START, frame
from test_paper_store import pg_store as pg_store
from test_pattern_memory import entry
from test_research_storage import packet, plan_at

from trading import autonomous_finance as finance
from trading.autonomous_spec import LabPolicy, LabProposal, RuleSpec, rule_feature
from trading.compact_memory import CompactMemory
from trading.execution_profiles import LEGACY_EXECUTION
from trading.experiment_registry import ExperimentPlan, ExperimentRegistry, fingerprint
from trading.lab_proposals import LabProposals
from trading.paper_engine import PaperEngine, initial_state
from trading.paper_strategy import Bar
from trading.research_evidence import canonical, digest
from trading.research_storage import ResearchStorage

CAPTURE_START = 1_790_605_200.0


def test_unlink_ack_loss_retries_before_advancing_cleanup(tmp_path, monkeypatch):
    from pathlib import Path

    store = ResearchStorage(plan_at(tmp_path))
    refs = []
    for i in range(6):
        refs.extend(store.append([packet(START + i)], START + i))
        store.housekeeping(START + i, capacity_triggered=True)
    real_unlink = Path.unlink
    interrupted = False

    def lose_ack(path, *args, **kwargs):
        nonlocal interrupted
        real_unlink(path, *args, **kwargs)
        if path.name.startswith("segment-") and not interrupted:
            interrupted = True
            raise OSError("Synthetic lost unlink acknowledgment")

    monkeypatch.setattr(Path, "unlink", lose_ack)
    with pytest.raises(OSError, match="acknowledgment"):
        store.housekeeping(START + 8000, capacity_triggered=True)
    monkeypatch.setattr(Path, "unlink", real_unlink)
    store.close()
    store = ResearchStorage(plan_at(tmp_path))
    for i in range(6):
        store.housekeeping(START + 8001 + i, capacity_triggered=True)
    assert not list(store.temporary.glob("segment-*.sqlite"))
    assert all(store.reopen(ref)["at"] == START + i for i, ref in enumerate(refs))
    store.close()


def test_all_eligible_segments_reclaim_with_protection_and_restart(tmp_path):
    plan = plan_at(tmp_path)
    store = ResearchStorage(plan)
    refs = []
    for i in range(8):
        refs.extend(store.append([packet(START + i)], START + i))
        store.housekeeping(START + i, capacity_triggered=True)
    store.protect(refs[0], START + 86400, "Pending protected dependency")
    store.close()
    store = ResearchStorage(plan)
    for i in range(8):
        store.housekeeping(START + 8000 + i, capacity_triggered=True)
    assert [p.name for p in store.temporary.glob("segment-*.sqlite")] == [
        "segment-000000000001.sqlite"
    ]
    assert all(store.reopen(ref)["at"] == START + i for i, ref in enumerate(refs))
    store.housekeeping(START + 86401, capacity_triggered=True)
    assert not list(store.temporary.glob("segment-*.sqlite"))
    store.close()


def proposal(bundle, *, bad_parent=False, horizon="short", name="valid-replication"):
    reference = RuleSpec(holding_horizon=horizon)
    return LabProposal(
        request_id=name,
        policy_id="continuous-test-policy",
        source="external",
        kind="variation" if bad_parent else "replication",
        strategy=reference.model_copy(update={"lookback": 11}) if bad_parent else reference,
        reference=reference,
        parent_trial="missing-parent" if bad_parent else None,
        parent_strategy_sha256=fingerprint(reference.model_dump()) if bad_parent else None,
        replication_of="reviewed-breakout-v1"
        if horizon == "short"
        else "reviewed-breakout-" + horizon + "-v2",
        mechanism="Explicit reviewed configuration for a disposable regression",
        question="Does the queue make progress without bypassing financial admission?",
        evidence_bundle_sha256=bundle["sha256"],
    )


@pytest.mark.parametrize("old_queue", [False, True])
def test_invalid_parent_cannot_block_valid_queued_work(pg_store, tmp_path, old_queue):
    store, _ = pg_store
    lab = make_lab(store, tmp_path)
    bundle = lab.bundle(START)
    bad = proposal(bundle, bad_parent=True, name="invalid-parent-proposal")
    good = proposal(bundle)
    if old_queue:
        lab.inbox.submit(bad, {})  # Reopen a formerly accepted or now-stale parent intent.
    else:
        lab.submit(bad, START)
    lab.submit(good, START)
    for i in range(4):
        now = START + i * 62
        tick_lab(lab, now)
        lab.step(now)
    assert lab.inbox.get(bad.request_id)["status"] == "rejected"
    assert "parent" in lab.inbox.get(bad.request_id)["reason"].lower()
    assert any(
        t["proposal_id"] == good.request_id and t["status"] == "active"
        for t in store.read()["autonomous_lab"]["trials"].values()
    )
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_transient_family_wait_allows_independent_work_and_retry(pg_store, tmp_path):
    from trading.autonomous_lab import AutonomousLab

    store, _ = pg_store
    lab = make_lab(store, tmp_path, family_slots=2)
    existing = admit(lab, START)
    now = existing["started_at"] + 2
    tick_lab(lab, now)
    bundle = lab.bundle(now)
    waiting = proposal(bundle, name="waiting-replication")
    valid = LabProposal(
        request_id="independent-behind-wait",
        policy_id=waiting.policy_id,
        kind="independent",
        strategy=RuleSpec(family="range_reversion", lookback=20),
        reference=RuleSpec(),
        mechanism="Distinct range idea behind a full family",
        question="Does family-specific capacity leave another eligible proposal usable?",
        evidence_bundle_sha256=bundle["sha256"],
    )
    lab.submit(waiting, now)
    lab.submit(valid, now)
    for i in range(4):
        tick_lab(lab, now + i * 2)
        lab.step(now + i * 2)
    assert lab.inbox.get(waiting.request_id)["status"] == "blocked"
    assert "family" in lab.inbox.get(waiting.request_id)["reason"]
    assert any(
        t["proposal_id"] == valid.request_id and t["status"] == "active"
        for t in store.read()["autonomous_lab"]["trials"].values()
    )
    lab = AutonomousLab(lab.registry, lab.paper, lambda: True)
    lab.paper.state = store.transact(
        now + 10,
        lambda engine: finance.retire_trial(
            engine, existing["id"], "Explicit disposable operator retirement"
        ),
    )
    retry = lab.inbox.get(waiting.request_id)["next_retry"]
    for i in range(4):
        tick_lab(lab, retry + i * 2)
        lab.step(retry + i * 2)
        if lab.inbox.get(waiting.request_id)["status"] == "funded":
            break
    assert lab.inbox.get(waiting.request_id)["status"] == "funded"
    assert lab.inbox.get(waiting.request_id)["reason"] is None
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_deferred_family_job_allows_controller_generated_discovery(pg_store, tmp_path):
    from trading.autonomous_lab import AutonomousLab

    store, _ = pg_store
    lab = make_lab(store, tmp_path, family_slots=2, horizon_seconds=3600)
    parent = admit(lab, START)
    close_window(lab, parent, "promising")
    before = store.read()
    frozen_parent = copy.deepcopy(before["autonomous_lab"]["trials"][parent["id"]])
    account = before["accounts"][parent["candidate"]]
    frozen_identity = {
        k: copy.deepcopy(account[k]) for k in ("rule_spec", "risk_policy", "funding", "admitted_at")
    }
    assert frozen_parent["status"] == "preserved"
    assert finance.slots(before)["used"] == 7  # Six originals and the frozen parent.
    assert lab._family_available("range_reversion", True)
    assert not lab._family_available("breakout")

    now = parent["review_at"] + 4
    tick_lab(lab, now)
    waiting = proposal(lab.bundle(now), name="deferred-behind-preserved-parent")
    lab.submit(waiting, now)
    assert not lab.step(now)
    deferred = lab.inbox.get(waiting.request_id)
    assert deferred["status"] == "blocked" and "family" in deferred["reason"]
    assert (
        deferred["next_retry"]
        == now + lab.paper.state["autonomous_lab"]["policy"]["cooldown_seconds"]
    )

    # Five further normal passes: the controller must issue the independent idea.
    # No direct generator call or manually submitted range proposal bypasses it.
    for i in range(1, 6):
        tick_lab(lab, now + i * 2)
        lab.step(now + i * 2)
        assert not lab.last_error, lab.last_error
    after = store.read()
    independent = [
        t
        for t in after["autonomous_lab"]["trials"].values()
        if t["contract"]["proposal"]["kind"] == "independent"
    ]
    assert len(independent) == 1
    trial = independent[0]
    assert trial["status"] == "active"
    generated = lab.inbox.get(trial["proposal_id"])
    assert generated["status"] == "funded" and generated["body"]["source"] == "deterministic"
    assert generated["body"]["strategy"]["family"] == "range_reversion"
    assert generated["evaluation"]["status"] == "supported_exploratory_configuration"
    assert lab.inbox.get(waiting.request_id) == deferred  # Its own backoff is unchanged.
    assert after["autonomous_lab"]["phase"] == "proposal_wait"
    assert after["autonomous_lab"]["next_action_at"] == deferred["next_retry"]
    assert after["autonomous_lab"]["trials"][parent["id"]] == frozen_parent
    assert {
        k: after["accounts"][parent["candidate"]][k] for k in frozen_identity
    } == frozen_identity
    assert finance.slots(after)["used"] == 9
    lab.registry.close()
    lab = AutonomousLab(
        ExperimentRegistry(tmp_path / "experiments.sqlite3"), lab.paper, lambda: True
    )
    tick_lab(lab, now + 12)
    assert not lab.step(now + 12)
    assert lab.inbox.get(waiting.request_id) == deferred
    assert store.read()["autonomous_lab"]["next_action_at"] == deferred["next_retry"]
    for account_id in (trial["candidate"], trial["reference"]):
        assert (
            store.connection.execute(
                "SELECT count(*) AS n FROM paper_events "
                "WHERE kind='lab_account_funded' AND account=%s",
                (account_id,),
            ).fetchone()["n"]
            == 1
        )
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_full_deferred_queue_waits_without_generating_or_issuing_bundle(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    lab = make_lab(store, tmp_path)
    bundle = lab.bundle(START)
    for i in range(4):
        p = proposal(bundle, name=f"full-deferred-queue-{i}")
        lab.submit(p, START)
        lab.inbox.defer(p.request_id, "Temporary admission wait", START + 60 + i * 60)
    before = lab.inbox.page()
    with pytest.raises(ValueError, match="Four active proposal jobs"):
        lab.submit(proposal(bundle, name="overflow-deferred-queue"), START)

    def no_discovery(_now):
        pytest.fail("A full four-job inbox must not dispatch autonomous discovery")

    monkeypatch.setattr(lab, "propose", no_discovery)
    assert not lab.step(START)
    assert lab.inbox.page() == before
    current = store.read()["autonomous_lab"]
    assert current["phase"] == "proposal_wait" and current["next_action_at"] == START + 60
    assert not lab.last_error
    assert lab.registry.db.execute("SELECT count(*) FROM lab_bundles").fetchone()[0] == 1
    assert finance.slots(store.read())["used"] == 6
    assert store.reconcile()["balanced"]
    lab.registry.close()


def test_discovery_capacity_precheck_cannot_overfill_concurrent_inbox(tmp_path):
    registry = ExperimentRegistry(tmp_path / "experiments.sqlite3")
    inbox = LabProposals(registry)
    bundle = inbox.bundle({"schema": "permitted-lab-bundle-v1", "evidence": {}})
    for i in range(3):
        p = proposal(bundle, name=f"last-inbox-slot-{i}")
        inbox.submit(p, {})
        inbox.defer(p.request_id, "Temporary admission wait", START + 300)
    barrier = Barrier(2)

    def submit_last_slot(i):
        assert inbox.has_capacity()
        barrier.wait(timeout=5)  # Both producers observe the same remaining slot.
        try:
            return inbox.submit(proposal(bundle, name=f"concurrent-discovery-{i}"), {})["status"]
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit_last_slot, range(2)))
    assert results.count("evaluated") == 1
    assert sum("Four active proposal jobs" in result for result in results) == 1
    assert not inbox.has_capacity()
    assert len(inbox.page()["proposals"]) == 4
    registry.close()


@pytest.mark.parametrize(
    ("guard", "expected_phase"),
    [
        ("resource", "waiting"),
        ("hourly", "budget_wait"),
        ("daily", "budget_wait"),
        ("pause", "paused"),
    ],
)
def test_deferred_discovery_respects_resource_budget_and_pause_guards(
    pg_store, tmp_path, monkeypatch, guard, expected_phase
):
    store, _ = pg_store
    lab = make_lab(store, tmp_path)
    p = proposal(lab.bundle(START), name="deferred-guard-check")
    lab.submit(p, START)
    lab.inbox.defer(p.request_id, "Temporary admission wait", START + 300)
    before = lab.inbox.get(p.request_id)

    def configure(engine):
        current = engine.state["autonomous_lab"]
        # Explicit synthetic budget fixture; no funding or outcomes are invented.
        if guard == "hourly":
            current["budget"]["steps"] = current["policy"]["hourly_steps"]
        elif guard == "daily":
            current["budget"]["trials"] = current["policy"]["daily_trials"]
        elif guard == "pause":
            finance.control(engine, "pause_proposals")

    lab.paper.state = store.transact(START, configure)
    if guard == "resource":
        monkeypatch.setattr(lab, "can_research", lambda: False)

    def no_discovery(_now):
        pytest.fail("A deferred job must not bypass the existing dispatch guards")

    monkeypatch.setattr(lab, "propose", no_discovery)
    assert not lab.step(START)
    assert store.read()["autonomous_lab"]["phase"] == expected_phase
    assert lab.inbox.get(p.request_id) == before
    assert not lab.last_error
    assert finance.slots(store.read())["used"] == 6
    assert store.reconcile()["balanced"]
    lab.registry.close()


def training_bundle(cutoff):
    return {
        "schema": "permitted-lab-bundle-v1",
        "evidence": {
            "training_episodes": [
                {
                    "episode": "disclosed-loss",
                    "cutoff": cutoff,
                    "available_at": cutoff + 2700,
                    "net_bps": -77,
                    "training_only": True,
                }
            ],
            "completed_trials": [],
        },
    }


def evaluation(cutoff, name="disclosed-window-evaluation"):
    return ExperimentPlan(
        request_id=name,
        name="Untouched comparison",
        mechanism="A bounded numerical rule under test",
        falsification="The held comparison rejects that rule",
        as_of=cutoff + 4000,
        test_start=cutoff + 1,
        test_end=cutoff + 3000,
    )


def test_bundle_disclosure_consumes_interval_and_retry_is_idempotent(tmp_path, monkeypatch):
    cutoff = START
    monkeypatch.setattr("trading.experiment_registry.time.time", lambda: cutoff + 5000)
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    inbox = LabProposals(registry)
    issued = inbox.bundle(training_bundle(cutoff))
    assert issued["bundle"]["evidence"]["training_episodes"][0]["net_bps"] == -77
    with pytest.raises(ValueError, match="consumed"):
        registry.reserve(evaluation(cutoff), "code")
    assert inbox.bundle(training_bundle(cutoff)) == issued
    assert (
        registry.db.execute(
            "SELECT count(*) FROM evidence_windows WHERE origin='lab proposer disclosure'"
        ).fetchone()[0]
        == 1
    )
    registry.close()


def test_bundle_and_reservation_cannot_both_expose_same_holdout(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.experiment_registry.time.time", lambda: START + 5000)
    path = tmp_path / "registry.sqlite"
    first, second = ExperimentRegistry(path), ExperimentRegistry(path)
    inbox = LabProposals(first)
    ready = Barrier(2)

    def issue():
        ready.wait()
        return bool(inbox.bundle(training_bundle(START))["bundle"]["evidence"]["training_episodes"])

    def reserve():
        ready.wait()
        try:
            second.reserve(evaluation(START), "code")
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        disclosure, reservation = pool.submit(issue), pool.submit(reserve)
        assert not (disclosure.result() and reservation.result())
    first.close()
    second.close()


@pytest.mark.parametrize("continued", [False, True])
def test_normal_bundle_loss_is_protected_before_return(pg_store, tmp_path, monkeypatch, continued):
    monkeypatch.setattr("trading.experiment_registry.time.time", lambda: START + 5000)
    store, _ = pg_store
    lab = make_lab(store, tmp_path)
    compact = CompactMemory(tmp_path / "memory-episodes.sqlite")
    descriptor = entry(START - 3600, "disclosed-loss")["descriptor"]
    label = {
        "status": "available",
        "available_at": START - 900,
        "net_bps": -77,
        "coverage": "Explicit synthetic executable outcome fixture",
    }
    compact.db.execute(
        "INSERT INTO compact_prefixes VALUES(NULL,?,?,?,?,?)",
        (
            "disclosed-loss",
            descriptor["cutoff"],
            descriptor["cutoff"] + 0.1,
            canonical(descriptor),
            digest(descriptor),
        ),
    )
    if continued:
        from trading.outcome_continuation import OutcomeContinuation

        continuation = OutcomeContinuation(tmp_path)
        continuation.db.execute(
            "INSERT INTO continued_outcomes VALUES(?,?,?,?,?,?)",
            (
                "compact",
                "disclosed-loss",
                digest(descriptor),
                label["available_at"],
                canonical(label),
                digest(label),
            ),
        )
        continuation.db.commit()
        continuation.close()
    else:
        compact.db.execute(
            "INSERT INTO compact_outcomes VALUES(?,?,?,?)",
            ("disclosed-loss", label["available_at"], canonical(label), digest(label)),
        )
    compact.db.commit()
    issued = lab.bundle(START)
    assert issued["bundle"]["evidence"]["training_episodes"][0]["net_bps"] == -77
    with pytest.raises(ValueError, match="consumed"):
        lab.registry.reserve(evaluation(START - 3600), "code")
    assert lab.bundle(START) == issued
    compact.close()
    lab.registry.close()


def range_bars(now, interval):
    end = int(now // interval) * interval * 1000
    result = []
    for aggregate in range(330):
        price = D(100) + (D("0.8") if aggregate % 2 else D(0))
        if aggregate == 329:
            price = D("99.5")
        for minute in range(interval // 60):
            at = end - (330 - aggregate) * interval * 1000 + minute * 60000
            result.append(
                Bar(at, price, price + D("0.2"), price - D("0.2"), price, D(100), at + 59999)
            )
    return result


@pytest.mark.parametrize("horizon", ["short", "medium", "long"])
def test_range_signal_enters_engine_at_each_declared_interval(horizon):
    spec = RuleSpec(family="range_reversion", lookback=20, holding_horizon=horizon)
    now = START + 3600.001
    bars = range_bars(now, spec.timing["feature_seconds"])
    feature = rule_feature(bars, now, spec, LEGACY_EXECUTION)
    assert feature["eligible"], feature
    engine = PaperEngine(initial_state(START), START)
    engine.universe_experiment(["BTCUSD", "ETHUSD"])
    finance.start(
        engine,
        LabPolicy(
            request_id="continuous-test-policy", holding_horizons=("short", "medium", "long")
        ),
    )
    p = LabProposal(
        request_id="range-entry-" + horizon,
        policy_id="continuous-test-policy",
        kind="independent",
        strategy=spec,
        reference=RuleSpec(holding_horizon=horizon),
        mechanism="Range excursion tested through the actual entry engine",
        question="Can contiguous sampling at the declared horizon submit an entry?",
        evidence_bundle_sha256="0" * 64,
    )
    trial = finance.reserve(engine, p)["trial_id"]
    finance.fund(engine, trial)
    candidate = engine.state["autonomous_lab"]["trials"][trial]["candidate"]
    version = engine.state["accounts"][candidate]["version"]
    engine = PaperEngine(engine.state, now)
    engine.tick({"BTCUSD": frame(now, "99.5")}, {"BTCUSD": {version: feature}})
    assert engine.state["accounts"][candidate]["pending"], engine.events
    assert any(e["kind"] == "order_intent" and e["account"] == candidate for e in engine.events)


def test_horizon_rotation_survives_bounded_scores_retries_and_restart(pg_store, tmp_path):
    from trading.autonomous_lab import AutonomousLab

    store, _ = pg_store
    lab = make_lab(store, tmp_path, daily_trials=24, holding_horizons=("short", "medium", "long"))
    seed = proposal(lab.bundle(START))
    lab.inbox.submit(seed, {})
    lab.inbox.update(seed.request_id, "completed", "synthetic-prior-seed")

    def prior_results(engine):
        for i in range(16):
            engine.emit(
                "lab_trial_scored",
                "system",
                {
                    "trial_id": "synthetic-prior-" + str(i),
                    "proposal_id": seed.request_id,
                    "outcome": "low_information",
                    "available_at": START - 10,
                    "window_start": START - 7200,
                    "window_end": START - 20,
                    "reason": "Explicit synthetic allocation fixture, no qualification",
                },
            )

    lab.paper.state = store.transact(START, prior_results)
    expected = ["short", "medium", "long"]
    for i in range(16):
        proposed = lab.propose(START + i)
        assert proposed.strategy.holding_horizon == expected[i % 3]
        assert lab.propose(START + i) == proposed  # No allocation before admission.
        lab.inbox.submit(proposed, {})
        receipt = store.lab_reserve(START + i, proposed)
        assert store.lab_reserve(START + i, proposed)["trial_id"] == receipt["trial_id"]
        lab.paper.state = store.read()
        assert lab.paper.state["autonomous_lab"]["horizon_cursor"] == i + 1
        lab.paper.state = store.transact(
            START + i,
            lambda engine, receipt=receipt: finance.retire_trial(
                engine, receipt["trial_id"], "Synthetic unfunded intent closure"
            ),
        )
        lab.inbox.update(proposed.request_id, "completed", receipt["trial_id"])
        if i == 7:
            lab = AutonomousLab(lab.registry, lab.paper, lambda: True)
        assert len(lab.bundle(START + i)["bundle"]["evidence"]["completed_trials"]) == 12
    assert store.reconcile()["balanced"]
    lab.registry.close()


def capture_engine_interval(directory):
    import asyncio
    import time

    from test_autonomous_lab import bars_at

    from trading.evidence_runtime import EvidenceRecorder
    from trading.paper_strategy import VARIANTS, features
    from trading.research_evidence import EvidenceArchive
    from trading.research_storage import save_plan

    legacy = directory / "research-evidence.sqlite"
    EvidenceArchive(legacy).close()
    original = legacy.read_bytes()
    plan = plan_at(directory)
    save_plan(directory, plan)
    recorder = EvidenceRecorder(legacy)
    state = initial_state(CAPTURE_START)
    for i in range(3):
        now = CAPTURE_START + 1 + i * 2
        bars = bars_at(now)
        frames = {"BTCUSD": {**frame(now, str(bars[-1].close), i + 1), "source": "synthetic-audit"}}
        study = {"BTCUSD": {version: features(bars, now, version) for version in VARIANTS}}
        value = recorder.prepare(
            now, frames, study, {"BTCUSD": bars}, {"BTCUSD": now}, 0, {}, state, [], {}, {}
        )
        engine = PaperEngine(state, now)
        engine.tick(frames, study)
        recorder.complete(value, engine.events, engine.state, [], {}, time.monotonic())
        state = engine.state
        asyncio.run(recorder.flush())
    storage = recorder._storage
    assert storage is not None
    for i in range(4):
        storage.housekeeping(CAPTURE_START + 8000 + i * 8000, capacity_triggered=True)
    assert not list(storage.temporary.glob("segment-*.sqlite"))
    rows = storage.db.execute(
        "SELECT sha,segment,record FROM storage_records WHERE kind='decision' ORDER BY at"
    ).fetchall()
    refs = [f"capture-v2:{row[1]}:{row[2]}:{row[0]}" for row in rows]
    assert legacy.read_bytes() == original
    return recorder, refs, original


@pytest.mark.parametrize(
    "mode,accounts",
    [
        ("order_flow", False),
        ("memory_entry", True),
        ("component_exit", False),
        ("component_size", False),
        ("observation_priority", False),
    ],
)
def test_capture_rollover_full_evaluator_and_exact_replay(tmp_path, monkeypatch, mode, accounts):
    import asyncio

    from trading.experiment_lab import ExperimentLab
    from trading.replay_lab import ReplayLab, ReplayPlan

    monkeypatch.setattr("trading.research_storage.time.time", lambda: CAPTURE_START + 100)
    recorder, refs, original = capture_engine_interval(tmp_path)
    monkeypatch.undo()  # Real child leases and receipt times must use the real worker clock.
    d = entry(CAPTURE_START + 3, "new-external-prefix")["descriptor"]
    recorder._compact.db.execute(
        "INSERT INTO compact_prefixes VALUES(NULL,?,?,?,?,?)",
        ("new-external-prefix", d["cutoff"], d["cutoff"] + 0.1, canonical(d), digest(d)),
    )
    recorder._compact.db.commit()
    lab = ExperimentLab(tmp_path / "experiments.sqlite3", None, lambda: True)
    plan = ExperimentPlan(
        request_id="full-evaluator-" + mode.replace("_", "-"),
        name="External capture acquisition",
        mechanism="Same engine decisions survive archive rollover",
        falsification="Missing dependencies cannot be claimed as a full comparison",
        experiment_mode=mode,
        account_comparison=accounts,
        horizon_minutes=45,
        as_of=CAPTURE_START + 40000,
        test_start=CAPTURE_START + 1,
        test_end=CAPTURE_START + 5,
    )
    receipt = lab.enqueue(plan)
    assert receipt["status"] == "queued"
    snapshot = lab.registry.get(plan.request_id, inputs=True)["snapshot"]
    assert len(snapshot["records"]) == 3
    assert [r["id"] for r in snapshot["records"]] == refs
    assert all(r["archive"] == "capture-v2" for r in snapshot["records"])
    assert any(r["episode"] == "new-external-prefix" for r in snapshot["rows"])
    assert snapshot["manifest"]["rows"] == len(snapshot["rows"])
    assert asyncio.run(lab.run_once())
    result = lab.registry.get(plan.request_id)
    assert result["status"] == "completed", result
    assert result["result"] is not None  # Insufficient training is an honest evaluated result.
    assert result["result"]["evidence_kind"] == "synthetic_qa"
    replay = ReplayLab(tmp_path / "replays.sqlite", recorder.path, lambda: True)
    requested = ReplayPlan(
        request_id="external-exact-replay-" + mode.replace("_", "-"), record_id=refs[0], records=3
    )
    assert replay.enqueue(requested)["status"] == "queued"
    assert asyncio.run(replay.run_once())
    final = replay.registry.get(requested.request_id)
    assert final["status"] == "completed", final
    assert final["result"]["status"] == "reconciled"
    assert [r["id"] for r in final["result"]["input_references"]] == refs
    assert recorder.path.read_bytes() == original
    replay.registry.close()
    lab.registry.close()
    recorder._compact.close()
    recorder._maturity.close()
    recorder._storage.close()


def test_acquisition_merges_versions_deduplicates_and_remains_read_only(tmp_path, monkeypatch):
    from trading.research_acquisition import decision_records
    from trading.research_evidence import EvidenceArchive
    from trading.research_storage import save_plan

    monkeypatch.setattr("trading.research_storage.time.time", lambda: CAPTURE_START + 100)
    path = tmp_path / "research-evidence.sqlite"
    old = EvidenceArchive(path)
    values = [packet(CAPTURE_START + i, bars={}) for i in range(3)]
    old.append(values[:2])
    # Freeze the original stored bytes, including v1's honest unavailable-prefix receipt.
    import json

    values[:2] = [
        json.loads(r[0])
        for r in old.connection.execute("SELECT payload FROM evidence_records ORDER BY id")
    ]
    old.close()
    original = path.read_bytes()
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    storage = ResearchStorage(plan)
    refs = storage.append(values[1:], CAPTURE_START + 100)
    index_before = storage.db.execute("SELECT * FROM storage_state").fetchone()
    result = decision_records(path, CAPTURE_START, CAPTURE_START + 2, CAPTURE_START + 100)
    assert [r["payload"] for r in result["records"]] == values
    assert [r["archive"] for r in result["records"]] == ["full", "full", "capture-v2"]
    assert result["records"][-1]["id"] == refs[-1]
    assert tuple(storage.db.execute("SELECT * FROM storage_state").fetchone()) == tuple(
        index_before
    )
    assert path.read_bytes() == original
    storage.close()


@pytest.mark.parametrize("failure", ["unknown_availability", "changed_payload", "missing_capture"])
def test_acquisition_refuses_unavailable_exact_dependencies(tmp_path, monkeypatch, failure):
    import sqlite3

    from trading.research_acquisition import decision_records
    from trading.research_storage import save_plan

    monkeypatch.setattr("trading.research_storage.time.time", lambda: CAPTURE_START + 100)
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    storage = ResearchStorage(plan)
    storage.append([packet(CAPTURE_START)], CAPTURE_START + 100)
    path = tmp_path / "research-evidence.sqlite"
    assert not decision_records(path, CAPTURE_START, CAPTURE_START + 1, CAPTURE_START + 99)[
        "records"
    ]
    if failure == "unknown_availability":
        storage.db.execute("UPDATE storage_records SET available=NULL")
        storage.db.commit()
    elif failure == "changed_payload":
        with sqlite3.connect(storage._path(1)) as segment:
            segment.execute(
                "UPDATE records SET body=?", (canonical(packet(CAPTURE_START, bad=True)),)
            )
    else:
        storage._path(1).unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        decision_records(path, CAPTURE_START, CAPTURE_START + 1, CAPTURE_START + 100)
    assert not path.exists()  # No empty fallback database or invented replacement.
    storage.close()


def test_complete_interval_refuses_record_and_byte_budgets(tmp_path, monkeypatch):
    from trading.research_acquisition import DependencyBudget, decision_records, replay_records
    from trading.research_storage import save_plan

    monkeypatch.setattr("trading.research_storage.time.time", lambda: CAPTURE_START + 100)
    plan = plan_at(tmp_path)
    save_plan(tmp_path, plan)
    storage = ResearchStorage(plan)
    refs = storage.append([packet(CAPTURE_START + i) for i in range(3)], CAPTURE_START + 100)
    path = tmp_path / "research-evidence.sqlite"
    with pytest.raises(DependencyBudget, match="2 records"):
        decision_records(path, CAPTURE_START, CAPTURE_START + 2, CAPTURE_START + 100, limit=2)
    with pytest.raises(DependencyBudget, match="100 byte"):
        decision_records(
            path, CAPTURE_START, CAPTURE_START + 2, CAPTURE_START + 100, bytes_limit=100
        )
    assert [r["id"] for r in replay_records(path, refs[1], 2, CAPTURE_START + 100)] == refs[1:]
    storage.close()


@pytest.mark.parametrize("horizon", ["short", "medium", "long"])
def test_range_sampling_retains_gap_future_and_minute_guards(horizon):
    from trading.numerical_candidates import feature_value

    spec = RuleSpec(family="range_reversion", lookback=20, holding_horizon=horizon)
    now = START + 3600.001
    bars = range_bars(now, spec.timing["feature_seconds"])
    assert rule_feature(bars, now, spec, LEGACY_EXECUTION)["eligible"]
    gapped = bars[:]
    del gapped[-10]
    assert not rule_feature(gapped, now, spec, LEGACY_EXECUTION)["eligible"]
    future = bars + [
        Bar(int(now * 1000) + 60000, D(1), D(1), D(1), D(1), D(1), int(now * 1000) + 119999)
    ]
    guarded = rule_feature(future, now, spec, LEGACY_EXECUTION)
    assert not guarded["eligible"]
    assert "coverage" in guarded["reason"]
    history = [{"minute": i * 5, "mid": 100 + i / 100, "at": i * 300} for i in range(21)]
    assert feature_value(history, "range_reversion") is None
    assert feature_value(history, "range_reversion", interval_minutes=5) is not None
    with pytest.raises(ValueError, match="sampling"):
        feature_value(history, "range_reversion", interval_minutes=2)


def test_normal_api_can_reopen_and_replay_retained_v2_capture(tmp_path, monkeypatch):
    import asyncio

    from fastapi.testclient import TestClient

    from trading.api import create_app
    from trading.config import Settings

    monkeypatch.setattr("trading.research_storage.time.time", lambda: CAPTURE_START + 100)
    recorder, refs, original = capture_engine_interval(tmp_path)
    monkeypatch.undo()
    app = create_app(
        Settings(),
        tmp_path / "monitor.sqlite",
        background=False,
        research_evidence=tmp_path / "no-model-evidence",
    )
    with TestClient(app) as client:
        reopened = client.get("/api/research/storage/evidence", params={"reference": refs[0]})
        assert reopened.status_code == 200
        assert reopened.json()["reference"] == refs[0]
        body = {"request_id": "api-external-capture-replay", "record_id": refs[0], "records": 3}
        assert client.post("/api/replays", json=body).status_code == 403
        accepted = client.post("/api/replays", json=body, headers={"X-Local-Operator": "1"})
        assert accepted.status_code == 200 and accepted.json()["status"] == "queued"
        # The API-only fixture has no market worker; isolate acquisition from its health gate.
        app.state.replay.can_research = lambda: True
        assert asyncio.run(app.state.replay.run_once())
        completed = client.get("/api/replays/" + body["request_id"]).json()
        assert completed["status"] == "completed"
        assert completed["result"]["status"] == "reconciled"
        assert [r["id"] for r in completed["result"]["input_references"]] == refs
        assert client.post("/api/replays", json=body, headers={"X-Local-Operator": "1"}).json()[
            "retry"
        ]
    assert recorder.path.read_bytes() == original
    recorder._compact.close()
    recorder._maturity.close()
    recorder._storage.close()


def test_full_capture_without_prefix_is_still_classified_synthetic(tmp_path, monkeypatch):
    import json

    from trading.experiment_lab import ExperimentLab
    from trading.experiment_worker import evaluate

    monkeypatch.setattr("trading.research_storage.time.time", lambda: CAPTURE_START + 100)
    recorder, _, _ = capture_engine_interval(tmp_path)
    monkeypatch.undo()
    lab = ExperimentLab(tmp_path / "experiments.sqlite3", None, lambda: True)
    plan = ExperimentPlan(
        request_id="no-prefix-synthetic-capture",
        name="Full capture data mode",
        mechanism="Synthetic packets remain synthetic with no descriptor prefix",
        falsification="Observed-market claims require observed-market inputs",
        experiment_mode="order_flow",
        horizon_minutes=45,
        as_of=CAPTURE_START + 40000,
        test_start=CAPTURE_START + 1,
        test_end=CAPTURE_START + 5,
    )
    assert lab.enqueue(plan)["status"] == "queued"
    job = lab.registry.get(plan.request_id, inputs=True)
    assert job["snapshot"]["records"] and not job["snapshot"]["rows"]
    job["snapshot"] = json.dumps(job["snapshot"])
    job["plan"] = json.dumps(job["plan"])
    result = evaluate(job)
    assert result["evidence_kind"] == "synthetic_qa"
    assert not result["eligible_for_exploratory_paper"]
    assert not result["eligible_for_forward_review"]
    lab.registry.close()
    recorder._compact.close()
    recorder._maturity.close()
    recorder._storage.close()
