"""Synthetic financial traces beside offline pressure decisions; no model admission.

Every order/position below comes from the real PaperEngine. Elapsed-work values
are supplied fixtures, not measured performance. Neither pressure policy is
injected into financial processing, and no store, capture writer or runtime
constructor is used. Matching input evidence is not disk-capture acceptance.
"""

import copy
import json
from collections import defaultdict, deque
from decimal import Decimal as D

import pytest
from test_paper_engine import START, frame, study

from trading.engine_diagnostics import EngineWorkDiagnostics, ModerateRecoveryCandidate
from trading.market import parse_book
from trading.paper_engine import PaperEngine, initial_state
from trading.tiered_runtime import TieredPaperRuntime


def current_pressure_policy():
    # Reuse the unchanged runtime observer without constructing its services.
    runtime = object.__new__(TieredPaperRuntime)
    runtime._loop_ms = deque(maxlen=1000)
    runtime._constrained_until = 0.0
    runtime._work_diagnostics = EngineWorkDiagnostics()
    runtime._notice_queue = []
    return runtime


def replay(policy, steps):
    state = initial_state(START)
    trace = []
    for offset, (frames, studies, paused) in enumerate(steps):
        if paused:
            state["paused"] = True
        engine = PaperEngine(state, START + offset)
        if offset == 0:
            engine.seed()
        # Financial work precedes pressure observation, as in the real loop.
        engine.tick(copy.deepcopy(frames), copy.deepcopy(studies))
        engine.assert_invariants()
        duration = 150.0 if 16 <= offset <= 19 else 20.0
        now_mono = 1000.0 + offset
        if isinstance(policy, TieredPaperRuntime):
            policy.observe_engine_work(duration, now_mono)
            would_allow = now_mono >= policy._constrained_until
        else:
            policy.observe(duration, now_mono)
            would_allow = policy.evaluate(now_mono).pressure_would_allow
        # Some emitted bodies share mutable engine objects; freeze each tick.
        trace.append(
            {
                "state": copy.deepcopy(state),
                "events": copy.deepcopy(engine.events),
                "frames": copy.deepcopy(frames),
                "studies": copy.deepcopy(studies),
                "pressure_would_allow": would_allow,
            }
        )
    return trace


def assert_matched_financial_trace(steps):
    current = replay(current_pressure_policy(), steps)
    candidate = replay(ModerateRecoveryCandidate(), steps)
    # The same moderate burst blocks both. Only the candidate has recovered
    # after twenty consecutive calm samples, while current retains its hold.
    assert not current[19]["pressure_would_allow"]
    assert not candidate[19]["pressure_would_allow"]
    assert not current[39]["pressure_would_allow"]
    assert candidate[39]["pressure_would_allow"]
    for old, proposed in zip(current, candidate, strict=True):
        for key in ("frames", "studies", "state", "events"):
            assert old[key] == proposed[key]
    old_events = [event for step in current for event in step["events"]]
    new_events = [event for step in candidate for event in step["events"]]
    assert json.dumps(old_events, sort_keys=True) == json.dumps(new_events, sort_keys=True)
    assert_journal_reconciles_each_tick(candidate)
    assert_fill_evidence(candidate)
    return candidate


def assert_journal_reconciles_each_tick(trace):
    balances = defaultdict(D)
    for step in trace:
        for event in step["events"]:
            totals = defaultdict(D)
            for row in event["lines"]:
                amount = D(row["amount"])
                totals[row["asset"]] += amount
                balances[event["account"], row["asset"], row["bucket"]] += amount
            assert all(total == 0 for total in totals.values())
        for name, account in step["state"]["accounts"].items():
            reserved = sum((D(order["reserved"]) for order in account["pending"].values()), D(0))
            assert balances[name, "USD", "reserved"] == reserved
            assert balances[name, "USD", "cash"] + reserved == D(account["cash"])
            assert balances[name, "USD", "fees"] == D(account["fees"])
            assert -balances[name, "USD", "fake_funding"] == D(account["funding"]) == 100
            quantity = sum((D(pos["quantity"]) for pos in account["positions"].values()), D(0))
            assert balances[name, "BTC", "inventory"] == quantity
            assert account["replenishments"] == 0
            assert account["risk_policy"] == "cash-spot-hard-stop-v1"


def assert_fill_evidence(trace):
    consumed = set()
    for step in trace:
        for event in step["events"]:
            if event["kind"] != "fill":
                continue
            body = event["body"]
            observed = step["frames"][body["symbol"]]
            assert body["book"] == observed["raw"]
            assert body["instrument"] == observed["instrument"]
            assert body["observed_at"] == body["observation"]["observed"] == observed["observed"]
            assert body["observed_at"] > body["created_at"]
            assert body["fee_asset"] == "USD"
            assert body["execution_profile"] == "paper-rest-ioc-v1"
            assert D(body["fee"]) == D(body["gross"]) * D("0.001")
            identity = (event["account"], body["symbol"], body["book"]["lastUpdateId"])
            assert identity not in consumed
            consumed.add(identity)


def primary_events(trace, kind):
    return [
        event
        for step in trace
        for event in step["events"]
        if event["account"] == "primary" and event["kind"] == kind
    ]


