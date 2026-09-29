# Paper risk and recovery

CP1 adds account-level blocked reasons, explicit hard-stop policy adoption and
recovery without adding funds or resetting the risk reference. See
[CP1 behavior and compatibility](docs/CP1_PAPER_RISK.md). This source implementation
is not a claim that the running Windows installation was updated.

# Local updates

After the import and CP0 are merged, double-click **Update Q-Trades.cmd** in the
GitHub checkout. It fetches `main`, builds the dashboard, backs up source, updates
the existing local application and restarts its existing task. No app-folder move,
new service, repeated ZIP import or release-management workflow is required.
Databases, credentials, configuration and research evidence stay untouched.
See [operation and failure handling](docs/LOCAL_UPDATES.md).

The implementation is in draft PR #3; it is not installed merely by pushing it.
The snapshot introduction below is retained as historical context.

---

# Reviewed Q-Trades snapshot

Start with [the product direction](docs/PRODUCT_DIRECTION_2026-09-28.md) and [the evidence-backed analysis](docs/reviews/2026-09-28-analysis.md). This package retains the original runtime source and research evidence, with dated guidance updates only. It does **not** implement the proposed fixes. The original upload contained no Git history.

Local databases, credentials, logs, dependencies, build products and fonts are excluded. Configure a separate local environment; do not copy private runtime credentials into Git. For the optional new private repository import, use `scripts/Publish-PrivateRepository.ps1` with an authenticated GitHub CLI and Git commit identity. The script has not been executed against GitHub in this review. It verifies private visibility before pushing and stages only hash-verified bundle files.

---

# Trading Research Platform

