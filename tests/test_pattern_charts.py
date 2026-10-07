"""Saved native chart reads; no operating database, venue or model requests."""

import copy
from decimal import Decimal
from pathlib import Path
from threading import Thread

import pytest
from fastapi.testclient import TestClient
from test_candle_history import row
from test_pattern_scanner import Fixture

from trading.api import create_app
from trading.candle_history import INTERVALS
from trading.candle_patterns import _Zone
from trading.config import Settings
from trading.pattern_charts import saved_chart
from trading.pattern_scanner import encoded, zone_body
from trading.research_evidence import digest


@pytest.fixture
def chart_fixture(tmp_path, monkeypatch):
    fixture = Fixture(tmp_path, monkeypatch)
    fixture.prepare()
    fixture.start()
    try:
        yield fixture
    finally:
        fixture.close()


def populate(fixture, frame="4h", count=300, *, skip=()):
    state = fixture.state(frame)
    step = INTERVALS[frame] * 1000
    start = state["cursor_ms"]
    end = start + count * step
    originals = [row(start + index * step, step) for index in range(count) if index not in skip]
    refs = fixture.scanner._retain(fixture.campaign, state, originals, end, fixture.now)
    fixture.scanner._stage(fixture.campaign, state, originals, refs, end, fixture.now)
    for _ in range(2000):
        state = fixture.state(frame)
        if "pending" not in state:
            return originals, refs
        assert fixture.scanner._work(fixture.campaign, state)
    pytest.fail("Finite disposable scanner processing fixture did not settle")


def chart(fixture, frame="4h", **kwargs):
    return saved_chart(fixture.scanner, fixture.campaign, "BTCUSD", frame, **kwargs)


def snapshot(fixture):
    return {
        table: [tuple(value) for value in fixture.registry.db.execute(f"SELECT * FROM {table}")]
        for table in (
            "pattern_campaigns",
            "pattern_progress",
            "pattern_pages",
            "pattern_levels",
            "pattern_events",
            "pattern_controls",
        )
    }


def level(fixture, identity, at, *, frame="4h", segment=0):
    body = {
        "id": identity,
        "kind": "support",
        "price": "99",
        "low": "98.85",
        "high": "99.15",
        "pivot_open_ms": at - 3 * INTERVALS[frame] * 1000 + 1,
        "confirmed_at_ms": at,
        "first_usable_ms": at + 1,
        "source_sha256": digest(identity),
        "source_references": [],
        "input_window_sha256": digest([identity]),
        "observed_at": fixture.now,
        "segment": segment,
        "historical": True,
        "financial_authority": False,
    }
    zone = _Zone(
        identity,
        "support",
        Decimal(body["price"]),
        Decimal(body["low"]),
        Decimal(body["high"]),
        at,
        body["pivot_open_ms"],
    )
    fixture.registry.db.execute(
        "INSERT INTO pattern_levels(campaign,symbol,timeframe,identity,price,kind,body,"
        "state,segment) "
        "VALUES(?,?,?,?,99,'support',?,?,?)",
        (
            fixture.campaign,
            "BTCUSD",
            frame,
            identity,
            encoded(body),
            encoded(zone_body(zone)),
            segment,
        ),
    )
    return body


def event(fixture, identity, at, *, frame="4h", kind="patterns"):
    body = {
        "id": identity,
        "kind": "support_bounce",
        "bar_open_ms": at,
        "bar_close_ms": at + INTERVALS[frame] * 1000 - 1,
        "level_id": "original-level",
        "level_price": "99.0001",
        "volume_ratio": "2.123",
        "volume_confirmed": True,
        "reason": "Original retained recognition, never recomputed by the chart",
        "historical": kind == "patterns",
        "financial_authority": False,
        "source_sha256": digest(identity),
        "source_references": [],
        "input_window_sha256": digest([identity]),
    }
    if kind == "alerts":
        body["evaluation"] = {"status": "unknown", "unknowns": ["Current book unavailable"]}
    fixture.registry.db.execute(
        "INSERT INTO pattern_events(campaign,symbol,timeframe,identity,kind,body) "
        "VALUES(?,?,?,?,?,?)",
        (fixture.campaign, "BTCUSD", frame, identity, kind, encoded(body)),
    )
    return body


