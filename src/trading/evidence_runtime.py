"""Optional bounded evidence work, queued after the financial transaction."""

import asyncio
import hashlib
import json
import time
import uuid
from collections import deque
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading.compact_memory import CompactMemory, prefix
from trading.paper_strategy import VARIANTS, Bar, features
from trading.research_evidence import (
    MAX_PACKET,
    VERSION,
    EvidenceArchive,
    EvidencePlan,
    book_features,
    digest,
)


def plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def compact_prefix(
    at: float,
    frame: dict[str, Any],
    bars: list[Bar],
    available: float,
    feature: dict[str, Any] | None,
    data_mode: str,
) -> dict[str, Any]:
    observed = plain({k: v for k, v in frame.items() if k != "book"})
    return prefix(
        at,
        frozen_bars(bars[-11:], available),
        {
            "book": book_features(observed, at),
            "closed_bar": feature,
        },
        data_mode,
    )


def frozen_bars(history: list[Bar], available_at: float) -> list[dict[str, Any]]:
    # Bar is immutable. Explicit scalar copies avoid recursive asdict/deepcopy and
    # a second JSON round trip, while retaining every original value and unit.
    return [
        {
            "open_ms": b.open_ms,
            "close_ms": b.close_ms,
            "open": str(b.open),
            "high": str(b.high),
            "low": str(b.low),
            "close": str(b.close),
            "volume": str(b.volume),
            "available_at": available_at,
        }
        for b in history[-600:]
    ]


def feature_reproduction(packet: dict[str, Any]) -> dict[str, Any]:
    if packet.get("schema") != VERSION or packet.get("kind") != "decision":
        return {"status": "unavailable", "reason": "Not a retained decision bundle"}
    book_results: dict[str, Any] = {}
    closed_results: dict[str, Any] = {}
    at = packet["at"]
    for symbol, frame in packet["frames"].items():
        book_results[symbol] = book_features(frame, at)
        raw_bars = packet["bars"].get(symbol, [])
        bars = [
            Bar(
                row["open_ms"],
                Decimal(row["open"]),
                Decimal(row["high"]),
                Decimal(row["low"]),
                Decimal(row["close"]),
                Decimal(row["volume"]),
                row["close_ms"],
            )
            for row in raw_bars
        ]
        origin = packet["feature_origin"].get(symbol)
        if origin is None:
            closed_results[symbol] = {"status": "unavailable", "reason": "Feature origin absent"}
            continue
        variants = {}
        if max(origin["computed_at"], origin.get("available_at", origin["computed_at"])) > at:
            closed_results[symbol] = {
                "status": "unavailable",
                "reason": "Feature computation was not yet available",
            }
            continue
        for version in VARIANTS:
            result = features(bars, origin["computed_at"], version)
            if result.get("bar_open_ms", 0) + 60000 < origin["ready_at"] * 1000:
                result.update(eligible=False, reason="Bootstrap only; awaiting new closed bar")
            if at * 1000 - result.get("bar_open_ms", 0) - 59999 > 90000:
                result.update(eligible=False, reason="Closed candle is stale")
            if origin["candle_error"]:
                result.update(eligible=False, reason=origin["candle_error"])
            variants[version] = result
        expected = {v: f for v, f in packet["study"].get(symbol, {}).items() if v in VARIANTS}
        closed_results[symbol] = {
            "matched": variants == expected,
            "reproduced": variants,
            "recorded": expected,
        }
        for a in packet["state_before"].get("accounts", {}).values():
            if symbol != "BTCUSD" or a.get("memory_entry_contract") != "memory-entry-v1":
                continue
            from trading.memory_quality import filtered_feature
            from trading.pattern_memory import descriptor

            recorded = packet["study"].get(symbol, {}).get(a["version"], {})
            try:
                inputs = recorded["memory_input"]
                d = descriptor(
                    inputs["bars"], inputs["cutoff"], inputs["context"], inputs["data_mode"]
                )
                available = recorded["memory_evidence"]["available_at"]
                prediction = filtered_feature(
                    variants["breakout-v1"], d, a["numerical_artifact"], available
                )
                comparable = [
                    "status",
                    "action",
                    "neighbors",
                    "expected_net_bps",
                    "profit_probability",
                    "artifact_sha256",
                ]
                matched = (
                    d == recorded["memory_descriptor"]
                    and inputs["cutoff"] <= available <= at
                    and all(
                        prediction["memory_evidence"].get(k) == recorded["memory_evidence"].get(k)
                        for k in comparable
                    )
                    and prediction["eligible"] == recorded["eligible"]
                )
            except (KeyError, ValueError, TypeError, ArithmeticError):
                matched = False
            closed_results[symbol]["memory_matched"] = matched
            closed_results[symbol]["matched"] = closed_results[symbol]["matched"] and matched
    return {
        "status": "reproduced",
        "books": book_results,
        "closed_bar_features": closed_results,
        "book_features_match": book_results == packet["book_features"],
        "numerical_limit": "Minute-quote inputs retained separately; no executable labels inferred",
    }


