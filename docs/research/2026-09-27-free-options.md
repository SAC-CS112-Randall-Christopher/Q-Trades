# Free options research account

Chris requested a separate cash-funded options account, learning from its history,
and then specified free data with no monthly subscription. This implements local
historical research. It does not establish a live options strategy or broker access.

Update: Chris is willing to open a free account for data. The
[live-data comparison](2026-09-27-live-options-data.md) identifies Public as the next
candidate, subject to account entitlement and fee conditions. The historical source
below remains the implemented feed; no broker connection has been established.

## Verified free source

[Market Data's authentication documentation](https://www.marketdata.app/docs/api/authentication/)
explicitly unlocks historical AAPL stock and option endpoints without a token.
Anonymous requests on September 27 Denver / September 28 UTC returned actual data,
including HTTP 203 cache responses. No account, key, subscription or paid request was used.

[Historical option chains](https://www.marketdata.app/docs/api/options/chain/) provide
end-of-day quotes and contract metadata; historical Greeks and IV are null. The adapter
selects the expiry nearest 14 calendar days and retains its full returned calls/puts.
[Contract quotes](https://www.marketdata.app/docs/api/options/quotes/) provide follow-up
observations for held or pending contracts after the selected chain expiry changes.
Historical open interest is the previous session's settled figure, not a real-time flow.
Prices, displayed sizes, daily volume, open interest, source timestamps and complete
accepted responses with SHA-256 hashes are retained. Missing evidence is not estimated.

The stock candle endpoint supplies the calendar only. Adjusted historical stock prices
are not strategy features; daily movement uses the underlying price in each as-of chain.
The initial calendar is the latest 90 completed sessions, refreshed every 12 hours.
Each date is consumed only once, in order. Dates and contract identity must match.
The live probe covered May 19–21, 2026, 178 contract observations, plus a separate
single-contract lookup. Its isolated PostgreSQL journal reconciled. The test namespace
was removed; these observations were not imported as synthetic trial trades.
Receipt: [isolated public-data check](../evidence/options-isolated-free-probe.json).

Other paths researched: Tradier requires an account/token; IBKR API market data has
funding/subscription requirements; Alpaca's free indicative quotes are modified and
cannot substantiate execution quality. Nasdaq's public quote response lacked the
per-quote timing/sizes needed here. Cboe webpage scraping was not used. These findings
do not establish that no better free source exists. This source is a usable starting
point with explicit restrictions, not a claim of comprehensive market coverage.

## Separate cash and execution model

- Independent fake $100 primary plus two separately funded frozen comparison accounts.
  None of their cash, funding, positions or outcomes enters a spot account.
- Own `options_paper` schema, writer lock, immutable events, balanced asset journal,
  projection and paginated `/api/options/journal` inside the dedicated local database.
- Purchased standard AAPL calls/puts only, one contract and one position per account.
  Standard 100-share multiplier inferred from ordinary OCC AAPL roots; adjusted roots
  are excluded. Deliverables have not been independently verified with a broker.
- Fees are an explicit $0.50/contract/side research assumption, not a broker quote.
  Full premium plus both fee sides must fit settled cash and 2.5% of account equity:
  initially $2.50. This can exclude every liquid option. A stop cannot reduce that
  maximum premium-loss budget. No fractional contracts, borrowing or naked sales.
- Entry intent at session D can fill only on a later session's ask at or below its
  recorded limit, after liquidity/risk rechecks. Exits use a later session's bid.
  One contract consumes at most 10% of displayed size; both sides need ten contracts.
  Entry screens also require 100 daily volume, 500 open interest and a bounded spread.
- No reuse of sale proceeds before the next observed trading session. Exit fees are
  reserved in settled cash at entry. Settlement is a conservative simulation rule,
  not a claim about unrestricted cash-account reuse at a particular broker.
- Exits are requested after five held sessions, within five calendar days of expiry,
  or at modeled profit/loss thresholds. Daily snapshots cannot establish intraday
  stop execution. Gaps can change the next executable price materially.
- A missing expiry disposition freezes the account, keeps the position unresolved
  and prevents invented payout, replenishment or automatic stock exercise. Covered
  option sales, corporate-action deliverables and broker exercise are not modeled.

## Learning without paid models

The fixed policies test five-session momentum of at least 1% versus ten-session
momentum of at least 2%, with 15% versus 10% maximum bid/ask spread. They choose calls
after positive movement and puts after negative movement, subject to the same cash
and liquidity gates. These are research baselines, not optimized recommendations.

Every four wall-clock hours, compare two disjoint 20-session historical windows.
Both incumbent and challenger need ten fully contained closed trades per window.
The challenger must beat mean net trade return, remain positive with an additional
$0.50 stress cost per trade, and have no worse lifetime drawdown, also at most 35%.
The primary must be flat with no pending order, and promotions must be eight hours
apart. Only subsequent dates use a promoted version; prior results remain unchanged.
Scarce evidence retains the existing policy. No neural model is being trained.

At 35% drawdown from the current risk-review peak, entries pause for review; reviews
can start a documented new risk segment while preserving lifetime drawdown. Missing
expiry disposition cannot be waived. A review cooldown skips the next session.

Only when liquidation equity is strictly below $5 and the account is flat and settled
does a recorded failure review precede restoring $100. Cumulative funding and losses
remain visible. The primary uses the fixed selective policy afterward. The review
records observed losses and costs; it does not claim to know a proven causal cure.

Success is still a majority of $100-to-$1,000 attempts, not trade win rate. Historical
replays and correlated shadows are not independent live attempts, and end-of-day AAPL
coverage cannot validate fast intraday options tactics or all-market profitability.

## Cost, storage and operation

The client reads no API key and allows only anonymous historical AAPL routes.
Requests are at least 12 seconds apart; a persisted 60-request UTC-day budget survives
restart. Failures also consume that budget. Processing waits 60 seconds between
sessions. Catch-up needs at least two daily request budgets, potentially longer when held
contracts require extra requests. Reviews continue during missing-data periods.
No fallback purchases data or calls a language model.

Each successful chain request is bounded to 1,000 rows and 2 MB. The observed
September 24 chain was about 14 KB for 88 contracts; 90 similar sessions would be
about 1.2 MB of source JSON, before metadata, events, indexes, projections and WAL.
That is an illustration, not a physical-disk forecast. Worst-case request volume is
bounded separately; actual permanent database growth remains visible in the dashboard.
Financial history and accepted source receipts are retained; recent UI lists are bounded.

The worker starts with the existing local `--experiment` service. The computer and
Docker must remain running. Options data errors do not stop spot processing. Fatal
options ledger/worker errors stop that worker and require inspection; they do not
silently reset its state. There is no public hosting or broker execution connection.
