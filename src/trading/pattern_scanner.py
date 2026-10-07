"""Resumable native-year observations in the existing research owner.

No orders, financial history, model tasks, subscriptions or account rules are
created here. Every strict confirmed pivot is retained; pagination is a view.
"""

import asyncio
import json
import math
import time
from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from pathlib import Path
from typing import Any

from trading.candle_history import INTERVALS, native_bar
from trading.candle_patterns import ZONE_HALF_WIDTH, _visit, _volume_ratio, _Zone
from trading.experiment_registry import ExperimentRegistry
from trading.research_evidence import digest
from trading.research_storage import ResearchStorage, StoragePlan, reopen_evidence
from trading.station import cost_hurdle
from trading.venue import FeedError, PublicVenue

VERSION = "year-pattern-scanner-v1"
YEAR_MS = 365 * 86400000
MARKET_LIMIT = 2000
PAGE_ROWS = 1000
PAGE_ATTEMPTS = 3
VIEW_ROWS = 100
BAR_WORK = 20
LEVEL_WORK = 128
WORK_SECONDS = 0.05
REGISTRY_RESERVE = 128 * 1024**2
WRITE_ESTIMATE = 8 * 1024**2


def encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def zone_body(zone: _Zone) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, Decimal) else value
        for key, value in asdict(zone).items()
    }


def zone_from(body: dict[str, Any]) -> _Zone:
    value = dict(body)
    for key in ("price", "low", "high"):
        value[key] = Decimal(value[key])
    return _Zone(**value)


