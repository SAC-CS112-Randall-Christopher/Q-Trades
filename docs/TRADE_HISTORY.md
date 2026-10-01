# Compact paper trade history

October 1, 2026 source work, based on merged main `6b059cf`.
The installed application was inspected read-only at that release before this work.
Its Orders page still has separate holdings and an oldest-first event journal.

Accepted requests, in order:

1. Show one row per trade: entry, exit, net dollar/percent result; green gains,
   red losses, amber open positions. Combine partial exits within one trade.
2. Keep the financial journal as it is; add a separate Trade history tab in Orders.
3. Default to all accounts and newest activity, with Account as the first column
   and an account filter. Page through all retained closed trades, including retired
   identities, rather than relying on the rolling recent-trades cache.

This is a read-only display projection. It does not change the engine, account
funding, risk, strategy, financial events or journal. Closed P/L comes from the
retained closure receipt after entry/exit fees. Percentage uses original entry cost
including entry fees. Prices are actual quantity-weighted fill prices, never stop
triggers or order limits. Missing legacy price inputs remain explicitly unavailable.
Open results are estimates using existing fresh executable books and the account's
frozen execution costs; partial realized results and remaining unrealized results
are separate in the row details. Stale books, dust and insufficient depth produce
unavailable estimates. Account operating charges remain in account economics.

Predeclared verification: use the separate QA PostgreSQL cluster and generated
schemas for complete/partial fills, losses/gains/zero, stale/depth/dust/unknown
inputs, archived identities, more than 1,000 retained closures, stable keyset pages,
account filtering, API errors and preservation/reopen. Verify the real API and
normal UI against a labelled synthetic disposable browser fixture: all accounts,
single account, state filter, older/newer pages, restart, original journal and row
details. Run the affected suite, full PostgreSQL suite, Ruff, strict mypy, dashboard
build and exact-head hosted gate. Retain failed attempts and observed limitations.

Chris subsequently requested merging the finished change and a screenshot.
Merge follows local verification and the exact-head hosted gate. Any installed
update/restart remains a separate action under the applicable human authorization.
No lab activation, financial mutation, provider call or model download is included.

Observed source/UI verification is recorded in
[the acceptance receipt](reviews/trade-history/ACCEPTANCE.md).

The first authorized installed rollout exposed a password-authentication dependency
masked by the original QA cluster. See the
[authenticated reader correction](reviews/trade-history/AUTH_READER.md) for its
retained failure, bounded diagnosis and stronger verification. The financial
preservation checks passed; installed API/browser acceptance remains a separate gate.
