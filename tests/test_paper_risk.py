"""Disposable risk-boundary fixtures; never evidence of a trading advantage."""

import copy
import json
from decimal import Decimal as D

import pytest
from test_paper_engine import START, buy, frame, study

from trading.paper_engine import (
    HARD_STOP_POLICY,
    LEGACY_POLICY,
    REVIEW_SECONDS,
    PaperEngine,
    account,
    initial_state,
    policy,
    risk_summary,
)


def asset_frame(symbol, at, sequence=1, price="100"):
    result = frame(at, price=price, sequence=sequence)
    result.update(base=symbol.removesuffix("USD"), instrument={"symbol": symbol})
    return result


def reserve_eth_after_btc(state):
    buy(state)
    observations = {symbol: asset_frame(symbol, START + 3, 3) for symbol in ("BTCUSD", "ETHUSD")}
    studies = {"ETHUSD": study()["BTCUSD"]}
    engine = PaperEngine(state, START + 3)
    engine.tick(observations, studies)
    assert "ETHUSD" in state["accounts"]["primary"]["pending"]
    return studies


def test_pending_buy_cannot_fill_with_a_missing_held_asset_valuation():
    state = initial_state(START)
    studies = reserve_eth_after_btc(state)
    a = state["accounts"]["primary"]
    cash = a["cash"]
    engine = PaperEngine(state, START + 5)
    engine.tick({"ETHUSD": asset_frame("ETHUSD", START + 5, 5)}, studies)
    assert not a["valuation_fresh"]
    assert set(a["positions"]) == {"BTCUSD"}
    assert a["cash"] == cash
    assert "ETHUSD" not in a["pending"]
    assert not any(e["kind"] == "fill" and e["account"] == "primary" for e in engine.events)


def test_scheduled_review_cannot_rearm_a_new_default_drawdown_stop():
    state = initial_state(START)
    a = state["accounts"]["primary"]
    a["cash"] = "64"  # Isolated simulated loss; no actual journal or account touched.
    PaperEngine(state, START + 1).tick({}, {})
    assert a["drawdown_pause"] and D(a["max_drawdown"]) == D("0.36")
    PaperEngine(state, START + REVIEW_SECONDS + 1).review()
    assert a["drawdown_pause"]
    assert a["risk_peak"] == "100"
    assert a["funding"] == "100" and a["replenishments"] == 0


def test_missing_value_cancels_once_and_recovery_does_not_replay_a_buy():
    state = initial_state(START)
    studies = reserve_eth_after_btc(state)
    cash = state["accounts"]["primary"]["cash"]
    first = PaperEngine(state, START + 5)
    first.tick({"ETHUSD": asset_frame("ETHUSD", START + 5, 5)}, studies)
    again = PaperEngine(state, START + 5)
    again.tick({"ETHUSD": asset_frame("ETHUSD", START + 5, 5)}, studies)
    assert not any(e["kind"] == "order_cancelled" for e in again.events)
    recovered = PaperEngine(state, START + 6)
    recovered.tick({s: asset_frame(s, START + 6, 6) for s in ("BTCUSD", "ETHUSD")}, studies)
    a = state["accounts"]["primary"]
    assert a["cash"] == cash and set(a["positions"]) == {"BTCUSD"}
    assert not a["pending"] and a["valuation_fresh"]
    cancellations = [
        e for e in first.events if e["kind"] == "order_cancelled" and e["account"] == "primary"
    ]
    assert len(cancellations) == 1 and "BTCUSD" in cancellations[0]["body"]["reason"]


def test_fill_itself_rechecks_portfolio_instead_of_trusting_old_fresh_flag():
    state = initial_state(START)
    reserve_eth_after_btc(state)
    a = state["accounts"]["primary"]
    assert a["valuation_fresh"]
    eth = asset_frame("ETHUSD", START + 5, 5)
    engine = PaperEngine(state, START + 5)
    engine.fill("primary", a, "ETHUSD", eth, {"ETHUSD": eth})
    assert not a["pending"] and set(a["positions"]) == {"BTCUSD"}
    assert not a["valuation_fresh"]


@pytest.mark.parametrize("observed", [START - 1, START + 20, float("nan"), float("inf")])
def test_stale_future_and_invalid_held_price_times_cannot_allow_a_pending_buy(observed):
    state = initial_state(START)
    studies = reserve_eth_after_btc(state)
    btc = asset_frame("BTCUSD", observed, 5)
    PaperEngine(state, START + 5).tick(
        {"BTCUSD": btc, "ETHUSD": asset_frame("ETHUSD", START + 5, 5)}, studies
    )
    assert set(state["accounts"]["primary"]["positions"]) == {"BTCUSD"}
    assert not state["accounts"]["primary"]["pending"]


