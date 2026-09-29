import copy
from decimal import Decimal as D

import pytest

from trading.market import parse_book
from trading.paper_engine import REVIEW_SECONDS, PaperEngine, initial_state
from trading.paper_strategy import VARIANTS

START = 1_800_000_000.0


def frame(now=START, price="100", sequence=1, quantity="100"):
    p = D(price)
    raw = {
        "lastUpdateId": sequence,
        "bids": [[str(p), quantity]],
        "asks": [[str(p + D("0.02")), quantity]],
    }
    return {
        "book": parse_book(raw),
        "raw": raw,
        "observed": now,
        "base": "BTC",
        "instrument": {"symbol": "BTCUSD"},
        "rules": {
            "step": D("0.00001"),
            "tick": D("0.01"),
            "min_qty": D("0.00001"),
            "max_qty": D(100),
            "min_notional": D(1),
            "min_price": D("0.01"),
            "max_price": D(1_000_000),
        },
    }


def study(bar=1):
    return {
        "BTCUSD": {
            v: {
                "eligible": True,
                "bar_open_ms": bar,
                "atr": "1",
                "reason": "Test breakout",
                "version": v,
            }
            for v in VARIANTS
        }
    }


def tick(state, now, price="100", sequence=1, studies=None):
    engine = PaperEngine(state, now)
    engine.tick({"BTCUSD": frame(now, price, sequence)}, studies or study())
    return engine


def buy(state):
    tick(state, START)
    return tick(state, START + 2, sequence=2)


def test_intent_reserves_cash_but_does_not_fill_until_future_observation():
    state = initial_state(START)
    first = tick(state, START)
    a = state["accounts"]["primary"]
    assert a["cash"] == "100" and not a["positions"]
    assert D(a["pending"]["BTCUSD"]["reserved"]) <= 50
    assert not any(e["kind"] == "fill" for e in first.events)
    tick(state, START + 0.5)
    assert not a["positions"]
    result = tick(state, START + 2, sequence=2)
    assert a["positions"] and not a["pending"]
    assert any(e["kind"] == "fill" for e in result.events)
    assert D(a["cash"]) + D(a["positions"]["BTCUSD"]["cost"]) == 100


def test_stop_closes_with_fees_and_no_double_execution():
    state = initial_state(START)
    buy(state)
    tick(state, START + 5, "98", 3)
    result = tick(state, START + 7, "97.9", 4)
    a = state["accounts"]["primary"]
    assert not a["positions"]
    assert a["closed"] == 1 and a["wins"] == 0
    assert D(a["realized"]) == D(a["cash"]) - 100
    assert D(a["fees"]) > 0
    before = a["cash"]
    again = tick(state, START + 9, "97.9", 4)
    assert before == a["cash"]
    assert not any(e["kind"] == "fill" for e in again.events)
    assert len([e for e in result.events if e["kind"] == "trade_closed"]) == 4


def test_partial_fills_cancel_remainder_and_do_not_reconsume_same_book():
    state = initial_state(START)
    tick(state, START)
    engine = PaperEngine(state, START + 2)
    engine.tick({"BTCUSD": frame(START + 2, sequence=2, quantity="1")}, study())
    a = state["accounts"]["primary"]
    assert D(a["positions"]["BTCUSD"]["quantity"]) == D("0.1")
    assert not a["pending"]
    fills = [e for e in engine.events if e["kind"] == "fill"]
    assert all(e["body"]["partial"] for e in fills)
    tick(state, START + 5, "98", 3)
    partial = PaperEngine(state, START + 7)
    partial.tick({"BTCUSD": frame(START + 7, "98", 4, "0.5")}, study())
    remaining = D(a["positions"]["BTCUSD"]["quantity"])
    # A new exit intent can be created, but the same liquidity cannot fill it twice.
    same = PaperEngine(state, START + 9)
    same.tick({"BTCUSD": frame(START + 9, "98", 4, "0.5")}, study())
    assert D(a["positions"]["BTCUSD"]["quantity"]) == remaining


def test_replenishment_strict_threshold_review_first_and_losses_retained():
    state = initial_state(START)
    a = state["accounts"]["primary"]
    a.update(cash="5", equity="5")
    engine = PaperEngine(state, START + 1)
    engine.tick({}, {})
    assert a["replenishments"] == 0
    a.update(cash="4.99", equity="4.99")
    engine = PaperEngine(state, START + 2)
    engine.tick({}, {})
    events = [e for e in engine.events if e["account"] == "primary"]
    kinds = [e["kind"] for e in events]
    assert kinds.index("failure_review") < kinds.index("replenishment")
    assert a["cash"] == "100" and a["funding"] == "195.01"
    assert a["attempt_failures"] == 1 and a["replenishments"] == 1
    assert a["version"] == "selective-v1"
    assert a["cooldown_until"] == START + 2 + 3600
    assert D(a["max_drawdown"]) >= D("0.9501")
    PaperEngine(state, START + 3).tick({}, {})
    assert a["replenishments"] == 1