class EvidenceRecorder:
    def __init__(self, path: Path):
        self.path = path
        self.plan = EvidencePlan()
        self.session = uuid.uuid4().hex
        self.source_files = {
            name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
            for name in (
                "paper_engine.py",
                "paper_strategy.py",
                "research_evidence.py",
                "pattern_memory.py",
                "execution_profiles.py",
                "numerical_candidates.py",
                "memory_quality.py",
            )
        }
        self.pending: deque[dict[str, Any]] = deque()
        self.dropped = 0
        self.queue_limit = 8
        self.status: dict[str, Any] = {"state": "starting", "financial_authority": False}
        self._archive: EvidenceArchive | None = None
        self._summary_minute = -1
        self.compact_pending: deque[dict[str, Any]] = deque()
        self._compact: CompactMemory | None = None
        self.compact_status: dict[str, Any] = {"state": "starting"}
        self.compact_dropped = 0

    def compact(self, packet: dict[str, Any]) -> None:
        if len(self.compact_pending) >= 8 or len(canonical_compact(packet)) > 65536:
            self.compact_dropped += 1
            return
        self.compact_pending.append(packet)

    def selected(self, at: float, study_changed: bool) -> bool:
        if len(self.pending) >= self.queue_limit:
            self.dropped += 1
            return False
        return self.status.get("state") not in {"capacity", "unavailable", "disk_pressure"} and (
            self.plan.selected(at) or study_changed
        )

    def enqueue(self, packet: dict[str, Any]) -> None:
        if self.status.get("state") in {"capacity", "unavailable", "disk_pressure"}:
            self.dropped += 1
            return
        if len(self.pending) >= self.queue_limit:
            self.dropped += 1
            return
        if packet["kind"] != "decision" and len(self.pending) >= self.queue_limit - 2:
            self.dropped += 1
            return
        try:
            if len(json.dumps(packet, allow_nan=False).encode()) > MAX_PACKET:
                self.dropped += 1
                return
        except (ValueError, TypeError):
            self.dropped += 1
            return
        packet["queued_mono"] = time.perf_counter()
        self.pending.append(packet)

    def prepare(
        self,
        at: float,
        frames: dict[str, dict[str, Any]],
        study: dict[str, Any],
        history: dict[str, list[Bar]],
        origins: dict[str, float],
        ready_at: float,
        candle_errors: dict[str, str],
        before: dict[str, Any],
        numerical_rows: list[dict[str, Any]],
        trade_tapes: dict[str, deque[dict[str, Any]]],
        feed_status: dict[str, Any],
        *,
        feature_timing: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        frozen_frames = plain(
            {s: {k: v for k, v in f.items() if k != "book"} for s, f in frames.items()}
        )
        return {
            "at": at,
            "kind": "decision",
            "schema": VERSION,
            "session": self.session,
            "source_files": self.source_files,
            "frames": frozen_frames,
            "study": plain(study),
            "state_before": plain(before),
            "bars": (
                {
                    s: frozen_bars(
                        history.get(s, []),
                        (feature_timing or {})
                        .get(s, {})
                        .get("available_at", origins.get(s, at + 1)),
                    )
                    for s in frames
                }
            ),
            "feature_origin": {
                s: {
                    "computed_at": origins[s],
                    "available_at": (feature_timing or {})
                    .get(s, {})
                    .get("available_at", origins[s]),
                    "ready_at": ready_at,
                    "candle_error": candle_errors.get(s),
                }
                for s in frames
                if s in origins
            },
            "book_features": {s: book_features(f, at) for s, f in frozen_frames.items()},
            "numerical_rows": plain(numerical_rows),
            "observed_trades": plain({s: list(trade_tapes.get(s, [])) for s in frames}),
            "feed_status": plain(feed_status),
            "feature_timing": plain(feature_timing or {}),
            "sampling": {
                "fixed_utc_window": self.plan.selected(at),
                "entry_outcome_used_for_selection": False,
                "queue_omissions_before_capture": self.dropped,
            },
            "timing_clocks": {
                "stage_and_queue_ms": "perf_counter monotonic",
                "event_and_receipt_mono": "monotonic; Windows resolution may be coarse",
            },
            "coverage": "Sampled decisions and fixed UTC windows; intervening input gaps remain",
            "scope": "Local paper loop; recorded sources; no broker acknowledgment timing",
        }

    def complete(
        self,
        packet: dict[str, Any],
        events: list[dict[str, Any]],
        after: dict[str, Any],
        traces: list[dict[str, Any]],
        stages: dict[str, float],
        started_mono: float,
        commit_receipt: dict[str, Any] | None = None,
    ) -> None:
        # A campaign rollback can erase attempted events. Link only surviving objects
        # to the journal's exact post-commit event IDs; evaluation timing is separate.
        timing = []
        for trace in traces:
            item = {k: v for k, v in trace.items() if k != "_event"}
            if "_event" in trace:
                index = next(
                    (i for i, event in enumerate(events) if event is trace["_event"]), None
                )
                item["committed_action"] = index is not None
                if index is not None and commit_receipt:
                    full_index = index + packet.get("event_offset", 0)
                    item["journal_reference"] = next(
                        (
                            ref
                            for ref in commit_receipt["events"]
                            if ref["event_index"] == full_index
                        ),
                        None,
                    )
            timing.append(item)
        packet.update(
            events=plain(events),
            dispatch_accounts=list(packet["state_before"].get("accounts", {})),
            after_tick_sha256=digest(plain(after)),
            event_timing=timing,
            stages_ms=stages,
            receipt_to_dispatch_ms={
                s: max(0, (started_mono - f["received_mono"]) * 1000)
                for s, f in packet["frames"].items()
                if "received_mono" in f
            },
            financial_commit=plain(commit_receipt) if commit_receipt else None,
            commit_mono=commit_receipt["commit_mono"] if commit_receipt else time.monotonic(),
        )
        self.enqueue(packet)

    def summary(self, at: float, frames: dict[str, dict[str, Any]], errors: dict[str, str]) -> None:
        minute = int(at // self.plan.summary_seconds)
        if minute == self._summary_minute:
            return
        self._summary_minute = minute
        self.enqueue(
            {
                "at": at,
                "kind": "summary",
                "schema": VERSION,
                "session": self.session,
                "markets": {
                    s: book_features(plain({k: v for k, v in f.items() if k != "book"}), at)
                    for s, f in frames.items()
                },
                "gaps": dict(errors),
                "coverage": "Broad fixed-period sampled summary",
            }
        )

    def raw(self, records: list[dict[str, Any]]) -> None:
        for row in records:
            if self.plan.selected(row["received_at"]) or row["kind"] in {
                "gap",
                "resync",
                "stream_error",
                "stream_gap",
                "trade_gap",
            }:
                self.enqueue(
                    {
                        "at": row["received_at"],
                        "kind": "wire",
                        "schema": VERSION,
                        "session": self.session,
                        "observation": deepcopy(row),
                    }
                )

    async def flush(self, disk_available: bool = True) -> None:
        compact = [self.compact_pending.popleft() for _ in range(len(self.compact_pending))]
        packets = [self.pending.popleft() for _ in range(min(8, len(self.pending)))]
        await asyncio.to_thread(self._write_batch, compact, packets, disk_available)

    def _write_batch(
        self, compact: list[dict[str, Any]], packets: list[dict[str, Any]], disk_available: bool
    ) -> None:
        # One off-thread write batch serves both bounded archives. No SQLite work
        # or extra executor round trips run in financial/event-loop processing.
        if compact:
            try:
                if self._compact is None:
                    self._compact = CompactMemory(self.path.with_name("memory-episodes.sqlite"))
                for packet in compact:
                    self._compact.append(packet, disk_available=disk_available)
                self.compact_status = self._compact.snapshot()
            except Exception:
                self.compact_dropped += len(compact)
                self.compact_status = {"state": "unavailable"}
        try:
            if self._archive is None:
                self._archive = EvidenceArchive(self.path)
                self.plan = self._archive.plan
            at = time.perf_counter()
            for packet in packets:
                packet["queue_wait_ms"] = max(0, (at - packet.pop("queued_mono")) * 1000)
            self._archive.append(packets, disk_available=disk_available)
            self.status = self._archive.snapshot()
        except Exception:
            self.dropped += len(packets)
            raise

    async def run(self, disk_check: Callable[[], bool]) -> None:
        try:
            while True:
                try:
                    work = asyncio.create_task(self.flush(disk_check()))
                    try:
                        await asyncio.shield(work)
                    except asyncio.CancelledError:
                        await work
                        raise
                except Exception:
                    self.status = {
                        "state": "unavailable",
                        "financial_authority": False,
                        "reason": "Evidence storage failed; financial operation continues",
                    }
                    self.dropped += len(self.pending)
                    self.pending.clear()
                await asyncio.sleep(0.25)
        finally:
            if self._archive is not None:
                self._archive.close()
            if self._compact is not None:
                self._compact.close()

    def snapshot(self) -> dict[str, Any]:
        return {
            **self.status,
            "queue": len(self.pending),
            "queue_limit": self.queue_limit,
            "queue_dropped": self.dropped,
            "selection": asdict(self.plan),
            "compact_memory": {
                **self.compact_status,
                "queue": len(self.compact_pending),
                "omitted": self.compact_dropped,
            },
        }


def canonical_compact(packet: dict[str, Any]) -> bytes:
    return json.dumps(packet, allow_nan=False).encode()
