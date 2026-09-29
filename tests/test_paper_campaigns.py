"""CP3 counterfactual accounts: isolation, causal data and explicit recovery."""

import copy
from decimal import Decimal as D

import pytest
from pydantic import ValidationError
from test_paper_economics import frames as paired_frames
from test_paper_engine import START, frame, study

from trading.execution_profiles import LEGACY_EXECUTION, PUBLIC_EXECUTION
from trading.paper_campaigns import CampaignSpec, control_account, create_campaign
from trading.paper_engine import HARD_STOP_POLICY, PaperEngine, initial_state, risk_summary


def spec(request_id="test-campaign-0001"):
    return CampaignSpec.model_validate(
        {
            "request_id": request_id,
            "name": "Ten paper comparisons",
            "accounts": [
                {
                    "label": f"Account {i + 1}",
                    "starting_cash": "50" if i % 2 else "100",
                    "strategy": ["breakout-v1", "responsive-v1", "selective-v1"][i % 3],
                    "execution_profile": LEGACY_EXECUTION,
                    "operating_daily_usd": "0",
                }
                for i in range(10)
            ],
        }
    )


def campaign_state():
    state = initial_state(START)
    e = PaperEngine(state, START)
    result = create_campaign(e, spec())
    return state, result["campaign"]["accounts"], e


def advance(state, offset, price="100", sequence=1, studies=None):
    e = PaperEngine(state, START + offset)
    e.tick({"BTCUSD": frame(START + offset, price, sequence)}, studies or {})
    e.assert_invariants()
    return e


def test_funding_and_identity_are_isolated_idempotent_and_bounded():
    state = initial_state(START)
    original = copy.deepcopy(state["accounts"])
    e = PaperEngine(state, START)
    result = create_campaign(e, spec())
    names = result["campaign"]["accounts"]
    assert len(names) == len(set(names)) == 10
    assert {k: state["accounts"][k] for k in original} == original
    for i, name in enumerate(names):
        a = state["accounts"][name]
        assert a["cash"] == a["funding"] == ("50" if i % 2 else "100")
        assert a["risk_policy"] == HARD_STOP_POLICY and not a["replenishments"]
        assert not a["pending"] and not a["positions"]
    before, events = copy.deepcopy(state), copy.deepcopy(e.events)
    assert create_campaign(e, spec())["status"] == "already_applied"
    assert state == before and e.events == events
    changed = spec().model_copy(update={"name": "Changed request"})
    with pytest.raises(ValueError, match="different configuration"):
        create_campaign(e, changed)
    with pytest.raises(ValueError, match="one ten-account"):
        create_campaign(e, spec("test-campaign-0002"))
    assert state == before


@pytest.mark.parametrize(
    "change",
    [
        {"starting_cash": "1000"},
        {"execution_profile": "invented-cheaper-fees"},
        {"strategy": "llm-orders"},
        {"operating_daily_usd": 0.5},
        {"operating_daily_usd": "-1"},
        {"label": "   "},
        {"risk_limit": "0.99"},
    ],
)
def test_invalid_account_contracts_cannot_expand_permissions(change):
    payload = spec().model_dump()
    payload["accounts"][0].update(change)
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(payload)


def test_distinct_labels_exact_count_and_unknown_operating_cost():
    payload = spec().model_dump()
    payload["accounts"][0]["operating_daily_usd"] = None
    assert CampaignSpec.model_validate(payload).accounts[0].operating_daily_usd is None
    payload["accounts"][1]["label"] = " account 1 "
    with pytest.raises(ValidationError, match="distinct"):
        CampaignSpec.model_validate(payload)
    payload["accounts"] = payload["accounts"][:9]
    with pytest.raises(ValidationError):
        CampaignSpec.model_validate(payload)


def test_ten_accounts_share_books_without_sharing_cash_inventory_or_fees():
    state, names, _ = campaign_state()
    advance(state, 0, studies=study())
    for name in names:
        a = state["accounts"][name]
        assert D(a["pending"]["BTCUSD"]["reserved"]) <= D(a["funding"]) / 2
    fill = advance(state, 2, sequence=2)
    assert {e["account"] for e in fill.events if e["kind"] == "fill"} >= set(names)
    for name in names:
        a = state["accounts"][name]
        assert D(a["cash"]) + D(a["positions"]["BTCUSD"]["cost"]) == D(a["funding"])
        assert D(a["fees"]) > 0 and not a["pending"]
    balances = {n: copy.deepcopy(state["accounts"][n]) for n in names}
    advance(state, 3, sequence=2)
    for name in names:
        a = state["accounts"][name]
        assert a["cash"] == balances[name]["cash"]
        assert a["fees"] == balances[name]["fees"]
    advance(state, 4, "98", 3)
    advance(state, 6, "98", 4)
    for name in names:
        a = state["accounts"][name]
        assert a["closed"] == 1 and not a["positions"]
        assert D(a["realized"]) == D(a["cash"]) - D(a["funding"])


