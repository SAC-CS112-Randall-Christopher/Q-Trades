import copy
import time

import pytest
from test_numerical_candidates import fixture_artifact
from test_paper_engine import START
from test_paper_store import pg_store as _pg_store

from trading import autonomous_finance as finance
from trading.autonomous_spec import LabPolicy, LabProposal, RuleSpec
from trading.experiment_registry import fingerprint
from trading.paper_challengers import admit
from trading.paper_economics import new_benchmark
from trading.paper_engine import PaperEngine, initial_state
from trading.paper_learning import (
    admit_rule,
    comparison,
    designate,
    drift,
    matched_control,
    retain_report,
    rollback,
    rule_offer,
    snapshot,
)

pg_store = _pg_store


def candidate_state():
    engine = PaperEngine(initial_state(START), START)
    engine.seed()
    artifact = fixture_artifact()
    name = admit(engine, "learning-fit", artifact, "100", "0")["account"]
    control = matched_control(engine, name)["account"]
    for a in engine.state["accounts"].values():
        a.update(valuation_fresh=True, valuation_at=START)
    return engine, name, control


def windows(engine, name, control, gain=0.003, days=28):
    # Constructed accounting contract, never an observed forward result or claim.
    rows = []
    for i in range(days * 6):
        a, b = engine.state["accounts"][name], engine.state["accounts"][control]
        common = {
            "eligible": True,
            "cohort": "Matched fixture",
            "execution_cost": "0.02",
            "start_equity": "100",
            "max_drawdown": "0.01",
            "benchmark_symbols": ["BTCUSD"],
            "cash_total_return": "0",
            "exposure_total_return": "0.001",
        }
        first = START + 60 + i * 14400
        rows.append(
            {
                "start": first,
                "end": first + 14400,
                "complete": True,
                "scores": {
                    name: dict(common, total_return=str(gain), strategy_version=a["version"]),
                    control: dict(common, total_return="0", strategy_version=b["version"]),
                },
            }
        )
    return rows


def test_matched_control_is_cash_isolated_idempotent_and_uses_declared_universe():
    engine, name, control = candidate_state()
    before = copy.deepcopy(engine.state)
    events = copy.deepcopy(engine.events)
    assert matched_control(engine, name)["status"] == "already_applied"
    assert engine.state == before and engine.events == events
    assert engine.state["accounts"][control]["symbols"] == ["BTCUSD"]
    assert new_benchmark("100", "paper-rest-ioc-v1", START, ("BTCUSD",))["legs"].keys() == {
        "BTCUSD"
    }
    assert engine.state["accounts"][control]["cash"] == "100"
    engine.assert_invariants()


def rule_fixture(outcome="low_information"):
    """Frozen source contract only; the shaped mature score is synthetic evidence."""
    from trading.paper_economics import sample

    engine = PaperEngine(initial_state(START), START)
    engine.seed()
    policy = LabPolicy(request_id="qualification-fixture-policy", daily_operating_usd="0.25")
    finance.start(engine, policy)
    proposal = LabProposal(
        request_id="qualification-fixture-proposal",
        policy_id=policy.request_id,
        kind="independent",
        strategy=RuleSpec(
            version="reviewed-lab-rules-v4", family="breakout-retest-v1", holding_horizon="medium"
        ),
        reference=RuleSpec(
            version="reviewed-lab-rules-v4", family="cost-breakout-v1", holding_horizon="medium"
        ),
        mechanism="Retained fixed-method source contract fixture",
        question="Does this frozen mechanism justify a prospective matched comparison?",
        evidence_bundle_sha256="a" * 64,
    )
    trial_id = finance.reserve(engine, proposal)["trial_id"]
    saved = copy.deepcopy(engine.state["autonomous_lab"]["trials"][trial_id])
    finance.fund(engine, trial_id)
    engine.now += 86400
    for a in engine.state["accounts"].values():
        a.update(valuation_fresh=True, valuation_at=engine.now)
    score = {
        "trial_id": trial_id,
        "proposal_id": proposal.request_id,
        "outcome": outcome,
        "available_at": engine.now,
        "candidate_sample": sample(engine.state["accounts"][saved["candidate"]], engine.now),
        "reference_sample": sample(engine.state["accounts"][saved["reference"]], engine.now),
    }
    engine.state["autonomous_lab"]["trials"][trial_id]["score"] = score
    receipt = {
        "id": 17,
        "at": START,
        "body": saved,
        "decisions": [{"kind": "lab_trial_scored", "at": engine.now, "body": score}],
        "environment": "paper",
    }
    return engine, receipt


