# Local command station — September 28, 2026

Chris requested useful trading-terminal features, a polished responsive layout and
little visible metadata. The implemented slice is a selected-market evidence workflow,
with deterministic tools that a future qualified advisory harness can also use.

## What each feature supports

| Feature | Purpose and source |
| --- | --- |
| Searchable market screen | Compare the existing USD scan's liquidity and 24-hour movement; selecting a row never changes feed or trading permissions. |
| Bid, ask and spread | Inspect the same validated book source the paper worker observes; stale/fallback/unavailable states remain explicit. |
| Closed-minute candles and volume | Inspect retained price and volume context across 30/60/120 candles; bootstrap history is not paper-trading evidence. |
| Visible order book | Inspect up to eight displayed levels per side from the selected source, without claiming hidden liquidity or execution certainty. |
| Observed trade tape | Show up to eight recent exchange prints, with exchange times; quiet markets and incomplete/gapped subscriptions are explicit. |
| Paper decision and activity | Inspect actual primary-account decisions and recent journal events for the selected market. |
| Four registered tools | Save market evidence, calculate the modeled cost hurdle, explain a recorded decision and review net outcomes/fees. |

The interface uses native SVG, React and existing icons. No dependency was added.
Chart width follows its container so phone labels remain readable. Diagnostics and
raw receipts start collapsed. The previous feed/storage panel is also collapsed;
useful stale/error notices remain visible. The desktop and 430/360-pixel layouts
were inspected in the real local browser with no horizontal document overflow.

## Evidence and authority

The subsequent **Strategies & learning** view reads the actual `VARIANTS` bank and
cached feature observations. It exposes the primary version separately from the
version being inspected. Three cards show independent balances of correlated
BTC/ETH comparison accounts; their performance is not relabeled as the selected
symbol's performance. Net results subtract lifetime funding, including replenishment.
Trend/breakout/volume/extension badges require complete, current closed-bar evidence;
stale or absent evidence is Unknown. The newest review retains its original timestamp,
reason and per-window trade counts, bounded to two windows.

All variants currently use a 20-period EMA of five-minute closes (price above the
EMA and EMA above its value three observations earlier), a minute-close breakout,
volume confirmation and a 14-period Wilder ATR. The entry lookback/volume thresholds
are 10/2x, 7/1.5x and 15/2.5x. A breakout more than 1.5 ATR above its trigger is rejected.
Initial stop is 1.5 ATR below the actual modeled entry. Once the bid rises by that
initial distance (1R), the stop becomes the maximum of its prior value and bid minus
one current ATR. It never loosens. No 1R progress after ten minutes and a 45-minute
maximum hold are additional exits; there is no fixed profit target. Stop triggers
request later simulated fills and cannot guarantee a profitable or capped-loss exit.
The UI states that price-based trailing activation may still lose after costs.

This addition changes neither those rules nor risk/learning permissions. Descriptive
research questions are authored labels for the frozen experiments, not generated
agent thoughts or newly trained policies. Current review counts and reasons remain
evidence-based. Broader trainable models and LLM roles remain inactive.

Final strategy-view checks: 170 tests passed, Ruff/mypy and frontend build passed.
The primary remained `breakout-v1` after inspecting both alternatives in the browser.
Desktop and 360-pixel layouts fit without horizontal overflow. The final JS bundle
is 90.73 KB gzip; the strategy projection adds approximately 3 KB to a ten-second
detail response. A subsequent owned reload preserved all account fields and six
tool receipts; the full journal balanced at revision 90717. See
`docs/evidence/strategy-view-*-20260928.json`.

`src/trading/station.py` projects existing runtime state, without new venue requests,
DB reads for market views, or financial writes. Money/quantity values cross APIs as
decimal strings. `market_live` returns at most ten book levels per side and twenty
trade prints; the feed keeps forty prints per subscribed symbol and drops that
temporary tape on demotion. Raw capture and permanent financial history retain their
existing independent policies.

`market_detail` bounds the scanner to eighty rows, history to 120 closed minute
candles and matching primary events to twelve. Omitted rows and missing candle
intervals are disclosed. Event projections contain compact summaries and journal IDs;
full books, instruments and observations remain in the original journal.

