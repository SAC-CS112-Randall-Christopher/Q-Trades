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

No operating accounts, installation, storage migration, downloads, paid calls,
merges or agent activation are authorized. Prior explicit authorization permits
bounded installed-model tests on the dedicated isolated CPU QA service; it does
not waive paper-resource admission or permit installed reconfiguration.

## Requirements and evidence ledger

| Checkpoint | Implementation / proof | Current limitation |
|---|---|---|
| CP17 | Delivered draft #29 at 32b5fc49; 580 native tests, no skips; exact-head hosted SUCCESS | Finite software/browser/native proof; see reviews/cp17/README.md |
| CP18 | Source implements evidence/idea/check/review/inbox/outcome/follow-up; actual dedicated CPU runtime observed | Operating resource guard blocks qualification; see CP18_QUALIFIED_ROLE_LOOP.md |
| CP19 | Planned after CP18 contracts | No two-generation role trace yet |
| CP20 | Planned historical-memory filter; assess supported data first | No new runtime component yet |
| CP21 | Planned controlled actor/task/evidence access | Actual scoped external transport unverified |
| CP22 | Planned shared scoped task path | Actual external transport unverified |
| CP23 | Planned integrated acceptance | No installed/prospective/economic claim |

Evidence stages are separate: planned, implemented, software verified, actual role
tested, installed verified, prospectively evaluated, economic value supported.
