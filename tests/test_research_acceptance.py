"""Final source faults and truthful reporting; actual model qualification stays separate."""

import asyncio
import json
import socket
from hashlib import sha256

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo
from test_autonomous_lab import close_window, tick_lab
from test_paper_engine import START
from test_paper_store import pg_store as pg_store
from test_research_storage import plan_at
from test_role_worker import ModelStub, make_lab

from trading.api import create_app
from trading.config import Settings
from trading.experiment_registry import ExperimentRegistry
from trading.research_quality import quality_report
from trading.research_storage import save_plan
from trading.role_worker import Question, RoleWorker
from trading.scoped_tools import reader
from trading.stock_research import StockQuestion, StockResearch


def test_role_history_equal_timestamp_cursor_conserves_all_ids(pg_store, tmp_path, monkeypatch):
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(pg_store[0], tmp_path)
    worker = RoleWorker(lab.registry, lab)
    first = worker.enqueue(
        Question(question="Retain the complete scoped history beyond the first page."), START
    )
    with lab.registry.transaction():
        for i in range(31):
            lab.registry.db.execute(
                "INSERT INTO role_tasks(id,created,updated,stage,status,context) "
                "VALUES(?,?,?,'complete','done',?)",
                ("role-" + f"{i:032x}", START, START, json.dumps(first["context"])),
            )
    page = worker.page()
    ids = {t["id"] for t in page["tasks"]}
    older = worker.page(page["next_before"], page["next_before_id"])
    assert len(ids) == 20 and len(older["tasks"]) == 12
    assert not ids.intersection(t["id"] for t in older["tasks"])
    assert len(ids | {t["id"] for t in older["tasks"]}) == 32
    assert older["next_before"] is None and pg_store[0].reconcile()["balanced"]
    lab.registry.close()


def test_late_native_completion_recovers_unknown_without_fresh_verdict(
    pg_store, tmp_path, monkeypatch
):
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(pg_store[0], tmp_path)
    model = ModelStub()
    model.slow = True
    original = RoleWorker(lab.registry, lab, model)
    original.enabled = True
    task = original.enqueue(
        Question(question="Keep a late completed model answer after its expired lease."), START
    )

    async def check():
        pending = asyncio.create_task(original.step(START))
        assert await asyncio.to_thread(model.entered.wait, 5)
        with lab.registry.transaction():
            lab.registry.db.execute(
                "UPDATE role_tasks SET lease_until=? WHERE id=?", (START - 1, task["id"])
            )
        replacement = RoleWorker(lab.registry, lab, ModelStub())
        replacement.enabled = True
        assert not await replacement.step(START)
        assert replacement.get(task["id"])["status"] == "failed"
        model.release.set()
        assert not await pending  # Expired original cannot dispatch its receipt.
        assert replacement.get(task["id"])["status"] == "queued"
        assert await replacement.step(START)
        assert replacement.get(task["id"])["stage"] == "evaluate"
        assert replacement.transport.calls == [] and model.calls == ["researcher"]

    asyncio.run(check())
    assert len(original.get(task["id"])["attempts"]) == 1
    assert pg_store[0].reconcile()["balanced"]
    lab.registry.close()


def test_stale_contract_followup_keeps_mature_history_without_new_inference(
    pg_store, tmp_path, monkeypatch
):
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(pg_store[0], tmp_path)
    worker = RoleWorker(lab.registry, lab, ModelStub())
    worker.enabled = True
    task = worker.enqueue(
        Question(question="Historical outcomes do not waive current follow-up contracts."), START
    )
    context = task["context"] | {"contract": "old-role-contract"}
    with lab.registry.transaction():
        lab.registry.db.execute(
            "UPDATE role_tasks SET stage='followup',context=? WHERE id=?",
            (json.dumps(context), task["id"]),
        )
    before = pg_store[0].read()
    assert not asyncio.run(worker.step(START))
    saved = worker.view(task["id"])
    assert "contract changed" in saved["reason"] and saved["attempts"] == []
    assert pg_store[0].read() == before
    lab.registry.close()