@pytest.mark.parametrize(
    "outcome", ["promising", "economically_unsuccessful", "inconclusive", "low_information"]
)
def test_rule_source_funds_a_separate_exact_pair_without_changing_originals(outcome):
    engine, receipt = rule_fixture(outcome)
    original = copy.deepcopy(engine.state["accounts"])
    offer = rule_offer(engine.state, receipt)
    before_slots = finance.slots(engine.state)["used"]
    result = admit_rule(
        engine,
        receipt,
        offer["rule_sha256"],
        offer["role_version"],
        offer["incumbent_configuration_sha256"],
        offer["implementation_sha256"],
    )
    a, b = (engine.state["accounts"][result[k]] for k in ("account", "control"))
    assert {n: engine.state["accounts"][n] for n in original} == original
    assert a["rule_spec"] == receipt["body"]["contract"]["proposal"]["strategy"]
    assert "numerical_artifact" not in a
    assert (
        a["cash"] == b["cash"] == "100"
        and a["operating_daily_usd"] == b["operating_daily_usd"] == "0.25"
    )
    assert b["version"] == original["primary"]["version"] and b["risk_policy"] == a["risk_policy"]
    assert finance.slots(engine.state)["used"] == before_slots + 2
    before = copy.deepcopy(engine.state), copy.deepcopy(engine.events)
    assert (
        admit_rule(
            engine,
            receipt,
            offer["rule_sha256"],
            offer["role_version"],
            offer["incumbent_configuration_sha256"],
            offer["implementation_sha256"],
        )["status"]
        == "already_applied"
    )
    assert (engine.state, engine.events) == before
    assert result["account"] in [a["account"] for a in snapshot(engine.state)["accounts"]]
    # Autonomous retirement never owns the new pair; its original source remains linked.
    with pytest.raises(ValueError, match="Protected/original"):
        finance.retire_account(engine, result["account"], "must refuse")
    assert a["qualification_source"]["score_sha256"] == fingerprint(receipt["decisions"][0]["body"])
    engine.assert_invariants()


@pytest.mark.parametrize(
    "change",
    [
        "rule",
        "incumbent",
        "capacity",
        "pause",
        "data_blocked",
        "risk_stopped",
        "source_version",
        "environment",
    ],
)
def test_rule_qualification_refusals_preserve_all_funding_and_history(change):
    engine, receipt = rule_fixture()
    offer = rule_offer(engine.state, receipt)
    rule_sha, incumbent_sha = offer["rule_sha256"], offer["incumbent_configuration_sha256"]
    if change == "rule":
        rule_sha = "b" * 64
    elif change == "incumbent":
        engine.state["accounts"]["primary"]["version"] = "responsive-v1"
    elif change == "capacity":
        engine.state["autonomous_lab"]["policy"]["slots"] = finance.slots(engine.state)["used"] + 1
    elif change == "pause":
        engine.state["paused"] = True
    elif change == "source_version":
        receipt["decisions"][0]["body"]["candidate_sample"]["strategy_version"] = "different"
    elif change == "environment":
        receipt["environment"] = "live"
    else:
        receipt["decisions"][0]["body"]["outcome"] = change
    before = copy.deepcopy(engine.state), copy.deepcopy(engine.events)
    with pytest.raises(ValueError):
        admit_rule(
            engine,
            receipt,
            rule_sha,
            offer["role_version"],
            incumbent_sha,
            offer["implementation_sha256"],
        )
    assert (engine.state, engine.events) == before


