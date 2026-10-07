"""Actual SQLite/native mocked-source paths, never a venue or trading-edge proof."""

import asyncio
import copy
import json
import time
from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from test_candle_history import row
from test_paper_runtime import instrument

from trading.api import create_app
from trading.candle_history import INTERVALS
from trading.config import Settings
from trading.experiment_registry import ExperimentRegistry
from trading.pattern_scanner import BAR_WORK, LEVEL_WORK, PatternScanner
from trading.research_evidence import digest
from trading.research_storage import ResearchStorage, StoragePlan, reopen_evidence, volume
from trading.universe import Universe
from trading.venue import PublicVenue

NOW = 1_800_000_000.0


class Fixture:
    def __init__(self, folder, monkeypatch, symbols=("BTCUSD",), generator=None):
        self.now = NOW
        monkeypatch.setattr(time, "time", lambda: self.now)
        universe = Universe()
        universe.instruments = {symbol: instrument(symbol[:-3]) for symbol in symbols}
        universe.metadata_at = self.now
        universe.screen(
            [
                {
                    "symbol": symbol,
                    "bidPrice": "100",
                    "askPrice": "100.1",
                    "quoteVolume": "1000000",
                    "lowPrice": "90",
                    "highPrice": "110",
                    "priceChangePercent": "1",
                    "count": 1000,
                    "closeTime": int(self.now * 1000),
                }
                for symbol in symbols
            ],
            self.now,
            set(),
        )
        self.paper = SimpleNamespace(
            universe=universe,
            running=True,
            error=None,
            state={
                "last_tick": self.now,
                "accounts": {"primary": {"fake_cash": "100", "positions": {}, "pending": {}}},
            },
            constrained=lambda: False,
            quotes=lambda: {"markets": []},
            stream=SimpleNamespace(trade_tape={}, stats={}, books={}),
            _fallback={},
        )
        self.original = copy.deepcopy(self.paper.state)
        self.calls = []
        self.frames = {"4h"}
        self.generator = generator or (lambda at, step: row(at, step))

        def handle(request):
            q = request.url.params
            self.calls.append(dict(q))
            step = INTERVALS[q["interval"]] * 1000
            start, end = int(q["startTime"]), int(q["endTime"])
            rows = (
                [self.generator(at, step) for at in range(start, end + 1, step)]
                if q["interval"] in self.frames
                else []
            )
            return httpx.Response(200, json=[r for r in rows if r is not None])

        self.venue = PublicVenue(transport=httpx.MockTransport(handle))
        root = folder / "Q-Trades-Data-scanner-fixture"
        self.plan = StoragePlan(
            root=str(root),
            volume_identity=volume(root)["identity"],
            temporary_bytes=128 * 1024**2,
            research_bytes=128 * 1024**2,
            scratch_bytes=16 * 1024**2,
            segment_bytes=8 * 1024**2,
            free_reserve_bytes=0,
        )
        self.storage = ResearchStorage(self.plan)
        self.registry = ExperimentRegistry(folder / "experiments.sqlite3")
        self.scanner = self.new_owner()
        self.campaign = None

    def new_owner(self):
        def borrow(plan):
            assert plan == self.plan
            return nullcontext(self.storage)

        return PatternScanner(self.registry, self.paper, self.venue, self.plan, borrow)

    def prepare(self, symbols=None, request="fixture-prepare-0001"):
        receipt = self.scanner.control(
            {
                "action": "prepare",
                "request_id": request,
                "symbols": symbols or list(self.paper.universe.instruments),
            },
            self.now,
        )
        self.campaign = receipt["campaign_id"]
        return receipt

    def start(self, request="fixture-start-0001"):
        return self.scanner.control(
            {
                "action": "start",
                "request_id": request,
                "campaign_id": self.campaign,
                "expected_revision": self.scanner.snapshot()["revision"],
            },
            self.now,
        )

    def state(self, frame="4h"):
        return json.loads(
            self.registry.db.execute(
                (
                    "SELECT body FROM pattern_progress WHERE campaign=? AND "
                    "symbol='BTCUSD' AND timeframe=?"
                ),
                (self.campaign, frame),
            ).fetchone()[0]
        )

    async def until(self, predicate, limit=15000):
        for _ in range(limit):
            if predicate():
                return
            assert await self.scanner.step()
        pytest.fail("Finite source-fixture step bound reached")

    def close(self):
        asyncio.run(self.venue.close())
        self.storage.close()
        self.registry.close()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch)
    try:
        yield f
    finally:
        f.close()


