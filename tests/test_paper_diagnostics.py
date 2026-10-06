"""Pure financial-domain QA; synthetic books, no runtime/DB/model/market proof."""

import copy
from collections import defaultdict
from decimal import Decimal as D

import pytest
from test_paper_engine import START, frame, tick

from trading.paper_diagnostics import (
    CONTRACT,
    FAKE_CAPITAL,
    MAX_ACTIONS_PER_TICK,
    create_diagnostic,
    diagnostic_snapshot,
    start_diagnostic,
    stop_diagnostic,
)
from trading.paper_engine import PaperEngine, account, initial_state

NAME = "performance-diagnostic"
CREATE = "diagnostic-create-0001"
RUN = "diagnostic-workload-0001"
STOP = "diagnostic-stop-0001"


def setup(seed=7, max_actions=1000, duration_seconds=600):
    state = initial_state(START)
    engine = PaperEngine(state, START)
    engine.seed()
    create_diagnostic(engine, CREATE)
    start_diagnostic(engine, RUN, seed, max_actions, duration_seconds)
    return state, copy.deepcopy(engine.events)


def diagnostic_tick(
    state, offset, sequence, *, observed=None, allowed=True, price="100", risk_valid=True
):
    now = START + offset
    frames = {"BTCUSD": frame(now if observed is None else observed, price, sequence)}
    frames["BTCUSD"]["diagnostic_risk_input_valid"] = risk_valid
    studies = {"BTCUSD": {"closed-market-input": {"atr": "1"}}}
    engine = PaperEngine(state, now)
    engine.tick(frames, studies, diagnostic_allowed=allowed)
    return engine


def run_state(state):
    return state["accounts"][NAME]["diagnostic"]["runs"][RUN]


def test_single_frozen_account_atomic_funding_and_lost_ack_retry_preserve_baselines():
    state = initial_state(START)
    before = copy.deepcopy(state["accounts"])
    engine = PaperEngine(state, START)
    result = create_diagnostic(engine, CREATE)
    a = state["accounts"][NAME]
    assert a["cash"] == a["funding"] == a["starting_capital"] == FAKE_CAPITAL
    assert a["purpose"] == "performance_diagnostic" and a["replenishments"] == 0
    assert a["attempt"]["outcome"] == "performance_only"
    assert {n: a for n, a in state["accounts"].items() if n != NAME} == before
    funding = engine.events[0]
    assert funding["kind"] == "performance_diagnostic_funded"
    assert funding["purpose"] == funding["body"]["purpose"] == a["purpose"]
    assert sum(D(row["amount"]) for row in funding["lines"]) == 0
    result["account"]["cash"] = "0"  # Detached operator response cannot change money.
    assert a["cash"] == FAKE_CAPITAL
    retried = PaperEngine(state, START + 1)
    assert create_diagnostic(retried, CREATE)["status"] == "already_applied"
    assert not retried.events and retried.state["accounts"][NAME] == a
    with pytest.raises(ValueError, match="already exists"):
        create_diagnostic(retried, "diagnostic-create-0002")
    assert len(state["accounts"]) == len(before) + 1


def test_slot_admission_counts_protected_originals_and_reserved_lab_accounts():
    state = initial_state(START)
    for index in range(12):
        state["accounts"][f"other-{index}"] = account("breakout-v1", START)
    state["autonomous_lab"] = {
        "policy": {"slots": 20},
        "trials": {
            "reserved": {"status": "reserved", "candidate": "reserved-a", "reference": "reserved-b"}
        },
    }
    before = copy.deepcopy(state)
    engine = PaperEngine(state, START)
    with pytest.raises(ValueError, match="slots are full"):
        create_diagnostic(engine, CREATE)
    assert state == before and not engine.events


def test_large_fake_capital_is_not_available_to_the_regular_account_factory():
    with pytest.raises(ValueError, match="50 or"):
        account("breakout-v1", START, FAKE_CAPITAL)


@pytest.mark.parametrize(
    "seed,actions,duration",
    [
        (True, 10, 10),
        (-1, 10, 10),
        (2**32, 10, 10),
        (1, 0, 10),
        (1, 1001, 10),
        (1, 10, 601),
        (1, 10, 0),
    ],
)
def test_workload_limits_fail_before_mutating(seed, actions, duration):
    state = initial_state(START)
    engine = PaperEngine(state, START)
    create_diagnostic(engine, CREATE)
    before = copy.deepcopy(state)
    with pytest.raises(ValueError):
        start_diagnostic(engine, RUN, seed, actions, duration)
    assert state == before


