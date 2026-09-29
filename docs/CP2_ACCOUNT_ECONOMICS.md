# CP2 — Whole-account economics and execution assumptions

## Operator workflow

The normal Paper screen now includes **Whole-account economics**. Select an account
and a current or completed common window. Current balances, reserved cash, realized
and open P&L are separate from window returns and trade counts. Missing holding
marks display unavailable results; old complete windows remain historical evidence.

Open **Execution and operating-cost assumptions** to select a prospective fee
scenario and an estimated daily operating allocation. A fee change requires a flat
account with no pending orders and explicit confirmation. Existing fees, balances,
orders, risk policies and prior results are not regraded. Repeated submissions are
idempotent; stale settings versions refuse replacement. An empty operating field is
**unknown**, whereas zero is an explicitly declared zero-cost scenario.

The new-account constructor supports $50 or $100 and a declared execution profile.
Existing accounts are not reset by calling initialization again. The existing paired
universe accounts inherit a new installation's declared capital/profile; previously
created pairs are not converted. Campaign/account creation in the UI belongs to CP3.
There is no capital-editing or funding endpoint in CP2.

## What the numbers mean

- Liquidation equity = owned cash plus estimated executable liquidation proceeds of
  all holdings, after modeled exit costs. Reserved cash is part of cash, not extra
  capital. An incomplete liquidation mark does not become a partial positive total.
- Open P&L = liquidation equity minus cash minus remaining position cost basis.
  That basis includes paid entry fees. Realized plus open P&L reconciles to equity
  minus cumulative external funding when complete marks are available.
- Window net trading P&L = ending equity minus starting equity minus external flows.
  Trading returns use the existing unitized equity, so replenishment is not profit.
  A zero/undefined unit reference is not presented as a return recovery. Its loss
  remains recorded. Windows with funding changes are not ranked or promoted.
- Execution-cost attribution includes paid fees and the change in embedded
  spread/depth/adverse-price costs and estimated exit costs. Gross reference minus
  this attribution equals net trading. It is not a frictionless backtest. Exit-cost
  estimates can reverse when realized; this is not a negative commission charge.
- Operating allocation = the operator's estimated USD/day times elapsed seconds /
  86400. It is reporting only, not a cash debit, provider bill or measured GPU cost.
  Total economics subtract it **once** from net trading P&L. Shared costs should be
  allocated deliberately; counterfactual accounts and their budgets are not pooled.

## Comparison and selection

Observations begin prospectively on the first CP2 tick. Historical trades are not
used to manufacture missing equity curves. Every account has the same window start
and end; windows nominally last four hours and close on an observed tick. Gaps over
30 seconds, missing marks, undefined returns, or changed strategy/risk/cost settings
make the affected comparison incomplete. The current window is explicitly provisional.

Ranks use returns **after operating allocation**, within identical original-capital,
cumulative-funding, execution-profile, risk-policy and operating-allocation groups.
Unknown operating costs do not become zero-cost rankings. Individual account returns
are never summed into a realizable portfolio. Closed trades/wins are diagnostics,
not a substitute for account growth. Idle cash and trades crossing window boundaries
remain in the equity calculation.

Bounded paper selection requires two completed nonoverlapping eligible windows,
matched assumptions for incumbent/challenger/primary, positive total economics,
after-operating return above cash and exposure controls, at least 0.1 percentage
point above the incumbent in each window, and no worse observed drawdown. Qualified
candidates are compared by **compounded**, not added, window returns. The primary
changes only while flat. There is no minimum-trade quota. This remains a heuristic
paper comparison, not statistical confidence or proof of repeatable profitability;
protected experimentation and stronger qualification are later checkpoints.

## Predeclared controls

Cash earns 0% before the same operating allocation. The exposure control is a fresh
50/50 BTC/ETH allocation **at each window's start**, funded hypothetically from that
account's window-opening equity. It buys once using later observed books and holds
until that window ends. It pays modeled entry and liquidation costs. This is a
four-hour allocation alternative, **not a continuously held buy-and-hold portfolio**.
Neither control is a spendable account or an additional financial ledger.

Control fills share the strategy engine's book-walking, participation, precision,
adverse-price and fee implementation. Same-budget/profile controls reuse one
calculation. Partial IOC fills cancel the remainder; nonfills retain cash. Missing
inputs and unliquidatable dust remain incomplete rather than invented fills/marks.
Original books and instrument metadata are retained in benchmark-fill events.

## Frozen execution profiles — sources checked September 29, 2026

`paper-rest-ioc-v1` retains the original **0.10% taker fee per side** as a fee-stress
scenario. An absent profile identifies this historical assumption. It remains the
default; upgrading software does not silently select cheaper fees.

`binance-us-public-2026-09-29-v1` records the published standard **0.02% taker**
schedule, with **0.01% for BNB/USD**, as an optional paper assumption. The public
maker rate is 0%, but CP2 does **not** model resting maker orders or free maker fills.
The simulated orders are taker IOC orders. BNB-payment discounts and high-volume
VIP tiers are not applied. Public source: https://www.binance.us/fees .

Both profiles retain a one-second minimum later-book delay, 15-second observation
expiry, two basis points of adverse price movement, and 10% participation in visible
depth. They use observed LOT_SIZE, PRICE_FILTER and minimum-notional constraints,
not a universal invented symbol precision. A cancel cannot release reservations
twice; an absent cancelled order cannot fill later.

**USD-quote fee charging is a research assumption, not a verified account contract.**
The venue documentation supports commissions in different assets. Base-asset/BNB
fee payment is unsupported and rejected, not converted without evidence. Paper sale
proceeds become usable only after the fill commits; there is no deposit credit,
borrowing, authenticated venue request, or live settlement/eligibility claim.

API contract source: https://docs.binance.us/ (filters, commissionAsset, execution
reports, timeout/unknown execution status). Queue position, hidden liquidity, market
impact, real broker acknowledgments, deposits and transfer finality remain outside
this simulator. A touched price does not prove a maker fill. Do not edit a frozen
profile ID to reinterpret earlier trades; introduce a new version.

## Storage, operation and compatibility

The existing paper-state transaction stores a bounded current window plus two
completed summaries. Completed windows, benchmark fills and setting changes are
retained as append-only events in the existing journal store. Existing transaction
rollback and writer ownership apply. Fee and fake-funding balances are now included
in reconciliation alongside cash, reserves and inventory. There is no new database,
separate financial authority, model call or quote-time fee API lookup.

The Paper screen, Strategy Lab and cost-hurdle tool use consistent profile/ranking
language. Older review results retain their historical scoring label. The detached
numerical-model preflight remains frozen on its original legacy assumptions; it is
not silently repriced or promoted by CP2. Future registry integration must declare
its execution profile explicitly.

The simple CP0 batch updater and requested log location are unchanged. No running
Windows source, account, policy, model runtime or database was modified by this work.
Apply only approved forward main updates. Pre-CP2 code does not understand the new
fee fields; restoring old source over new-profile history is not a supported rollback.
See the implementation audit for executed checks and remaining native acceptance.