def test_rule_qualification_policy_stays_prospective_and_reversible():
    engine, receipt = rule_fixture()
    offer = rule_offer(engine.state, receipt)
    result = admit_rule(
        engine,
        receipt,
        offer["rule_sha256"],
        offer["role_version"],
        offer["incumbent_configuration_sha256"],
        offer["implementation_sha256"],
    )
    name, control = result["account"], result["control"]
    for a in engine.state["accounts"].values():
        a.update(valuation_fresh=True)
    data = windows(engine, name, control)
    # Shift constructed windows after the actual new admission, never recycling exploration.
    for row in data:
        row["start"] += 86400
        row["end"] += 86400
    now = START + 31 * 86400
    engine.state["evidence_kind"] = "synthetic_qa"
    assert comparison(engine.state, name, data, now, START)["decision"] == "no_promotion"
    assert comparison(engine.state, name, data[:6], now, START)["decision"] == "no_promotion"
    engine.state["evidence_kind"] = "observed_public_feed"  # Label for policy contract only.
    report = comparison(engine.state, name, data, now, START)
    assert report["decision"] == "eligible_for_paper_designation", report["reasons"]
    assert report["artifact_sha256"] is None and report["rule_sha256"] == offer["rule_sha256"]
    frozen = retain_report(engine, "rule-qualification-policy-report", report)
    engine.now = now
    accounts = copy.deepcopy(engine.state["accounts"])
    assert designate(engine, frozen["request_id"], frozen["sha256"], 0)["incumbent"] == name
    assert rollback(engine, 1)["incumbent"] == "primary"
    assert engine.state["accounts"] == accounts


@pytest.mark.parametrize("changed", ["incumbent", "control", "rule"])
def test_designation_rechecks_all_frozen_strategy_and_reference_configurations(changed):
    engine, name, control = candidate_state()
    report = retain_report(
        engine,
        "all-configurations-report",
        comparison(engine.state, name, windows(engine, name, control), START + 30 * 86400, START),
    )
    target = "primary" if changed == "incumbent" else control if changed == "control" else name
    engine.state["accounts"][target]["version"] = "different-version"
    engine.now = report["created_at"]
    with pytest.raises(ValueError, match="configuration|incumbent"):
        designate(engine, report["request_id"], report["sha256"], 0)
    assert engine.state["learning"]["incumbent"] == "primary"


def test_insufficient_synthetic_reused_negative_and_exceptional_data_never_promotes():
    engine, name, control = candidate_state()
    report = comparison(engine.state, name, [], START + 60, START)
    assert report["decision"] == "no_promotion" and report["daily_blocks"] == []
    engine.state["evidence_kind"] = "synthetic_qa"
    data = windows(engine, name, control)
    assert (
        comparison(engine.state, name, data, START + 30 * 86400, START)["decision"]
        == "no_promotion"
    )
    engine.state["evidence_kind"] = "observed_public_feed"  # Constructed contract only.
    reused = comparison(engine.state, name, data, START + 30 * 86400, START + 30 * 86400)
    assert reused["matched_windows"] == 0 and reused["decision"] == "no_promotion"
    negative = comparison(
        engine.state, name, windows(engine, name, control, gain=-0.002), START + 30 * 86400, START
    )
    assert negative["decision"] == "no_promotion" and any(
        "not positive" in r for r in negative["reasons"]
    )
    exceptional = windows(engine, name, control, gain=0)
    for w in exceptional[:6]:
        w["scores"][name]["total_return"] = "1"
    r = comparison(engine.state, name, exceptional, START + 30 * 86400, START)
    assert any("exceptional" in reason for reason in r["reasons"])
    assert r["attribution"]["regime"].startswith("Unknown")


