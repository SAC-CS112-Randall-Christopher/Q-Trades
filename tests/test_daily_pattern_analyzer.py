"""Daily research uses the disposable scanner owner, never operating data."""

import asyncio
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_pattern_scanner import Fixture, row

from trading import pattern_scanner as scanner_module
from trading.api import PatternControl, create_app
from trading.config import Settings
from trading.pattern_scanner import DAILY_POLICY, DAILY_VERSION, encoded
from trading.research_evidence import digest


@pytest.fixture
def daily(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, [f"COIN{n}USD" for n in range(12)])
    try:
        yield f
    finally:
        f.close()


def enable(f, request="daily-enable-fixture-0001"):
    current = f.scanner.snapshot()
    command = {
        "action": "daily_enable",
        "request_id": request,
        "expected_revision": current["revision"],
    }
    if current["current_campaign_id"]:
        command["campaign_id"] = current["current_campaign_id"]
    receipt = f.scanner.control(command, f.now)
    f.campaign = receipt["campaign_id"]
    return receipt


def finish(f):
    for _ in range(500):
        f.scanner._daily_work(f.now)
        selection = f.scanner.snapshot()["daily_selection"]
        if selection["latest_id"] and selection["active_day"] is None:
            return f.scanner.daily_snapshot(selection["latest_id"])
    raise AssertionError("Bounded daily fixture did not finish")


def advance(f, seconds=86400):
    f.now += seconds
    f.paper.state["last_tick"] = f.now
    f.paper.universe.metadata_at = f.now
    f.paper.universe.scanned_at = f.now


def test_default_and_first_pick_real_screen_five_scopes(daily):
    f = daily
    assert f.scanner.snapshot()["daily_selection"]["enabled"] is False
    receipt = enable(f)
    result = finish(f)
    assert len(result["picks"]) == len(set(p["symbol"] for p in result["picks"])) == 5
    assert len(result["enrolled_today"]) == 5
    assert result["policy_sha256"] == digest(DAILY_POLICY)
    assert result["roster"]["rows"] == f.scanner.roster(f.now, full=True)["rows"]
    assert all(p["basis"] == "history_pending" and not p["evidence"] for p in result["picks"])
    assert all(
        len(p["coverage"]) == 5 and p["quote_volume"] == "1000000" and p["trades"] == 1000
        for p in result["picks"]
    )
    assert f.registry.db.execute("SELECT count(*) FROM pattern_progress").fetchone()[0] == 25
    assert f.scanner.request(receipt["request_id"]) == receipt
    assert f.scanner.snapshot()["campaign"]["version"] == DAILY_VERSION
    assert f.paper.state == f.original and not f.calls


def test_second_day_enrolls_five_without_recreating_or_mutating_history(daily):
    f = daily
    enable(f)
    first = finish(f)
    first_hash = digest(first)
    states = [tuple(r) for r in f.registry.db.execute("SELECT * FROM pattern_progress")]
    advance(f)
    second = finish(f)
    assert len(second["enrolled_today"]) == 5
    assert set(first["enrolled_today"]).isdisjoint(second["enrolled_today"])
    assert f.registry.db.execute("SELECT count(*) FROM pattern_campaigns").fetchone()[0] == 1
    assert f.registry.db.execute("SELECT count(*) FROM pattern_progress").fetchone()[0] == 50
    for old in states:
        assert (
            tuple(
                f.registry.db.execute(
                    "SELECT * FROM pattern_progress WHERE campaign=? AND symbol=? AND timeframe=?",
                    old[:3],
                ).fetchone()
            )
            == old
        )
    assert digest(f.scanner.daily_snapshot(first["id"])) == first_hash
    assert second["utc_day"] == first["utc_day"] + 1 and not f.calls