def test_active_position_partial_stop_exit_and_journal_match_after_moderate_recovery():
    steps = []
    for offset in range(44):
        if offset == 1:
            observed = frame(START, sequence=1)  # Intent's original book cannot fill it.
        elif offset in (2, 3):
            observed = frame(START + 2, sequence=2, quantity="1")
        elif offset == 40:
            observed = frame(START + 40, "98", 4)
        elif offset == 41:
            observed = frame(START + 41, "97.9", 5, "0.5")
        elif offset in (42, 43):
            observed = frame(START + 42, "97.8", 6)
        else:
            observed = frame(START + offset, sequence=1 if offset == 0 else 3)
        steps.append(({"BTCUSD": observed}, study(), offset >= 4))
    trace = assert_matched_financial_trace(steps)
    assert trace[0]["state"]["accounts"]["primary"]["pending"]
    assert not primary_events(trace[:2], "fill")
    position = trace[39]["state"]["accounts"]["primary"]["positions"]["BTCUSD"]
    assert D(position["quantity"]) == D("0.1")
    assert D(position["cost"]) == D("10.0150050")
    assert trace[39]["state"]["paused"]  # Pause must still permit actual stop exits.
    fills = primary_events(trace, "fill")
    assert [D(e["body"]["filled_quantity"]) for e in fills] == [D("0.1"), D("0.05"), D("0.05")]
    assert [e["body"]["partial"] for e in fills] == [True, True, False]
    assert [D(e["body"]["gross"]) for e in fills] == [D("10.005"), D("4.894"), D("4.889")]
    assert not primary_events(trace[43:], "fill")
    account = trace[-1]["state"]["accounts"]["primary"]
    assert not account["positions"] and not account["pending"]
    assert account["closed"] == 1 and account["wins"] == 0
    assert D(account["cash"]) == D("99.75821200")
    assert D(account["fees"]) == D("0.01978800")
    assert D(account["realized"]) == D("-0.24178800") == D(account["cash"]) - 100
    closed = primary_events(trace, "trade_closed")
    assert len(closed) == 1
    assert closed[0]["body"]["entry_features"] == study()["BTCUSD"]["breakout-v1"]
    assert D(closed[0]["body"]["pnl"]) == D(account["realized"])


@pytest.mark.parametrize(
    "outcome", ["fill", "operator_cancel", "filter_rejection", "expiry", "entry_rejection"]
)
def test_pending_order_fill_cancel_and_real_rejection_conventions_match(outcome):
    steps = []
    for offset in range(55 if outcome == "expiry" else 41):
        observed = frame(START + offset, sequence=1 if offset <= 38 else 2)
        frames = {"BTCUSD": observed}
        studies = study() if offset >= 38 and outcome != "entry_rejection" else {}
        paused = offset >= 39 and outcome == "operator_cancel"
        if offset >= 39:
            if outcome == "filter_rejection":
                observed["rules"]["min_notional"] = D(200)
            elif outcome == "expiry":
                frames, studies = {}, {}
            elif outcome == "entry_rejection":
                observed["raw"]["asks"] = [["101", "100"]]
                observed["book"] = parse_book(observed["raw"])
                studies = study()
        steps.append((frames, studies, paused))
    trace = assert_matched_financial_trace(steps)
    account = trace[-1]["state"]["accounts"]["primary"]
    if outcome != "entry_rejection":
        pending = trace[38]["state"]["accounts"]["primary"]["pending"]["BTCUSD"]
        assert D(pending["reserved"]) == D("49.9998178680")
        assert not primary_events(trace[:39], "fill")
    if outcome == "fill":
        fills = primary_events(trace, "fill")
        assert len(fills) == 1 and not fills[0]["body"]["partial"]
        position = account["positions"]["BTCUSD"]
        assert D(position["quantity"]) == D("0.49890")
        assert D(position["cost"]) == D("49.9648599450")
        assert D(account["cash"]) == D("50.0351400550")
        assert D(account["cash"]) + D(position["cost"]) == 100
        assert D(account["fees"]) == D("0.0499149450")
    else:
        assert D(account["cash"]) == 100 and D(account["fees"]) == 0
        assert not account["positions"] and not primary_events(trace, "fill")
        cancelled = primary_events(trace, "order_cancelled")
        if outcome == "entry_rejection":
            assert not cancelled and not primary_events(trace, "order_intent")
            decisions = primary_events(trace, "decision")
            assert len(decisions) == 1
            assert decisions[0]["body"]["reason"] == "Spread exceeds 25 bps"
        else:
            reasons = {
                "operator_cancel": "Operator paused entries; position exits remain enabled.",
                "filter_rejection": "Price or notional filters changed",
                "expiry": "Expired across data gap or restart",
            }
            assert len(cancelled) == 1 and cancelled[0]["body"]["reason"] == reasons[outcome]
            assert D(cancelled[0]["body"]["reserved"]) == D("49.9998178680")
            if outcome == "expiry":
                assert trace[39]["state"]["accounts"]["primary"]["pending"]
                assert cancelled[0]["at"] == START + 54
    assert not account["pending"]
    assert account["closed"] == 0 and D(account["realized"]) == 0
