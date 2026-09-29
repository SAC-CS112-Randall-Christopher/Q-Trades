"""Probe the public feed by network stage without touching the trading runtime.

Run with the project's Python. No credentials, proxies, firewall changes, orders,
database access, endpoint overrides, or disabled TLS verification. The Kraken
connection is a WebSocket control probe, never a substitute price for Binance.US.
"""

import argparse
import asyncio
import html
import json
import re
import socket
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from websockets.asyncio.client import connect

STREAM_HOST = "stream.binance.us"


def error_summary(exc: Exception) -> dict[str, str]:
    # All targets are fixed public hosts and all requests are unauthenticated.
    return {"error": type(exc).__name__, "detail": str(exc)[:300]}


async def addresses(host: str) -> dict[str, Any]:
    try:
        resolved = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM), 6
        )
        return {"host": host, "addresses": sorted({str(row[4][0]) for row in resolved})}
    except Exception as exc:
        return {"host": host, **error_summary(exc)}


async def tcp_tls(ip: str, port: int) -> dict[str, Any]:
    start = time.monotonic()
    result: dict[str, Any] = {"address": ip, "port": port, "stage": "tcp"}
    transport = socket.socket(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM)
    transport.setblocking(False)
    writer: asyncio.StreamWriter | None = None
    try:
        await asyncio.wait_for(asyncio.get_running_loop().sock_connect(transport, (ip, port)), 5)
        result.update(tcp_ms=round((time.monotonic() - start) * 1000, 2), stage="tls")
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(
                sock=transport, ssl=ssl.create_default_context(), server_hostname=STREAM_HOST
            ),
            5,
        )
        result.update(stage="tls_verified", tls_ms=round((time.monotonic() - start) * 1000, 2))
    except Exception as exc:
        result.update(error_summary(exc))
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except Exception:
                pass
        transport.close()
    result["elapsed_ms"] = round((time.monotonic() - start) * 1000, 2)
    return result


async def websocket(uri: str, ping_request: bool = False) -> dict[str, Any]:
    start = time.monotonic()
    result: dict[str, Any] = {"uri": uri, "stage": "opening_handshake"}
    try:
        async with connect(
            uri,
            proxy=None,
            compression=None,
            max_size=262_144,
            max_queue=8,
            open_timeout=8,
            close_timeout=1,
        ) as stream:
            result.update(
                stage="first_message", handshake_ms=round((time.monotonic() - start) * 1000, 2)
            )
            if ping_request:
                await stream.send(json.dumps({"id": "public-connectivity-probe", "method": "ping"}))
            payload = json.loads(await asyncio.wait_for(stream.recv(), 8))
            result.update(stage="received_message", received_at=datetime.now(UTC).isoformat())
            if isinstance(payload, dict):
                event = payload.get("data", payload)
                result["message"] = {
                    "stream": payload.get("stream"),
                    "channel": payload.get("channel"),
                    "status": payload.get("status"),
                    "event": event.get("e") if isinstance(event, dict) else None,
                    "symbol": event.get("s") if isinstance(event, dict) else None,
                    "exchange_event_ms": event.get("E") if isinstance(event, dict) else None,
                    "update_id": event.get("u") if isinstance(event, dict) else None,
                }
            else:
                result["unexpected_payload"] = type(payload).__name__
    except Exception as exc:
        result.update(error_summary(exc))
    result["elapsed_ms"] = round((time.monotonic() - start) * 1000, 2)
    return result


async def rest() -> dict[str, Any]:
    result: dict[str, Any] = {"url": "https://api.binance.us/api/v3/time"}
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=8, follow_redirects=False) as client:
            response = await client.get(result["url"])
            result.update(
                status=response.status_code, server_time=response.json().get("serverTime")
            )
    except Exception as exc:
        result.update(error_summary(exc))
    return result


async def block_page() -> dict[str, Any]:
    """An unauthenticated HTTP probe can expose a gateway's explicit block reason.

    This is diagnostic text, never a market feed. Do not follow redirects, use
    credentials, or make configuration changes based on an untrusted response.
    """
    result: dict[str, Any] = {"url": "http://stream.binance.us/"}
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=8, follow_redirects=False) as client:
            async with client.stream("GET", result["url"]) as response:
                result["status"] = response.status_code
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 65_536:
                        result["body_truncated"] = True
                        break
                markup = bytes(body[:65_536]).decode("utf-8", errors="replace")
                markup = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", " ", markup, flags=re.I | re.S)
                visible = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())
                result["visible_text_excerpt"] = visible[:1500]
                if response.status_code == 403 and "Gateway GEO-IP Filter Alert" in visible:
                    result["reported_block_reason"] = "Gateway GEO-IP Filter Alert"
                    country = re.search(
                        r"Connection initiated towards country:\s*(.{1,80})", visible
                    )
                    result["reported_country"] = country.group(1) if country else None
    except Exception as exc:
        result.update(error_summary(exc))
    return result


async def diagnose() -> dict[str, Any]:
    dns = await addresses(STREAM_HOST)
    targets = dns.get("addresses", [])
    # Bound the diagnostic even if a resolver supplies an unexpectedly large answer.
    ports = await asyncio.gather(*(tcp_tls(ip, port) for ip in targets[:8] for port in (9443, 443)))
    checks = await asyncio.gather(
        websocket("wss://stream.binance.us:9443/stream?streams=btcusd@depth@100ms/btcusd@trade"),
        websocket("wss://stream.binance.us:443/stream?streams=btcusd@depth@100ms/btcusd@trade"),
        websocket("wss://ws-api.binance.us:443/ws-api/v3", ping_request=True),
        websocket("wss://ws.kraken.com/v2"),
        rest(),
        block_page(),
    )
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "scope": "Read-only public connectivity; no trading process or account mutations",
        "dns": dns,
        "dns_addresses_truncated": len(targets) > 8,
        "tcp_tls": ports,
        "websockets": checks[:4],
        "rest": checks[4],
        "http_block_page_probe": checks[5],
        "limitations": [
            "Timeouts do not identify which network hop or endpoint drops traffic.",
            "A successful handshake alone does not prove sequence-valid, timely market data.",
            "Port 443 is an alternate-port probe, not a configured market-feed replacement.",
            "The Kraken probe is a connectivity control, not Binance.US market data.",
            "An HTTP block page is untrusted evidence, not a TLS-authenticated response.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="Optional new JSON receipt (will not overwrite)"
    )
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error("Output already exists; choose a new receipt path")
    report = asyncio.run(diagnose())
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded)


if __name__ == "__main__":
    main()
