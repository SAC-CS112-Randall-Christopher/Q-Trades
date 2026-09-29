# Futures observations and cash-funded options research

Chris's current direction is to observe futures and exclude futures execution.
Purchased options or fully covered sales remain candidates for separate research.
The original $100 spot attempt continues without a reset or change to its risk limits.

## Implemented source and meaning

The anonymous Kraken public API was accessible from this machine. The live probe
resolved BTC, ETH, SOL, ADA, SUI and DOGE to active linear USD perpetual contracts;
BTC's venue symbol is PF_XBTUSD. Instrument metadata must show a unique supported
contract with one base unit per contract. An accessible public endpoint does not
establish eligibility for a trading account.

The adapter reads a selected ticker for each tracked asset, at most eight per cycle,
with two concurrent requests. It waits 60 seconds after a completed cycle, so the
effective interval includes response time. Metadata refreshes hourly. The allowed
GET routes have no signing or account functions. See the official
[ticker endpoint](https://docs.kraken.com/api-reference/market-data/get-ticker-by-symbol)
and [instrument endpoint](https://docs.kraken.com/api-reference/instrument-details/get-instruments).

| Observation | Stored interpretation | What it does not establish |
|---|---|---|
| Mark/index premium | `(mark / index - 1) * 10,000` basis points, on Kraken | An executable Binance.US spread or arbitrage profit |
| Funding | USD per base unit per hour; signed and preserved verbatim | A forecast of price direction |
| Approximate funding percentage | Funding divided by the current index, clearly labeled approximate | The official rate-setting index or a realized future payment |
| Open interest | Outstanding base-unit equivalent for that contract | Whether traders collectively favor longs or shorts |
| Change in open interest | Same contract, two observations 30–180 seconds apart | New money inflow, liquidations, or a causal explanation |

Kraken documents hourly funding and absolute payments per unit. Positive funding
transfers from longs to shorts; negative funding reverses the transfer. Predicted
funding is retained separately. See
[contract and funding specifications](https://support.kraken.com/articles/4844359082772-linear-multi-collateral-derivatives-contract-specifications).

## Evidence, freshness and storage

Each public response retains its original body and hash, local request/receipt times,
monotonic round-trip duration and exchange server timestamp. Responses taking over
five seconds, an excessive clock offset or a local clock jump are rejected. Context
expires after 150 seconds. The exchange's response time does not prove that every
underlying field changed at that instant; last-trade time is not used as quote age.
Missing or stale data stays unknown and never becomes an invented zero.

Selected ticker bodies and normalized observations are permanent PostgreSQL events.
Order intents and fills include the available context and capture identifier.
Contract identity fields and metadata hashes are retained; the full hourly catalog
uses the existing bounded SQLite raw ring and can expire. A four-hour window holds
descriptive counts, ranges and first/last open interest for at most 64 contracts;
omissions are counted. Failure reviews retain the last context with time/causality
caveats. Strategy calculations, cash and risk checks do not consume these values.

The six-market live probe received 3,522 bytes of ticker bodies: roughly 4.84 MiB/day
at one cycle per minute before normalized fields, timestamps, indexes, journal links,
state rewrites, WAL and backups. This is a payload extrapolation, not a physical-disk
forecast. Full metadata is approximately one MB per hourly refresh in bounded raw
capture. Permanent context history grows; it is not covered by raw-ring pruning.
Including normalized observations and receipt envelopes, that probe's serialized
event was 11,964 bytes, approximately 16.4 MiB/day at six markets and one cycle per
minute before database overhead. The active universe and JSON sizes can change.

Coverage is one venue's perpetual market. Liquidation streams, CME/dated futures,
commodity futures, cross-venue totals and options chains are not connected. No claim
that futures improve the strategy is justified yet. A future test should predeclare
context rules and compare untouched control/challenger accounts on new observations
after costs; avoid tuning on the same outcomes used to judge the change.

## Options hypothesis and next requirements

Buying options with cash can produce large percentage gains, while the premium may
be lost entirely. Direction alone is insufficient: timing, volatility and spreads
affect the outcome. Exercise can also require more cash than the premium. These are
reasons to model the full lifecycle, not assume that cash funding removes leverage.
See the Options Industry Council's
[long-call explanation](https://prd-web.optionseducation.org/strategies/all-strategies/long-call).

The proposal is a separate paper experiment using actual time-stamped option and
underlying quotes, actual deliverables/multipliers, conservative delayed fills,
fees, settlement and explicit expiry/exercise handling. It must keep premium and
fees within the cash and risk budget; a stop is not a guarantee of recovering part
of the premium. With only $100 and unchanged limits, some periods may have no eligible
contracts. Cheapness alone does not qualify a contract. Covered sales additionally
need reserved underlying coverage. Naked sales and futures orders are excluded.

Predeclare the evaluation horizon, preserve full-premium losses, distinguish open
attempts from failures, and compare $100-to-$1,000 outcomes after all funding and
costs. A few large option winners do not establish majority success. No options
feed or simulator is implemented by this change, and no broker account, paid data
subscription or live order was created.
