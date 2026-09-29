"""Whole-account fixtures are hypothetical; they are not trading performance."""

import copy
from decimal import Decimal as D

import pytest
from test_paper_engine import START, buy, frame, study
from test_paper_risk import asset_frame

from trading import paper_economics as eco
from trading.execution_profiles import LEGACY_EXECUTION, PROFILES, PUBLIC_EXECUTION, execution
from trading.paper_engine import PaperEngine, initial_state


def frames(at, sequence=1, price="100"):
    return {s: asset_frame(s, at, sequence, price) for s in ("BTCUSD", "ETHUSD")}


def marked_state(capital="100", profile=LEGACY_EXECUTION):
    state = initial_state(START, capital, profile)
    for a in state["accounts"].values():
        a["operating_daily_usd"] = "0"
    PaperEngine(state, START).tick(frames(START), {})
    return state


def windows(monkeypatch):
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = marked_state()
    for i in range(1, 21):
        for name, a in state["accounts"].items():
            gain = D("0.1") if name == "selective-v1" else D("0.01")
            a["cash"] = str(D(a["cash"]) + gain)
        PaperEngine(state, START + i).tick(frames(START + i, i + 1), {})
    return state


def test_account_returns_rank_amounts_not_completed_trade_percentages(monkeypatch):
    state = windows(monkeypatch)
    result = state["economics"]["completed"][0]["scores"]
    assert D(result["selective-v1"]["return"]) > D(result["breakout-v1"]["return"])
    assert result["selective-v1"]["rank"] == 1
    assert result["selective-v1"]["trades"] == 0
    PaperEngine(state, START + 20).review()
    assert state["accounts"]["primary"]["version"] == "selective-v1"
    assert state["review_history"][-1]["evaluation"] == eco.VERSION


@pytest.mark.parametrize(
    "defect", ["one_window", "gap", "profile", "capital", "funding", "operating_unknown"]
)
def test_promotion_requires_matched_complete_economics(monkeypatch, defect):
    state = windows(monkeypatch)
    if defect == "one_window":
        state["economics"]["completed"] = state["economics"]["completed"][:1]
    else:
        s = state["economics"]["completed"][0]["scores"]["selective-v1"]
        if defect == "gap":
            s["eligible"] = False
        if defect == "profile":
            s["execution_profile"] = PUBLIC_EXECUTION
        if defect == "capital":
            s["starting_capital"] = "50"
        if defect == "funding":
            s["funding_change"] = "100"
        if defect == "operating_unknown":
            s["total_pnl"] = None
    PaperEngine(state, START + 20).review()
    assert state["promotion_count"] == 0


def test_open_loss_and_cross_window_trade_are_in_whole_account_results(monkeypatch):
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = marked_state()
    buy(state)
    a = state["accounts"]["primary"]
    for i in range(3, 21):
        PaperEngine(state, START + i).tick(frames(START + i, i + 1, "99.5"), {})
    assert a["positions"] and a["closed"] == 0
    first = state["economics"]["completed"][0]["scores"]["primary"]
    assert D(first["net_pnl"]) < 0 and D(first["return"]) < 0
    live = eco.sample(a, START + 20)
    assert D(live["unrealized"]) < 0
    assert D(live["realized"]) + D(live["unrealized"]) == D(live["net_pnl"])
    assert first["trades"] == 0


def test_funding_changes_are_not_profit_or_return(monkeypatch):
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = marked_state()
    a = state["accounts"]["primary"]
    a.update(cash="150", funding="150", units="150")  # Explicit external-flow fixture.
    for i in range(1, 11):
        PaperEngine(state, START + i).tick(frames(START + i, i + 1), {})
    result = state["economics"]["completed"][0]["scores"]["primary"]
    assert D(result["net_pnl"]) == 0 and D(result["return"]) == 0
    assert result["rank"] is None and D(result["funding_change"]) == 50


