# Automated Trading Research Platform
## Product foundation, agent orchestration, and implementation specification

**Owner:** Chris Randall / Randall Automation Works LLC  
**Version:** 0.1 — proposed build baseline  
**Prepared:** September 27, 2026  
**Account jurisdiction:** Colorado, United States  
**Initial operating mode:** Paper trading only  
**Initial live stake under consideration:** $50–$100 total, subject to separate authorization  
**Relationship to True to Plan:** Separate application, repository, credentials, data, and operating budget

> **Architecture in one sentence:** One deterministic trading and accounting engine runs isolated strategy portfolios; bounded AI assistants research, challenge, and explain strategies without receiving authority to place live orders, change risk limits, or move funds.

### Document status and how to use it

This is a specification, not an implemented application or a verified profitable strategy. It defines the intended product, operational boundaries, proposed architecture, research candidates, and acceptance criteria. No account was accessed, strategy backtested, market feed deployed, or order submitted while preparing it.

The three tiers and cash-only requirement come from Chris's stated objectives. Technical decisions and numeric strategy/risk settings below are **proposed engineering and research defaults**, not previously approved live settings and not empirically optimized parameters. External facts are footnoted and dated; they must be rechecked before integration and funding. All uncited implementation rules are design proposals rather than claims about existing software or market performance.

The immediate deliverable is an honest research instrument: it must be capable of concluding that a strategy is unprofitable, undercapitalized, or not sufficiently verified. The desired eventual deliverable is unattended operation of an explicitly authorized, fully funded strategy, with understandable reporting and recoverable failures.

## Reading paths

**Product and agent decisions:** Sections 1–5.  
**Trading and accounting implementation:** Sections 6–12 and 15–18.  
**Evidence, AI, and live readiness:** Sections 13–16 and 24.  
**UI, configuration, tests, and delivery:** Sections 19–23 and 25.

## Contents

