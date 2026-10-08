"""Bounded native OHLCV studies retained by the existing tool/capture owners.

These are historical public observations retrieved now, never reconstructed
prospective trading inputs. No financial database or active strategy is written.
"""

import copy
import json
import math
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from decimal import Decimal, InvalidOperation
from typing import Any

from trading.candle_patterns import analyze_candles
from trading.paper_strategy import Bar
from trading.research_evidence import digest
from trading.research_storage import ResearchStorage, StoragePlan, reopen_evidence
from trading.venue import PublicVenue

INTERVALS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}
WINDOWS = {"week": 7, "month": 30, "six_months": 180, "year": 365}
MAX_BARS = 5000
MAX_PAGES = 6


def native_bar(row: list[Any], step_ms: int) -> Bar:
    if not isinstance(row, list) or not 7 <= len(row) <= 12:
        raise ValueError("Malformed public candle row")
    if type(row[0]) is not int or type(row[6]) is not int:
        raise ValueError("Candle timestamps must be integer milliseconds")
    if row[0] < 0 or row[0] % step_ms or row[6] != row[0] + step_ms - 1:
        raise ValueError("Candle interval identity differs from requested UTC timeframe")
    if any(not isinstance(v, str) or len(v) > 64 for v in row[1:6]):
        raise ValueError("Candle OHLCV must contain bounded decimal strings")
    try:
        values = [Decimal(v) for v in row[1:6]]
    except InvalidOperation as exc:
        raise ValueError("Invalid candle decimal") from exc
    if not all(v.is_finite() for v in values):
        raise ValueError("Nonfinite candle observation")
    if any(v and abs(v.adjusted()) > 30 for v in values):
        raise ValueError("Candle decimal exceeds the declared chart numeric range")
    opened, high, low, closed, volume = values
    if not 0 < low <= min(opened, closed) <= max(opened, closed) <= high or volume < 0:
        raise ValueError("Invalid candle price range or volume")
    return Bar(row[0], opened, high, low, closed, volume, row[6])


async def load_history(
    venue: PublicVenue, symbol: str, timeframe: str, window: str, now: float
) -> tuple[dict[str, Any], list[list[Any]]]:
    if timeframe not in INTERVALS or window not in {"recent", *WINDOWS}:
        raise ValueError("Unsupported candle study scope")
    if not math.isfinite(now) or now <= 0:
        raise ValueError("Invalid observation cutoff")
    step = INTERVALS[timeframe] * 1000
    cutoff = int(now * 1000) // step * step
    requested = (
        cutoff - 240 * step if window == "recent" else max(0, cutoff - WINDOWS[window] * 86400000)
    )
    requested = (requested + step - 1) // step * step
    start = max(requested, cutoff - MAX_BARS * step)
    cursor = start
    bars: list[Bar] = []
    originals: list[list[Any]] = []
    pages = 0
    while cursor < cutoff and pages < MAX_PAGES and len(bars) < MAX_BARS:
        limit = min(1000, MAX_BARS - len(bars), (cutoff - cursor) // step)
        rows = await venue.historical_candles(symbol, timeframe, cursor, cutoff - 1, limit)
        pages += 1
        if not isinstance(rows, list) or len(rows) > limit:
            raise ValueError("Public candle response exceeds its requested bound")
        if not rows:
            break
        previous = cursor - step
        for row in rows:
            bar = native_bar(row, step)
            if bar.open_ms < cursor or bar.open_ms <= previous or bar.close_ms >= cutoff:
                raise ValueError(
                    "Public candle response is unordered, duplicated or outside cutoff"
                )
            previous = bar.open_ms
            bars.append(bar)
            originals.append(copy.deepcopy(row))
        cursor = bars[-1].open_ms + step
    if not bars:
        raise ValueError("No completed candles were returned for this market and interval")
    observed_at = time.time()
    # CPU work is moved off the event loop by the caller below.
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "window": window,
        "cutoff": cutoff / 1000,
        "observed_at": observed_at,
        "requested_start_ms": requested,
        "bounded_start_ms": start,
        "requested_end_ms": cutoff - 1,
        "pages": pages,
        "truncated": start > requested or cursor < cutoff and pages == MAX_PAGES,
        "source": "binance.us-public-native-klines",
        "source_sha256": digest(originals),
    }, originals


def analyze_history(scope: dict[str, Any], originals: list[list[Any]]) -> dict[str, Any]:
    step = INTERVALS[scope["timeframe"]] * 1000
    bars = [native_bar(row, step) for row in originals]
    result = analyze_candles(bars, scope["timeframe"], scope["cutoff"])
    result.update({key: value for key, value in scope.items() if key != "cutoff"})
    result["coverage"].update(
        requested_start_ms=scope["requested_start_ms"],
        actual_start_ms=bars[0].open_ms,
        actual_end_ms=bars[-1].close_ms,
        requested_end_ms=scope["requested_end_ms"],
        bar_count=len(bars),
        expected_bars=(scope["requested_end_ms"] + 1 - scope["requested_start_ms"]) // step,
        missing_bars=(scope["requested_end_ms"] + 1 - scope["bounded_start_ms"]) // step
        - len(bars),
        truncated=scope["truncated"],
        latest_close_age_seconds=scope["observed_at"] - bars[-1].close_ms / 1000,
        latest_close_age_basis="Wall clock when the source read completed",
    )
    result["evidence_kind"] = "historical_public_candles_retrieved_at_request_time"
    result["financial_authority"] = False
    result["limitations"].append(
        "Historical candles retrieved now were not observed inputs to earlier paper decisions; "
        "patterns are descriptive hypotheses, not after-cost performance evidence."
    )
    return result


