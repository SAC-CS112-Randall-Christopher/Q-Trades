"""Low-cost discovery and a bounded promotion/demotion policy, independent of orders."""

from decimal import Decimal
from typing import Any

from trading.market import decimal_string, parse_instruments
from trading.paper_engine import SYMBOLS, filters

POLICY = "usd-liquidity-ladder-v1"
STABLE_BASES = {"USD", "USDT", "USDC", "DAI", "TUSD", "BUSD", "USDP", "FDUSD", "USD1"}


class Universe:
    def __init__(self) -> None:
        self.instruments: dict[str, dict[str, Any]] = {}
        self.rows: list[dict[str, Any]] = []
        self.selected: list[str] = []
        self.entered_at: dict[str, float] = {}
        self.streaks: dict[str, int] = {}
        self.scanned_at = 0.0
        self.metadata_at = 0.0

    def metadata(self, raw: dict[str, Any], now: float) -> None:
        rows = raw.get("symbols")
        if not isinstance(rows, list) or len(rows) > 2000:
            raise ValueError("Invalid or oversized market universe")
        symbols = [
            r["symbol"]
            for r in rows
            if r.get("quoteAsset") == "USD"
            and r.get("baseAsset") not in STABLE_BASES
            and r.get("status") == "TRADING"
            and r.get("isSpotTradingAllowed") is True
        ]
        self.instruments = parse_instruments(raw, symbols)
        self.metadata_at = now

    def screen(self, raw: list[dict[str, Any]], now: float, held: set[str]) -> None:
        if len(raw) > 2000:
            raise ValueError("Oversized ticker universe")
        seen = set()
        rows = []
        for tick in raw:
            symbol = tick.get("symbol")
            if symbol not in self.instruments:
                continue
            if symbol in seen:
                raise ValueError("Duplicate ticker identity")
            seen.add(symbol)
            try:
                filters(self.instruments[symbol])
                bid, ask = decimal_string(tick["bidPrice"]), decimal_string(tick["askPrice"])
                volume = decimal_string(tick["quoteVolume"], positive=False)
                low, high = decimal_string(tick["lowPrice"]), decimal_string(tick["highPrice"])
                change = Decimal(tick["priceChangePercent"])
                if not change.is_finite() or abs(change) > 100000 or ask < bid or high < low:
                    raise ValueError("Invalid ticker range")
                spread = (ask - bid) / ((ask + bid) / 2) * 10000
                count, close = tick["count"], tick["closeTime"]
                if type(count) is not int or type(close) is not int:
                    raise ValueError("Invalid ticker time or activity")
                reason = "Qualified for closer observation"
                eligible = True
                if not -5000 <= now * 1000 - close <= 120000:
                    eligible, reason = False, "Ticker stale"
                elif spread > 25:
                    eligible, reason = False, "Spread exceeds 25 bps"
                elif volume < 100000 or count < 300:
                    eligible, reason = False, "Insufficient observed USD trading activity"
                elif now - self.metadata_at > 900:
                    eligible, reason = False, "Instrument metadata stale"
                self.streaks[symbol] = self.streaks.get(symbol, 0) + 1 if eligible else 0
                rows.append(
                    {
                        "symbol": symbol,
                        "eligible": eligible,
                        "reason": reason,
                        "quote_volume": str(volume),
                        "trades": count,
                        "spread_bps": str(spread),
                        "change_percent": str(change),
                        "range_percent": str((high / low - 1) * 100),
                        "confirmed": self.streaks[symbol] >= 2,
                    }
                )
            except (ValueError, KeyError, ArithmeticError):
                self.streaks[symbol] = 0
                rows.append(
                    {
                        "symbol": symbol,
                        "eligible": False,
                        "confirmed": False,
                        "reason": "Invalid ticker or market filters",
                    }
                )
        for symbol in set(self.streaks) - seen:
            self.streaks[symbol] = 0
        eligible_symbols = {r["symbol"] for r in rows if r["eligible"] and r["confirmed"]}
        # Held/pending assets cannot disappear from the fast feed after losing eligibility.
        selected = sorted(held - set(SYMBOLS))
        if len(selected) > 6:
            raise ValueError("Held market count exceeds the explicit subscription capacity")
        for symbol in self.selected:
            if (
                symbol in eligible_symbols
                and symbol not in selected
                and now - self.entered_at.get(symbol, now - 300) < 300
            ):
                selected.append(symbol)
        ranked = sorted(
            (r for r in rows if r["symbol"] in eligible_symbols),
            key=lambda r: (abs(Decimal(r["change_percent"])), Decimal(r["quote_volume"])),
            reverse=True,
        )
        for row in ranked:
            symbol = row["symbol"]
            if len(selected) >= max(4, len(held - set(SYMBOLS))):
                break
            if symbol not in selected and symbol not in SYMBOLS:
                selected.append(symbol)
                self.entered_at[symbol] = now
        self.selected = selected[:6]
        self.rows, self.scanned_at = rows, now

    def plan(self, study: dict[str, Any], held: set[str], *, constrained: bool) -> dict[str, int]:
        # BTC/ETH remain the comparison baseline. Four extra subscriptions at most normally.
        plan = dict.fromkeys(SYMBOLS, 100)
        fast_candidates = 0
        for symbol in self.selected:
            if symbol in held:
                plan[symbol] = 100
            elif not constrained:
                qualifies = any(f.get("eligible") for f in study.get(symbol, {}).values())
                interval = 100 if qualifies and fast_candidates < 2 else 1000
                fast_candidates += int(interval == 100)
                plan[symbol] = interval
        for symbol in held:
            plan[symbol] = 100
        return plan

    def snapshot(self) -> dict[str, Any]:
        return {
            "policy": POLICY,
            "scan_seconds": 60,
            "scanned_at": self.scanned_at,
            "markets_scanned": len(self.rows),
            "selected": self.selected,
            "rows": self.rows,
            "candidate_limit": 4,
            "fast_candidate_limit": 2,
        }
