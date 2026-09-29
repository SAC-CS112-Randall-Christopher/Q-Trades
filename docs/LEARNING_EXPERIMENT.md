# Tier 3 continuous paper experiment

Authorization: Chris, 2026-09-27. Start with fake USD 100. Aim to reach USD 1,000
before falling below USD 5, in more than half of attempts. Continue until Chris
accepts the evidence or stops the experiment. There is no promised return or deadline.

## Research choice

Use deterministic online evaluation: predict/decide with information available now,
record the subsequent outcome, and then update the selection of strategy parameters.
Closed one-minute bars provide trend, volatility, volume, and breakout features.
Historical bootstrap bars warm indicators; they never produce retroactive paper fills.

A small, predeclared bank of three Tier 3 breakout variants is observed in separate
shadow portfolios. All use the foundation's trend filter, ATR stops, timed exits,
cash-only accounting, and fixed risk ceilings. Reviews run every four hours. A
candidate must have adequate **new forward** outcomes in two disjoint four-hour
windows before promotion. Every comparison, rejection, and promotion is recorded.
Four hours is a review cadence, not a promise of sufficient evidence. Candidate
selection remains an experiment, not a statistically proven edge.

Why: repeated optimization against the same historical observations produces
selection bias ([Bailey et al., probability of backtest overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)).
Training and evaluation must respect time order, excluding overlapping outcomes
at boundaries ([scikit-learn, time-series splitting](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)).
The first implementation therefore uses frozen candidates and future observation
windows instead of unrestricted self-modifying code or reinforcement learning.

## Money, attempts, and failures

- USD cash and spot markets only. The primary and three original shadow variants
  retain BTC/USD and ETH/USD. A separately funded pair compares those markets with
  a screened, bounded USD universe. USDT does not become USD buying power.
  No authenticated exchange endpoint exists.
- Primary account begins with exactly $100. Shadow accounts are separate simulations;
  their balances and results cannot be added to the primary account.
- Below $5 means conservatively estimated total liquidation equity, including
  owned positions and estimated exit fees. It does not mean uninvested cash.
- On failure, cancel entries, attempt exits using subsequently observed bids,
  and wait for a flat, reconciled account. Record the failure analysis first, then
  add only enough fake cash to restore $100 in the same database transaction.
  No fresh or complete valuation means no replenishment.
- Every injection stays in the ledger. Net P&L is equity minus all fake funding.
  A new attempt does not erase losses, costs, drawdowns, or prior strategy versions.
- Failure analysis reports observed exit reasons, costs, losses, and data gaps;
  causal explanations remain hypotheses. It selects the predeclared selective
  variant and imposes a one-hour entry cooldown as containment, not proof of a cure.
- First passage to $1,000 records a won attempt. The primary balance keeps running;
  it is not withdrawn or reset on success. Further $100 trials require future
  replenishment or separately labeled research experiments. Re-crossing $1,000
  in the same attempt does not count as another success.
- Wins / failures / unresolved attempts are separate. Shadow variants on the same
  market history are correlated and are not independent repeatability evidence.
  No automatic 'majority proven' claim is made from one winner or open attempts.

## Fixed risk and simulation contract

Maximum gross exposure 90%, one position 50%, planned risk 2.5% per entry and
5% combined. Daily loss 15% pauses new entries until the next UTC day; 35%
drawdown from the current risk-review peak pauses entries until the next review.
The review may start a new risk segment after documenting the drawdown; lifetime
drawdown remains recorded. Exits continue through all entry pauses. Turnover is
capped at 30 times start-of-day equity for entries, including both sides in usage.

The original execution observation model was REST every two seconds plus request time.
The versioned `paper-tiered-feed-ioc-v2` upgrade requests sequenced push depth at
100 ms for priority markets and 1 s for candidates. When unavailable, REST fallback
waits 0.5 s after each fast-market response or 5 s for a candidate, under a shared
request-weight budget. Actual transport, age and gaps are shown; stream connectivity
has not yet been established on this machine. Historical outcomes keep their model.
Orders use a subsequent fresh observation after at least one second, walk 20 visible
levels, consume at most 10% of displayed liquidity, and cancel any unfilled remainder.
Entry limits, quantity increments, minimum notionals, reserved cash, modeled fees,
and stale-data checks apply. The cost model charges 0.10% each side and a 2 bp
adverse price adjustment, explicitly an assumption rather than an account fee quote.
Stops are simulated decisions, not guaranteed stop prices. Gaps can cause larger losses.

