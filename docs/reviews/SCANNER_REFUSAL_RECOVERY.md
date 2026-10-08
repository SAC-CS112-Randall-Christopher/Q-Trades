# Retain and clear a definite scanner refusal under cross-window contention

PR86's original hosted browser run failed during scanner control recovery.
The backend had acknowledged Pause at revision 6 and refused the delayed Start
at revision 5 with HTTP 409. Each command was sent once and the scanner remained
paused. The original window's definite-refusal bookkeeping requested the shared
Web Lock only if immediately available. When the other window held it, the
cleanup failed, leaving a known refused Start recorded as pending.

Queue only that terminal bookkeeping for the existing lock. Once acquired,
recheck the original request UUID and complete command payload, record its
refusal, and remove only that command. Other pending commands stay intact.
Dispatch, successful acknowledgment and exact GET recovery retain their existing
immediate-lock behavior. There is no automatic POST retry. The synchronous
bookkeeping callback has no awaited network operation or nested lock.

The original failed run, full log and uploaded artifacts are retained under
`continuation-20261008-14/review/guard-ci-failure-01`; their failure is not changed
by this repair. The deterministic regression holds the real shared browser lock
in the second window while the actual backend returns Pause 200 and Start 409.
It observes the queued cleanup, releases the lock, verifies the exact refused
command was cleared, and reopens the original Pause receipt with GET only.
Its original 30-second phase deadline and one-POST assertions remain intact.

The current TypeScript/Vite build passed with its existing pinned dependencies.
The compiled isolated workflow passed all 14 groups in 31.31 seconds, including
the deterministic contention and normal lost-acknowledgment recovery. Source and
compiled bindings matched before and after. The browser harness reported close
and Stop 200; Node and the synthetic server exited 0 and the isolated listener
was absent. Native absence of the entire Chromium process cohort was not checked.

These are source and disposable normal-workflow results. They do not install,
restart or activate operating Q-Trades, acquire market data, call a model, prove
model coexistence or establish a trading result. The accepted installed rollout
and original grants/attempts remain unchanged.