def test_start_retry_never_renews_deadline_or_rerolls_after_restart():
    state, _ = setup()
    diagnostic_tick(state, 0, 1)
    restored = copy.deepcopy(state)
    engine = PaperEngine(restored, START + 20)
    expected = copy.deepcopy(run_state(restored))
    assert start_diagnostic(engine, RUN, 7)["status"] == "already_applied"
    assert run_state(restored) == expected and not engine.events
    with pytest.raises(ValueError, match="different limits"):
        start_diagnostic(engine, RUN, 8)
    assert diagnostic_snapshot(restored)["run"]["request_id"] == RUN


def test_intents_need_later_fresh_books_and_diagnostic_cannot_win_baseline_target():
    state, _ = setup()
    first = diagnostic_tick(state, 0, 1)
    a = state["accounts"][NAME]
    assert a["pending"] and not a["positions"]
    assert D(a["pending"]["BTCUSD"]["reserved"]) <= D("1000")
    assert not any(e["kind"] == "fill" for e in first.events)
    diagnostic_tick(state, 1, 1, observed=START)
    assert not a["positions"] and run_state(state)["attempted"] == 1
    actual = diagnostic_tick(state, 2, 2)
    assert a["positions"] and D(a["fees"]) > 0
    assert a["attempt_wins"] == 0 and a["attempt"]["outcome"] == "performance_only"
    assert not any(
        e["account"] == NAME and e["kind"] in {"decision", "attempt_won"} for e in actual.events
    )


def test_active_drain_never_invents_a_fill_and_preserves_partial_exit_inventory():
    state, _ = setup()
    diagnostic_tick(state, 0, 1)
    diagnostic_tick(state, 2, 2)
    a = state["accounts"][NAME]
    quantity = a["positions"]["BTCUSD"]["quantity"]
    stopped = PaperEngine(state, START + 3)
    stop_diagnostic(stopped, STOP)
    assert run_state(state)["status"] == "draining" and a["positions"]
    assert not any(e["kind"] == "fill" for e in stopped.events)
    gap = PaperEngine(state, START + 4)
    gap.tick({}, {})
    assert a["positions"]["BTCUSD"]["quantity"] == quantity
    diagnostic_tick(state, 5, 3)
    assert a["pending"]["BTCUSD"]["side"] == "sell"
    final = PaperEngine(state, START + 7)
    final.tick({"BTCUSD": frame(START + 7, "100", 4, "0.01")}, {})
    assert a["positions"] and run_state(state)["status"] == "draining"
    remaining = a["positions"]["BTCUSD"]["quantity"]
    diagnostic_tick(state, 8, 4)
    assert a["positions"]["BTCUSD"]["quantity"] == remaining
    diagnostic_tick(state, 9, 5)
    assert not a["positions"] and not a["pending"]
    assert run_state(state)["status"] == "completed"
    assert a["funding"] == FAKE_CAPITAL and a["replenishments"] == 0


def test_end_of_time_budget_cancels_unfilled_buy_without_invented_execution():
    state, _ = setup(duration_seconds=1)
    diagnostic_tick(state, 0, 1)
    end = diagnostic_tick(state, 1, 2)
    a = state["accounts"][NAME]
    assert not a["positions"] and not a["pending"] and a["cash"] == FAKE_CAPITAL
    assert run_state(state)["status"] == "completed"
    assert run_state(state)["cancels"] == 1 and run_state(state)["fills"] == 0
    assert not any(e["kind"] == "fill" for e in end.events)


def test_guard_closes_new_diagnostic_work_but_keeps_existing_position_exits():
    state, _ = setup()
    diagnostic_tick(state, 0, 1)
    blocked = diagnostic_tick(state, 2, 2, allowed=False)
    a = state["accounts"][NAME]
    assert not a["positions"] and not a["pending"]
    assert run_state(state)["attempted"] == 1
    assert not any(e["kind"] == "fill" for e in blocked.events)
    diagnostic_tick(state, 3, 3)
    diagnostic_tick(state, 5, 4)
    assert a["positions"]
    diagnostic_tick(state, 10, 5, allowed=False)
    assert a["pending"]["BTCUSD"]["side"] == "sell"
    diagnostic_tick(state, 12, 6, allowed=False)
    assert not a["positions"] and not a["pending"]


