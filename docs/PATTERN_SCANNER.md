# Native candle scanner — goal #66

Chris requested upfront historical analysis of eligible USD crypto markets,
followed by alerts and immediate candidate evaluation. The declared scope is
365 days on native 5m, 15m, 30m, 1h and 4h candles, every detected historical
support/resistance level, and reasons for an alert's current eligibility.
The existing Markets workspace owns the interface; ExperimentLab owns the
cooperative background work and its existing registry owns saved progress.
Orders, accounts, model requests and strategy activation are separate owners.

## Source and observation contract

The current universe's USD spot, status, volume, activity, spread and freshness
screens supply the roster. A campaign freezes selected markets, the observed
roster, source/version digest, storage-plan digest and time cutoff. Selection
can cover the whole eligible roster within the existing 2,000-market discovery
bound; it is not limited to the six markets receiving detailed live feeds.
Campaigns remain bounded at 32, and all markets/scopes retain explicit progress.

The public venue's native interval API supplies actual OHLCV and original rows.
[Binance.US's candlestick contract](https://docs.binance.us/#get-candlestick-data)
allows up to 1,000 rows per request and identifies candles by opening time.
Completed UTC candles only are accepted. No minute-quote aggregation, missing
candle interpolation, live-trade subscription expansion or synthetic operating
fallback is part of this scanner.

A dense 365-day market has 105,120 five-minute, 35,040 fifteen-minute,
17,520 thirty-minute, 8,760 hourly and 2,190 four-hour candles: 168,630 total.
The native-page lower bound is 172 requests per market. This is a data-volume
calculation, not measured venue throughput or verified full-market availability.
Newly listed markets and missing provider observations remain incomplete.
The interactive chart inspector retains its separate 5,000-candle bound.

Raw pages, their hashes and immutable source references are retained through the
existing research store and quota/protection checks. Processing advances a
durable cursor only after the corresponding bounded work commits. Every
confirmed pivot is retained in the registry; pagination does not discard levels.
Missing intervals interrupt causal indicator/visit continuity. Older levels
remain visible with the discontinuity disclosed, rather than implying a fully
observed path through the gap.

The shared experiment registry keeps its existing 512-MiB physical ceiling.
The external 400/100-GB store is not additional capacity for the registry's
level/event tables. The 2,000-market selection bound does not prove a full year
of every market fits. Optional scanner transactions must preserve registry
headroom for the existing research owners and stop with explicit incomplete
progress before exhausting it. No quota increase, second database or evidence
deletion is authorized by this source proposal.

## Detection and candidate meaning

The initial version reuses the candle tool's strictly confirmed support and
resistance pivots, zone width, causal visits, bounce, breakout and retest
definitions and prior-volume observations. The separate candle-chart inspector
shows 10/50/100 simple moving averages using candle periods in the selected
timeframe; those averages are not scanner entry criteria in this version.
A pivot requires its confirming
closed candles; later observations cannot retrospectively supply an earlier
signal. Pattern/level observations preserve the original source and definition.

An alert evaluates the present screen, freshness and available cost inputs and
retains its reasons. Unavailable information remains unavailable. A detected
pattern is an inspectable structural hypothesis; it has no measured winning
edge until a separately frozen, prospective comparison establishes one after
costs. Historical patterns are not inputs that earlier paper decisions actually
observed. The scanner does not authorize an entry or rewrite a financial rule.

## Runtime and recovery

Preparation freezes scope without running it. Start uses the exact campaign
identity and expected revision. Pause advances revision so a delayed Start
cannot silently reactivate work. Request receipts are immutable and an uncertain
acknowledgment reopens by its original request ID. The UI retains its request
identity across reload and does not automatically repeat a POST.

One cooperative scanner step runs through the existing lab owner; there is no
new scheduler, researcher, serving backend or financial writer. Native requests
and registry/level work are bounded. Dense overlaps remain pending behind a
durable level cursor until all matches are processed; a LIMIT cannot stand in
for completion. Prepared scopes receive continuing completed-candle analysis
alongside historical preparation. A process restart preserves observations and
returns campaigns to paused state. Source/storage identity changes require a
new explicit compatible scope rather than regrading old evidence.

Optional writes borrow the existing EvidenceRecorder's initialized ResearchStorage
under its lock. They cannot initialize another recovery owner while recording
is active. An unready, closed or differently configured recorder refuses the
optional write. Candle-study reopening uses the existing read-only
`reopen_evidence` helper and preserves the exact original receipt digest.
Shutdown waits for the borrowed writer off the async event loop so independent
financial cleanup can proceed. Normal storage quotas, free reserve, volume
identity, retained history and failure reporting remain protected.

## Acceptance ledger

The source lane starts from merged/installed candle PR #79 commit
`f9bd8574f71badf7218ace0952ad2709ac1a7461`. Its reviewed PR tree and resulting
merge tree match. All six exact merged-commit CI jobs passed. Its single approved
updater used the full ExpectedCommit guard and the existing paper task; the
existing Windows launcher opened the dashboard with exit 0. This browser-based
launcher does not complete native desktop goal #65.

The reused rollout collector and individual offline review confirmed unchanged
original financial prefixes (1,619,609 events / 15,196 journal rows), original
account/funding/configuration/contracts, retained evidence, model attempts,
twenty-slot capacity and 400/100-GB policy. There were 1,268 legitimate appended
events and 17 appended experiment events within the scoped role comparison.
All 249 installed-file checks and 15 storage checks passed. The original consumed
two attempts/two allowances were unchanged. Current financial audit was available
and balanced. Strict receipt coverage and direct NAT writer mapping remain false.

Installed-workflow limitations are retained: the finite native handoff observer
failed with `Task action differs.`; its largest sample interval was 47.838 seconds
and it did not verify a new writer. First startup required a natural supervisor
retry. Stop-stage to ready was at most 151.229 seconds, and restart-stage to ready
at most 128.331 seconds; neither is an exact measured interruption duration.
The later 30.047-second recording check passed 7/8 checks, with +282 captures
and +4 queue drops, but its last research-recording state was unavailable.
Installed BTCUSD 5m study #18 retained its original failed/OSError result after
exact request recovery. A subsequently retained atomic recording-status receipt
reported `Capture recovery busy: another storage writer owns this root`.
This identifies a contention condition but does not establish the exact cause
of study #18's class-only error. No operating repeat request or update follows.

The initial matched disposable storage checks passed 35 tests, with two native
PostgreSQL cases deliberately excluded before explicit QA database verification.
The original live-lock constructor failed in the fixture while the repaired
read-only reopening succeeded on the same retained data without changing segment
state or original receipt. Borrowed tool writes reused the initialized owner
without another startup reconciliation; threaded capture serialized correctly.
Independent review found a synchronous shutdown wait; the off-thread correction
and its cancellation/independent-async-work regression were then verified.

The frozen scanner's focused native run passed 17 tests with no failures or
skips. It covers a complete synthetic native four-hour year, five-minute
continuation beyond the inspector's 5,000-candle limit, dense overlapping levels,
native-source rejection, gaps, revision recovery, restart, cancellation, bounded
source retries and protected registry/storage refusal. The affected shared
storage/tool suites passed 126 tests with one Windows symlink-privilege skip.
Earlier failed setup/test runs and their repairs remain retained.

All-source Ruff and strict Windows mypy passed (115 source files). The compiled
dashboard passed its build and 14 disposable browser groups: preparation,
Start/Pause and exact command recovery, paged levels, historical patterns,
prospective alerts/evaluation, original campaign reopening and responsive layout.
The final dense browser scope retained 106 levels across pages of 100 and six;
its partially processed source page still reported zero completed pages/bars.
Those progress counters advance when the staged page finishes, so saved level
counts are separate from completed-page coverage. The prospective alert came
after 2,190 synthetic four-hour bars; the other native frames in that browser
fixture explicitly remained missing. No real venue or financial database was
used. The browser and its owned fixture server closed normally. Earlier browser
failures remain retained, including fixture assumptions about page completion
and support-bounce candle direction.

Independent combined source review cleared the scanner, shared writer repair,
UI and additive CI scope. An additive independent review verified the final
browser artifacts, frozen source/build match, owned cleanup and retained red
runs. The complete native Windows suite then passed 1,999 tests, with one
symlink-creation privilege skip and one existing Starlette/httpx deprecation
warning, in 982.83 seconds. Its explicit disposable PostgreSQL identity was
`qtrades_qa` / `postgres` at loopback port 54544; no operating database was used.
The exact disposable process/data-directory/listener was verified before its
normal stop; no other client connections remained. The owned process and
listener are gone, and all disposable data and receipts are retained.
Exact-head hosted results remain a separate check to record on the draft PR.
The first hosted head `7040c946d8c3d59369a474b53ccb62838e0073c7` passed five
jobs, including the complete PostgreSQL and compiled browser workflows. Its
Windows native job was cancelled at the existing eight-minute limit after
1,271 passes and 189 skips (477.23 seconds of pytest), so that head did not pass
all gates. That run had no per-case duration report; the new cases are not
established as the sole timing cause. The follow-up moves only the two new
scanner/shared-writer selectors to the existing Windows persistent-research
job, alongside candle history, and adds duration diagnostics to both jobs.
Every baseline selector, job and lifecycle budget remains unchanged. Final
hosted completion must verify both the original native selection and the
additional Windows research coverage; no longer limit or reduced selection
substitutes for completion.

The second hosted head `d6ad9309f0182573f78c32ee821845ddc42a4b09` passed
four jobs, including the added scanner/shared-writer research coverage. Its
portable PostgreSQL suite failed one concurrent-review case after 1,901 passes
and 98 platform skips (430.60 seconds). The failure was a vanished SQLite
shared-memory file between `is_file()` and the separate size stat. The trace
does not identify the closing thread. The corrected storage tally uses one
stat for classification and size. A missing known SQLite sidecar restarts the
entire tally once because checkpointing can grow a main database already
counted. A second disappearance refuses admission; persistent-file loss,
missing directories and other I/O failures still propagate. Real SQLite
fixtures reproduce the old failure and verify checkpoint-growth quota refusal,
bounded recount, retained evidence and unchanged reserves/volume checks.

That second Windows native job was cancelled with one station-test failure,
1,319 passes and 194 skips (469.45 seconds). The station fixture incorrectly
assumed its real I/O would finish within the production one-second cooldown.
Its API-local test clock now verifies refusal at 0.999 seconds, unchanged
receipts and admission at exactly one second without replacing the global
clock or changing production policy. Duration evidence also measured two
existing scoped-tool cases at 135.47 and 71.66 seconds. Those exact cases
retain their assertions and move from the native selection to the existing
Windows runtime-ownership job. All 95 baseline native file selectors remain
in order, with only those two exact node IDs deselected there and selected
in the ownership job. The new storage-accounting regression file is also
explicitly selected on Windows. Six jobs, their original selectors in the
combined coverage, and every lifecycle budget remain protected. A fresh
exact-head run must establish completion; the failed runs remain retained.

After those repairs, the affected native storage, capture, concurrent-review,
scanner, candle, scoped-tool and station suites passed 150 tests with the same
single Windows symlink-privilege skip and existing deprecation warning (95.84
seconds). They used the explicitly verified disposable PostgreSQL database,
including the native maturity/expansion cases omitted from the author's initial
SQLite-only check. The separate 14 new storage regressions passed without
skips. All-source Ruff passed; the changed storage owner passed strict Windows
mypy. Independent reviews cleared the repair and exact selector partition.
The fresh compiled scanner browser check passed all 14 groups at the changed
storage-owner hash, using the unchanged compiled dashboard. Its owned browser,
fixture server and loopback listener closed normally. The disposable PostgreSQL
owner was verified before normal cleanup, no other clients remained, and its
process/listener stopped with all data retained. The earlier 1,999-pass full
native run applies to the pre-repair application source; it is not substituted
for final-head hosted verification. Published PR #80 checks and the subsequent
#66 checkpoint record that separate exact-head outcome.

Operating installation/activation and a full real year across the eligible
roster remain separate acceptance. No trading value, complete model coexistence,
continuous recording or populated Library/Reviews acceptance follows from
synthetic fixtures. After the scanner is complete, Chris requested investigation
of the expected eighteen accounts versus eight shown; that investigation does
not authorize recreating accounts or restoring financial history.

The later bounded account investigation read the installed status, account
identities, autonomous trial history and performance status, then reopened
one archived candidate through the ordinary dashboard. All ten requested
additions were funded as five candidate/reference pairs with fixed four-hour
reviews. Each pair recorded a data-blocked review and then retired through
the existing supervisor; they collectively retained 12 closed trades. Their
retirement preceded the PR #79 rollout. Six protected original accounts and
one newer medium-horizon pair remain active, explaining the displayed eight.
All 18 archived identities remain listed, for 26 distinct identities over time.
This is not an eight-account UI cap or evidence of update-related deletion.
The saved scores omit the exact input/passive-evidence predicate that blocked
those reviews, so the precise blocker remains unknown. The archived trials
are not established as losing strategies. This investigation does not fund,
restore, reopen or convert them into continuing accounts.
