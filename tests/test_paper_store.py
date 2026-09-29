import uuid
from decimal import Decimal as D
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from test_futures_context import metadata, receipt
from test_paper_engine import START, frame, study

from trading.futures_context import FuturesContext
from trading.paper_store import PaperStore, load_dsn


class RedactedDsn(str):
    def __repr__(self):
        return "<dedicated local test database>"


@pytest.fixture
def pg_store():
    settings = Path("data/paper-database.json")
    if not settings.is_file():
        pytest.skip("Dedicated local paper PostgreSQL is not configured")
    dsn = load_dsn(settings)
    schema = "test_paper_" + uuid.uuid4().hex
    admin = psycopg.connect(dsn, autocommit=True)
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    test_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    store = PaperStore(test_dsn, owner=True)
    store.initialize(START)
    try:
        yield store, RedactedDsn(test_dsn)
    finally:
        store.close()
        # Only this test's freshly generated schema; never the application schema/database.
        assert schema.startswith("test_paper_") and len(schema) == 43
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


def test_seed_restart_fills_reconcile_and_repeat_observation_is_idempotent(pg_store):
    store, dsn = pg_store
    assert store.read()["accounts"]["primary"]["cash"] == "100"
    store.transact(START, lambda e: e.tick({"BTCUSD": frame()}, study()))
    assert store.reconcile()["balanced"]
    store.transact(START + 2, lambda e: e.tick({"BTCUSD": frame(START + 2, sequence=2)}, study()))
    assert store.reconcile()["balanced"]
    cash = store.read()["accounts"]["primary"]["cash"]
    store.close()
    reopened = PaperStore(dsn, owner=True)
    try:
        reopened.initialize(START + 3)
        reopened.transact(
            START + 3, lambda e: e.tick({"BTCUSD": frame(START + 3, sequence=2)}, study())
        )
        assert reopened.read()["accounts"]["primary"]["cash"] == cash
        reopened.transact(
            START + 6, lambda e: e.tick({"BTCUSD": frame(START + 6, "98", 3)}, study())
        )
        reopened.transact(
            START + 8, lambda e: e.tick({"BTCUSD": frame(START + 8, "98", 4)}, study())
        )
        assert reopened.reconcile()["balanced"]
        assert reopened.read()["accounts"]["primary"]["closed"] == 1
    finally:
        reopened.close()


def test_database_rejects_second_engine_and_audit_mutation(pg_store):
    store, dsn = pg_store
    with pytest.raises(RuntimeError, match="Another paper engine"):
        PaperStore(dsn, owner=True)
    with pytest.raises(psycopg.Error, match="append-only"):
        store.connection.execute("UPDATE paper_events SET kind='hidden'")
    assert store.reconcile()["balanced"]
    reader = PaperStore(dsn)
    try:
        with pytest.raises(RuntimeError, match="exclusive engine writer lock"):
            reader.transact(START + 1, lambda e: e.tick({}, {}))
    finally:
        reader.close()


def test_futures_receipts_survive_restart_and_are_linked_to_intents_and_fills(pg_store):
    store, dsn = pg_store
    row = FuturesContext().accept("BTCUSD", "BTC", metadata(), receipt(START))
    row["capture_id"] = "test-context"
    report = {
        "version": "test-context",
        "capture_id": row["capture_id"],
        "observed_at": START,
        "markets": {"BTCUSD": row},
        "receipts": [{"wire": '{"test_only":true}', "sha256": "test-fixture"}],
    }
    before = store.read()["accounts"]
    store.transact(START, lambda e: e.record_futures_context(report))
    assert store.read()["accounts"] == before
    assert store.reconcile()["balanced"]
    store.close()
    reopened = PaperStore(dsn, owner=True)
    try:
        reopened.initialize(START + 1)
        for elapsed, sequence in [(1, 1), (3, 2)]:
            observed = {**frame(START + elapsed, sequence=sequence), "futures_context": row}
            reopened.transact(START + elapsed, lambda e, f=observed: e.tick({"BTCUSD": f}, study()))
        events = reopened.export(0, 100)["records"]
        retained = [e for e in events if e["kind"] == "futures_context"]
        assert len(retained) == 1 and retained[0]["body"] == report
        linked = [e for e in events if e["kind"] in ("order_intent", "fill")]
        assert {e["kind"] for e in linked} == {"order_intent", "fill"}
        assert all(e["body"]["observation"]["futures_context"] == row for e in linked)
        assert reopened.read()["futures_context_window"]["snapshots"] == 1
        assert reopened.reconcile()["balanced"]
        assert not reopened.connection.execute(
            "SELECT 1 FROM paper_journal WHERE event_id=%s", (retained[0]["id"],)
        ).fetchall()
    finally:
        reopened.close()