def test_account_fault_rolls_back_diagnostic_only_and_reports_a_real_error():
    state, _ = setup()
    baseline = copy.deepcopy(state["accounts"]["primary"])
    state["accounts"][NAME]["diagnostic"]["contract"]["notional_cap_usd"] = "99999999"
    result = diagnostic_tick(state, 0, 1)
    a = state["accounts"][NAME]
    assert a["fault"]["code"] == "ValueError"
    assert run_state(state)["status"] == "faulted" and run_state(state)["errors"] == 1
    assert not a["positions"] and not a["pending"]
    assert not any(e["account"] == NAME and e["kind"] == "order_intent" for e in result.events)
    expected = copy.deepcopy(baseline)
    primary = state["accounts"]["primary"]
    assert primary["cash"] == expected["cash"] and not primary["positions"]
    assert "fault" not in primary


def test_seeded_varied_workload_is_restart_stable_bounded_and_journal_balanced():
    state, events = setup(seed=33, max_actions=40)
    for offset in range(15):
        events.extend(copy.deepcopy(diagnostic_tick(state, offset, offset + 1).events))
    restored = copy.deepcopy(state)
    for offset in range(15, 80):
        original = diagnostic_tick(state, offset, offset + 1)
        restarted = diagnostic_tick(restored, offset, offset + 1)
        assert original.state == restarted.state and original.events == restarted.events
        assert (
            sum(e["kind"] == "performance_diagnostic_action" for e in original.events)
            <= MAX_ACTIONS_PER_TICK
        )
        events.extend(copy.deepcopy(original.events))
    a = state["accounts"][NAME]
    assert run_state(state)["status"] == "completed" and run_state(state)["attempted"] == 40
    assert run_state(state)["completed"] > 2 and run_state(state)["fills"] > 4
    intents = [e["body"] for e in events if e["account"] == NAME and e["kind"] == "order_intent"]
    assert len({o["quantity"] for o in intents if o["side"] == "buy"}) > 1
    assert all(D(o["reserved"]) <= 1000 for o in intents if o["side"] == "buy")
    balances = defaultdict(D)
    for event in events:
        if event["account"] != NAME:
            continue
        totals = defaultdict(D)
        for row in event["lines"]:
            totals[row["asset"]] += D(row["amount"])
            balances[row["asset"], row["bucket"]] += D(row["amount"])
        assert all(value == 0 for value in totals.values())
    assert balances["USD", "cash"] == D(a["cash"])
    assert balances["USD", "reserved"] == 0 and balances["BTC", "inventory"] == 0
    assert balances["USD", "fees"] == D(a["fees"])
    assert -balances["USD", "fake_funding"] == D(FAKE_CAPITAL)
    assert D(a["realized"]) == D(a["cash"]) - D(FAKE_CAPITAL)
    assert a["attempt_wins"] == a["attempt_failures"] == a["replenishments"] == 0


def test_diagnostic_brief_cooldown_does_not_change_normal_trade_cooldown():
    state = initial_state(START)
    tick(state, START)
    tick(state, START + 2, sequence=2)
    tick(state, START + 5, "98", 3)
    tick(state, START + 7, "97.9", 4)
    assert state["accounts"]["primary"]["cooldowns"]["BTCUSD"] == START + 607
    diagnostic, _ = setup()
    for offset in range(20):
        diagnostic_tick(diagnostic, offset, offset + 1)
    a = diagnostic["accounts"][NAME]
    assert a["closed"] >= 2
    assert a["cooldowns"]["BTCUSD"] <= START + 20
    assert CONTRACT["symbol_cooldown_seconds"] == 1


def test_missing_risk_inputs_and_repeated_books_remain_honest_non_execution():
    state, _ = setup()
    engine = PaperEngine(state, START)
    book = frame()
    book["diagnostic_risk_input_valid"] = True
    engine.tick({"BTCUSD": book}, {})
    assert not state["accounts"][NAME]["pending"]
    assert "ATR unavailable" in run_state(state)["reason"]
    for offset in range(1, 5):
        diagnostic_tick(state, offset, 1)
    assert run_state(state)["attempted"] == 1 and run_state(state)["fills"] == 0


def test_stopping_uncertain_execution_never_frees_or_completes_unknown_work():
    state, _ = setup()
    diagnostic_tick(state, 0, 1)
    a = state["accounts"][NAME]
    a["pending"]["BTCUSD"]["uncertain"] = True
    a["execution_uncertain"] = True
    engine = PaperEngine(state, START + 1)
    stop_diagnostic(engine, STOP)
    assert a["pending"] and run_state(state)["status"] == "draining"
    assert not any(e["kind"] == "order_cancelled" for e in engine.events)
    stop_diagnostic(PaperEngine(state, START + 2), STOP)
    assert a["pending"]


