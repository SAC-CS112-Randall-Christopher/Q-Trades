# CP9 decision packet — not ready, live disabled

Source check: **September 29, 2026**. Normal dashboard section `live-readiness`
and read-only `/api/readiness` expose the facts version/fingerprint, costs,
unresolved items, engineering requirements and current local paper evidence.
Refresh/export reads evidence; it cannot enable execution. No live candidate is
selected, no live capital is allocated and no independently qualified subsequent
forward result was obtained. CP7 synthetic contract tests are not 28 elapsed days.

## Venue and account facts

[Binance.US supported states](https://support.binance.us/en/articles/9842798-list-of-supported-and-unsupported-states-and-regions)
(June 3, 2026) lists Colorado. This is venue availability, not verification of a
particular person's identity, residency, account, tax/legal obligations or permissions.
[Terms](https://www.binance.us/terms-of-use), updated June 5, 2026, cover API use
and preserve intellectual-property rights. Account acceptance, redistribution rights
and any third-party access remain unverified; public data availability grants no
general publication license. Only code, concise source facts and synthetic receipts
are published. Terms also describe automatic soft-staking for certain eligible
assets: verify assets and opt-out before any future cash-spot account decision.

[Published fees](https://www.binance.us/fees) show zero maker and 0.02% taker on
BTC/USD and ETH/USD; BNB/USD has a different tier. The paper public profile is a
dated scenario, not actual account commissions or fee-currency evidence. Maker
orders, BNB discounts, base-asset fees and account-specific fees are unsupported in
the current paper execution model. Published ACH charges do not establish an
account's transfer permissions or limits; crypto withdrawal charges are dynamic.

[Negative balances](https://support.binance.us/en/articles/10309366-understanding-and-settling-a-negative-balance)
(June 4, 2026) can follow reversal of pre-credited bank deposits. The published
[withdrawal hold](https://support.binance.us/en/articles/9842883-why-is-a-portion-of-my-balance-unable-to-be-withdrawn-or-unavailable)
does not prove irreversible settlement. No promise that cash-spot can never owe
money is supported by this evidence. Future funding must be separately reviewed
and reconciled as settled; no programmatic deposit/top-up path is proposed.
[FDIC coverage](https://www.fdic.gov/resources/deposit-insurance/financial-products-not-insured)
does not insure crypto assets. Venue custody/failure, blocked withdrawals,
stablecoin depegging if such quote assets are later proposed, and transfer/tax
costs are distinct from paper price risk. Current USD pairs are not a permission
to substitute USDT or another quote asset.

Two unsigned public exchangeInfo requests returned HTTP 200 on September 29.
The packet records exact retrieval times and response hashes for BTCUSD/ETHUSD:
public status TRADING, price tick $0.01, minimum quantity/step 0.00001 BTC and
0.0001 ETH, and $1 MIN_NOTIONAL applying to market orders. Actual executable
minimum also depends on current price, rounding, price/side percentage filters,
MARKET_LOT_SIZE, order/amendment counts and account restrictions. Those live
filters exceed the current paper subset. Private account tradability is unknown.
Raw public responses remain in ignored local QA data; source-linked facts are
bounded. Future permission checks must refresh every applicable filter.

## Total-capital economics and risk envelope

The options are **$50 or $100 total settled capital for one selected future
strategy**, not twenty funded live portfolios. At unchanged price, an all-cash
round trip that reserves the entry fee loses `capital * 2f / (1+f)` in fees.
For f=0.0002, $50/$100 losses are approximately $0.0200/$0.0400; the historical
0.10% taker stress costs approximately $0.0999/$0.1998. The current two-basis-point
adversity on each side adds a separate approximately $0.02/$0.04 price proxy,
before spread, depth, latency, dust, transfers, tax and operating expenses.
An illustrative $1/month operating cost is 2%/1% of capital; this is not a bill.
There is no demonstrated positive live after-cost return.

Current paper sizing plans 2.5% equity risk per order, 5% aggregate planned risk,
at most 50% equity cash per new order and 90% aggregate gross exposure. These are
the actual engine constants, not a new future-live authorization. Hard-stop policy
cash-spot-hard-stop-v1 latches at 35% drawdown from the retained peak; manual
recovery cannot reset its reference. Stop sizing cannot guarantee liquidation or
bound custody/gap losses. No live candidate/version/hash or final approved risk
envelope exists. A future packet must freeze all of them, including operating
budget and an account-wide settled allocation, before a separate decision.

## Deterministic adapter requirements, still unimplemented

The current adapter permits allowlisted public GETs only; Settings accepts paper
mode and literal false for live_enabled. It has no signing, private balance,
order, deposit or withdrawal route. Before adding live execution:

1. Persist account-wide reservations and immutable intent IDs atomically before
   submission. Broker client IDs are unique among open orders and can be reused
   after fills; they do not supply durable application idempotency.
2. Unknown submission outcomes freeze the affected intent and reconcile broker
   orders/fills/balances before any retry. Restart and reconnect reconcile sequence
   gaps and fees, rather than restoring an older financial database.
3. Enforce all current filters, actual fee assets, settled-cash/fee buffers,
   partial fills, dust and exposure across strategies. Record blocked exits and
   mismatches; reconcile execution costs exactly once.
4. Treat cancel/replace as potentially partial success, not a transaction. Track
   original and replacement orders separately; an uncertain cancellation cannot
   free the reservation. Use account-wide self-trade prevention and ownership.
5. Separate read-only monitoring and narrowly scoped trading keys, disable
   withdrawals, constrain IPs, rotate secrets outside research/LLMs and test key
   revocation. No credentials or permission changes are required for this packet.
6. Reserve management capacity; observe clock, rate limits, stream gaps and
   heartbeat failures. Pause new entries separately from existing risk. A kill
   action cannot claim a position is closed until reconciled fills establish it.
7. Define measured alert/response coverage, records retention and operating budget.
   Rollback pauses new risk, reconciles pending orders/positions, then switches
   reviewed code without discarding losses, fees or financial history.

These are proposed engineering requirements informed by the current official
[Binance.US API](https://docs.binance.us/),
[key safety guidance](https://support.binance.us/en/articles/9842812-binance-us-api-keys-best-practices-safety-tips)
and [self-trade prevention](https://support.binance.us/en/articles/9842907-self-trade-prevention).
The older official GitHub REST/error documents are dated 2023 and are only
cross-checks; global Binance documentation is not substituted for the US venue.
No signed request, account setup, order, funding, permission change or approval
was performed. Completing this checkpoint is a usable **no-go evidence packet**;
it does not grant an automatic transition to live trading.