def test_saved_stock_request_reconciles_after_restart_without_source_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr("trading.stock_research.public_url", lambda url: url)
    calls = []
    text = json.dumps(
        {
            "Meta Data": {
                "2. Symbol": "IBM",
                "3. Last Refreshed": "2026-09-30",
                "5. Time Zone": "US/Eastern",
            },
            "Time Series (Daily)": {
                "2026-09-28": {
                    "1. open": "100",
                    "2. high": "102",
                    "3. low": "99",
                    "4. close": "100",
                    "5. volume": "1000",
                },
                "2026-09-29": {
                    "1. open": "100",
                    "2. high": "102",
                    "3. low": "99",
                    "4. close": "101",
                    "5. volume": "1000",
                },
            },
        }
    )

    def fetch(url):
        calls.append(url)
        return {
            "url": url,
            "text": text,
            "retrieved_at": START,
            "bytes": len(text),
            "sha256": sha256(text.encode()).hexdigest(),
        }

    monkeypatch.setattr("trading.stock_research.fetch_public", fetch)
    monkeypatch.setattr("trading.stock_research.time.time", lambda: START)
    save_plan(tmp_path, plan_at(tmp_path))
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    question = StockQuestion(
        security="IBM",
        as_of=float(START),
        market=True,
        hypothesis="Retain the exact explicit public-source study acknowledgment.",
        request_id="stock-request-0001",
    )
    first = StockResearch(registry).market_study(question)
    registry.close()
    monkeypatch.setattr(
        "trading.stock_research.fetch_public",
        lambda _: pytest.fail("Reconciled study must not refetch"),
    )
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    assert StockResearch(registry).market_study(question) == first and len(calls) == 1
    with pytest.raises(ValueError, match="identity cannot change"):
        StockResearch(registry).market_study(question.model_copy(update={"as_of": START - 1}))
    with pytest.raises(ValueError, match="identity cannot change"):
        StockResearch(registry).investigate(question)
    registry.close()


def test_quality_report_keeps_unknown_tokens_and_no_matched_value(pg_store, tmp_path, monkeypatch):
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(pg_store[0], tmp_path)
    worker = RoleWorker(lab.registry, lab, ModelStub())
    worker.enabled = True
    worker.enqueue(
        Question(question="Software completion counts never imply matched model value."), START
    )
    assert asyncio.run(worker.step(START))
    report = quality_report(worker)
    assert report["attempts"] == 1 and report["native_usage"]["unknown_attempts"] == 1
    assert report["native_usage"]["input_tokens"] is None
    assert not report["economic_value"]["supported"]
    assert all(a["quality_per_budget"] is None for a in report["matched_research_arms"])
    assert "off" in report["recommendation"]
    lab.registry.close()


def test_database_outage_retains_mature_outcome_and_recovers_once(pg_store, tmp_path, monkeypatch):
    store, dsn = pg_store
    monkeypatch.setattr("trading.role_worker.time.time", lambda: START)
    lab = make_lab(store, tmp_path, horizon_seconds=3600)
    save_plan(tmp_path, plan_at(tmp_path))
    from trading.evidence_runtime import EvidenceRecorder

    recorder = EvidenceRecorder(tmp_path / "research-evidence.sqlite")
    recorder.enqueue({"kind": "wire", "at": START, "source": "synthetic-outage-fixture"})
    asyncio.run(recorder.flush())
    model = ModelStub()
    worker = RoleWorker(lab.registry, lab, model)
    worker.enabled = True
    task = worker.enqueue(
        Question(question="Retain the original ordinary outcome through a database outage."), START
    )
    for _ in range(5):
        assert asyncio.run(worker.step(START))
    for i in range(1, 5):
        tick_lab(lab, START + i * 2)
        lab.step(START + i * 2)
    proposal = lab.inbox.get("role-proposal-" + task["id"][5:])
    trial = lab.paper.state["autonomous_lab"]["trials"][proposal["trial_id"]]
    score = close_window(lab, trial, "inconclusive")
    before = store.read()
    events = store.export(0, 1000)["records"]

    # Own a native loopback port without a listener; the real PostgreSQL driver
    # must fail to connect, while the independently owned writer remains healthy.
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        bad_dsn = make_conninfo(dsn, port=unavailable.getsockname()[1], connect_timeout=1)

        def disconnected(_):
            return psycopg.connect(bad_dsn)

        monkeypatch.setattr("trading.role_worker.reader", disconnected)
        assert not asyncio.run(worker.step(score["available_at"] + 1))
    saved = worker.get(task["id"])
    assert saved["stage"] == "outcome" and saved["status"] == "waiting"
    assert saved["reason"] == "Paper database unavailable; saved stage retained for retry"
    assert "outcome" not in saved["result"] and model.calls == ["researcher", "reviewer"]
    assert store.read() == before and store.export(0, 1000)["records"] == events
    monkeypatch.setattr("trading.role_worker.reader", reader)
    assert asyncio.run(worker.step(score["available_at"] + 32))
    assert worker.get(task["id"])["result"]["outcome"]["body"] == score
    assert model.calls == ["researcher", "reviewer"] and store.reconcile()["balanced"]
    assert store.read() == before and store.export(0, 1000)["records"] == events
    assert len(worker.get(task["id"])["attempts"]) == 2
    lab.registry.close()


def test_source_fetch_requires_operator_and_bad_cursor_is_rejected(tmp_path):
    with TestClient(
        create_app(Settings(), tmp_path / "monitor.sqlite", background=False)
    ) as client:
        assert (
            client.get(
                "/api/research/stocks/studies/unknown/section?phrase=Risk%20Factors"
            ).status_code
            == 403
        )
        assert client.get("/api/lab/roles?before=inf").status_code == 422
