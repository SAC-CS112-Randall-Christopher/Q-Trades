"""Prospective rule changes preserve accounting and immutable old experiments."""

import time
from copy import deepcopy
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_paper_engine import START, frame, study
from test_paper_store import pg_store as _pg_store
from test_redesign_strategy import fixture as strategy_fixture
from test_redesign_strategy import observed_at

from trading.account_redesign import StrategyChange, change_strategy
from trading.api import create_app
from trading.autonomous_spec import LabPolicy, LabProposal, RuleSpec, contract, rule_feature
from trading.config import Settings
from trading.execution_profiles import LEGACY_EXECUTION, PUBLIC_EXECUTION
from trading.experiment_registry import fingerprint
from trading.financial_readback import FinancialReadback
from trading.paper_campaigns import control_account
from trading.paper_engine import PaperEngine, initial_state
from trading.paper_runtime import PaperRuntime
from trading.paper_store import PaperStore
from trading.redesign_strategy import STRATEGIES
from trading.tiered_runtime import TieredPaperRuntime

qa_store = _pg_store


@pytest.fixture
def native_store(qa_store):
    store, dsn = qa_store
    store.transact(START, lambda engine: engine.tick({}, {}))
    return store, dsn


def flat_state(now):
    state = initial_state(now)
    PaperEngine(state, now).tick({}, {})
    return state


def change(
    version="cost-breakout-v1",
    expected="breakout-v1",
    control=0,
    request="test-redesign-request-001",
):
    return StrategyChange(
        request_id=request,
        strategy=version,
        expected_strategy=expected,
        expected_control_version=control,
    )


@pytest.mark.parametrize("version", STRATEGIES)
def test_change_only_versions_the_flat_account_and_retains_all_financial_state(version):
    state = flat_state(START)
    before = deepcopy(state)
    engine = PaperEngine(state, START + 1)
    result = change_strategy(engine, "primary", change(version))
    after = deepcopy(state)
    for key in ("version", "control_version", "last_strategy_change"):
        after["accounts"]["primary"].pop(key, None)
        before["accounts"]["primary"].pop(key, None)
    assert after == before
    assert result["from"] == "breakout-v1" and result["to"] == version
    assert engine.events[0]["kind"] == "account_strategy_changed"
    assert not engine.events[0]["lines"]
    assert state["accounts"]["primary"]["closed"] == state["accounts"]["primary"]["wins"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("positions", {"BTCUSD": {}}),
        ("pending", {"BTCUSD": {}}),
        ("fault", {"reason": "unresolved"}),
        ("execution_uncertain", True),
        ("valuation_fresh", False),
    ],
)
def test_unresolved_account_cannot_switch(field, value):
    state = flat_state(START)
    state["accounts"]["primary"][field] = value
    before = deepcopy(state)
    engine = PaperEngine(state, START + 1)
    with pytest.raises(ValueError):
        change_strategy(engine, "primary", change())
    assert state == before and not engine.events


def test_controls_unknown_presets_and_frozen_lab_accounts_are_protected():
    state = flat_state(START)
    engine = PaperEngine(state, START)
    for spec in (change(expected="different-old-version"), change(control=1)):
        with pytest.raises(ValueError, match="changed"):
            change_strategy(engine, "primary", spec)
    with pytest.raises(ValueError, match="contracts stay frozen"):
        change_strategy(engine, "some-lab-account", change())
    with pytest.raises(ValidationError):
        change("invented-profit-maker")
    with pytest.raises(ValidationError):
        StrategyChange(**change().model_dump(), funding="1000")
    assert not engine.events


def test_existing_pauses_cooldowns_risk_costs_and_losing_history_survive():
    state = flat_state(START)
    a = state["accounts"]["primary"]
    a.update(
        cash="80",
        equity="80",
        realized="-20",
        fees="18",
        closed=200,
        wins=3,
        entries_paused=True,
        drawdown_pause=True,
        daily_pause=True,
    )
    a["cooldowns"] = {"BTCUSD": START + 600}
    original = deepcopy(a)
    change_strategy(PaperEngine(state, START + 1), "primary", change())
    assert all(a[key] == value for key, value in original.items() if key != "version")
    assert a["last_strategy_change"]["baseline"]["closed"] == 200