def test_paired_universe_accounts_have_separate_funding_and_reconcile_new_asset(pg_store):
    store, _ = pg_store
    before = store.read()["accounts"]["primary"]
    store.transact(START, lambda e: e.universe_experiment(["SOLUSD"]))
    first_revision = store.read()["revision"]
    store.transact(START + 0.1, lambda e: e.universe_experiment(["SOLUSD"]))
    assert store.read()["accounts"]["primary"] == before
    account = store.read()["accounts"]["universe-wide-v1"]
    assert account["funding"] == account["cash"] == "100"
    assert not store.connection.execute(
        "SELECT id FROM paper_events WHERE revision > %s AND kind='research_account_created'",
        (first_revision,),
    ).fetchall()
    observations = {"SOLUSD": study()["BTCUSD"]}

    def sol_frame(at, sequence):
        result = frame(at, sequence=sequence)
        result.update(
            base="SOL",
            instrument={"symbol": "SOLUSD"},
            source="test-only",
            exchange_event_ms=int(at * 1000),
        )
        return result

    store.transact(START + 1, lambda e: e.tick({"SOLUSD": sol_frame(START + 1, 1)}, observations))
    store.transact(START + 3, lambda e: e.tick({"SOLUSD": sol_frame(START + 3, 2)}, observations))
    accounts = store.read()["accounts"]
    assert accounts["universe-wide-v1"]["positions"]["SOLUSD"]["base"] == "SOL"
    assert not accounts["universe-control-v1"]["positions"]
    assert not accounts["primary"]["positions"]
    assert store.reconcile()["balanced"]
    # A missing projection must not hide inventory in an additional asset.
    store.transact(
        START + 4, lambda e: e.state["accounts"]["universe-wide-v1"]["positions"].clear()
    )
    receipt = store.reconcile()
    assert not receipt["balanced"]
    assert any("SOL inventory mismatch" in item for item in receipt["projection_errors"])


def test_closed_candle_revisions_are_detected_across_restarts(pg_store):
    store, _ = pg_store
    raw = [[60000, "100", "101", "99", "100", "1", 119999]]
    assert store.bars("BTCUSD", raw, 120, True) == 1
    assert store.bars("BTCUSD", raw, 121, True) == 0
    raw[0][4] = "100.5"
    with pytest.raises(ValueError, match="differs"):
        store.bars("BTCUSD", raw, 122, True)


def test_exchange_confirmed_close_preserves_local_receipt_when_clock_is_behind(pg_store):
    store, _ = pg_store
    raw = [[60000, "100", "101", "99", "100", "1", 119999]]
    assert store.bars("BTCUSD", raw, 119.5, False) == 0
    assert store.bars("BTCUSD", raw, 119.5, False, closed_before_ms=120005) == 1
    retained = store.connection.execute(
        "SELECT observed_at, body FROM paper_bars WHERE symbol='BTCUSD'"
    ).fetchone()
    assert retained["observed_at"] == 119.5 and retained["body"] == raw[0]
    assert store.bars("ETHUSD", raw, 119.5, False, closed_before_ms=119999) == 0


def test_failed_transaction_leaves_no_partial_financial_state(pg_store):
    store, _ = pg_store
    before = store.read()

    def crash(engine):
        engine.state["accounts"]["primary"]["cash"] = "1"
        engine.emit("should_not_commit", "primary", {})
        raise RuntimeError("synthetic interruption")

    with pytest.raises(RuntimeError, match="synthetic interruption"):
        store.transact(START + 1, crash)
    assert store.read() == before
    assert store.reconcile()["balanced"]


def test_loss_review_replenishment_atomic_and_historically_reconciled(pg_store):
    store, _ = pg_store

    def loss(engine):
        # Synthetic test fixture models a historical cash loss with both journal sides.
        a = engine.state["accounts"]["primary"]
        a["cash"] = "4"
        engine.emit(
            "synthetic_test_loss",
            "primary",
            {},
            [engine.line("USD", "cash", D(-96)), engine.line("USD", "test_loss", D(96))],
        )
        engine.tick({}, {})

    store.transact(START + 1, loss)
    assert store.reconcile()["balanced"]
    a = store.read()["accounts"]["primary"]
    assert a["cash"] == "100" and a["funding"] == "196"
    events = store.export(0, 100)["records"]
    reviews = [e for e in events if e["kind"] == "failure_review"]
    funding = [e for e in events if e["kind"] == "replenishment"]
    assert reviews[0]["id"] < funding[0]["id"]
    assert reviews[0]["revision"] == funding[0]["revision"]
    seen, cursor = [], 0
    while True:
        page = store.export(cursor, 2)
        seen.extend(e["id"] for e in page["records"])
        cursor = page["next_after"]
        if not page["has_more"]:
            break
    assert seen == [e["id"] for e in events]
