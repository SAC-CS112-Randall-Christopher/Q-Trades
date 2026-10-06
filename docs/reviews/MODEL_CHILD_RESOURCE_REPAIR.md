# Windows model child resource repair (#66)

The policy integration in PR #68 is merged and installed at
`44354feab630caffa188d1e5839407c8f5c838de`. Its preservation and controlled
lifecycle acceptance is complete within the recorded bounded scope. This
follow-up is source and disposable QA; it is not another operating update.

The original trained-v2 request was admitted once under the approved 500 ms,
four-of-twenty policy, unchanged packet and profile. It was cooperatively
cancelled after a native observation demonstrated that the live memory guard
watched the Windows virtual-environment launcher while a descendant interpreter
owned the model memory. No overage was observed. This is an enforcement defect,
not evidence that the model fits the protected budget.

The existing owner retained one failed development attempt and one full
600-second/8192-token allowance. Its actual transport duration was 225.420 seconds;
the normal development detail and history GETs reopened the failure with the
original packet/profile, without changing the task's queued idea stage. The
original permission is consumed. No preferred-answer retry is authorized.

## Repair in the existing owner

On Windows, the transport creates the existing launcher suspended. ChildOwner
assigns its existing kill-on-close Job before the launcher can create an
interpreter. The parent sets the existing two-core/IDLE placement while suspended,
writes the existing owner-ready marker and resumes the
verified primary thread. The existing runner and model profile remain unchanged.

ChildOwner obtains a bounded list of actual Job members and pins their process
handles. It verifies membership, observes their working-set peaks and retains
already observed peaks across member exits. The sampled guard uses the
conservative sum of those member peaks, which need not occur simultaneously;
it does not present that sum as an atomic simultaneous working set. A final
runner-reported peak above the existing limit fails acceptance while retaining
the original complete answer with its failure receipt.

The same 24 GiB byte limit additionally bounds per-process and aggregate private
committed allocations through the Job. Committed memory and resident working
sets are different metrics. These allocation caps add conservative protection;
they do not replace the working-set observations or establish model capacity.

The original 600-second wall limit, two inference threads on distinct physical
cores, IDLE priority, 8 GiB available reserve, 32 GiB prelaunch reserve, context,
token allowance and accounting are unchanged. Financial balance/current-audit,
paper/input/storage/recording guards remain in their existing owners. The
500 ms/four-of-twenty admission policy is unchanged.

## Evidence and limits

The retained native point identified the real interpreter at 335,675,392 resident
bytes while the launcher held about 4 MiB. The transport's 4,317,184-byte sampled
peak therefore describes the launcher; the actual model's complete peak is
unknown. One Ctrl-C to the verified isolated CLI console invoked the existing
asyncio/transport cancellation path. The owner retained cancellation and cleanup,
and a subsequent exact PID/birth check found the known interpreter and launchers
gone. No financial process, database session or original data was killed or reset.

The finite observation's whole-work timings are distinct from order-start or fill
latency. Natural positions and pending orders were absent; neither the failed
model trial nor synthetic fixtures establish active-order capacity or win-rate
impact. Direct database NAT mapping, populated Library/Review acceptance and
desktop package acceptance remain separate and unresolved.

Disposable owner verification passed 30 tests with no skips or warnings. A newly
created Windows venv demonstrates that the actual interpreter stays unstarted
until resume, retains its 64 MiB resident peak after freeing the allocation,
inherits Job ownership, and is terminated by Job closure. Separate 128 MiB
per-process and 160 MiB aggregate commit fixtures refuse oversized allocations.
Invalid, partial, unstable and unreadable membership and failed handle cleanup
refuse success. The first native setup run failed on the sandbox's pytest temp
ACL; that failure remains retained, followed by actual native execution outside
that restriction.

Affected transport/retention verification passed 25 tests, with six cases skipped
because the explicit disposable PostgreSQL database was absent, and one pinned
Starlette TestClient deprecation warning. The six new integration cases exercise
ownership, CPU placement and readiness before resume, pin/CPU/publication
failures, owned aggregate overage despite a small launcher, and a late complete
answer retained with a failed budget receipt and no repeat. Ruff is clear across
source/tests; changed-file formatting is clear. Windows type checks passed for
the changed owner/transport, and the full 108-source-file check passed. An
exploratory whole-repository formatter check reports 32 existing unchanged
files; those unrelated files were not reformatted.

Independent review found and closed two cleanup reporting defects: failed
handle closes remain observable after every cleanup step is attempted, and an
owner constructor that does not return leaves cleanup explicitly unverified.
After the final constructor-receipt correction, the six affected integration
cases passed again with zero skips/failures and the same one deprecation warning
in 1.94 seconds. The earlier 25-test run and its six PostgreSQL skips remain
separate evidence. Final production and focused-test hashes were independently
reviewed with no remaining material finding.

Tests use small allocations and procedural outputs; they do not run the trained
model or consume its ledger. Sampled peaks describe members while observable;
an exited member keeps its last observed peak, while an entirely unobserved
short-lived member's peak remains unknown. Commit caps are a separate protection.
The unsuspended knowledge-worker caller preserves its existing per-process cap;
the new aggregate cap is opted into only by the suspended model launch.

## Next operating decision

After source checks and review, a separate authorization must specify the exact
reviewed source to merge and install through the supported ExpectedCommit
updater, the controlled restart of the same paper owner, and one new finite
development attempt with a reviewed original-packet/profile binding. It must
preserve this failed attempt and allowance, rather than reset or reinterpret
the consumed single-attempt grant. No operating update, retry, research
activation, RAG, qualification/holdouts, external review/spending, training,
downloads/conversion, compression or financial-policy change follows here.

The native ownership design uses Microsoft's documented
[suspended creation flag](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags),
[ResumeThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread)
and [Job inheritance and limits](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
The existing cooperative cancellation follows Python 3.12's
[asyncio SIGINT cleanup](https://docs.python.org/3.12/library/asyncio-runner.html#handling-keyboard-interruption).
