# Binance.US WebSocket: SonicWall Geo-IP block

## Resolved at approximately 07:04–07:05 Denver

Chris reported adding Japan to the allowed countries. His earlier screenshot showed
All Connections mode; this was a country-wide policy change made by Chris, not a
destination exception or a firewall mutation by this agent.

The new diagnostic completed verified TLS to both resolved stream addresses on
9443 and 443 and received a real BTC `depthUpdate` over the configured 9443 stream.
The existing application reconnected automatically without a service restart.
At 07:04:48, 07:05:04 and 07:05:19, BTC/ETH were fresh, usable and sourced from
`binance.us-depth-websocket`, with advancing exchange timestamps and no per-stream
error. Accepted books advanced BTC 70→110→153 and ETH 67→132→194; BTC trades advanced
1→4→7. No ETH trade message occurred in this short window. Reconnect counters stayed
at 87 and trade gaps at zero. These are sequence-validated application publications,
not just a successful standalone handshake. At the last sample the estimated
event-age p95 was 70.91 ms BTC / 78.89 ms ETH, with 62.5 ms clock uncertainty;
this is a short observation, not a sustained latency guarantee.

Paper remained running, nonstale and error-free, with the existing eight historical
engine gaps preserved. Two SOL/HBAR REST fallback warnings remained in the status;
this does not claim every wider-universe market is healthy. The journal reconciled
at revision 81168. Primary equity was $98.8371108497, nine closed trades, no open
positions or replenishments, and $100 lifetime funding. No financial/risk state
was manually changed. HTTP port 80 still timed out; it is not the production stream.

Receipts: `websocket-japan-allowed-20260928T070409.json`,
`websocket-japan-allowed-validation-20260928T130519Z.json`, and
`websocket-japan-allowed-journal-20260928T130525Z.json` under `docs/evidence/`.
The diagnostic filename uses local time; receipt contents record UTC.

## Original diagnosis

September 28, 2026, approximately 02:05-02:14 Denver. The network block is identified;
the WebSocket has not been restored. Chris will handle the firewall later at the
office. No firewall setting, security service or trading process was changed.

## Evidence

A capture restricted to TCP 443/9443 and two current stream addresses recorded
16 outbound connection attempts and 16 incoming resets, with no successful TCP
handshake. Resets arrived in 0.205-0.691 milliseconds from the Ethernet address
of the SonicWall gateway at `192.168.1.1`.

An unauthenticated HTTP diagnostic request to `http://stream.binance.us/` received
a SonicWall HTTP 403 block page with reason **Gateway GEO-IP Filter Alert** and
country **Japan**. The retained raw page names `35.74.53.127`; the repeatable
diagnostic subsequently names `52.69.13.128`. This is the firewall's classification,
not an independent geolocation measurement. HTTP content is not TLS-authenticated;
the matching local packet evidence corroborates the filtering diagnosis.

The application uses the documented public market endpoint
`wss://stream.binance.us:9443`. Its TLS and WebSocket handshake cannot begin while
TCP is blocked. Increasing the application timeout does not correct that block.
REST fallback remains available. Other faults can only be excluded after the
network change and a successful live stream validation.

## Targeted correction for the firewall administrator

| Setting | Observed value / required scope |
|---|---|
| Source | Trading PC, currently `192.168.1.223`; verify its address before configuring |
| Destination | Official hostname `stream.binance.us` and its current resolved addresses |
| Service | Outbound TCP **9443**, with normal stateful return traffic |
| Identified block | Geo-IP policy classifies the destination as Japan |
| Dashboard | Remains local; no inbound rule or port forwarding is required |

Keep the general country policy. Inspect the current Geo-IP mode before making
an exception; an ordinary outbound allow rule may not override Geo-IP filtering.

- If already using firewall-rule-based Geo-IP enforcement, scope the exception to
  this source, destination and service while preserving other security inspection.
- If using All Connections mode, a destination Geo-IP exclusion can have a wider
  effect. Confirm that scope and use the supported destination exception mechanism.
  Do not blindly switch the global mode or exempt the PC from all filtering.
- Use a destination object that tracks DNS where supported, and verify the firewall's
  resolved membership. The DNS answers varied during testing; a permanent exception
  for one observed IP may stop working. Do not allow all AWS addresses or all Japan.
- Preserve existing exclusions and Botnet Filter protection. Some configurations
  share a default Geo-IP/Botnet exclusion group; inspect that before editing it.
- Record the original settings and the specific change so it can be reversed.

The management page redirected to `https://192.168.1.1/sonicui/7/login/`, but its
certificate was not trusted by the browser. No warning was bypassed and no login
was performed. The firmware version and actual rule configuration remain unverified.

SonicWall documents [rule-based host exclusions](https://www.sonicwall.com/de-de/support/knowledge-base/kA1VN0000000JvW0AU)
and the [difference between internal-client and destination exclusions](https://www.sonicwall.com/it-it/support/knowledge-base/how-to-exclude-a-client-from-geo-ip/kA1VN0000000IQ30AM).
The stream address follows the [Binance.US market-stream contract](https://docs.binance.us/#websocket-streams).

## Verification after the change

The collector already retries with a backoff capped at 60 seconds. A restart is
not needed simply to retry. Allow for that retry interval, then inspect the local
status and run a new diagnostic receipt:

```powershell
.venv/Scripts/python.exe scripts/diagnose_public_stream.py --output docs/evidence/websocket-recheck-NEW-TIMESTAMP.json
Invoke-RestMethod -Uri 'http://127.0.0.1:8780/api/status'
```

Use a unique receipt filename. Require successful TCP/TLS/WebSocket connection,
advancing Binance.US book/trade messages, fresh exchange timestamps and valid
sequence reconstruction in the running application. A successful handshake alone
does not prove usable market data. Preserve any remaining errors for diagnosis.
The diagnostic also probes unrelated controls and alternate ports; the production
market stream on 9443 is the required path, not every diagnostic endpoint.

At the 02:13:46 Denver service check, the worker was running, nonstale and error-free;
its journal balanced at revision 49619. Primary equity was $99.7593799833, with two
closed trades, no positions/pending orders and no replenishments. This is a dated
snapshot; no account, strategy or funding changes were made during diagnosis.

## Retained receipts and checks

- [Scoped packet capture summary](../evidence/websocket-sonicwall-packets-2026-09-28.json), including capture hash; original capture remains under ignored `data/`.
- [Original block response](../evidence/websocket-sonicwall-block-2026-09-28.json), including response hash and source URL.
- [Repeatable diagnostic result](../evidence/websocket-sonicwall-diagnosis-2026-09-28.json).
- [Service and journal snapshot](../evidence/websocket-sonicwall-service-2026-09-28.json).

The standalone diagnostic now includes a bounded HTTP block-page check with no
redirect following, credentials or account access. Ruff and strict mypy passed
for that script after the change. The live diagnostic reproduced the Geo-IP block.
Trading-runtime code was unchanged; the trading suite was not rerun for this
diagnostic/documentation change. Earlier passing stream tests remain dated evidence.
