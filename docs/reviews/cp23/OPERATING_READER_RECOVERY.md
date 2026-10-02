# Operational CP18 reader repair and capacity diagnosis

This bounded repair follows the approved installation of main `4c3e78a` and stays
under issue #28. It does not complete model qualification, mature feedback,
sustained operation or economic acceptance.

## Distinct diagnoses and source changes

The installed financial-activity connection fails when reconstructed from
`connection.info.dsn` alone; the authenticated read-only connection reads the
durable activity rows. A private actual-driver probe confirmed that authentication
failure without publishing credentials. The endpoint now carries the password
through proper connection-string encoding, retains existing connection options,
and bounds connection establishment. The retained-learning-report export reuses
the already authenticated scoped read-only reader too.

The earlier `OutOfOrderTransactionNesting` has a separate actual-driver
reproduction: a financial control and candle collection open overlapping native
transaction scopes on the shared writer connection. Whole candle transactions now
take the same existing reentrant writer lock as financial transactions. Journal,
bar immutability, candle-revision validation and financial calculations remain
unchanged. No inference or dependency wait is placed inside that lock.

On unchanged main, the paired regression file produces three failures: two private
authentication-option contracts and the native transaction race. Its unrelated
connection-outage control passes. The repair's focused reader/store/activity/history
selection passes 33 cases; the added transaction/guard diagnostics receive their
own final full-suite verification. Failed test-setup attempts are retained
privately and are not counted as product reproductions.

The installed fault recurred at 2026-10-02 04:05:14 UTC, before the new model
supervisor/development attempt. Its private log again names
`OutOfOrderTransactionNesting` in candle collection. The full financial admission
check subsequently rejects a stale/error paper worker even after its resource
cooldown has expired. A cleared capacity flag is not healthy admission.

The real disposable SCRAM probe requires rejection of the redacted login before
acceptance. Activity, trade-history, scoped outcome and retained-report reads then
pass, retain original evidence dates separately from query time, expose no password,
and preserve financial state/events and reconciliation. Only a generated QA role
and schema are used; their removal and restoration of the original QA HBA hash are
verified. Operating database authentication is not modified.

## Resource evidence and measurement correction

Fresh operating measurements observed repeated slow engine work and a five-minute
cooldown, sufficient local/G: free space, and later a naturally open guard. That
brief admission is not sustained capacity proof. The old `commit_p95_ms` also
included post-commit compact capture. It cannot establish database commit latency
or locate the whole-loop bottleneck by itself.

Actual CPython 3.12.10 reports `GetTickCount64()`/15.625 ms resolution for
`monotonic()` versus `QueryPerformanceCounter()`/0.0001 ms for `perf_counter()`.
A read-only query of 150 coalesced guard receipts yielded 1,060 distinct selected
work samples: the old clock classified 49 as slow despite precise durations at or
below 100 ms, and missed one precise duration above 100 ms. This selected diagnostic
population is not a distribution of every work item, nor proof that every cooldown
was unnecessary. The guard now measures the identical entire work interval using
the precise counter. The four-sample/100 ms, single-1,000 ms and 300-second rules
are unchanged. Four normal-loop cases put elapsed work in post-commit capture and
verify both directions at the repeated and severe boundaries using actual financial
transactions; all four fail on unchanged main and pass on the repair.
Python documents the intended short-duration clock in
[the performance-counter reference](https://docs.python.org/3.12/library/time.html#time.perf_counter).

The new diagnostics separate writer-lock wait, state read/decode, projection
verification, financial calculation/invariants, journal append, projection encoding,
database update and commit. Tiered work additionally records state-before capture,
the financial tick, compact capture and full capture. Nested phases are identified
by name; they must not be summed with their enclosing transaction phase. Current
work/window samples and explicit cooldown/disk/capture blocking conditions distinguish
fresh work from an old trigger. The commit percentile now measures the actual
transaction, while the unchanged admission guard still measures the entire work.

Private diagnostics used the actual retained projection, approximately 660 KB of
JSON, from installed PostgreSQL 18.6. Detached calculations and a copied projection
on owned PostgreSQL 17.2 are separate evidence: no operating write was made and no
full retained-event population was copied. In the 30-per-variant randomized
compression probe, pglz median total was 43.234 ms versus 34.037 ms for LZ4. All
copied states matched and the generated schema was removed. This limited saving
does not explain the observed intermittent operating stalls, so compression and
account-history retention are not changed by this repair.

The operating bottleneck still needs an admitted installed observation with the
new stage timings. Source/QA timing is not installed measurement. Guard thresholds,
cooldown, disk/capture requirements and financial/evidence records are preserved.
Do not raise a limit, disable capture or change placement to manufacture admission.

## Current model and remaining acceptance

Current development/qualification uses the approved dedicated sequential CPU
runtime and existing Qwen3.5 4B weights only. Every attempted dispatch checks actual
operating admission. The new bounded development attempt waited 602.747 seconds
and sent **zero model requests** because the installed paper worker was stale/error.
The service alone and this refused attempt provide no role qualification. The
failed receipt is preserved, and holdout stays withheld unless independent 4/4
screens pass for both roles, then each 36-case/three-seed population must complete
with at least 34 correct and zero critical violations.

The bounded new repair stays draft pending applicable merge/install authorization.
After installation, verify the normal activity UI's genuine market, evaluation,
research, pending-outcome and model-work dates, restored-reader polling and financial
preservation. A separately owned real-paper cycle must still show actual qualified
answers, deterministic checks, mandatory review, ordinary matched accounts, its
frozen genuine elapsed maturity, retained result and supported continuation.
Operating activation, CP23 sustained usefulness, native SEC access, actual Crik
connectivity and subsequent economic evidence remain separate requirements.
