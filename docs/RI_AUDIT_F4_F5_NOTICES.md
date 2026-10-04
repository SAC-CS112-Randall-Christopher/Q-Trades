# October 4 selected-evidence and notice repairs

Owner: draft PR #52, issue #48. Original source head:
`fd029f7db12e04dc03c57f244c3385c20047575a`.
Updated PRs #40/#49/#50/#51 are merged into this draft without rewriting history.

| Finding | Original reproduction | Root correction | Verification | Remaining limitation |
| --- | --- | --- | --- | --- |
| F4: obsolete notice/lesson reads replace selected evidence | Original compiled UI displays A's notice or lesson after selecting B; removing the lesson parameter retains unrelated detail | Use PR #51's generation/abort hook and verify response identity. Fence success, error and loading updates. Store source identity in the URL, restore it on history/reload, and clear it when the parameter disappears. Unmount aborts obsolete reads | Compiled repaired UI: delayed success/error leaves B's exact source selected; Back/Forward/reload restore it; parameter removal and unmount/remount clear it. Normal endpoint disclosures and lesson-access history remain recorded | Software-generated disposable lessons and procedural qualification; zero actual model calls or installed acceptance |
| F5: older/same-timestamp evidence falsely confirms recovery | Both supplied transition counterexamples fail on unchanged source. A held registry also prevents the ordinary optional supervisor from progressing in a bounded observation | Require distinct monotonic source observations and matching candidate/state. Persist small indexed producer-epoch metadata, reject superseded epochs and clock regressions, preserve last confirmed severity/receipt, and require fresh confirmations after uncertainty. Limit notice registry-lock acquisition to one second and let the existing supervisor record/retry persistence failures | Native/disposable focused run: **24 passed in 57.07 seconds**, no skips. Six ordinary ten-second checks span **51.765 seconds**, including real registry contention and a read-only SQLite storage fault; the same supervisor makes **26 progress steps** and confirms recovery after restoration. Actual producer freshness tests separately refuse stale/future inputs and accept two genuinely new clear observations | Transition counterexamples are software probes, not observed production faults. Paced disposable persistence is not installed overhead or retained operating-scale evidence |

Environment: Windows PowerShell 5.1, CPython 3.12.10, authenticated owned
PostgreSQL 17.2 schemas and disposable SQLite registries. One existing
Starlette test-client deprecation warning. Ruff and strict Windows mypy pass
(95 source files); compiled TypeScript/Vite build passes (1,930 modules).
The eight-minute hosted workflow limit and all earlier selectors remain;
the normally paced regression is added to that selection.

The original `f5-original.log` and `f5-contention-original.log` retain the
unchanged-source failures. The first paced QA run failed because its test
release event was already set; that failed fixture receipt is preserved,
then corrected without changing the product's confirmation rules. The
original disposable database later became unavailable; final native checks
use a newly initialized owned local PostgreSQL cluster. No installed
database, task, service, runtime, financial record or protected artifact
was changed or restarted.

Already recorded disclosures are not undone by cancelling a browser read.
Presentation acknowledgment/snooze remains separate from observed recovery.
No new scheduler, research worker, admission bypass or financial authority
is added. Exact owning heads and the combined full-suite/hosted results are
recorded in the final issue #48 audit ledger.
