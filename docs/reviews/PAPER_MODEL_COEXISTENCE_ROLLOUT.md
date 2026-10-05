# Installed coexistence repair receipt — October 5, 2026 UTC

PR [#60](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/pull/60) is
merged and installed after Chris explicitly approved the controlled release once
capacity and the required local checks recovered. This completes that release;
it does not complete concurrent trained-model operation or CP18/23.

## Tested content and release

| Evidence | Observed result |
| --- | --- |
| Reviewed source head | `ac59d06561757218f003162f5914d328169deedc` |
| Merged/installed main | `fca588586f9b72e9506caef6384ee8e65edea738` |
| Exact shared source tree | `4174b2eb699c8eeae52ae1093002ba36c9da8fd5` |
| Fresh native full suite | 1,040 passed, one skipped, one existing warning; 443.81 seconds |
| Native PostgreSQL | Separately owned 17.2, actual SCRAM/password authentication |
| New monitoring cases | All seven executed in that full run |
| Source identity | All 296 manifested source/test/dependency files unchanged |
| Installed bytes | All 220 checked release files match; installed marker agrees |

The fresh full run used real C: fixtures without a fixture override, resource
mock or changed assertion, clock, deadline or operating reserve. Its sole skip
is symlink creation without Windows Developer Mode. Previous failed or partial
runs remain failed or partial; this is a separately recorded successful run.
Local disk space had recovered before this run; the receipt does not attribute
that recovery to our earlier task-artifact cleanup.

The workflow has no push trigger, so merged-main verification was explicitly
dispatched against the exact merged commit. All three jobs succeeded in
[run 37303376159](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/actions/runs/37303376159):

| Merged-main job | Recorded result |
| --- | --- |
| Native | 635 passed / 196 skipped; dashboard built 1,930 modules |
| Runtime ownership | 46 passed |
| Complete PostgreSQL integration | 959 passed / 82 skipped; one existing warning |

These hosted selections and Windows/native execution remain distinct proof
stages. The exact source-tree comparison binds the reviewed local run to the
released implementation despite the expected merge-commit change.

## Controlled update and preservation

The existing updater took its ordinary source backup, used the reviewed process
ownership/shutdown procedure, installed the exact main and restarted the normal
paper task. No compression or storage-transition option was supplied. The update
finished successfully in 67 seconds. Startup's first two health requests were
unavailable; its third was ready at the exact release commit.

Authenticated read-only before/after receipts confirm:

- All 1,255,084 original events have identical ordered row hashes.
- All 13,023 original journal lines have identical ordered row hashes and balance.
- All eight existing accounts retain identity/version, funding and starting capital.
- All 247 checked configuration/evidence files have identical SHA-256 hashes.
- The application reports fresh paper work, a balanced journal and no paper error.

Ordinary recording appended new observations during the rollout; the after receipt
had 1,256,259 events. No history was truncated or regraded, no account was seeded
or replaced, and no financial reconciliation exception was needed. Twenty-slot
capacity, successful parents, financial locks, outcome maturity and the operating
400/100 decimal-GB G: policy remain intact. The earlier recording gap remains in
its historical receipt; current recording does not erase it.

## Installed inference-off observation

One expressly bounded observer polled normal status every five seconds for at
most 1,200 seconds, at lowered priority. It read the original development registry
without writing it. The observer completed and its separately owned QA PostgreSQL
was stopped; no continuing helper or observation schedule was left running.

| Metric | Result |
| --- | ---: |
| Actual elapsed time, including final sleep | 1,204.969 seconds |
| Status polls | 238 |
| Successful / unavailable polls | 237 / one `RemoteProtocolError` |
| Polls admitting research | Zero |
| Distinct retained financial-work samples | 1,951 |
| Whole-work median / p95 | 56.139 / 111.855 ms |
| Samples over 100 ms | 163 |
| Severe stalls at least one second | Two: 1,419.875 and 1,209.050 ms |
| Failed financial readbacks in successful polls | Zero |
| Reported stale/error paper states in successful polls | Zero |
| Available physical memory range | 56.435–59.484 GiB |
| Local free-space range during observation | 9.56–10.89 GiB |
| Actual model attempts | Zero |

The final blocking condition was `engine_work_cooldown`. Capture was healthy
with no reported discards. The original question remains queued at the idea stage
with zero attempts; the approved development attempt has not been consumed.
Normal health/activity/role API reads after observation succeeded at the installed
commit. No independent rendered-browser walkthrough was completed in this run.

Every observed portfolio was flat. This is actual installed observation, but it
does not establish protection of active positions or a twenty-slot loaded trial.
Other workstation work was uncontrolled, and brief owned isolated probes ran
during part of the interval. There was no matched old-release observation or
actual model workload; do not infer a causal installed speedup from the median.

The two severe intervals consumed only 62.5 and 31.25 ms of thread CPU. Their
large wall-time contributions were read/decode and projection encoding, rather
than financial calculations. These observations identify waiting/descheduling
as a remaining investigation target; they do not prove disk, scheduler, driver,
GIL contention or another process to be the unique cause. Separate development
workers were present; their ownership and data were preserved, and none was stopped
or reconfigured to manufacture a better result.

The unchanged policy remains: four slow samples among twenty, new work over
100 ms, a one-second severe stall and a five-minute cooldown. Offline arithmetic
over the same observed samples still ends in cooldown at hypothetical 125, 150
and 200 ms limits. That arithmetic neither changes policy nor proves an alternative
safe. Raising a limit merely to obtain a model run is not supported here.

## Bounded alternatives investigated and rejected

An authenticated read-only projection profile measured approximately 862 KB of
ASCII cache JSON, including approximately 608 KB of account state. Across three
one-second differences, only the valuation timestamp changed within each of the
eight account objects, alongside ordinary root-level changes. Raw values and
the copied projection remain private.

The installed server is PostgreSQL 18.6. A twenty-second read-only statistics
slice recorded 45 new block reads and 46,216 hits, approximately 99.9% hits,
30 projection updates and approximately 414 KB/second of WAL. The current
projection relation, including TOAST/indexes, was approximately 24.6 MB; the event
relation approximately 816.6 MB. These are a short measured slice, not a storage
growth forecast or permission to tune durability. Database counters did not show
an active SQL lock blocker at the sampled instants. A first statistics query used
removed WAL-view columns and failed read-only; the probe was corrected without
changing application code or guards.

Two private comparisons used the copied retained projection, not operating writes:

| Candidate | Matched measured baseline | Candidate result | Decision |
| --- | --- | --- | --- |
| Smaller SQL object merge, 40 samples per method, full/merge/merge/full blocks | Full update median 27.835 ms / p95 47.700 ms; approximately 862 KB payload | Merge median 39.848 ms / p95 50.328 ms; approximately 43 KB payload | Reject: less payload but slower measured update |
| Process-private binary RAM copy, forty alternating samples per method | Current JSON encode/decode median 15.478 ms / p95 20.893 ms | Exact numeric normalization plus binary copy median 22.906 ms / p95 32.927 ms | Reject: its correctness overhead removes the decoding advantage |

Every saved SQL candidate projection matched its ordinary full-update counterpart.
The SQL comparison was on separately owned native PostgreSQL 17.2 with the existing
LZ4 setting, not the installed Docker server; it does not establish installed latency.
The copy test used no database. Neither candidate was put in application source or
installed. No new dependency, model download, training, holdout or provider call was
needed. No operating PostgreSQL setting, memory allocation or durability was changed.

## Remaining acceptance

The financial-reader/cooldown/core-placement implementation is released and its
preservation verified. The next capacity decision must address measured waiting
or establish an explicitly tested resource policy; more RAM is not an established
remedy to the observed high-hit-rate workload. Keep the original guard and approved
model identity/profile until that decision has applicable authorization.

One development answer from the actual pinned base plus trained v2 adapter still
has not happened. Its existing CPU float32/two-distinct-physical-core/600-second
attempt remains authorized when the complete guard admits it, with the original
24-GiB RSS ceiling and eight-GiB reserve. Operating roles remain disabled and
unqualified. Qualification, a genuinely mature ordinary paper feedback loop,
correct continuation, sustained protection and CP23 usefulness are still open.
No synthetic answer, changed clock or weaker financial authority can replace them.

This receipt is a source documentation successor. PR #57's separate earlier
rollout record and all older failures/receipts remain unchanged. Detailed logs,
hashes, account records, DSNs, process identities and model artifacts remain private.