Paper trading cannot establish live execution quality: market impact, latency,
queue priority, and venue failures are incompletely modeled
([Alpaca, paper-trading limitations](https://docs.alpaca.markets/us/docs/paper-trading)).
The public adapter follows [Binance.US public market-data documentation](https://docs.binance.us/).

## Broader-market comparison

`universe-control-v1` and `universe-wide-v1` start together with separate $100 balances
and the same breakout-v1 rules/costs. Control stays BTC/ETH; wide may enter qualified
USD markets after the liquidity screen, closed-bar warmup and fast-tier promotion.
They follow the same below-$5 review/replenishment rule. Initial research funding
is labeled separately from replenishment and never increases primary buying power.

Discovery runs once a minute: active USD spot, fresh ticker, at least $100,000 observed
24-hour quote volume, at least 300 trades, spread at most 25 bps, and two qualifying
scans. Normally at most four additional symbols receive closer observation, with a
five-minute minimum stay while eligible. Two qualifying candidates can receive 100 ms
depth; held/pending symbols retain priority. Total subscription ceiling is eight.
Resource pressure demotes optional research before held positions. These heuristic
thresholds are a recorded experiment, not optimized profitability claims.

Four-hour reviews include the paired outcomes without automatically expanding the
primary universe. Correlated accounts are not independent attempts or pooled capital.
The user's later options permission is implemented in a separate historical research
account described below. Futures observations remain separate, with no futures orders.

## Futures context and options research

The user excluded futures execution while requesting awareness of futures markets.
Kraken public linear perpetual snapshots record funding, open interest and the
mark/index premium about once per minute, separately from Binance.US spot prices.
Context has a 150-second expiry and explicit gaps, source and request/server times.
Order/fill evidence links the available snapshot; reviews summarize observations
without making causal or predictive claims or changing the strategy bank.

Only one futures venue is covered. Liquidation data, dated/CME futures and live options
chains are not connected. Public data access does not establish broker eligibility.
Cash-funded purchased options are a research hypothesis, not an established faster
path to majority $100-to-$1,000 success. Current risk ceilings stay fixed;
if no contract fits them, the correct result is no eligible trade.

## Separate free options account

The options primary and two frozen research variants each receive independent fake $100.
They use anonymous AAPL historical end-of-day bid/ask, sizes, volume and open interest.
No live options stream, broker account, paid subscription, LLM, Greeks or IV is required.
History runs once in chronological order; each intent requires a later session's quote.
The 2.5% entry-risk limit includes the full premium and both modeled fee sides. Proceeds
cannot fund another entry until the next observed session. Expiry without verified
disposition remains unresolved; it cannot become an invented payout or replenishment.

Four-hour wall-clock reviews compare fixed momentum and selective variants using two
disjoint 20-session replay windows with at least ten fully contained trades in each for
the incumbent and challenger. Stress costs, drawdown, flatness and eight-hour promotion
spacing must also pass. These gates select a future policy; they do not establish live
profitability or independent majority success. Repeated reviews do not repeat the data.
Below $5, a flat, settled account records failure evidence before restoring $100, retains
all funding/losses, and the primary adopts the fixed selective policy with a cooldown.
See [sources, assumptions and limitations](research/2026-09-27-free-options.md).

## Continuous operation

PostgreSQL holds an atomic state projection, balanced asset journal, immutable
events, bars, decisions, reviews, and replenishments. The UI provides recent records;
paginated journal export preserves access to older records. A database writer lock
prevents concurrent engines. Pausing entries never disables position management.

The application performs its own four-hour reviews without any LLM or open chat.
A Codex follow-up also checks its health and evidence every four hours. The computer
and Docker must remain running for trading; Codex must be available for its follow-up.
Outages are logged, missed reviews are coalesced into one catch-up review, and no
trades are invented for downtime. No uptime or majority-success result is implied.