def test_missing_intermediate_marks_and_gaps_do_not_rank(monkeypatch):
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = marked_state()
    buy(state)
    PaperEngine(state, START + 5).tick({}, {})
    PaperEngine(state, START + 40).tick(frames(START + 40, 4), {})
    result = state["economics"]["completed"][0]["scores"]["primary"]
    assert not result["eligible"] and result["rank"] is None
    assert any("gap" in reason for reason in result["reasons"])
    historical = copy.deepcopy(state["economics"]["completed"])
    PaperEngine(state, START + 41).tick(frames(START + 41, 5), {})
    assert state["economics"]["completed"] == historical


def test_costs_are_attributed_not_charged_twice(monkeypatch):
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = marked_state()
    buy(state)
    for i in range(3, 11):
        PaperEngine(state, START + i).tick(frames(START + i, i + 1), {})
    result = state["economics"]["completed"][0]["scores"]["primary"]
    assert D(result["gross_reference_pnl"]) - D(result["execution_cost"]) == D(result["net_pnl"])
    assert result["net_pnl"] == result["total_pnl"]
    assert D(result["execution_cost"]) > D(result["fees_paid"]) > 0


def test_operating_cost_is_explicit_prospective_and_does_not_debit_cash(monkeypatch):
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = marked_state()
    a = state["accounts"]["primary"]
    e = PaperEngine(state, START)
    e.set_economics("primary", LEGACY_EXECUTION, "8.64", 0)
    for i in range(1, 21):
        PaperEngine(state, START + i).tick(frames(START + i, i + 1), {})
    first, last = state["economics"]["completed"]
    assert first["scores"]["primary"]["operating_cost"] is None
    assert D(last["scores"]["primary"]["operating_cost"]) == D("0.001")
    assert D(last["scores"]["primary"]["total_pnl"]) == D("-0.001")
    assert a["cash"] == "100" and a["funding"] == "100"


def test_quote_profile_change_is_flat_only_and_retry_safe():
    state = marked_state()
    a = state["accounts"]["primary"]
    e = PaperEngine(state, START)
    assert e.set_economics("primary", PUBLIC_EXECUTION, "0", 0)["status"] == "applied"
    assert e.set_economics("primary", PUBLIC_EXECUTION, "0", 0)["status"] == "already_applied"
    with pytest.raises(ValueError, match="changed"):
        e.set_economics("primary", LEGACY_EXECUTION, "0", 0)
    buy(state)
    before = copy.deepcopy(a)
    with pytest.raises(ValueError, match="flat"):
        e.set_economics("primary", LEGACY_EXECUTION, "0", 1)
    assert a == before
    assert a["pending"] == {} and a["fees"] != "0"


def test_unknown_operating_cost_and_zero_trades_are_not_fabricated(monkeypatch):
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = initial_state(START)
    for i in range(11):
        PaperEngine(state, START + i).tick(frames(START + i, i + 1), {})
    result = state["economics"]["completed"][0]["scores"]["primary"]
    assert result["operating_cost"] is None and result["total_pnl"] is None
    assert D(result["return"]) == 0 and result["trades"] == 0


def test_default_history_uses_original_fees_and_public_scenario_uses_taker():
    old = initial_state(START)
    current = initial_state(START, "100", PUBLIC_EXECUTION)
    for a in old["accounts"].values():
        a.pop("execution_profile")
    old_events = buy(old).events
    current_events = buy(current).events
    for events, rate in [(old_events, D("0.001")), (current_events, D("0.0002"))]:
        fills = [e["body"] for e in events if e["kind"] == "fill"]
        assert fills and all(D(f["fee"]) == D(f["gross"]) * rate for f in fills)
        assert all(f["liquidity_role"] == "taker" and f["fee_asset"] == "USD" for f in fills)
    assert PROFILES[PUBLIC_EXECUTION].fee("BNBUSD") == D("0.0001")
    with pytest.raises(ValueError):
        PROFILES[PUBLIC_EXECUTION].fee("BTCUSDT")


