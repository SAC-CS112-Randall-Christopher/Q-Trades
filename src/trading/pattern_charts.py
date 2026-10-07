"""Bounded read views of original scanner candles and recognition.

This module does not change the scanner's frozen implementation identity. It
uses the existing registry and read-only archive reader, never a venue fetch or
a storage recovery/writer constructor.
"""

import json
import re
import time
from typing import Any

from trading.candle_history import INTERVALS, native_bar
from trading.candle_patterns import analyze_candles
from trading.pattern_scanner import PAGE_ROWS, VIEW_ROWS, PatternScanner
from trading.pattern_scanner import VERSION as SCANNER_VERSION
from trading.research_evidence import digest
from trading.research_storage import reopen_evidence

VERSION = "saved-scanner-chart-v1"
MAX_CURSOR = 9223372036854775807


def _cursor(value: int | None) -> bool:
    return value is None or type(value) is int and 0 <= value <= MAX_CURSOR


def _overlays(
    scanner: PatternScanner,
    kind: str,
    scope: tuple[str, str, str],
    start: int | None,
    end: int | None,
    before: int,
) -> dict[str, Any]:
    if end is None:
        return {"rows": [], "total": 0, "next_before": None}
    table = "pattern_levels" if kind == "levels" else "pattern_events"
    clause = "campaign=? AND symbol=? AND timeframe=?"
    args: list[Any] = list(scope)
    if kind == "levels":
        clause += " AND json_extract(body,'$.confirmed_at_ms')<=?"
        args.append(end)
    else:
        clause += (
            " AND kind=? AND json_extract(body,'$.bar_open_ms')>=?"
            " AND json_extract(body,'$.bar_close_ms')<=?"
        )
        args.extend((kind, start, end))
    total = scanner.registry.db.execute(
        f"SELECT count(*) FROM {table} WHERE {clause}", args
    ).fetchone()[0]
    if before:
        clause += " AND seq<?"
        args.append(before)
    rows = scanner.registry.db.execute(
        f"SELECT seq,body FROM {table} WHERE {clause} ORDER BY seq DESC LIMIT ?",
        [*args, VIEW_ROWS + 1],
    ).fetchall()
    return {
        "rows": [{"seq": row["seq"], **json.loads(row["body"])} for row in rows[:VIEW_ROWS]],
        "total": total,
        "next_before": rows[VIEW_ROWS - 1]["seq"] if len(rows) > VIEW_ROWS else None,
    }