@pytest.mark.parametrize("frame", list(INTERVALS))
def test_latest_exact_native_processed_buffer_and_read_only_scope(chart_fixture, frame):
    f = chart_fixture
    populate(f, frame, 120)
    state = f.state(frame)
    financial, registry = copy.deepcopy(f.paper.state), snapshot(f)
    calls = list(f.calls)
    result = chart(f, frame)
    assert len(result["candles"]) == 100
    assert [c["open_ms"] for c in result["candles"]] == [r[0] for r in state["buffer"]]
    assert all(
        c["close_ms"] - c["open_ms"] + 1 == INTERVALS[frame] * 1000 for c in result["candles"]
    )
    assert result["processed_through_ms"] == state["latest_close_ms"]
    assert result["source"]["rows_sha256"] == digest(state["buffer"])
    assert result["source"]["archive_verified"] is False
    assert result["source"]["kind"] == "saved_processed_buffer"
    assert result["coverage"]["input_candles"] == 100
    assert sum(p["sma100"] is not None for p in result["indicators"]["points"]) == 1
    assert result["financial_authority"] is False
    assert f.calls == calls and f.paper.state == financial and snapshot(f) == registry


def test_historical_original_archive_useful_sma_warmup_and_older_page(chart_fixture):
    f = chart_fixture
    originals, refs = populate(f, count=1000)
    step = INTERVALS["4h"] * 1000
    second, _ = populate(f, count=200)
    financial, registry = copy.deepcopy(f.paper.state), snapshot(f)
    result = chart(f, at_ms=originals[400][0])
    assert result["mode"] == "historical" and result["source"]["archive_verified"] is True
    assert result["source"]["references"] == refs and len(refs) == 2
    assert [c["open_ms"] for c in result["candles"]] == [r[0] for r in originals]
    assert result["source"]["rows_sha256"] == digest(originals)
    assert sum(p["sma100"] is not None for p in result["indicators"]["points"]) == 901
    newest = chart(f, before_ms=chart(f)["pagination"]["next_before_ms"])
    assert newest["candles"][0]["open_ms"] == second[0][0]
    older = chart(f, before_ms=newest["pagination"]["next_before_ms"])
    assert older["candles"][0]["open_ms"] == originals[0][0]
    assert older["pagination"]["next_before_ms"] is None
    assert older["coverage"]["requested_end_ms"] == originals[-1][0] + step - 1
    assert f.paper.state == financial and snapshot(f) == registry and not f.calls


def test_original_recognition_and_unknown_evaluation_preserved_not_analyzer_patterns(chart_fixture):
    f = chart_fixture
    originals, _ = populate(f)
    original_level = level(f, "original-level", originals[205][6])
    original_pattern = event(f, "saved-pattern", originals[250][0])
    original_alert = event(f, "saved-alert", originals[251][0], kind="alerts")
    before = snapshot(f)
    result = chart(f)
    assert [{k: v for k, v in r.items() if k != "seq"} for r in result["levels"]["rows"]] == [
        original_level
    ]
    assert [{k: v for k, v in r.items() if k != "seq"} for r in result["patterns"]["rows"]] == [
        original_pattern
    ]
    assert [{k: v for k, v in r.items() if k != "seq"} for r in result["alerts"]["rows"]] == [
        original_alert
    ]
    assert result["patterns"]["rows"][0]["level_price"] == "99.0001"
    assert (
        not {
            "zones_retained",
            "patterns_retained",
            "patterns_observed",
            "patterns_omitted_from_display",
        }
        & result["coverage"].keys()
    )
    assert snapshot(f) == before


def test_dense_known_levels_and_events_page_without_silent_omission(chart_fixture):
    f = chart_fixture
    originals, _ = populate(f)
    for index in range(225):
        level(f, f"known-{index}", originals[205][6])
        event(f, f"pattern-{index}", originals[250][0])
    first = chart(f)
    assert first["levels"]["total"] == first["patterns"]["total"] == 225
    seen_levels, seen_patterns = set(), set()
    cursor_l, cursor_p = 0, 0
    for _ in range(3):
        result = chart(
            f,
            levels_before=cursor_l,
            patterns_before=cursor_p,
            expected_progress_sha256=first["source"]["progress_sha256"],
        )
        assert len(result["levels"]["rows"]) <= 100
        seen_levels.update(r["id"] for r in result["levels"]["rows"])
        seen_patterns.update(r["id"] for r in result["patterns"]["rows"])
        cursor_l = result["levels"]["next_before"]
        cursor_p = result["patterns"]["next_before"]
    assert cursor_l is None and cursor_p is None
    assert len(seen_levels) == len(seen_patterns) == 225