def test_restart_concurrent_bookkeeping_and_once_per_day(daily):
    f = daily
    enable(f)
    f.scanner = f.new_owner()
    assert f.scanner.snapshot()["enabled"] is True
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: f.scanner._daily_work(f.now), range(4)))
    saved = finish(f)
    for _ in range(4):
        assert f.scanner._daily_work(f.now) is False
    assert f.scanner.daily_pages()["total"] == 1
    assert f.scanner.daily_snapshot(saved["id"]) == saved
    assert len(saved["enrolled_today"]) == 5 and not f.calls


def test_pause_atomically_disables_campaign_and_producer_and_recovers_uuid(daily):
    f = daily
    enable(f)
    first = finish(f)
    pause = {
        "action": "daily_pause",
        "request_id": "daily-pause-fixture-0001",
        "campaign_id": f.campaign,
    }
    receipt = f.scanner.control(pause, f.now)
    f.scanner = f.new_owner()
    assert f.scanner.control(pause, f.now) == receipt
    assert not f.scanner.snapshot()["enabled"]
    assert not f.scanner.snapshot()["daily_selection"]["enabled"]
    advance(f)
    assert asyncio.run(f.scanner.step()) is False
    assert f.scanner.daily_pages()["total"] == 1
    assert f.scanner.daily_snapshot(first["id"]) == first and not f.calls
    with pytest.raises(ValueError, match="daily controls"):
        f.scanner.control(
            {
                "action": "start",
                "request_id": "manual-start-forbidden",
                "campaign_id": f.campaign,
                "expected_revision": receipt["revision"],
            }
        )


@pytest.mark.parametrize("fault", ["pressure", "paper_error", "stale_tick", "missing_plan"])
def test_protected_closed_never_enrolls_publishes_or_fetches(daily, fault):
    f = daily
    enable(f)
    if fault == "pressure":
        f.paper.constrained = lambda: True
    elif fault == "paper_error":
        f.paper.error = "retained error"
    elif fault == "stale_tick":
        f.paper.state["last_tick"] -= 11
    else:
        f.scanner.plan = None
    assert asyncio.run(f.scanner.step()) is False
    assert f.scanner.snapshot()["daily_selection"]["state"] in {"waiting_admission", "blocked"}
    assert f.scanner.daily_pages()["total"] == 0
    assert f.registry.db.execute("SELECT count(*) FROM pattern_enrollments").fetchone()[0] == 0
    assert not f.calls


def test_stale_roster_refuses_and_current_eligibility_stays_separate(daily):
    f = daily
    f.paper.universe.scanned_at -= 121
    with pytest.raises(ValueError, match="Fresh eligible"):
        enable(f)
    assert not f.scanner.snapshot()["enabled"]
    f.paper.universe.scanned_at = f.now
    enable(f)
    saved = finish(f)
    f.paper.universe.scanned_at -= 121
    status = f.scanner.snapshot()
    assert status["roster"]["available"] is True
    assert status["daily_selection"]["current_roster"]["available"] is False
    assert f.scanner.daily_snapshot(saved["id"]) == saved


def seed_setup(f, symbol, *, future=False, confirmed=True):
    for frame in ("5m", "15m", "30m", "1h", "4h"):
        saved = f.registry.db.execute(
            "SELECT body FROM pattern_progress WHERE campaign=? AND symbol=? AND timeframe=?",
            (f.campaign, symbol, frame),
        ).fetchone()
        state = json.loads(saved[0])
        state.update(
            cursor_ms=state["cutoff_ms"],
            latest_close_ms=state["cutoff_ms"] - 1,
            status="monitoring",
            observed_bars=state["expected_bars"],
            pages=1,
        )
        f.scanner._save(f.campaign, state)
    body = {
        "id": "synthetic-saved-original",
        "kind": "resistance_breakout",
        "volume_confirmed": confirmed,
        "volume_ratio": "2",
        "historical": True,
        "bar_close_ms": int((f.now + (1 if future else -1)) * 1000),
        "observed_at": f.now,
        "source_sha256": "a" * 64,
        "input_window_sha256": "b" * 64,
        "source_references": ["saved-native-reference"],
        "financial_authority": False,
        "reason": "Original causal fixture reason",
    }
    cursor = f.registry.db.execute(
        "INSERT INTO pattern_events(campaign,symbol,timeframe,identity,kind,body) "
        "VALUES(?,?,?,?,?,?)",
        (f.campaign, symbol, "4h", body["id"], "patterns", encoded(body)),
    )
    f.registry.db.execute(
        "INSERT INTO pattern_daily_evidence VALUES(?,?,?,?,?)",
        (f.campaign, symbol, "4h", cursor.lastrowid, encoded(body)),
    )
    return body


