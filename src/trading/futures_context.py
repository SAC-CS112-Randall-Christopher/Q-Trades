"""Read-only futures observations. No account, signing, execution or financial authority."""

import asyncio
import hashlib
import json
import re
import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from trading.venue import FeedError, retry_delay

VERSION = "kraken-futures-context-v1"
ORIGIN = "https://futures.kraken.com/derivatives/api/v3"
POLL_SECONDS = 60
STALE_SECONDS = 150
MAX_MARKETS = 8


def number(value: Any, *, positive: bool = False, nonnegative: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise ValueError("Invalid numeric field")
    result = Decimal(str(value))
    if not result.is_finite() or (positive and result <= 0) or (nonnegative and result < 0):
        raise ValueError("Invalid numeric field")
    return result


def timestamp(value: Any) -> float:
    if not isinstance(value, str):
        raise ValueError("Missing exchange timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Exchange timestamp lacks timezone")
    return parsed.timestamp()


def canonical_base(value: str) -> str:
    return "BTC" if value == "XBT" else value


class FuturesPublicData:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.client = httpx.AsyncClient(
            timeout=5,
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            headers={"User-Agent": "TradingResearch/0.1 read-only-futures-context"},
        )
        self.cooldown_until = 0.0

    async def close(self) -> None:
        await self.client.aclose()

    async def get(self, path: str) -> dict[str, Any]:
        if path != "/instruments" and not re.fullmatch(r"/tickers/PF_[A-Z0-9]+USD", path):
            raise ValueError("Only public futures metadata and perpetual tickers are allowed")
        if time.monotonic() < self.cooldown_until:
            raise FeedError("Futures context rate-limit cooldown")
        sent, started = time.time(), time.monotonic()
        try:
            async with self.client.stream("GET", ORIGIN + path) as response:
                if response.status_code == 429:
                    delay = retry_delay(response.headers.get("Retry-After"), 60)
                    self.cooldown_until = time.monotonic() + delay
                    raise FeedError("Futures context rate limit", delay)
                if response.status_code != 200:
                    raise FeedError(f"Futures public endpoint HTTP {response.status_code}")
                body = bytearray()
                cap = 2_000_000 if path == "/instruments" else 65_536
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > cap:
                        raise FeedError("Futures public response exceeded size limit")
        except httpx.HTTPError as exc:
            raise FeedError("Futures public feed unavailable: " + type(exc).__name__) from None
        received, ended = time.time(), time.monotonic()
        if ended - started > 5 or abs(received - sent - (ended - started)) > 0.25:
            raise FeedError("Futures response too slow or local clock changed")
        # Preserve the wire body; decimal-valued JSON numbers do not pass through binary floats.
        wire = body.decode("utf-8")
        payload = json.loads(wire, parse_float=str)
        if not isinstance(payload, dict) or payload.get("result") != "success":
            raise FeedError("Futures public endpoint did not return success")
        server_at = timestamp(payload.get("serverTime"))
        if not -5 <= received - server_at <= 15:
            raise FeedError("Futures response timestamp is stale or clock offset is excessive")
        return {
            "path": path,
            "sent_at": sent,
            "received_at": received,
            "received_mono": ended,
            "server_at": server_at,
            "round_trip_ms": (ended - started) * 1000,
            "sha256": hashlib.sha256(body).hexdigest(),
            "wire": wire,
            "raw": payload,
        }


class FuturesContext:
    """Bounded descriptive context, independent of spot signals and order permissions."""

    def __init__(self, previous: dict[str, Any] | None = None):
        self.previous = dict((previous or {}).get("markets", {}))
        self.latest: dict[str, Any] = {}
        self.markets: dict[str, dict[str, Any]] = {}
        self.metadata: list[dict[str, Any]] = []
        self.metadata_at = 0.0
        self.metadata_mono = 0.0
        self.metadata_hash: str | None = None
        self.metadata_wire: str | None = None
        self.last_failure: str | None = None

    def resolve(self, base: str) -> dict[str, Any]:
        candidates = [
            row
            for row in self.metadata
            if canonical_base(str(row.get("base"))) == base
            and row.get("quote") == "USD"
            and row.get("type") == "flexible_futures"
            and re.fullmatch(r"PF_[A-Z0-9]+USD", str(row.get("symbol", "")))
            and row.get("tradeable") is True
            and row.get("isExpired") is False
            and row.get("tradfi") is False
            and number(row.get("contractSize"), positive=True) == 1
        ]
        if len(candidates) != 1:
            raise ValueError("No unique supported linear USD perpetual contract")
        return candidates[0]

    def accept(
        self, spot_symbol: str, base: str, instrument: dict[str, Any], receipt: dict[str, Any]
    ) -> dict[str, Any]:
        raw = receipt["raw"].get("ticker")
        if not isinstance(raw, dict):
            raise ValueError("Missing futures ticker")
        symbol = instrument["symbol"]
        if (
            str(raw.get("symbol", "")).upper() != symbol
            or raw.get("tag") != "perpetual"
            or canonical_base(str(raw.get("pair", "")).split(":")[0]) != base
            or not str(raw.get("pair", "")).endswith(":USD")
            or raw.get("suspended") is not False
        ):
            raise ValueError("Futures contract identity/status mismatch")
        mark = number(raw.get("markPrice"), positive=True)
        index = number(raw.get("indexPrice"), positive=True)
        oi = number(raw.get("openInterest"), nonnegative=True)
        funding = number(raw.get("fundingRate"))
        predicted = number(raw.get("fundingRatePrediction"))
        row: dict[str, Any] = {
            "status": "observed",
            "spot_symbol": spot_symbol,
            "contract": symbol,
            "base": base,
            "observed_at": receipt["received_at"],
            "server_at": receipt["server_at"],
            "round_trip_ms": round(receipt["round_trip_ms"], 2),
            "mark_price": str(mark),
            "index_price": str(index),
            "premium_bps": str((mark / index - 1) * 10000),
            "open_interest_base": str(oi),
            "open_interest_change_pct": None,
            "change_interval_seconds": None,
            "funding_usd_per_base_hour": str(funding),
            "predicted_funding_usd_per_base_hour": str(predicted),
            # Approximate ratio to today's index, NOT the official rate-setting index.
            "funding_est_bps_hour": str(funding / index * 10000),
            "funding_direction": "longs pay"
            if funding > 0
            else "shorts pay"
            if funding < 0
            else "zero",
            "last_trade_at": raw.get("lastTime"),
            "raw_sha256": receipt["sha256"],
            "metadata_sha256": self.metadata_hash,
            "instrument": {
                key: instrument.get(key)
                for key in (
                    "symbol",
                    "base",
                    "quote",
                    "type",
                    "contractSize",
                    "tradeable",
                    "isExpired",
                    "tradfi",
                )
            },
        }
        previous = self.previous.get(spot_symbol, {})
        interval = receipt["server_at"] - previous.get("server_at", 0)
        if previous.get("contract") == symbol and 30 <= interval <= 180:
            old_oi = number(previous["open_interest_base"], nonnegative=True)
            row["change_interval_seconds"] = round(interval, 2)
            if old_oi:
                row["open_interest_change_pct"] = str((oi / old_oi - 1) * 100)
        self.previous[spot_symbol] = row
        return row

    async def collect(self, client: FuturesPublicData, targets: dict[str, str]) -> dict[str, Any]:
        if len(targets) > MAX_MARKETS or any(
            not re.fullmatch(r"[A-Z0-9]+USD", symbol) or not re.fullmatch(r"[A-Z0-9]+", base)
            for symbol, base in targets.items()
        ):
            raise ValueError("Futures context target limit/identity invalid")
        self.last_failure = None
        self.metadata_wire = None
        self.previous = {s: row for s, row in self.previous.items() if s in targets}
        capture_id = uuid.uuid4().hex
        observed: dict[str, dict[str, Any]] = {}
        receipts: list[dict[str, Any]] = []
        try:
            if time.monotonic() - self.metadata_mono >= 3600 or not self.metadata:
                metadata = await client.get("/instruments")
                rows = metadata["raw"].get("instruments")
                if (
                    not isinstance(rows, list)
                    or len(rows) > 5000
                    or any(not isinstance(row, dict) for row in rows)
                ):
                    raise ValueError("Invalid futures instrument catalog")
                self.metadata = rows
                self.metadata_at = metadata["received_at"]
                self.metadata_mono = time.monotonic()
                self.metadata_hash = metadata["sha256"]
                self.metadata_wire = metadata["wire"]
            semaphore = asyncio.Semaphore(2)

            async def one(spot: str, base: str) -> None:
                try:
                    instrument = self.resolve(base)
                    async with semaphore:
                        receipt = await client.get("/tickers/" + instrument["symbol"])
                    receipts.append(
                        {k: v for k, v in receipt.items() if k not in ("raw", "received_mono")}
                    )
                    row = self.accept(spot, base, instrument, receipt)
                    row["capture_id"] = capture_id
                    row["received_mono"] = receipt["received_mono"]
                    observed[spot] = row
                except (ValueError, KeyError, ArithmeticError, FeedError) as exc:
                    observed[spot] = {
                        "status": "unavailable",
                        "reason": str(exc),
                        "spot_symbol": spot,
                    }

            await asyncio.gather(*(one(s, base) for s, base in targets.items()))
        except (ValueError, KeyError, ArithmeticError, FeedError) as exc:
            self.last_failure = str(exc)
            observed = {
                s: {"status": "unavailable", "reason": str(exc), "spot_symbol": s} for s in targets
            }
        self.markets = observed
        self.latest = {
            "version": VERSION,
            "source": "Kraken public linear perpetuals",
            "capture_id": capture_id,
            "observed_at": time.time(),
            "markets": {
                s: {k: v for k, v in row.items() if k != "received_mono"}
                for s, row in observed.items()
            },
        }
        return {**self.latest, "receipts": receipts, "error": self.last_failure}

    def context_for(self, symbol: str, now: float, mono: float) -> dict[str, Any]:
        row = self.markets.get(symbol, {"status": "unavailable", "reason": "Not observed"})
        result = {k: v for k, v in row.items() if k != "received_mono"}
        if row.get("status") != "observed":
            return result
        age = mono - row["received_mono"]
        if (
            not 0 <= age <= STALE_SECONDS
            or not -5 <= now - row["server_at"] <= STALE_SECONDS
            or abs((now - row["observed_at"]) - age) > 0.25
        ):
            return {
                "status": "stale",
                "capture_id": row["capture_id"],
                "reason": "Context expired or local clock changed",
            }
        result["age_seconds"] = round(age, 1)
        return result

    def snapshot(self) -> dict[str, Any]:
        now, mono = time.time(), time.monotonic()
        return {
            "enabled": True,
            "version": VERSION,
            "source": "Kraken public linear perpetuals",
            "role": "Observation and research only; no futures execution or signal changes",
            "poll_seconds": POLL_SECONDS,
            "stale_seconds": STALE_SECONDS,
            "coverage": "One venue sample; no liquidation feed, dated/CME futures or options chain",
            "error": self.last_failure,
            "markets": {s: self.context_for(s, now, mono) for s in self.markets},
        }