def test_default_disabled_all_eligible_frozen_year_and_saved_campaign_recovery(
    tmp_path, monkeypatch
):
    symbols = ["BTCUSD"] + [f"COIN{n}USD" for n in range(25)]
    f = Fixture(tmp_path, monkeypatch, symbols)
    try:
        assert not f.scanner.snapshot()["enabled"]
        receipt = f.prepare()
        saved = f.scanner.snapshot()
        assert len(saved["campaign"]["symbols"]) == 26
        assert saved["progress_total"] == 130 and saved["progress_omitted"] == 30
        assert (
            sum(
                r["expected_bars"]
                for r in f.registry.db.execute(
                    "SELECT json_extract(body,'$.expected_bars') AS expected_bars "
                    "FROM pattern_progress"
                )
            )
            == 168630 * 26
        )
        page = f.scanner.page("progress", f.campaign, "", "")
        second = f.scanner.page("progress", f.campaign, "", "", page["next_before"])
        assert len(page["rows"]) + len(second["rows"]) == 130
        assert (
            f.scanner.control(
                {"action": "prepare", "request_id": "fixture-prepare-0001", "symbols": symbols}
            )
            == receipt
        )
        old = f.campaign
        f.prepare(["BTCUSD"], "fixture-prepare-0002")
        assert f.scanner.snapshot(old)["is_current"] is False
        assert f.scanner.snapshot(old)["campaign"] == saved["campaign"]
        assert len(f.scanner.campaigns()["rows"]) == 2
        assert f.paper.state == f.original and not f.calls
    finally:
        f.close()


def test_controls_lost_ack_pause_before_delayed_start_and_restart(fixture):
    f = fixture
    f.prepare()
    revision = f.scanner.snapshot()["revision"]
    start = {
        "action": "start",
        "request_id": "fixture-delayed-start",
        "campaign_id": f.campaign,
        "expected_revision": revision,
    }
    pause = f.scanner.control(
        {"action": "pause", "request_id": "fixture-pause-0001", "campaign_id": f.campaign}
    )
    assert f.scanner.request("fixture-pause-0001") == pause
    with pytest.raises(ValueError):
        f.scanner.control(start)
    ack = f.start()
    f.scanner = f.new_owner()
    assert f.scanner.request(ack["request_id"]) == ack
    assert not f.scanner.snapshot()["enabled"]
    assert (
        f.scanner.control(
            {
                "action": "start",
                "request_id": ack["request_id"],
                "campaign_id": f.campaign,
                "expected_revision": pause["revision"],
            }
        )
        == ack
    )
    assert not f.scanner.snapshot()["enabled"]
    assert f.paper.state == f.original


def test_four_hour_full_year_and_raw_native_exact_storage(fixture):
    f = fixture
    f.prepare()
    f.start()
    asyncio.run(f.until(lambda: f.state()["status"] == "monitoring"))
    state = f.state()
    assert state["observed_bars"] == state["expected_bars"] == 2190
    assert state["missing_bars"] == 0 and state["pages"] == 3
    pages = f.registry.db.execute(
        "SELECT body FROM pattern_pages WHERE campaign=? AND timeframe='4h' ORDER BY start_ms",
        (f.campaign,),
    ).fetchall()
    original = []
    for saved in pages:
        page = json.loads(saved[0])
        rows = []
        for reference in page["references"]:
            packet = reopen_evidence(f.plan, reference)
            assert packet["campaign_id"] == f.campaign and packet["timeframe"] == "4h"
            rows.extend(packet["rows"])
        assert digest(rows) == page["rows_sha256"]
        original.extend(rows)
    assert len(original) == 2190 and original[-1][6] < f.now * 1000
    assert original[0] == row(state["requested_start_ms"], 14400000)
    assert all(int(q["limit"]) <= 1000 for q in f.calls)
    assert f.paper.state == f.original


