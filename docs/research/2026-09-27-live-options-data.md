# Free live options data research

Checked September 27, 2026 Denver / September 28 UTC. This is a source comparison
and proposed integration, not a connected broker feed or a change to the experiment.
Chris is willing to open an account for data provided it is free. He has not
authorized a deposit, subscription, live orders, or account creation on his behalf.
Chris subsequently reaffirmed IBKR as the intended options execution candidate.
The free-data comparison does not select or replace the eventual execution broker.

## Preferred candidate: Public

Public's [API FAQ](https://public.com/api) states that API access and requests are
free and that real-time options data is available. Its individual API is for
personal, noncommercial use. A brokerage account and API credentials are required.
This is a better candidate for forward research than restricting ourselves to
sources that require no signup.

The [quotes endpoint](https://public.com/api/docs/resources/market-data/get-quotes)
documents bid/ask, displayed sizes, separate price timestamps, volume, open interest,
and options Greeks including implied volatility. The
[chain endpoint](https://public.com/api/docs/resources/market-data/get-option-chain)
supports underlying and expiration selection. These are documented fields, not
observations from Chris's account; actual completeness, age, entitlement, contract
deliverables and volume/open-interest semantics still need verification. Top-of-book
quotes do not establish Level 2 access or guaranteed fills. Greeks are estimates.

The [current fee schedule](https://public.com/disclosures/fee-schedule/), updated
September 23, 2026, lists $0 account maintenance but $3.99 monthly inactivity fees
for accounts below $70 with no activity for six months. Public's
[inactivity FAQ](https://help.public.com/en/articles/6415744-what-are-inactivity-fees)
says signing in at least once every 180 days avoids that fee, without deposits or
trades. Do not assume API traffic qualifies as a sign-in. Do not describe the account
as unconditionally free forever.

Unresolved: the reviewed official documents do not explicitly guarantee live options
entitlement for a completely unfunded account, or specify whether additional market
data agreements/approvals are needed. Verify those conditions before any funding or
paid enrollment. No need for a paid plan is stated for the API itself. Credentials
must be entered locally, never pasted in chat or committed. Account identity and
agreement acceptance remain with Chris.

## Other sources

| Source | Verified distinction | Fit for this project |
|---|---|---|
| Interactive Brokers | [Account minimums and inactivity fees](https://www.interactivebrokers.com/en/accounts/required-minimums.php) are $0 for individual Pro/Lite accounts. [Market-data pricing](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php) lists OPRA at $1.50/month for qualifying nonprofessional users, with $500 individual-account equity plus subscription cost required for activation; free OPRA data is delayed 15 minutes. | Remains the intended execution candidate. Live options data is inexpensive but does not meet the current zero-cost, unfunded constraint. Delayed data is a separate research possibility; account-specific API access has not been tested. |
| TradingView | [Coverage](https://www.tradingview.com/data-coverage/) lists free OPRA quotes delayed 15 minutes and a paid real-time feed. Its [API help](https://www.tradingview.com/support/solutions/43000474413-i-need-access-to-your-api-in-order-to-get-data-or-indicator-values/) says it does not provide a market-data API. [Terms section 3](https://www.tradingview.com/policies/) restrict data to display use and prohibit automated non-display processing. | Useful for manual market inspection; not the application's data backend under the published terms. |
| Tradier | [Market-data docs](https://docs.tradier.com/docs/market-data) distinguish live brokerage data from delayed sandbox data. [Pricing](https://tradier.com/pricing) lists a $0/month Lite plan with API access, but $50/year inactivity with fewer than two trades per year. | Not a clean permanent free research-only account. Do not trade to avoid fees. |
| tastytrade | [Market-data docs](https://developer.tastytrade.com/docs/concepts/market-data/) require a funded account for real-time REST quotes and point to streaming for lower latency. | Alternative if Chris later accepts a funding requirement; no deposit is currently authorized. |
| Alpaca | [Historical options docs](https://docs.alpaca.markets/us/docs/historical-option-data) distinguish the free indicative feed, with modified quotes, from subscribed OPRA. | Indicative prices must not be labeled actual executable options quotes. |
| Market Data anonymous AAPL | [Existing probe and implementation](2026-09-27-free-options.md) use historical end-of-day data without any account. | Verified bootstrap source already integrated; inadequate to validate fast intraday trading. |

IBKR details: the $500 requirement is account equity, not a $500 service charge.
The OPRA fee has a $20 monthly commission waiver threshold, subject to IBKR's
allocation rules; simulated commissions do not qualify. The $1.50 is not a complete
quote for every possible data need: [IBKR's subscription guide](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/popular-market-data-subscriptions/introduction)
requires the underlying network subscription for dependent Greeks and does not
include underlying index quotes with an options subscription. The
[TWS API guide](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-delayed/introduction)
supports delayed data where available, with limitations; this is not a verified
promise of unrestricted options access for a new unfunded account. Actual U.S.
options trading has separate [commissions](https://www.interactivebrokers.com/en/pricing/commissions-options.php),
commonly $0.65/contract with a $1 order minimum and applicable additional fees.
The existing historical simulator's $0.50/side assumption is not an IBKR fee model.
Any eventual IBKR-specific experiment must version realistic fees and settlement
conditions without rewriting prior outcomes. No subscription has been activated.

## Proposed connection and validation

1. Verify a standard individual account's market-data access at zero subscription
   cost, including any funding and exchange-agreement conditions. No paid trial,
   deposit, options trade or margin enrollment is part of this step.
2. Add a separate authenticated data adapter using only account identification and
   market-data endpoints. Request the minimum available permissions. Do not claim
   the provider offers a data-only key until verified; enforce an endpoint allowlist
   in our application even if the key has broader authority. No broker order code.
3. Begin with a small stock/ETF watchlist and bounded expiration/contract selection.
   Batch quotes, promote candidates, and prioritize held contracts. Start with
   moderate snapshot intervals and measure age, latency, CPU and storage before
   increasing frequency. The [changelog](https://public.com/api/docs/changelog)
   documents a global 10-request/second limit per account; that is a ceiling, not
   a target or proof of ten fresh observations each second. The verified interface
   here is REST snapshots, not a connected push stream.
4. During an open market session, verify source timestamps, bid/ask sizes and
   spreads, missing/stale/crossed quotes, throttling and reconnect behavior. An
   HTTP success outside market hours does not prove current live quotes.
5. Record a separate versioned forward-data experiment. Preserve the historical
   account and all its results; do not splice current quotes into its historical
   clock or count replays as independent forward successes. Keep the fake $100,
   cash controls, fixed premium-risk budget and four-hour evidence reviews.
6. Persist source/receipt times and decision/trade evidence with bounded collection.
   Measure actual payload and database growth before setting retention. Avoid
   collecting every chain continuously. Never prune financial history to meet a
   market-data retention limit.

No broker API was called with credentials, no account was opened, and no runtime or
financial state was changed during this research. Live access remains unverified.