def test_exact_selected_original_record_survives_overlay_page_limit_and_reload(chart_fixture):
    f = chart_fixture
    originals, _ = populate(f)
    wanted = event(f, "selected-first", originals[250][0])
    wanted_seq = f.registry.db.execute(
        "SELECT seq FROM pattern_events WHERE identity='selected-first'"
    ).fetchone()[0]
    for index in range(110):
        event(f, f"newer-{index}", originals[251][0])
    assert wanted["id"] not in {r["id"] for r in chart(f)["patterns"]["rows"]}
    selected = chart(f, at_ms=originals[250][0], selected_kind="patterns", selected_seq=wanted_seq)
    assert selected["selection"] == {
        "kind": "patterns",
        "record": {"seq": wanted_seq, **wanted},
        "known_by_window_end": True,
        "candle_available": True,
    }
    assert (
        chart(f, at_ms=originals[250][0], selected_kind="patterns", selected_seq=wanted_seq)[
            "selection"
        ]
        == selected["selection"]
    )
    with pytest.raises(LookupError, match="selected scanner record"):
        chart(f, selected_kind="alerts", selected_seq=wanted_seq)
    with pytest.raises(ValueError, match="scope"):
        chart(f, selected_kind="patterns")


def test_selected_level_never_becomes_known_before_its_confirmation(chart_fixture):
    f = chart_fixture
    originals, _ = populate(f, count=1000)
    next_rows, _ = populate(f, count=5)
    wanted = level(f, "next-page-confirmation", next_rows[1][6])
    seq = f.registry.db.execute(
        "SELECT seq FROM pattern_levels WHERE identity='next-page-confirmation'"
    ).fetchone()[0]
    # The original pivot is the last candle of the earlier retained page.
    assert wanted["pivot_open_ms"] == originals[-1][0]
    result = chart(f, at_ms=originals[-1][0], selected_kind="levels", selected_seq=seq)
    assert result["selection"]["record"] == {"seq": seq, **wanted}
    assert result["selection"]["candle_available"] is True
    assert result["selection"]["known_by_window_end"] is False
    assert wanted["id"] not in {r["id"] for r in result["levels"]["rows"]}


def test_partly_processed_page_and_event_never_claim_completed(chart_fixture):
    f = chart_fixture
    populate(f, count=100)
    state = f.state()
    step = INTERVALS["4h"] * 1000
    pending = [row(state["cursor_ms"] + index * step, step) for index in range(1000)]
    end = state["cursor_ms"] + len(pending) * step
    refs = f.scanner._retain(f.campaign, state, pending, end, f.now)
    f.scanner._stage(f.campaign, state, pending, refs, end, f.now)
    assert f.scanner._work(f.campaign, f.state())
    state = f.state()
    next_at = state["latest_close_ms"] + 1
    event(f, "partly-observed-current-bar", next_at)
    level(f, "partly-confirmed-current-bar", next_at + step - 1)
    result = chart(f)
    assert result["coverage"]["pending"] is True
    assert result["candles"][-1]["close_ms"] == state["latest_close_ms"]
    assert not result["patterns"]["rows"] and not result["levels"]["rows"]
    historical = chart(f, at_ms=pending[0][0])
    assert len(historical["candles"]) == state["pending"]["index"]
    assert historical["candles"][-1]["close_ms"] == state["latest_close_ms"]


def test_gaps_and_missing_selected_native_slot_remain_explicit(chart_fixture):
    f = chart_fixture
    originals, _ = populate(f, count=240, skip=(120,))
    state = f.state()
    at = state["requested_start_ms"] + 120 * INTERVALS["4h"] * 1000
    result = chart(f, at_ms=at)
    assert at not in {c["open_ms"] for c in result["candles"]}
    assert len(result["candles"]) == len(originals) == 239
    assert result["coverage"]["missing_candles"] == 1
    assert result["coverage"]["state"] == "gapped" and len(result["gaps"]) == 1
    assert result["indicators"]["points"][120]["sma100"] is None
    assert state["gap_count"] == 1 and chart(f)["coverage"]["scanner_missing_bars"] == 1
    assert result["coverage"]["selected_at_ms"] == at
    assert result["coverage"]["selected_candle_available"] is False