def test_individual_and_global_entry_pauses_release_only_buy_reservations():
    state, names, _ = campaign_state()
    advance(state, 0, studies=study())
    e = PaperEngine(state, START)
    control_account(e, names[0], "pause", 0, {})
    assert not state["accounts"][names[0]]["pending"]
    assert all(state["accounts"][n]["pending"] for n in names[1:])
    assert "this account" in risk_summary(state["accounts"][names[0]], False, START)["reason"]
    assert control_account(e, names[0], "pause", 0, {})["status"] == "already_applied"
    with pytest.raises(ValueError, match="changed"):
        control_account(e, names[0], "resume", 0, {})
    advance(state, 2, sequence=2)
    assert not state["accounts"][names[0]]["positions"]
    assert all(state["accounts"][n]["positions"] for n in names[1:])
    state["paused"] = True
    control_account(PaperEngine(state, START + 3), names[0], "resume", 1, {})
    assert state["paused"]
    advance(state, 4, "98", 3)
    advance(state, 6, "98", 4)
    assert all(not state["accounts"][n]["positions"] for n in names)


def test_rolled_back_account_failure_retains_balances_and_healthy_siblings(monkeypatch):
    state, names, _ = campaign_state()
    advance(state, 0, studies=study())
    before = copy.deepcopy(state["accounts"][names[0]])
    original = PaperEngine.tick_account

    def fail_after_fill(e, name, a, frames, features):
        original(e, name, a, frames, features)
        if name == names[0]:
            raise ValueError("synthetic account-step failure")

    with monkeypatch.context() as m:
        m.setattr(PaperEngine, "tick_account", fail_after_fill)
        e = advance(state, 2, sequence=2)
    a = state["accounts"][names[0]]
    assert a["cash"] == before["cash"] and a["pending"] == before["pending"]
    assert not a["positions"] and a["fault"]["code"] == "ValueError"
    assert not any(x["kind"] == "fill" and x["account"] == names[0] for x in e.events)
    assert all(state["accounts"][n]["positions"] for n in names[1:])
    risk = risk_summary(a, False, START + 2)
    assert "processing" in risk["reason"] and not risk["recoverable"]
    control_account(
        PaperEngine(state, START + 2),
        names[0],
        "recover",
        1,
        {"BTCUSD": frame(START + 2, sequence=2)},
    )
    advance(state, 3, sequence=3)
    assert state["accounts"][names[0]]["positions"]
    assert state["accounts"][names[0]]["funding"] == before["funding"]


def test_preexisting_financial_corruption_still_stops_the_whole_writer():
    state, names, _ = campaign_state()
    state["accounts"][names[0]]["cash"] = "-1"
    with pytest.raises(ValueError, match="conservation"):
        advance(state, 0)


def test_reordered_books_signals_and_tick_clock_cannot_fill_or_rewind():
    state, names, _ = campaign_state()
    advance(state, 0, sequence=10, studies=study(10))
    advance(state, 2, sequence=9, studies=study(9))
    assert all(not state["accounts"][n]["positions"] for n in names)
    assert all(state["accounts"][n]["last_decision"]["BTCUSD"]["bar"] == 10 for n in names)
    advance(state, 3, sequence=11)
    before = copy.deepcopy(state)
    assert not advance(state, 1, sequence=12).events and state == before
    previous = state["accounts"][names[0]]["equity"]
    advance(state, 4, "50", 10)
    assert state["accounts"][names[0]]["equity"] == previous
    assert not state["accounts"][names[0]]["valuation_fresh"]


def test_reordered_and_conflicting_books_cannot_reprice_economics_controls():
    state, _, _ = campaign_state()
    for offset, sequence in [(0, 10), (2, 11)]:
        PaperEngine(state, START + offset).tick(paired_frames(START + offset, sequence), {})
    control = next(iter(state["economics"]["active"]["benchmarks"].values()))
    equity = control["equity"]
    PaperEngine(state, START + 3).tick(paired_frames(START + 3, 9, "50"), {})
    assert control["equity"] == equity and not control["fresh"]
    PaperEngine(state, START + 4).tick(paired_frames(START + 4, 11, "50"), {})
    assert control["equity"] == equity and not control["fresh"]


def test_stale_held_symbol_cancels_new_risk_and_resume_cannot_clear_loss_stop():
    state, names, _ = campaign_state()
    advance(state, 0, studies=study())
    advance(state, 2, sequence=2)
    a = state["accounts"][names[0]]
    a.update(drawdown_pause=True, risk_stop_id=1, entries_paused=True)
    control_account(PaperEngine(state, START + 3), names[0], "resume", 0, {})
    assert a["drawdown_pause"] and a["risk_peak"] == "100"
    e = PaperEngine(state, START + 3)
    e.tick({}, {})
    assert not a["valuation_fresh"]
    assert all(state["accounts"][n]["funding"] in {"50", "100"} for n in names)
    with pytest.raises(ValueError, match="frozen"):
        e.set_economics(names[0], PUBLIC_EXECUTION, "0", 0)


def test_underfunded_campaign_failure_is_retained_without_sibling_funding():
    state, names, _ = campaign_state()
    a = state["accounts"][names[0]]
    a["cash"] = a["equity"] = "4"
    e = advance(state, 0, studies=study())
    assert a["attempt"]["outcome"] == "failed" and a["funding"] == "100"
    assert not a["replenishments"] and a["failure_pending"]
    assert not any(x["kind"] == "replenishment" for x in e.events)
    assert all(state["accounts"][n]["pending"] for n in names[1:])