def test_uncertain_running_execution_stops_new_load_and_preserves_owned_inventory():
    state, _ = setup()
    diagnostic_tick(state, 0, 1)
    diagnostic_tick(state, 2, 2)
    a = state["accounts"][NAME]
    quantity = a["positions"]["BTCUSD"]["quantity"]
    a["execution_uncertain"] = True
    result = diagnostic_tick(state, 9, 3)
    assert run_state(state)["status"] == "draining"
    assert a["positions"]["BTCUSD"]["quantity"] == quantity and not a["pending"]
    assert not any(e["account"] == NAME and e["kind"] == "order_intent" for e in result.events)
    assert "uncertain" in a["positions"]["BTCUSD"]["exit_blocked"]


def test_stop_retry_after_another_workload_cannot_stop_the_new_request():
    state, _ = setup()
    stop_diagnostic(PaperEngine(state, START + 1), STOP)
    next_request = "diagnostic-workload-0002"
    start_diagnostic(PaperEngine(state, START + 2), next_request, 19)
    retried = PaperEngine(state, START + 3)
    receipt = stop_diagnostic(retried, STOP)
    assert receipt["status"] == "already_applied"
    assert receipt["requested_receipt"]["run_request_id"] == RUN
    assert diagnostic_snapshot(state)["run"]["request_id"] == next_request
    assert diagnostic_snapshot(state)["run"]["status"] == "running" and not retried.events


def test_old_start_retry_retains_its_receipt_while_a_different_workload_is_active():
    state, _ = setup()
    stop_diagnostic(PaperEngine(state, START + 1), STOP)
    next_request = "diagnostic-workload-0002"
    start_diagnostic(PaperEngine(state, START + 2), next_request, 19)
    retried = PaperEngine(state, START + 3)
    result = start_diagnostic(retried, RUN, 7)
    assert result["run"]["request_id"] == next_request and not retried.events
    assert result["requested_receipt"] == {
        "action": "start",
        "request_id": RUN,
        "run_request_id": RUN,
        "status": "completed",
    }
    assert set(result["applied_request_ids"]) == {CREATE, RUN, STOP, next_request}


@pytest.mark.parametrize("protected_source", ["stale", "candle_error", "bootstrap"])
def test_positive_retained_atr_cannot_override_protected_input_eligibility(protected_source):
    state, _ = setup()
    book = frame()
    # The runtime computes this Boolean from actual protected input provenance,
    # independently of a strategy's signal. Narrative text supplies no authority.
    book["diagnostic_risk_input_valid"] = False
    studies = {
        "BTCUSD": {
            "closed-market-input": {
                "atr": "1",
                "eligible": False,
                "reason": "irrelevant narrative",
                "fixture_provenance": protected_source,
            }
        }
    }
    engine = PaperEngine(state, START)
    engine.tick({"BTCUSD": book}, studies)
    assert not state["accounts"][NAME]["pending"]
    assert run_state(state)["attempted"] == 1 and run_state(state)["intents"] == 0
    assert not any(e["account"] == NAME and e["kind"] == "order_intent" for e in engine.events)


def test_missing_marker_fails_closed_even_for_direct_diagnostic_intents():
    state, _ = setup()
    engine = PaperEngine(state, START)
    a = state["accounts"][NAME]
    engine.value(a, {"BTCUSD": frame()})
    feature = {"eligible": True, "atr": "1", "diagnostic_notional_usd": "100"}
    reason = engine.enter(NAME, a, "BTCUSD", frame(), feature)
    assert "Protected current" in reason and not a["pending"]


def test_valid_market_risk_input_can_ignore_untriggered_strategy_signal():
    state, _ = setup()
    book = frame()
    book["diagnostic_risk_input_valid"] = True
    engine = PaperEngine(state, START)
    engine.tick(
        {"BTCUSD": book},
        {
            "BTCUSD": {
                "closed-market-input": {
                    "atr": "1",
                    "eligible": False,
                    "reason": "No breakout signal",
                }
            }
        },
    )
    assert state["accounts"][NAME]["pending"]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), True])
def test_invalid_clock_cannot_create_unbounded_diagnostic_work(invalid):
    state = initial_state(START)
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match="finite financial clock"):
        create_diagnostic(PaperEngine(state, invalid), CREATE)
    assert state == before
