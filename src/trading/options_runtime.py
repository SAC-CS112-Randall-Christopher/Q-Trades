"""Independent free-data historical research worker; spot operations do not depend on it."""

import asyncio
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal as D
from typing import Any

from trading.options_data import FreeOptionsData
from trading.options_engine import OptionsEngine, reserved
from trading.options_store import OptionsStore
from trading.venue import FeedError

logger = logging.getLogger(__name__)


class OptionsRuntime:
    def __init__(self, store: OptionsStore):
        self.store = store
        self.state = store.read()
        self.running = False
        self.error: str | None = None
        self.receipt = store.reconcile()
        self.events = store.recent()
        self.last_activity = time.time()
        self.source: FreeOptionsData | None = None

    def reserve_request(self) -> None:
        def update(engine: OptionsEngine) -> None:
            budget = engine.state["request_budget"]
            today = datetime.now(UTC).date().isoformat()
            if budget["day"] != today:
                budget.update(day=today, used=0)
            if budget["used"] >= budget["limit"]:
                raise FeedError(
                    "Daily free-data request budget reached; resumes after UTC midnight"
                )
            budget["used"] += 1

        self.state = self.store.transact(time.time(), update)

    def set_paused(self, paused: bool) -> None:
        self.state = self.store.transact(time.time(), lambda e: e.set_paused(paused))
        self.receipt = self.store.reconcile()
        self.events = self.store.recent()

    async def step(self, source: FreeOptionsData) -> None:
        now = time.time()
        if now >= self.state["next_review"]:
            self.state = self.store.transact(now, lambda e: e.review())
        calendar = self.state.get("calendar", [])
        if not calendar or now - self.state.get("calendar_fetched_at", 0) >= 43200:
            days, receipt = await source.sessions()

            def calendar_update(engine: OptionsEngine) -> None:
                if engine.state["market_day"] and engine.state["market_day"] < days[0]:
                    raise ValueError(
                        "Replay cursor predates available calendar; explicit gap review required"
                    )
                engine.state["calendar"] = days
                engine.state["calendar_fetched_at"] = time.time()
                engine.emit(
                    "research_calendar",
                    "system",
                    {
                        "days": days,
                        "receipt": receipt,
                        "note": "Stock prices from this response are not strategy features",
                    },
                )

            if not days:
                raise ValueError("Historical trading calendar is empty")
            self.state = self.store.transact(time.time(), calendar_update)
            calendar = days
        remaining = [
            d for d in calendar if not self.state["market_day"] or d > self.state["market_day"]
        ]
        if not remaining:
            caught_up = "Historical replay caught up; waiting for the next completed session"
            if self.state["feed_status"] != caught_up:

                def idle(engine: OptionsEngine) -> None:
                    engine.state["feed_status"] = caught_up
                    engine.emit("research_caught_up", "system", {"day": engine.state["market_day"]})

                self.state = self.store.transact(now, idle)
                self.events = self.store.recent()
                self.receipt = self.store.reconcile()
            self.error = None
            return
        held = {
            s
            for a in self.state["accounts"].values()
            for s in set(a["positions"]) | set(a["pending"])
        }
        packet = await source.session(remaining[0], held)

        def apply(engine: OptionsEngine) -> None:
            if packet["missing_held_quotes"]:
                engine.state["data_gaps"] += 1
                engine.emit(
                    "missing_contract_quotes",
                    "system",
                    {"day": packet["day"], "symbols": packet["missing_held_quotes"]},
                )
            engine.process_session(packet)

        self.state = self.store.transact(time.time(), apply)
        self.receipt = self.store.reconcile()
        if not self.receipt["balanced"]:
            raise RuntimeError("Options journal reconciliation needs attention")
        self.events = self.store.recent()
        self.error = None

    async def run(self) -> None:
        self.running = True
        self.source = FreeOptionsData(self.reserve_request)
        try:
            while True:
                try:
                    if not self.receipt["balanced"]:
                        raise RuntimeError("Options journal reconciliation needs attention")
                    await self.step(self.source)
                except (ValueError, ArithmeticError, KeyError, FeedError) as exc:
                    reason = str(exc)
                    if reason != self.error:

                        def rejected(engine: OptionsEngine, reason: str = reason) -> None:
                            engine.state["feed_status"] = reason
                            engine.state["data_gaps"] += 1
                            engine.emit("research_data_unavailable", "system", {"reason": reason})

                        self.state = self.store.transact(time.time(), rejected)
                    self.error = reason
                except Exception:
                    # Stop this worker only. The independent spot worker keeps managing positions.
                    self.error = "Options research stopped; ledger/worker inspection required"
                    logger.exception("Options research worker stopped")
                    break
                self.last_activity = time.time()
                await asyncio.sleep(60)
        finally:
            self.running = False
            await self.source.close()

    def snapshot(self) -> dict[str, Any]:
        accounts = {}
        for name, a in self.state["accounts"].items():
            accounts[name] = {
                **a,
                "net_pnl": str(D(a["equity"]) - D(a["funding"])),
                "available_cash": str(D(a["cash"]) - reserved(a)),
                "unsettled_cash": str(sum((D(i["amount"]) for i in a["unsettled"]), D(0))),
                "risk_budget": str(D(a["equity"]) * D("0.025")),
            }
        return {
            "enabled": True,
            "running": self.running,
            "error": self.error,
            "paused": self.state["paused"],
            "mode": "Historical end-of-day replay",
            "source": "Market Data free AAPL historical demo",
            "monthly_data_cost": "0",
            "market_day": self.state["market_day"],
            "sessions": self.state["sessions"],
            "contracts_studied": self.state["contracts_studied"],
            "next_review": self.state["next_review"],
            "review_count": self.state["review_count"],
            "reviews": self.state["reviews"],
            "promotions": self.state["promotions"],
            "accounts": accounts,
            "feed_status": self.state["feed_status"],
            "last_study": self.state["last_study"],
            "rejections": self.state["rejections"],
            "data_gaps": self.state["data_gaps"],
            "request_budget": self.state["request_budget"],
            "journal": self.receipt,
            "events": self.events,
            "limitations": [
                "Historical AAPL only; no live or intraday execution evidence",
                "No historical Greeks/IV; adjusted deliverables are excluded",
                "$0.50/contract/side and 100-share multiplier are model assumptions",
                "Later-session bid/ask fills; 10% size cap; only settled cash can fund entries",
                "Unresolved expiry freezes the position; no unaffordable stock exercise",
                "Correlated replay/shadow outcomes do not establish majority live success",
            ],
        }
