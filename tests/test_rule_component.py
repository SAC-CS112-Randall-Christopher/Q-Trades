"""The same frozen optional component reaches contracts, runtime and ordinary paper."""

import copy
from collections import deque
from decimal import Decimal

import pytest
from test_autonomous_lab import admit, close_window, make_lab, tick_lab
from test_memory_quality import fitted
from test_paper_engine import START, frame
from test_paper_store import pg_store as pg_store

from trading.autonomous_spec import LabProposal, MemoryFilter, RuleSpec, changes
from trading.evidence_runtime import EvidenceRecorder, feature_reproduction
from trading.experiment_registry import fingerprint
from trading.memory_quality import filtered_feature
from trading.paper_engine import PaperEngine, account, initial_state
from trading.paper_strategy import VARIANTS, Bar, features
from trading.research_evidence import digest
from trading.rule_components import reviewed_feature


def component():
    return MemoryFilter(artifact=fitted()[3], marginal_daily_usd="1")


def rejection_case():
    _, rows, _, artifact = fitted()
    for row in artifact["library"]:
        row["net_bps"] = -50  # Declared harmful synthetic labels, never market evidence.
    artifact.pop("sha256")
    artifact["sha256"] = digest(artifact)
    end = int(START // 60) * 60000
    prices = [Decimal("99.8") + Decimal(i) / 3000 for i in range(389)]
    p = Decimal(100)
    prices.append(p)
    for ret in rows[-1]["descriptor"]["returns_bps"]:
        p *= 1 + Decimal(str(ret)) / 10000
        prices.append(p)
    bars = [
        Bar(
            end - (400 - i) * 60000,
            p,
            p + Decimal(".0001"),
            p - Decimal(".0001"),
            p,
            Decimal(100) if i == 399 else Decimal(10),
            end - (399 - i) * 60000 - 1,
        )
        for i, p in enumerate(prices)
    ]
    spec = RuleSpec(
        version="reviewed-lab-rules-v3",
        entry_filter=MemoryFilter(artifact=artifact, marginal_daily_usd="0"),
    )
    return bars, spec


def test_actual_order_intent_and_replay_use_same_causal_filter(tmp_path):
    bars, child = rejection_case()
    parent = RuleSpec()
    f = frame(START, str(bars[-1].close))
    base = reviewed_feature(bars, START, parent, "legacy-v1", f)
    filtered = reviewed_feature(bars, START, child, "legacy-v1", f)
    assert base["eligible"] and not filtered["eligible"]
    state = initial_state(START - 3600)
    state["next_review"] = START + 7200
    state["accounts"] = {}
    for name, spec, feature in (("parent", parent, base), ("child", child, filtered)):
        a = account(feature["version"], START - 3600)
        a.update(rule_spec=spec.model_dump(), symbols=["BTCUSD"], admitted_at=START-3600)
        state["accounts"][name] = a
    study = {"BTCUSD": {v: features(bars, START, v) for v in VARIANTS}}
    study["BTCUSD"].update({base["version"]: base, filtered["version"]: filtered})
    recorder = EvidenceRecorder(tmp_path / "component-evidence.sqlite")
    packet = recorder.prepare(
        START,
        {"BTCUSD": f},
        study,
        {"BTCUSD": bars},
        {"BTCUSD": START},
        0,
        {},
        state,
        [],
        {"BTCUSD": deque()},
        {},
    )
    reproduction = feature_reproduction(packet)
    assert reproduction["closed_bar_features"]["BTCUSD"]["component_matched"]
    engine = PaperEngine(copy.deepcopy(state), START)
    engine.tick({"BTCUSD": f}, study)
    assert "BTCUSD" in engine.state["accounts"]["parent"]["pending"]
    assert not engine.state["accounts"]["child"]["pending"]
    changed = copy.deepcopy(packet)
    changed["study"]["BTCUSD"][filtered["version"]]["eligible"] = True
    assert not feature_reproduction(changed)["closed_bar_features"]["BTCUSD"]["matched"]


def test_legacy_exact_serialization_and_single_supported_delta():
    legacy = RuleSpec().model_dump()
    assert "entry_filter" not in legacy
    assert RuleSpec.model_validate(legacy).model_dump() == legacy
    child = RuleSpec.model_validate(
        legacy | {"version": "reviewed-lab-rules-v3", "entry_filter": component().model_dump()}
    )
    assert set(changes(RuleSpec(), child)) == {"entry_filter", "version"}
    with pytest.raises(ValueError, match="genuine short"):
        RuleSpec(version="reviewed-lab-rules-v3", holding_horizon="long", entry_filter=component())
    corrupt = component().model_dump()
    corrupt["artifact"]["means"][0] += 1
    with pytest.raises(ValueError, match="fingerprint"):
        MemoryFilter.model_validate(corrupt)
    with pytest.raises(ValueError):
        MemoryFilter(artifact=fitted()[3], marginal_daily_usd="NaN")


def test_supported_rejection_never_creates_entry_or_touches_exits():
    _, rows, _, artifact = fitted()
    d = rows[-1]["descriptor"]
    negative = copy.deepcopy(artifact)
    for row in negative["library"]:
        row["net_bps"] = -50
    negative.pop("sha256")
    negative["sha256"] = digest(negative)
    base = {"eligible": True, "atr": "1", "stop_atr": "1.5"}
    result = filtered_feature(base, d, negative, d["cutoff"])
    assert not result["eligible"] and result["stop_atr"] == base["stop_atr"]
    base["eligible"] = False
    assert not filtered_feature(base, d, artifact, d["cutoff"])["eligible"]
    assert (
        filtered_feature(base, d, artifact, d["expires_at"] + 1)["memory_evidence"]["status"]
        == "result_too_late"
    )


def test_real_runtime_consumes_component_and_preserves_frozen_parent(pg_store, tmp_path):
    store, _ = pg_store
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    lab.paper.state = store.transact(START, lambda e: e.state.update(evidence_kind="synthetic_qa"))
    parent = admit(lab, START)
    close_window(lab, parent, "promising")
    parent_spec = copy.deepcopy(parent["contract"]["proposal"]["strategy"])
    original = copy.deepcopy(lab.paper.state["accounts"][parent["candidate"]])
    strategy = RuleSpec.model_validate(
        parent_spec | {"version": "reviewed-lab-rules-v3", "entry_filter": component().model_dump()}
    )
    now = parent["review_at"] + 4
    tick_lab(lab, now)
    proposal = LabProposal(
        request_id="cp20-frozen-memory-child",
        policy_id=lab.paper.state["autonomous_lab"]["policy"]["request_id"],
        kind="variation",
        strategy=strategy,
        reference=RuleSpec.model_validate(parent_spec),
        parent_trial=parent["id"],
        parent_strategy_sha256=fingerprint(parent_spec),
        mechanism="Test only the existing frozen historical-memory entry filter.",
        question="Reject a child with inferior matched after-cost whole-account value.",
        evidence_bundle_sha256=lab.bundle(now)["sha256"],
    )
    lab.submit(proposal, now)
    for i in range(1, 20):
        tick_lab(lab, now + i * 2)
        lab.step(now + i * 2)
        trials = [
            t
            for t in lab.paper.state["autonomous_lab"]["trials"].values()
            if t["proposal_id"] == proposal.request_id
        ]
        if trials and trials[0]["status"] == "active":
            break
    assert trials and trials[0]["status"] == "active"
    child = trials[0]
    at = child["started_at"] + 2
    tick_lab(lab, at)
    study = {}
    lab.paper.numerical_study(at, study)
    account = lab.paper.state["accounts"][child["candidate"]]
    actual = study["BTCUSD"][account["version"]]
    expected = reviewed_feature(
        lab.paper.lab_history(at, "short"),
        at,
        strategy,
        account["execution_profile"],
        lab.paper.memory_book("BTCUSD"),
    )
    assert actual == expected and actual["component_version"] == "memory-entry-filter-v1"
    assert (
        study["BTCUSD"][lab.paper.state["accounts"][child["reference"]]["version"]].get(
            "component_version"
        )
        is None
    )
    assert account["operating_daily_usd"] == "1"
    assert lab.paper.state["accounts"][parent["candidate"]]["rule_spec"] == parent_spec
    for key in ("funding", "risk_policy", "admitted_at"):
        assert lab.paper.state["accounts"][parent["candidate"]][key] == original[key]
    assert store.reconcile()["balanced"]
    # Full account arithmetic charges the component once and preserves passive/cash controls.
    score = close_window(lab, child, "economically_unsuccessful")
    assert Decimal(score["component_operating_usd"]["candidate"]) > 0
    assert Decimal(score["component_operating_usd"]["reference"]) == 0
    lab.registry.close()