def test_recognized_rank_preserves_exact_saved_event_and_adverse_history(daily):
    f = daily
    enable(f)
    first = finish(f)
    symbol = first["enrolled_today"][-1]
    original = seed_setup(f, symbol)
    advance(f, 1)
    candidate = f.scanner._daily_candidate(
        f.campaign, f.paper.universe.rows[0] | {"symbol": symbol}, f.now
    )
    assert candidate["basis"] == "recognized_setup"
    assert candidate["evidence"][0]["body"] == original
    assert candidate["evidence"][0]["kind"] == "patterns"
    assert f.scanner._priority(candidate) < f.scanner._priority(first["picks"][0])
    assert f.paper.state["accounts"] == f.original["accounts"]
    with pytest.raises(sqlite3.IntegrityError):
        f.registry.db.execute("UPDATE pattern_events SET body='{}'")
    with pytest.raises(sqlite3.IntegrityError):
        f.registry.db.execute("UPDATE pattern_daily_days SET body='{}'")


@pytest.mark.parametrize(
    "fault", ["future", "volume_unknown", "corrupt_summary", "missing_original"]
)
def test_missing_future_or_altered_evidence_never_becomes_setup_rank(daily, fault):
    f = daily
    enable(f)
    first = finish(f)
    symbol = first["enrolled_today"][0]
    seed_setup(
        f, symbol, future=fault == "future", confirmed=None if fault == "volume_unknown" else True
    )
    if fault in {"corrupt_summary", "missing_original"}:
        f.registry.db.execute(
            "UPDATE pattern_daily_evidence SET body='{}'"
            if fault == "corrupt_summary"
            else "UPDATE pattern_daily_evidence SET seq=999999"
        )
        with pytest.raises(ValueError, match="immutable recognized"):
            f.scanner._daily_candidate(f.campaign, f.paper.universe.rows[0], f.now)
    else:
        candidate = f.scanner._daily_candidate(f.campaign, f.paper.universe.rows[0], f.now)
        assert candidate["basis"] == "analyzed_no_setup" and not candidate["evidence"]


def test_monitoring_cannot_starve_initial_scopes_and_only_one_page_pending(daily):
    f = daily
    enable(f)
    saved = finish(f)
    symbol = saved["enrolled_today"][0]
    seed_setup(f, symbol)
    advance(f, 300)
    asyncio.run(f.scanner.step())
    assert len(f.calls) == 1
    assert f.calls[0]["symbol"] != symbol and int(f.calls[0]["limit"]) <= 1000
    assert (
        f.registry.db.execute("SELECT count(*) FROM pattern_progress WHERE pending=1").fetchone()[0]
        == 1
    )


def test_financial_subscription_and_full_state_are_unchanged(daily):
    f = daily
    selected = copy.deepcopy(f.paper.universe.selected)
    state = copy.deepcopy(f.paper.state)
    enable(f)
    finish(f)
    assert f.paper.universe.selected == selected and f.paper.state == state and not f.calls


