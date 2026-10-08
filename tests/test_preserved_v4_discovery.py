"""Source-only native seeds and an explicitly disposable synthetic PG lifecycle."""

import copy
import json
import time
from collections import Counter
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_autonomous_lab import admit, bars_at, make_lab
from test_paper_engine import START, frame
from test_paper_store import pg_store as pg_store
from test_redesign_strategy import fixture as strategy_fixture
from test_rule_component import component

from trading import autonomous_finance as finance
from trading.autonomous_lab import AutonomousLab
from trading.autonomous_spec import ORIGINALS, LabPolicy, LabProposal, RuleSpec
from trading.experiment_registry import ExperimentRegistry, fingerprint
from trading.paper_engine import PaperEngine, account, initial_state
from trading.paper_store import PaperStore


def fixed_spec():
    return RuleSpec(
        version="reviewed-lab-rules-v4",
        family="compression-breakout-v1",
        holding_horizon="medium",
    )


@pytest.fixture
def native_lab(tmp_path):
    # These preserved-parent seeds exercise proposer/schema control only. They
    # are NOT a claimed earned financial preservation or historical return.
    state = initial_state(START)
    finance.start(PaperEngine(state, START), LabPolicy(request_id="synthetic-native-policy"))
    paper = SimpleNamespace(state=state, running=True, error=None)
    registry = ExperimentRegistry(tmp_path / "native-registry.sqlite3")
    lab = AutonomousLab(registry, paper, lambda: True)
    lab.bundle = lambda now: lab.inbox.bundle(
        {
            "scope": "Synthetic native control; no financial preservation evidence",
            "evidence": {"training_episodes": [], "completed_trials": []},
            "current_inputs": {"last_closed_at": now - 1},
        }
    )
    yield lab
    registry.close()


def seed_parent(lab, spec, name="synthetic-parent"):
    candidate, reference = name + "-candidate", name + "-reference"
    lab.paper.state["accounts"][candidate] = {
        **account("synthetic-control", START),
        "rule_spec": spec.model_dump(),
        "lab_trial": name,
    }
    parent = {
        "id": name,
        "candidate": candidate,
        "reference": reference,
        "status": "preserved",
        "branched": False,
        "contract": {"proposal": {"strategy": spec.model_dump(), "kind": "replication"}},
    }
    lab.paper.state["autonomous_lab"]["trials"][name] = parent
    return parent


def test_fixed_v4_parent_is_unchanged_and_later_baseline_discovery_runs(native_lab):
    parent = seed_parent(native_lab, fixed_spec())
    before = copy.deepcopy(native_lab.paper.state)
    proposal = native_lab.propose(START)
    assert proposal.kind == "replication"
    assert proposal.strategy == RuleSpec()
    assert proposal.parent_trial is None
    assert proposal.replication_of == "reviewed-breakout-v1"
    assert native_lab.paper.state == before
    assert parent["branched"] is False
    assert LabProposal.model_validate(proposal.model_dump()) == proposal


@pytest.mark.parametrize("version", ["reviewed-lab-rules-v2", "reviewed-lab-rules-v3"])
def test_fixed_v4_does_not_hide_later_legacy_lookback_variation(native_lab, version):
    fixed = seed_parent(native_lab, fixed_spec(), "fixed-v4-parent")
    spec = RuleSpec(
        version=version, **({"entry_filter": component()} if version.endswith("v3") else {})
    )
    legacy = seed_parent(native_lab, spec, "legacy-parent")
    before = copy.deepcopy(native_lab.paper.state)
    proposal = native_lab.propose(START)
    assert proposal.kind == "variation" and proposal.parent_trial == legacy["id"]
    assert proposal.reference == spec
    assert proposal.parent_strategy_sha256 == fingerprint(spec.model_dump())
    expected = spec.model_dump()
    expected["lookback"] = 9
    assert proposal.strategy.model_dump() == expected
    assert LabProposal.model_validate(proposal.model_dump()) == proposal
    finance.validate_parent(native_lab.paper.state, proposal)
    assert native_lab.paper.state == before
    assert not fixed["branched"] and not legacy["branched"]