def test_insufficient_depth_blocks_buys_but_still_allows_partial_risk_reducing_exit():
    state = initial_state(START)
    reserve_eth_after_btc(state)
    a = state["accounts"]["primary"]
    original = D(a["positions"]["BTCUSD"]["quantity"])
    for elapsed, seq in [(5, 5), (7, 7)]:
        btc = frame(START + elapsed, price="98", sequence=seq, quantity="0.5")
        PaperEngine(state, START + elapsed).tick(
            {"BTCUSD": btc, "ETHUSD": asset_frame("ETHUSD", START + elapsed, seq)}, {}
        )
    assert D(a["positions"]["BTCUSD"]["quantity"]) < original
    assert "ETHUSD" not in a["positions"]


def test_exit_with_one_missing_holding_and_a_healthy_sibling_can_still_buy():
    state = initial_state(START)
    studies = reserve_eth_after_btc(state)
    both = {s: asset_frame(s, START + 5, 5) for s in ("BTCUSD", "ETHUSD")}
    PaperEngine(state, START + 5).tick(both, studies)
    a = state["accounts"]["primary"]
    assert "ETHUSD" in a["positions"]
    state["accounts"]["healthy"] = account("breakout-v1", START + 5)
    for elapsed, seq in [(7, 7), (9, 9)]:
        eth = asset_frame("ETHUSD", START + elapsed, seq, "98")
        PaperEngine(state, START + elapsed).tick({"ETHUSD": eth}, {"ETHUSD": study(2)["BTCUSD"]})
    assert set(a["positions"]) == {"BTCUSD"}
    assert "ETHUSD" in state["accounts"]["healthy"]["positions"]


def stopped_state():
    state = initial_state(START)
    state["accounts"]["primary"]["cash"] = "64"  # Synthetic loss only.
    PaperEngine(state, START + 1).tick({}, {})
    return state


def test_default_stop_survives_reviews_restart_and_does_not_refill_failure():
    state = stopped_state()
    saved = json.loads(json.dumps(state))
    now = START + REVIEW_SECONDS * 3
    engine = PaperEngine(saved, now)
    engine.tick({}, {})
    a = saved["accounts"]["primary"]
    assert a["drawdown_pause"] and a["risk_peak"] == "100"
    assert a["risk_stop_id"] == 1 and a["cash"] == "64"
    a["cash"] = "4"
    engine = PaperEngine(saved, now + 1)
    engine.tick({}, {})
    assert a["cash"] == "4" and a["funding"] == "100" and a["replenishments"] == 0
    assert a["attempt"]["outcome"] == "failed"
    assert a["attempt_failures"] == 1
    retry = PaperEngine(saved, now + 2)
    retry.tick({}, {})
    assert not any(
        e["kind"] in {"failure_review", "attempt_failed", "replenishment"} for e in retry.events
    )