def test_utc_rollover_retains_incomplete_day_without_catchup_or_enrollment(daily, monkeypatch):
    f = daily
    enable(f)
    monkeypatch.setattr(scanner_module, "BAR_WORK", 1)
    assert f.scanner._daily_work(f.now)
    original_day = int(f.now // 86400)
    advance(f)
    assert f.scanner._daily_work(f.now)
    old = f.scanner.daily_pages()["rows"][0]
    snapshot = f.scanner.daily_snapshot(old["id"])
    assert snapshot["utc_day"] == original_day and snapshot["status"] == "incomplete"
    assert snapshot["pool"]["scored"] == 1 and snapshot["enrolled_today"] == []
    second = finish(f)
    advance(f, 4 * 86400)
    latest = finish(f)
    assert latest["missed_days"] == 3 and latest["utc_day"] == second["utc_day"] + 4
    assert f.scanner.daily_pages()["total"] == 3 and len(latest["enrolled_today"]) <= 5


def test_source_identity_change_blocks_restart_work_but_not_exact_pause(daily):
    f = daily
    enable(f)
    before = finish(f)
    original = digest(before)
    f.scanner = f.new_owner()
    f.scanner.implementation_sha256 = "f" * 64
    advance(f)
    assert asyncio.run(f.scanner.step()) is False
    assert f.scanner.snapshot()["daily_selection"]["state"] == "blocked"
    assert f.scanner.daily_pages()["total"] == 1 and not f.calls
    with pytest.raises(ValueError, match="source/storage changed"):
        enable(f, "changed-source-enable-0001")
    pause = f.scanner.control(
        {
            "action": "daily_pause",
            "request_id": "changed-source-pause-0001",
            "campaign_id": f.campaign,
        },
        f.now,
    )
    assert pause["applied"] and not f.scanner.snapshot()["enabled"]
    assert digest(f.scanner.daily_snapshot(before["id"])) == original


def test_scoring_uses_three_batched_scope_reads_not_per_market_queries(daily):
    f = daily
    enable(f)
    statements = []
    f.registry.db.set_trace_callback(statements.append)
    finish(f)
    f.registry.db.set_trace_callback(None)
    # Twelve eligible markets share one bounded slice; each source table has
    # one indexed input read regardless of the number of candidates.
    assert sum("SELECT symbol,timeframe,body FROM pattern_progress" in s for s in statements) == 1
    assert sum("FROM pattern_daily_evidence d LEFT JOIN" in s for s in statements) == 1
    assert sum("SELECT symbol FROM pattern_enrollments" in s for s in statements) == 1


def test_daily_api_v1_successor_strict_identity_and_saved_get_lost_ack(
    daily, tmp_path, monkeypatch
):
    f = daily
    predecessor = f.prepare(["COIN0USD"])["campaign_id"]
    archived_v1 = f.scanner.snapshot(predecessor)
    app = create_app(
        Settings(),
        tmp_path / "monitor.sqlite3",
        background=False,
        venue=f.venue,
        paper_database=None,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert app.state.paper is None  # Explicitly no financial database owner.
        app.state.pattern_scanner = f.scanner
        command = {
            "action": "daily_enable",
            "request_id": "daily-api-enable-0001",
            "campaign_id": predecessor,
            "expected_revision": archived_v1["revision"],
        }
        route = "/api/research/pattern-scanner/control"
        headers = {"x-local-operator": "1"}
        assert client.post(route, json=command).status_code == 403
        assert (
            client.post(route, json={**command, "unexpected": True}, headers=headers).status_code
            == 422
        )
        assert (
            client.post(
                route, json={**command, "expected_revision": False}, headers=headers
            ).status_code
            == 422
        )
        original_snapshot = f.scanner.snapshot
        monkeypatch.setattr(
            f.scanner,
            "snapshot",
            lambda *a: (_ for _ in ()).throw(ValueError("Synthetic saved response lost")),
        )
        assert client.post(route, json=command, headers=headers).status_code == 503
        monkeypatch.setattr(f.scanner, "snapshot", original_snapshot)
        recovered = client.get("/api/research/pattern-scanner/requests/" + command["request_id"])
        assert recovered.status_code == 200
        receipt = recovered.json()
        f.campaign = receipt["campaign_id"]
        assert receipt["previous_campaign_id"] == predecessor and f.campaign != predecessor
        assert receipt["applied"] is True and receipt["policy"] == DAILY_POLICY["version"]
        assert f.scanner.snapshot(predecessor)["campaign"] == archived_v1["campaign"]
        assert f.scanner.control(
            PatternControl(**command).model_dump(), f.now
        ) == f.scanner.request(command["request_id"])
        saved = finish(f)
        assert (
            client.get("/api/research/pattern-scanner/daily/shortlists/" + saved["id"]).json()
            == saved
        )
        assert client.get("/api/research/pattern-scanner/daily/shortlists").json()["total"] == 1
        assert (
            client.get(
                "/api/research/pattern-scanner/daily/shortlists/daily-" + "a" * 24
            ).status_code
            == 404
        )
        paused = client.post(
            route,
            headers=headers,
            json={
                "action": "daily_pause",
                "request_id": "daily-api-pause-0001",
                "campaign_id": f.campaign,
            },
        )
        assert paused.status_code == 200 and not paused.json()["current_status"]["enabled"]
        assert (
            client.post(
                route,
                headers=headers,
                json={
                    **command,
                    "campaign_id": f.campaign,
                    "request_id": "daily-api-stale-enable-0001",
                    "expected_revision": receipt["revision"],
                },
            ).status_code
            == 409
        )
    assert f.paper.state == f.original and not f.calls


def test_actual_native_page_recognition_indexes_original_then_ranks_partial_scope(daily):
    f = daily
    enable(f)
    first = finish(f)
    symbol = first["enrolled_today"][0]
    step = 14400000
    cutoff = int(f.now * 1000) // step * step

    def history(at, interval):
        value = row(at, interval)
        if at == cutoff - 5 * step:
            value[2] = "103"
        if at >= cutoff - 2 * step:
            value[2:6] = ["105", "99", "104", "20"]
        return value

    f.generator = history
    # This isolated method fixture declares 32 native 4h slots, not a measured
    # full year. Other enrolled frame histories remain unprepared and retained.
    for saved in f.registry.db.execute("SELECT body FROM pattern_progress").fetchall():
        state = json.loads(saved[0])
        if state["symbol"] == symbol and state["timeframe"] == "4h":
            state.update(
                requested_start_ms=cutoff - 32 * step,
                cursor_ms=cutoff - 32 * step,
                expected_bars=32,
            )
        else:
            state["retry_at"] = f.now + 86400
        f.scanner._save(f.campaign, state)

    async def run():
        for _ in range(12):
            assert await f.scanner.step()
            saved = f.registry.db.execute(
                "SELECT body FROM pattern_progress WHERE campaign=? AND symbol=? "
                "AND timeframe='4h'",
                (f.campaign, symbol),
            ).fetchone()
            if json.loads(saved[0])["status"] == "monitoring":
                return
        raise AssertionError("Finite 32-bar native recognition did not complete")

    asyncio.run(run())
    events = f.scanner.page("patterns", f.campaign, symbol, "4h")["rows"]
    actual = next(e for e in events if e["volume_confirmed"] is True)
    summary = f.registry.db.execute(
        "SELECT d.body,e.body AS original FROM pattern_daily_evidence d "
        "JOIN pattern_events e ON e.seq=d.seq WHERE d.campaign=? AND d.symbol=?",
        (f.campaign, symbol),
    ).fetchone()
    assert (
        summary["body"] == summary["original"] and json.loads(summary["body"])["id"] == actual["id"]
    )
    candidate = f.scanner._daily_candidate(f.campaign, f.paper.universe.rows[0], f.now)
    assert candidate["basis"] == "recognized_setup" and candidate["prepared_timeframes"] == ["4h"]
    assert candidate["evidence"][0]["body"] == json.loads(summary["original"])
    assert sum(c["status"] == "monitoring" for c in candidate["coverage"]) == 1
    assert len(f.calls) == 1 and f.calls[0]["interval"] == "4h"
    assert f.paper.state == f.original