@pytest.mark.parametrize("historical", [False, True])
def test_overlay_continuation_requires_exact_saved_progress(chart_fixture, historical):
    f = chart_fixture
    originals, _ = populate(f)
    for index in range(110):
        level(f, f"bound-{index}", originals[205][6])
    window = {"at_ms": originals[250][0]} if historical else {}
    first = chart(f, **window)
    cursor = first["levels"]["next_before"]
    with pytest.raises(ValueError, match="cursor"):
        chart(f, **window, levels_before=cursor)
    second = chart(
        f,
        **window,
        levels_before=cursor,
        expected_progress_sha256=first["source"]["progress_sha256"],
    )
    assert len(second["levels"]["rows"]) == 10
    populate(f, count=10)
    with pytest.raises(ValueError, match="progress advanced"):
        chart(
            f,
            **window,
            levels_before=cursor,
            expected_progress_sha256=first["source"]["progress_sha256"],
        )
    refreshed = chart(f, **window)
    assert refreshed["source"]["progress_sha256"] != first["source"]["progress_sha256"]


def test_partial_historical_window_cannot_extend_between_overlay_pages(chart_fixture):
    f = chart_fixture
    state = f.state()
    step = INTERVALS["4h"] * 1000
    raw = [row(state["cursor_ms"] + index * step, step) for index in range(300)]
    end = state["cursor_ms"] + len(raw) * step
    refs = f.scanner._retain(f.campaign, state, raw, end, f.now)
    f.scanner._stage(f.campaign, state, raw, refs, end, f.now)
    assert f.scanner._work(f.campaign, f.state())
    for index in range(110):
        level(f, f"partial-{index}", raw[0][6])
    first = chart(f, at_ms=raw[0][0])
    assert len(first["candles"]) < len(raw)
    assert f.scanner._work(f.campaign, f.state())
    with pytest.raises(ValueError, match="progress advanced"):
        chart(
            f,
            at_ms=raw[0][0],
            levels_before=first["levels"]["next_before"],
            expected_progress_sha256=first["source"]["progress_sha256"],
        )


def test_historical_storage_plan_change_refuses_before_archive_open(chart_fixture, monkeypatch):
    f = chart_fixture
    originals, _ = populate(f)
    import trading.pattern_charts as projection

    def forbidden(*args):
        pytest.fail("Changed frozen plan must not open an archive")

    monkeypatch.setattr(projection, "reopen_evidence", forbidden)
    f.scanner.plan = f.plan.model_copy(update={"segment_bytes": f.plan.segment_bytes + 1})
    with pytest.raises(ValueError, match="storage identity changed"):
        chart(f, at_ms=originals[100][0])
    assert not f.calls and f.paper.state == f.original


def test_causal_visible_segments_do_not_infer_unseen_historical_continuity(chart_fixture):
    f = chart_fixture
    originals, _ = populate(f, count=240, skip=(120,))
    known = chart(f, at_ms=originals[30][0])
    assert [span["scanner_segment"] for span in known["coverage"]["segment_spans"]] == [0, 1]
    old_level = level(f, "before-gap", originals[20][6], segment=0)
    current_level = level(f, "after-gap", originals[180][6], segment=1)
    latest = chart(f)
    assert len(latest["coverage"]["segment_spans"]) == 1
    assert latest["coverage"]["segment_spans"][0]["scanner_segment"] == 1
    assert {r["id"]: r["segment"] for r in latest["levels"]["rows"]} == {
        old_level["id"]: 0,
        current_level["id"]: 1,
    }
    populate(f, count=20)
    earlier = chart(f, at_ms=originals[30][0])
    assert [span["scanner_segment"] for span in earlier["coverage"]["segment_spans"]] == [
        None,
        None,
    ]
    assert earlier["levels"]["total"] == 2


def test_empty_unprepared_short_error_and_unchanged_identity_are_honest(chart_fixture):
    f = chart_fixture
    identity = f.scanner.implementation_sha256
    empty = chart(f)
    assert empty["candles"] == [] and empty["coverage"]["state"] == "empty"
    assert empty["processed_through_ms"] is None and empty["pagination"]["next_before_ms"] is None
    populate(f, count=4)
    state = f.state()
    state.update(status="source_blocked", error="Original native source failed")
    f.scanner._save(f.campaign, state)
    result = chart(f)
    assert len(result["candles"]) == 4 and result["coverage"]["scanner_error"] == state["error"]
    assert all(point["sma10"] is None for point in result["indicators"]["points"])
    assert result["source"]["implementation_sha256"] == identity
    assert f.scanner.implementation_sha256 == identity


