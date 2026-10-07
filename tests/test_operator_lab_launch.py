"""Finite operator setup proposal; synthetic inputs, never operating permissions."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_autonomous_lab import make_lab
from test_paper_engine import START
from test_paper_store import pg_store as pg_store

from trading import autonomous_finance as finance
from trading.api import create_app
from trading.autonomous_spec import LabProposal, OperatorLaunch, RuleSpec
from trading.config import Settings
from trading.engine_diagnostics import EngineWorkDiagnostics, EngineWorkPressurePolicy
from trading.experiment_registry import fingerprint
from trading.paper_store import PaperStore
from trading.tiered_runtime import TieredPaperRuntime

HEADERS = {"X-Local-Operator": "1", "Origin": "http://testserver"}


def resource_owner(monkeypatch, duration=600, count=20):
    """Actual owner methods and observation producers, with synthetic clock/audit."""
    paper = TieredPaperRuntime.__new__(TieredPaperRuntime)
    paper._work_pressure = EngineWorkPressurePolicy()
    paper._work_diagnostics = EngineWorkDiagnostics()
    paper.disk_free = 10 * 1024**3
    paper._capture_failure = None
    paper._readback_error = None
    paper._readback_sample = None
    paper._readback_audit_mono = 11.0
    paper.receipts = {"balanced": True}
    now = 11.0
    for index in range(count):
        now = 11.0 + index * 0.6
        paper._work_pressure.observe(duration, now)
        pressure = paper._work_pressure.evaluate(now)
        paper._work_diagnostics.record(
            {"at": START + index * 0.6, "elapsed_ms": duration},
            now,
            repeated=pressure.observed_repeated,
            severe=pressure.observed_severe,
        )
    monkeypatch.setattr(
        "trading.tiered_runtime.time",
        SimpleNamespace(monotonic=lambda: now + 0.1, time=lambda: START),
    )
    return paper


@pytest.mark.parametrize("duration", [600, 1200])
def test_explicit_exception_requires_complete_known_moderate_or_severe_work(monkeypatch, duration):
    owner = resource_owner(monkeypatch, duration)
    before = copy.deepcopy((owner._work_pressure._window, owner._work_diagnostics.samples))
    assert not owner.operator_launch_admission()["admitted"]
    admitted = owner.operator_launch_admission(True)
    assert admitted["admitted"] and admitted["latency_exception_applied"]
    assert admitted["complete_current_work_coverage"]
    assert admitted["raw_blocking_conditions"] == ["engine_work_recovery"]
    assert owner.constrained()  # Background and trade gates remain closed.
    assert (owner._work_pressure._window, owner._work_diagnostics.samples) == before


def test_default_uses_existing_admission_without_new_diagnostic_completeness_rule(monkeypatch):
    owner = resource_owner(monkeypatch, duration=50)
    owner._work_diagnostics.samples.clear()
    assert not owner.constrained()
    assert owner.operator_launch_admission()["admitted"]
    assert not owner.operator_launch_admission(True)["admitted"]


@pytest.mark.parametrize(
    "fault",
    [
        "startup",
        "missing_number",
        "wrong_epoch",
        "stale",
        "regressed_clock",
        "gap",
        "unknown_duration",
        "policy_mismatch",
        "unproven_trigger",
    ],
)
def test_exception_refuses_unknown_or_incomplete_work_coverage(monkeypatch, fault):
    owner = resource_owner(monkeypatch, count=19 if fault == "startup" else 20)
    if fault == "missing_number":
        owner._work_diagnostics.samples[4]["work_number"] += 1
    elif fault == "wrong_epoch":
        owner._work_diagnostics.samples[4]["observation_epoch"] = "another-process"
    elif fault == "stale":
        monkeypatch.setattr("trading.tiered_runtime.time.monotonic", lambda: 99.0)
    elif fault == "regressed_clock":
        monkeypatch.setattr("trading.tiered_runtime.time.monotonic", lambda: 1.0)
    elif fault == "gap":
        owner._work_diagnostics.samples[4]["observed_mono"] -= 3
    elif fault == "unknown_duration":
        owner._work_diagnostics.samples[4]["elapsed_ms"] = None
    elif fault == "policy_mismatch":
        owner._work_pressure._window[4] = 10
    elif fault == "unproven_trigger":
        owner._work_diagnostics.last_trigger = None
    result = owner.operator_launch_admission(True)
    assert not result["admitted"]
    assert "engine_work_observation_coverage" in result["blocking_conditions"]


@pytest.mark.parametrize(
    "fault", ["disk", "capture", "audit_missing", "audit_expired", "imbalance", "audit_error"]
)
def test_exception_preserves_every_existing_nonlatency_resource_veto(monkeypatch, fault):
    owner = resource_owner(monkeypatch)
    if fault == "disk":
        owner.disk_free = 1
    elif fault == "capture":
        owner._capture_failure = "Synthetic recording failure"
    elif fault == "audit_missing":
        owner._readback_audit_mono = None
    elif fault == "audit_expired":
        owner._readback_audit_mono = -200.0
    elif fault == "imbalance":
        owner.receipts["balanced"] = False
    elif fault == "audit_error":
        owner._readback_error = "Synthetic observer error"
    result = owner.operator_launch_admission(True)
    assert not result["admitted"] and result["blocking_conditions"]


def setup_launch(store, directory, monkeypatch, duration=600, evidence_records=None):
    monkeypatch.setattr("trading.autonomous_lab.time.time", lambda: START)
    monkeypatch.setattr(
        "trading.autonomous_lab.shutil.disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3)
    )
    lab = make_lab(store, directory)
    if evidence_records is not None:
        lab.paper.evidence = SimpleNamespace(
            enqueue=lambda payload: evidence_records.append(copy.deepcopy(payload))
        )
    owner = resource_owner(monkeypatch, duration)
    lab.operator_admission = owner.operator_launch_admission
    lab.can_research = lambda: not owner.constrained()
    issued = lab.bundle(START)
    proposal = LabProposal(
        request_id="operator-launch-test-0001",
        policy_id="continuous-test-policy",
        source="external",
        kind="independent",
        strategy=RuleSpec(family="range_reversion", lookback=5),
        reference=RuleSpec(lookback=5),
        mechanism="Synthetic matched range/breakout setup under unchanged cash and rules",
        question="Does the finite prospective range comparison beat its after-cost reference?",
        evidence_bundle_sha256=issued["sha256"],
    )
    assert lab.submit(proposal, START)["status"] == "evaluated"
    intent = OperatorLaunch(
        intent="finite-paper-account-setup-v1",
        expected_proposal_sha256=fingerprint(proposal.model_dump()),
        expected_policy_sha256=lab.paper.state["autonomous_lab"]["policy_sha256"],
        allow_engine_work_recovery=True,
    )
    return lab, proposal, intent, owner


def test_default_full_guard_blocks_and_explicit_pair_funds_once(pg_store, tmp_path, monkeypatch):
    store, _ = pg_store
    evidence_records = []
    lab, proposal, intent, owner = setup_launch(
        store, tmp_path, monkeypatch, evidence_records=evidence_records
    )
    assert len(evidence_records) == 1
    assert evidence_records[0]["kind"] == "lab_inputs"
    assert evidence_records[0]["evaluation"] == lab.evaluate(proposal, START)
    assert evidence_records[0]["evaluation"]["inputs"]
    assert "inputs_sha256" not in evidence_records[0]
    assert "input_count" not in evidence_records[0]
    before, events = store.read(), store.export(0, 1000)
    default = intent.model_copy(update={"allow_engine_work_recovery": False})
    with pytest.raises(finance.AdmissionWait, match="Protected setup admission"):
        lab.launch_existing(proposal.request_id, default)
    assert store.read() == before and store.export(0, 1000) == events
    result = lab.launch_existing(proposal.request_id, intent)
    assert result["status"] == "funded"
    after = store.read()
    assert len(after["accounts"]) == 8
    assert {key: after["accounts"][key] for key in before["accounts"]} == before["accounts"]
    assert store.reconcile()["balanced"] and owner.constrained()
    retained = store.export(0, 1000)
    assert len([row for row in retained["records"] if row["kind"] == "lab_account_funded"]) == 2
    assert lab.launch_existing(proposal.request_id, intent)["status"] == "already_funded"
    assert store.export(0, 1000) == retained
    assert lab.inbox.get(proposal.request_id)["status"] == "funded"
    assert after["autonomous_lab"]["budget"]["steps"] == 2
    assert after["autonomous_lab"]["budget"]["compute_seconds"] >= 2
    outcome = store.lab_proposal_outcome(proposal.request_id)
    assert outcome and outcome["funding_complete"] and len(outcome["funded_accounts"]) == 2


def test_five_short_pairs_create_ten_unique_accounts_preserving_eight_and_twenty_slots(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    lab, proposal, _, owner = setup_launch(store, tmp_path, monkeypatch)
    old = proposal.model_copy(
        update={
            "request_id": "synthetic-old-range-twenty",
            "strategy": RuleSpec(family="range_reversion", lookback=20),
            "reference": RuleSpec(lookback=10),
        }
    )
    old_id = store.lab_reserve(START, old)["trial_id"]
    lab.paper._transact_state(START, lambda engine: finance.fund(engine, old_id))
    before = copy.deepcopy(lab.paper.state["accounts"])
    for lookback, family, reference in (
        (5, "range_reversion", "breakout"),
        (15, "range_reversion", "breakout"),
        (30, "breakout", "range_reversion"),
        (8, "breakout", "range_reversion"),
        (22, "breakout", "range_reversion"),
    ):
        item = (
            proposal
            if lookback == 5
            else proposal.model_copy(
                update={
                    "request_id": f"operator-five-pairs-{lookback}",
                    "strategy": RuleSpec(family=family, lookback=lookback),
                    "reference": RuleSpec(family=reference, lookback=lookback),
                }
            )
        )
        # Fresh synthetic source identities; no operating proposal is resubmitted.
        lab.submit(item, START)
        intent = OperatorLaunch(
            intent="finite-paper-account-setup-v1",
            expected_proposal_sha256=fingerprint(item.model_dump()),
            expected_policy_sha256=lab.paper.state["autonomous_lab"]["policy_sha256"],
            allow_engine_work_recovery=True,
        )
        assert lab.launch_existing(item.request_id, intent)["status"] == "funded"
    state = store.read()
    assert {key: state["accounts"][key] for key in before} == before
    added = [value for key, value in state["accounts"].items() if key not in before]
    assert len(added) == len({fingerprint(account["rule_spec"]) for account in added}) == 10
    assert all(account["cash"] == "100" and account["funding"] == "100" for account in added)
    assert finance.slots(state)["managed"] == 18 and finance.slots(state)["available"] == 2
    assert state["autonomous_lab"]["policy"]["family_slots"] == 6
    assert state["autonomous_lab"]["policy"]["daily_trials"] == 8
    assert store.reconcile()["balanced"] and owner.constrained()


def test_existing_background_reservation_is_funded_once_after_protected_recheck(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    lab, proposal, intent, _ = setup_launch(store, tmp_path, monkeypatch)
    reserved = store.lab_reserve(START, proposal)
    lab.paper.state = store.read()
    lab.inbox.update(proposal.request_id, "reserved", reserved["trial_id"])
    default = intent.model_copy(update={"allow_engine_work_recovery": False})
    before, events = store.read(), store.export(0, 1000)
    with pytest.raises(finance.AdmissionWait):
        lab.launch_existing(proposal.request_id, default)
    assert store.read() == before and store.export(0, 1000) == events
    assert lab.launch_existing(proposal.request_id, intent)["status"] == "funded"
    assert store.read()["autonomous_lab"]["budget"]["trials"] == 1
    assert store.read()["autonomous_lab"]["budget"]["steps"] == 1
    assert store.reconcile()["balanced"]


@pytest.mark.parametrize(
    "fault",
    [
        "policy",
        "proposal",
        "paused",
        "entries_paused",
        "paper_stale",
        "inputs_missing",
        "hourly_budget",
        "daily_budget",
        "owner_missing",
    ],
)
def test_native_refusals_leave_original_financial_state_unchanged(
    pg_store, tmp_path, monkeypatch, fault
):
    store, _ = pg_store
    lab, proposal, intent, _ = setup_launch(store, tmp_path, monkeypatch)
    if fault in {"policy", "proposal"}:
        key = "expected_policy_sha256" if fault == "policy" else "expected_proposal_sha256"
        intent = intent.model_copy(update={key: "f" * 64})
    elif fault in {"paused", "entries_paused", "hourly_budget", "daily_budget", "paper_stale"}:

        def change(engine):
            if fault == "paused":
                engine.state["paused"] = True
            elif fault == "entries_paused":
                engine.state["autonomous_lab"]["entries_paused"] = True
            elif fault == "hourly_budget":
                engine.state["autonomous_lab"]["budget"]["steps"] = 120
            elif fault == "daily_budget":
                engine.state["autonomous_lab"]["budget"]["trials"] = 8
            else:
                engine.state["last_tick"] = START - 11

        lab.paper._transact_state(START, change)
    elif fault == "inputs_missing":
        lab.paper.books = {}
    elif fault == "owner_missing":
        store.owner = False
    before, events = store.read(), store.export(0, 1000)
    with pytest.raises((ValueError, RuntimeError)):
        lab.launch_existing(proposal.request_id, intent)
    assert store.read() == before and store.export(0, 1000) == events
    assert lab.inbox.get(proposal.request_id)["status"] == "evaluated"
    store.owner = True


def test_lost_financial_acknowledgment_get_reopens_actual_pair_and_exact_retry(
    pg_store, tmp_path, monkeypatch
):
    store, _ = pg_store
    lab, proposal, intent, _ = setup_launch(store, tmp_path, monkeypatch)
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    original = store.transact

    def lost_ack(now, work):
        original(now, work)
        raise psycopg.OperationalError("Synthetic lost acknowledgment after native commit")

    with TestClient(app) as client:
        client.app.state.lab = SimpleNamespace(autonomous=lab)
        route = "/api/autonomous/proposals/" + proposal.request_id
        assert client.post(route + "/launch", json=intent.model_dump()).status_code == 403
        assert (
            client.post(
                route + "/launch",
                json=intent.model_dump(),
                headers={**HEADERS, "Origin": "http://wrong.invalid"},
            ).status_code
            == 403
        )
        with monkeypatch.context() as patch:
            patch.setattr(store, "transact", lost_ack)
            response = client.post(route + "/launch", json=intent.model_dump(), headers=HEADERS)
        assert response.status_code == 503
        reopened = client.get(route).json()
        assert reopened["status"] == "evaluated"  # Registry acknowledgment was not fabricated.
        assert reopened["financial_outcome"]["funding_complete"]
        retained = store.export(0, 1000)
        assert (
            client.post(route + "/launch", json=intent.model_dump(), headers=HEADERS).json()[
                "status"
            ]
            == "already_funded"
        )
        assert store.export(0, 1000) == retained and store.reconcile()["balanced"]
        assert client.get(route).json()["status"] == "funded"


def test_actual_api_wiring_retains_existing_research_owner_vetoes_for_latency_exception(
    pg_store, tmp_path, monkeypatch
):
    store, dsn = pg_store
    lab, proposal, intent, owner = setup_launch(store, tmp_path, monkeypatch)
    lab.paper.operator_launch_admission = owner.operator_launch_admission
    database = tmp_path / "disposable-paper-database.json"
    database.write_text(json.dumps({"dsn": dsn}))
    monkeypatch.setattr("trading.api.PaperStore", lambda *args, **kwargs: store)
    monkeypatch.setattr("trading.api.PaperRuntime", lambda *args, **kwargs: lab.paper)
    monkeypatch.setattr("trading.api.policy", lambda account: "synthetic-spot-only")
    app = create_app(
        Settings(), tmp_path / "monitor.sqlite", paper_database=database, background=False
    )
    with TestClient(app) as client:
        assert client.app.state.lab.autonomous is not lab
        client.app.state.replay.busy = True
        before, events = store.read(), store.export(0, 1000)
        route = "/api/autonomous/proposals/" + proposal.request_id + "/launch"
        response = client.post(route, json=intent.model_dump(), headers=HEADERS)
        assert response.status_code == 409
        assert "replay_worker_active" in response.json()["detail"]
        assert store.read() == before and store.export(0, 1000) == events
        client.app.state.replay.busy = False
        client.app.state.lab.child = SimpleNamespace()  # Owned-work marker; no child is launched.
        response = client.post(route, json=intent.model_dump(), headers=HEADERS)
        assert response.status_code == 409
        assert "numerical_worker_active" in response.json()["detail"]
        assert store.read() == before and store.export(0, 1000) == events
        client.app.state.lab.child = None
        assert (
            client.post(route, json=intent.model_dump(), headers=HEADERS).json()["status"]
            == "funded"
        )
        assert store.reconcile()["balanced"]


def test_lost_inbox_ack_restart_and_concurrent_same_id_never_refund(
    pg_store, tmp_path, monkeypatch
):
    store, dsn = pg_store
    lab, proposal, intent, _ = setup_launch(store, tmp_path, monkeypatch)
    update = lab.inbox.update
    with monkeypatch.context() as patch:
        patch.setattr(
            lab.inbox,
            "update",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("Synthetic inbox ack failure")),
        )
        with pytest.raises(OSError):
            lab.launch_existing(proposal.request_id, intent)
    assert store.lab_proposal_outcome(proposal.request_id)["funding_complete"]
    before = store.export(0, 1000)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _: lab.launch_existing(proposal.request_id, intent), range(2))
        )
    assert all(row["status"] == "already_funded" for row in results)
    assert store.export(0, 1000) == before
    assert lab.inbox.update == update
    store.close()
    reopened = PaperStore(dsn, owner=True)
    try:
        assert reopened.lab_proposal_outcome(proposal.request_id)["funding_complete"]
        assert reopened.export(0, 1000) == before and reopened.reconcile()["balanced"]
    finally:
        reopened.close()