def test_legacy_used_child_is_not_reissued_and_original_ack_reopens(native_lab):
    seed_parent(native_lab, fixed_spec(), "fixed-v4-parent")
    seed_parent(native_lab, RuleSpec(), "legacy-parent")
    first = native_lab.propose(START)
    acknowledged = native_lab.inbox.submit(first, {"scope": "Synthetic native numerical stub"})
    assert (
        native_lab.inbox.submit(first, acknowledged["evaluation"])["sha256"]
        == acknowledged["sha256"]
    )
    native_lab.inbox.update(first.request_id, "completed")
    second = native_lab.propose(START + 1)
    assert second.strategy.lookback == 11 and second.request_id != first.request_id
    assert native_lab.inbox.get(first.request_id)["body"] == first.model_dump()
    assert native_lab.registry.db.execute("SELECT count(*) FROM lab_proposals").fetchone()[0] == 1


def test_fixed_v4_skip_reaches_existing_independent_discovery(native_lab):
    parent = seed_parent(native_lab, fixed_spec())
    baseline = native_lab.propose(START)
    native_lab.inbox.submit(baseline, {"scope": "Synthetic native numerical stub"})
    native_lab.inbox.update(baseline.request_id, "completed")
    proposal = native_lab.propose(START + 1)
    assert proposal.kind == "independent" and proposal.strategy.family == "range_reversion"
    assert proposal.strategy.lookback == 20 and proposal.parent_trial is None
    assert not parent["branched"]


@pytest.mark.parametrize("guard", ["risk_stop_id", "fault", "lab_retiring", "purpose"])
def test_existing_parent_ineligibility_still_skips_legacy_child(native_lab, guard):
    parent = seed_parent(native_lab, RuleSpec())
    value = "performance_diagnostic" if guard == "purpose" else "synthetic-stop"
    native_lab.paper.state["accounts"][parent["candidate"]][guard] = value
    proposal = native_lab.propose(START)
    assert proposal.kind == "replication" and proposal.parent_trial is None
    assert not parent["branched"]


def test_existing_capacity_and_strict_fixed_schema_are_not_relaxed(native_lab):
    seed_parent(native_lab, fixed_spec())
    for i in range(20):
        native_lab.paper.state["accounts"][f"synthetic-capacity-{i}"] = account(
            "breakout-v1", START
        )
    assert native_lab.propose(START) is None
    with pytest.raises(ValidationError, match="fixed bank mechanism"):
        RuleSpec.model_validate({**fixed_spec().model_dump(), "lookback": 9})


@pytest.mark.parametrize("gate", ["proposals_paused", "paused", "resource"])
def test_supervisor_pause_and_resource_gates_precede_discovery(native_lab, monkeypatch, gate):
    seed_parent(native_lab, fixed_spec())
    phases = []
    monkeypatch.setattr(
        native_lab, "_state", lambda now, phase, reason, delay: phases.append(phase)
    )
    monkeypatch.setattr(native_lab, "_budget", lambda *args: None)
    monkeypatch.setattr(native_lab, "propose", lambda now: pytest.fail("Discovery bypassed guard"))
    if gate == "resource":
        native_lab.can_research = lambda: False
    elif gate == "paused":
        native_lab.paper.state["paused"] = True
    else:
        native_lab.paper.state["autonomous_lab"]["proposals_paused"] = True
    assert (
        native_lab._step(START, copy.deepcopy(native_lab.paper.state), time.perf_counter()) is False
    )
    assert phases == ["waiting" if gate == "resource" else "paused"]