def test_legacy_review_cannot_auto_replace_operator_rule_or_claim_promotion():
    state = flat_state(START)
    change_strategy(PaperEngine(state, START), "primary", change())
    engine = PaperEngine(state, state["next_review"])
    engine.review()
    assert state["accounts"]["primary"]["version"] == "cost-breakout-v1"
    assert state["promotion_count"] == 0


def test_current_fee_spread_hurdle_refuses_tiny_movement_and_retains_cost_assumptions():
    state = flat_state(START)
    engine = PaperEngine(state, START)
    change_strategy(engine, "primary", change())
    engine = PaperEngine(state, START + 1)
    a = state["accounts"]["primary"]
    feature = deepcopy(study()["BTCUSD"]["breakout-v1"])
    feature.update(
        version=a["version"],
        redesign_version="original-account-redesign-v1",
        atr="0.01",
        input_available_at=START + 0.5,
    )
    reason = engine.enter("primary", a, "BTCUSD", frame(START + 1), feature)
    assert "modeled round-trip costs" in reason and not a["pending"]
    assert D(feature["modeled_cost_hurdle_bps"]) >= 24
    assert a["execution_profile"] == "paper-rest-ioc-v1"
    feature["atr"] = "1"
    assert engine.enter("primary", a, "BTCUSD", frame(START + 1), feature).startswith(
        "Paper entry reserved"
    )
    assert a["pending"]["BTCUSD"]["reason"] == STRATEGIES[a["version"]]


@pytest.mark.parametrize("available", [None, START - 1, START, START + 2, True, float("nan")])
def test_preselection_missing_future_and_invalid_bar_availability_cannot_start_entry(available):
    state = flat_state(START)
    change_strategy(PaperEngine(state, START), "primary", change())
    a = state["accounts"]["primary"]
    feature = {"eligible": True, "bar_open_ms": 1, "atr": "1", "input_available_at": available}
    reason = PaperEngine(state, START + 1).enter("primary", a, "BTCUSD", frame(START + 1), feature)
    assert "subsequent complete five-minute" in reason and not a["pending"]


def test_same_bank_feature_annotations_are_isolated_by_account_and_execution_profile():
    state = flat_state(START)
    for name in ("primary", "breakout-v1"):
        change_strategy(PaperEngine(state, START), name, change(request=f"change-{name}-0001"))
    state["accounts"]["breakout-v1"]["execution_profile"] = PUBLIC_EXECUTION
    feature = {
        "version": "cost-breakout-v1",
        "redesign_version": "original-account-redesign-v1",
        "eligible": True,
        "bar_open_ms": 1,
        "atr": "1",
        "reason": "fixed signal",
        "input_available_at": START + 0.5,
    }
    studies = {"BTCUSD": {"cost-breakout-v1": feature}}
    before = deepcopy(studies)
    engine = PaperEngine(state, START + 1)
    engine.tick({"BTCUSD": frame(START + 1)}, studies)
    assert studies == before
    rows = {
        event["account"]: event["body"]["features"]
        for event in engine.events
        if event["kind"] == "decision" and event["account"] in {"primary", "breakout-v1"}
    }
    assert D(rows["primary"]["modeled_cost_hurdle_bps"]) > D(
        rows["breakout-v1"]["modeled_cost_hurdle_bps"]
    )
    assert state["accounts"]["primary"]["execution_profile"] == LEGACY_EXECUTION


def test_redesigned_original_processing_recovery_keeps_rule_financials_and_pause():
    state = flat_state(START)
    change_strategy(PaperEngine(state, START), "primary", change())
    a = state["accounts"]["primary"]
    a.update(fault={"reason": "synthetic processing failure"}, entries_paused=True)
    preserved = {
        key: deepcopy(a[key])
        for key in ("cash", "funding", "fees", "closed", "wins", "version", "entries_paused")
    }
    control_account(PaperEngine(state, START + 1), "primary", "recover", 1, {})
    assert "fault" not in state["accounts"]["primary"]
    assert all(state["accounts"]["primary"][key] == value for key, value in preserved.items())
    state["accounts"]["primary"].update(version="unknown-new-rule", fault={"reason": "unresolved"})
    with pytest.raises(ValueError, match="strategy needs repair"):
        control_account(PaperEngine(state, START + 2), "primary", "recover", 2, {})