def test_archive_and_indicator_work_do_not_hold_shared_registry_lock(chart_fixture, monkeypatch):
    f = chart_fixture
    originals, _ = populate(f)
    import trading.pattern_charts as projection

    original_reader = projection.reopen_evidence
    original_analysis = projection.analyze_candles

    def independent_lock_read():
        acquired = []

        def read():
            with f.registry.lock:
                acquired.append(f.registry.db.execute("SELECT 1").fetchone()[0])

        thread = Thread(target=read)
        thread.start()
        thread.join(1)
        assert not thread.is_alive() and acquired == [1]

    def reader(*args):
        independent_lock_read()
        return original_reader(*args)

    def analysis(*args):
        independent_lock_read()
        return original_analysis(*args)

    monkeypatch.setattr(projection, "reopen_evidence", reader)
    monkeypatch.setattr(projection, "analyze_candles", analysis)
    assert chart(f, at_ms=originals[100][0])["candles"]


@pytest.mark.parametrize("alteration", ["identity", "checksum", "offset", "count", "missing"])
def test_bad_archived_source_refuses_without_fresh_fetch(chart_fixture, monkeypatch, alteration):
    f = chart_fixture
    originals, _ = populate(f)
    import trading.pattern_charts as projection

    reader = projection.reopen_evidence

    def changed(plan, reference):
        if alteration == "missing":
            raise LookupError("Exact source unavailable")
        packet = copy.deepcopy(reader(plan, reference))
        if alteration == "identity":
            packet["symbol"] = "ETHUSD"
        elif alteration == "checksum":
            packet["rows"][0][1] = "99.5"
        elif alteration == "offset":
            packet["offset"] = 500
        elif alteration == "count":
            packet["rows"].append(copy.deepcopy(packet["rows"][0]))
        return packet

    monkeypatch.setattr(projection, "reopen_evidence", changed)
    before = snapshot(f)
    with pytest.raises((ValueError, LookupError)):
        chart(f, at_ms=originals[100][0])
    assert snapshot(f) == before and not f.calls and f.paper.state == f.original


@pytest.mark.parametrize(
    "kwargs",
    [
        {"at_ms": -1},
        {"before_ms": True},
        {"at_ms": 1, "before_ms": 2},
        {"levels_before": 2**63},
        {"timeframe": "2h"},
    ],
)
def test_invalid_scope_and_cursors_refused_before_archive(chart_fixture, kwargs):
    f = chart_fixture
    kwargs = dict(kwargs)
    frame = kwargs.pop("timeframe", "4h")
    with pytest.raises(ValueError):
        chart(f, frame, **kwargs)
    assert not f.calls


def test_actual_get_route_historical_scope_errors_and_no_lifespan_fallback(chart_fixture, tmp_path):
    f = chart_fixture
    originals, _ = populate(f)
    app = create_app(Settings(), tmp_path / "explicit-absent-monitor.sqlite3", background=False)
    app.state.pattern_scanner = f.scanner
    client = TestClient(app, base_url="http://127.0.0.1")
    params = {"campaign_id": f.campaign, "symbol": "BTCUSD", "timeframe": "4h"}
    registry, financial = snapshot(f), copy.deepcopy(f.paper.state)
    try:
        latest = client.get("/api/research/pattern-scanner/chart", params=params)
        assert latest.status_code == 200, latest.text
        historical = client.get(
            "/api/research/pattern-scanner/chart", params={**params, "at_ms": originals[100][0]}
        )
        assert (
            historical.status_code == 200
            and historical.json()["source"]["archive_verified"] is True
        )
        assert (
            client.get(
                "/api/research/pattern-scanner/chart", params={**params, "timeframe": "2h"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/research/pattern-scanner/chart", params={**params, "symbol": "ETHUSD"}
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/api/research/pattern-scanner/chart",
                params={**params, "at_ms": originals[100][0], "before_ms": 1},
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/research/pattern-scanner/chart", params={**params, "at_ms": int(f.now * 1000)}
            ).status_code
            == 422
        )
        assert f.paper.state == financial and snapshot(f) == registry and not f.calls
        assert not Path(tmp_path / "explicit-absent-monitor.sqlite3").exists()
    finally:
        client.close()
