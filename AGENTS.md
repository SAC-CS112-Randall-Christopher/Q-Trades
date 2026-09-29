# Current work order: a simple manual updater, then CP1

Chris's September 29 correction supersedes the earlier managed-installer design.
Use `Update Q-Trades.cmd`: fetch main, build, back up code, stop the existing task,
copy application code, install dependencies, restart and report health/version.
Keep the existing runtime folder, task and desktop launcher. Do not add release
registries, activation state machines, task migration or financial-checkpoint gates
to this updater. See `docs/LOCAL_UPDATES.md` and issue #1.

The database, configuration, credentials and research evidence stay local and are
never mirrored or reset by an update. A Git push is not a deployment. Preserve local
source work and require the existing merge/deployment authorization. The archived
installer implementation is not the current product direction.

# September 28, 2026 product-alignment update

Read `docs/PRODUCT_DIRECTION_2026-09-28.md` and `docs/reviews/2026-09-28-analysis.md` before the historical instructions below. The current request adopts the stronger paper-only, cash-only brief and authorizes private GitHub source storage. For new default experiments, derivatives exposure and automatic replenishment are excluded. Earlier options/replenishment permissions below are historical, not authority to expand the new default. Preserve their evidence and do not modify a running local experiment without inspecting and explicitly reconciling its frozen policy.

This bundle changes guidance only. Runtime code is the reviewed baseline: findings in the report are NOT fixed by this document. Private source storage does not authorize public hosting, live trading, paid inference, merge or deployment. Work on one complete vertical checkpoint, beginning with reliable portfolio-valuation/risk-stop behavior.

---

# Trading Research Platform

Read `docs/FOUNDATION.md`, `docs/STATUS.md`, and affected code before substantial changes.
This repository is separate from Auto_bid / True to Plan, including data, credentials, and budget.
Chris explicitly wants local operation (2026-09-27): no internet hosting, shared True to Plan
database, remote database, or public dashboard. Outbound public market feeds are permitted.

- Default to paper. Live credentials, account funding, live trading, paid services, merges,
  external publication, and deployment require applicable explicit authorization.
- The current deliverable is a local Tier 3 paper experiment plus the public-market monitor.
- Latest direction (September 27 evening): focus development and research on cash-funded
  crypto spot first. Defer stocks/options expansion; preserve existing account histories.
  Chris wants trainable models and automated hypothesis research, beyond switching among
  fixed strategies, and welcomes LLM involvement where it improves the application.
  Provider, credentials and an inference spending cap are not yet selected. The current
  fixed strategies remain baselines; describe proposed learning separately from implemented
  behavior. See `docs/research/2026-09-27-crypto-learning-plan.md`.
  Chris also requested research/training sub-agent roles inside the application and
  explicitly authorized local Python tests of the models on those tasks. Prior GIS
  benchmarks may be read under `C:/GIS_AI` for model assessment; this does not authorize
  changing the GIS application or importing its private data/credentials into trading.
  See `docs/research/2026-09-27-agent-harness.md` and the retained model-evaluation receipts.
- September 28: Chris authorized continued role-specific local LLM qualification and,
  once suitable candidates qualify, implementation of a three-role agent harness with
  a UI showing tasks, evidence, concise rationales, actual tool results and failures.
  This permits bounded local advisory inference; paid calls and financial permissions
  remain excluded. Chris approved downloading Qwen3.5 9B and subsequently Ministral 3
  8B Reasoning for comparison on September 28; ask before downloading other weights.
  He will handle disk cleanup and the WebSocket firewall correction at the office.
  His screenshot identifies
  Contrastive Language Model CLM-8B, distinct from contract lifecycle management.
  See docs/research/2026-09-28-contrastive-language-models.md. Preserve failed evaluations
  and distinguish role-contract qualification from trading success.
  Chris subsequently authorized a dedicated local model runtime so ArcGIS and trading
  research can progress concurrently. Trading uses loopback port 11435, CPU-only;
  the initial profile used two logical processors and below-normal worker priority. ArcGIS retains 11434 and
  GPU access. Preserve one trading inference job at a time and paper-worker resource
  gates. Do not terminate, unload or reconfigure the ArcGIS runtime as part of trading
  qualification. Reuse approved installed model files without new downloads. See
  docs/research/2026-09-28-dedicated-runtime.md and current STATUS for the active batch.
  Chris then clarified that research should use spare workstation capacity and yield
  when an ArcGIS request arrives. The two-processor allocation is the current frozen
  qualification profile, not a permanent product limit. Preserve that active profile;
  implement and measure the subsequent elastic policy separately. CPU scheduling and
  GPU handoff are different mechanisms: separate runtimes alone do not provide GPU
  preemption. See docs/research/2026-09-28-resource-priority.md for the accepted direction,
  implementation boundary and required handoff checks.
  The initial two-processor batch subsequently stopped with a retained 600-second
  incomplete response. Its source archive and terminal receipt remain unchanged.
  A separate six-thread CPU profile now allows all processors at Windows IDLE
  priority, below ArcGIS and paper work. An infrastructure probe verified placement
  and priority; simultaneous ArcGIS request latency is not yet measured. The GPU
  remains reserved for ArcGIS. See current STATUS for the active elastic-profile
  qualification freeze; do not change its files or allocation while it runs.
  Supervisors and qualification queues now use project pythonw.exe/windowless
  children. Inspect both python.exe and pythonw.exe plus durable batch state before
  stopping a runtime; preserve active work even if no model is currently resident.