def test_positive_contract_requires_explicit_approval_and_rollback_preserves_all_accounts():
    engine, name, control = candidate_state()
    data = windows(engine, name, control)
    engine.now = START + 30 * 86400
    report = comparison(engine.state, name, data, engine.now, START)
    assert report["decision"] == "eligible_for_paper_designation", report["reasons"]
    frozen = retain_report(engine, "learning-report-0001", report)
    accounts = copy.deepcopy(engine.state["accounts"])
    assert engine.state["learning"]["incumbent"] == "primary"
    assert designate(engine, frozen["request_id"], frozen["sha256"], 0)["incumbent"] == name
    assert (
        designate(engine, frozen["request_id"], frozen["sha256"], 0)["status"] == "already_applied"
    )
    assert engine.state["accounts"] == accounts
    assert rollback(engine, 1)["incumbent"] == "primary"
    assert rollback(engine, 1)["status"] == "already_applied"
    assert engine.state["accounts"] == accounts
    assert engine.state["learning"]["promotions"][0]["rolled_back"]
    reference = engine.state["learning"]["reports"][frozen["request_id"]]
    assert reference["sha256"] == frozen["sha256"] and "daily_blocks" not in reference
    assert reference["daily_block_count"] == len(frozen["daily_blocks"])
    assert (
        next(e["body"] for e in engine.events if e["kind"] == "learning_report_retained") == frozen
    )
    engine.assert_invariants()


def test_drift_expired_report_version_and_unmatched_instrument_fail_closed():
    engine, name, control = candidate_state()
    data = windows(engine, name, control)
    now = START + 30 * 86400
    report = retain_report(
        engine, "learning-report-0002", comparison(engine.state, name, data, now, START)
    )
    engine.now = now + 86401
    with pytest.raises(ValueError, match="expired"):
        designate(engine, report["request_id"], report["sha256"], 0)
    engine.now = now
    engine.state["accounts"][name]["economics_settings_version"] = 1
    assert drift(engine.state["accounts"][name])
    with pytest.raises(ValueError, match="changed"):
        designate(engine, report["request_id"], report["sha256"], 0)
    engine.state["accounts"][name].pop("economics_settings_version")
    data[0]["scores"][name]["benchmark_symbols"] = ["BTCUSD", "ETHUSD"]
    r = comparison(engine.state, name, data, now, START)
    assert any("instrument" in w["reason"] for w in r["discarded_windows"])
    assert r["decision"] == "no_promotion"
    engine.state["accounts"][name]["numerical_artifact"]["weight"] += 1
    assert "invalid" in drift(engine.state["accounts"][name])[0]


def test_report_journal_restart_and_loss_preservation(pg_store):
    store, dsn = pg_store
    result = {}

    def setup(engine):
        engine.state["evidence_kind"] = "synthetic_qa"
        name = admit(engine, "database-learning", fixture_artifact(), "100", "0")["account"]
        matched_control(engine, name)
        result["candidate"] = name

    store.transact(time.time(), setup)
    report = comparison(store.read(), result["candidate"], [], time.time(), 0)
    store.transact(time.time(), lambda e: retain_report(e, "durable-report-0001", report))
    before = store.read()
    with pytest.raises(ValueError, match="does not permit"):
        store.transact(
            time.time(),
            lambda e: designate(
                e,
                "durable-report-0001",
                before["learning"]["reports"]["durable-report-0001"]["sha256"],
                0,
            ),
        )
    assert store.read() == before and store.reconcile()["balanced"]
    events = store.export(0, 1000)["records"]
    assert sum(e["kind"] == "learning_report_retained" for e in events) == 1
    assert sum(e["kind"] == "matched_control_funded" for e in events) == 1
    assert fingerprint(store.read()["accounts"]) == fingerprint(before["accounts"])