Cost hurdle uses the engine's existing 0.1% fee per side, 2-basis-point adverse price
assumption and tick rounding. It requires a fresh quote and current instrument
metadata. It is a per-unit top-of-book threshold, excludes deeper impact/quantity
constraints/timing/fill uncertainty, and creates no simulated order. Outcome summaries
cover the latest thirty matching trades from the primary account's retained
1,000-trade memory; net P&L already includes fees. Whole-account totals are separate.

`ToolJournal` is an isolated local SQLite database. Runs persist before execution;
completed/failed results include immutable hashes and cannot be overwritten. Restart
marks unfinished runs interrupted. Bounds are 5,000 runs, 128 KiB per result and
16,384 SQLite pages. Capacity rejects optional work without pruning receipts. SQLite
I/O runs outside the trading event loop. The API requires local operator/same-origin
requests, a healthy paper worker, free disk, and at most one bounded tool execution
per second. No model text is executed as a command and no financial tool is registered.

These are working deterministic tools, not a completed agent harness. Model trials
remain visible separately; no role is qualified or activated. There are no paid calls,
new downloads, strategy/risk changes or financial permissions in this change.

## Responsiveness and verification

Only visible station views poll: quotes about once per second, detail/receipts every
ten seconds, with one request at a time and bounded timeouts. Hidden tabs and sections
pause market-view requests. Chart and result components are memoized independently
of the quote-freshness timer. The worker feed and trading loop operate independently.

A bounded persistent-client sample of eight local HTTP requests per route measured:

| Route | Median / maximum observed | Payload in final sample |
| --- | --- | --- |
| Selected live view | 1.28 / 1.80 ms | 3,333 bytes |
| Detail view | 1.80 / 2.11 ms | 35,547 bytes |
| Tool list | 1.37 / 2.48 ms | 1,151 bytes |

These are short local request samples, not exchange latency, execution latency or a
long-duration resource guarantee. Compact event summaries reduced the observed BTC
detail payload from about 73.5 KB to 35.5 KB. The final main JS bundle is 88.56 KB gzip
versus approximately 84.80 KB before this station. Actual worker CPU was about 1.98%
of the machine, with 62 ms engine-work p95 in one status snapshot; Docker/other
processes are excluded. Resource constraints and occasional fallback still apply.

All 168 Python tests passed; 37 focused station/stream/quotes/API checks also passed.
Ruff, strict mypy (33 modules) and the TypeScript/Vite build passed. The existing
Starlette/httpx deprecation warning was retained. Tests cover read-only behavior,
cost math, retained-window totals, bounds, gaps, duplicate trades, immutable results,
failure/restart recovery, capacity, origin/health/rate gates and financial-state
preservation. Real browser checks covered selecting BTC/ETH, searching/clearing,
liquidity filtering, 60-to-120 candle switching, all four tools, an honest failed
AAVE cost request, reopening receipts and desktop/mobile layouts.

## Recovery and retained evidence

The final backend reload at approximately 08:08 Denver preserved all six spot
accounts, options accounts and three pre-existing tool receipts byte-for-byte at
the API object level. The financial report balanced at revision 89006. Primary
equity remained $98.6630401795, ten closed trades, attempt 1 open, no replenishments.
Natural trading may subsequently change these values.

The Windows supervisor had exited at 07:56:44 with return code 3221225786 while its
worker stayed alive. Its cause was not established. The verified existing task was
restarted with the updated worker; it remained running through subsequent checks.
No scheduled-task definition or unrelated process was changed. Sustained recovery
from the earlier supervisor exit is not proven.

Receipts: `docs/evidence/station-status-*-20260928.json`,
`station-journal-*-20260928.json`, `station-tools-before-reload-20260928.json`, and
`station-reload-validation-20260928.json`. The PowerShell-produced at-reload status
file contains a JSON-encoded string and needs a second JSON decode; its original
bytes were preserved. Independent Python snapshots and post-reload comparisons
confirm the unchanged account fields. Browser tool runs remain in the real isolated
tool journal, including the failed request. No synthetic trade entered the trial.
