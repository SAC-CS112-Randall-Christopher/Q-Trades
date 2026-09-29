# Expanding the paper-trading market universe

Research and recommendation, 2026-09-27. The running experiment still trades only
BTC/USD and ETH/USD. No strategy, risk ceiling, funding, or execution rule changed
during this investigation.

## Finding

Expand market observation and test selective participation in other liquid USD
pairs. BTC/ETH are an initial operational baseline, not a demonstrated optimal
universe. A large historical price range alone does not establish executable
profit, predictive value, or a higher probability of reaching $1,000 from $100.

## Public-market evidence

At 23:35 UTC / 17:35 Denver, Binance.US public exchange information listed 54 USD
pairs with status TRADING and spot trading allowed. This count includes stablecoin
pairs; public listing status is not confirmation of account or jurisdiction eligibility.
There were also 202 USDT pairs. USD and USDT balances must remain distinct.

The following combines rolling 24-hour ticker statistics sampled at 23:35:46 UTC
with individual order books sampled at 23:36:27-29 UTC. These are observations,
not performance results or a prediction of which coin will rise next.

| Pair | 24-hour high/low range | 24-hour quote volume | Quoted spread at book sample |
|---|---:|---:|---:|
| BTC/USD | 1.18% | $1,692,252 | 0.000095% |
| ETH/USD | 1.95% | $563,718 | 0.00633% |
| SUI/USD | 11.60% | $261,610 | 0.06355% |
| ONE/USD | 61.44% | $3,312 | 27.02307% |

Range is `(high / low - 1) * 100`; spread is `(ask - bid) / midpoint * 100`.
The high/low range does not imply a feasible low-to-high trade or even an upward
move. ONE/USD's net 24-hour price change in the ticker sample was -11.103%.
At the later book sample, its best bid was 0.001181 and ask was 0.001550.
Buying at that ask and immediately selling at that bid would lose approximately
23.81% before fees, even assuming both displayed quotes could be executed in the
required size. The current 25-basis-point spread ceiling would reject this entry.
SUI's narrower spread warrants study; it does not prove an entry signal or profit.

Raw, timestamped responses are retained locally in:

- `data/research/universe-20260927T233546Z.json`
- `data/research/depth-20260927T2336.json`

Sources: [exchange information](https://api.binance.us/api/v3/exchangeInfo),
[24-hour ticker](https://api.binance.us/api/v3/ticker/24hr), and
[public depth API documentation](https://docs.binance.us/#get-order-book-depth).

## Proposed experiment

1. Screen the available USD universe, excluding stablecoin bases from the directional
   momentum ranking. Preserve timestamped membership, rejected pairs, and delistings.
2. Apply the foundation's eligibility rules before ranking: usable price history,
   current instrument filters, trade activity, spread, entry and exit depth, freshness,
   minimum order sizes, and existing portfolio concentration limits.
3. Study a bounded shortlist, initially 5-10 eligible pairs. Rank unusually strong
   activity relative to each pair's own history, sustained momentum, volatility,
   and estimated costs. SOL/USD, XRP/USD, DOGE/USD, and SUI/USD are examples from
   this snapshot to investigate, not permanently approved trades.
4. Compare one separately versioned wider-universe paper candidate with the frozen
   BTC/ETH baseline using the same dates, $100 starting capital, risk limits, and
   execution assumptions. Do not pool accounts or select winners retrospectively.
5. Review every four hours, but change a version only after sufficient fresh evidence.
   Record losses, fees, rejected opportunities, time to target, unresolved attempts,
   and below-$5 failures. Report attempts reaching $1,000, not just winning trades.
   A common evaluation horizon must be declared before calling a majority successful;
   open attempts cannot silently disappear from the denominator.

The existing REST polling and closed-minute-bar signals do not validate subsecond
spike capture. Before a fast-move strategy is evaluated, implement and verify streamed
trades/books, gap recovery, observation timing, delayed fills, and adverse exit
execution. Binance.US documents public book streams at 100ms or 1000ms; that update
frequency is not an execution-latency guarantee. Portfolio risk limits remain fixed.

Sources: [Binance.US streams](https://docs.binance.us/#partial-order-book-depth-stream),
[CFTC discussion of thin-market pump and dump risks](https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/beware_virtual_currency_pump_dump.html).

## Cost-model observation

The current simulator intentionally records 0.10% per-side fees as an assumption.
The public fee page retrieved during this research advertised 0.02% taker fees on
most spot pairs and 0.01% on BNB/USD, before any applicable discount. No authenticated
account fee schedule was queried. Retain the existing assumption for the baseline;
any change must be a new cost-model version and must never regrade prior outcomes.

Source: [Binance.US published fees](https://www.binance.us/fees).

This one market snapshot establishes neither a persistent liquidity ranking nor a
profitable strategy. Broader observation is the recommendation; majority success
at a tenfold account return remains an unproven research goal.
