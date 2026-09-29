import copy
import time

import pytest
from test_numerical_candidates import fixture_artifact
from test_paper_engine import START
from test_paper_store import pg_store as _pg_store

from trading.experiment_registry import fingerprint
from trading.paper_challengers import admit
from trading.paper_economics import new_benchmark
from trading.paper_engine import PaperEngine, initial_state
from trading.paper_learning import (
    comparison,
    designate,
    drift,
    matched_control,
    retain_report,
    rollback,
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
    assert engine.state["learning"]["reports"][frozen["request_id"]] == frozen
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
