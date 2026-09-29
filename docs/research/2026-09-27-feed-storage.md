# Local feed, learning evidence and storage — September 27, 2026

The application remains entirely local. Public Binance.US network connections supply
market information; they do not host the application. The dedicated PostgreSQL container
`trading-research-paper-paper-db-1` binds only to 127.0.0.1:55432. The dashboard binds
only to 127.0.0.1:8780. Neither uses True to Plan / Auto_bid databases or credentials.

## What is actually receiving data

The upgraded live service uses real public REST fallback because WebSocket connections
timed out on this machine, including separate probes of ports 9443 and 443. At the
initial live checkpoint, BTC/ETH requests completed in approximately 203–219 ms.
Fast fallback waits 500 ms after each response, plus rate-budget delays if necessary.
That suggests roughly 0.7 seconds between observations under those conditions; it is
not a latency guarantee and does not capture every intervening change.

Push support is implemented and covered by mocked sequence/reconnection tests, but
no genuine 100 ms stream has yet been received. The documented public endpoint is
`wss://stream.binance.us:9443`; each symbol combines depth, trades and one-minute klines.
Depth supports 100 ms or 1,000 ms delivery. REST depth has sequence IDs but no exchange
event timestamp; depth stream E and trade E/T are retained separately from local
receipt time. [Official Binance.US market-data specification](https://docs.binance.us/).

An exchange clock sample estimates offset and uncertainty. Sequence gaps, stale events,
clock jumps, crossed books, insufficient bootstrap coverage and malformed values
invalidate executable evidence. The book is reconstructed from a 1,000-level bootstrap,
with 20 usable levels provided to the simulator. Price-aggregated L2 does not reveal
individual order identity or our queue position. Faster observations do not establish
better returns, executable fills or exchange proximity.

## Promotion and demotion

Every minute the collector screens active USD spot markets, excluding stablecoin bases.
The first running screen covered 52 such markets. Selection requires two valid scans,
at least $100,000 observed 24-hour volume, 300 trades and spread <=25 bps. Qualifying
candidates are ranked by absolute 24-hour percentage change and then volume. This is
a versioned heuristic, not evidence that the largest move is profitable.

Normally four additional candidates receive 1 s depth targets (5 s REST fallback).
Two with eligible closed-bar signals can receive 100 ms targets. Held/pending markets
always receive priority. Total capacity is eight symbols, including BTC/ETH and any
pinned holdings. Minimum residence is five minutes while eligible. Processing pressure
temporarily removes optional subscriptions; it cannot demote held markets.

A live correction avoids throttling on one brief disk/scheduler outlier: reduction
requires four >100 ms engine samples in the last twenty, or one >=1,000 ms stall.
After that fix, six markets were subscribed at 18:30 Denver, research was unconstrained,
application CPU averaged 0.59%, and engine p95 remained 31 ms. Their streams still
timed out; real REST fallback continued. No connected-push throughput is implied.

The running original primary and three strategy shadows retain BTC/ETH. Two newly
labeled $100 research accounts compare BTC/ETH against screened USD opportunities
using the same breakout rules and costs. Their funding is independent. Four-hour
reviews include their observations but cannot automatically widen the primary universe.

## Storage policy

| Record | Local store | Retention |
|---|---|---|
| Account balances, funding, fills, costs, intents, decisions, attempts, reviews | Dedicated PostgreSQL | Permanent, append-only events/journal |
| Closed minute bars, discovery scan decisions, per-minute sampled-book summaries | Same PostgreSQL | Permanent |
| Raw stream envelopes, REST fallback books, snapshots and gap diagnostics | `data/paper-stream.sqlite` | Newest 20,000 records, additionally capped at 64 MiB JSON payload |
| Original four-pair dashboard monitor | `data/monitor.sqlite3` | Existing 2,000-record / 16 MB payload ceiling |

The new raw SQLite main file is limited to 128 MiB by page count. WAL, shared memory,
indexes and filesystem overhead are additional; the 64 MiB label is a payload cap,
not a total filesystem limit. Pruning counts and actual bytes are visible. Raw capture
stops below 5 GiB free. Its bounded input queue counts discarded records; it never
silently claims a complete replay after pruning, gaps or queue overflow.

The permanent database continues growing. Losses and trade evidence are not pruned
to meet a raw-data target. Its reported size excludes PostgreSQL WAL/backup copies
and Docker's virtual-disk allocation. The free-disk reading captures overall pressure.
Backups and recovery drills still need implementation; retention is not a backup.

## Observed cost and growth

The machine reported about 96 GiB installed memory, six physical/twelve logical CPU
cores and roughly 37–38 GiB free on C:. No cleanup was performed.

At 18:23 Denver, approximately four minutes after the upgrade:

- Application CPU average: 0.40% of total logical CPU capacity. This excludes Docker.
- Paper engine p95 work and transaction time: 31 ms each.
- Separate PostgreSQL container snapshot: 66.07 MiB memory; Docker reported 7.56% CPU
  using its own convention. This is a momentary reading, not a total-machine average.
- New raw capture: 641 records, 2.10 MiB payload, 5.78 MiB physical files.
- Incoming raw rate projected to 0.884 GiB/day **if all input were retained**. The
  rolling retention cap prevents that being daily retained raw growth.
- Permanent database: 10.92 MiB, 3,756 bars and 1,110 events, including history from
  before the upgrade and new candidate bootstrap bars.

The early 18-second isolated probe projected 1.881 GiB/day because startup snapshots
dominated. Neither rate is a long-term forecast. For scale, measured 10 KiB/s would be
0.824 GiB/day; 100 KiB/s would be 8.24 GiB/day without retention. A connected push feed
with more active markets may be substantially larger than this REST fallback sample.
Permanent growth should be measured after warmup and across active trading periods;
it cannot be inferred from short startup database-size changes.

## Verification and limitations

85 tests passed, including isolated real PostgreSQL tests. Covered cases include gap
reconstruction, stale/clock checks, capture pruning, candidate screening, fallback
timestamp honesty, new-asset inventory reconciliation and separate research funding.
An exchange-confirmed closed candle persists even when the local clock is behind;
its actual local receipt timestamp is preserved. Ruff, strict mypy and pip checks pass.

An isolated 18-second public-feed probe completed with no engine error and balanced
accounting. A real service restart preserved primary cash exactly at
99.7593799833000000000, total funding 100, two closed trades, no pending order and
no position. The execution observation model transition was journaled. Original
fees (0.10% per side), 2 bps adverse prices, 10% depth participation, fixed risk limits
and minimum one-second delay remain unchanged.

The paired wider accounts, real push connectivity, prolonged high-throughput load,
first four-hour review, replenishment and majority $1,000 success are not proven by
these tests. See `docs/evidence/tiered-*` for the checkpoint receipts and phone preview.
