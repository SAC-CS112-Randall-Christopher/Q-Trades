# Re-audit interaction repairs in the existing draft stack

The independent re-audit of `a21637dd543368f8ed405b9bde575ea8ea122838`
closed F1/F3/F4/F5/F7 and reproduced three remaining F2/F6 interactions.
Those closed repairs are preserved. This delivery corrects the three interactions
in their existing owning drafts; independent confirmation remains with the reviewer.
No review thread is resolved by this implementation.

## Supervisor recovery: R1 / F2, PR #31

The normal background loop supervises dependency discovery, follow-up selection
and dispatch separately. Actual PostgreSQL operational/interface failures and
temporary storage failures receive a recorded thirty-second retry. Dependency
failures preserve the exact wait/source binding and allow unrelated questions to
progress. Phase failures survive worker reconstruction; cancellation exits normally.
Programming or metadata-consistency failures remain visible and propagate instead
of becoming perpetual outage retries. The outstanding supervisor state is available
in the existing role status response.

The acceptance test creates an ordinary pending comparison and a software answer
selecting its offered mature outcome. It directs only the research reader to an
owned, bound but non-listening port, using the actual authenticated PostgreSQL
driver. The real background loop survives the connection failure, records its
cooldown and progresses independent work. Restoring the reader, recording declared
synthetic maturity and advancing the fixture clock yields exactly one correctly
bound successor without restarting the supervisor. A second normal-loop test
restores an unavailable owned storage plan and verifies the same preservation and
continuation. Journal reconciliation remains balanced.

## Original late answer and archival: R2 / F6, PRs #30 and #35

Archival excludes any task with an unanswered attempt whose original transport
has not returned. Lease expiry, failure classification and explicit retry cannot
retire that attempt while its receipt can still arrive. When it returns, the
existing immutable receipt and ownership controls reconcile uncertainty without
replacing a newer attempt or dispatching from an expired owner. A missing attempt
now prevents requeueing: answer persistence must update exactly one retained row.
The archive hash/metadata consistency checks remain unchanged.

Paired tests run real archival pressure before and after a delayed software answer,
with and without an explicit retry. The no-retry path calls the original answer
once and reuses it without a fresh verdict. The explicitly authorized retry path
retains both answers and never lets the older answer overwrite the newer result.
Final archival and reconstruction retain the exact receipts and reserved costs
once, with balanced journals. Stub reservation accounting is not measured model
token use. Unreturned uncertainty remains hot under existing storage/hot bounds;
no completion or automatic abandonment is invented.

## Durable follow-up eligibility: R3 / F6, PRs #30 and #31

Completion records a small indexed pending-follow-up row transactionally,
independently of the large result. Archival therefore cannot erase eligibility.
Selection consumes that row only after recording a supported successor or a
supported wait. Deferred and unknown-acknowledgment selections retain the stable
successor identity and retry state; restart reconciles rather than duplicating it.
The selector does not scan all archived payloads each tick.

Eight paired ordinary disposable-comparison tests cover hot/archived results before
initial selection, after deferral, after a lost committed acknowledgment and after
consumption. Each retains its exact outcome and produces one total successor or
keeps its already selected successor. Legacy cold history uses a saved row cursor
and fixed migration boundary, at most eight records per pass. Tests preserve
pending/consumed legacy state and verify that restart advances the cursor without
rescanning already examined cold records.

## Observed verification and exact source stages

Full-tested integrated product source:
`d435c881ccb091e5a48c3a3252ed3b14de9367fe`.
Later delivery changes only documentation and public receipts. Its exact final
delivery head and hosted run are recorded in draft #35 and issue #28.

| Check | Observed result |
|---|---|
| Complete native Windows suite, owned PostgreSQL | **686 passed, zero skips, 253.73 s** |
| Integrated supervisor/history/lesson/actor/question/packet checks | **66 passed, zero skips, 86.13 s** |
| Whole-repository Ruff | Passed |
| Strict Windows-targeted mypy | Passed, 84 source files |
| TypeScript/Vite build | Passed, 1,926 transformed modules |
| Native environment, directly verified | CPython **3.12.10**, PostgreSQL **17.2**, owned loopback cluster |

One existing Starlette/httpx deprecation warning remains. The auditor's independent
Linux **642 passed / 26 Windows-only skips**, CPython 3.12.14 / PostgreSQL 16.2
receipt is separately attributed; it is not this new native run's environment.

The original actual-driver supervisor failure, archived late-answer failure and
three archived follow-up failures are retained, along with their passing controls.
Initial missing-reader/storage setup errors, one corrected fixture context-key
error and two read-only environment-probe setup errors remain retained separately;
the environment errors occurred before pytest started. Product admission, stage,
storage and consistency guards were not weakened. Exact private receipt hashes,
changed-product file hashes, counts and a fresh bounded read-only installed
observation are in [the public software receipt](reaudit-integration-software-checks.json).

## Proof boundaries and preserved operation

The new combined scenarios use software answers and accelerated synthetic maturity:
zero actual model calls and zero market-provider calls. They prove software recovery
and retention. Earlier eight finite Windows/G: cases, rendered browser walkthrough,
public-source access and actual runtime development attempts retain their original
heads and attribution; they were not repeated in this backend repair pass.

Actual current-contract qualification, the qualified-model CP18 lifecycle, matched
qualified A/B/C/D value and prospective economic benefit remain unresolved. The
read-only installed sample still constrains optional research, and the dedicated
QA model service is absent. No qualification or admission requirement is waived.
An unwritable registry retains an in-memory cooldown because it cannot persist
its own failure at that instant; persisted recovery resumes when storage is writable.

The financial engine, original six/history, successful parents, twenty-slot
capacity, G: storage policy, outcome disclosure/maturity and inference outside
financial locks are preserved. All drafts remain unmerged. This work makes no
installed restart, deployment, operating activation/account/data/storage change,
model download or paid-service call. Live listener identity stability across other
activity is not claimed; the current read-only health observation is recorded.