def test_unsupported_fee_asset_refuses_fill_and_cancel_is_idempotent():
    state = marked_state()
    e = PaperEngine(state, START)
    e.tick(frames(START), study())
    a = state["accounts"]["primary"]
    a["pending"]["BTCUSD"]["fee_asset"] = "BNB"
    before = a["cash"]
    e = PaperEngine(state, START + 2)
    e.fill("primary", a, "BTCUSD", frame(START + 2, sequence=2), frames(START + 2, 2))
    assert a["cash"] == before and not a["positions"] and not a["pending"]
    count = len(e.events)
    e.cancel("primary", a, "BTCUSD", "Repeated cancel")
    e.fill("primary", a, "BTCUSD", frame(START + 2, sequence=2), frames(START + 2, 2))
    assert len(e.events) == count


def test_benchmark_uses_later_book_partial_fill_filters_and_dust():
    b = eco.new_benchmark("50", PUBLIC_EXECUTION, START)
    assert eco.benchmark_tick(b, frames(START), START) == []
    assert b["cash"] == "50"
    thin = {s: asset_frame(s, START + 2, 2) for s in ("BTCUSD", "ETHUSD")}
    thin["BTCUSD"] = frame(START + 2, sequence=2, quantity="0.01")
    receipts = eco.benchmark_tick(b, thin, START + 2)
    assert D(receipts[0]["unfilled_cancelled"]) > 0
    assert not b["fresh"]  # Tiny holding cannot be fully liquidated above minimum.
    cash = b["cash"]
    assert eco.benchmark_tick(b, thin, START + 2) == [] and cash == b["cash"]
    no_data = eco.new_benchmark("50", PUBLIC_EXECUTION, START)
    eco.benchmark_tick(no_data, {}, START + 16)
    assert no_data["cash"] == "50" and not no_data["coverage"]


def test_current_results_disclose_disconnection_and_keep_completed_history(monkeypatch):
    state = windows(monkeypatch)
    r = eco.report(state, START + 21, False)
    assert r["accounts"]["primary"]["net_pnl"] is None
    assert r["current"]["scores"]["primary"]["return"] is None
    assert r["current"]["scores"]["primary"]["exposure_return"] is None
    assert r["completed"] == state["economics"]["completed"]


def test_zero_nav_replenishment_cannot_appear_as_an_economic_recovery(monkeypatch):
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = marked_state()
    a = state["accounts"]["primary"]
    a.pop("risk_policy")
    a.update(cash="0", equity="0")
    PaperEngine(state, START + 1).tick(frames(START + 1, 2), {})
    assert a["cash"] == "100"  # Existing explicitly historical policy remains unchanged.
    assert eco.sample(a, START + 1)["nav"] is None


def test_zero_nav_end_reports_loss_without_crashing_ranking(monkeypatch):
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = marked_state()
    a = state["accounts"]["primary"]
    a.pop("risk_policy")
    a.update(cash="0", equity="0")
    for i in range(1, 11):
        PaperEngine(state, START + i).tick(frames(START + i, i + 1), {})
    s = state["economics"]["completed"][0]["scores"]["primary"]
    assert s["return"] is None and s["rank"] is None
    assert D(s["net_pnl"]) == D("-100")


def test_pristine_fifty_dollar_universe_pairs_use_same_capital_and_costs():
    state = initial_state(START, "50", PUBLIC_EXECUTION)
    e = PaperEngine(state, START)
    e.universe_experiment(["BTCUSD", "ETHUSD"])
    for name in ("universe-control-v1", "universe-wide-v1"):
        assert state["accounts"][name]["starting_capital"] == "50"
        assert execution(state["accounts"][name]).id == PUBLIC_EXECUTION
    funding = [r for r in e.events if r["kind"] == "research_account_created"]
    assert all(r["body"]["amount"] == "50" for r in funding)


def test_unknown_execution_on_primary_does_not_crash_healthy_siblings(monkeypatch):
    state = windows(monkeypatch)
    state["accounts"]["primary"]["execution_profile"] = "unsupported"
    PaperEngine(state, START + 20).review()
    assert state["promotion_count"] == 0


