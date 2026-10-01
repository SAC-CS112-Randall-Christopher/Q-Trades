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
| CP18 | Draft #30, 9ab26c0; 597 native/no skips; exact hosted green; complete source result-feedback workflow | Operating resource guard blocks qualification; see CP18_QUALIFIED_ROLE_LOOP.md |
| CP19 | Draft #31, 408c5af; 600 native/no skips; exact hosted green; referenced lessons/different-test selection | Two-generation synthetic software proof; actual-model trace blocked |
| CP20 | Draft #32, 7f9f9ba; 604 native/no skips; exact hosted green; single frozen entry filter | Synthetic source proof; actual fitted role discovery unverified |
| CP21 | Draft #33, d0f8e0d; 614 native/no skips; exact hosted green; SEC facts and public IBM study | Actual IBM native read; SEC HTTP 403/cooldown; entitled vintage unverified |
| CP22 | Draft #34, dd55b89; 622 native/no skips; exact hosted green; shared scoped leases/result lifecycle | Actual Crik/authorized bridge absent; see CP22_SCOPED_COLLABORATION.md |
| CP23 | Final full-tested product source 197e5a1: 629 native/no skips, typing/build, SCRAM reader, desktop/mobile/retry and finite native measurements; see reviews/cp23 | Actual qualified-model workload/trace and matched quality comparison blocked; prospective/economic observation insufficient |

Evidence stages are separate: planned, implemented, software verified, actual role
tested, installed verified, prospectively evaluated, economic value supported.

## Final integration and remaining required observations

[CP23 finite declaration](CP23_ACCEPTANCE_PLAN.md) preceded measurement.
[Observed native/browser/fault ledger](reviews/cp23/README.md) identifies exact
proof and original failed attempts. [Rollout handoff](CP23_ROLLOUT_HANDOFF.md)
is concrete but has not been executed. Final delivery-head hosted evidence is in
its draft/issue, separate from the frozen measured product source.

Actual CP18 is the first complete LLM milestone and remains unmet. Current v5
qualification, actual guard-admitted trace through mature paper outcome/follow-up,
actual busy model load and matched usefulness/cost comparisons require eligible
runtime evidence. Native SEC denial/cooldown and unavailable Crik bridge remain
precise provider limits. No actual installed, prospective or economic stage is
claimed from software stubs. All draft PRs stay unmerged; no operating state was
changed by this source work.