def retain_history(
    plan: StoragePlan,
    namespace: str,
    run_id: int,
    analysis: dict[str, Any],
    raw: list[list[Any]],
    account: str = "primary",
    storage_owner: Callable[[StoragePlan], AbstractContextManager[ResearchStorage]] | None = None,
) -> dict[str, Any]:
    """Keep exact inputs and full chart in the existing bounded research store."""
    access = storage_owner(plan) if storage_owner else closing(ResearchStorage(plan))
    with access as with_store:
        now = time.time()
        if not 0 < len(raw) <= MAX_BARS or len(analysis["candles"]) != len(raw):
            raise ValueError("Candle study input and analysis counts differ")
        # Fixed-size chunks stay below the existing packet cap, even for long legal
        # decimal values. Never shorten a study merely to fit its hot receipt.
        references = []
        until = now + plan.temporary_retention_seconds
        for start in range(0, len(raw), 500):
            packet = {
                "kind": "candle_pattern_chunk",
                "at": now,
                "namespace": namespace,
                "run_id": run_id,
                "start": start,
                "rows": raw[start : start + 500],
                "candles": analysis["candles"][start : start + 500],
                "points": analysis["indicators"]["points"][start : start + 500],
            }
            reference = with_store.append([packet], now)[0]
            if with_store.reopen(reference) != packet:
                raise ValueError("Retained candle chunk verification failed")
            with_store.protect(reference, until, "Saved candle study inputs and chart")
            references.append(reference)
        header = copy.deepcopy(analysis)
        header["candles"] = []
        header["indicators"]["points"] = []
        full = {
            "kind": "candle_pattern_manifest",
            "at": now,
            "namespace": namespace,
            "run_id": run_id,
            "chunk_references": references,
            "bar_count": len(raw),
            "analysis": header,
        }
        full_reference = with_store.append([full], now)[0]
        if with_store.reopen(full_reference) != full:
            raise ValueError("Retained candle analysis verification failed")
        # Same existing protection/retention owner; no new quota or archive policy.
        with_store.protect(full_reference, until, "Saved candle study chart")
        overview = copy.deepcopy(analysis)
        overview["candles"] = overview["candles"][-1:]
        overview["indicators"]["points"] = overview["indicators"]["points"][-1:]
        overview["coverage"]["gaps_total"] = len(overview["gaps"])
        overview["coverage"]["gaps_omitted_from_overview"] = max(0, len(overview["gaps"]) - 1)
        overview["gaps"] = overview["gaps"][-1:]
        return {
            "result": overview,
            "envelope": {
                "account": account,
                "disclosure_start": analysis["coverage"]["actual_start_ms"] / 1000,
                "observation_cutoff": analysis["requested_end_ms"] / 1000,
                "overview_scope": (
                    "Latest candle and gap only; full saved chart reopens "
                    "from exact retained inputs"
                ),
                "candle_analysis_reference": full_reference,
                "candle_analysis_sha256": digest(analysis),
                "retention_until": until,
            },
        }


def reopen_history(plan: StoragePlan, namespace: str, receipt: dict[str, Any]) -> None:
    value = receipt.get("result")
    if receipt.get("tool") != "candle_patterns" or not value:
        return
    envelope = value["envelope"]
    full = reopen_evidence(plan, envelope["candle_analysis_reference"])
    if (
        full.get("kind") != "candle_pattern_manifest"
        or full.get("namespace") != namespace
        or full.get("run_id") != receipt["id"]
        or not 0 < full.get("bar_count", 0) <= MAX_BARS
        or len(full.get("chunk_references", [])) != (full["bar_count"] + 499) // 500
    ):
        raise ValueError("Saved candle study identity differs")
    analysis = copy.deepcopy(full["analysis"])
    raw_rows = []
    for index, reference in enumerate(full["chunk_references"]):
        chunk = reopen_evidence(plan, reference)
        expected = min(500, full["bar_count"] - index * 500)
        if (
            chunk.get("kind") != "candle_pattern_chunk"
            or chunk.get("namespace") != namespace
            or chunk.get("run_id") != receipt["id"]
            or chunk.get("start") != index * 500
            or any(len(chunk.get(key, [])) != expected for key in ("rows", "candles", "points"))
        ):
            raise ValueError("Saved candle chunk identity differs")
        raw_rows.extend(chunk["rows"])
        analysis["candles"].extend(chunk["candles"])
        analysis["indicators"]["points"].extend(chunk["points"])
    query = json.loads(receipt["query"])
    if (
        digest(raw_rows) != analysis["source_sha256"]
        or digest(analysis) != envelope["candle_analysis_sha256"]
        or analysis["symbol"] != receipt["symbol"]
        or any(analysis[key] != query[key] for key in ("timeframe", "window"))
        or envelope["account"] != receipt["account"]
    ):
        raise ValueError("Saved candle input identity differs")
    # Preserve the original receipt body and result_sha256 exactly. The expanded
    # chart has its own manifest/reference and analysis digest in the envelope.
    receipt["candle_analysis"] = analysis
