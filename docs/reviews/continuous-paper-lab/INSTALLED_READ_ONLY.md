# Installed-state investigation before implementation

Two read-only observations on September 30, 2026, at 10:59:40 and 11:00:32 Mountain
time (52 seconds apart). The actual loopback application reported main
`a3ed677e580d801c1561b65130421c1cbbc90b29`; selected installed source hashes matched
the refreshed baseline. Private paths, database identity and complete receipts are
retained locally under ignored `data/installed-observation-{first,second}.json`.
PostgreSQL connections explicitly enforced `transaction_read_only=on`. SQLite used
`mode=ro` and `query_only=ON`. No mutation, restart or service activation occurred.
The observed application origin was `http://127.0.0.1:8780`. The installed
paper-worker Python process identities were 22364/6800 and API identities
53268/32356. Command lines, installed version marker, API settings and database
configuration resolved to the existing installed application's directories, not
this worktree or a disposable database. Exact private paths remain in the receipts.

Market observations, closed candles, paper processing, durably journaled minute
observations and signal decisions advanced across the observations. The latest
signals were no-trade decisions with their original data/risk conditions intact.
Trade absence therefore did not establish worker failure.

| Observed stage (UTC, September 30) | First | Second |
| --- | --- | --- |
| Market observation | id 59785, 16:59:32 | id 59797, 17:00:21 |
| Latest closed BTC/ETH candle open | 16:58:00 | 16:59:00 |
| Durable minute market evidence | id 477223, 16:59:00 | id 477326, 17:00:00 |
| Paper processing | 16:59:39 | 17:00:32 |
| Signal decision | id 477242, 16:59:01 | id 477345, 17:00:00 |
| Full replay capture | id 132, 11:27:14 | unchanged |
| Compact input cutoff / availability | 16:10:00 / 16:10:01 | unchanged |
| Latest matured outcome | 16:55:01, unavailable | unchanged |
| Latest available executable outcome | 16:48:05 | unchanged |
| Experiments / campaigns / learning stages | 0 / 0 / 0 | unchanged |

Latest actual fill/trade was 16:46:24. Later decisions retained no-breakout,
volume-confirmation and extension reasons; this is a healthy evaluation path.

The September 28 cards are saved role-qualification files. Their card date comes
from the result's filename/start; the old "Snapshot" date comes from the API query.
Neither establishes active trading-model learning. Agents are explicitly disabled.

The installed numerical registry had no experiments, learning stages or finite
campaigns. Consequently there was no evidence of a cancelled/expired campaign,
exhausted job count, or an automatic successor waiting to run. The worker was alive
but optional research was yielding to a resource guard repeatedly extended after
slow financial commits. Disk free space exceeded the existing 5-GiB gate.

The first stopped evidence-acquisition stage was the full replay archive: its
declared physical-capacity state was latched; newest full record and row count did
not advance. Compact research inputs were newer and separately retained mature
outcomes, including an available modeled executable label and honestly unavailable
labels. Selection and 45-minute maturity mean these need not advance in 52 seconds.
No completed strategy-learning job was retained.

The full replay plan was 64 MiB. Payload usage was 65,596,628 bytes, physical
usage 66,908,160 bytes, and 132 rows. The frozen plan and latched capacity state
explain this stop; raising a default would not change that already saved plan.
Source inspection also found that installed `EvidenceArchive.append` returns at
capacity before its bounded `_mature` pass. Four original episodes had no stored
outcomes. This is a code-path finding, not an installed runtime reproduction; no
attempt was made to execute maturity or migrate that archive. The branch now has
separate versioned, bounded due-outcome continuation and disposable available,
unavailable, resource-pending, immutable-reference and restart checks.
Resource-guard event counts advanced 399 to 415 while its cooldown extended
197 to 282 seconds after occasional financial commits near 970 ms. These are
separate observed constraints. The two samples are bounded diagnostic evidence,
not a sustained production latency benchmark.

The market chart received valid current OHLC data. Its full-height mouse hitboxes
were painted by the theme's candle-group rectangle selector. Browser inspection
confirmed colored 217-pixel hitboxes; only range buttons existed. The replacement
uses locally bundled TradingView Lightweight Charts and read-only causal overlays.
This does not alter strategy configurations or financial authority.

Follow-up source changes distinguish actual activity, historical result dates,
completed learning, physical archive capacity and next action. Their delivery and
disposable verification are separate from any future operating installation.

The later owner allocation was independently checked read-only: G: is a local
USB NTFS disk, not a redirected network share, with about 1.18 TB available.
The scheduled paper task uses the same user's interactive logon context. ACLs
permit that user context to modify the requested directory. An actual installed
worker write was not attempted. Source QA uses newly owned disposable subtrees;
activation, migrating operating data, and restart remain outside this assignment.