- [1. Product intent and non-negotiable requirements](#1-product-intent-and-non-negotiable-requirements)
- [2. Decisions this document makes](#2-decisions-this-document-makes)
- [3. Verified venue assumptions and unresolved conditions](#3-verified-venue-assumptions-and-unresolved-conditions)
- [4. Would we have several agents?](#4-would-we-have-several-agents)
- [5. Architecture and ownership boundaries](#5-architecture-and-ownership-boundaries)
- [6. End-to-end deterministic orchestration](#6-end-to-end-deterministic-orchestration)
- [7. Capital isolation and portfolio ownership](#7-capital-isolation-and-portfolio-ownership)
- [8. Initial strategy specifications](#8-initial-strategy-specifications)
- [9. Deterministic risk and cash controls](#9-deterministic-risk-and-cash-controls)
- [10. Order lifecycle and exactly-once accounting](#10-order-lifecycle-and-exactly-once-accounting)
- [11. Accounting, valuation, and financial truth](#11-accounting-valuation-and-financial-truth)
- [12. Paper execution that does not manufacture profits](#12-paper-execution-that-does-not-manufacture-profits)
- [13. Research, evaluation, and promotion](#13-research-evaluation-and-promotion)
- [14. AI roles and controlled learning](#14-ai-roles-and-controlled-learning)
- [15. Operating states, failures, and recovery](#15-operating-states-failures-and-recovery)
- [16. Security, authorization, and abuse prevention](#16-security-authorization-and-abuse-prevention)
- [17. Data model, storage, and reproducibility](#17-data-model-storage-and-reproducibility)
- [18. Proposed implementation stack and repository layout](#18-proposed-implementation-stack-and-repository-layout)
- [19. Operator experience and dashboard requirements](#19-operator-experience-and-dashboard-requirements)
- [20. Configuration example and validation rules](#20-configuration-example-and-validation-rules)
- [21. Verification and acceptance tests](#21-verification-and-acceptance-tests)
- [22. Phased implementation plan](#22-phased-implementation-plan)
- [23. Worked example: one complete paper trade](#23-worked-example-one-complete-paper-trade)
- [24. Open decisions and live blockers](#24-open-decisions-and-live-blockers)
- [25. Instructions for future implementation agents](#25-instructions-for-future-implementation-agents)
- [26. Sources and research notes](#26-sources-and-research-notes)

---

## 1. Product intent and non-negotiable requirements

### 1.1 What Chris should be able to do

Open one dashboard, see three clearly distinguished strategy tiers, inspect their real costs and losses, compare them against passive alternatives, understand why trades occurred, and decide whether a particular frozen strategy deserves a small live experiment.

The application should support this complete workflow:

```text
Select a research profile and a realistic starting balance
  -> collect eligible market data
  -> evaluate explicit strategy rules
  -> simulate orders under actual venue constraints
  -> account for every fill, fee, open position, and failure
  -> compare net results with an appropriate benchmark
  -> review a fixed evaluation record
  -> separately authorize a limited live experiment, or reject the strategy
```

A chart, a successful API request, or a large number of trades does not complete this workflow.

### 1.2 The three objectives

| Tier | Working name | User objective | Interpretation |
|---|---|---|---|
| 1 | Systematic | The original comparatively conservative idea: diversified quantitative investing, seeking above-market results over a multi-year horizon. | Quality/value/momentum stock selection and cross-asset trend research. Not a capital guarantee. |
| 2 | Aggressive | Investigate 10–20% account growth per week. | An aspirational evaluation target for selective, shorter-horizon strategies; not an assumed expected return. |
| 3 | Experimental | Investigate 10–20% account growth per day through very aggressive, potentially high-volume trading. | A high-risk research objective; frequent trading must demonstrate positive after-cost economics rather than satisfy an activity quota. |

Returns mean **whole-portfolio growth**, including open losses and costs—not the return on the best trade or on only the money currently invested. No weekly or daily target is permitted to increase a risk limit, override a rejected order, or force a trade.

### 1.3 Hard boundaries

- No margin, loans, short selling, derivatives, leveraged tokens, or borrowing of cash or assets.
- No reliance on provisional deposit credit. Trading requires verified eligible funding and actual available balances.
- No automated deposits, withdrawals, bank pulls, credit-card funding, inter-exchange transfers, or loss replenishment.
- No selling more of an asset than the account and the relevant portfolio allocation actually own and have available.
- No live deployment, capital increase, or expansion of permissions without Chris's explicit authorization.
- No silent resets, erased losing experiments, invented fills, hidden operating costs, or claims of verified profitability based on unverified simulations.
- No customer funds, pooled investment accounts, copy trading, or public investment-management service in this initial product.

**Important boundary:** Application controls can prohibit borrowing and use of provisional funds. They cannot promise that an exchange's contract, a reversed deposit, taxes, account compromise, or third-party service bills can never create an obligation. An absolute legal guarantee of “never owe anything” has not been established. Funding and account terms remain a live-launch blocker until reviewed against Chris's requirement.[^bn-negative][^bn-terms]

### 1.4 Priority order

1. Prevent unauthorized actions, borrowing, duplicate spending, and destructive accounting errors.
2. Preserve correct balances, fills, costs, and research results.
3. Complete the paper-to-review workflow through the normal UI.
4. Make the system understandable and recoverable without reading logs or editing database rows.
5. Improve returns, execution, efficiency, and model sophistication within those boundaries.

---

## 2. Decisions this document makes

| Decision | Baseline |
|---|---|
| Agent architecture | One deterministic runtime; three strategy tiers; three bounded AI roles, not a swarm of autonomous traders. |
| Initial execution | Our own paper executor using live market data. No trading credentials required for the first public-data slice. |
| Initial crypto venue candidate | Binance.US, provisionally, for Tier 2 and Tier 3 research. Not yet selected irrevocably for live execution. |
| Tier 1 venue | Separate stocks/ETF data and cash-broker decision. Do not relabel a crypto-only proxy as the original Tier 1. |
| Account ownership | One human owner initially; dedicated trading account recommended for any live pilot, with no unrelated holdings or manual trading. |
| Capital comparison | Independent $50 and $100 paper runs per implemented tier. These are counterfactual portfolios, not six funded brokerage accounts. |
| Initial live scope | At most one explicitly selected strategy/portfolio at a time, using a total $50–$100 stake. Other tiers continue on paper. |
| Strategy implementation | Explicit algorithms first. Optional frozen statistical models later. No language-model call in the order decision or safety-critical path. |
| Data/accounting | One authoritative application ledger, reconciled to exchange evidence; raw market data stored separately. |
| Deployment | A small modular application with a long-running runtime, relational database, research jobs, and a web UI. No initial microservice fleet. |
| Adaptation | Strategies may adapt only through predeclared deterministic rules. New research changes require a new strategy version and evaluation record. |
| Live promotion | Human decision following technical and economic evidence; never automatic because a target or trade count was reached. |

The initial absence of a live adapter is a safety property, not a reason to delay a useful paper product.

---

## 3. Verified venue assumptions and unresolved conditions

### 3.1 Binance.US snapshot

The following describes official documentation reviewed on September 27, 2026. It is not an account-specific verification or a measurement of live execution.

| Topic | Documented observation | Consequence for our design |
|---|---|---|
| Colorado | Colorado appears in Binance.US's supported-state list.[^bn-states] | Verify eligibility during actual onboarding; do not bypass residency restrictions. |
| Standard spot commissions | Published standard rates are 0% maker and 0.02% taker; BNB/USD has separate pricing.[^bn-fees] | Record effective rates by account, symbol, date, fee asset, and execution role. Do not depend on promotional or exceptional rates. |
| Deposit credit | Binance.US may pre-credit deposits; failed or reversed deposits can create negative balances.[^bn-negative] | Exclude provisional funds even when the venue labels them tradable. |
| Withdrawal hold | ACH funding has a seven-day withdrawal restriction; that is not a fresh seven-day hold after every trade.[^bn-ach] | Model funding clearance, trading availability, and withdrawal eligibility separately. |
| Trade settlement | Rules describe prompt digital-asset settlement and periodic fiat settlement, without an interval or settlement guarantee.[^bn-rules] | No blanket T+1 delay for crypto fills, but no invented guarantee of instantaneous USD reuse. Wait for reconciled availability. |
| New-account Soft-Staking | Accounts created on or after June 5, 2026 require Soft-Staking enrollment for full functionality; the FAQ lists eligible assets and a reward-sharing arrangement.[^bn-staking] | Review and accept or avoid the arrangement before funding. Never silently activate a yield strategy. |
| Security | API permissions and trusted-IP restrictions are available.[^bn-keys] | The future executor gets only necessary reading/trading permission; no withdrawal capability. Verify actual permissions rather than assume defaults. |
| Historical data | The venue advertises historical candles, trades, and aggregated trades.[^bn-history] | Useful for research, but not a substitute for historical executable order-book depth. |
| Minimum orders | The published trading-limit table includes separate quantity, notional, and price restrictions.[^bn-limits] | Validate entries and exits against current market rules; small position sizes are not universally supported. |
| Maintenance | The August 2026 upgrade notice canceled open orders and did not reinstate them.[^bn-maintenance] | Reconcile after interruptions; a previously submitted protective order cannot be assumed to remain present. |

### 3.2 Current API facts worth preserving

The API provides market data, account/order functions, filters, and rate limits. Its order-test endpoint validates a request without matching it. The September 17, 2026 changelog deprecates `listenKey` streams and introduces `userDataStream.subscribe.signature`, with retirement timing still to be confirmed. Account-specific filters can require information beyond symbol metadata. The documentation also contains examples; example numeric limits are not verified account entitlements.[^bn-api]

**Implementation rule:** Build the adapter against the current Binance.US contract and observed responses. Do not assume Binance.com, an old tutorial, or an exchange library has equivalent behavior. Record capability-test evidence before enabling each order type.

### 3.3 What remains unverified

Live spreads, order-book depth, latency, practical fill quality, exact available markets for Chris's account, account-specific permissions, settlement behavior for the selected quote asset, and a funding arrangement satisfying the no-borrowing requirement remain unverified.

Binance.US is a **candidate with attractive documented costs**, not a completed broker selection. The provider boundary must allow replacement without duplicating strategy or accounting logic.

### 3.4 Separate funding facts from trading facts

Maintain distinct values for:

- Funds reported by the venue.
- Funds approved as cleared and eligible for this application.
- Funds reserved by our pending or open orders.
- Funds locked externally or awaiting reconciliation.
- Funds withdrawable under the venue's policy.

A venue balance increase must never automatically create additional authorized strategy capital. A manual funding review may establish an approved baseline, but is not a guarantee against subsequent reversals. An unexplained increase is recorded and quarantined, not treated as profit.

---

## 4. Would we have several agents?

### 4.1 Yes, several roles; no, several independent money handlers

Use “agent” only where it describes a useful responsibility. A strategy module is not necessarily an LLM, a process, or a separate service.

| Role | Implementation | May do | Must not do |
|---|---|---|---|
| Runtime orchestrator | Deterministic application code | Schedule work, process events, coordinate portfolio and order state. | Invent trades, rewrite rules, or call an LLM to decide whether to bypass a control. |
| Strategy modules | Deterministic rules; later optional frozen statistical models | Produce typed entry/exit intentions from eligible data. | Access trading credentials, submit orders, allocate another tier's money. |
| Portfolio/risk controller | Deterministic code | Size/reject intentions, reserve capital, apply exposure and loss limits. | Accept an AI vote as permission to exceed limits. |
| Executor and reconciler | Deterministic code | Submit authorized commands, track actual orders/fills, reconcile balances. | Infer a fill from an acknowledgment or retry an uncertain order blindly. |
| AI Researcher | Optional bounded LLM job | Propose hypotheses, extract public information, request registered research jobs. | Change an active strategy or access a live signing credential. |
| AI Reviewer | Separate bounded review pass | Challenge evidence, identify leakage/cost assumptions, request approved checks. | Certify safety or profitability by narrative judgment alone. |
| AI Operations Analyst | Read-only LLM/reporting role | Explain results and incidents using structured records. | Create trades, change balances, or “fix” an incident by editing production state. |
| Chris | Authenticated human operator | Approve research profiles, review evidence, authorize live use and risk changes. | Be asked to approve every routine order of an already authorized algorithm. |

The three AI roles can initially be three prompt/tool profiles running sequentially with one provider. They do not require three subscriptions, three constantly running models, or inter-agent debate on every trade. Separate roles improve responsibility and review; they do not guarantee independent errors or statistical validity.

### 4.2 The practical answer about algorithmic trading

**Execution is algorithmic. Research can be AI-assisted.**

A rule can ask whether a completed price bar exceeded a prior range, whether volume increased, whether spread is acceptable, and whether the account has enough eligible cash. These are explicit calculations.

Later, an approved model could output a probability or ranking. The resulting decision would still pass deterministic portfolio, cost, and execution rules. A model's score is not a permission and is not a calibrated probability unless calibration has been evaluated.

An LLM may extract a structured fact from a public filing. That extraction is asynchronous research data with provenance and an availability timestamp—not a live instruction to buy. A model outage must not stop existing position management.

### 4.3 What we explicitly will not build first

No autonomous committee debating each tick; no always-on “AI portfolio manager” with unrestricted brokerage tools; no reinforcement-learning agent trained on live money; no strategy that changes itself after every loss; no market making, cross-venue arbitrage, or short-side strategy simply to increase activity.

---

## 5. Architecture and ownership boundaries

### 5.1 Two paths, one application

```text
RESEARCH / REVIEW PATH — no trading secrets

Public documents + historical data + approved performance records
         |
         v
AI Researcher -> registered deterministic experiments -> AI Reviewer
         |                                              |
         +------------ candidate evidence --------------+
                                |
                         Chris reviews
                                |
                 frozen strategy/configuration
                                |
                                v
TRADING PATH — no LLM dependency

Venue feed -> validate/normalize -> features -> strategy intentions
                                                |
                                                v
                                  portfolio + risk + cash reservation
                                                |
                                                v
                                  sole execution coordinator
                                     /                    \
                            paper adapter          live adapter
                            default                absent/disabled initially
                                     \                    /
                                      order/fill evidence
                                                |
                                  ledger + reconciliation
                                                |
                                 dashboard + deterministic reports
                                                |
                                  optional AI explanation
```

The UI is not the runtime. Closing a browser tab must not stop trading or accounting. Conversely, an attractive connected dashboard does not imply that the execution process is healthy.

### 5.2 Initial process layout

One repository and shared domain code; a few necessary runtime boundaries:

1. **Trading runtime:** Market ingestion, scheduling, feature calculations, strategies, risk, paper execution, and reconciliation. Only this role may dispatch authorized trading commands.
2. **Web/API process:** Dashboard, authenticated commands, reporting queries. It persists requested actions; it does not call an exchange trading endpoint directly.
3. **Research worker:** Bounded historical jobs and optional AI tasks. Separate credentials, resource budget, and write permissions.
4. **PostgreSQL plus market-data files:** Operational ledger and metadata in the database; partitioned raw/history datasets in files.

A minimal local paper release may combine the first two process roles if there is still exactly one execution coordinator. Research must not block the event loop or gain access to live credentials later.

Do not introduce Kafka, a distributed workflow service, multiple live writers, a vector database, or a separate service per tier until a measured requirement justifies it.

### 5.3 Module ownership

| Module | Owns |
|---|---|
| `market_data` | Connection health, received timestamps, normalized trades/books/bars, gaps, and historical ingestion. |
| `features` | Reproducible calculations using data available at the decision time. |
| `strategies` | Pure evaluation rules and frozen model inference. |
| `portfolio` | Per-run allocations, positions, pending commitments, and net exposure. |
| `risk` | Cash eligibility, limits, stops, cooldowns, and entry rejection reasons. |
| `execution` | Durable commands, order lifecycle, priority, adapter dispatch, and uncertain outcomes. |
| `accounting` | Fills, fees, cash/asset journal, valuations, external flows, and reconciliation. |
| `research` | Experiment definitions, chronological evaluation, cost scenarios, and candidate records. |
| `ai_assistance` | Constrained research/review/explanation tools and their budgets. |
| `reporting` | Metrics and read models derived from the ledger, not a second balance calculation. |
| `operations` | Health, maintenance state, alerts, manual controls, backups, and recovery. |

The exchange is authoritative about actual fills and assets it holds. Our reconciled ledger is the authoritative application record used by strategies and reporting. Differences become visible incidents; neither source silently overwrites the other.

---

## 6. End-to-end deterministic orchestration

### 6.1 Startup sequence

1. Read the operating mode, fixed strategy package, account scope, and configuration hash.
2. In paper mode, ensure no live trading secret is mounted and no live adapter can be constructed.
3. In live mode, require separate authorization, a verified account, and an approved funding/risk profile. Missing prerequisites mean no entry capability.
4. Acquire exclusive execution ownership for the account. Do not rely only on an in-memory boolean or UI indicator.
5. Load the ledger, open reservations, order states, portfolio allocations, incident state, and persistent loss/high-water marks.
6. Reconcile outstanding or uncertain orders and actual balances before considering a new entry.
7. Load approved venue capabilities, fee assumptions, market filters, maintenance status, and data freshness limits.
8. Synchronize market subscriptions and seed each required history window. Expose warming-up and incomplete-data states in the UI.
9. Enable management of known positions under the approved recovery policy.
10. Enable new entries only when account, data, and operating checks are healthy.

A restart must not reset a drawdown, clear a loss halt, or replay old entry intentions as new trades.

### 6.2 A market-event cycle

```text
Receive event
 -> capture exchange time + local receive time + local sequence
 -> reject malformed or duplicate payloads
 -> update validated market state
 -> detect gaps, stale books, or market-status changes
 -> update only affected features
 -> process due exits / protective actions first
 -> evaluate eligible strategy entry rules at their declared cadence
 -> produce an intention, or a structured no-trade reason
 -> apply account/portfolio/cost/risk checks
 -> atomically reserve eligible cash or owned assets
 -> persist a uniquely identified execution command
 -> revalidate freshness, ownership, and limits immediately before dispatch
 -> send to the selected paper/live adapter
 -> ingest acknowledgments and executions as different event types
 -> apply fills and fees once
 -> reconcile spendable balances and release only safe reservations
 -> publish updated positions, performance, and explanations
```

Strategies do not run on every incoming message unless their definition requires it. Tier 2 can evaluate a completed bar while Tier 3 evaluates a shorter bar. Both share validated market data rather than opening duplicate feeds for each portfolio.

### 6.3 Periodic work

| Work | Proposed scheduling rule |
|---|---|
| Protective position management | Event-driven, with bounded timer checks independent of entry signals. |
| Entry evaluation | On a strategy's completed bar or explicit event condition. Never on an assumed final unfinished candle. |
| Reconciliation | On reconnect, uncertain outcomes, relevant account events, and a configurable periodic safety sweep. |
| Fee/capability refresh | At startup, by a controlled refresh schedule, and after relevant errors or notices; not before every ordinary order. |
| UI updates | Batched/rate-limited, while executions and financial events remain durably recorded. |
| Daily report | After the defined UTC reporting boundary, once balances and valuations are ready. |
| Research jobs | On explicit requests or an approved schedule, within CPU/storage/API budgets. |
| AI summaries | After deterministic reports complete, and only within a separately approved spend limit. |

Authentication signing is required for the venue's private requests, but our design does not add an unnecessary external permission lookup or LLM approval round trip before every trade. Local policy checks use verified, time-bounded account/capability state.

### 6.4 Time semantics

Store UTC event and accounting timestamps; display America/Denver time for Chris. Define daily results as 00:00–24:00 UTC and weekly results as Monday 00:00 UTC through the next Monday. Display those boundaries explicitly so a daylight-saving change does not alter the experiment.

Use a monotonic clock for durations, deadlines, and latency measurements. Wall-clock adjustments must not create duplicate bars or extend an expired order intention. Preserve both the time something happened and the time the application first could know about it.

A new reporting day is not permission to erase a persistent drawdown halt.

---

## 7. Capital isolation and portfolio ownership

### 7.1 Research comparisons

Create two counterfactual starting balances per tier: **$50 and $100**. Each run has its own cash, holdings, costs, fills, benchmark, and evaluation record. Two variants of the same tier also get separate runs, not simultaneous access to one imaginary balance.

Independent runs can reuse the same historical market observations because they represent alternative decisions. Do not add their profits together and describe the sum as the return of one funded account.

A combined-portfolio experiment is different: it starts with one total balance, explicit allocations, shared reservations, and a single account-level risk budget. It must be simulated separately.

### 7.2 Initial live operation

The initial live pilot, if separately approved, runs one selected strategy at a time. This avoids allocating a tiny stake among several strategies and reduces ambiguity about inventory ownership.

The paper tiers can continue in parallel, including a paper counterpart of the live strategy. That counterpart helps identify differences between simulated and observed execution; it does not get to overwrite the real account record.

A dedicated live account should contain only approved strategy capital and related assets. Unrelated manual trades or transfers are not silently incorporated into the algorithm. They trigger reconciliation and operator review.

### 7.3 Future multi-tier live operation

If later approved, one account-level allocator must own all shared resources. Separate virtual portfolios are accounting partitions, not legally or physically isolated exchange accounts.

Requirements include:

- Sum of tier allocations and reservations cannot exceed reconciled account resources.
- A tier may sell only inventory assigned to it, not a sibling tier's holdings.
- Each submitted order has one explicit owner. Do not aggregate/net orders across tiers in the first implementation.
- Check for crossing own resting orders across all tiers; reject or resolve conflicts before dispatch.
- No automatic transfers from a successful tier into a losing tier.
- Account-level asset and correlation exposure overrides individual tier limits.

Do not assume retail subaccounts are available. Physical account separation would require a separate venue/account capability decision.

---

## 8. Initial strategy specifications

### 8.1 Research basis and its limits

Published research motivates studying value and momentum together, business quality, and cross-asset trend following. It does not establish the returns of these proposed portfolios, their small-account implementation, or either aggressive target.[^value-momentum][^quality][^trend]

Much of the trend evidence involves long/short futures or forwards. A fully funded long-or-cash ETF version is a different strategy and must establish its own results. The crypto candidates below are hypotheses, not strategies validated by the cited equity research.

### 8.2 Shared eligibility rules

Before any entry signal is considered, the market must pass a frozen eligibility policy:

1. Available for the intended jurisdiction, account, asset type, and order capability.
2. Long-only, fully funded ownership; no prohibited product or funding mechanism.
3. Enough relevant history and acceptable data quality for every required feature.
4. Quantity increments, minimum notional, and realistic exit size compatible with the allocated balance.
5. Acceptable current spread and executable depth at the proposed size.
6. No unsupported quote asset, unresolved token identity, halt, scheduled delisting, or relevant maintenance restriction.
7. Within concentration and correlated-exposure limits.

A low nominal coin price does not make an asset cheaper to trade or more suitable. Stablecoins used as quote assets are tracked as assets with their own USD conversion and risk, not assumed to equal dollars permanently.

For the baseline, permit at most one open position per instrument per run and one unresolved entry intention for that instrument. A repeated signal does not stack another purchase onto an existing position. Deduplicate signals by strategy version, instrument, and decision event. Pyramiding and averaging down are absent unless a separately defined future experiment is explicitly approved.

Start the collector with a small candidate universe and expand based on measured data/compute costs. “Scan dozens” is an eventual coverage goal, not a requirement to trade dozens or collect full-depth books for every listed instrument.

### 8.3 Tier 1A — quality/value/momentum equities

**Purpose:** Test slower diversified stock selection against a fixed broad-equity benchmark.

**Data prerequisite:** A point-in-time eligible equity universe, actual publication times for financial data, delisted securities, corporate actions, distributions, and execution rules for the selected cash broker. Until these exist, this profile is **not ready**, rather than pretending current constituents and revised fundamentals are historical truth.

**Proposed baseline:**

- Daily prices; monthly selection/rebalance, with daily operational and risk monitoring.
- Momentum: total-return strength from approximately twelve months ago to one month ago, using a declared exchange-session calendar.
- Quality: sector-aware ranks of profitability, cash generation, and financial resilience. Ratios inappropriate for a sector are not replaced with arbitrary zeros.
- Value: sector-aware valuation ranks from explicitly defined fundamentals. Missing or economically unsuitable inputs produce exclusion or a predefined alternate metric—not an improvised estimate.
- Combine the three standardized component ranks with equal weights initially; no optimizer searches for the best historical weights in the baseline.
- Select a diversified top cohort subject to sector and position caps. Use separate entry/retention thresholds to reduce churn near the cutoff.
- Weight simply and cap positions; do not use leverage to obtain a volatility target.

**Small-account constraint:** Fifty stock positions are not assumed implementable with $50. If fractional shares, minimums, settlement, or costs prevent faithful execution, report the profile as not executable at that balance. An ETF approximation may be researched separately with its own name and benchmark; it must not inherit the stock strategy's identity or performance.

### 8.4 Tier 1B — cross-asset ETF trend

**Purpose:** Test a slow long-or-cash alternative with different exposures from stock selection.

**Proposed baseline:** A predefined set of unleveraged, eligible ETFs representing broad domestic/international equities, government bonds, gold, and other explicitly approved exposures. Exact funds and data licenses are a later broker/data decision, not selected by this document.

For each instrument, calculate three-, six-, and twelve-month total-return direction at a monthly review. A simple initial rule holds a capped allocation when at least two horizons are positive and otherwise retains that allocation in permitted cash. Any cash yield must be actually available or explicitly modeled; zero is the default when unverified.

Report Tier 1A and Tier 1B independently first. Any combined Tier 1 portfolio has a fixed, predeclared allocation and its own capital budget. A cryptocurrency trend baseline is not a substitute for this original cross-asset scope.

Most U.S. equity transactions currently settle T+1; the stock adapter must respect cash-account settlement restrictions rather than inherit crypto availability assumptions.[^finra]

### 8.5 Tier 2A — breakout continuation

**Purpose:** Test whether selected upward breakouts have sufficient continuation after costs.

**Proposed seed rules, all paper-only:**

- Evaluate completed 15-minute bars; use a completed one-hour trend filter.
- Require the latest completed one-hour close to exceed its 50-bar exponential moving average, with that average higher than three completed hourly bars earlier.
- Define the breakout reference as the maximum high of the preceding 20 completed 15-minute bars, excluding the candidate bar.
- Require candidate close above that reference and candidate volume above 1.5 times the median volume of those preceding 20 bars.
- Require the candidate move not to be excessively extended relative to a declared 14-bar average true range (ATR) rule; begin with a two-ATR extension ceiling.
- Apply spread, liquidity, fee, and exposure checks after the signal. The signal bar's close is not a guaranteed executable price.
- Enter no earlier than the first eligible market state after decision and modeled transmission latency.
- Use an initial planned exit distance of two ATR units, calculated from information available at entry; impose a 48-hour maximum holding period.
- After a favorable move of two initial risk distances, an explicitly tested trailing-exit rule may activate. Stop levels may tighten but never widen to avoid recognizing a loss.

For this seed, true range is the maximum of high minus low, absolute high minus prior close, and absolute low minus prior close. ATR uses Wilder smoothing over 14 completed bars, initialized from the first 14 true ranges. EMA uses alpha `2 / (n + 1)`, seeded by an `n`-bar simple mean. Require at least 100 completed hourly bars before Tier 2 entries; use only completed candidate bars in the ATR. The extension ceiling is candidate close minus breakout reference, divided by ATR. After a two-risk-distance favorable move, trail two current completed-bar ATR units below the highest valid executable bid observed since entry, never moving the stop downward. The re-entry cooldown is 30 minutes after the prior position closes. These definitions are research choices, not claimed optimal settings.

Bar boundaries and tie-breaking behavior must be fixed in code and tests. A missing hour of data makes the feature incomplete, not a zero-volatility market.

### 8.6 Tier 2B — pullback continuation challenger

Test separately from the breakout baseline. Reuse the hourly trend filter, then require a predefined pullback toward a moving reference and recovery above the previous completed bar's high. Define the pullback depth, recovery deadline, and invalidation level before evaluation.

Do not run both candidates on one portfolio and choose whichever trade would have won afterward. Each gets an independent run until a fixed combination rule has its own evaluation.

### 8.7 Tier 3A — short-horizon momentum

**Purpose:** Test more frequent opportunities without sacrificing cost and fill realism.

**Proposed seed rules, all paper-only:**

- Evaluate completed one-minute bars with a completed five-minute trend filter.
- Require the completed five-minute close above its 20-bar EMA, with that EMA higher than three completed five-minute bars earlier; require at least 60 completed five-minute bars of warmup.
- Require a one-minute close beyond the highest high of the preceding ten completed one-minute bars and volume above twice their median.
- Reject excessive spread, insufficient depth, stale books, and a candidate close more than 1.5 one-minute ATR units beyond the breakout reference.
- Initially use a price-capped aggressive entry, not an assumed free passive fill.
- Use a 14-bar one-minute Wilder ATR and an initial planned stop distance of 1.5 ATR. Apply the same indicator definitions as Tier 2. Initial reference risk distance is fixed at entry.
- Exit after ten minutes if the highest eligible executable bid since entry has not reached entry VWAP plus one initial risk distance. Otherwise manage the position with a one-ATR trailing stop activated after that favorable move; never widen it.
- Apply a 45-minute absolute holding limit, subject to actual exit availability.
- Apply a ten-minute cooldown in the same asset after the prior position closes.

Compute time limits from the first fill, not the original unfilled signal. Exit quantities follow actual holdings. Partial entries, unavailable exit liquidity, and delayed execution remain subject to the core order/recovery rules. A candidate missing its complete indicator, exit, or risk definitions is invalid, not eligible for best-effort interpretation.

This is not colocated high-frequency trading. Subsecond strategies would be a later experiment requiring demonstrated data and execution fidelity, not an optimization promised by using a faster programming language.

### 8.8 Tier 3B — short-horizon reversal challenger

Investigate a sharply falling price only after a precisely defined stabilization/recovery condition. One initial formulation to research is a large negative standardized short-horizon return, followed by two completed bars establishing a higher low and a recovery close, with normal spread/depth restored.

It must have a time limit, an invalidation level, and a long-only inventory cap. No averaging down, martingale progression, or “it has fallen enough” discretionary override. Freeze the standardized-return window and threshold before testing; do not let the AI choose them per event.

### 8.9 Strategy output contract

Every strategy produces an **intention**, not an order. Required fields:

| Field | Meaning |
|---|---|
| `strategy_id`, `version`, `run_id` | Exact rules and owning experiment. |
| `instrument_id`, `side`, `intent_kind` | What owned market exposure is being opened, reduced, or closed. |
| `decision_time`, `available_at`, `expires_at` | Causal timing and a finite execution opportunity. |
| `feature_snapshot_id` | Inputs that explain this decision. |
| `entry_condition`, `exit_plan`, `time_limit` | Explicit rationale and management plan. |
| `requested_exposure` | A request subject to sizing, not authority to spend. |
| `signal_strength` | A defined ranking measure; not automatically a probability or expected return. |
| `model_id` | Optional frozen model identity. |
| `reason_codes` | Machine-readable facts supporting the user-facing explanation. |

If an expected-return estimate is used in a cost gate, it must come from a documented, out-of-sample calibration. A take-profit target is not an expected return. Without an estimator, use explicit opportunity filters and test the resulting economics rather than manufacture a confidence percentage.

---

## 9. Deterministic risk and cash controls

### 9.1 Proposed paper profiles

These are deliberately different research profiles, **not approved live settings**. They define loss/exposure discipline, not guaranteed maximum losses. Actual losses can exceed a planned stop or halt threshold because of gaps, stale valuations, failures, and unavailable exits.

| Setting | Tier 1 | Tier 2 | Tier 3 |
|---|---:|---:|---:|
| Maximum gross invested exposure | 90% | 75% | 90% |
| Single-position cap | 10% stock / 25% ETF | 35% | 50% |
| Planned entry loss budget as % of equity | Weight-based; not an artificial per-trade stop | 1.5% | 2.5% |
| Sum of planned stop losses | Not applicable; use allocation/concentration limits | 3% | 5% |
| Daily loss threshold: pause new entries | 3% | 8% | 15% |
| Peak-to-trough threshold: require review | 12% | 20% | 35% |
| Maximum total daily executed notional / start-day equity | 2x | 5x | 30x |
| Minimum trade quota | None | None | None |
| Automatic capital replenishment | Never | Never | Never |

“Total executed notional” counts purchases **and** sales. Closing/reducing owned positions must remain possible after an entry turnover budget is exhausted. Display separately when emergency exits cause turnover to exceed the entry budget.

Daily loss is measured against start-of-day equity adjusted for external flows, using a consistent valuation basis; persistent drawdown is measured from the cash-flow-adjusted high-water mark. Reaching a limit pauses new entries as specified, not an assertion that further losses are impossible. An existing position above a cap because prices changed may be reduced under its policy; it does not authorize new exposure. Midnight does not clear a persistent review halt.

Position and risk caps can make an intended trade too small for the venue. The correct result is “not executable at this balance,” not silently increasing risk to meet an order minimum.

### 9.2 Sizing a fully funded purchase

Let:

- `E` = current conservatively valued portfolio equity.
- `C` = reconciled eligible cash after holds and existing reservations.
- `B` = separately retained cash buffer.
- `P_cap` = maximum permitted entry price per unit.
- `f` = conservative fee fraction when charged in the quote asset.
- `S` = planned exit trigger below entry for a long position.
- `r` = permitted planned loss fraction of equity.
- `c_unit` = modeled entry/exit costs per unit for the risk calculation.

For a quote-fee purchase:

```text
cash_quantity_limit = max(0, C - B) / (P_cap * (1 + f))
position_quantity_limit = remaining_position_notional_cap / P_cap
planned_risk_quantity_limit = (E * r) / (P_cap - S + c_unit)

quantity = round_down_to_allowed_increment(
    min(cash_quantity_limit,
        position_quantity_limit,
        planned_risk_quantity_limit,
        executable_liquidity_limit)
)
```

Validate all terms as finite and positive where required. A stop at/above a long entry, a nonfinite feature, or an unavailable fee policy rejects the intention. For weight-based Tier 1 allocations, omit the artificial stop-distance calculation and apply the declared allocation rules instead.

This formula bounds **planned** risk only. It does not guarantee an exit at `S`. Order cash safety must additionally use actual order semantics and conservative price/fee reservation. A fee charged in the base asset or a third asset requires that asset's own accounting and availability checks; do not force it into this simplified quote-fee formula.

### 9.3 Entry-check order

Evaluate inexpensive hard exclusions first, then calculate size:

1. Correct mode, authorized profile, account ownership, and eligible funding.
2. Account/venue health, symbol capability, complete/fresh data.
3. Intention not expired, strategy not paused, no unresolved conflicting command.
4. Asset ownership/cash, fees, minimums, increments, and price limits.
5. Current and pending exposure, correlation/concentration, loss and turnover budgets.
6. Executable liquidity and strategy-specific cost/opportunity criteria.
7. Atomic reservation and durable command creation.
8. Dispatch-time revalidation against the latest relevant account and market state.

Return a concrete rejection reason, such as `FUNDING_NOT_CLEARED`, `ORDER_BELOW_MINIMUM`, `SPREAD_TOO_WIDE`, or `ACCOUNT_RECONCILIATION_REQUIRED`. Avoid a generic “AI confidence too low” explanation.

### 9.4 Exit rules are different from entry rules

A necessary risk-reducing exit should not be rejected because its estimated profit is negative, its signal score is low, or the entry fee/turnover budget is exhausted. It still must obey ownership, quantity, market capability, and authorization rules.

A pause blocks new exposure but normally keeps existing position management active. An account uncertainty incident may require a stricter reconciliation-only state. A data failure must not cause blindly priced liquidation.

Native protective orders may be used only after their exact supported behavior and reservation interactions are tested. A software stop is not sufficient protection during an application outage, and a venue order is not a guarantee during exchange failure.

---

## 10. Order lifecycle and exactly-once accounting

### 10.1 One execution coordinator

Only one active account coordinator may dispatch orders. Persist ownership and stop dispatch immediately when ownership is lost. In the initial single-host design, do not implement automatic standby takeover: an operator must establish that the old writer is stopped and reconcile the account first.

A database lease alone cannot prevent an already-running, partitioned process from calling an external exchange. Deployment and credential boundaries must make concurrent live writers difficult, and recovery must not assume perfect distributed fencing.

### 10.2 Durable intent before network side effects

In one database transaction, record the approved command and reserve its resources. Commit before the external call. Give each command a unique, never-reused client identifier that meets the venue's verified constraints.

This creates an auditable instruction even if the process crashes after sending it. It does **not** create an exactly-once exchange API. Treat external effects as potentially uncertain and financial event application as idempotent.

### 10.3 Internal order states

```text
PROPOSED -> REJECTED
        -> RESERVED -> DISPATCHING -> ACKNOWLEDGED / OPEN
                                  -> SUBMISSION_UNKNOWN

OPEN -> PARTIALLY_FILLED -> FILLED
     -> CANCEL_PENDING -> CANCELED
                       -> CANCEL_UNKNOWN
     -> EXPIRED / REJECTED

SUBMISSION_UNKNOWN or CANCEL_UNKNOWN -> reconciliation
  -> confirmed actual state, with any newly discovered fills applied
```

These are internal states; the adapter maps actual venue statuses into them. A canceled order may retain earlier fills. A failed cancellation may leave the order open. “Order accepted” does not mean “position acquired.”

### 10.4 An uncertain submission

If a request times out after transmission:

1. Mark its outcome unknown and keep the relevant resources reserved.
2. Suspend conflicting entries; do not immediately send a replacement.
3. Check the original order identity, account events, orders, and executions using a bounded recovery procedure.
4. Treat one “not found” response as insufficient when evidence may be delayed.
5. Escalate unresolved ambiguity rather than release funds by timeout alone.
6. If a new attempt is eventually allowed, document why the original cannot remain active and use a new command identity linked to that resolution.

Do not depend on client-order identifiers being globally idempotent forever. Never intentionally recycle one after a fill or cancellation.

### 10.5 Fill processing

Deduplicate using a verified venue/account/symbol/execution identity. In one transaction, record the fill, fee in its actual asset, journal entries, reservation adjustment, and resulting portfolio state.

Duplicate transport messages should not duplicate a fee or profit. Late fills must still be applied after a cancellation or restart. A disagreement among order events and balance evidence becomes an incident, not a guessed balancing entry.

### 10.6 Protective exits and cancellations

Do not submit multiple independent full-position sell orders and assume they share one reservation safely. Use a verified linked-order capability or explicitly coordinate cancellation/remaining quantity under one owner.

When a protective order is absent or canceled during maintenance, display the uncovered exposure. Do not blindly recreate it at an old price before checking actual holdings and current conditions.

A pause action must not casually cancel protective exits. A “cancel all” administrative action must identify whether it includes exits and require the appropriate confirmation.

---

## 11. Accounting, valuation, and financial truth

### 11.1 Ledger design

Use an append-only financial journal with balanced entries **per asset**, backed by fill and funding evidence. Do not add quantities of BTC and USD together and call the result a balanced journal. Each traded asset has asset-unit entries and corresponding clearing/counterparty entries; cost basis and reporting-currency valuations are separate records.

Track at least:

| Record | Required content |
|---|---|
| Account and funding | Venue account, authorized capital, approved funding evidence, pending/reversed flows, holds. |
| Portfolio/run | Tier, starting balance, strategy/config version, benchmark, ownership allocation. |
| Order/command | Unique identity, owner, side, quantity, prices, status, reservations, times, evidence. |
| Fill | Execution identity, quantity, price, fee amount/asset, role, order link, actual/simulated designation. |
| Journal entry | Asset, signed amount, event identity, counter-entry group, recorded/effective times. |
| Position and lot | Owned quantity, allocated quantity, cost basis, realized/unrealized results. |
| Valuation | Price source, freshness, depth assumptions, quote-to-USD conversion, uncertainty. |
| External adjustment | Deposit, withdrawal, reward, manual trade, reversal, correction, reason and evidence. |

Corrections are new attributable entries, not edits that erase the original evidence. Current balances are calculated/read-model outputs from this journal and reservations—not a second financial authority.

### 11.2 Available balance

Compute a conservative bound from both sources:

```text
application_remaining = approved/reconciled owned amount
                        - all active application commitments
                        - quarantined or otherwise ineligible amount

usable_now = min(application_remaining, venue_reported_free_amount)
             - applicable additional safety reserve
```

Define each reservation exactly once. Do not subtract a venue lock twice merely because it is also represented in our order record; the two values are independently calculated bounds, not an instruction to add all locks indiscriminately.

A pending sale's expected proceeds are not spendable. Reuse becomes possible only after fills, fees, and availability have been reconciled. This is how we support rapid crypto turnover without inventing credit or a settlement schedule.

### 11.3 Equity and profit

Report both:

- **Standard marked equity:** Cash plus holdings at the declared valuation method, with freshness labels.
- **Estimated liquidation equity:** Cash plus conservatively modeled sale proceeds from owned positions, including exit costs and USD conversion where applicable.

Use an appropriate conservative equity for risk checks. If a position cannot be valued reliably, mark the metric uncertain and halt new exposure; do not value it at its last favorable price or zero without an explicit impairment policy.

Distinguish trading profit, unrealized changes, funding flows, rewards, commissions, and operating costs. A deposit is not profit. A Soft-Staking credit, if present, is not evidence that a signal worked.

### 11.4 Decimal precision

Use decimal values from strings or validated integer asset units for money, quantities, fees, and order constraints. Binary floating-point analytics may be acceptable inside research indicators, but must cross a validated conversion boundary before creating financial quantities. Python's `decimal` module supports explicit precision and rounding suitable for this boundary.[^python-decimal]

The UI may display two decimal places for dollars, but storage and calculations must retain enough precision to account for sub-cent fees. Validate fee rounding against venue evidence rather than always rounding in our favor.

### 11.5 Tax records

Maintain complete acquisitions, disposals, fees, asset-to-asset exchanges, rewards, and USD valuations with source timestamps. Export records rather than claim an unaudited tax liability. U.S. digital-asset transactions can create reporting obligations, including disposals and rewards; cash withdrawal is not the sole relevant event.[^irs]

Cost-basis methods and any tax reserve are explicit account policies to review separately. Trading permissions must not depend on the bot preparing a definitive tax return.

---

## 12. Paper execution that does not manufacture profits

### 12.1 One core, two execution adapters

Replay, forward paper, and live modes use the same strategy, sizing, order-management, and accounting logic. Only time/data delivery and execution differ. A fast approximate backtester can screen ideas, but finalists must pass the event-driven core before their results are eligible for review.

A venue's sandbox is not automatically an economic simulator. For example, Alpaca explicitly documents omissions including market impact, latency slippage, queue position, and dividends.[^alpaca-paper] We must model the effects relevant to our own strategy rather than import a displayed paper balance as proof.

### 12.2 Causal timing

At a decision time, the strategy sees only information available to it by then. Historical exchange time alone is not sufficient when publication, ingestion, or computation happened later.

For an order, model:

```text
observable information
 -> decision and computation
 -> dispatch delay
 -> hypothetical venue arrival
 -> executable market state and order semantics
 -> fill or non-fill
 -> delayed execution report
 -> reconciled availability
```

Start with explicit latency sensitivity scenarios such as 250 ms, 1,000 ms, and 3,000 ms. They are synthetic stress assumptions, not measured Binance.US latency. Replace/calibrate them with collected evidence where possible and continue to report adverse scenarios.

### 12.3 Marketable and price-capped orders

Walk the available book at modeled arrival time, applying the order's price cap and finite liquidity. If only part of the quantity is executable, apply the actual tested order semantics: partial fill, cancellation of a remainder, or no fill. Do not complete the remainder at an invented price.

Maintain hypothetical consumed liquidity within each run so concurrent simulated orders do not repeatedly spend the same displayed quantity. Reject or conservatively adjust cases where our modeled participation is too large for a non-impact replay assumption.

Independent counterfactual experiments do not share this hypothetical consumption, but a combined-portfolio run does.

### 12.4 Passive orders

A candle touching the limit price does not prove our order filled. Without defensible queue evidence, passive results are exploratory. Model queue-ahead uncertainty, relevant subsequent trades, cancellation latency, missed fills, and adverse price moves after fills.

Report pessimistic and alternative queue assumptions. Never promote a strategy whose profit exists only when every touched maker order receives a free, immediate fill. Baseline aggressive-order results provide a useful, separately labeled comparison.

### 12.5 Bars, stops, and gaps

When using only bars and both stop and target fall inside the same bar, the intrabar order is unknown. Use a declared conservative resolution or mark the trade indeterminate; never always choose the profitable sequence.

A gap through a stop executes at an actually available subsequent price under the execution model, not magically at the trigger. A price-capped exit may remain unfilled. Record the exposure and failed exit, not a fabricated loss cap.

### 12.6 Cost accounting

Charge actual applicable simulated commission per fill and in the proper asset. Spread, book depth, and delay effects already represented in fill prices must not be subtracted a second time as a generic slippage fee.

Report estimated execution shortfall separately from charged commissions. Include startup conversions, residual dust, and any necessary quote-asset conversion in the economic comparison. Funding/withdrawal scenarios and operating costs should be visible even when they are outside the trading ledger.

### 12.7 Feed failures and restarts

Missing market data is not a flat market. A stalled collector marks a data gap and blocks new entries. Do not fabricate a complete forward track record by later backfilling that gap and pretending the bot saw the data in real time.

Backfilled data may support a separately labeled reconstruction. Restore a forward run from its durable ledger, retaining the interruption and any uncertainty about position valuation or missed exits.

---

## 13. Research, evaluation, and promotion

### 13.1 Separate software correctness from economic evidence

A correctly implemented strategy can lose money. A profitable backtest can contain software defects. Maintain two separate reports:

- **Engineering qualification:** Accounting, causality, permissions, execution, recovery, and UI work as specified.
- **Economic evaluation:** The frozen strategy's after-cost results, risks, uncertainty, benchmark comparison, and sensitivity to implementation assumptions.

Neither report substitutes for the other. A successful target week does not override an unresolved balance discrepancy.

### 13.2 Experiment registration

Before each evaluation, record the hypothesis, expected mechanism, strategy/configuration hash, data sources, exact universe selection, benchmark, risk profile, fee policy, latency/fill assumptions, sample periods, planned comparisons, and rejection criteria.

Keep a record of every attempted variation, including unsuccessful and abandoned ones. A new model, feature, universe rule, stop rule, or risk setting creates a new candidate. It does not retroactively improve the old candidate's record.

This addresses the selection problem documented in research on backtest overfitting: even ordinary holdout techniques can be unreliable when many investment strategies are tried and only the winners are retained.[^pbo]

### 13.3 Historical evaluation

Use chronological training/development, validation, and final held-out evaluation. Do not randomly split overlapping time-series observations into train and test sets.

For labels or positions that span time boundaries, remove overlapping training observations and use an appropriate separation interval. Fit scalers, feature selection, model parameters, and thresholds only on the training information available at that stage. A final holdout becomes development data once its results influence further design; use subsequent fresh data for the next real evaluation.

Test multiple market conditions and start dates. Include failed/delisted assets where applicable, correct historical listing eligibility, and the financial information actually available at the time. Avoid selecting today's successful assets for the entire historical period.

Fees and market rules also have effective dates. A backtest applying today's low commissions to older prices is a **current-cost counterfactual**, not proof those historical profits were attainable then. Label it separately from a historical-cost reconstruction. Actual venue fee/filter changes during a forward run are external events to record, not reasons to reset the record or rewrite past costs.

Predeclare a small parameter neighborhood rather than search thousands of combinations until a chart looks good. A stable neighborhood is more credible than a single exceptional setting, but it is still evidence to evaluate, not proof of future returns.

### 13.4 Forward evaluation

Freeze the strategy and run it on subsequently arriving data. Record the actual availability time of each observation, model feature, and decision. No retroactive trades; no choosing new thresholds while calling the record unchanged.

A provisional observation plan could collect at least 90 calendar days for Tiers 2 and 3, plus several hundred completed position episodes where natural activity permits. **Neither duration nor count is a pass condition.** Correlated trades do not become independent evidence because they are numerous. A low-activity strategy must not force trades to meet a sample quota.

Tier 1 cannot establish a multi-year outperformance claim from a 90-day operational trial. Its short forward trial verifies operation; longer historical and future evidence address the economic claim.

### 13.5 Benchmarks

| Profile | Required comparisons |
|---|---|
| Tier 1A | Fixed eligible broad-equity total-return benchmark, with a documented cash component where needed. |
| Tier 1B | Fixed passive allocation to the selected eligible exposures and an explicitly defined cash baseline. |
| Tier 2 / Tier 3 | Cash in the same quote asset; predetermined BTC or market-basket exposure if eligible; results also valued in USD. |
| Any combined portfolio | A fixed passive mix using the same total capital and external cash-flow schedule. |

Benchmark constituents and rules are chosen before the evaluation, not after seeing which makes the strategy look best. Fees, conversions, distributions, and actual eligible cash yields must be treated consistently.

### 13.6 Metrics

Calculate from the ledger, not LLM arithmetic:

- Start/end equity; net dollar profit; total return and time-weighted return when external flows exist.
- Daily and weekly return distributions, including zero-trade periods and losses.
- Fraction of completed periods reaching 10% and 20%, with sample counts and uncertainty.
- Maximum drawdown, worst day/week, recovery time, and time under water.
- Gross trading result, commissions, execution shortfall, operating costs, and final economic result shown separately.
- Turnover, average exposure, concentration, trade duration, fill/rejection rates, and data-gap exposure.
- Results after removing the largest winning trade/day, with removal treated as a sensitivity analysis—not an edited official record.
- Performance across predeclared regimes and comparable parameter/latency/cost scenarios.

Primary daily/weekly target attainment uses whole-account results after trading costs and a declared allocation of ongoing operating expenses, before personal income taxes. Show the raw trading-only result, research/development spending, and any optional tax scenario separately. Do not hide a cost category behind an unexplained “net” label.

Use block-based resampling or another justified method for uncertainty where observations are dependent; disclose its assumptions. Do not treat 1,000 overlapping trades as 1,000 independent trials. Do not turn a few days of returns into a prominently advertised annualized return.

### 13.7 Promotion states

```text
DRAFT HYPOTHESIS
 -> ENGINEERING-VALIDATED
 -> HISTORICAL SCREENING
 -> FROZEN FORWARD PAPER
 -> EVIDENCE REVIEW
 -> ELIGIBLE FOR A LIVE-PILOT DECISION
 -> LIVE PILOT, only with explicit authorization
```

“Eligible for a decision” does not mean automatically approved. A candidate may also be rejected, retired, or returned to research. Material changes restart the applicable evaluation; accounting bug fixes require a visible explanation of which prior results are invalidated and how they were reconstructed.

### 13.8 Live-pilot criteria

Require all of the following before presenting an enable-live action:

1. Venue/account/funding restrictions and permissions meet the approved cash-only profile.
2. No unresolved critical safety, causality, balance, or execution defects.
3. An interpretable forward record with appropriate costs and no hidden resets.
4. Sufficient evidence to justify the stated experiment, with uncertainty and adverse scenarios disclosed.
5. A deliberately limited capital amount and separately chosen live risk limits.
6. An approved deployment, recovery procedure, market universe, and maximum operating spend.
7. Explicit operator authorization tied to the exact account, strategy version, limits, and environment.

No universal Sharpe ratio, win rate, trade count, or profit threshold guarantees success. Live operation remains a measurement of actual execution and behavior, not a promise that the daily/weekly target is proven.

---

## 14. AI roles and controlled learning

### 14.1 AI Researcher

**Inputs:** Approved public sources, frozen datasets, existing experiment summaries, strategy contracts, and compute/cost budgets.

**Allowed tools, proposed application interfaces:**

```text
list_approved_datasets()
read_dataset_manifest(dataset_id)
read_strategy_definition(strategy_id, version)
read_experiment_summary(run_id)
submit_candidate_proposal(structured_proposal)
run_registered_experiment(candidate_id, permitted_configuration)
```

The experiment tool accepts only registered code and validated parameters inside a resource-limited worker. It is not unrestricted shell execution or permission to install arbitrary code in the trading runtime. New source code belongs in a development branch with review and tests.

**Output:** A hypothesis card, economic rationale, feature/data requirements, expected failure modes, test plan, and evidence. The researcher must describe why the hypothesis could be wrong, not merely narrate a positive result.

### 14.2 AI Reviewer

Receive the candidate definition, full experiment roster, deterministic reports, and approved data samples. Challenge missing costs, leakage, parameter sensitivity, untradeable size, concentration, benchmark choice, and dependence on optimistic fills.

The reviewer may request bounded additional tests. Its recommendation is advisory. It cannot label an unrun test passed, certify a balance, modify the winner selection, or grant live permission.

The same provider may perform both roles initially, but their outputs are not independent statistical replication. Independent verification comes from reproducible calculations, separate evaluation data, tests, and observed execution.

### 14.3 AI Operations Analyst

Read structured daily/weekly metrics and incidents and produce explanations such as:

> “Tier 3 generated $1.20 of gross trading gain, paid $0.46 in commissions, and ended $0.74 ahead before allocated operating costs. Most rejected entries were below the liquidity requirement. The daily target was not reached; no risk limit changed.”

This is illustrative wording, not a reported result. Every numeric statement must bind to a computed metric or fail validation. When data is incomplete, the analyst says which part is unavailable instead of filling gaps with a plausible explanation.

Safe questions include “Why did we skip this trade?”, “How much did costs reduce the result?”, and “Which assumptions does this result depend on?” Answers should link to the relevant records in the application.

### 14.4 Optional AI-derived data and statistical models

Later candidates may include structured public-document changes, sentiment, or industry indicators. Every extracted observation requires source identity, publication time, first-seen time, extraction completion time, schema version, model/prompt version, and validation outcome.

Historical LLM experiments have an additional risk: model training may overlap the evaluated history or company knowledge may affect text interpretation. Published work specifically examines these effects.[^llm-bias] Therefore, treat newly arriving documents evaluated prospectively by a frozen model as particularly important evidence. An LLM cannot be assumed to forget the future merely because the prompt says “pretend it is 2020.”

Statistical models must beat a simple baseline outside their training/development period after costs. Start with interpretable models and explicit feature checks; add complexity only for measured incremental benefit. Missing or expired model features follow a predeclared fallback—usually no new entry—not an ad hoc call to another model.

### 14.5 Learning without self-modifying live trading

```text
Observed performance / incident
 -> deterministic diagnostics
 -> optional AI hypothesis
 -> candidate code/configuration in research
 -> bounded tests and historical evaluation
 -> frozen forward run
 -> human review
 -> explicitly selected next version
```

Permitted adaptation includes a volatility-based size calculation whose formula and bounds were fixed before the run. Not permitted: a model changing the stop, enlarging leverage, switching strategies after a bad hour, or optimizing against the current evaluation period while claiming an unchanged record.

### 14.6 AI cost and security limits

AI is optional and disabled by default until a budget is approved. Set request, token, runtime, and daily-dollar ceilings, with bounded retries and no agent-to-agent recursion. Cache repeated source analysis and summarize structured metrics rather than send raw tick histories.

A model outage or budget exhaustion disables assistance, not deterministic risk management. No AI role receives live keys, bank details, withdrawal tools, production shell access, or permission to edit account state. External documents are untrusted inputs; least-privilege tool boundaries and validation are more important than asking a model to follow a safety prompt.[^owasp]

---

## 15. Operating states, failures, and recovery

### 15.1 Useful operator states

Use a small set of understandable runtime states, separate from strategy research status:

| State | New entries | Existing positions | UI explanation |
|---|---|---|---|
| Warming up | Blocked | Reconcile/manage under recovery policy | Waiting for complete data and account confirmation. |
| Running | Allowed within policy | Managed normally | Current mode, profile, and data health visible. |
| Entries paused | Blocked | Management remains active | Operator request, loss limit, or maintenance preparation. |
| Data degraded | Blocked for affected scope | Only actions supported by validated data/approved protective orders | Explicit stale feed or missing data warning. |
| Reconciliation required | Blocked for affected account | No conflicting commands; recover actual state | Order or balance outcome unresolved. |
| Manual halt | Blocked | Action depends on specified halt type | Persistent state requiring authorized resume. |
| Stopped | No runtime dispatch | Venue orders may still exist | Clear warning: stopping the process does not close positions. |

A symbol-specific data issue need not stop an unrelated healthy paper portfolio. A shared account-balance discrepancy must stop new exposure across that account.

### 15.2 Three different stop controls

**Pause new entries:** Safest routine control. Stop opening exposure and cancel outstanding entry orders through the normal coordinator while preserving position management and verified protective exits.

**Cancel selected orders:** Explicitly distinguish entry orders from protective exits. Confirm any action that removes protection from owned positions.

**Attempt to flatten:** A separate, confirmed action to liquidate owned positions under defined execution constraints. Show that completion is not guaranteed, may incur losses/costs, and may leave dust or unavailable assets. Do not label a flatten request “all funds safe.”

No AI role may initiate these actions through a conversational tool in the first release. Deterministic safety policies may automatically pause entries under preapproved conditions.

### 15.3 Failure matrix

| Failure | Required response |
|---|---|
| Market stream stale or sequence gap | Invalidate affected book/features; block entries; resynchronize. Do not trade on a cached favorable quote. |
| Private account stream lost | Reconcile orders and balances using supported reads; restrict new entries until continuity is established. |
| Order submission timeout | Preserve reservation; mark unknown; query/reconcile rather than resubmit. |
| Cancel timeout | Assume the order may still execute; do not reuse funds or place a conflicting exit. |
| Rate limit / temporary server failure | Respect retry guidance, back off, prioritize account recovery and exits, suppress lower-priority research. |
| Database unavailable | Stop new side effects; preserve already accepted venue protections; alert and recover. Do not run an unlogged trading mode. |
| Process crash/restart | Reacquire exclusive ownership, restore persistent state, reconcile before entry. |
| Disk full / recorder backlog | Stop new research/entries as appropriate, retain financial events, and mark market-data gaps. No silent evidence deletion. |
| Manual external trade or unexpected transfer | Record evidence, quarantine ambiguous allocation, pause affected live account for review. |
| Fee/filter change | Stop affected entry eligibility until recalculated; manage existing holdings under the new verified constraints. |
| Quote-asset valuation disruption | Mark USD results uncertain, restrict new exposure, and require the predeclared response policy. |
| Scheduled venue maintenance | Warn, stop entries before the configured boundary, reconcile after service returns. |
| AI outage or prompt-injection attempt | Disable/contain that assistance path; trading decisions do not depend on it. |

### 15.4 Reconciliation procedure

Compare local open orders, executions, balances, and fees with venue evidence using overlapping recovery windows and deduplication. Apply confirmed missing fills exactly once. Detect unknown orders, manual activity, fee mismatches, and inconsistent allocations.

A discrepancy may be an exchange update delay rather than fraud or a code defect. Keep the evidence and investigate. Do not create a synthetic profitable adjustment, ignore the difference because it is small, or repeatedly oscillate balances between sources.

### 15.5 Recovery controls

Resume only when the cause is understood or the documented automated recovery criteria have genuinely passed. Persist manual halts across deployments. Routine bounded feed recovery may resume an affected paper strategy automatically if its predeclared policy allows; a critical balance discrepancy or live risk-profile change requires human review.

Maintain encrypted backups and demonstrate restoration into an isolated environment. Restoring a database must never start a second live trading process. No automatic live failover in the initial release.

---

## 16. Security, authorization, and abuse prevention

### 16.1 Paper/live separation

Paper and live must have separate environments, databases or strictly isolated account namespaces, secrets, and deployment controls. The first paper build should not mount live keys or instantiate a live adapter at all.

A UI toggle or environment variable alone is not sufficient live authorization. A future enable-live action must bind the selected account, strategy/config hash, capital cap, risk limits, allowed assets, and deployment identity. Material expansion invalidates that authorization.

### 16.2 Least-privilege permissions

- Trading keys belong only to the executor's secret store, never source files, browser storage, URLs, logs, or LLM requests.
- Verify actual API scopes. Disable withdrawal permissions and apply trusted-IP restrictions where supported.[^bn-keys]
- Keep account login protection and secret rotation under operator control.
- The dashboard requires authentication; all reads and mutations are scoped server-side to the proper account and run.
- Browser clients cannot override server-side prices, balances, profile permissions, or available capital.
- Use explicit server-side command validation, request forgery protection where applicable, and sanitized rendering of imported text.

Disabling withdrawals does not make a stolen trading key harmless: damaging trades are still possible. Incident procedures must include revocation and reconciliation.

### 16.3 Research containment

Research jobs run without live secrets, limited filesystem access, bounded CPU/memory/storage, and restricted network access. Untrusted datasets, documents, and generated code are not executed inside the live process. Dependency updates pass tests and review; generated code cannot deploy itself.

Prompt-injection tests must verify that malicious source text cannot change tool permissions, expose secrets, install code, alter risk, or submit an order. A second LLM reviewer is not a substitute for those deterministic boundaries.[^owasp]

### 16.4 Trading conduct

No wash trading, self-trading to manufacture volume, spoofing, manipulative order placement, coordinated pumping, or attempts to evade exchange limits. High volume means bona fide eligible trades, not gaming a fee tier or displaying fake activity.

All rate limits are respected across the application. Do not rotate accounts, IP addresses, or credentials to circumvent them. The application uses only public or appropriately authorized data and funds belonging to the approved account owner.

---

## 17. Data model, storage, and reproducibility

### 17.1 Minimum operational entities

Start with a compact relational model rather than a new platform of overlapping authorities:

```text
venue_accounts / funding_events
instruments / capability_snapshots / fee_snapshots
strategy_versions / experiment_runs / portfolio_allocations
market_data_manifests / feature_snapshots
execution_commands / orders / fills / reservations
journal_transactions / journal_lines / position_lots
valuation_snapshots / performance_periods
incidents / operator_actions / authorization_records
research_jobs / ai_artifacts
```

Separate tables only when identity, constraints, access, or query needs justify them. They are not separate microservices.

### 17.2 Required database constraints

- Unique financial-event and execution identities at the appropriate account/symbol scope.
- Unique, never-reused execution command/client-order identity.
- Foreign keys connecting fills, orders, runs, snapshots, and journal transactions.
- Explicit environment/account/run scope on financial reads and writes.
- Atomic capital reservation and financial application; no read-modify-write race over free cash.
- Nonnegative owned/available quantities where the model requires them, with violations surfaced as incidents rather than clipped to zero.
- Explicit enum/schema validation for operating mode and allowed order capabilities.

Use short transactions and consistent lock ordering. PostgreSQL row-level locking can support serialized updates to account/portfolio resources; implement and test the actual concurrency behavior rather than assume a transaction alone prevents overspending.[^postgres]

### 17.3 Market storage

Keep high-volume normalized trades and depth events in partitioned, compressed files suitable for replay, with a database manifest for venue, symbol, time range, sequence range, completeness, and integrity hash. Do not put every market tick into the financial journal or into an LLM/vector store.

Retain full decision-time evidence for evaluation runs, including data required to reproduce fills under the chosen simulator. A checksum without the original data is not enough to reproduce a result.

Use an explicit retention plan. A proposed operational starting point is a rolling raw-capture window with selected evaluation datasets pinned until their evidence is no longer needed. Measure actual disk usage before setting final durations; do not promise indefinite free full-market depth storage.

Never delete financial records merely because market ticks age out. Confirm tax and account-record retention requirements separately before implementing deletion policies.

### 17.4 What to record for a strategy decision

Preserve the strategy/code/config hash, feature snapshot, data availability cutoff, model version if any, reason codes, risk result, fee/capability snapshot identities, and resulting command or rejection.

This is enough to answer “What did we know, what rule fired, why was the size chosen, and what actually happened?” Do not add unrelated revision systems or require an operator to navigate internal IDs for routine use.

### 17.5 Efficiency controls

Use incremental features, bounded queues, finite in-memory windows, batched writes for market data, and indexed account/time/order queries. Financial events require durable handling and must not be silently dropped to keep a chart smooth.

When overloaded, preserve the order/account path, reduce optional subscriptions/research, invalidate incomplete books, and pause affected entries. Do not allow a slow UI subscriber or research report to create an unbounded queue in the execution runtime.

---

## 18. Proposed implementation stack and repository layout

### 18.1 Technology choices

These are implementation proposals, not dependencies already installed in a project. Pin supported versions and verify licenses/security at implementation time; do not copy a stale version list from this document.

| Layer | Initial choice | Reason and boundary |
|---|---|---|
| Runtime/research | Python, typed domain models, asynchronous network I/O | One language for strategy research and execution logic; profile before adding native-code optimization. |
| Money/quantity math | Decimal or validated scaled integers | Exact financial boundaries; no binary-float balances. |
| Application API | FastAPI or equivalent small typed Python service | Reuse domain validation; keep exchange execution out of request handlers. |
| Operational database | PostgreSQL | Transactions, constraints, account-scoped queries, and durable records. |
| Historical storage | Partitioned Parquet; DuckDB for local analytical queries | Keep bulk market data out of transactional order processing. |
| Dashboard | TypeScript/React | Familiar, testable UI with explicit paper/live modes. Reuse design experience, not True to Plan's databases or business modules. |
| Deployment | Containerized long-running process on a controlled host; Compose for local development | Stable runtime and simple recovery. No serverless request handler as the trading engine. |
| Tests | Unit/property tests, database integration tests, captured-event replay, browser workflow tests | Prove financial invariants and normal operator behavior. |
| AI integration | Provider-neutral optional adapter | No dependency on one model for correctness, safety, or continued execution. |

A bounded asynchronous queue is an available Python primitive, but the design must specify behavior at capacity; a queue alone is not a durability or correctness guarantee.[^python-queues]

### 18.2 Suggested code map

```text
trading-research-platform/
  AGENTS.md
  README.md
  docs/
    FOUNDATION.md
    decisions/
    runbooks/
  apps/
    api/
    web/
  src/trading/
    domain/
    market_data/
    features/
    strategies/
      systematic_equity/
      systematic_etf_trend/
      momentum_swing/
      momentum_intraday/
      reversal_challenger/
    portfolio/
    risk/
    execution/
      coordinator/
      paper/
      venues/binance_us/
    accounting/
    research/
    ai_assistance/
    reporting/
    operations/
  configs/
    paper/
    live_template_disabled/
  tests/
    unit/
    invariants/
    integration/
    replay/
    security/
    browser/
  scripts/
  migrations/
  pyproject.toml
  compose.yaml
```

This is a proposed layout, not a claim that a repository or these files exist. The first live namespace should contain no executable trading implementation until that phase is separately authorized.

### 18.3 Cost discipline

Start locally with public data and paper execution where possible. Measure CPU, memory, network, storage, and database growth before choosing paid hosting or additional feeds. Keep the trading runtime separate from expensive backtests and AI jobs.

Maintain a single actual platform expense ledger and separately report the cost of operating each hypothetical strategy alone. Do not make a strategy appear economic by dividing unavoidable costs among dozens of paper experiments that will never be funded. Conversely, do not multiply one actual hosting bill by six and call that actual spending.

Recurring runtime costs, research/AI costs, and one-time development effort are distinct. Set spend limits before enabling paid services; exceeding a limit stops optional work rather than charging automatically beyond the approved budget.

A $10 monthly service against a $100 stake represents a 10% monthly cost before trading. This is arithmetic illustrating why infrastructure expense must be visible, not a quoted hosting price.

---

## 19. Operator experience and dashboard requirements

### 19.1 Overview

The normal landing page answers:

**Which mode is running? How much capital is exposed? What did we make or lose after costs? Why did trades happen? Is anything unsafe or incomplete? What action is needed?**

Show a permanent, unmistakable **PAPER** or **LIVE** indicator. Do not use only color to distinguish modes. Each tier card shows its objective, actual measured result, benchmark, open exposure, largest loss, cost total, data health, and operating state.

A target is labeled **research target**, never projected income. Tier 1 is identified as comparatively conservative, not insured or risk-free.

### 19.2 Core screens

| Screen | Required content and actions |
|---|---|
| Overview | Tier comparison, net results, capital in use, current operating mode, unresolved incidents. |
| Markets | Eligible/rejected symbols, spread/depth/freshness, coverage, and why a market is excluded. |
| Positions/orders | Owned quantity, entry cost, current valuation, exit plan, pending commands, and confirmed protection state. |
| Trade detail | Decision inputs, exact rule, sizing, expected versus actual execution, fees, and resulting balance. |
| Research lab | Candidate definition, frozen parameters, dataset coverage, all experiments including failures, and version comparison. |
| Performance | Daily/weekly distributions, benchmarks, drawdowns, cost breakdown, and sample limitations. |
| Operations | Connectivity, reconciliation, funding eligibility, maintenance, alerts, pause/resume controls. |
| Configuration | Edit a draft profile; show the change impact; never silently mutate a running evaluation. |
| Reports/export | Download trades, financial records, experiment reports, and the assumptions underlying them. |

### 19.3 Useful explanations

Prefer:

> “No entry: the minimum tradable order would exceed this portfolio's risk budget.”

> “Entries paused: we sent an order but have not yet confirmed whether it filled. Its cash remains reserved.”

> “This week's account gain is 2.1% after commissions. The 10–20% research target was not reached.”

These are examples, not actual results. Avoid exposing internal hashes, event sequences, or raw exchange errors as the primary explanation. Provide diagnostic detail behind an expandable view.

### 19.4 Critical interaction rules

- Editing parameters creates a draft/new version and shows that previous results do not transfer to it.
- A halted strategy is not silently re-enabled by restarting the app or refreshing the page.
- Disable controls with a specific reason and recovery action, not an unexplained gray button.
- Show incomplete data and uncertain valuation directly on affected metrics.
- A report can load even if the AI summary is unavailable; deterministic metrics are primary.
- Provide a filtered event history for an incident without requiring the operator to inspect database rows.
- Confirmation is required for meaningful risk changes and live authorization, not every routine simulated trade.

---

## 20. Configuration example and validation rules

This YAML is a **design example**, not a runnable trading configuration or an authorization. Numeric strategy/risk settings are paper-only. The implementation must introduce a validated schema before accepting it.

```yaml
schema_version: 1
project: automated-trading-research-platform
mode: paper
jurisdiction: US-CO
reporting_currency: USD
display_timezone: America/Denver
reporting_timezone: UTC

live:
  supported_in_initial_release: false
  armed: false
  authorized_account_id: null
  authorized_total_capital_usd: null
  authorized_strategy_version: null
  authorized_risk_profile: null
  authorization_record_id: null

safety:
  allow_margin: false
  allow_shorting: false
  allow_derivatives: false
  allow_leveraged_products: false
  allow_provisional_funding: false
  allow_automatic_deposits: false
  allow_withdrawals: false
  allow_automatic_topups: false
  allow_ai_trading_tools: false
  allow_target_driven_risk_increases: false
  require_exclusive_account_executor: true
  require_reconciliation_before_entries: true
  preserve_halts_on_restart: true

venue:
  research_candidate: binance_us
  live_selection_finalized: false
  quote_asset: null  # Select after comparing markets and USD conversion costs.
  approved_symbols: []  # Empty means no strategy entries, not all symbols.
  discover_and_validate_market_filters: true
  verify_account_specific_restrictions_before_live: true
  public_fee_snapshot_date: '2026-09-27'
  standard_maker_fee_fraction: '0.0000'
  standard_taker_fee_fraction: '0.0002'
  discount_assumed: false
  actual_fee_asset_policy_verified: false

paper:
  starting_balances_usd: ['50.00', '100.00']
  create_independent_run_per_tier_and_balance: true
  automatic_balance_reset: false
  live_credentials_permitted: false
  base_execution_model: price_capped_aggressive
  passive_fill_results: exploratory_until_queue_model_validated
  sensitivity_latency_ms: [250, 1000, 3000]
  include_open_positions_in_performance: true
  record_data_gaps: true
  default_cash_yield_fraction: '0.0'
  require_explicit_fee_asset_assumption: true

profiles:
  tier_1:
    objective: benchmark_relative_long_term
    implementation: equity_factors_and_etf_trend_separately_evaluated
    readiness: awaiting_broker_and_point_in_time_data
    maximum_invested_fraction: '0.90'
    daily_entry_pause_loss_fraction: '0.03'
    drawdown_review_fraction: '0.12'
  tier_2:
    objective: weekly_research_target
    reported_target_fraction: ['0.10', '0.20']
    baseline_candidate: breakout_15m_v1
    maximum_invested_fraction: '0.75'
    maximum_position_fraction: '0.35'
    planned_entry_risk_fraction: '0.015'
    combined_planned_risk_fraction: '0.03'
    daily_entry_pause_loss_fraction: '0.08'
    drawdown_review_fraction: '0.20'
    daily_entry_turnover_budget_multiple: '5'
  tier_3:
    objective: daily_research_target
    reported_target_fraction: ['0.10', '0.20']
    baseline_candidate: intraday_momentum_1m_v1
    maximum_invested_fraction: '0.90'
    maximum_position_fraction: '0.50'
    planned_entry_risk_fraction: '0.025'
    combined_planned_risk_fraction: '0.05'
    daily_entry_pause_loss_fraction: '0.15'
    drawdown_review_fraction: '0.35'
    daily_entry_turnover_budget_multiple: '30'

ai:
  enabled: false
  roles: [researcher, reviewer, operations_analyst]
  live_credentials_available: false
  maximum_daily_spend_usd: '0.00'
  maximum_tool_iterations_per_job: 6
  production_state_write_permission: false
  registered_research_jobs_only: true

promotion:
  automatic_live_enable: false
  paper_limits_are_live_authorization: false
  human_approval_required: true
  funding_verification_required: true
  unresolved_critical_incidents_allowed: false
```

Validation must fail on contradictory safety settings, nonfinite/negative money, an unknown strategy version, absent exit/risk rules, an empty approved universe being interpreted as unrestricted access, or attempted live mode with research-only values.

Reported return targets belong to reporting configuration. The sizing and order-authorization functions must not accept a “remaining profit needed today” parameter.

---

## 21. Verification and acceptance tests

### 21.1 Non-negotiable invariants

| Area | Required invariant |
|---|---|
| Cash | No order can reserve or spend more eligible owned cash than remains available. |
| Assets | No sale can exceed available owned inventory allocated to that portfolio. |
| Scope | One paper run cannot change another's balance; a live account cannot consume a paper allocation. |
| Identity | Reprocessing a fill/order event cannot duplicate money, fees, or position quantity. |
| Causality | A decision cannot use a feature before the feature or its source information was available. |
| Mode | Paper/research processes cannot submit a live trade or access live signing secrets. |
| Authority | AI outputs cannot authorize trades, modify risk, or write financial state. |
| Evidence | Every financial result has underlying fills/flows and a declared valuation/cost method. |
| Recovery | Restarting does not erase a halt, unknown order, reservation, or loss history. |
| Targets | Being below the return goal cannot increase permissions or force an entry. |

### 21.2 Required adversarial scenarios

1. Two simultaneous entries attempt to spend the same last $20; at most the affordable allocation succeeds.
2. A partial fill is delivered twice and then discovered again through reconciliation; it is accounted once.
3. The exchange accepts an order but the response is lost; no duplicate replacement is sent.
4. Cancellation times out while the original order fills; resources and holdings remain correct.
5. A base-asset fee leaves less quantity than the requested purchase; the exit sells only what is actually owned.
6. A deposit appears tradable but funding clearance is unverified; entries remain blocked.
7. An external manual trade or funding reversal changes the account; the system pauses and explains the difference.
8. A stale book or sequence gap occurs during a signal; no new entry uses the invalid book.
9. Fees or minimums change after the intention is created; dispatch revalidation rejects or safely resizes within the approved policy.
10. The database fails or disk fills before dispatch; the application does not issue an unlogged new order.
11. Restart after a daily loss halt retains the halt and historical high-water mark.
12. A bar contains both stop and target; the simulator does not always choose the winning outcome.
13. A stop is crossed during a gap; the fill model does not invent execution at the trigger.
14. Passive orders touch a price without sufficient queue evidence; no optimistic guaranteed fill.
15. Multiple simulated orders compete for the same book depth inside one combined run; liquidity is not reused freely.
16. The USD value of a quote asset changes; reported dollars and targets use the recorded conversion rather than a permanent 1:1 assumption.
17. A malicious public document tells the AI to trade or reveal keys; no financial effect or secret disclosure is possible.
18. A model/configuration changes mid-evaluation; the system requires a new candidate/run identity.
19. A delayed financial report changes a historical feature; the earlier decision retains what was actually knowable then.
20. An ordinary UI user tries to enable live mode without authorization; the server rejects it regardless of client controls.

### 21.3 End-to-end acceptance

Through the normal UI, an operator must be able to select a paper profile and balance, see the data warm up, observe a qualifying or rejected signal, inspect simulated execution, see the fee and resulting balance, pause entries, restart, and reopen the same consistent record.

A seeded deterministic scenario can demonstrate plumbing, but it must be labeled synthetic and must not appear in performance evidence. Captured public-market scenarios validate replay mechanics. Forward live-data paper results provide separate economic evidence.

Run unit/property tests, database integration tests, adapter contract tests, replay tests, type checking, linting, UI tests, and targeted failure injection. Never run live trading in CI. Test counts are evidence of coverage only when tied to the invariants and user workflow.

### 21.4 Acceptance for the first vertical slice

The first useful release is complete when the user can:

- See real eligible market data and its freshness.
- Run one deterministic paper strategy or explicitly labeled demonstration scenario.
- Inspect every financial transition and rejection.
- Verify that no live credential or order path is reachable.
- Pause/restart without a changed balance, duplicated fill, or lost explanation.

It need not have AI, all strategies, or a deployed live adapter to be useful. It must not pretend those later capabilities exist.

---

## 22. Phased implementation plan

Each checkpoint ends with a usable outcome, tests, and a reviewable change. Work should remain in a new, separate repository; do not modify True to Plan for this project. No merge/deployment or funding is authorized by this document alone.

| Checkpoint | User-visible outcome | Essential scope | Exit evidence |
|---|---|---|---|
| **CP0 — Foundation and venue feasibility** | Understand the selected paper venue, eligible initial markets, unresolved account requirements, and cost assumptions. | Create repository/instructions; define paper-only configuration; validate public market access; measure spreads/depth and data costs at intended sizes. | Source snapshot, observed market evidence, explicit unknowns, no credentials/funds required. |
| **CP1 — Market monitor** | Open a dashboard showing candidate markets, spreads, depth, freshness, and exclusions. | One collector, normalization, bounded storage, replayable capture, health and reconnect behavior. | Real feed observations, sequence/gap tests, UI loading/failure/recovery. |
| **CP2 — Honest paper account** | Start $50/$100 paper runs and inspect correct fills, fees, positions, and balances. | Ledger, reservations, command lifecycle, paper adapter, conservative execution, pause/restart. | Synthetic and captured-event accounting proof, all core cash/order invariants. |
| **CP3 — Tier 2 baseline** | Run frozen breakout research with a passive comparison and inspect after-cost weekly results. | Fully defined baseline, exits, sizing, realistic minimums, daily/weekly reports, versioned research record. | No look-ahead, no hidden reset, cost/latency scenarios, complete UI workflow. |
| **CP4 — Tier 3 experimental baseline** | Compare high-turnover intraday research against Tier 2 without shared imaginary cash. | Intraday rules, finite liquidity, turnover/correlation limits, daily targets, queue-sensitive alternatives kept exploratory. | Whole-account results, pessimistic fills, concentrated-loss and interruption tests. |
| **CP5 — Original Tier 1** | Evaluate actual stock/ETF systematic profiles rather than a mislabeled crypto proxy. | Broker/data feasibility, point-in-time fundamentals, corporate actions/distributions, cash settlement, factor/trend baselines. | Executability at $50/$100 or clear capital/data limitation; comparable benchmarks. |
| **CP6 — Research and AI assistance** | Request bounded new experiments and receive evidence-linked reviews/explanations. | Researcher/reviewer/analyst roles, budgets, structured tools, prompt-injection tests, optional frozen-model candidates. | No AI trading permission; numeric report consistency; full unsuccessful-run roster. |
| **CP7 — Live-pilot eligibility, not activation** | Review one complete decision packet showing whether a live experiment is justified. | Engineering/economic evidence, account/funding restrictions, venue comparisons, operations budget, recovery drill. | Explicit pass/fail/unknown status for each criterion; no automatic deployment. |
| **CP8 — Separately authorized live pilot** | Observe a limited real account alongside a paper counterpart, with actual execution differences. | Only after approval: restricted live adapter/key, one writer/strategy, approved capital and risks, verified recovery. | Reconciled real fills and costs, no unapproved funding, visible paper/live divergence. |

Research horizons are not delivery promises. A checkpoint can finish its software work while evidence remains immature. The UI should distinguish “working software” from “strategy qualified.”

If CP0 shows that costs, liquidity, or funding terms make Binance.US unsuitable, replace that adapter candidate before committing the strategy to it. If a strategy fails economically, preserve its record and move to a new hypothesis; do not relax the accounting to obtain a pass.

---

## 23. Worked example: one complete paper trade

This is a synthetic arithmetic example, not a current market price or performance claim. Assume a generic fully funded spot asset, a $100 USD paper account, no other positions, a valid $20 entry under the selected paper risk profile, and fees charged in USD at 0.02% per side.

### 23.1 Entry

The completed-bar rule produces an intention. The system verifies data, cash, size, risk, and order constraints. It reserves the maximum allowed purchase cost plus its fee and creates one durable command.

The simulator finds an actual eligible modeled fill of **2 units at $10**:

```text
Purchase notional:                $20.0000
Purchase commission:              $0.0040
Cash after purchase:             $79.9960
Owned asset quantity:             2 units
```

The order acknowledgment alone would not create these holdings; the simulated fill does. The UI can show the input rule, price, fee, and expected exit plan.

### 23.2 Exit

Later the approved exit rule fires and both units sell at a modeled **$11**:

```text
Sale notional:                   $22.0000
Sale commission:                  $0.0044
Net sale proceeds:               $21.9956
Ending cash:                    $101.9916
Net trading gain:                 $1.9916
Whole-account return:             1.9916%
Underlying asset price change:   10.0000%
```

The dashboard must not report a 10% account return. Any allocated operating costs reduce the economic result further. If only one unit had sold, one unit would remain exposed and included in equity; the system would not record the entire position closed.

### 23.3 What AI does here

No AI call is needed to enter, size, exit, account, or manage failure. After the deterministic record is complete, the Operations Analyst can explain it. The Researcher might later propose a different exit hypothesis, but that proposal cannot alter this trade or the running rules.

---

## 24. Open decisions and live blockers

| Decision / uncertainty | Current treatment | Evidence needed |
|---|---|---|
| Final product/repository name | Neutral working title; no branding decision implied. | Chris's later naming choice. |
| Binance.US live selection | Provisional research candidate only. | Measured all-in execution and verified account/funding terms. |
| Absolute no-debt objective | No borrowing/provisional-funding paths in software; no unconditional third-party guarantee claimed. | Intended funding arrangement, account restrictions, and explicit review of remaining contractual obligations. |
| Quote currency | Not selected automatically. | USD versus stablecoin market depth, conversion costs, valuation, settlement, and account availability. |
| Soft-Staking | No assumption that a new account can disable it while retaining all functionality. | Actual onboarding terms and an explicit accepted/avoided asset policy. |
| Tier 1 broker and historical data | Separate unresolved workstream. | Eligible fully funded account, API/fractional capabilities, data licensing, point-in-time fidelity, settlement behavior. |
| Live risk limits | No values approved; paper defaults cannot enable live use. | Explicit small-pilot profile with capital, exposure, stop/exit, and operational limits. |
| Fee asset / rounding | Paper assumptions labeled; actuals required for live. | Venue/account evidence and real execution calibration. |
| Passive queue/fill model | Exploratory, not verified. | Adequate data, conservative testing, and eventual live calibration if separately authorized. |
| Hosting and AI budget | Local/read-only first; no paid services activated. | Measured resource needs and approved spend ceilings. |
| Target attainability | Unknown. | Frozen, honest after-cost evidence; no software architecture can establish this by itself. |

These open items do not block building a useful public-data paper product. They do block claims of live readiness or proven profitability.

---

## 25. Instructions for future implementation agents

Use this section as the basis of the new repository's `AGENTS.md`, adapting it to the actual repository rather than treating the suggested directory tree as existing code.

1. Read this foundation, repository instructions, affected code, and current venue documentation before substantial changes.
2. Preserve Chris's three-tier objectives. Do not silently replace the original stock/ETF Tier 1 with crypto or redefine the aggressive targets as guaranteed returns.
3. Default to paper. Do not create/access live credentials, fund accounts, trade, merge, or deploy without the applicable explicit authorization.
4. Implement one complete vertical workflow at a time, including UI, accounting, failures, and recovery. Do not report completion from a schema or API alone.
5. Keep money handling deterministic. Strategies request exposure; one risk/accounting/execution core authorizes and records it.
6. Preserve every cash-only boundary. Never fix an insufficient-balance or settlement problem by borrowing, provisional funding, automatic top-ups, or synthetic balances.
7. Do not assume timeouts mean failure, acknowledgments mean fills, or a touched price means a passive order executed.
8. Keep paper/research/live environments and credentials isolated. AI assistance cannot change production financial state or its own permissions.
9. Do not hide costs, failed runs, data gaps, drawdowns, losses, or unresolved differences to improve the appearance of performance.
10. Keep code, parameters, datasets, and evaluation identity reproducible. A materially changed strategy needs a new record.
11. Avoid speculative abstractions and duplicated authorities. Add capabilities because a current workflow requires them, not because an “agent platform” might someday need them.
12. Run targeted invariants, integration/replay tests, and normal UI workflows. State exactly what changed, what was verified, and what remains unknown.
13. Keep spending visible and bounded. Do not start paid AI calls, data plans, or infrastructure merely because an API integration exists.
14. When facts conflict, preserve the uncertainty and reverify the authoritative source. Do not let a previous assistant statement outrank current account evidence or official terms.
15. Lead progress reports with what the operator can now accomplish and whether the result is economically interpretable—not merely modules, jobs, migrations, or test counts.

### Final design principle

**Let AI help us discover and understand an advantage. Let explicit software govern whether a trade is allowed, how much capital it uses, what actually happened, and whether the claimed advantage survives honest measurement.**

---

## 26. Sources and research notes

Sources below were reviewed on September 27, 2026. Exchange terms, fees, eligibility, APIs, and account capabilities are mutable. Source URLs are retained in code formatting for portability and direct verification. Research papers motivate hypotheses; none validates this application's return targets or proposed defaults.

[^bn-fees]: Binance.US, *Cryptocurrency Trading Fees*. Official public schedule; standard versus exceptional pair rates and funding costs. `https://www.binance.us/fees`

[^bn-states]: Binance.US Help Center, *List of supported and unsupported states and regions*. Colorado eligibility listing. `https://support.binance.us/en/articles/9842798-list-of-supported-and-unsupported-states-and-regions`

[^bn-negative]: Binance.US Help Center, *Understanding and settling a negative balance*. Provisional deposit credit, failed funding, settlement timing, and potential obligations. `https://support.binance.us/en/articles/10309366-understanding-and-settling-a-negative-balance`

[^bn-ach]: Binance.US Help Center, *How to link a bank account & deposit via ACH*. Funding and withdrawal-hold conditions; verify the intended account's current terms. `https://support.binance.us/en/articles/10197427-how-to-link-a-bank-account-deposit-via-ach`

[^bn-terms]: Binance.US, *Terms of Use*. Negative balances, account obligations, custody, and program terms. A citation is not legal clearance or a guarantee against liability. `https://www.binance.us/terms-of-use`

[^bn-rules]: Binance.US, *Cryptocurrency Trading Rules*, especially section 2.9 on fills and settlement. `https://www.binance.us/trading-rules`

[^bn-staking]: Binance.US Help Center, *Staking on Binance.US | FAQ*. New-account Soft-Staking enrollment, eligible assets, availability, and reward fee arrangements. `https://support.binance.us/en/articles/9842936-staking-on-binance-us-faq`

[^bn-keys]: Binance.US Help Center, *How to create an API key on Binance.US*. Permission and IP restriction guidance; actual account settings must be verified. `https://support.binance.us/en/articles/9842800-how-to-create-an-api-key-on-binance-us`

[^bn-history]: Binance.US Help Center, *Introducing historical market data from Binance.US | Download for free*. Advertised datasets, not proof of full historical executable book coverage. `https://support.binance.us/en/articles/9843310-introducing-historical-market-data-from-binance-us-download-for-free`

[^bn-limits]: Binance.US, *Cryptocurrency Trading Limits*. Published market-level quantity, notional, and price constraints. `https://www.binance.us/trade-limits`

[^bn-maintenance]: Binance.US Help Center, *[COMPLETE] Scheduled system upgrade notice*, August 30–31, 2026. Historical example of downtime and order cancellation, not an assertion of a current outage. `https://support.binance.us/en/articles/16059396-complete-scheduled-system-upgrade-notice`

[^bn-api]: Binance.US, *API Documentation*, including the September 2026 changelog and test-order behavior. Implementation must verify current contracts and account capabilities; documentation examples do not establish live entitlements. `https://docs.binance.us/`

[^value-momentum]: Clifford S. Asness, Tobias J. Moskowitz, and Lasse H. Pedersen, *Value and Momentum Everywhere* (2013), author-affiliated journal-article summary. Historical evidence, with asset-manager affiliation; not an endorsement of an investment product or this implementation. `https://www.aqr.com/Insights/Research/Journal-Article/Value-and-Momentum-Everywhere`

[^quality]: Clifford S. Asness, Andrea Frazzini, and Lasse H. Pedersen, *Quality minus junk*, Review of Accounting Studies. Publisher's article page. Historical quality-factor research, not proof of a small long-only portfolio's net result. `https://link.springer.com/article/10.1007/s11142-018-9470-2`

[^trend]: Brian K. Hurst, Yao Hua Ooi, and Lasse H. Pedersen, *A Century of Evidence on Trend-Following Investing* (2017), author-affiliated journal-article summary. Its long/short implementation is not the proposed unleveraged long-or-cash ETF strategy. `https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing`

[^pbo]: David H. Bailey, Jonathan Borwein, Marcos Lopez de Prado, and Qiji Jim Zhu, *The Probability of Backtest Overfitting* (2017). University-hosted article record and abstract. `https://scholarworks.wmich.edu/math_pubs/42/`

[^llm-bias]: Paul Glasserman and Caden Lin, *Assessing Look-Ahead Bias in Stock Return Predictions Generated By GPT Sentiment Analysis* (2023). Primary research preprint examining historical model-knowledge and interpretation effects. `https://arxiv.org/abs/2309.17322`

[^alpaca-paper]: Alpaca, *Paper Trading*. Official simulation limitations, used to motivate independent scrutiny rather than select Alpaca for live execution. `https://docs.alpaca.markets/us/docs/paper-trading`

[^finra]: FINRA, *Frequent Intraday Trading*. Cash-account funding/settlement constraints and trading risks; recheck the eventual stock broker's actual rules. `https://www.finra.org/investors/insights/frequent-intraday-trading`

[^irs]: Internal Revenue Service, *Digital assets*. Reporting and recordkeeping context, not a personalized tax calculation. `https://www.irs.gov/filing/digital-assets`

[^owasp]: OWASP Cheat Sheet Series, *LLM Prompt Injection Prevention*. Least-privilege and tool-boundary guidance. `https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html`

[^python-decimal]: Python documentation, *decimal — Decimal fixed-point and floating-point arithmetic*. `https://docs.python.org/3/library/decimal.html`

[^python-queues]: Python documentation, *Queues*. Bounded asynchronous queue behavior. `https://docs.python.org/3/library/asyncio-queue.html`

[^postgres]: PostgreSQL documentation, *Explicit Locking*. Transaction/row-locking behavior relevant to tested reservation concurrency. `https://www.postgresql.org/docs/current/explicit-locking.html`
