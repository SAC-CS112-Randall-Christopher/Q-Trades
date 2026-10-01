"""Disposable CP17 scope, exposure, archival and recovery acceptance."""

import copy
import time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from test_paper_engine import START
from test_paper_store import pg_store as _pg_store
from test_research_storage import plan_at
from test_station import runtime as _runtime
from test_trade_history import closure

from trading.api import create_app
from trading.config import Settings
from trading.experiment_registry import ExperimentRegistry
from trading.paper_engine import account as new_account
from trading.research_storage import ResearchStorage
from trading.scoped_tools import disclose, run
from trading.station import cost_hurdle, execute_tool, strategy_evidence
from trading.tiered_runtime import TieredPaperRuntime as PaperRuntime
from trading.tool_journal import ToolJournal

runtime = _runtime
pg_store = _pg_store


def test_selected_child_uses_frozen_costs_and_recorded_causal_features(runtime):
    child = copy.deepcopy(runtime.state["accounts"]["primary"])
    child["execution_profile"] = "binance-us-public-2026-09-29-v1"
    child["last_decision"]["BTCUSD"].update(
        features={"close": "100.1234567890123456789012345", "note": "旧图 Δ"},
        reason="Child did not enter",
    )
    runtime.state["accounts"]["child"] = child
    runtime.study["BTCUSD"] = {child["version"]: {"close": "9999"}}
    before = copy.deepcopy(runtime.state)
    result = execute_tool(runtime, "strategy_evidence", "BTCUSD", "child")["result"]
    assert (
        result["account"] == "child" and result["last_decision"]["reason"] == "Child did not enter"
    )
    assert result["features"] == child["last_decision"]["BTCUSD"]["features"]
    assert (
        cost_hurdle(runtime, "BTCUSD", "child")["execution_profile"] == child["execution_profile"]
    )
    assert runtime.state == before
    with pytest.raises(ValueError, match="no primary fallback"):
        strategy_evidence(runtime, "BTCUSD", "missing-child")


def test_permanent_outcomes_scope_totals_cutoff_and_late_membership(pg_store):
    store, _ = pg_store

    def seed(engine):
        for _i in range(1103):
            body = closure()["body"] | {"pnl": "-0.13", "fees": "0.10"}
            engine.emit("trade_closed", "primary", body)
        engine.emit("trade_closed", "breakout-v1", closure()["body"] | {"pnl": "500"})

    store.transact(START + 100, seed)
    original = copy.deepcopy(store.read())
    snapshot = store.research_account("primary", START + 101)
    assert "recent_trades" not in snapshot["state"]
    result = store.research_outcomes(snapshot, "BTCUSD")
    assert result["market_totals"]["trades"] == 1103
    assert Decimal(result["market_totals"]["net_pnl"]) == Decimal("-143.39")
    assert Decimal(result["market_totals"]["fees"]) == Decimal("110.30")
    assert len(result["events"]) == 20 and result["has_more"]
    # An immutable late revision cannot join a previously frozen query.
    store.transact(START + 101, lambda e: e.emit("trade_closed", "primary", closure()["body"]))
    second = store.research_events(
        "primary",
        "BTCUSD",
        snapshot["cutoff"],
        snapshot["maximum_event_id"],
        before=result["next_before"],
    )
    assert len(second["events"]) == 20
    assert all(e["id"] <= snapshot["maximum_event_id"] for e in second["events"])
    assert not {e["id"] for e in result["events"]} & {e["id"] for e in second["events"]}
    assert store.read()["accounts"] == original["accounts"] and store.reconcile()["balanced"]


def test_retired_scope_has_its_own_frozen_decision_and_lifetime_outcomes(pg_store):
    store, _ = pg_store
    from psycopg.types.json import Jsonb

    saved = new_account("breakout-v1", START)
    saved["last_decision"]["BTCUSD"] = {
        "at": START,
        "reason": "Retired child decision",
        "features": {"atr": "2"},
    }
    store.connection.execute(
        "INSERT INTO paper_lab_archives VALUES(%s,%s,%s,%s)",
        ("retired-child", "retired-trial", START + 10, Jsonb(saved)),
    )
    store.transact(
        START + 100, lambda e: e.emit("trade_closed", "retired-child", closure()["body"])
    )
    snapshot = store.research_account("retired-child", START + 101)
    result = store.research_outcomes(snapshot, "BTCUSD")
    assert result["archived"] and result["trial_id"] == "retired-trial"
    assert result["market_totals"]["trades"] == 1
    assert snapshot["state"]["last_decision"]["BTCUSD"]["reason"] == "Retired child decision"
    with pytest.raises(KeyError, match="account"):
        store.research_account("missing-child", START + 101)


def test_reader_open_does_not_interrupt_live_owned_tool_job(tmp_path):
    path = tmp_path / "tools.sqlite3"
    writer = ToolJournal(path)
    run_id = writer.start("market_evidence", "BTCUSD")
    observer = ToolJournal(path)
    assert observer.get(run_id)["status"] == "running"
    observer.close()
    assert writer.get(run_id)["status"] == "running"
    writer.finish(run_id, {"result": {"real": "receipt"}}, None)
    writer.close()