def test_mixed_strategy_economics_window_is_not_ranked_and_prior_windows_survive(monkeypatch):
    from test_paper_economics import frames, marked_state

    from trading import paper_economics as eco

    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = marked_state()
    for offset in range(1, 11):
        PaperEngine(state, START + offset).tick(frames(START + offset, offset + 1), {})
    historical = deepcopy(state["economics"]["completed"])
    assert historical
    change_strategy(PaperEngine(state, START + 11), "primary", change())
    for offset in range(11, 21):
        PaperEngine(state, START + offset).tick(frames(START + offset, offset + 1), {})
    assert state["economics"]["completed"][:-1] == historical
    latest = state["economics"]["completed"][-1]["scores"]["primary"]
    assert not latest["eligible"]
    assert "Cost, risk or strategy settings changed inside the window" in latest["reasons"]
    assert state["accounts"]["primary"]["closed"] == 0
    assert state["accounts"]["primary"]["funding"] == "100"


def test_v4_uses_retained_public_prefix_and_requires_poststartup_complete_bar():
    bars = strategy_fixture("compression-breakout-v1")
    now = observed_at(bars)
    spec = RuleSpec(
        version="reviewed-lab-rules-v4", family="compression-breakout-v1", holding_horizon="medium"
    )
    state = flat_state(now)
    a = state["accounts"]["primary"]
    a.update(version="lab-rule-" + fingerprint(spec.model_dump())[:24], rule_spec=spec.model_dump())
    paper = PaperRuntime.__new__(PaperRuntime)
    paper.state, paper.history = state, {"BTCUSD": bars}
    paper.ready_at, paper.books = bars[-1].close_ms / 1000, {}
    paper._lab_features = {}
    study_before = {}
    paper.numerical_study(now, study_before)
    assert not study_before["BTCUSD"][a["version"]]["eligible"]
    assert "Bootstrap only" in study_before["BTCUSD"][a["version"]]["reason"]
    paper.ready_at -= 1
    study_after = {}
    paper.numerical_study(now, study_after)
    feature = study_after["BTCUSD"][a["version"]]
    assert feature["eligible"] and feature["mechanism"] == spec.family
    assert feature["input_cutoff"] == now and len(feature["input_bars_sha256"]) == 64


def test_replacement_position_keeps_immediate_stops_and_six_hour_hold():
    state = flat_state(START)
    e = PaperEngine(state, START)
    change_strategy(e, "primary", change())
    studies = study()
    features = deepcopy(studies["BTCUSD"]["breakout-v1"])
    features.update(
        version="cost-breakout-v1",
        redesign_version="original-account-redesign-v1",
        input_available_at=START + 1,
    )
    studies["BTCUSD"]["cost-breakout-v1"] = features
    PaperEngine(state, START + 1).tick({"BTCUSD": frame(START + 1)}, studies)
    PaperEngine(state, START + 3).tick({"BTCUSD": frame(START + 3, sequence=2)}, {})
    a = state["accounts"]["primary"]
    assert a["positions"]["BTCUSD"]["version"] == "cost-breakout-v1"
    PaperEngine(state, START + 2705).tick({"BTCUSD": frame(START + 2705, sequence=3)}, {})
    assert not a["pending"] and a["positions"]
    PaperEngine(state, START + 4).tick({"BTCUSD": frame(START + 4, price="98", sequence=4)}, {})
    # A monotonic subsequent clock triggers the original stop without a minimum hold.
    PaperEngine(state, START + 2706).tick(
        {"BTCUSD": frame(START + 2706, price="98", sequence=4)}, {}
    )
    assert a["pending"]["BTCUSD"]["reason"] == "ATR stop"