def test_recovery_requires_original_limit_and_is_idempotent_for_exact_stop():
    state = stopped_state()
    a = state["accounts"]["primary"]
    before = copy.deepcopy(a)
    with pytest.raises(ValueError, match="recover above"):
        PaperEngine(state, START + 2).recover_hard_stop("primary", 1)
    assert a == before
    # A hypothetical valuation recovery, not a funding action. Next UTC day clears daily pause.
    a["cash"] = "66"
    now = (int(START // 86400) + 1) * 86400
    PaperEngine(state, now).tick({}, {})
    assert a["drawdown_pause"] and risk_summary(a, False, now)["recoverable"]
    engine = PaperEngine(state, now)
    assert engine.recover_hard_stop("primary", 1)["status"] == "recovered"
    after = copy.deepcopy(a)
    retry = PaperEngine(state, now + 1)
    assert retry.recover_hard_stop("primary", 1)["status"] == "already_applied"
    assert not retry.events and after == a and a["risk_peak"] == "100"
    assert a["funding"] == "100" and a["attempt"]["number"] == 1
    a["cash"] = "64"
    PaperEngine(state, now + 2).tick({}, {})
    assert a["risk_stop_id"] == 2 and a["drawdown_pause"]
    with pytest.raises(ValueError, match="stop changed"):
        PaperEngine(state, now + 2).recover_hard_stop("primary", 1)


@pytest.mark.parametrize(
    "condition", ["stale", "operator_pause", "daily_pause", "cooldown", "failed"]
)
def test_recovery_cannot_bypass_other_controls(condition):
    state = stopped_state()
    a = state["accounts"]["primary"]
    a["cash"] = "90"
    now = (int(START // 86400) + 1) * 86400
    PaperEngine(state, now).tick({}, {})
    if condition == "stale":
        a["valuation_at"] = now - 6
    if condition == "operator_pause":
        state["paused"] = True
    if condition == "daily_pause":
        a["daily_pause"] = True
    if condition == "cooldown":
        a["cooldown_until"] = now + 10
    if condition == "failed":
        a["failure_pending"] = True
    before = copy.deepcopy(state)
    with pytest.raises(ValueError):
        PaperEngine(state, now).recover_hard_stop("primary", 1)
    assert state == before


def test_historical_policy_is_retained_until_explicit_adoption_and_unknown_fails_closed():
    state = initial_state(START)
    a = state["accounts"]["primary"]
    a.pop("risk_policy")
    a["cash"] = "64"
    PaperEngine(state, START + 1).tick({}, {})
    assert policy(a) == LEGACY_POLICY
    PaperEngine(state, START + REVIEW_SECONDS).review()
    assert not a["drawdown_pause"] and a["risk_peak"] == "64"
    saved_funding = a["funding"]
    adopt = PaperEngine(state, START + REVIEW_SECONDS + 1)
    assert adopt.adopt_hard_stop("primary")["status"] == "applied"
    assert a["risk_policy"] == HARD_STOP_POLICY and a["funding"] == saved_funding
    assert a["risk_peak"] == "64"
    repeat = PaperEngine(state, START + REVIEW_SECONDS + 2)
    assert repeat.adopt_hard_stop("primary")["status"] == "already_applied"
    assert not repeat.events
    a["risk_policy"] = "unknown-policy"
    a["cash"] = "4"
    PaperEngine(state, START + REVIEW_SECONDS + 3).tick({}, {})
    assert a["cash"] == "4" and a["funding"] == saved_funding
    assert risk_summary(a, False, START + REVIEW_SECONDS + 3)["blocked"]


def test_recovery_cannot_extend_the_age_of_the_underlying_held_quote():
    state = initial_state(START)
    buy(state)
    a = state["accounts"]["primary"]
    # Hypothetical previously latched stop; inventory has recovered, but its quote is aging.
    a.update(drawdown_pause=True, risk_stop_id=1)
    PaperEngine(state, START + 6.9).tick({"BTCUSD": frame(START + 2, sequence=2)}, {})
    assert risk_summary(a, False, START + 6.9)["recoverable"]
    with pytest.raises(ValueError, match="fresh"):
        PaperEngine(state, START + 7.1).recover_hard_stop("primary", 1)


def test_retained_public_depth_and_filters_preserve_risk_boundary():
    from pathlib import Path

    from trading.market import parse_book, parse_instruments
    from trading.paper_engine import filters

    capture = json.loads(
        (
            Path(__file__).resolve().parents[1] / "docs/evidence/first-market-capture.json"
        ).read_text()
    )
    instruments = parse_instruments(capture["observations"][0]["payload"], ["BTCUSD", "ETHUSD"])
    depths = {
        s: next(r for r in capture["observations"] if r["kind"] == "depth" and r["symbol"] == s)
        for s in ("BTCUSD", "ETHUSD")
    }

    def observed(symbol, at):
        row = depths[symbol]
        # Original prices, depth, sequence and instrument filters; synthetic receipt
        # times isolate the outage scenario. This is not a historical strategy run.
        return {
            "book": parse_book(row["payload"]),
            "raw": row["payload"],
            "observed": at,
            "source": capture["source"],
            "recorded_observed_at": row["observed_at"],
            "rules": filters(instruments[symbol]),
            "instrument": instruments[symbol],
            "base": instruments[symbol]["base"],
        }

    state = initial_state(START)
    a = state["accounts"]["primary"]
    e = PaperEngine(state, START)
    btc = observed("BTCUSD", START)
    e.value(a, {"BTCUSD": btc})
    feature = {**study()["BTCUSD"]["breakout-v1"], "atr": "100"}
    assert "reserved" in e.enter("primary", a, "BTCUSD", btc, feature)
    e = PaperEngine(state, START + 2)
    btc = observed("BTCUSD", START + 2)
    e.fill("primary", a, "BTCUSD", btc, {"BTCUSD": btc})
    assert "BTCUSD" in a["positions"]
    both = {s: observed(s, START + 3) for s in depths}
    e = PaperEngine(state, START + 3)
    assert e.value(a, both)
    feature = {**feature, "atr": "5"}
    assert "reserved" in e.enter("primary", a, "ETHUSD", both["ETHUSD"], feature)
    previous_cash = a["cash"]
    eth = observed("ETHUSD", START + 5)
    e = PaperEngine(state, START + 5)
    e.fill("primary", a, "ETHUSD", eth, {"ETHUSD": eth})
    assert set(a["positions"]) == {"BTCUSD"} and a["cash"] == previous_cash
    assert not a["pending"] and "BTCUSD" in a["valuation_issues"]
