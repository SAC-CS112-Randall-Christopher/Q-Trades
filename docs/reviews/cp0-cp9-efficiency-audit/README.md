# CP0–CP9 audit receipt — September 29, 2026

Final measured implementation: **06ca5271aaf9986e114df1637c97098805910009**.
Matched baseline: CP9 **0cfd601083036e2c75e525ec00610bce3c141079**.
The same efficiency driver SHA-256
`13f382ad3829bf7a6f86467685d526e5cf870f4b55e4ff92b126e4b048753477`
was used on both. Capacity/soak receipts record clean source, all driver/module
hashes, timestamps, host, frozen SLOs and membership. All data here is synthetic QA.

| Large bounded history measurement | Matched CP9 baseline | Final audited source |
|---|---:|---:|
| Frozen-input receipt get p95 | 62.64 ms | 17.17 ms |
| Peak Python allocation for one receipt read | 19,188,635 bytes | 5,471 bytes |
| Financial hot-state projection | 2,895,292 bytes | 39,819 bytes |
| Projection transaction p95 | 257.79 ms | 3.56 ms |
| Full journal reconciliation | balanced | balanced |

Thirty reads use a 7,033,881-byte frozen input. Twenty accounts retain thirty-two
reports, each containing 512 discarded windows; twenty-four no-op transactions
isolate projection cost. Full inputs and journal receipts are preserved. Timing
varies with host activity; initial and repeat observations are retained without
selecting the fastest run as the final result.

| Thirty-second capacity case | Commit p95 | Result |
|---|---:|---|
| 1 account, research idle | 6.52 ms | pass |
| 1 account, research busy | 5.61 ms | pass |
| 10 accounts, research idle | 18.26 ms | pass |
| 10 accounts, research busy | 18.70 ms | pass |
| 20 accounts, research idle | 31.82 ms | pass |
| 20 accounts, research busy | 41.55 ms | pass |

The final twenty-account busy soak completed 1,200 shared executable-book ticks at
four per second in **301.46 seconds**. Commit p95/p99/max was
**26.66/35.81/87.28 ms**, queue lag p99 **0.364 ms**, queue peak **one**.
Parent peak RSS was **62.96 MiB**, growth **1.23 MiB**, and CPU **3.09% of one core**.
The real child PID 17592 matched the supervised PID, ran at Windows IDLE on two
processors and peaked at **58.54 MiB**. It completed 3,444 synthetic fits; paid
calls and GPU use were zero. Journal reconciliation was balanced with zero
processing errors. Actual PostgreSQL state plus PaperRuntime account/economics
projection and JSON serialization p95 was **9.73 ms**; network and paint are excluded.
The own journal table grew 1,761,280 bytes. Whole QA database growth 3,866,624 bytes
also includes other development work and is not the engine's isolated storage cost.

Verification: **382 local tests passed, no skips, 80.41 seconds**; 38 affected audit
tests and 19 final reader/forward tests passed separately. Lint, 47-module Python
types and production TypeScript/dashboard build passed. Hosted implementation-head
run [36642583198](https://github.com/SAC-CS112-Randall-Christopher/Q-Trades/actions/runs/36642583198)
passed with **158 tests and 32 database-dependent skips**. Local PostgreSQL proof
covers database contracts separately; hosted skips are not relabeled as passes.
Seven normal-browser checks passed, including complete frozen receipt export,
candidate/control isolation, compact no-promotion display, disabled approval,
version-fenced controls and readiness refresh. The first empty-campaign null-guard
browser failure is retained in browser-results.json and was corrected/rechecked.

Files prefixed `initial-` or `prior-` are earlier discovery/repeat receipts.
`baseline.json`, `final-efficiency.json`, `final-capacity.json`, `final-soak.json`,
`full-tests.txt` and `browser-results.json` are the qualifying final evidence.
Earlier full 381-pass runs remain in the retained logs. The additional test verifies
that an immutable no-promotion receipt cannot be overridden by a forged summary.

This finite synthetic proof is neither prospective trading advantage nor 24/7,
network-to-paint, real advisory/GIS concurrency, live-account eligibility or native
installation acceptance. All changes remain draft, original accounts/updater/model
runtimes are preserved, and CP9 concludes not ready for live execution. Roadmap #1
remains open for the separate authorization and real forward proof stages.
