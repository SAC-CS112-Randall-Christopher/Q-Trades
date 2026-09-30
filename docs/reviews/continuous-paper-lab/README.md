# Continuous paper lab verification

All performance/lifecycle observations below use generated disposable schemas and
explicit synthetic inputs. The operating installed application was inspected
read-only in [the separate installed receipt](INSTALLED_READ_ONLY.md); no migration,
activation, cleanup, restart or deployment was performed.

## Post-audit source verification

The six independent findings at `bed73a1` are corrected in the working branch.
See [corrections and predeclared gates](AUDIT_CORRECTIONS.md). The final local
full suite passes **539 tests, zero skips, one existing test-client warning,
151.15 seconds**, with isolated PostgreSQL 17. Its five affected components pass
84 tests in 27.04 seconds; Ruff, strict mypy (72 source files) and dashboard build
pass. Thirty new audit regressions cover the six findings, shutdown failure and
capacity/status boundaries. Earlier 537/538/539 receipts retain their original
source stages. [Final checks](audit-checks.json), [source hashes](audit-source-manifest.json)
and [all correction receipts](audit-failures.json) remain distinct from original delivery.

The [first post-audit USB run](audit-native-first-failure.json) is a failed receipt:
four cases passed; ten/idle and twenty/busy each omitted one full and one compact
input at queue eight. Financial latency limits passed and every ledger balanced.
Backlog scheduling now continues immediately with unchanged queue/batch/durability
limits. [Corrected native measurement](audit-native-final.json) passes all six
cases with zero full/compact omissions and writer errors, queue peaks 5–8 and
financial-loop p95 23.02–62.96 ms under the original latency/storage limits:

| Accounts | Idle financial loop p95 ms | Busy research p95 ms |
| --- | ---: | ---: |
| 1 | 34.30 | 23.02 |
| 10 | 35.94 | 54.97 |
| 20 | 61.36 | 62.96 |

[Corrected controller soak](audit-soak-final.json) records 240 ticks over 59.81
seconds, restart at thirty seconds, twenty peak slots, 43 trial histories, 72
archived accounts and a balanced ledger; financial-loop p95 is 42.90 ms. Both
measurements are at `a61e8516`, after the six audit fixes and backlog continuation.
Later exceptional cancellation and empty capacity-recovery/status guards have
final-source regression/UI coverage; these benchmarks were not repeated at final head.

The [actual final browser replay](audit-browser-replay.json) opens an exact v2
capture from the normal UI while acquisition is capacity-blocked, completes its
isolated worker replay, reconciles the recorded state/events/journal, and reopens
the completed receipt from UI history. The one flat synthetic decision has no fills
or full-horizon economics. Five full evaluator tests independently capture, roll,
retain/reclaim, acquire all three exact packets plus compact input, evaluate in the
real worker and reconcile all three in replay; insufficient/inconclusive results
remain such. Legacy v1, mixed deduplication, unknown availability, source checks,
missing and oversized intervals retain truthful refusal.

[Final browser capacity observations](audit-browser-capacity-final.json) retain
the same capture/reference and unavailable quota reason 107.70 seconds apart.
Omitted full captures advance 102 -> 495, queue stays zero, paper processing remains
fresh/balanced and independent due checks advance. This exposed and corrected empty
passes briefly reporting recording and stale omission counters. Disposable tests
also verify blocked restart retaining its capture/reference, omission counts and
intake requirements through a bounded receipt for the identical frozen plan, then
recovery after restoring real space with every quota unchanged. That startup-only
correction followed the browser observation; its final-source proof is the disposable
restart regression/full suite. Separate
available/unavailable maturity tests preserve original sources and actual label times;
the browser fixture itself had no new due labels. Earlier browser failures are retained.

[Hosted source run 36788003672](audit-hosted-source.json), at `5cba53e`, passes 288
selected Windows tests with 58 PostgreSQL/environment skips in 94.23 seconds and
the TypeScript/Vite build. It follows the [cancelled source run](audit-hosted-cancelled.json),
which is retained as incomplete 183-pass/33-skip proof. Later capacity-status guards
follow that passing run; final exact-head hosted results are recorded in PR24/issue #1
after push, separately from the complete local PostgreSQL suite.

## Original bed73a1 delivery

Original local verification: **509 passed, no skips, one existing FastAPI/httpx
deprecation warning, 163.24 seconds** with the disposable PostgreSQL fixture.
Ruff passes; strict mypy passes all 71 source files; the dashboard type-check/build
passes. The chart bundle is lazy loaded. Hosted exact-head checks are reported
separately and cannot substitute for this PostgreSQL/native receipt.

The normal browser/API path started a frozen policy, admitted equal-funded paired
trials, preserved promising experimental parents, produced a lookback 10 -> 9
child and a separate range-reversion family, persisted both pauses, retired the
child with reconciled flat closure, reopened its original account/history and
frozen proposal/evaluation, and reopened an exact capture reference. See
[browser receipt](browser-acceptance.json). Outcome clocks and coverage were
explicitly accelerated fixtures. One full capture omission around that synthetic
clock transition remains disclosed as missing coverage. This is software proof,
not observed real-duration returns or qualification.

Disposable tests additionally exercise 36 sequential paired trials, twenty concurrent
managed/reserved slots, 72 immutable archived account identities, history pagination,
more than 512 proposals, rollback/lost acknowledgment, competing schedulers, initial
funding exact-once behavior, crash/restart, pause/protection, dust/uncertain orders,
data/risk stops, provider failure, UTC budgets and no reactivation of retired identities.
Slow presets freeze warmup, bar/progress/hold/outcome/review/retention together;
their real multi-day operation has not been observed.

