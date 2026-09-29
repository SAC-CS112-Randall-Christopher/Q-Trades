# CP1 — paper-account risk and deliberate recovery

## What the operator can do

The Paper experiment now includes **Risk & recovery** for the primary account and
its comparison accounts. It identifies the held asset preventing a complete
valuation, differentiates an operator pause from a hard loss stop, and explains
which actions remain available. Exits still use their own market's data.

A reserved buy is cancelled when required portfolio marks are missing, stale,
future-dated or insufficient for liquidation. Its reservation is released once;
the cancellation does not add cash to the account. Restored data does not replay
that buy. A subsequent eligible signal must create a new order.

## Policy and history

New spot accounts use `cash-spot-hard-stop-v1`: the existing 35% drawdown threshold
latches; scheduled strategy reviews do not lower its reference or clear it, and
failed accounts are not automatically replenished. Existing sizing, fees, execution
costs, daily limits, and strategies are unchanged. No new options account is created
for a fresh default spot installation; already-existing options history is retained.

Saved accounts without a risk-policy field are identified as
`legacy-paper-review-v1`. Their historical review/refill rules are retained and
explicitly labeled. **Use hard-stop policy** is an account-scoped, confirmed operator
action: it records the change in the existing journal, preserves funding, balances,
positions, attempts, losses and the current reference, and cancels outstanding buys
for reevaluation. It cannot switch back to the less restrictive historical policy.
An unknown explicit policy blocks entries rather than becoming the legacy default.

There is no database replacement or new financial authority. Optional policy and
recovery fields live in the existing account JSON and the existing append-only
paper event journal. Pre-CP1 records remain readable without a destructive migration.

## Recovery

**Resume within existing loss limit** is available only when the account has a
fresh complete valuation above 65% of its unchanged current high-water risk
reference, and no daily pause, failure stop, operator pause or cooldown still blocks
it. Recovery never lowers the reference, injects money, changes the strategy,
increments the attempt number or resets performance history. A cash-only account
still below that limit cannot recover by clicking a button. New campaign/account
creation is later CP3 work, not an implicit refill here.

The account's stop number scopes recovery to the stop the operator saw. A repeated
successful request is a no-op, including after restart; an old request cannot clear
a newer stop. The recovery receipt is persisted in the same transaction as the
account update. Denied requests leave financial state unchanged. API controls use
the existing loopback operator/same-origin boundary and reject arbitrary funding,
policy or risk-limit fields. Normal paper orders do not require manual approval.

The global entry control clears only the operator pause, not a hard stop. Failed
requests remain visible in the UI, and successful controls wait for normal status
refresh instead of fabricating a new account balance.

## Scope

This is an implementation and isolated-test checkpoint, not an operating Windows
cutover, profitable trading result, or completion of CP2–CP9. CP0's batch updater
and requested log path are unchanged. The original local experiment is not silently
converted to the new policy by pushing or later installing this code.

The next checkpoint is CP2: equal-capital whole-account economics, open P&L,
cost scenarios, and benchmarks. Its evaluation and venue-fee work is not claimed
by CP1's risk corrections.