@pytest.mark.parametrize("family", STRATEGIES)
def test_explicit_v4_contract_is_honest_and_does_not_change_v2_defaults(family):
    original = RuleSpec().model_dump()
    spec = RuleSpec(version="reviewed-lab-rules-v4", family=family, holding_horizon="medium")
    reference = RuleSpec(
        version="reviewed-lab-rules-v4",
        family=next(k for k in STRATEGIES if k != family),
        holding_horizon="medium",
    )
    proposal = LabProposal(
        request_id="replacement-pair-0001",
        policy_id="test-policy-0001",
        kind="independent",
        strategy=spec,
        reference=reference,
        mechanism="New fixed entry hypothesis compared prospectively",
        question="Does this entry rule improve subsequent after-cost account value?",
        evidence_bundle_sha256="a" * 64,
    )
    declared = contract(proposal, LabPolicy(request_id="test-policy-0001"))
    assert declared["entry"] == STRATEGIES[family]
    assert declared["inapplicable_compatibility_fields"] == {"lookback": 10, "volume_multiple": "2"}
    assert not {"lookback", "volume_multiple"} & declared["unchanged"].keys()
    assert declared["fixed_method"]["mechanism"] == family
    assert declared["fixed_method"]["inputs"]["prior_range_and_median_volume_bars"] == 20
    assert spec.timing["warmup_minutes"] == 305
    assert spec.timing["maximum_hold"] == 21600
    assert rule_feature([], START, spec, "paper-rest-ioc-v1")["eligible"] is False
    assert RuleSpec().model_dump() == original
    with pytest.raises(ValidationError):
        RuleSpec(family=family)
    with pytest.raises(ValidationError):
        RuleSpec(version="reviewed-lab-rules-v4", family=family, holding_horizon="short")
    with pytest.raises(ValidationError):
        RuleSpec(
            version="reviewed-lab-rules-v4", family=family, holding_horizon="medium", lookback=11
        )


def runtime(store):
    paper = PaperRuntime(store, object())
    paper.running = True
    paper.state["last_tick"] = START
    return paper


def test_native_change_restart_duplicate_and_receipt_survive_later_controls(
    native_store, monkeypatch
):
    store, dsn = native_store
    monkeypatch.setattr("trading.paper_runtime.time.time", lambda: START)
    paper = runtime(store)
    before, events = deepcopy(store.read()), store.export(0, 1000)
    first = paper.strategy_change("primary", change())
    assert first["status"] == "applied" and store.reconcile()["balanced"]
    assert all(
        store.read()["accounts"]["primary"][k] == v
        for k, v in before["accounts"]["primary"].items()
        if k not in {"version", "control_version", "last_strategy_change"}
    )
    paper.account_control("primary", "pause", 1)
    prior_receipt = paper.strategy_receipt("primary", change().request_id)
    after_control = deepcopy(store.read())
    assert paper.strategy_change("primary", change())["status"] == "already_applied"
    assert store.read()["accounts"] == after_control["accounts"]
    assert (
        len(
            [r for r in store.export(0, 1000)["records"] if r["kind"] == "account_strategy_changed"]
        )
        == 1
    )
    assert store.export(0, 1000)["records"][: len(events["records"])] == events["records"]
    assert paper.strategy_receipt("responsive-v1", change().request_id) is None
    store.close()
    reopened = PaperStore(dsn, owner=True)
    try:
        reopened.initialize(START)
        assert runtime(reopened).strategy_receipt("primary", change().request_id) == prior_receipt
        assert reopened.reconcile()["balanced"]
    finally:
        reopened.close()


def test_native_rollback_keeps_original_state_and_no_receipt(native_store):
    store, _ = native_store
    before, events = deepcopy(store.read()), store.export(0, 1000)

    def fail(engine):
        change_strategy(engine, "primary", change())
        raise RuntimeError("Synthetic precommit failure")

    with pytest.raises(RuntimeError):
        store.transact(START, fail)
    assert store.read() == before and store.export(0, 1000) == events
    assert runtime(store).strategy_receipt("primary", change().request_id) is None


def test_native_lost_ack_reopens_exact_committed_receipt_without_repeat(native_store, monkeypatch):
    store, _ = native_store
    monkeypatch.setattr("trading.paper_runtime.time.time", lambda: START)
    paper = runtime(store)
    original = paper._transact_state

    def lost(now, work):
        original(now, work)
        raise RuntimeError("Synthetic acknowledgment lost after commit")

    monkeypatch.setattr(paper, "_transact_state", lost)
    with pytest.raises(RuntimeError, match="after commit"):
        paper.strategy_change("primary", change())
    receipt = paper.strategy_receipt("primary", change().request_id)
    assert receipt and receipt["to"] == "cost-breakout-v1"
    assert store.reconcile()["balanced"]
    assert (
        len(
            [r for r in store.export(0, 1000)["records"] if r["kind"] == "account_strategy_changed"]
        )
        == 1
    )