The maturity correction has separate disposable available/unavailable tests for
already-due full and compact inputs after acquisition capacity stops. Original
files are byte-identical afterward, original hashes/references persist, price paths
remain separate from executable net labels, a linked loss stays negative, availability
is the actual later observation time, earlier cutoffs see pending, and restart/retry
does not emit another label. A sixteen-per-source pass drains twenty queued prefixes
over two passes; a resource stop leaves the work cursor pending until writable space
returns. No installed maturity reproduction was performed.
An additional physical-quota test fills the research tier to its normal acquisition
boundary and still records a truthful unavailable due receipt. At most 16 MiB of
declared scratch surplus is reserved for these outputs; complete-transfer scratch,
the physical tier quota and the volume free-space floor remain enforced.

## Original finite native receipts

[Final USB load](native-final.json) uses thirty seconds per case, four financial
ticks per second, 520 prior synthetic captures (~64 MiB payload), small 512-MiB
physical tier budgets and separate bounded capture writes. It is not a 100-GB
throughput or external-worker service-account durability benchmark.

| Accounts | Idle financial loop p95 ms | Busy research p95 ms |
| --- | ---: | ---: |
| 1 | 27.90 | 25.08 |
| 10 | 50.39 | 49.41 |
| 20 | 77.00 | 60.67 |

All six cases meet the unchanged declared limits. Capture queue peaks are 5–7
against a bound of eight; no full/compact inputs or writer errors were omitted.
Writer drain is 0.86–1.45 seconds and peak RSS is 75.87–82.21 MiB. Growth,
transaction/dispatch percentiles, CPU, physical PostgreSQL/archive sizes and history
are retained in the JSON. Sampled/compressed research data never supplies financial
authority or fabricated missed intervals.

[Final controller soak](soak-final.json) records 240 scheduled ticks over an actual
59.81 seconds (the predeclared sixty-second schedule starts with a tick at zero),
restart at thirty seconds, twenty peak slots, 43 retained trial histories, bounded
work and a balanced ledger. Financial loop p95 is 34.98 ms. This headless controller
fixture has no collected exchange candles and is explicitly not market or 24-hour proof.

## Retained failures and interruptions

- Initial full suite: 492 passed, 2 failed. An object-built memory fixture lacked
  the new optional feature cache; a financial reconciliation assignment was indented
  outside its loop. Focused and full repaired receipts were retained separately.
- Initial storage/API set: 20 passed, 4 failed. Windows fsync used a read-only file
  descriptor and the policy JSON round trip compared a tuple with a list. Corrected
  native writable fsync and JSON-compatible serialization preserve the old files.
- First expanded maturity full suite: 505 passed, 2 failed. A second maturity check
  after an acquisition failure replaced that pass's processed counter with zero.
  The independent check now runs once per batch and preserves its completed receipt.
- The first maturity-headroom test attempt passed eleven tests and failed one
  because its insertion split an existing test. Restoring the original test boundary
  produced twelve passing storage tests; the failed raw receipt is retained.
- [Initial synchronous USB diagnostic](native-initial-sync-failure.json): one-account
  financial-loop p95 626.86 ms. Serial per-record archive commits coupled to finance
  were replaced by bounded separate capture and one FULL commit per segment batch.
- [Pre-maturity native pass](native-pre-maturity-pass.json) remains a distinct earlier
  measurement. [Later overlap failure](native-maturity-overlap-failure.json) passed
  five cases and failed twenty/busy: loop p95 135.80 ms, transaction p95 111.70 ms.
  A separate browser QA financial writer was active in that measurement. Final
  native load closed that writer and passed; the failure remains valid evidence
  that the broader co-running QA workload did not meet the declared limits.
- Early native warmups and one later soak setup were interrupted. They are not
  accepted timed runs. Two original interrupted G: QA directories remain because
  automatic approval review rejected their removal as “blocked by policy.”
- Browser fixture metadata initially omitted minimum notional, correctly blocking
  admission. An early review helper rewound into an already-observed synthetic
  interval and returned inconclusive; a later helper lacked its tick binding. Both
  failures were retained. The final helper starts later than the latest financial
  observation, keeps the original review horizon, and uses explicit synthetic ticks.
- Earlier static/build attempts found an optional dictionary index, two long SQL
  strings and one newly inserted non-UTF-8 UI byte. These were corrected; final Ruff,
  strict mypy and dashboard build are recorded separately from failed attempts.

Private raw logs remain under ignored `data/`. Published JSON receipts are synthetic
and redact filesystem/volume identities. There are no skips in the observed local
full PostgreSQL suite; hosted checks without a PostgreSQL fixture have a narrower
scope and their skips must not be described as full native/PostgreSQL acceptance.
`source-manifest.json` hashes source/testing files with CRLF normalized to LF, so
the recorded SHA-256 values can be compared with the committed Git blobs.
Earlier performance and browser receipts describe their recorded stages; the final
physical-quota test and display-only headroom text followed those measurements.

## Remaining limits

No actual-market economic edge, untouched qualification window, seven-day live
trial, twenty-model concurrency, paid provider transport, installed external-drive
write, 100-GB capacity stress or twenty-four-hour reliability is established. The
retained tier stops honestly at its physical budget. CP7 human/28-day promotion
remains unchanged. Draft source delivery grants no rollout authority.