@pytest.mark.parametrize("bad", ["duplicate", "wrong_interval", "malformed", "forming"])
def test_bad_native_source_does_not_advance_or_create_map(fixture, bad):
    f = fixture
    f.prepare()
    f.start()
    f.frames = set(INTERVALS)
    if bad == "wrong_interval":
        f.generator = lambda at, step: row(at, step + 1)
    elif bad == "malformed":
        f.generator = lambda at, step: row(at, step, volume="NaN")
    elif bad == "duplicate":
        first = f.state()["requested_start_ms"]
        f.generator = lambda at, step: row(first, step)
    else:
        f.generator = lambda at, step: row(int(f.now * 1000) // step * step, step)
    before = f.state("15m")
    assert asyncio.run(f.scanner.step()) is False
    after = f.state("15m")
    assert after["cursor_ms"] == before["cursor_ms"] and after["error"]
    assert not f.registry.db.execute("SELECT 1 FROM pattern_levels").fetchone()
    assert not f.registry.db.execute("SELECT 1 FROM pattern_pages").fetchone()


def test_pending_restart_never_refetches_and_corruption_refuses_progress(fixture):
    f = fixture
    f.prepare()
    f.start()
    f.frames = set(INTERVALS)
    assert asyncio.run(f.scanner.step())
    first = f.state("15m")
    assert "pending" in first
    calls = len(f.calls)
    f.scanner = f.new_owner()
    f.start("fixture-restart-start")
    assert asyncio.run(f.scanner.step())
    assert len(f.calls) == calls and f.state("15m")["pending"]["index"] <= BAR_WORK
    # Verified staging is immutable, including against accidental writes.
    with pytest.raises(Exception, match="immutable"):
        f.registry.db.execute("UPDATE pattern_inputs SET row='[]'")


def test_protected_owner_and_missing_storage_never_fetch(fixture):
    f = fixture
    f.prepare()
    f.start()
    f.paper.constrained = lambda: True
    assert not asyncio.run(f.scanner.step()) and not f.calls
    f.paper.constrained = lambda: False
    f.scanner.storage_owner = None
    assert not asyncio.run(f.scanner.step())
    assert f.state("15m")["error"] and f.state("15m")["pages"] == 0


def dense(at, step):
    # Strict pivots every five bars; every overlapping pivot remains retained.
    n = (at // step) % 5
    price = "100" if n != 2 else "102"
    high = "101" if n != 2 else "103"
    low = "99" if n != 2 else "98"
    result = row(at, step, price)
    result[2:4] = [high, low]
    return result


def test_dense_overlapping_levels_checkpoint_all_matches_and_paged_views(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, generator=dense)
    try:
        f.prepare()
        f.start()
        asyncio.run(f.until(lambda: f.state()["observed_bars"] >= 1000, limit=4000))
        page = f.scanner.page("levels", f.campaign, "BTCUSD", "4h")
        origin = f.state()["requested_start_ms"] // 14400000
        expected = 2 * sum((origin + n) % 5 == 2 for n in range(2, 998))
        assert page["total"] == expected
        assert page["total"] > 100 and len(page["rows"]) == 100 and page["next_before"]
        ids = set()
        while True:
            ids.update(v["id"] for v in page["rows"])
            if page["next_before"] is None:
                break
            page = f.scanner.page("levels", f.campaign, "BTCUSD", "4h", page["next_before"])
        assert len(ids) == page["total"]
        # Every processed-row batch remains bounded even for the dense map.
        statements = []
        f.registry.db.set_trace_callback(statements.append)
        for _ in range(300):
            statements.clear()
            assert asyncio.run(f.scanner.step())
            if any(s.startswith("UPDATE pattern_levels SET") for s in statements):
                break
        assert any(s.startswith("UPDATE pattern_levels SET") for s in statements)
        # SQLite traces the outer UPDATE again while evaluating its immutable-body
        # trigger. Each expanded logical update has a distinct (seq, processed_ms).
        updates = {s for s in statements if s.startswith("UPDATE pattern_levels SET")}
        assert 0 < len(updates) <= LEVEL_WORK
        assert all("json_extract" not in s for s in statements if "pattern_levels" in s)
        f.registry.db.set_trace_callback(None)
        assert f.paper.state == f.original
    finally:
        f.close()


def test_gaps_reset_causal_windows_without_invented_bars(fixture):
    f = fixture
    f.generator = lambda at, step: None if (at // step) % 17 == 0 else dense(at, step)
    f.prepare()
    f.start()
    asyncio.run(f.until(lambda: f.state()["observed_bars"] > 0, limit=3000))
    state = f.state()
    assert state["missing_bars"] > 0 and state["gap_count"] > 0
    assert state["observed_bars"] + state["missing_bars"] == 1000
    levels = f.scanner.page("levels", f.campaign, "BTCUSD", "4h")["rows"]
    assert levels and all(v["first_usable_ms"] > v["confirmed_at_ms"] for v in levels)
    for event in f.scanner.page("patterns", f.campaign, "BTCUSD", "4h")["rows"]:
        assert event["historical"] is True and "evaluation" not in event


def test_five_minute_year_continues_beyond_old_5000_chart_limit(fixture):
    f = fixture
    f.frames = {"5m"}
    f.prepare()
    f.start()
    asyncio.run(f.until(lambda: f.state("5m")["observed_bars"] >= 6000, limit=1500))
    state = f.state("5m")
    assert state["expected_bars"] == 105120 and state["observed_bars"] == 6000
    assert state["status"] == "preparing" and state["cursor_ms"] < state["cutoff_ms"]
    assert state["pages"] == 6 and state["missing_bars"] == 0
    assert f.paper.state == f.original


def test_registry_reserve_and_capture_quota_preserve_cursor_and_finance(fixture):
    f = fixture
    f.prepare()
    f.start()
    before = f.state("15m")
    page_size = f.registry.db.execute("PRAGMA page_size").fetchone()[0]
    used = f.registry.db.execute("PRAGMA page_count").fetchone()[0]
    f.registry.db.execute(f"PRAGMA max_page_count={used + 128 * 1024**2 // page_size}")
    assert not asyncio.run(f.scanner.step()) and not f.calls
    assert f.state("15m") == before and f.scanner.reason
    f.registry.db.execute("PRAGMA max_page_count=131072")
    with (f.storage.temporary / "quota-fixture").open("wb") as out:
        out.truncate(f.plan.temporary_bytes)
    assert not asyncio.run(f.scanner.step())
    assert f.state("15m")["cursor_ms"] == before["cursor_ms"]
    assert f.state("15m")["error"] and f.paper.state == f.original


def test_cancelled_owned_work_finishes_before_registry_shutdown(fixture, monkeypatch):
    f = fixture
    f.frames = set(INTERVALS)
    f.prepare()
    f.start()
    entered, release = Event(), Event()
    actual = f.scanner._work

    def held(*args):
        entered.set()
        assert release.wait(5)
        return actual(*args)

    monkeypatch.setattr(f.scanner, "_work", held)

    async def run():
        assert await f.scanner.step()
        task = asyncio.create_task(f.scanner.step())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and f.scanner._busy
            # Independent event-loop work still progresses while cleanup owns the thread.
            await asyncio.wait_for(asyncio.sleep(0.001), 1)
            assert f.registry.db.execute("SELECT 1").fetchone()[0] == 1
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert f.state("15m")["pending"]["index"] > 0 and not f.scanner._busy
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_three_source_failures_are_bounded_not_unlimited_retry(fixture):
    f = fixture
    f.frames = set(INTERVALS)
    f.prepare()
    f.start()
    f.generator = lambda at, step: row(at, step, volume="NaN")
    for _ in range(3):
        assert not asyncio.run(f.scanner.step())
        f.now += 31
        f.paper.state["last_tick"] = f.now
    assert f.state("15m")["status"] == "source_blocked"
    assert f.state("15m")["request_attempts"] == 3
    count = len(f.calls)
    # Other scopes may advance; the same failed source cannot silently redispatch.
    for _ in range(2):
        asyncio.run(f.scanner.step())
    assert (
        sum(c["interval"] == "15m" and c["startTime"] == f.calls[0]["startTime"] for c in f.calls)
        == 3
    )
    assert len(f.calls) >= count
    snapshot = f.scanner.snapshot()
    assert snapshot["status"] == "incomplete" and snapshot["reason"]


def test_actual_operator_api_bounds_pause_cas_and_postcommit_lost_ack(
    fixture, tmp_path, monkeypatch
):
    f = fixture
    app = create_app(Settings(), tmp_path / "monitor.sqlite3", background=False)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        app.state.pattern_scanner = f.scanner
        headers = {"x-local-operator": "1"}
        command = {
            "action": "prepare",
            "request_id": "api-prepare-fixture-0001",
            "symbols": ["BTCUSD"],
        }
        assert client.post("/api/research/pattern-scanner/control", json=command).status_code == 403
        assert not f.scanner.campaigns()["rows"]
        assert (
            client.post(
                "/api/research/pattern-scanner/control",
                headers=headers,
                json={**command, "symbols": ["BTCUSD"] * 2001},
            ).status_code
            == 422
        )
        response = client.post(
            "/api/research/pattern-scanner/control", headers=headers, json=command
        )
        assert response.status_code == 200, response.text
        receipt = response.json()
        campaign = receipt["campaign_id"]
        assert receipt["request_id"] == command["request_id"] and receipt["applied"] is True
        assert (
            client.get("/api/research/pattern-scanner/requests/" + command["request_id"]).json()
            == receipt
        )
        revision = receipt["revision"]
        original_snapshot = f.scanner.snapshot
        monkeypatch.setattr(
            f.scanner,
            "snapshot",
            lambda *args: (_ for _ in ()).throw(
                ValueError("Synthetic postcommit projection unavailable")
            ),
        )
        pause = {"action": "pause", "request_id": "api-pause-fixture-0001", "campaign_id": campaign}
        assert (
            client.post(
                "/api/research/pattern-scanner/control", headers=headers, json=pause
            ).status_code
            == 503
        )
        monkeypatch.setattr(f.scanner, "snapshot", original_snapshot)
        reopened = client.get("/api/research/pattern-scanner/requests/" + pause["request_id"])
        assert reopened.status_code == 200 and reopened.json()["action"] == "pause"
        delayed = {
            "action": "start",
            "request_id": "api-delayed-start-0001",
            "campaign_id": campaign,
            "expected_revision": revision,
        }
        assert (
            client.post(
                "/api/research/pattern-scanner/control", headers=headers, json=delayed
            ).status_code
            == 409
        )
        assert f.scanner.request(delayed["request_id"]) is None
        assert (
            client.get("/api/research/pattern-scanner/campaigns").json()["rows"][0]["id"]
            == campaign
        )
        assert (
            client.get(
                "/api/research/pattern-scanner/progress", params={"campaign_id": campaign}
            ).json()["total"]
            == 5
        )
        assert (
            client.get(
                "/api/research/pattern-scanner/levels",
                params={"campaign_id": campaign, "symbol": "BTCUSD", "timeframe": "1m"},
            ).status_code
            == 422
        )
        assert (
            client.get("/api/research/pattern-scanner/requests/notfoundrequest-0001").status_code
            == 404
        )
    assert f.paper.state == f.original and not f.calls


def test_prepared_scope_live_alert_while_other_years_remain_missing_and_deduplicated(fixture):
    f = fixture
    step = 14400000
    cutoff = int(f.now * 1000) // step * step

    def history(at, interval):
        value = row(at, interval)
        if at == cutoff - 5 * step:
            value[2] = "103"
        if at >= cutoff:
            value[2:6] = ["105", "99", "104", "20"]
        return value

    f.generator = history
    f.prepare()
    f.start()
    asyncio.run(f.until(lambda: f.state()["status"] == "monitoring", limit=600))
    assert f.state()["observed_bars"] == 2190
    f.now += INTERVALS["4h"]
    f.paper.state["last_tick"] = f.now
    f.paper.universe.scanned_at = f.now
    f.paper.universe.metadata_at = f.now
    before = json.loads(json.dumps(f.paper.state))

    async def run():
        assert await f.scanner.step()
        await f.until(
            lambda: bool(f.scanner.page("alerts", f.campaign, "BTCUSD", "4h")["rows"]), limit=20
        )
        for _ in range(3):
            await f.scanner.step()

    asyncio.run(run())
    alerts = f.scanner.page("alerts", f.campaign, "BTCUSD", "4h")
    assert alerts["total"] == 1
    alert = alerts["rows"][0]
    assert alert["kind"] == "resistance_breakout" and alert["historical"] is False
    assert alert["volume_confirmed"] is True and alert["evaluation"]["status"] == "unknown"
    assert alert["evaluation"]["unknowns"] and alert["financial_authority"] is False
    window = f.registry.db.execute(
        "SELECT start,end FROM evidence_windows WHERE request_id=?",
        ("pattern-page:" + f.campaign + ":BTCUSD:4h:" + str(cutoff),),
    ).fetchone()
    assert window is not None and tuple(window) == (cutoff / 1000, (cutoff + step) / 1000)
    assert f.state("5m")["missing_bars"] > 0 and f.paper.state == before