def test_cash_below_five_does_not_refill_an_invested_account():
    state = initial_state(START)
    buy(state)
    a = state["accounts"]["primary"]
    a["cash"] = "4"
    tick(state, START + 3, sequence=3)
    assert D(a["equity"]) > 5
    assert a["replenishments"] == 0


def test_stale_position_has_no_replenishment_or_imaginary_exit():
    state = initial_state(START)
    buy(state)
    a = state["accounts"]["primary"]
    a.update(cash="0", equity="1")
    result = PaperEngine(state, START + 60)
    result.tick({}, {})
    assert a["positions"] and not a["valuation_fresh"]
    assert not any(e["kind"] in ("fill", "replenishment") for e in result.events)


def test_unexitable_dust_cannot_establish_a_liquidation_target():
    state = initial_state(START)
    buy(state)
    a = state["accounts"]["primary"]
    a["cash"] = "1000"
    result = tick(state, START + 4, "0.02", 3)
    assert not a["valuation_fresh"]
    assert a["attempt_wins"] == 0
    assert not any(e["kind"] == "attempt_won" for e in result.events)


def test_success_is_account_target_not_trade_win_rate_and_counted_once():
    state = initial_state(START)
    a = state["accounts"]["primary"]
    a["cash"] = "1000"
    result = PaperEngine(state, START + 1)
    result.tick({}, {})
    assert a["attempt_wins"] == 1 and a["closed"] == 0
    assert a["attempt"]["outcome"] == "won" and a["cash"] == "1000"
    assert any(e["kind"] == "attempt_won" for e in result.events)
    PaperEngine(state, START + 2).tick({}, {})
    assert a["attempt_wins"] == 1


def test_pending_entry_expires_after_restart_or_gap_without_fill():
    state = initial_state(START)
    tick(state, START)
    result = tick(state, START + 100, sequence=2)
    a = state["accounts"]["primary"]
    assert a["cash"] == "100" and not a["pending"] and not a["positions"]
    assert any(e["kind"] == "observation_gap" for e in result.events)


def test_pause_stops_new_entries_but_still_closes_existing_positions():
    state = initial_state(START)
    buy(state)
    state["paused"] = True
    tick(state, START + 700, "100", 3)
    tick(state, START + 702, "100", 4)
    a = state["accounts"]["primary"]
    assert a["closed"] == 1 and not a["positions"]
    tick(state, START + 1500, "100", 5, study(2))
    assert not a["pending"]


def test_daily_loss_fuse_does_not_replenish_or_increase_risk():
    state = initial_state(START)
    a = state["accounts"]["primary"]
    a["cash"] = "84"
    tick(state, START)
    assert a["daily_pause"] and not a["pending"]
    assert not a["replenishments"]


def test_limit_price_and_changed_filters_reject_without_spending():
    state = initial_state(START)
    tick(state, START)
    tick(state, START + 2, "101", 2)
    a = state["accounts"]["primary"]
    assert a["cash"] == "100" and not a["positions"]
    tick(state, START + 60, "100", 3, study(2))
    next_frame = frame(START + 62, sequence=4)
    next_frame["rules"]["min_notional"] = D(200)
    PaperEngine(state, START + 62).tick({"BTCUSD": next_frame}, study(2))
    assert a["cash"] == "100" and not a["positions"]


def test_four_hour_reviews_do_not_force_promotion_or_replay_missed_windows():
    state = initial_state(START)
    engine = PaperEngine(state, START + REVIEW_SECONDS * 3 + 5)
    engine.tick({}, {})
    assert state["review_count"] == 1
    assert state["promotion_count"] == 0
    assert state["review_history"][-1]["missed_intervals"] == 2
    assert state["next_review"] == engine.now + REVIEW_SECONDS


def test_two_disjoint_forward_windows_required_for_promotion():
    state = initial_state(START)
    now = START + REVIEW_SECONDS * 2
    for version in VARIANTS:
        a = state["accounts"][version]
        for window in range(2):
            for i in range(10):
                a["recent_trades"].append(
                    {
                        "opened_at": START + window * REVIEW_SECONDS + i * 120,
                        "closed_at": START + window * REVIEW_SECONDS + i * 120 + 60,
                        "pnl": "1" if version == "selective-v1" else "0.1",
                        "cost": "50",
                        "fees": "0.2",
                    }
                )
    one_window = copy.deepcopy(state)
    for a in one_window["accounts"].values():
        a["recent_trades"] = a["recent_trades"][:10]
    PaperEngine(one_window, now).review()
    assert one_window["promotion_count"] == 0
    PaperEngine(state, now).review()
    assert state["accounts"]["primary"]["version"] == "selective-v1"
    assert state["promotion_count"] == 1


def test_unbalanced_journal_cannot_be_emitted():
    engine = PaperEngine(initial_state(START), START)
    with pytest.raises(ValueError, match="Unbalanced"):
        engine.emit("bad", "primary", {}, [engine.line("USD", "cash", D(1))])
