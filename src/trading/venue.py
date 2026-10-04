"""Allowlisted public GET endpoints. No credentials, signing, or order endpoint."""

import asyncio
import json
import math
import time
import uuid
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, cast

import httpx

BASE_URL = "https://api.binance.us"


class FeedError(Exception):
    def __init__(self, reason: str, retry_after: float = 0):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


def retry_delay(value: str | None, fallback: float) -> float:
    try:
        delay = float(value or "")
        if math.isfinite(delay) and delay >= 0:
            return max(fallback, delay)
    except ValueError:
        pass
    try:
        stamp = parsedate_to_datetime(value or "")
        return max(fallback, (stamp - datetime.now(UTC)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return fallback


class PublicVenue:
    def __init__(self, timeout: int = 8, transport: httpx.AsyncBaseTransport | None = None):
        self.weight_per_minute = 1800.0
        self._tokens = 100.0
        self._token_at = time.monotonic()
        self._budget_lock = asyncio.Lock()
        self._cooldown_until = 0.0
        self._request_epoch = str(uuid.uuid4())
        self._request_started = time.time()
        self._requests: dict[str, dict[str, int]] = {}
        self.client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            headers={"User-Agent": "TradingResearch/0.1 public-monitor"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    def request_counts(self) -> dict[str, Any]:
        """Restart-scoped observations, never a reconstruction of old receipts."""
        return {
            "epoch": self._request_epoch,
            "started_at": self._request_started,
            "observed_at": time.time(),
            "scope": "This PublicVenue instance; at most 64 endpoint/market keys plus overflow",
            "basis": "Sent means local transport dispatch; remote receipt remains unknown",
            "rows": {key: dict(row) for key, row in self._requests.items()},
        }

    def _request_row(self, path: str, params: dict[str, str | int]) -> dict[str, int]:
        symbol = str(params.get("symbol", "all"))
        if not symbol.isascii() or not symbol.isalnum() or len(symbol) > 20:
            symbol = "other"
        key = f"{path}:{symbol}"
        if key not in self._requests and len(self._requests) >= 64:
            key = "overflow"
        return self._requests.setdefault(
            key,
            dict.fromkeys(
                (
                    "requested",
                    "sent",
                    "responses",
                    "completed",
                    "http_error",
                    "rate_limited",
                    "transport_error",
                    "invalid_payload",
                    "cancelled_before_send",
                    "cancelled_after_send_unknown",
                ),
                0,
            ),
        )

    async def _pace(self, weight: int) -> None:
        while True:
            async with self._budget_lock:
                now = time.monotonic()
                rate = self.weight_per_minute / 60
                self._tokens = min(100.0, self._tokens + (now - self._token_at) * rate)
                self._token_at = now
                delay = max(0, self._cooldown_until - now, (weight - self._tokens) / rate)
                if delay <= 0:
                    self._tokens -= weight
                    return
            await asyncio.sleep(delay)

    async def _get(self, path: str, params: dict[str, str | int]) -> Any:
        if path not in (
            "/api/v3/exchangeInfo",
            "/api/v3/depth",
            "/api/v3/klines",
            "/api/v3/time",
            "/api/v3/ticker/24hr",
        ):
            raise ValueError("Only public market endpoints are supported")
        weight = {"/api/v3/exchangeInfo": 20, "/api/v3/ticker/24hr": 40, "/api/v3/klines": 2}.get(
            path, 1
        )
        if path == "/api/v3/depth":
            limit = int(params.get("limit", 100))
            weight = 5 if limit <= 100 else (25 if limit <= 500 else 50)
        counts = self._request_row(path, params)
        counts["requested"] += 1
        sent = False
        try:
            await self._pace(weight)
            sent = True
            counts["sent"] += 1
            async with self.client.stream("GET", BASE_URL + path, params=params) as response:
                counts["responses"] += 1
                if response.status_code in (418, 429):
                    counts["rate_limited"] += 1
                    counts["http_error"] += 1
                    fallback = 300.0 if response.status_code == 418 else 60.0
                    cooldown = retry_delay(response.headers.get("Retry-After"), fallback)
                    self._cooldown_until = time.monotonic() + cooldown
                    raise FeedError(
                        "Venue rate limit; public requests are cooling down",
                        cooldown,
                    )
                if response.status_code != 200:
                    counts["http_error"] += 1
                    raise FeedError(f"Public endpoint returned HTTP {response.status_code}")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    cap = 2_000_000 if path == "/api/v3/exchangeInfo" else 512_000
                    if len(body) > cap:
                        counts["invalid_payload"] += 1
                        raise FeedError("Public response exceeded the capture size limit")
                payload = json.loads(body)
                list_response = path in ("/api/v3/klines", "/api/v3/ticker/24hr")
                if not isinstance(payload, list if list_response else dict):
                    counts["invalid_payload"] += 1
                    raise FeedError("Unexpected public response format")
                counts["completed"] += 1
                return payload
        except asyncio.CancelledError:
            counts["cancelled_after_send_unknown" if sent else "cancelled_before_send"] += 1
            raise
        except httpx.HTTPError as exc:
            counts["transport_error"] += 1
            raise FeedError("Public feed connection failed; observations may be stale") from exc
        except (ValueError, UnicodeError) as exc:
            counts["invalid_payload"] += 1
            raise FeedError("Public feed returned invalid JSON") from exc

    async def instruments(self, symbols: list[str]) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._get(
                "/api/v3/exchangeInfo", {"symbols": json.dumps(symbols, separators=(",", ":"))}
            ),
        )

    async def depth(self, symbol: str, limit: int) -> dict[str, Any]:
        return cast(
            dict[str, Any], await self._get("/api/v3/depth", {"symbol": symbol, "limit": limit})
        )

    async def server_time(self) -> dict[str, Any]:
        return cast(dict[str, Any], await self._get("/api/v3/time", {}))

    async def universe(self) -> dict[str, Any]:
        return cast(dict[str, Any], await self._get("/api/v3/exchangeInfo", {}))

    async def tickers(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._get("/api/v3/ticker/24hr", {}))

    async def candles(self, symbol: str, limit: int = 600) -> list[list[Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid public candle limit")
        return cast(
            list[list[Any]],
            await self._get("/api/v3/klines", {"symbol": symbol, "interval": "1m", "limit": limit}),
        )
