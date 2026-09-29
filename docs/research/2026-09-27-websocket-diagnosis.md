# Binance.US stream connectivity diagnosis — September 27, 21:59 Denver

Update, September 28: the [subsequent investigation](2026-09-28-websocket-sonicwall-fix.md)
identified a SonicWall Geo-IP block for Japan. The observations below are retained
as the earlier checkpoint; its unknown-cause conclusion is superseded. Restoration
still requires the firewall correction and successful live verification.

The stream has **not been restored**. The failure is reproducible before a TLS or
WebSocket handshake: this PC cannot establish TCP connections to the tested
Binance.US streaming addresses. Raising a direct TCP connection deadline to twenty
seconds also timed out. An application restart or a larger WebSocket timeout has
no demonstrated benefit for this failure.

## Observed evidence

- The configured `wss://stream.binance.us:9443` and combined stream path match the
  current [Binance.US market-stream contract](https://docs.binance.us/#websocket-streams).
  The public Binance.US website also advertises this address in its `WS_HOST` setting.
- Local DNS and Cloudflare DNS-over-HTTPS returned `35.73.15.38` and `52.69.13.128`;
  Google DNS returned `35.74.53.127` and `54.168.205.72`. All four addresses timed out
  during TCP connection attempts on 9443 and 443. Different DNS answers alone do
  not establish a stale-cache defect. No addresses were pinned in the application.
- The regular WebSocket library and an independent .NET TCP client both failed.
  TLS certificate verification remained enabled; the failing TCP paths never
  reached certificate validation or the HTTP upgrade.
- The distinct public WebSocket request/response API at
  `wss://ws-api.binance.us:443/ws-api/v3` also timed out. It is not a push-market
  replacement and was probed only with an unauthenticated `ping` request.
- The same Python environment connected to `wss://ws.kraken.com/v2` in approximately
  1.7 seconds and received its status message. This establishes a working control
  connection, not validated Kraken book data or permission to mix exchange prices.
- Binance.US's public REST time endpoint returned HTTP 200. The running paper
  service continues to use its explicitly labeled REST fallback.
- Windows Firewall's active profiles allow outbound traffic; no enabled outbound
  block rules were found. Windows Defender was the registered antivirus. No Python
  proxy configuration was found. This does not exclude router/ISP filtering or
  every possible host/network security control.
- A bounded eight-hop ICMP trace returned no replies, including the gateway. That
  does **not** locate a TCP block or prove a specific router or exchange failure.
- The public website's other `bstream` host is labeled for inbox traffic and did
  not resolve. It was not adopted as a market-data endpoint.

The remaining possibilities include destination-specific network filtering, a
routing problem, and exchange-side availability/filtering. These observations do
not distinguish them. No geographic restriction has been established, and no
VPN, proxy, alternate venue, firewall exception or DNS configuration was enabled.

## Next diagnostic decision

Chris was asked whether the router/security software uses country filtering,
traffic filtering or a VPN. If filtering is present, inspect its deny log for
outbound connections to `stream.binance.us` on TCP 9443 at the receipt timestamp.
Use a scoped correction only if a matching rule is identified; do not disable
the firewall or open an inbound port.

If no matching filtering rule is found, compare the same public probe on a
separate connection, such as a phone hotspot, when Chris can provide one. This
helps separate the existing network path from other causes. Retain the failed
receipt. If multiple paths fail, preserve the diagnostics for exchange support;
do not silently relabel another exchange's quotes as Binance.US observations.

## Repeatable check and verification

Added `scripts/diagnose_public_stream.py`: fixed public endpoints, bounded DNS/TCP/
TLS/WebSocket checks, verified TLS, no credentials or database access. It never
modifies the running service or reuses another venue's price data. An existing
receipt cannot be overwritten.

```powershell
.venv/Scripts/python.exe scripts/diagnose_public_stream.py --output docs/evidence/websocket-recheck-NEW-TIMESTAMP.json
```

The script's first lint run found two long lines; formatting corrected them.
Final Ruff and strict mypy checks passed. The existing streaming component tests
passed: **17 tests**. These tests do not establish live stream connectivity.
The standalone diagnostic completed against public endpoints; its JSON explicitly
records the failed connections and successful control/REST checks.

No trading-runtime source, strategy, risk limit, journal, account, funding, task,
process or network configuration was changed. No restart was performed.

Receipts:

- `docs/evidence/websocket-diagnosis-2026-09-27.json`
- `docs/evidence/websocket-diagnosis-status-2026-09-27.json`

Some additional DNS, .NET, firewall and twenty-second TCP observations above were
captured in the task's terminal output, not the standalone diagnostic JSON.