def test_normal_api_retains_no_promotion_export_and_consumption(pg_store, tmp_path):
    from fastapi.testclient import TestClient

    from trading.api import create_app
    from trading.config import Settings
    from trading.paper_runtime import PaperRuntime

    store, _ = pg_store
    state = {}

    def setup(e):
        state.update(admit(e, "api-learning", fixture_artifact(), "100", "0"))
        e.state.update(last_tick=e.now, evidence_kind="synthetic_qa")

    store.transact(time.time(), setup)
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    with TestClient(app) as client:
        runtime = PaperRuntime(store, None)
        runtime.running = True
        app.state.paper = runtime
        name = state["account"]
        header = {"X-Local-Operator": "1"}
        assert client.post("/api/paper/learning/control/" + name).status_code == 403
        assert client.post("/api/paper/learning/control/" + name, headers=header).status_code == 200
        body = {"request_id": "api-learning-report-0001", "candidate": name}
        result = client.post("/api/paper/learning/reports", json=body, headers=header)
        assert result.status_code == 200, result.text
        report = result.json()
        assert report["decision"] == "no_promotion" and not report["daily_blocks"]
        assert (
            client.post("/api/paper/learning/reports", json=body, headers=header).json()["sha256"]
            == report["sha256"]
        )
        exported = client.get("/api/paper/learning/reports/" + body["request_id"]).json()
        assert exported["sha256"] == report["sha256"]
        assert app.state.lab.registry.snapshot()["protected_through"] >= report["created_at"]
        assert (
            client.post(
                "/api/paper/learning/role",
                headers=header,
                json={
                    "action": "designate",
                    "expected_version": 0,
                    "report_id": body["request_id"],
                    "report_sha256": report["sha256"],
                },
            ).status_code
            == 409
        )
        assert store.reconcile()["balanced"]


def test_numerical_incumbent_control_is_an_exact_frozen_copy():
    engine, name, control = candidate_state()
    engine.now = START + 30 * 86400
    report = retain_report(
        engine,
        "numerical-role-0001",
        comparison(engine.state, name, windows(engine, name, control), engine.now, START),
    )
    designate(engine, report["request_id"], report["sha256"], 0)
    second = admit(
        engine, "another-frozen-fit", fixture_artifact("volatility_breakout"), "100", "0"
    )["account"]
    matched = matched_control(engine, second)["account"]
    assert (
        engine.state["accounts"][matched]["numerical_artifact"]
        == engine.state["accounts"][name]["numerical_artifact"]
    )
    assert engine.state["accounts"][matched]["version"] == engine.state["accounts"][name]["version"]
    assert engine.state["accounts"][matched]["admitted_at"] == engine.now
    engine.assert_invariants()


