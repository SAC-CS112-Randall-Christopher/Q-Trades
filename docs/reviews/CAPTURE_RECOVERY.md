# Owned capture rollback recovery — issue #48

The installed incident exposed `SQLITE_READONLY_ROLLBACK`: owner startup opened
an interrupted segment read-only, so SQLite could not roll back its hot journal.
This draft repairs that startup boundary without changing ordinary historical
readers, financial storage, quotas or the inference guard.

All application segment mutations and startup share a short OS-released root
lock. The current frozen root marker and volume must agree; redirected paths are
refused. New segment ownership intent is fsynced before the first segment write.
It binds segment number, root, storage version and volume, while allowing an
explicitly reviewed quota successor to retain the same segment ownership.

Only an indexed active segment or an orphan with matching durable intent can
enter non-creating `mode=rw` recovery. A SQLite write reservation refuses an
external competing writer too. SQLite performs rollback, then query-only integrity
and checksum checks precede one transactional index reconciliation. Original
availability is copied from the segment, never replaced by startup time.
At most eight eligible segments are reconciled per startup; committed orphan
progress survives a pending retry. No journal is manually deleted or reset.

Unknown pre-intent orphans are explicitly refused for owner inspection. This is
intentional: an old orphan without index or intent cannot establish ownership
solely from a filename. Existing indexed segments do not need a new marker for
recovery. Already retained segments and ordinary evidence readers stay read-only.
Busy, missing, corrupt, foreign and pending failures remain visible through the
existing recorder's unavailable/retry receipt. Constructor failures close the
index and release ownership, allowing an unattended later retry.

## Observed isolated proof

On unchanged main, a subprocess committed two ordinary packets, spilled a later
uncommitted transaction, and exited without closing SQLite. Read-only access and
normal owner startup reproduced `SQLITE_READONLY_ROLLBACK`; the original failing
receipt is retained privately. With the repair, the same journal recovers through
normal startup, both committed payloads/references/timestamps/hashes/availability
survive, new capture resumes, and another restart does not duplicate evidence.

Additional actual SQLite/process cases cover an owned hot orphan after a lost
index acknowledgment, process exit during index reconciliation, both application
and SQLite competing writers, legacy indexed recovery, invalid root/segment
ownership, corruption, missing files and nine orphan segments across bounded retries.
The focused storage/history/tools/evidence/context selection with a fresh isolated
password-authenticated PostgreSQL cluster passed **99 cases, one conditional skip**.
These are procedural software tests, not operating capture or model evidence.

The native full suite passed **989 tests, one existing conditional skip** in
429.72 seconds. After the final canonical-name guard and unattended recorder
acceptance were added, all **12 recovery cases**, Ruff and strict Windows-targeted
mypy passed. The earlier full result and final focused result are distinct proof
stages; the dependent integration will include these final cases too.

## Shutdown inspection and remaining acceptance

The normal evidence worker shields an in-flight flush and awaits it on coroutine
cancellation before closing its stores. The updater's verified process handles
can still terminate a process without running that coroutine cleanup. Other
abrupt process exits/power loss can also leave a journal. The incident appearing
after restart establishes neither which shutdown path ran nor its exact cause.
Crash recovery is therefore needed independently of any shutdown-policy change;
this draft does not alter updater authority or claim the updater caused the incident.

New installed acceptance requires separate merge/install authorization. Preserve
the incident's original files, committed financial history and recorded gap counts.
Actual trained-v2 execution, model qualification and genuine paper feedback remain
separate unfinished milestones.
