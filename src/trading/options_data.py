"""Anonymous, bounded access to explicitly offered free AAPL historical demo data."""

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from trading.options_policy import NY, SOURCE, dec
from trading.venue import FeedError, retry_delay

ORIGIN = "https://api.marketdata.app"


class FreeOptionsData:
    def __init__(
        self,
        reserve_request: Callable[[], None],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.client = httpx.AsyncClient(
            timeout=12, trust_env=False, follow_redirects=False, transport=transport
        )
        self.reserve_request = reserve_request
        self.next_request = 0.0
        self.minimum_interval = 12.0

    async def close(self) -> None:
        await self.client.aclose()

    async def get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        # No token input, environment keys, real-time endpoint or non-AAPL symbol is allowed.
        if path not in (
            "/v1/stocks/candles/D/AAPL/",
            "/v1/options/chain/AAPL/",
        ) and not re.fullmatch(r"/v1/options/quotes/AAPL\d{6}[CP]\d{8}/", path):
            raise ValueError("Only free AAPL historical research routes are allowed")
        if set(params) - {"date", "from", "to", "dte"}:
            raise ValueError("Unsupported options query parameter")
        today = datetime.now(NY).date()
        if path.startswith("/v1/options/"):
            if "date" not in params or datetime.fromisoformat(params["date"]).date() >= today:
                raise ValueError("Only completed historical dates are permitted")
        else:
            if not {"from", "to"} <= params.keys():
                raise ValueError("Historical candle interval required")
            first, last = (datetime.fromisoformat(params[k]).date() for k in ("from", "to"))
            if not first <= last < today or (last - first).days > 400:
                raise ValueError("Candle interval outside the research bound")
        await asyncio.sleep(max(0, self.next_request - time.monotonic()))
        self.reserve_request()
        sent, started = time.time(), time.monotonic()
        self.next_request = started + self.minimum_interval
        try:
            async with self.client.stream("GET", ORIGIN + path, params=params) as response:
                if response.status_code == 429:
                    self.next_request = time.monotonic() + retry_delay(
                        response.headers.get("Retry-After"), 60
                    )
                    raise FeedError("Free options source rate limit; collection backed off")
                if response.status_code not in (200, 203):
                    raise FeedError(f"Free options source HTTP {response.status_code}")
                body = bytearray()
                async for part in response.aiter_bytes():
                    body.extend(part)
                    if len(body) > 2_000_000:
                        raise FeedError("Options response exceeded the size bound")
        except httpx.HTTPError as exc:
            raise FeedError("Free options data unavailable: " + type(exc).__name__) from None
        received = time.time()
        elapsed = time.monotonic() - started
        if elapsed > 12 or abs(received - sent - elapsed) > 0.25:
            raise FeedError("Options response too slow or local clock changed")
        wire = body.decode("utf-8")
        raw = json.loads(wire, parse_float=str)
        if not isinstance(raw, dict) or raw.get("s") != "ok":
            raise FeedError("No verified historical options data for this request")
        return {
            "source": SOURCE,
            "path": path,
            "params": params,
            "sent_at": sent,
            "received_at": received,
            "round_trip_ms": round(elapsed * 1000, 2),
            "sha256": hashlib.sha256(body).hexdigest(),
            "wire": wire,
            "raw": raw,
        }

    async def sessions(self) -> tuple[list[str], dict[str, Any]]:
        last = datetime.now(NY).date() - timedelta(days=1)
        response = await self.get(
            "/v1/stocks/candles/D/AAPL/", {"from": str(last - timedelta(days=240)), "to": str(last)}
        )
        stamps = response["raw"].get("t")
        if not isinstance(stamps, list) or len(stamps) > 400:
            raise ValueError("Invalid historical session calendar")
        days = [datetime.fromtimestamp(float(dec(t)), NY).date().isoformat() for t in stamps]
        if days != sorted(set(days)) or any(day > str(last) for day in days):
            raise ValueError("Out-of-order or incomplete session calendar")
        return days[-90:], {k: v for k, v in response.items() if k != "raw"}

    @staticmethod
    def quotes(response: dict[str, Any], day: str) -> dict[str, dict[str, Any]]:
        raw = response["raw"]
        symbols = raw.get("optionSymbol")
        if (
            not isinstance(symbols, list)
            or not 0 < len(symbols) <= 1000
            or len(set(symbols)) != len(symbols)
        ):
            raise ValueError("Invalid or oversized historical option chain")
        fields = {
            "underlying": "underlying",
            "side": "side",
            "strike": "strike",
            "bid": "bid",
            "ask": "ask",
            "bid_size": "bidSize",
            "ask_size": "askSize",
            "volume": "volume",
            "open_interest": "openInterest",
            "underlying_price": "underlyingPrice",
        }
        for field in (*fields.values(), "updated", "expiration"):
            if not isinstance(raw.get(field), list) or len(raw[field]) != len(symbols):
                raise ValueError("Mismatched historical option columns")
        result = {}
        for i, symbol in enumerate(symbols):
            updated = float(dec(raw["updated"][i]))
            if datetime.fromtimestamp(updated, NY).date().isoformat() != day:
                raise ValueError("Provider returned a different historical date")
            expiry = datetime.fromtimestamp(float(dec(raw["expiration"][i])), NY).date().isoformat()
            row = {key: raw[field][i] for key, field in fields.items()}
            # Standard unadjusted AAPL roots only. No adjusted deliverables are modeled.
            row.update(
                symbol=symbol,
                day=day,
                expiration_date=expiry,
                updated_at=updated,
                multiplier="100",
                source=SOURCE,
                receipt_sha256=response["sha256"],
                greeks="Historical Greeks and IV unavailable",
            )
            result[symbol] = row
        return result

    async def session(self, day: str, held: set[str]) -> dict[str, Any]:
        if len(held) > 6:
            raise ValueError("Options observation limit exceeded")
        response = await self.get("/v1/options/chain/AAPL/", {"date": day, "dte": "14"})
        quotes = self.quotes(response, day)
        closes = {str(dec(q["underlying_price"], "0.01")) for q in quotes.values()}
        if len(closes) != 1:
            raise ValueError("Underlying reference differs within a historical chain")
        receipts = [{k: v for k, v in response.items() if k != "raw"}]
        missing = []
        for symbol in sorted(held - quotes.keys()):
            try:
                extra = await self.get(f"/v1/options/quotes/{symbol}/", {"date": day})
                observed = self.quotes(extra, day)
                if set(observed) != {symbol}:
                    raise ValueError("Historical contract lookup returned wrong instrument")
                quotes.update(observed)
                receipts.append({k: v for k, v in extra.items() if k != "raw"})
            except (FeedError, ValueError, ArithmeticError):
                missing.append(symbol)
        return {
            "source": SOURCE,
            "day": day,
            "quotes": quotes,
            "underlying_close": next(iter(closes)),
            "receipts": receipts,
            "missing_held_quotes": missing,
        }