def test_unequal_trade_sizes_do_not_override_account_return_ranking(monkeypatch):
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = marked_state()
    # 2% on $5 is $0.10; 1% on $50 is $0.50. Both started with $100.
    for name, gain, cost in [("responsive-v1", "0.10", "5"), ("selective-v1", "0.50", "50")]:
        a = state["accounts"][name]
        a["cash"] = str(D(a["cash"]) + D(gain))
        a["realized"] = gain
        a["recent_trades"] = [{"pnl": gain, "cost": cost}]
    for i in range(1, 11):
        PaperEngine(state, START + i).tick(frames(START + i, i + 1), {})
    r = state["economics"]["completed"][0]["scores"]
    assert r["selective-v1"]["rank"] < r["responsive-v1"]["rank"]
    assert D(r["selective-v1"]["return"]) == D("0.005")


def test_legacy_fee_profile_keeps_original_commission_and_delay():
    state = initial_state(START)
    result = buy(state)
    for event in result.events:
        if event["kind"] == "fill":
            row = event["body"]
            assert D(row["fee"]) == D(row["gross"]) * D("0.001")
    assert PROFILES[LEGACY_EXECUTION].slippage == "0.0002"
    assert PROFILES[LEGACY_EXECUTION].latency_seconds == 1


def test_real_retained_depth_filters_support_both_fee_scenarios():
    import json
    from pathlib import Path

    from trading.market import parse_book, parse_instruments
    from trading.paper_engine import filters

    raw = json.loads(
        (
            Path(__file__).resolve().parents[1] / "docs/evidence/first-market-capture.json"
        ).read_text()
    )
    instruments = parse_instruments(raw["observations"][0]["payload"], ["BTCUSD", "ETHUSD"])
    books = {
        s: next(r for r in raw["observations"] if r["kind"] == "depth" and r["symbol"] == s)
        for s in instruments
    }
    for profile in (LEGACY_EXECUTION, PUBLIC_EXECUTION):
        for capital in ("50", "100"):
            b = eco.new_benchmark(capital, profile, START)
            for delay in (0, 2):
                observed = {
                    s: {
                        "book": parse_book(r["payload"]),
                        "raw": r["payload"],
                        "observed": START + delay,
                        "rules": filters(instruments[s]),
                        "instrument": instruments[s],
                    }
                    for s, r in books.items()
                }
                receipts = eco.benchmark_tick(b, observed, START + delay)
            assert b["fresh"] and D(b["cash"]) >= 0 and receipts
            assert all(
                D(r["fee"]) == D(r["gross"]) * PROFILES[profile].fee(r["symbol"]) for r in receipts
            )
            assert D(b["equity"]) < D(capital)  # Same prices: costs, not a return advantage.


def test_ranking_accounts_for_operating_cost_relative_to_window_capital(monkeypatch):
    monkeypatch.setattr(eco, "WINDOW_SECONDS", 10)
    state = initial_state(START)
    for a in state["accounts"].values():
        a["operating_daily_usd"] = "8640"  # $1 per 10s fixture.
    state["accounts"]["responsive-v1"].update(cash="200", realized="100")
    PaperEngine(state, START).tick(frames(START), {})
    state["accounts"]["responsive-v1"].update(cash="200.98", realized="100.98")
    state["accounts"]["selective-v1"].update(cash="100.50", realized="0.50")
    for i in range(1, 11):
        PaperEngine(state, START + i).tick(frames(START + i, i + 1), {})
    r = state["economics"]["completed"][0]["scores"]
    assert D(r["selective-v1"]["return"]) > D(r["responsive-v1"]["return"])
    assert r["responsive-v1"]["rank"] < r["selective-v1"]["rank"]


def test_two_window_selection_compounds_instead_of_adding_returns(monkeypatch):
    state = windows(monkeypatch)
    for v, returns in [("selective-v1", ["0.50", "0.01"]), ("responsive-v1", ["0.25", "0.25"])]:
        for window, r in zip(state["economics"]["completed"], returns, strict=True):
            window["scores"][v].update({"return": r, "total_return": r, "total_pnl": "1"})
    PaperEngine(state, START + 20).review()
    assert state["accounts"]["primary"]["version"] == "responsive-v1"