A standalone local trading research application based on [Chris's foundation](docs/FOUNDATION.md).
Trading, accounting, and reviews run in ordinary software, independently of ChatGPT.

**Active experiment:** Tier 3, $100 fake USD, BTC/USD and ETH/USD. The target is $100
reaching $1,000 in the majority of attempts. Three frozen breakout variants run in
separate shadow portfolios. Every four hours the application evaluates new forward
outcomes and may select a version after its gates pass. Otherwise it records a
decision to retain the current version. [Exact contract](docs/LEARNING_EXPERIMENT.md).

A minute-by-minute USD market screen promotes liquid candidates to closer observation.
Two additional, separately funded paper accounts compare BTC/ETH with the wider universe.
Depth/trade/closed-candle WebSocket support requests 100 ms fast depth and 1 s candidate
depth; the dashboard reports the actual transport. **On September 28 at approximately
07:04 Denver, the firewall change restored live BTC/ETH WebSocket data**, verified
through advancing, sequence-validated books and timestamps. Earlier REST-only results
remain retained. Requested update frequency is not a guaranteed arrival rate. Fast
REST fallback waits 0.5 s after each response, subject to rate limits.

Replenishment requires total liquidation equity strictly below $5, cancelled entries,
reconciled liquidation, and a recorded failure review. It adds only enough fake money
to restore $100. All losses, costs, funding, and failed attempts remain visible.
There is no real-money execution or model API integration.

## Running instance

Open [the local dashboard](http://127.0.0.1:8780/#experiment).

The [command station](http://127.0.0.1:8780/#live-quotes) combines a searchable USD
market screen, selected-market bid/ask/spread, closed-minute price/volume candles,
visible order-book depth, observed exchange trades and actual paper decisions.
**Strategies & learning** shows the three real breakout comparisons, their net
outcomes, the selected market's indicator checks, entry/exit rules, and why the
latest four-hour review retained or selected a rule. Inspecting a comparison changes
only the view. Technical metadata stays collapsed; missing/stale evidence stays explicit.
Prices refresh about once a second; chart and decision evidence refresh every ten
seconds. The worker receives WebSocket events independently at its configured
100 ms / 1 s targets. Choosing a market does not promote it into a live subscription.
Unavailable data, fallback transport and stale quotes are labeled explicitly.

Four read-only tools inspect market evidence, calculate a modeled cost hurdle,
explain a recorded decision, and summarize retained paper outcomes after costs.
Runs and failures persist locally and can be reopened. Researcher, Trainer and
Reviewer remain disabled until model qualification; these are deterministic tools,
not simulated agent activity. Technical details and the older feed/storage panel
are collapsed into diagnostics. No charting dependency or additional venue request
was added. [Implementation, limits and verification](docs/research/2026-09-28-command-station.md).

The old slow USD/USDT price table has been removed. Its separate background REST
capture remains available for diagnostic exports and has its own pause control
under Operations.

On this Windows computer, double-click **Trading Research.exe** on Chris's desktop.
The small launcher opens the dashboard in the default browser. If needed, it starts
the existing project startup task and waits up to 90 seconds for the dashboard.
It never stops a worker or changes a task, trading rule, balance or firewall setting.
The application, Python environment, database and journal stay in this project
folder; the desktop executable is not a portable copy of the whole application.

Launcher source: `scripts/TradingDashboardLauncher.cs` and
`scripts/Open-TradingDashboard.ps1`. Rebuild with
`scripts/Build-DesktopLauncher.ps1`; use `-InstallDesktop` for first installation.
The installer preserves an existing desktop file instead of replacing it. Windows'
installed .NET Framework compiler is used; no additional runtime download is needed
on the verified machine. Moving the project requires rebuilding the launcher.
Startup errors appear in a dialog and `data/desktop-launcher.log`.

Windows task `TradingResearch-Paper-20260927` starts a hidden supervisor at sign-in.
It checks the service and restarts its own worker after exits or repeated health
failures. A dedicated Docker PostgreSQL instance listens on **127.0.0.1:55432**.
Other projects and databases are not used.

Keep the computer awake and Docker running. Closing the dashboard or chat does not
stop the application. Host sleep, shutdown, Docker loss, or storage failure can stop
work; missing observations are never filled in with invented trades. A separate
Codex heartbeat checks every four hours while the app is available:
`review-the-100-paper-trading-experiment`.

**Pause paper entries** persists across restarts and permits position exits.
**Pause collection** controls only the separate public monitor. To stop the entire
program, stop its named scheduled task and verified owned Python worker; that also
stops position management. Use the entry pause for normal operator intervention.

## Reproduce locally

Python 3.12+, Node.js 24, and Docker Desktop were used. From this folder in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
.\.venv\Scripts\python -m pip install -e . --no-deps
npm --prefix apps/web ci
npm --prefix apps/web run build
.\scripts\Initialize-PaperDatabase.ps1
.\.venv\Scripts\python -m trading serve --experiment
```

Run only one service. For sign-in startup instead of the foreground command:

```powershell
.\scripts\Install-PaperStartup.ps1
```

Without `--experiment`, the original public monitor runs alone. The database rejects
a second engine owner. The local API is loopback-only, not network-authenticated.

## Dedicated local model runtime

Trading research uses `http://127.0.0.1:11435`; ArcGIS retains its existing runtime
on port 11434. The trading server reuses installed weights, disables cloud inference,
uses CPU only, and the elastic profile allows six inference threads across all
processors at Windows IDLE priority, below ArcGIS and paper work. The earlier fixed
two-processor profile remains available for reproducing its archived configuration.
It has one model/request at a time and does not block on ArcGIS's resident
models. Memory and disk bandwidth are still shared hardware resources.

```powershell
.\scripts\Install-ResearchRuntime.ps1 -RuntimeProfile CpuElastic
```

This installs/starts `TradingResearch-Models-20260928` for the current user's sign-in.
Runtime status and ownership are saved in `data/research-runtime.json`. To stop this
runtime after research jobs finish and its model has unloaded:

```powershell
.\scripts\Stop-ResearchRuntime.ps1
```

Finish the active test batch before changing a profile. CPU scheduling shares spare
capacity; automatic GPU borrowing/preemption is not implemented. The six-thread
counting probe completed in 71.329 seconds at 2.799 generated tokens/second with zero
GPU use. This is infrastructure evidence, not role qualification or simultaneous
ArcGIS latency validation. See [resource priority](docs/research/2026-09-28-resource-priority.md).

Model tests use `scripts/run_qualification_queue.py` with the exact current freeze
receipt listed in [STATUS](docs/STATUS.md). Do not launch a duplicate queue or replace
an unfinished receipt. The dashboard's Model trials view reads actual evaluation
results. A runtime, a model test, and an enabled advisory harness are separate stages.
See [operation and limits](docs/research/2026-09-28-dedicated-runtime.md).

## Evidence and storage

```powershell
.\.venv\Scripts\python -m trading paper-report
.\.venv\Scripts\python -m trading replay path\to\public-market-capture.json
```

`GET /api/status` returns current status. `GET /api/paper/journal` returns immutable
events and journal lines. Pass `after=<next_after>` until `has_more` is false;
`limit` is capped at 1,000. The UI shows recent primary events and separate shadows.

`GET /api/paper/quotes` is a small read-only view of up to eight existing in-memory
books. It makes no market requests or database calls and does not mutate execution
state. Money crosses the API as decimal strings; displayed quote freshness expires
locally between requests. It grants no trading authority.

`GET /api/station/live` and `/api/station/detail` accept a selected `symbol` and
project the existing runtime observations. `/api/research/tools` lists registered
tools and recent runs; `POST /api/research/tools/run` accepts only a tool name and
known symbol, requires the local operator header and same origin, and cannot place
orders. Receipt reads use `/api/research/tools/runs/{id}`. Results are saved separately
in `data/research-tools.sqlite3`, capped at 5,000 runs and 128 KiB per result, with a
database page ceiling. Capacity stops optional work rather than pruning history.

`data/monitor.sqlite3` retains at most 2,000 public responses and 16 MB of payloads.
PostgreSQL financial and candle history is separate and retained. The volume is
`trading-research-paper_paper-pg18`; do not remove it. Ignored files under `data/`
hold restricted local database credentials, unrelated to any exchange account.
No exchange or model API keys are read.

`data/paper-stream.sqlite` keeps a rolling maximum of 20,000 raw records / 64 MiB
of payloads. Database files and WAL add overhead. Trades, costs, decisions, minute
summaries, discovery scans and reviews remain in PostgreSQL. The dashboard measures
raw input rate, actual file size, database size and free disk. Raw capture pauses below
5 GiB free; permanent history is not automatically deleted. See
[feed and storage details](docs/research/2026-09-27-feed-storage.md).

[Broker research](docs/research/2026-09-27-brokers.md) covers cash-funded options,
commodity exposure, settlement constraints and fees. No broker or futures execution
adapter is connected. The application and both databases remain local to this machine.

The separate options paper account also starts with `--experiment`. It has its own
$100, immutable journal in PostgreSQL schema `options_paper`, two separately funded
frozen research variants, four-hour reviews and below-$5 failure/replenishment rules.
It studies actual **free AAPL historical end-of-day** quotes without an account or key.
This is chronological replay, not live options trading. The $2.50 initial premium-plus-fee
risk limit can rule out every contract; there is no forced trade or automatic risk increase.
See [free-data experiment and limitations](docs/research/2026-09-27-free-options.md).
`GET /api/options/journal` provides the separate paginated audit history.

Public Kraken perpetual futures provide observation-only funding, open interest and
mark/index price differences about once a minute for up to eight tracked assets.
The dashboard labels missing/stale context; observations accompany order/fill receipts
and four-hour reviews. This does not change spot signals or permit futures orders.
Liquidations, CME/dated futures and live options chains are not connected. See
[futures context and options research](docs/research/2026-09-27-futures-context.md).

## Checks

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy src
npm --prefix apps/web run build
```

PostgreSQL tests use uniquely named disposable schemas, never the running account.
They skip without local database settings; skipped tests are not database proof.
The spot simulator uses subsequent fresh observations, capped IOC fills, 10% displayed depth,
0.10% fees per side, and 2 bps adverse prices. These are modeling assumptions.
See [verification and limitations](docs/STATUS.md).
