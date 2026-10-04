# October 4 audit repair: owned runtime lifetime and maintenance

Owner: draft PR #53, issue #48. This is source and disposable Windows QA;
it does not authorize or report an installed task recovery or a model call.

| Finding | Original reproduction | Root correction | Verification | Limitations |
| --- | --- | --- | --- | --- |
| F1: a validated PID can name a different process at stop time | Original `1cc4e9e80270189fd548a4ffb461a3de22f2f1ef`: three delayed PID replacement cases failed after the mock task stop; numeric stop targeted a replacement | Pin the native process handle before checking creation time, path and parent. Kill, wait and exit checks use that handle. Validate child creation time and refuse unknown children. Apply the same lifetime checks to supervisor child budgeting and cleanup | 51 native Windows PowerShell 5.1 tests pass, including mocked late server/child/both replacement, changed creation time, final exit-to-kill race, partial shutdown, resident work and uncertain listeners. A native pair of owned sleeping processes confirms that no new PID lookup occurs after validation | The native pair does not force the OS to recycle a PID; deterministic replacement cases supply that boundary. No installed service or model process was touched |
| F1: recovery can rewrite the owner or race newly admitted work | Existing recovery fixtures preserve the original task action; added tests exercise admission at registration | Preserve the existing limited interactive principal and trigger. Hold the existing queue and inference byte locks throughout maintenance, without truncating or replacing their files | A separate disposable PowerShell process holds both locks; actual Python `CollectorLock` admission is refused and succeeds after release. Registration-time admission is also refused | This verifies the admission mechanism, not installed inference or runtime readiness |

`Stop-ResearchRuntime.ps1` writes a stopped receipt only after all owned stops
and the final port check succeed. On uncertain ownership or partial failure,
the retained failed receipt remains intact. Every pinned handle and admission
lock is released on exit. Supervisor cleanup releases its mutex even if a stop
fails. Readiness, private trained PEFT-v2 runtime compatibility, current role
development/qualification, operating admission and activation remain separate.
Restoring the scheduled Ollama path would not establish PEFT-v2 compatibility.

Local receipts: `f1-original.log`, `f1-focused-01.log` through
`f1-focused-05.log` in the owned October 4 QA directory. The earlier missing
test-file invocation and Ruff failures are retained; they are not passing runs.
Focused final result: **51 passed in 37.58 seconds**, no skips. Ruff passes.
Integration and hosted results are reported separately on issue #48 with the
tested Git heads. All drafts remain unmerged and uninstalled.
