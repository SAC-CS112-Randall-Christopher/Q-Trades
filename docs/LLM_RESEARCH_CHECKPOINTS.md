# Current implementation: issue #28, CP17–CP23

Work order: https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/issues/28
Implementation addendum: issue comment 5933501730. Integration owner: this
assignment, starting from main `6fc72dccb51e07e00b30bd5c880234c13099297b`.
Prerequisite #27 is merged; its projection and retained failures are preserved.

## Acceptance declared before execution

CP17 uses bounded selected-account, immutable snapshot receipts, authenticated
read-only PostgreSQL, the existing G: research tiers, and the existing information
authority. Ordinary overview target is 4–8 KiB where adequate; the hard receipt
limit remains 131,072 UTF-8 bytes. Detail pages contain at most 30 candle/indicator
rows or 20 financial events; hot journal rollover is at most eight receipts per
pass. Cross 5,000 logical receipts without losing earlier IDs or errors. Retain
failed attempts; no unreported truncation or current-data historical substitute.

Native measurements retain the existing 100 ms financial-loop p95, 512 MiB RSS
and 64 MiB growth limits. Measure query/serialization percentiles and actual bytes
on declared fixtures; sparse/small fixtures are not 100-GB or 24/7 proof. Normal
browser checks use an isolated app/database and synthetic market observations.
Password-authenticated checks use a separately owned disposable cluster.

No operating accounts, installation, storage migration, model service, downloads,
paid calls, merges or activation are authorized. Only draft source PRs.

## Requirements and evidence ledger

| Checkpoint | Implementation / proof | Current limitation |
|---|---|---|
| CP17 | Implemented: scoped tools, durable outcomes, verified rollover and disclosure | Finite software/browser/native proof; see reviews/cp17/README.md |
| CP18 | Read-only preflight: no trading listener at 11435; old qualification incomplete | Real-model operational proof blocked; do independent source work |
| CP19 | Planned after CP18 contracts | No two-generation role trace yet |
| CP20 | Planned historical-memory filter; assess supported data first | No new runtime component yet |
| CP21 | Independent official source work eligible after scoped contracts | Providers/entitlements unverified |
| CP22 | Planned shared scoped task path | Actual external transport unverified |
| CP23 | Planned integrated acceptance | No installed/prospective/economic claim |

Evidence stages are separate: planned, implemented, software verified, actual role
tested, installed verified, prospectively evaluated, economic value supported.