def synthetic_tick(lab, now, price="100", eligible=False, coverage=False):
    """Actual engine orders/fills; explicit synthetic features and accelerated coverage."""
    paper = lab.paper
    paper.history = {"BTCUSD": bars_at(now)}
    paper.books = {"BTCUSD": frame(now, price, int(now * 10))}
    study = {"BTCUSD": {}}
    for saved in paper.state["accounts"].values():
        if not saved.get("lab_trial"):
            continue
        spec = saved["rule_spec"]
        feature = {
            "eligible": eligible,
            "atr": "1",
            "reason": "Synthetic observed-book execution fixture; not bank prediction",
            "bar_open_ms": int(now // 300) * 300000,
            "input_available_at": now,
            "version": saved["version"],
        }
        if spec["version"] == "reviewed-lab-rules-v4":
            feature.update(redesign_version="synthetic-fixed-bank-input", mechanism=spec["family"])
        study["BTCUSD"][saved["version"]] = feature

    def apply(engine):
        if coverage:
            for trial in engine.state["autonomous_lab"]["trials"].values():
                if trial["status"] == "active":
                    trial["covered_seconds"] = max(
                        0, min(now, trial["review_at"]) - trial["started_at"]
                    )
            engine.emit("synthetic_coverage_fixture", "system", {"qualification": False})
        engine.tick(paper.books, study)

    paper.state = paper.store.transact(now, apply)


def test_actual_engine_refuses_reused_bar_then_enters_on_later_synthetic_bar(native_lab):
    """In-memory execution check; no PG journal or economic preservation claim."""
    state = initial_state(START)
    setup = PaperEngine(state, START)
    setup.universe_experiment(["BTCUSD", "ETHUSD"])
    finance.start(
        setup,
        LabPolicy(request_id="synthetic-fixedbar-policy", holding_horizons=("short", "medium")),
    )
    native_lab.paper.state = state
    events = []

    def transact(now, apply):
        engine = PaperEngine(native_lab.paper.state, now)
        apply(engine)
        events.extend(copy.deepcopy(engine.events))
        return engine.state

    native_lab.paper.store = SimpleNamespace(transact=transact)
    proposal = LabProposal(
        request_id="synthetic-fixedbar-pair-001",
        policy_id="synthetic-fixedbar-policy",
        kind="independent",
        strategy=fixed_spec(),
        reference=RuleSpec(
            version="reviewed-lab-rules-v4", family="washout-rebound-v1", holding_horizon="medium"
        ),
        mechanism="Synthetic new-bar execution-control fixture",
        question="Does the actual engine retain its new-bar admission gate?",
        evidence_bundle_sha256=native_lab.bundle(START)["sha256"],
    )
    reserved = finance.reserve(setup, proposal)
    finance.fund(setup, reserved["trial_id"])
    trial = state["autonomous_lab"]["trials"][reserved["trial_id"]]
    synthetic_tick(native_lab, START + 2)
    synthetic_tick(native_lab, START + 4)
    first_bar = state["accounts"][trial["candidate"]]["last_decision"]["BTCUSD"]["bar"]
    synthetic_tick(native_lab, START + 120, "90", True)
    synthetic_tick(native_lab, START + 122, "90", True)
    assert not state["accounts"][trial["candidate"]]["positions"]
    assert not any(event["kind"] == "order_intent" for event in events)
    synthetic_tick(native_lab, START + 600, "90", True)
    synthetic_tick(native_lab, START + 602, "90", True)
    for role in ("candidate", "reference"):
        saved = state["accounts"][trial[role]]
        assert saved["last_decision"]["BTCUSD"]["bar"] > first_bar
        assert saved["positions"], json.dumps(saved["last_decision"], indent=2)
        assert D(saved["fees"]) > 0
        assert any(event["account"] == trial[role] and event["kind"] == "fill" for event in events)


def test_actual_preserved_v4_parent_keeps_accounting_and_normal_discovery(pg_store, tmp_path):
    """Earn preservation via the real scorer; no manual preserved/branched or P&L edits."""
    store, dsn = pg_store
    lab = make_lab(store, tmp_path, holding_horizons=("short", "medium"), hourly_compute_seconds=60)
    initial = store.export(0, 10000)
    original = copy.deepcopy(lab.paper.state["accounts"])
    failure = None
    try:
        bars = strategy_fixture("compression-breakout-v1")
        offset = int(START * 1000) - bars[-1].close_ms - 1
        lab.paper.history["BTCUSD"] = [
            replace(bar, open_ms=bar.open_ms + offset, close_ms=bar.close_ms + offset)
            for bar in bars
        ]
        proposal = LabProposal(
            request_id="preserved-v4-real-owner-001",
            policy_id="continuous-test-policy",
            kind="independent",
            strategy=fixed_spec(),
            reference=RuleSpec(
                version="reviewed-lab-rules-v4",
                family="washout-rebound-v1",
                holding_horizon="medium",
            ),
            mechanism="Synthetic prospective fixed pair through existing financial owner",
            question=(
                "Can the unchanged fixed controls earn preservation on synthetic observed books?"
            ),
            evidence_bundle_sha256=lab.bundle(START)["sha256"],
        )
        assert lab.submit(proposal, START)["status"] == "evaluated"
        parent = admit(lab, START)
        assert parent["contract"]["proposal"] == proposal.model_dump()
        parent_id = parent["id"]
        controls = copy.deepcopy(parent["contract"])
        candidate = lab.paper.state["accounts"][parent["candidate"]]
        identity = {
            key: candidate[key] for key in ("rule_spec", "funding", "risk_policy", "admitted_at")
        }
        start = parent["started_at"]
        synthetic_tick(lab, start + 2)
        synthetic_tick(lab, start + 4)
        # A genuine later five-minute decision ID is required: +120 reuses
        # the first ineligible bar and is correctly skipped by the engine.
        synthetic_tick(lab, start + 600, "90", True)
        synthetic_tick(lab, start + 602, "90", True)
        candidate = lab.paper.state["accounts"][parent["candidate"]]
        assert candidate["positions"], json.dumps(candidate["last_decision"], indent=2)
        synthetic_tick(lab, start + 605, "110")
        synthetic_tick(lab, start + 22300, "110")
        synthetic_tick(lab, start + 22302, "110")
        at = parent["review_at"]
        # After the actual candidate exit, the book returns to its initial
        # level. This intentionally synthetic positive control must beat the
        # full-period passive benchmark through the unchanged scorer.
        synthetic_tick(lab, at, "100", coverage=True)
        assert lab.step(at), lab.last_error
        scored = store.connection.execute(
            "SELECT body FROM paper_events WHERE kind='lab_trial_scored' AND body->>'trial_id'=%s",
            (parent_id,),
        ).fetchone()
        assert scored is not None
        assert scored["body"]["outcome"] == "promising", json.dumps(scored["body"], indent=2)
        parent = lab.paper.state["autonomous_lab"]["trials"][parent_id]
        assert parent["score"] == scored["body"]
        assert parent["status"] == "preserved" and parent["branched"] is False
        assert parent["contract"] == controls
        candidate = lab.paper.state["accounts"][parent["candidate"]]
        assert candidate["lab_protected"] and candidate["closed"] == 1 and D(candidate["fees"]) > 0
        assert {key: candidate[key] for key in identity} == identity
        synthetic_tick(lab, at + 2, "100")
        assert store.archived_account(parent["reference"])

        # The ordinary pause gate still blocks new discovery after preservation.
        lab.paper.state = store.transact(
            at + 3, lambda engine: finance.control(engine, "pause_proposals", None)
        )
        synthetic_tick(lab, at + 4, "100")
        assert lab.step(at + 4) is False
        assert lab.paper.state["autonomous_lab"]["phase"] == "paused"
        resume = lab.paper.state["autonomous_lab"]["next_action_at"]
        lab.paper.state = store.transact(
            resume, lambda engine: finance.control(engine, "resume_proposals", None)
        )
        successor = admit(lab, resume)
        discovered = successor["contract"]["proposal"]
        assert discovered["kind"] == "replication" and discovered["parent_trial"] is None
        assert discovered["strategy"] == RuleSpec().model_dump()
        assert discovered["strategy"]["version"] == "reviewed-lab-rules-v2"
        parent = lab.paper.state["autonomous_lab"]["trials"][parent_id]
        assert parent["status"] == "preserved" and not parent["branched"]
        assert parent["contract"] == controls
        assert {
            key: lab.paper.state["accounts"][parent["candidate"]][key] for key in identity
        } == identity
        for name in ORIGINALS:
            for key in (
                "rule_spec",
                "funding",
                "risk_policy",
                "execution_profile",
                "starting_capital",
            ):
                assert lab.paper.state["accounts"][name].get(key) == original[name].get(key)
        audit = store.export(0, 10000)
        assert not audit["has_more"]
        assert audit["records"][: len(initial["records"])] == initial["records"]
        assert store.reconcile()["balanced"]
        assert finance.slots(lab.paper.state)["capacity"] == 20
        assert lab.inbox.get(proposal.request_id)["body"] == proposal.model_dump()
        # Reopen through both original state and immutable proposal owners.
        # A fresh read connection bypasses the original writer's RAM projection;
        # it does not compete for or claim a second financial writer.
        reopened = PaperStore(dsn)
        reopened_registry = ExperimentRegistry(lab.registry.path)
        try:
            restored = AutonomousLab(
                reopened_registry, SimpleNamespace(state=reopened.read()), lambda: False
            )
            assert restored.inbox.get(proposal.request_id)["body"] == proposal.model_dump()
            assert (
                restored.paper.state["autonomous_lab"]["trials"][parent_id]["contract"] == controls
            )
            assert reopened.archived_account(parent["reference"])
            assert reopened.reconcile()["balanced"]
        finally:
            reopened_registry.close()
            reopened.close()
    except BaseException as exc:
        failure = {"type": type(exc).__name__, "error": str(exc)[:2000]}
        raise
    finally:
        errors = []

        def retain(name, value):
            try:
                encoded = json.dumps(value, indent=2, default=str).encode("utf-8")
                if len(encoded) > 4 * 1024**2:
                    raise ValueError("Disposable artifact exceeds 4 MiB")
                (tmp_path / name).write_bytes(encoded)
            except Exception as exc:
                errors.append(
                    {"artifact": name, "type": type(exc).__name__, "error": str(exc)[:1000]}
                )

        try:
            audit = store.export(0, 10000)
            events = audit["records"]
            counts = Counter((row["account"], row["kind"]) for row in events)
            retain("financial-export.json", audit)
            retain("paper-state.json", lab.paper.state)
            retain(
                "discovery-proof.json",
                {
                    "scope": (
                        "Disposable PG actual financial owner, synthetic features/books/coverage; "
                        "no economic qualification"
                    ),
                    "original_failure": failure,
                    "prefix_sha256": fingerprint(initial["records"]),
                    "prefix_preserved": events[: len(initial["records"])] == initial["records"],
                    "event_counts": [
                        {"account": a, "kind": k, "count": n}
                        for (a, k), n in sorted(counts.items())
                    ],
                    "slots": finance.slots(lab.paper.state),
                    "reconciliation": store.reconcile(),
                    "capture_errors": errors,
                },
            )
        except Exception as exc:
            errors.append(
                {
                    "artifact": "financial-capture",
                    "type": type(exc).__name__,
                    "error": str(exc)[:1000],
                }
            )
        (tmp_path / "capture-errors.json").write_text(
            json.dumps(errors, indent=2), encoding="utf-8"
        )
        lab.registry.close()
        if failure is None:
            assert not errors, errors