def test_more_than_5000_receipts_reopen_failures_and_stable_request_ids(tmp_path):
    journal = ToolJournal(tmp_path / "tools.sqlite3", plan_at(tmp_path))
    try:
        first = journal.start("unsupported", "BTCUSD", request_id="stable-first-id")
        journal.finish(first, None, "Unsupported capability retained")
        for i in range(5008):
            run_id = journal.start("strategy_evidence", "BTCUSD")
            journal.finish(
                run_id, {"result": {"ordinal": i, "decimal": "0.1234567890123456789"}}, None
            )
        assert journal.recent()["total"] == 5009
        assert journal.connection.execute("SELECT count(*) FROM tool_runs").fetchone()[0] <= 5000
        assert journal.get(first)["error"] == "Unsupported capability retained"
        assert journal.start("unsupported", "BTCUSD", request_id="stable-first-id") == first
        with pytest.raises(ValueError, match="different evidence scope"):
            journal.start("unsupported", "ETHUSD", request_id="stable-first-id")
        assert len(journal.recent()["runs"]) == 20
    finally:
        journal.close()


def test_archive_failure_retains_hot_receipt_and_no_new_id(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.tool_journal.MAX_RUNS", 1)
    journal = ToolJournal(tmp_path / "tools.sqlite3", plan_at(tmp_path))
    first = journal.start("strategy_evidence", "BTCUSD")
    journal.finish(first, {"result": {"reason": "No entry"}}, None)

    def failed(*args, **kwargs):
        raise OSError("Injected archive outage")

    monkeypatch.setattr(ResearchStorage, "append", failed)
    with pytest.raises(OSError, match="archive outage"):
        journal.start("strategy_evidence", "BTCUSD")
    assert journal.get(first)["status"] == "completed" and journal.recent()["total"] == 1
    journal.close()


def test_physical_journal_pressure_archives_before_64_mib(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.tool_journal.MAX_RUNS", 10000)
    journal = ToolJournal(tmp_path / "tools.sqlite3", plan_at(tmp_path))
    for _ in range(470):
        run_id = journal.start("strategy_evidence", "BTCUSD")
        journal.finish(run_id, {"result": {"large": "x" * 115000}}, None)
    assert journal.connection.execute("PRAGMA page_count").fetchone()[0] * 4096 < 64 * 1024**2
    assert journal.connection.execute("SELECT count(*) FROM tool_runs").fetchone()[0] < 470
    assert journal.get(1)["result"]["result"]["large"] == "x" * 115000
    journal.close()


def test_expired_cursor_and_checksum_failure_never_substitute_live_data(tmp_path, monkeypatch):
    journal = ToolJournal(tmp_path / "tools.sqlite3")
    run_id = journal.start("strategy_evidence", "BTCUSD")
    journal.finish(run_id, {"result": {"reason": "Saved only"}}, None)
    cursor = journal.cursor({"kind": "runs", "before": 2})
    later = time.time() + 3601
    monkeypatch.setattr("trading.tool_journal.time.time", lambda: later)
    with pytest.raises(ValueError, match="expired"):
        journal.recent(cursor)
    with journal.connection:
        journal.connection.execute("UPDATE tool_runs SET result='{}' WHERE id=?", (run_id,))
    with pytest.raises(ValueError, match="checksum"):
        journal.get(run_id)
    journal.close()


def test_captured_analogue_consumes_outcomes_before_cached_delivery(tmp_path):
    from trading.research_evidence import EvidenceArchive

    archive = EvidenceArchive(tmp_path / "research-evidence.sqlite")
    lookup = {
        "matches": [{"episode": "synthetic-prior", "outcome": {"net_bps": "-3.14"}}],
        "query_cutoff": 1,
        "status": "available",
    }
    archive.append(
        [
            {
                "kind": "decision",
                "at": 1,
                "episode": {
                    "episode": "synthetic-query",
                    "new": True,
                    "opportunity": "synthetic-only",
                    "available_at": 1,
                    "descriptor": {"cutoff": 1, "horizon_at": 2, "data_mode": "synthetic_qa"},
                    "retrieval": lookup,
                },
            }
        ]
    )
    archive.close()
    with TestClient(
        create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    ) as client:
        for _ in range(2):
            response = client.get("/api/research/analogues/1")
            assert response.status_code == 200 and response.json()["lookup"] == lookup
            assert response.headers["cache-control"] == "no-store"
        rows = client.app.state.lab.registry.db.execute(
            "SELECT * FROM evidence_windows WHERE origin='analogue tool disclosure'"
        ).fetchall()
        assert len(rows) == 1 and rows[0]["end"] == 1
        assert client.get("/api/research/analogues/9999").status_code == 404


def test_captured_detail_pages_exact_indicator_parity_and_cursor_scope(runtime, tmp_path):
    plan = plan_at(tmp_path)
    journal = ToolJournal(tmp_path / "tools.sqlite3", plan)
    result = run(runtime, "market_evidence", "BTCUSD", "primary", "market-capture-id")
    first = journal.start("market_evidence", "BTCUSD")
    journal.finish(first, result, None)
    saved = journal.get(first)
    assert saved["status"] == "completed"
    assert len(saved["result"]["result"]["detail"]["candles"]) == 1
    pages, cursor = [], None
    while True:
        page = journal.detail(first, cursor)
        pages.extend(page["facts"]["detail"]["indicators"]["points"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == result["result"]["detail"]["indicators"]["points"]
    cursor = journal.detail(first)["next_cursor"]
    second = journal.start("market_evidence", "BTCUSD", account="breakout-v1")
    journal.finish(
        second, run(runtime, "market_evidence", "BTCUSD", "breakout-v1", "second-market-id"), None
    )
    with pytest.raises(ValueError, match="different receipt"):
        journal.detail(second, cursor)
    with pytest.raises(ValueError, match="invalid"):
        journal.detail(first, cursor + "tampered")
    # Changing today's bars cannot rewrite the retained chart/indicator result.
    runtime.history["BTCUSD"].clear()
    assert journal.detail(first)["total"] == 120
    journal.close()


def test_finalization_failure_resumes_exact_artifact_after_restart(runtime, tmp_path, monkeypatch):
    path, plan = tmp_path / "tools.sqlite3", plan_at(tmp_path)
    journal = ToolJournal(path, plan)
    first = journal.start("market_evidence", "BTCUSD", request_id="restart-capture-id")
    real_reopen = ResearchStorage.reopen

    def crash(self, reference):
        raise OSError("Crash after artifact commit")

    monkeypatch.setattr(ResearchStorage, "reopen", crash)
    with pytest.raises(OSError, match="artifact commit"):
        journal.finish(
            first, run(runtime, "market_evidence", "BTCUSD", "primary", "restart-capture-id"), None
        )
    assert journal.get(first)["status"] == "finalizing"
    with journal.connection:
        journal.connection.execute("UPDATE tool_runs SET lease_until=0 WHERE id=?", (first,))
    journal.close()
    monkeypatch.setattr(ResearchStorage, "reopen", real_reopen)
    reopened = ToolJournal(path, plan)
    assert reopened.start("market_evidence", "BTCUSD", request_id="restart-capture-id") == first
    assert reopened.get(first)["status"] == "completed"
    assert reopened.detail(first)["total"] == 120
    reopened.close()


def test_saved_and_cached_disclosure_consumes_once_and_metadata_exposes_no_results(
    runtime, tmp_path
):
    journal = ToolJournal(tmp_path / "tools.sqlite3")
    registry = ExperimentRegistry(tmp_path / "registry.sqlite3")
    first = journal.start("strategy_evidence", "BTCUSD")
    journal.finish(
        first, run(runtime, "strategy_evidence", "BTCUSD", "primary", "exposure-capture-id"), None
    )
    before = registry.db.execute("SELECT count(*) FROM evidence_windows").fetchone()[0]
    for _ in range(2):
        disclose(registry, journal.get(first))
    assert registry.db.execute("SELECT count(*) FROM evidence_windows").fetchone()[0] == before + 1
    assert all(
        "result" not in item and "result_sha256" not in item for item in journal.recent()["runs"]
    )
    registry.close()
    journal.close()


def test_api_selected_outcomes_paging_reopen_and_metadata_preserve_financial_state(
    pg_store, tmp_path, monkeypatch
):
    monkeypatch.setattr("trading.scoped_tools.time.time", lambda: START + 200)
    store, _ = pg_store
    store.transact(
        START + 100,
        lambda e: [e.emit("trade_closed", "breakout-v1", closure()["body"]) for _ in range(45)],
    )
    original = store.read()
    runtime = PaperRuntime(store, None, tmp_path / "capture.sqlite3")
    runtime.running, runtime.disk_free = True, 10 * 1024**3
    runtime.state["last_tick"] = time.time()
    from test_paper_runtime import instrument

    runtime.instruments = {"BTCUSD": instrument("BTC")}
    app = create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    with TestClient(app) as client:
        app.state.paper = runtime
        command = {
            "tool": "outcome_review",
            "symbol": "BTCUSD",
            "account": "breakout-v1",
            "request_id": "scoped-outcomes-id",
        }
        response = client.post(
            "/api/research/tools/run", json=command, headers={"X-Local-Operator": "1"}
        )
        saved = response.json()
        assert response.status_code == 200 and saved["status"] == "completed", saved
        assert saved["result"]["result"]["market_totals"]["trades"] == 45
        page = client.get(f"/api/research/tools/runs/{saved['id']}/detail").json()
        assert len(page["events"]) == 20
        second = client.get(
            f"/api/research/tools/runs/{saved['id']}/detail", params={"cursor": page["next_cursor"]}
        ).json()
        assert len(second["events"]) == 20
        assert client.get(f"/api/research/tools/runs/{saved['id']}").json() == saved
        assert client.get("/api/research/tools/accounts").status_code == 200
        assert store.read() == original and store.reconcile()["balanced"]
