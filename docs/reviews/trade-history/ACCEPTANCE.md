# Trade history acceptance

October 1, 2026. Software/display verification with synthetic disposable data.

The ordered requests in [the contract](../../TRADE_HISTORY.md) are implemented.
Orders defaults to Trade history with Account first, all accounts selected and
newest activity first. Entry/exit and net USD/percent results occupy one row;
gains are green, losses red, open positions amber, and zero results neutral.
The account/status filters, older/newer/latest pagination and optional cost details
use permanent evidence. Positions & pending and Journal remain separate tabs.
The journal component and original journal API/export logic are unchanged.

The new GET API runs in a worker thread on a separate repeatable-read, read-only
PostgreSQL connection. An additive partial index locates original entry fills;
no event or journal is rewritten. Retired identities remain searchable through
the same history endpoint. Full paging crosses the 1,000-entry rolling cache.
Entry/exit prices require retained fills and coherent original financial receipts.
Closed P/L is the original recorded result; missing prices remain unavailable.
Open estimates use frozen execution costs and fresh executable depth. Known partial
realized results remain distinct from the remaining unrealized estimate.

Observed local checks:

- 17 focused checks passed in 4.19 seconds, including actual engine partial exits,
  archived-account retrieval, reopening, 1,027 retained closures and read-only API
  preservation. Synthetic generated read-model records are not market performance.
- 48 affected engine/store/API checks passed in 9.96 seconds.
- Full suite: 563 passed, zero skips, 155.04 seconds, with isolated PostgreSQL.
- Ruff passes; strict Windows-targeted mypy passes for 73 source files.
- TypeScript/Vite build passes with 1,920 modules.
- Normal browser/API checks: default all-six-account rows; single-account and
  closed-only filters; cost details; original oldest-first 100-event journal;
  six holdings; 50-closure first page and 22-closure older page with no repeated
  open rows; newer navigation; stale open marks with closed gains/losses retained;
  visible 503 read failure and normal Refresh recovery.

The final reusable offline fixture is `scripts/verify_trade_history.py`. It refuses
the installed port/database, creates a generated schema on QA PostgreSQL port 55633,
labels the normal dashboard Synthetic QA, uses actual engine fills and journals,
and drops only its own generated schema on clean shutdown. Local raw receipts,
browser snapshots and screenshots stay under ignored `data/trade-history-*`.
The final source build/browser reload and hosted gate are reported in the PR.

Retained failures: the first lint check found long lines, fixed by formatting the
new files. A hidden PostgreSQL launcher waited for its long-lived child; interrupting
that launch required recovery of this QA cluster. The original focused run records
7 failures, 8 passes and 1 connection-timeout error in 132.86 seconds. The next run
records 7 failures and 9 passes in 3.63 seconds: six assertions compared equivalent
Decimal zeros as strings, and one fixture expected an exit at a price outside its
existing limit. Corrected fixtures compare numeric zeros and supply the subsequent
executable observation; the engine's original cancellation/limit behavior is intact.
The first browser fixture omitted normalized instrument fields and contained only
four accounts/48 closures; its marks were truthfully unavailable. The corrected
fixture has six accounts/72 closures and fresh marks. An incorrect recorder cleanup
attribute caused a retained QA shutdown error; the offline fixture never starts
that recorder, so the invalid cleanup call was removed. None of these attempts is
substituted for a passing run or an installed-state claim.

One existing FastAPI/httpx deprecation warning remains. These checks establish the
history projection and software preservation, not trading profitability, external
provider reliability or an installed update. Merge, final-main hosted checks and
any authorized installation are distinct subsequent receipts.