def saved_chart(
    scanner: PatternScanner,
    campaign_id: str,
    symbol: str,
    timeframe: str,
    at_ms: int | None = None,
    before_ms: int | None = None,
    levels_before: int = 0,
    patterns_before: int = 0,
    alerts_before: int = 0,
    expected_progress_sha256: str | None = None,
    selected_kind: str | None = None,
    selected_seq: int | None = None,
) -> dict[str, Any]:
    """Snapshot one exact saved scope, then read/compute outside its owner lock."""
    if (
        not re.fullmatch(r"patterns-[a-f0-9]{24}", campaign_id)
        or not re.fullmatch(r"[A-Z0-9]{3,24}", symbol)
        or timeframe not in INTERVALS
        or not all(
            _cursor(value)
            for value in (at_ms, before_ms, levels_before, patterns_before, alerts_before)
        )
        or any(value is None for value in (levels_before, patterns_before, alerts_before))
        or at_ms is not None
        and before_ms is not None
        or expected_progress_sha256 is not None
        and not re.fullmatch(r"[a-f0-9]{64}", expected_progress_sha256)
        or any((levels_before, patterns_before, alerts_before))
        and expected_progress_sha256 is None
        or (selected_kind is None) != (selected_seq is None)
        or selected_kind is not None
        and selected_kind not in {"levels", "patterns", "alerts"}
        or not _cursor(selected_seq)
        or selected_seq == 0
    ):
        raise ValueError("Invalid exact saved chart scope or cursor")
    scope = (campaign_id, symbol, timeframe)
    historical = at_ms is not None or before_ms is not None
    with scanner.registry.lock:
        campaign_row = scanner.registry.db.execute(
            "SELECT body FROM pattern_campaigns WHERE id=?", (campaign_id,)
        ).fetchone()
        state_row = scanner.registry.db.execute(
            "SELECT body FROM pattern_progress WHERE campaign=? AND symbol=? AND timeframe=?",
            scope,
        ).fetchone()
        if campaign_row is None or state_row is None:
            raise LookupError("Exact saved campaign market/timeframe is unavailable")
        campaign, state = json.loads(campaign_row[0]), json.loads(state_row[0])
        if expected_progress_sha256 is not None and digest(state) != expected_progress_sha256:
            raise ValueError("Saved chart progress advanced; reopen the window before paging")
        processed = state["latest_close_ms"]
        if processed is not None and (type(processed) is not int or processed < 0):
            raise ValueError("Saved completed scanner cutoff differs")
        page = None
        if historical:
            if processed is None:
                raise LookupError("No completed native scanner history is available")
            if at_ms is not None:
                if not state["requested_start_ms"] <= at_ms <= processed:
                    raise ValueError("Selected time is outside completed scanner history")
                row = scanner.registry.db.execute(
                    "SELECT start_ms,body FROM pattern_pages WHERE campaign=? AND symbol=? "
                    "AND timeframe=? AND start_ms<=? ORDER BY start_ms DESC LIMIT 1",
                    (*scope, at_ms),
                ).fetchone()
            else:
                row = scanner.registry.db.execute(
                    "SELECT start_ms,body FROM pattern_pages WHERE campaign=? AND symbol=? "
                    "AND timeframe=? AND start_ms<? ORDER BY start_ms DESC LIMIT 1",
                    (*scope, min(before_ms or 0, processed + 1)),
                ).fetchone()
            if row is None:
                raise LookupError("Earlier saved native window is unavailable")
            page = {"start_ms": row["start_ms"], **json.loads(row["body"])}
            start, end = page["requested_start_ms"], min(page["requested_end_ms"], processed)
            if at_ms is not None and not start <= at_ms <= end:
                raise LookupError("Selected native interval has no saved source page")
            earlier = scanner.registry.db.execute(
                "SELECT 1 FROM pattern_pages WHERE campaign=? AND symbol=? AND timeframe=? "
                "AND start_ms<? LIMIT 1",
                (*scope, page["start_ms"]),
            ).fetchone()
            next_before = page["start_ms"] if earlier else None
        else:
            buffer = state["buffer"]
            if not isinstance(buffer, list) or len(buffer) > 100:
                raise ValueError("Saved completed candle buffer exceeds its bound")
            start = buffer[0][0] if buffer else None
            end = processed if buffer else None
            available = scanner.registry.db.execute(
                "SELECT 1 FROM pattern_pages WHERE campaign=? AND symbol=? AND timeframe=? "
                "AND start_ms<? LIMIT 1",
                (*scope, (processed + 1) if processed is not None else 0),
            ).fetchone()
            next_before = processed + 1 if available and processed is not None else None
        overlays = {
            kind: _overlays(scanner, kind, scope, start, end, cursor)
            for kind, cursor in (
                ("levels", levels_before),
                ("patterns", patterns_before),
                ("alerts", alerts_before),
            )
        }
        selected = None
        if selected_kind is not None:
            table = "pattern_levels" if selected_kind == "levels" else "pattern_events"
            args: list[Any] = [*scope, selected_seq]
            clause = "campaign=? AND symbol=? AND timeframe=? AND seq=?"
            if selected_kind != "levels":
                clause += " AND kind=?"
                args.append(selected_kind)
            selected_row = scanner.registry.db.execute(
                f"SELECT seq,body FROM {table} WHERE {clause}", args
            ).fetchone()
            if selected_row is None:
                raise LookupError("Exact selected scanner record is unavailable in this scope")
            selected = {"seq": selected_row["seq"], **json.loads(selected_row["body"])}
    # The original pages, event bodies and campaign are immutable. No archive I/O
    # or indicator work holds the shared research registry lock.
    rows = state["buffer"] if page is None else []
    references = list(dict.fromkeys(ref for refs in state["buffer_refs"] for ref in refs))
    if page is not None:
        references = page["references"]
        if scanner.plan is None:
            raise OSError("Saved scanner archive configuration is unavailable")
        if digest(scanner.plan.model_dump()) != campaign["storage_plan_sha256"]:
            raise ValueError("Frozen scanner storage identity changed; no archive substitute")
        if not isinstance(references, list) or not 1 <= len(references) <= 2:
            raise ValueError("Saved native window exceeds two archive references")
        for index, reference in enumerate(references):
            if not isinstance(reference, str) or len(reference) > 200:
                raise ValueError("Saved native archive reference differs")
            packet = reopen_evidence(scanner.plan, reference)
            if (
                not isinstance(packet, dict)
                or packet.get("kind") != "native_year_pattern_inputs"
                or packet.get("version") != SCANNER_VERSION
                or packet.get("campaign_id") != campaign_id
                or packet.get("symbol") != symbol
                or packet.get("timeframe") != timeframe
                or packet.get("requested_start_ms") != page["requested_start_ms"]
                or packet.get("requested_end_ms") != page["requested_end_ms"]
                or packet.get("offset") != index * 500
                or not isinstance(packet.get("rows"), list)
                or len(packet["rows"]) > 500
            ):
                raise ValueError("Saved native archive identity differs; no substitute")
            rows.extend(packet["rows"])
        if (
            len(rows) > PAGE_ROWS
            or len(rows) != page["count"]
            or digest(rows) != page["rows_sha256"]
        ):
            raise ValueError("Saved native page count or original checksum differs")
    interval = INTERVALS[timeframe] * 1000
    native = [native_bar(row, interval) for row in rows]
    if any(
        bar.open_ms < (page["requested_start_ms"] if page else state["requested_start_ms"])
        or page is not None
        and bar.close_ms > page["requested_end_ms"]
        or index
        and bar.open_ms <= native[index - 1].open_ms
        for index, bar in enumerate(native)
    ):
        raise ValueError("Saved native candles are unordered or outside original scope")
    native = [bar for bar in native if processed is not None and bar.close_ms <= processed]
    observed_at = time.time()
    analysis = analyze_candles(native, timeframe, observed_at)
    actual_start = native[0].open_ms if native else None
    actual_end = native[-1].close_ms if native else None
    expected = 0 if start is None or end is None else (end + 1 - start) // interval
    spans: list[dict[str, Any]] = []
    for bar in native:
        if not spans or bar.open_ms != spans[-1]["end_ms"] + 1:
            spans.append({"start_ms": bar.open_ms, "end_ms": bar.close_ms, "scanner_segment": None})
        else:
            spans[-1]["end_ms"] = bar.close_ms
    # A window ending at the exact processed cutoff can bind its visible runs
    # backwards from the saved scanner segment. Earlier windows cannot infer an
    # unseen gap's segment identity, so their historical continuity stays unknown.
    if native and actual_end == processed:
        for index, span in enumerate(spans):
            span["scanner_segment"] = state["segment"] - (len(spans) - index - 1)
    coverage = {
        **{
            key: analysis["coverage"][key]
            for key in (
                "state",
                "input_candles",
                "segments",
                "latest_segment_candles",
                "latest_close_age_seconds",
                "warmup",
            )
        },
        "actual_start_ms": actual_start,
        "actual_end_ms": actual_end,
        "requested_start_ms": start,
        "requested_end_ms": end,
        "missing_candles": max(0, expected - len(native)),
        "source_available": bool(native),
        "source_error": None,
        "scanner_status": state["status"],
        "scanner_error": state["error"],
        "scanner_observed_bars": state["observed_bars"],
        "scanner_expected_bars": state["expected_bars"],
        "scanner_missing_bars": state["missing_bars"],
        "scanner_gap_count": state["gap_count"],
        "segment_spans": spans,
        "pending": "pending" in state,
        "selected_at_ms": at_ms,
        "selected_candle_available": (
            None if at_ms is None else any(bar.open_ms <= at_ms <= bar.close_ms for bar in native)
        ),
    }
    return {
        "version": VERSION,
        "campaign_id": campaign_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "seconds": INTERVALS[timeframe],
        "observed_at": observed_at,
        "mode": "historical" if historical else "latest",
        "processed_through_ms": processed,
        "candles": analysis["candles"],
        "indicators": analysis["indicators"],
        **overlays,
        "selection": (
            None
            if selected is None
            else {
                "kind": selected_kind,
                "record": selected,
                "known_by_window_end": end is not None
                and selected["confirmed_at_ms" if selected_kind == "levels" else "bar_close_ms"]
                <= end,
                "candle_available": any(
                    bar.open_ms
                    == selected["pivot_open_ms" if selected_kind == "levels" else "bar_open_ms"]
                    for bar in native
                ),
            }
        ),
        "coverage": coverage,
        "gaps": analysis["gaps"],
        "pagination": {"next_before_ms": next_before},
        "source": {
            "kind": "retained_native_page" if historical else "saved_processed_buffer",
            "rows_sha256": digest(rows),
            "raw_rows_count": len(rows),
            "displayed_rows_count": len(native),
            "progress_sha256": digest(state),
            "recognition_source_sha256": state["source_sha256"],
            "implementation_sha256": campaign["implementation_sha256"],
            "references": references,
            "archive_verified": historical,
        },
        "parameters": analysis["parameters"],
        "limitations": [
            "Candles and original recognition belong to the exact saved scanner campaign.",
            "Indicators are display-only recomputations within this bounded window; "
            "their warmup is explicit.",
            "Analyzer zones/patterns are not substituted for original scanner records.",
            "Historical candles were retrieved when scanned, not necessarily observed "
            "in earlier paper decisions.",
            "Level lines first exist at their saved first_usable_ms, not at their pivot timestamp.",
            "All original recognition remains paginated; a chart page is not the "
            "entire detected set.",
            "Latest shows at most 100 processed candles; historical reads at most "
            "two archived chunks.",
            "A level's continuation before an earlier window is unknown unless its "
            "saved scanner segment can be bound to that visible run.",
            "No trading edge, execution authority or prospective performance follows from a chart.",
        ],
        "financial_authority": False,
    }