class PatternScanner:
    reason: str | None

    def _admission(self, estimate: int = WRITE_ESTIMATE) -> None:
        size = self.registry.db.execute("PRAGMA page_size").fetchone()[0]
        maximum = self.registry.db.execute("PRAGMA max_page_count").fetchone()[0] * size
        used = self.registry.db.execute("PRAGMA page_count").fetchone()[0] * size
        if used + estimate + REGISTRY_RESERVE > maximum:
            raise OSError(
                "Optional pattern map yields to protected registry headroom; progress retained"
            )

    async def _owned(self, function: Callable[..., Any], *args: Any) -> Any:
        work = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError as cancelled:
            try:
                await work
            except Exception:
                self.reason = "Owned scanner work failed during requested shutdown"
            raise cancelled

    def __init__(
        self,
        registry: ExperimentRegistry,
        paper: Any,
        venue: PublicVenue,
        plan: StoragePlan | None,
        storage_owner: Callable[[StoragePlan], AbstractContextManager[ResearchStorage]]
        | None = None,
    ):
        self.registry, self.paper, self.venue, self.plan = registry, paper, venue, plan
        self.storage_owner = storage_owner
        self.implementation_sha256 = digest(
            {
                name: digest(Path(__file__).with_name(name).read_text(encoding="utf8"))
                for name in ("pattern_scanner.py", "candle_patterns.py", "candle_history.py")
            }
        )
        self._busy = False
        self.reason = None
        with registry.lock:
            registry.db.executescript("""
                CREATE TABLE IF NOT EXISTS pattern_campaigns(
                    id TEXT PRIMARY KEY, body TEXT NOT NULL, enabled INTEGER NOT NULL,
                    revision INTEGER NOT NULL, created REAL NOT NULL);
                CREATE TRIGGER IF NOT EXISTS pattern_campaign_frozen
                    BEFORE UPDATE ON pattern_campaigns
                    WHEN NEW.body!=OLD.body OR NEW.id!=OLD.id OR NEW.created!=OLD.created
                    BEGIN SELECT RAISE(ABORT,'Preparation scope immutable'); END;
                CREATE TABLE IF NOT EXISTS pattern_controls(
                    request_id TEXT PRIMARY KEY, command TEXT NOT NULL, receipt TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pattern_progress(
                    campaign TEXT, symbol TEXT, timeframe TEXT, body TEXT NOT NULL,
                    status TEXT,cursor_ms INTEGER,cutoff_ms INTEGER,retry_at REAL,pending INTEGER,
                    PRIMARY KEY(campaign,symbol,timeframe));
                CREATE INDEX IF NOT EXISTS pattern_work
                    ON pattern_progress(campaign,pending,status,retry_at,cursor_ms);
                CREATE TABLE IF NOT EXISTS pattern_inputs(
                    campaign TEXT,symbol TEXT,timeframe TEXT,ordinal INTEGER,
                    row TEXT NOT NULL,row_sha256 TEXT NOT NULL,
                    PRIMARY KEY(campaign,symbol,timeframe,ordinal));
                CREATE TRIGGER IF NOT EXISTS pattern_inputs_immutable
                    BEFORE UPDATE ON pattern_inputs
                    BEGIN SELECT RAISE(ABORT,'Staged native rows immutable'); END;
                CREATE TABLE IF NOT EXISTS pattern_pages(
                    campaign TEXT,symbol TEXT,timeframe TEXT,start_ms INTEGER,
                    body TEXT NOT NULL,PRIMARY KEY(campaign,symbol,timeframe,start_ms));
                CREATE TABLE IF NOT EXISTS pattern_levels(
                    seq INTEGER PRIMARY KEY,campaign TEXT,symbol TEXT,timeframe TEXT,
                    identity TEXT NOT NULL,price REAL NOT NULL,kind TEXT NOT NULL,
                    body TEXT NOT NULL,state TEXT NOT NULL,in_visit INTEGER,breakout_until INTEGER,
                    segment INTEGER,processed_ms INTEGER,
                    UNIQUE(campaign,symbol,timeframe,identity));
                CREATE INDEX IF NOT EXISTS pattern_level_price
                    ON pattern_levels(campaign,symbol,timeframe,segment,price,seq);
                CREATE INDEX IF NOT EXISTS pattern_level_visits
                    ON pattern_levels(campaign,symbol,timeframe,segment,in_visit,seq);
                CREATE INDEX IF NOT EXISTS pattern_level_breakouts
                    ON pattern_levels(campaign,symbol,timeframe,segment,breakout_until,seq);
                CREATE TABLE IF NOT EXISTS pattern_events(
                    seq INTEGER PRIMARY KEY,campaign TEXT,symbol TEXT,timeframe TEXT,
                    identity TEXT NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL,
                    UNIQUE(campaign,symbol,timeframe,identity));
                CREATE TRIGGER IF NOT EXISTS pattern_pages_immutable_update
                    BEFORE UPDATE ON pattern_pages
                    BEGIN SELECT RAISE(ABORT,'Native pages immutable'); END;
                CREATE TRIGGER IF NOT EXISTS pattern_pages_immutable_delete
                    BEFORE DELETE ON pattern_pages
                    BEGIN SELECT RAISE(ABORT,'Native pages immutable'); END;
                CREATE TRIGGER IF NOT EXISTS pattern_controls_immutable_update
                    BEFORE UPDATE ON pattern_controls
                    BEGIN SELECT RAISE(ABORT,'Controls immutable'); END;
                CREATE TRIGGER IF NOT EXISTS pattern_controls_immutable_delete
                    BEFORE DELETE ON pattern_controls
                    BEGIN SELECT RAISE(ABORT,'Controls immutable'); END;
                CREATE TRIGGER IF NOT EXISTS pattern_events_immutable_update
                    BEFORE UPDATE ON pattern_events
                    BEGIN SELECT RAISE(ABORT,'Observations immutable'); END;
                CREATE TRIGGER IF NOT EXISTS pattern_events_immutable_delete
                    BEFORE DELETE ON pattern_events
                    BEGIN SELECT RAISE(ABORT,'Observations immutable'); END;
                CREATE TRIGGER IF NOT EXISTS pattern_levels_immutable_body
                    BEFORE UPDATE ON pattern_levels WHEN NEW.body!=OLD.body
                    BEGIN SELECT RAISE(ABORT,'Confirmed levels immutable'); END;
                CREATE TRIGGER IF NOT EXISTS pattern_levels_immutable_delete
                    BEFORE DELETE ON pattern_levels
                    BEGIN SELECT RAISE(ABORT,'Confirmed levels immutable'); END;
            """)
            # A process restart is observation recovery, never operating activation.
            registry.db.execute(
                "UPDATE pattern_campaigns SET enabled=0,revision=revision+1 WHERE enabled=1"
            )

    def roster(self, now: float) -> dict[str, Any]:
        universe = getattr(self.paper, "universe", None)
        if universe is None:
            return {"available": False, "observed_at": None, "rows": [], "eligible": 0, "total": 0}
        valid = 0 <= now - universe.scanned_at <= 120 and 0 <= now - universe.metadata_at <= 900
        rows = [
            {
                "symbol": row["symbol"],
                "eligible": valid and row.get("eligible") is True,
                "reason": row.get("reason") if valid else "Current market screen unavailable",
                "selected": False,
                "queued": valid and row.get("eligible") is True,
            }
            for row in universe.rows
        ]
        return {
            "available": valid,
            "observed_at": universe.scanned_at,
            "rows": rows,
            "total": len(rows),
            "eligible": sum(row["eligible"] for row in rows),
        }

    def _campaign(self) -> Any:
        return self.registry.db.execute(
            "SELECT * FROM pattern_campaigns ORDER BY rowid DESC LIMIT 1"
        ).fetchone()

    def control(self, command: dict[str, Any], now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        if not math.isfinite(now) or now <= 0:
            raise ValueError("Invalid control time")
        with self.registry.transaction():
            old = self.registry.db.execute(
                "SELECT * FROM pattern_controls WHERE request_id=?", (command["request_id"],)
            ).fetchone()
            if old:
                if old["command"] != encoded(command):
                    raise ValueError("Request identity belongs to a different scanner control")
                receipt: dict[str, Any] = json.loads(old["receipt"])
                return receipt
            action = command["action"]
            current = self._campaign()
            if action == "prepare":
                self._admission(WRITE_ESTIMATE + len(command.get("symbols", [])) * 8192)
                if current and current["enabled"]:
                    raise ValueError("Pause the existing preparation before declaring another")
                if self.plan is None:
                    raise ValueError("Existing owned research storage is required")
                if (
                    self.registry.db.execute("SELECT count(*) FROM pattern_campaigns").fetchone()[0]
                    >= 32
                ):
                    raise ValueError("Retained preparation capacity reached; history preserved")
                roster = self.roster(now)
                symbols = command.get("symbols", [])
                available = {r["symbol"] for r in roster["rows"] if r["eligible"]}
                if (
                    not 1 <= len(symbols) <= MARKET_LIMIT
                    or len(set(symbols)) != len(symbols)
                    or not set(symbols) <= available
                ):
                    raise ValueError(
                        "Choose currently eligible USD markets within discovery capacity"
                    )

                for row in roster["rows"]:
                    row.update(
                        selected=row["symbol"] in symbols,
                        queued=row["eligible"] and row["symbol"] not in symbols,
                    )
                campaign = "patterns-" + digest(command)[:24]
                body = {
                    "id": campaign,
                    "version": VERSION,
                    "created": now,
                    "symbols": symbols,
                    "roster": roster,
                    "requested_days": 365,
                    "timeframes": list(INTERVALS),
                    "financial_authority": False,
                    "source": "binance.us-public-native-klines",
                    "implementation_sha256": self.implementation_sha256,
                    "storage_plan_sha256": digest(self.plan.model_dump()),
                    "expected_slots_per_market": 168630,
                    "dense_native_pages_per_market": 172,
                    "maximum_source_attempts_per_page": PAGE_ATTEMPTS,
                    "limitations": [
                        "Historical discovery is not prospective performance or "
                        "independent evidence.",
                        "All confirmed pivots are descriptive; no trading edge is established.",
                        "Markets outside this bounded campaign remain queued/unprepared.",
                    ],
                }
                self.registry.db.execute(
                    "INSERT INTO pattern_campaigns VALUES(?,?,0,1,?)",
                    (campaign, encoded(body), now),
                )
                for symbol in symbols:
                    for frame, seconds in INTERVALS.items():
                        step = seconds * 1000
                        cutoff = int(now * 1000) // step * step
                        start = cutoff - YEAR_MS
                        state = {
                            "symbol": symbol,
                            "timeframe": frame,
                            "requested_start_ms": start,
                            "cutoff_ms": cutoff,
                            "cursor_ms": start,
                            "expected_bars": YEAR_MS // step,
                            "observed_bars": 0,
                            "missing_bars": 0,
                            "pages": 0,
                            "status": "queued",
                            "error": None,
                            "retry_at": 0,
                            "buffer": [],
                            "source_sha256": digest([]),
                            "gap_count": 0,
                            "segment": 0,
                            "latest_close_ms": None,
                            "request_attempts": 0,
                            "attempts_at_cursor": 0,
                            "buffer_refs": [],
                        }
                        self.registry.db.execute(
                            "INSERT INTO pattern_progress VALUES(?,?,?,?,'queued',?,?,0,0)",
                            (campaign, symbol, frame, encoded(state), start, cutoff),
                        )
                revision = 1
            else:
                if not current or current["id"] != command.get("campaign_id"):
                    raise ValueError("Exact current campaign identity is required")
                campaign, revision = current["id"], current["revision"] + 1
                if action == "start" and command.get("expected_revision") != current["revision"]:
                    raise ValueError(
                        "Preparation changed; reopen its current revision before Start"
                    )

                if action == "start":
                    frozen = json.loads(current["body"])
                    if (
                        self.plan is None
                        or frozen["implementation_sha256"] != self.implementation_sha256
                        or frozen["storage_plan_sha256"] != digest(self.plan.model_dump())
                    ):
                        raise ValueError(
                            "Frozen scanner source/storage identity changed; no automatic adoption"
                        )

                if action not in {"start", "pause"}:
                    raise ValueError("Unknown scanner control")
                self.registry.db.execute(
                    "UPDATE pattern_campaigns SET enabled=?,revision=? WHERE id=?",
                    (int(action == "start"), revision, campaign),
                )
            receipt = {
                "request_id": command["request_id"],
                "action": action,
                "campaign_id": campaign,
                "revision": revision,
                "applied": True,
                "applied_at": now,
            }
            self.registry.db.execute(
                "INSERT INTO pattern_controls VALUES(?,?,?)",
                (command["request_id"], encoded(command), encoded(receipt)),
            )
            return receipt

    def request(self, request_id: str) -> dict[str, Any] | None:
        with self.registry.lock:
            row = self.registry.db.execute(
                "SELECT receipt FROM pattern_controls WHERE request_id=?", (request_id,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def snapshot(self, campaign_id: str | None = None) -> dict[str, Any]:
        with self.registry.lock:
            current = self._campaign()
            row = (
                current
                if campaign_id is None
                else self.registry.db.execute(
                    "SELECT * FROM pattern_campaigns WHERE id=?", (campaign_id,)
                ).fetchone()
            )
            if campaign_id is not None and row is None:
                raise ValueError("Saved campaign identity unavailable")
            campaign = json.loads(row["body"]) if row else None
            identity = row["id"] if row else ""
            progress = [
                json.loads(x[0])
                for x in self.registry.db.execute(
                    "SELECT body FROM pattern_progress WHERE campaign=? ORDER BY "
                    "symbol,timeframe LIMIT 100",
                    (identity,),
                )
            ]
            counts = dict(
                self.registry.db.execute(
                    "SELECT status,count(*) FROM pattern_progress WHERE campaign=? GROUP BY status",
                    (identity,),
                )
            )
            for value in progress:
                value.pop("buffer", None)
                value.pop("pending", None)
            enabled = bool(row and row["enabled"])
            blocked = counts.get("source_blocked", 0)
            status = (
                "paused"
                if row and not enabled
                else "incomplete"
                if blocked
                else "monitoring"
                if counts and set(counts) == {"monitoring"}
                else "preparing"
                if row
                else "not_prepared"
            )
            return {
                "version": VERSION,
                "enabled": enabled,
                "campaign": campaign,
                "current_campaign_id": current["id"] if current else None,
                "is_current": bool(row and current and row["id"] == current["id"]),
                "revision": row["revision"] if row else 0,
                "progress": progress,
                "progress_counts": counts,
                "progress_total": sum(counts.values()),
                "progress_omitted": max(0, sum(counts.values()) - len(progress)),
                "roster": campaign["roster"] if campaign else self.roster(time.time()),
                "status": status,
                "reason": self.reason
                or (
                    "Native source attempts exhausted for "
                    + str(blocked)
                    + " scopes; incomplete evidence retained"
                    if blocked
                    else None
                ),
                "limits": {
                    "selected_markets": MARKET_LIMIT,
                    "native_rows_per_step": PAGE_ROWS,
                    "bars_per_processing_step": BAR_WORK,
                    "level_updates_per_step": LEVEL_WORK,
                    "processing_yield_seconds": WORK_SECONDS,
                    "protected_registry_reserve_bytes": REGISTRY_RESERVE,
                    "view_rows": VIEW_ROWS,
                    "days": 365,
                },
                "authority": "Descriptive alerts and criteria checks; no financial or model "
                "authority",
            }

    def campaigns(self) -> dict[str, Any]:
        with self.registry.lock:
            rows = []
            for row in self.registry.db.execute(
                "SELECT * FROM pattern_campaigns ORDER BY rowid DESC LIMIT 32"
            ):
                body = json.loads(row["body"])
                rows.append(
                    {
                        "id": row["id"],
                        "created": row["created"],
                        "enabled": bool(row["enabled"]),
                        "revision": row["revision"],
                        "market_count": len(body["symbols"]),
                        "timeframes": body["timeframes"],
                        "requested_days": body["requested_days"],
                    }
                )
            return {"rows": rows, "total": len(rows)}

    def page(
        self, kind: str, campaign: str, symbol: str, frame: str, before: int = 0
    ) -> dict[str, Any]:
        if kind not in {"levels", "patterns", "alerts", "progress"} or before < 0:
            raise ValueError("Invalid saved scanner scope")
        if kind == "progress":
            with self.registry.lock:
                if (
                    self.registry.db.execute(
                        "SELECT 1 FROM pattern_campaigns WHERE id=?", (campaign,)
                    ).fetchone()
                    is None
                ):
                    raise LookupError("Saved campaign is unavailable")
                progress_args = (campaign, before or 9223372036854775807)
                rows = self.registry.db.execute(
                    "SELECT rowid AS seq,body FROM pattern_progress WHERE campaign=? "
                    "AND rowid<? ORDER BY rowid DESC LIMIT 101",
                    progress_args,
                ).fetchall()
                values = []
                for row in rows[:100]:
                    value = json.loads(row["body"])
                    value.pop("buffer", None)
                    value.pop("pending", None)
                    values.append({"seq": row["seq"], **value})
                total = self.registry.db.execute(
                    "SELECT count(*) FROM pattern_progress WHERE campaign=?", (campaign,)
                ).fetchone()[0]
                return {
                    "campaign_id": campaign,
                    "rows": values,
                    "total": total,
                    "next_before": rows[99]["seq"] if len(rows) > 100 else None,
                }
        if frame not in INTERVALS:
            raise ValueError("Invalid native timeframe")
        table = "pattern_levels" if kind == "levels" else "pattern_events"
        with self.registry.lock:
            exists = self.registry.db.execute(
                "SELECT 1 FROM pattern_progress WHERE campaign=? AND symbol=? AND timeframe=?",
                (campaign, symbol, frame),
            ).fetchone()
            if not exists:
                raise LookupError("Exact prepared market/timeframe is unavailable")
            clause = "campaign=? AND symbol=? AND timeframe=?"
            args: list[Any] = [campaign, symbol, frame]
            if kind != "levels":
                clause += " AND kind=?"
                args.append(kind)
            total = self.registry.db.execute(
                f"SELECT count(*) FROM {table} WHERE {clause}", args
            ).fetchone()[0]
            if before:
                clause += " AND seq<?"
                args.append(before)
            rows = self.registry.db.execute(
                f"SELECT seq,body FROM {table} WHERE {clause} ORDER BY seq DESC LIMIT ?",
                [*args, VIEW_ROWS + 1],
            ).fetchall()
            return {
                "campaign_id": campaign,
                "symbol": symbol,
                "timeframe": frame,
                "rows": [{"seq": r["seq"], **json.loads(r["body"])} for r in rows[:VIEW_ROWS]],
                "total": total,
                "next_before": rows[VIEW_ROWS - 1]["seq"] if len(rows) > VIEW_ROWS else None,
            }

    def _allowed(self) -> bool:
        return bool(
            self.paper
            and self.paper.running
            and self.paper.error is None
            and 0 <= time.time() - self.paper.state["last_tick"] < 10
            and not self.paper.constrained()
        )

    def _evaluate(
        self, symbol: str, frame: str, buffer: list[list[Any]], pattern: dict[str, Any], at: float
    ) -> dict[str, Any]:
        bar = native_bar(buffer[-1], INTERVALS[frame] * 1000)
        age = at - bar.close_ms / 1000
        ranges = [native_bar(r, INTERVALS[frame] * 1000) for r in buffer[-15:]]
        atr = (
            sum(
                (
                    max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
                    for a, b in zip(ranges, ranges[1:], strict=False)
                ),
                Decimal(0),
            )
            / 14
            if len(ranges) == 15
            else None
        )
        hurdles: dict[str, Any] | None = None
        unknown = []
        try:
            hurdles = cost_hurdle(self.paper, symbol)
        except (ValueError, KeyError, ArithmeticError):
            unknown.append(
                "Fresh current quote, account execution costs or market filters unavailable"
            )

        quotes = self.paper.quotes()
        quote = next(
            (
                q
                for q in quotes.get("markets", [])
                if q.get("symbol") == symbol and q.get("state") == "fresh"
            ),
            None,
        )
        spread = (
            Decimal(quote["spread_bps"]) if quote and quote.get("spread_bps") is not None else None
        )
        universe = getattr(self.paper, "universe", None)
        screen = (
            next((r for r in universe.rows if r["symbol"] == symbol), None) if universe else None
        )
        screen_eligible = (
            screen.get("eligible") is True
            if screen and universe is not None and 0 <= at - universe.scanned_at <= 120
            else None
        )
        checks = {
            "closed_input_fresh": 0 <= age <= INTERVALS[frame] + 60,
            "volume_confirmed": pattern["volume_confirmed"],
            "volatility_available": None if atr is None else atr > 0,
            "spread_within_existing_25_bps": None if spread is None else spread <= 25,
            "current_universe_eligible": screen_eligible,
            "protected_research_available": self._allowed(),
            "fresh_execution_cost_inputs": None if hurdles is None else True,
        }
        if pattern["volume_confirmed"] is None:
            unknown.append("Twenty positive prior native volumes unavailable")
        if atr is None:
            unknown.append("Fourteen contiguous native true ranges unavailable")
        if spread is None or screen_eligible is None:
            unknown.append("Current observed USD screen or fresh spread unavailable")
        return {
            "status": "unknown"
            if unknown
            else "candidate"
            if all(v is True for v in checks.values())
            else "does_not_meet_criteria",
            "checks": checks,
            "unknowns": unknown,
            "atr": None if atr is None else str(atr),
            "cost_hurdle": hurdles,
            "spread_bps": None if spread is None else str(spread),
            "evaluated_at": at,
            "criteria": "Descriptive v1: native close freshness, prior20 volume>=1.5, "
            "positive14 true ranges, existing USD eligibility/spread<=25bps, "
            "protected inputs and frozen account cost hurdle availability",
            "limitations": [
                "No measured outcome or probability; not strategy approval.",
                "An alert cannot place orders, change account rules or fund an account.",
            ],
        }

    def _save(self, campaign: str, state: dict[str, Any]) -> None:
        self.registry.db.execute(
            "UPDATE pattern_progress SET "
            "body=?,status=?,cursor_ms=?,cutoff_ms=?,retry_at=?,pending=? "
            "WHERE campaign=? AND symbol=? AND timeframe=?",
            (
                encoded(state),
                state["status"],
                state["cursor_ms"],
                state["cutoff_ms"],
                state["retry_at"],
                int("pending" in state),
                campaign,
                state["symbol"],
                state["timeframe"],
            ),
        )

    def _stage(
        self,
        campaign: str,
        state: dict[str, Any],
        raw: list[list[Any]],
        references: list[str],
        end: int,
        now: float,
    ) -> None:
        with self.registry.transaction():
            self._admission(WRITE_ESTIMATE + sum(len(encoded(row).encode()) * 3 for row in raw))
            current = self._campaign()
            saved = self.registry.db.execute(
                "SELECT body FROM pattern_progress WHERE campaign=? AND symbol=? AND timeframe=?",
                (campaign, state["symbol"], state["timeframe"]),
            ).fetchone()
            if (
                not current
                or current["id"] != campaign
                or not current["enabled"]
                or json.loads(saved[0])["cursor_ms"] != state["cursor_ms"]
            ):
                return
            page = {
                "requested_start_ms": state["cursor_ms"],
                "requested_end_ms": end - 1,
                "count": len(raw),
                "rows_sha256": digest(raw),
                "references": references,
                "observed_at": now,
                "missing_bars": (end - state["cursor_ms"]) // (INTERVALS[state["timeframe"]] * 1000)
                - len(raw),
            }
            self.registry.db.execute(
                "INSERT INTO pattern_pages VALUES(?,?,?,?,?)",
                (campaign, state["symbol"], state["timeframe"], state["cursor_ms"], encoded(page)),
            )
            self.registry.db.execute(
                "INSERT OR IGNORE INTO evidence_windows VALUES(?,?,?,?)",
                (
                    "pattern-map:" + campaign + ":" + state["symbol"] + ":" + state["timeframe"],
                    state["requested_start_ms"] / 1000,
                    state["cutoff_ms"] / 1000,
                    "Native historical pattern-map disclosure",
                ),
            )
            self.registry.db.execute(
                "INSERT OR IGNORE INTO evidence_windows VALUES(?,?,?,?)",
                (
                    "pattern-page:"
                    + campaign
                    + ":"
                    + state["symbol"]
                    + ":"
                    + state["timeframe"]
                    + ":"
                    + str(state["cursor_ms"]),
                    state["cursor_ms"] / 1000,
                    end / 1000,
                    "Exact retained native pattern input slice, including continuing observations",
                ),
            )
            self.registry.db.executemany(
                "INSERT INTO pattern_inputs VALUES(?,?,?,?,?,?)",
                [
                    (
                        campaign,
                        state["symbol"],
                        state["timeframe"],
                        index,
                        encoded(row),
                        digest(row),
                    )
                    for index, row in enumerate(raw)
                ],
            )
            state["pending"] = {
                "end_ms": end,
                "count": len(raw),
                "index": 0,
                "level_after": 0,
                "references": references,
                "observed_at": now,
                "bar_started": False,
            }
            self._save(campaign, state)

    def _matches(
        self, campaign: str, state: dict[str, Any], bar: Any, previous: Any, limit: int
    ) -> list[Any]:
        low = float(min(bar.low, previous.close) / Decimal("1.01"))
        high = float(max(bar.high, previous.close) * Decimal("1.01"))
        pending = state["pending"]
        phase = pending.get("level_phase", 0)
        after = pending.get("level_after", 0)
        key = pending.get("level_key", -1)
        clause = "campaign=? AND symbol=? AND timeframe=? AND segment=? "
        args: list[Any] = [campaign, state["symbol"], state["timeframe"], state["segment"]]
        # Each cursor follows its index order. Overlapping sets are visited once
        # per bar, and an expired breakout never causes a historical full scan.
        if phase == 0:
            clause += "AND price BETWEEN ? AND ? AND (price,seq)>(?,?) "
            args.extend((low, high, key, after))
            order = "price,seq"
        elif phase == 1:
            clause += "AND in_visit=1 AND price NOT BETWEEN ? AND ? AND seq>? "
            args.extend((low, high, after))
            order = "seq"
        else:
            clause += (
                "AND breakout_until>=? AND price NOT BETWEEN ? AND ? "
                "AND (breakout_until,seq)>(?,?) "
            )
            args.extend((bar.open_ms, low, high, key, after))
            order = "breakout_until,seq"
        clause += "AND (processed_ms IS NULL OR processed_ms!=?)"
        args.extend((bar.open_ms, limit + 1))
        return self.registry.db.execute(
            f"SELECT seq,state,price,breakout_until FROM pattern_levels WHERE {clause} "
            f"ORDER BY {order} LIMIT ?",
            args,
        ).fetchall()

    def _work(self, campaign: str, state: dict[str, Any]) -> bool:
        work_deadline = time.perf_counter() + WORK_SECONDS
        with self.registry.transaction(), localcontext(Context(prec=38, rounding=ROUND_HALF_EVEN)):
            self._admission()
            current = self._campaign()
            if not current or current["id"] != campaign or not current["enabled"]:
                return False
            saved_state = self.registry.db.execute(
                "SELECT body FROM pattern_progress WHERE campaign=? AND symbol=? AND timeframe=?",
                (campaign, state["symbol"], state["timeframe"]),
            ).fetchone()
            if saved_state is None or json.loads(saved_state[0]) != state:
                return False
            step = INTERVALS[state["timeframe"]] * 1000
            pending = state["pending"]
            symbol, frame = state["symbol"], state["timeframe"]
            level_budget = LEVEL_WORK
            for _ in range(BAR_WORK):
                if level_budget == 0 or time.perf_counter() >= work_deadline:
                    self._save(campaign, state)
                    return True
                if not self._allowed():
                    self.reason = "Protected research admission closed; exact pending work retained"
                    self._save(campaign, state)
                    return False
                if pending["index"] >= pending["count"]:
                    consumed = (pending["end_ms"] - state["cursor_ms"]) // step
                    state["missing_bars"] += consumed - pending["count"]
                    state["observed_bars"] += pending["count"]
                    state["pages"] += 1
                    state.update(
                        cursor_ms=pending["end_ms"],
                        status="monitoring"
                        if pending["end_ms"] >= state["cutoff_ms"]
                        else "preparing",
                        error=None,
                        retry_at=0,
                        attempts_at_cursor=0,
                    )
                    state["coverage_state"] = (
                        "observed_with_missing_intervals"
                        if state["missing_bars"]
                        else "observed_contiguous_requested_slices"
                    )
                    del state["pending"]
                    self.registry.db.execute(
                        "DELETE FROM pattern_inputs WHERE campaign=? AND symbol=? AND timeframe=?",
                        (campaign, symbol, frame),
                    )
                    self._save(campaign, state)
                    return True
                saved_input = self.registry.db.execute(
                    "SELECT row,row_sha256 FROM pattern_inputs WHERE campaign=? AND "
                    "symbol=? AND timeframe=? AND ordinal=?",
                    (campaign, symbol, frame, pending["index"]),
                ).fetchone()
                row = json.loads(saved_input[0])
                if digest(row) != saved_input[1]:
                    raise ValueError("Staged native source identity differs; no cursor advancement")
                bar = native_bar(row, step)
                buffer = state["buffer"]
                previous = native_bar(buffer[-1], step) if buffer else None
                if not pending["bar_started"]:
                    if previous and bar.open_ms != previous.open_ms + step:
                        state["gap_count"] += 1
                        state["segment"] += 1
                        buffer.clear()
                        state["buffer_refs"].clear()
                        previous = None
                    pending["source_sha256"] = digest(
                        {"previous": state["source_sha256"], "row": row}
                    )
                    pending["bar_started"] = True
                    pending.update(level_phase=0, level_key=-1, level_after=0)
                ratio = _volume_ratio(
                    bar, deque((native_bar(r, step).volume for r in buffer[-20:]), maxlen=20)
                )
                while previous and pending["level_phase"] < 3:
                    if level_budget == 0 or time.perf_counter() >= work_deadline:
                        self._save(campaign, state)
                        return True
                    matches = (
                        self._matches(campaign, state, bar, previous, level_budget)
                        if previous
                        else []
                    )
                    applied = matches[:level_budget]
                    for saved in applied:
                        if time.perf_counter() >= work_deadline:
                            self._save(campaign, state)
                            return True
                        if not self._allowed():
                            self.reason = (
                                "Protected admission closed; remaining level cursor retained"
                            )
                            self._save(campaign, state)
                            return False
                        zone = zone_from(json.loads(saved["state"]))
                        found = (
                            _visit(zone, bar, previous, ratio, step)
                            if zone.confirmed_at_ms < bar.open_ms
                            else []
                        )
                        until = (
                            zone.breakout_ms + 10 * step if zone.breakout_ms is not None else None
                        )
                        self.registry.db.execute(
                            "UPDATE pattern_levels SET "
                            "state=?,in_visit=?,breakout_until=?,processed_ms=? WHERE seq=?",
                            (
                                encoded(zone_body(zone)),
                                int(zone.in_visit),
                                until,
                                bar.open_ms,
                                saved["seq"],
                            ),
                        )
                        pending["level_after"] = saved["seq"]
                        pending["level_key"] = (
                            saved["price"]
                            if pending["level_phase"] == 0
                            else saved["breakout_until"]
                            if pending["level_phase"] == 2
                            else -1
                        )
                        for event in found:
                            historical = state["status"] != "monitoring"
                            event.update(
                                symbol=symbol,
                                timeframe=frame,
                                source_sha256=pending["source_sha256"],
                                observed_at=pending["observed_at"],
                                bar_close_ms=bar.close_ms,
                                historical=historical,
                                financial_authority=False,
                                source_references=list(
                                    dict.fromkeys(
                                        ref
                                        for refs in [
                                            *state["buffer_refs"][-20:],
                                            pending["references"],
                                        ]
                                        for ref in refs
                                    )
                                ),
                                input_window_sha256=digest([*buffer[-20:], row]),
                            )
                            if not historical:
                                event["evaluation"] = self._evaluate(
                                    symbol, frame, [*buffer, row], event, time.time()
                                )
                            self.registry.db.execute(
                                "INSERT OR IGNORE INTO "
                                "pattern_events(campaign,symbol,timeframe,identity,kind,body) "
                                "VALUES(?,?,?,?,?,?)",
                                (
                                    campaign,
                                    symbol,
                                    frame,
                                    event["id"],
                                    "patterns" if historical else "alerts",
                                    encoded(event),
                                ),
                            )
                    incomplete = len(matches) > level_budget
                    level_budget -= len(applied)
                    if incomplete:
                        self._save(campaign, state)
                        return True
                    pending.update(
                        level_phase=pending["level_phase"] + 1, level_key=-1, level_after=0
                    )
                buffer.append(row)
                state["buffer_refs"].append(pending["references"])
                del buffer[:-100]
                del state["buffer_refs"][:-100]
                if len(buffer) >= 5:
                    recent = [native_bar(r, step) for r in buffer[-5:]]
                    pivot, confirmation = recent[2], recent[4]
                    others = recent[:2] + recent[3:]
                    for kind, price, qualifies in (
                        ("support", pivot.low, all(pivot.low < b.low for b in others)),
                        ("resistance", pivot.high, all(pivot.high > b.high for b in others)),
                    ):
                        if not qualifies:
                            continue
                        zone = _Zone(
                            f"{kind}:{pivot.open_ms}",
                            kind,
                            price,
                            price * (1 - ZONE_HALF_WIDTH),
                            price * (1 + ZONE_HALF_WIDTH),
                            confirmation.close_ms,
                            pivot.open_ms,
                            in_visit=confirmation.low <= price * (1 + ZONE_HALF_WIDTH)
                            and confirmation.high >= price * (1 - ZONE_HALF_WIDTH),
                        )
                        body = {
                            "id": zone.id,
                            "kind": kind,
                            "price": str(price),
                            "low": str(zone.low),
                            "high": str(zone.high),
                            "pivot_open_ms": pivot.open_ms,
                            "confirmed_at_ms": confirmation.close_ms,
                            "first_usable_ms": confirmation.close_ms + 1,
                            "source_sha256": pending["source_sha256"],
                            "source_references": list(
                                dict.fromkeys(
                                    ref for refs in state["buffer_refs"][-5:] for ref in refs
                                )
                            ),
                            "input_window_sha256": digest(buffer[-5:]),
                            "observed_at": pending["observed_at"],
                            "segment": state["segment"],
                            "historical": state["status"] != "monitoring",
                            "financial_authority": False,
                            "validation": (
                                "Strict native2-left/2-right pivot only; no outcome or edge proof"
                            ),
                        }
                        self.registry.db.execute(
                            "INSERT OR IGNORE INTO pattern_levels(campaign,symbol,timeframe,"
                            "identity,price,kind,body,state,in_visit,breakout_until,segment) "
                            "VALUES(?,?,?,?,?,?,?,?,?,NULL,?)",
                            (
                                campaign,
                                symbol,
                                frame,
                                zone.id,
                                float(price),
                                kind,
                                encoded(body),
                                encoded(zone_body(zone)),
                                int(zone.in_visit),
                                state["segment"],
                            ),
                        )
                state["source_sha256"] = pending["source_sha256"]
                state["latest_close_ms"] = bar.close_ms
                pending.update(index=pending["index"] + 1, level_after=0, bar_started=False)
            self._save(campaign, state)
            return True

    async def step(self) -> bool:
        if self._busy:
            return False
        self._busy = True
        try:
            with self.registry.lock:
                current = self._campaign()
                if not current or not current["enabled"]:
                    return False
                campaign = current["id"]
                now = time.time()
                scope = (campaign, now)
                chosen = self.registry.db.execute(
                    "SELECT body FROM pattern_progress WHERE campaign=? AND retry_at<=? "
                    "AND pending=1 AND status='monitoring' ORDER BY cursor_ms LIMIT 1",
                    scope,
                ).fetchone()
                if chosen is None:
                    chosen = self.registry.db.execute(
                        "SELECT body FROM pattern_progress WHERE campaign=? AND "
                        "retry_at<=? AND status='monitoring' AND pending=0 "
                        "AND cursor_ms < CAST(? / (CASE timeframe WHEN '5m' THEN 300000 "
                        "WHEN '15m' THEN 900000 "
                        "WHEN '30m' THEN 1800000 WHEN '1h' THEN 3600000 ELSE 14400000 "
                        "END) AS INTEGER)*"
                        "(CASE timeframe WHEN '5m' THEN 300000 WHEN '15m' THEN 900000 "
                        "WHEN '30m' THEN 1800000 "
                        "WHEN '1h' THEN 3600000 ELSE 14400000 END) ORDER BY cursor_ms LIMIT 1",
                        (*scope, now * 1000),
                    ).fetchone()
                if chosen is None:
                    chosen = self.registry.db.execute(
                        "SELECT body FROM pattern_progress WHERE campaign=? AND retry_at<=? "
                        "AND pending=1 ORDER BY cursor_ms LIMIT 1",
                        scope,
                    ).fetchone()
                if chosen is None:
                    chosen = self.registry.db.execute(
                        "SELECT body FROM pattern_progress WHERE campaign=? AND "
                        "retry_at<=? AND status IN ('queued','preparing') AND "
                        "cursor_ms<cutoff_ms ORDER BY cursor_ms,symbol,timeframe LIMIT 1",
                        scope,
                    ).fetchone()
                state = json.loads(chosen[0]) if chosen else None
            if state is None:
                self.reason = None
                return False
            if self.plan is None or not self._allowed():
                self.reason = "Preparation yielding to protected research/storage inputs"
                return False
            try:
                with self.registry.lock:
                    self._admission()
            except OSError as exc:
                self.reason = str(exc)
                return False
            if "pending" in state:
                return bool(await self._owned(self._work, campaign, state))
            frame, symbol = state["timeframe"], state["symbol"]
            interval = INTERVALS[frame] * 1000
            target = (
                state["cutoff_ms"]
                if state["cursor_ms"] < state["cutoff_ms"]
                else int(now * 1000) // interval * interval
            )
            end = min(target, state["cursor_ms"] + PAGE_ROWS * interval)
            try:
                with self.registry.transaction():
                    saved = json.loads(
                        self.registry.db.execute(
                            "SELECT body FROM pattern_progress WHERE campaign=? AND symbol=? "
                            "AND timeframe=?",
                            (campaign, symbol, frame),
                        ).fetchone()[0]
                    )
                    if saved != state:
                        return False
                    state["request_attempts"] += 1
                    state["attempts_at_cursor"] += 1
                    self._save(campaign, state)
                async with asyncio.timeout(12):
                    raw = await self.venue.historical_candles(
                        symbol,
                        frame,
                        state["cursor_ms"],
                        end - 1,
                        (end - state["cursor_ms"]) // interval,
                    )
                if not isinstance(raw, list) or len(raw) > PAGE_ROWS:
                    raise ValueError("Native history page exceeds declared bound")
                previous = state["cursor_ms"] - interval
                for row in raw:
                    bar = native_bar(row, interval)
                    if not state["cursor_ms"] <= bar.open_ms < end or bar.open_ms <= previous:
                        raise ValueError("Native page duplicated,unordered or outside exact scope")
                    if bar.close_ms >= time.time() * 1000:
                        raise ValueError("Forming or future native candle cannot enter a year map")
                    previous = bar.open_ms
                if not self._allowed():
                    raise ValueError("Protected admission closed after source read")
                refs = await self._owned(self._retain, campaign, state, raw, end, time.time())
                await self._owned(self._stage, campaign, state, raw, refs, end, time.time())
                self.reason = None
                return True
            except (FeedError, TimeoutError, ValueError, OSError, LookupError) as exc:
                self.reason = str(exc)[:240]
                with self.registry.transaction():
                    saved = json.loads(
                        self.registry.db.execute(
                            "SELECT body FROM pattern_progress WHERE campaign=? AND symbol=? "
                            "AND timeframe=?",
                            (campaign, symbol, frame),
                        ).fetchone()[0]
                    )
                    saved.update(
                        error=self.reason,
                        retry_at=time.time() + max(30, getattr(exc, "retry_after", 0)),
                    )
                    if saved["attempts_at_cursor"] >= PAGE_ATTEMPTS:
                        saved["status"] = "source_blocked"
                    self._save(campaign, saved)
                return False
        finally:
            self._busy = False

    def _retain(
        self, campaign: str, state: dict[str, Any], raw: list[list[Any]], end: int, now: float
    ) -> list[str]:
        if self.plan is None:
            raise ValueError("Existing research storage is unavailable")
        if self.storage_owner is None:
            raise ValueError(
                "Existing recording storage owner is unavailable; no recovery fallback"
            )

        references = []
        with self.storage_owner(self.plan) as store:
            for start in range(0, max(1, len(raw)), 500):
                packet = {
                    "kind": "native_year_pattern_inputs",
                    "version": VERSION,
                    "at": now,
                    "campaign_id": campaign,
                    "symbol": state["symbol"],
                    "timeframe": state["timeframe"],
                    "requested_start_ms": state["cursor_ms"],
                    "requested_end_ms": end - 1,
                    "offset": start,
                    "rows": raw[start : start + 500],
                }
                reference = store.append([packet], now)[0]
                if reopen_evidence(self.plan, reference) != packet:
                    raise ValueError("Native source retention verification failed")
                store.protect(
                    reference, now + self.plan.temporary_retention_seconds, "Native year map source"
                )
                references.append(reference)
            return references