def test_api_catalog_local_authority_conflict_and_exact_read_receipt(
    native_store, tmp_path, monkeypatch
):
    store, _ = native_store
    monkeypatch.setattr("trading.paper_runtime.time.time", lambda: START)
    paper = runtime(store)
    app = create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    with TestClient(app) as client:
        app.state.paper = paper
        rows = client.get("/api/paper/strategies").json()["strategies"]
        assert [r["id"] for r in rows] == list(STRATEGIES)
        route = "/api/paper/accounts/primary/strategy"
        assert client.post(route, json=change().model_dump()).status_code == 403
        assert (
            client.post(
                route,
                json=change().model_dump(),
                headers={"X-Local-Operator": "1", "Origin": "http://foreign.example"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                route, json=change(control=1).model_dump(), headers={"X-Local-Operator": "1"}
            ).status_code
            == 409
        )
        assert (
            client.post(
                route, json=change().model_dump(), headers={"X-Local-Operator": "1"}
            ).status_code
            == 200
        )
        receipt = client.get(route + "/" + change().request_id)
        assert receipt.status_code == 200 and receipt.json()["request_id"] == change().request_id
        assert client.get(route + "/unknown-receipt-0001").status_code == 404
        assert client.get(route + "/bad").status_code == 422
        assert store.reconcile()["balanced"]


@pytest.mark.parametrize(
    "name",
    [
        "primary",
        "breakout-v1",
        "responsive-v1",
        "selective-v1",
        "universe-control-v1",
        "universe-wide-v1",
    ],
)
def test_each_protected_original_can_select_a_rule_without_new_funding(
    native_store, name, monkeypatch
):
    store, _ = native_store
    store.transact(
        START,
        lambda engine: (engine.universe_experiment(["BTCUSD", "ETHUSD"]), engine.tick({}, {})),
    )
    monkeypatch.setattr("trading.paper_runtime.time.time", lambda: START)
    paper = runtime(store)
    before = deepcopy(store.read()["accounts"])
    spec = change(expected=before[name]["version"], request=f"switch-{name}-0001")
    assert paper.strategy_change(name, spec)["status"] == "applied"
    after = store.read()["accounts"]
    for key in ("cash", "funding", "fees", "realized", "closed", "wins", "risk_policy", "symbols"):
        assert after[name].get(key) == before[name].get(key)
    assert all(after[other] == before[other] for other in before if other != name)
    assert store.reconcile()["balanced"]


@pytest.mark.parametrize(
    "condition",
    [
        "imbalance",
        "missing_audit",
        "expired_audit",
        "readback_error",
        "storage",
        "capture",
        "pressure",
        "stale_paper",
        "paper_error",
    ],
)
def test_tiered_rule_change_keeps_every_existing_admission_prerequisite(
    native_store, tmp_path, condition
):
    store, _ = native_store
    now = time.time()
    store.transact(now, lambda engine: engine.tick({}, {}))
    paper = TieredPaperRuntime(store, object(), tmp_path / "capture.sqlite")
    paper.running = True
    reader = FinancialReadback(store)
    try:
        observed = reader.sample(audit=True)
        paper._accept_financial_audit(observed)
        paper._accept_financial_sample(observed)
    finally:
        reader.close()
    paper.disk_free = 10 * 1024**3
    mono = time.monotonic()
    for offset in range(20):
        paper._work_pressure.observe(20, mono - (19 - offset) * 0.55)
    assert not paper.constrained()
    if condition == "imbalance":
        paper.receipts["balanced"] = (
            False  # Explicit monitor fixture; no financial data corruption.
        )
    elif condition == "missing_audit":
        paper._readback_audit_mono = None
    elif condition == "expired_audit":
        paper._readback_audit_mono = time.monotonic() - 121
    elif condition == "readback_error":
        paper._readback_error = "synthetic observation failure"
    elif condition == "storage":
        paper.disk_free = 5 * 1024**3 - 1
    elif condition == "capture":
        paper._capture_failure = "synthetic capture failure"
    elif condition == "pressure":
        paper._work_pressure.observe(1000, time.monotonic())
    elif condition == "stale_paper":
        paper.state["last_tick"] = time.time() - 11
    else:
        paper.error = "synthetic paper error"
    before = deepcopy(store.read()), store.export(0, 1000)
    with pytest.raises(ValueError):
        paper.strategy_change("primary", change())
    assert (store.read(), store.export(0, 1000)) == before
    assert paper.strategy_receipt("primary", change().request_id) is None


@pytest.mark.parametrize("seconds", [300, 900])
def test_current_frames_keeps_old_horizon_staleness_while_new_five_minute_bank_is_current(
    monkeypatch, seconds
):
    from test_paper_runtime import instrument

    monkeypatch.setattr("trading.tiered_runtime.time.time", lambda: START + 200)
    paper = TieredPaperRuntime.__new__(TieredPaperRuntime)
    paper.state = flat_state(START)
    paper.stream = SimpleNamespace(
        plan={"BTCUSD": 100},
        fresh_books=lambda **kw: {"BTCUSD": {**frame(START + 200), "source": "synthetic-stream"}},
    )
    paper.instruments, paper.metadata_at = {"BTCUSD": instrument("BTC")}, START + 200
    paper._fallback, paper._rest_requests, paper._fallback_at = {}, {}, {}
    paper._rest_retry_at, paper._previous_books, paper.feed_errors = 0, {}, {}
    paper._candle_errors, paper._input_eligibility = {}, {}
    common = {"eligible": True, "bar_open_ms": int(START * 1000), "feature_seconds": seconds}
    paper.study = {
        "BTCUSD": {
            "lab-old": dict(common),
            "cost-breakout-v1": {
                **common,
                "feature_seconds": 300,
                "redesign_version": "original-account-redesign-v1",
            },
        }
    }
    _, studies = paper.current_frames()
    assert studies["BTCUSD"]["lab-old"] == {
        **common,
        "eligible": False,
        "reason": "Closed candle is stale",
    }
    assert studies["BTCUSD"]["cost-breakout-v1"]["eligible"]


def test_v4_pair_uses_same_retained_inputs_and_existing_native_funding_owner(
    native_store, tmp_path
):
    from dataclasses import replace

    from test_autonomous_lab import make_lab

    from trading import autonomous_finance as finance

    store, _ = native_store
    lab = make_lab(store, tmp_path, holding_horizons=("medium",))
    bars = strategy_fixture("compression-breakout-v1")
    offset = int(START * 1000) - bars[-1].close_ms - 1
    lab.paper.history["BTCUSD"] = [
        replace(bar, open_ms=bar.open_ms + offset, close_ms=bar.close_ms + offset) for bar in bars
    ]
    proposal = LabProposal(
        request_id="redesign-distinct-pair-001",
        policy_id="continuous-test-policy",
        kind="independent",
        strategy=RuleSpec(
            version="reviewed-lab-rules-v4",
            family="compression-breakout-v1",
            holding_horizon="medium",
        ),
        reference=RuleSpec(
            version="reviewed-lab-rules-v4", family="washout-rebound-v1", holding_horizon="medium"
        ),
        mechanism="Prospective compression escape versus post-washout recovery",
        question=(
            "Which distinct fixed entry mechanism preserves subsequent value after actual costs?"
        ),
        evidence_bundle_sha256=lab.bundle(START)["sha256"],
    )
    original = deepcopy(store.read()["accounts"])
    evaluated = lab.evaluate(proposal, START)
    assert len(evaluated["inputs"]) == len(bars) == 305
    assert evaluated["feature"]["input_cutoff"] == START
    assert lab.submit(proposal, START)["status"] == "evaluated"
    reserved = store.lab_reserve(START, proposal)
    lab.paper.state = store.transact(
        START, lambda engine: finance.fund(engine, reserved["trial_id"])
    )
    trial = lab.paper.state["autonomous_lab"]["trials"][reserved["trial_id"]]
    assert trial["status"] == "active" and trial["review_at"] == START + 86400
    assert all(lab.paper.state["accounts"][name] == account for name, account in original.items())
    for role, spec in (("candidate", proposal.strategy), ("reference", proposal.reference)):
        account = lab.paper.state["accounts"][trial[role]]
        assert account["rule_spec"] == spec.model_dump()
        assert account["funding"] == "100" and account["closed"] == 0
    assert finance.slots(lab.paper.state)["managed"] == 8
    assert store.reconcile()["balanced"]
    lab.registry.close()