- Chris authorized continuous fake-money trading on 2026-09-27: start at $100, review every
  four hours, permit bounded automatic paper-strategy refinement, and restore to $100 only
  when total liquidation equity falls strictly below $5 after a recorded failure review.
  Success means $100 reaching $1,000 in the majority of attempts, not a high trade win rate.
  Preserve failures, open attempts, costs, every funding event, and cumulative net P&L.
- Keep execution, sizing, accounting, and risk deterministic. AI assistance is optional, disabled,
  and must never authorize orders, write financial state, or alter risk limits. The deterministic
  paper learner may select a version from the reviewed, bounded strategy bank under its gates.
- Preserve all three tier objectives. Tier 1 means stocks/ETFs; aggressive return targets are
  research goals, never guarantees or inputs that increase risk permissions.
- Preserve cash-only boundaries: no borrowing, uncovered sales, provisional funding,
  real deposits/withdrawals, real top-ups, or selling unowned inventory. The fake replenishment
  policy above is the only funding exception. A learner cannot raise its own risk ceilings
  to chase the goal. Chris welcomes aggressive paper experiments: new risk profiles must
  be explicit, versioned and separately evaluated, retaining realistic costs and fills.
- Chris subsequently authorized researching U.S. equity/ETF and crypto options, limited to
  purchased options or fully covered sales. He then excluded futures trading and requested
  futures observations as market context. This supersedes the foundation's blanket
  derivatives exclusion for research;
  it does not authorize live derivatives, borrowing, naked options, or broker account setup.
  Chris then authorized a separate $100 cash-funded options paper account and requested
  free data only, with no monthly subscriptions. He is willing to open a free account
  for market data; this is not authorization to create it for him, deposit money,
  subscribe, or trade through it. See `docs/research/2026-09-27-live-options-data.md`
  before selecting a broker feed. Its isolated `options_paper` PostgreSQL
  schema uses anonymous Market Data AAPL historical end-of-day data, never live quotes.
  Purchased standard calls/puts only: fully reserve premium and fees, next-session fills,
  no same-session reuse of sale proceeds, and unresolved expiry freezes the account.
  The 100-share multiplier and $0.50/contract/side fees are explicit research assumptions.
  Do not count replay outcomes as live results, fabricate Greeks, pool balances, buy data,
  or relax the fixed 2.5% premium-risk ceiling to force activity. Historical windows advance
  once; four-hour reviews can choose only from the frozen options strategy bank.
  The Kraken public perpetual adapter is observation-only. Funding, open interest and basis
  cannot alter trading/risk rules. Claims about their predictive value need forward comparison.
- The paired universe-control-v1 and universe-wide-v1 accounts each have their own fake $100
  and funding record. They compare BTC/ETH with screened USD markets. Never pool their money,
  erase the primary attempt, or automatically promote a wider universe into the primary.
- Build one usable workflow at a time, including UI, failures, persistence, and recovery.
  Do not claim a later checkpoint from scaffolding or passing unit tests.
- Decimal strings cross all money/quantity boundaries. Preserve original public responses,
  observation times, limitations, gaps, failed experiments, losses, and costs.
- Version strategy and execution-cost changes; never rewrite historical parameters or
  regrade old outcomes. Use disposable test schemas, never synthetic trades in the real trial.
- No synthetic fallback for unavailable live data. Do not assume acknowledgments are fills,
  timeouts are failures, or touched prices prove execution.
- Keep queries, in-memory state, and observation retention bounded and disclose truncation.
  The monitor's rolling retention policy must never be reused for a financial journal.
- Do not access unrelated projects or credentials. No financial signing or authenticated venue
  endpoints belong in the public-data adapter. Keep the local service bound to loopback.
- Verify current venue contracts before changing adapters. Existing narrative is not account evidence.
- Run focused tests plus the affected component checks. Report observed evidence and uncertainty.

Checks: `.venv\Scripts\python -m pytest`, `.venv\Scripts\python -m ruff check .`,
`.venv\Scripts\python -m mypy src`, and `npm --prefix apps/web run build`.