def test_native_retired_rule_source_api_recovers_same_funding_after_lost_ack(
    pg_store, tmp_path, monkeypatch
):
    import psycopg
    from fastapi.testclient import TestClient
    from test_autonomous_lab import admit as admit_trial
    from test_autonomous_lab import close_window, make_lab

    from trading.api import create_app
    from trading.config import Settings

    store, _ = pg_store
    directory = tmp_path / "native"
    directory.mkdir()
    lab = make_lab(store, directory, daily_operating_usd="0.25", horizon_seconds=3600)
    trial = admit_trial(lab, START)
    score = close_window(lab, trial, "economically_unsuccessful")
    clock = score["available_at"] + 2
    monkeypatch.setattr(time, "time", lambda: clock)
    assert store.archived_account(trial["candidate"])
    original = copy.deepcopy(store.export(0, 10000)["records"])
    app = create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    try:
        with TestClient(app) as client:
            app.state.paper = lab.paper
            app.state.lab.autonomous = lab
            source_url = "/api/autonomous/trials/" + trial["id"]
            original_view = client.get(source_url).json()
            offer = original_view["qualification_offer"]
            assert offer["available"] and not offer["already_admitted"]
            body = {
                "environment": "paper",
                "trial_id": trial["id"],
                "rule_sha256": offer["rule_sha256"],
                "expected_role_version": offer["role_version"],
                "incumbent_configuration_sha256": offer["incumbent_configuration_sha256"],
                "implementation_sha256": offer["implementation_sha256"],
                "approve_hypothetical_funding": True,
            }
            header = {"X-Local-Operator": "1"}
            assert client.post("/api/paper/learning/rules", json=body).status_code == 403
            assert (
                client.post(
                    "/api/paper/learning/rules", json=body | {"environment": "live"}, headers=header
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/paper/learning/rules",
                    json=body | {"approve_hypothetical_funding": False},
                    headers=header,
                ).status_code
                == 422
            )
            saved = lab.paper.qualify_rule

            def lose_ack(*args):
                saved(*args)
                raise psycopg.OperationalError("Synthetic acknowledgment lost after native commit")

            monkeypatch.setattr(lab.paper, "qualify_rule", lose_ack)
            assert (
                client.post("/api/paper/learning/rules", json=body, headers=header).status_code
                == 503
            )
            confirmed = client.get(source_url).json()["qualification_offer"]
            assert confirmed["already_admitted"]
            monkeypatch.setattr(lab.paper, "qualify_rule", saved)
            retried = client.post("/api/paper/learning/rules", json=body, headers=header)
            assert retried.status_code == 200 and retried.json()["status"] == "already_applied", (
                retried.text
            )
            name, control = retried.json()["account"], retried.json()["control"]
            current = store.read()
            assert (
                current["accounts"][name]["rule_spec"] == trial["contract"]["proposal"]["strategy"]
            )
            assert (
                current["accounts"][control]["version"] == current["accounts"]["primary"]["version"]
            )
            assert (
                current["accounts"][name]["cash"] == current["accounts"][control]["cash"] == "100"
            )
            records = store.export(0, 10000)["records"]
            assert records[: len(original)] == original
            assert sum(row["kind"] == "forward_rule_account_funded" for row in records) == 1
            assert sum(row["kind"] == "matched_control_funded" for row in records) == 1
            assert store.reconcile()["balanced"]
            report = client.post(
                "/api/paper/learning/reports",
                json={"request_id": "native-rule-source-report", "candidate": name},
                headers=header,
            ).json()
            assert report["decision"] == "no_promotion" and not report["daily_blocks"]
            assert (
                report["artifact_sha256"] is None and report["rule_sha256"] == body["rule_sha256"]
            )
            # Ambiguous original events refuse exact lookup and cannot become a source.
            store.transact(clock, lambda e: e.emit("lab_trial_scored", "system", score))
            assert client.get(source_url).status_code == 404
    finally:
        lab.registry.close()


def test_unavailable_implementation_does_not_prevent_financial_management(monkeypatch):
    from pathlib import Path

    from test_paper_runtime import ReadOnlyStub

    from trading.paper_engine import entry_reason
    from trading.paper_learning import implementation_identity
    from trading.paper_runtime import PaperRuntime

    implementation_identity.cache_clear()
    reads = []

    def unavailable(path):
        reads.append(path)
        raise OSError("Synthetic optional provenance read failure")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_bytes", unavailable)
            runtime = PaperRuntime(ReadOnlyStub(), None)
            assert runtime.state["accounts"]["primary"]["cash"] == "100"
            assert implementation_identity() is None and len(reads) == 1
            a = copy.deepcopy(runtime.state["accounts"]["primary"])
            a.update(campaign_id="forward-research", strategy_implementation_sha256="a" * 64)
            assert "implementation" in entry_reason(a, False, time.time())
            assert len(reads) == 1
    finally:
        implementation_identity.cache_clear()


def test_changed_implementation_refuses_new_entries_and_designation_only(monkeypatch):
    from trading.paper_engine import entry_reason

    engine, name, control = candidate_state()
    now = START + 30 * 86400
    report = retain_report(
        engine,
        "changed-implementation-report",
        comparison(engine.state, name, windows(engine, name, control), now, START),
    )
    monkeypatch.setattr("trading.paper_learning.implementation_identity", lambda: "f" * 64)
    assert "implementation" in entry_reason(engine.state["accounts"][name], False, START)
    assert entry_reason(engine.state["accounts"]["primary"], False, START) is None
    engine.now = now
    with pytest.raises(ValueError, match="frozen matched incumbent changed"):
        designate(engine, report["request_id"], report["sha256"], 0)
