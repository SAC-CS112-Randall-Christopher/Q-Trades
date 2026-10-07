# Native candle scanner — goal #66

Chris requested upfront historical analysis of eligible USD crypto markets,
followed by alerts and immediate candidate evaluation. The declared scope is
365 days on native 5m, 15m, 30m, 1h and 4h candles, every detected historical
support/resistance level, and reasons for an alert's current eligibility.
The existing Markets workspace owns the interface; ExperimentLab owns the
cooperative background work and its existing registry owns saved progress.
Orders, accounts, model requests and strategy activation are separate owners.

## Saved analysis charts

The chart follow-up makes the scanner's saved analysis the primary Markets view.
An analyzed market has native 5m, 15m, 30m, 1h and 4h cards, with original pattern
annotations and support/resistance alert zones. Opening an original event reads
its retained candle window; it does not dispatch a fresh candle-tool study or
retrospectively replace the scanner's findings. The separate candle study keeps
its existing request and recovery workflow.

The charts show actual available candles, volume, SMA 10/50/100 and trailing
50-candle approximate VWAP. Indicator context is display-only. The current
scanner recognizes confirmed support/resistance pivots, bounce, breakout and
retest behavior; it does not establish a predictive VWAP/MA relationship or an
after-cost winning edge. Original event reasons, volume confirmation and source
coverage remain inspectable. Missing warmup, gaps, unavailable history and
partial preparation remain explicit rather than producing blank success.

Saved zones become usable only after their confirming candles. Their historical
lines must not imply that an earlier candle knew a later-confirmed level.
Current alert evaluations remain distinct from historical recognition. All
retained levels and events remain reachable through bounded pages; a displayed
window is not the complete year or an automatically selected shortlist.

The read path shares the existing API, registry, immutable input archives and
chart library. A chart-only projection preserves the scanner's frozen source
identity, uses only completed processing, and cannot fetch new venue history,
prepare/start work, place orders or invoke a model. Source/disposable chart
acceptance and an installed chart rollout are separate proof stages.

The latest view contains at most 100 already processed native candles. Older
views reopen one original native page, at most 1,000 rows in two retained archive
chunks, and clip forming/unprocessed observations. Its requested and actual
bounds, progress state, gaps and indicator warmup remain explicit. Opening
older history supplies more moving-average context when the original source
has it; there is no fabricated warmup or all-year overview from 100 candles.

Each original level, pattern and alert page is bounded at 100 records, with a
total and continuation cursor. Continuation pins the progress digest and refuses
a changed snapshot. A clicked original record can be reopened by its exact
kind and sequence, scoped to the same campaign, market and interval, even when
it falls outside that newest page. This single-record selection preserves its
original body and does not perform an unbounded page walk. A record without an
available candle remains inspectable as such, without an invented chart marker.

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

### Approved scanner installation, October 7

PR #80 merged as `3ee32cbce1c56fec3862ec9c576ffc5fe2c9af75`; its six reviewed-head
and six merged-head jobs passed. PR #81's reviewed reader proposal merged as
`de51151173ae9455521728e5e44ac6fdfac9fdb6`, with exact reviewed/merged tree equality.
PR #81 changed only proposal documentation; its runtime equals PR #80 and it had
no separate hosted checks. One supported updater installed that full SHA after
its own ExpectedCommit fetch matched, using the existing paper-service task.
This accepted receipt is reused for the chart follow-up, with no second update.

The scoped individual post-review confirmed the original 1,636,860-event and
15,196-journal prefixes, accounts/funding/contracts, all 18 archived identities,
retained evidence, selected role prefixes, consumed attempts, protected
configuration, twenty-slot capacity and 400/100-GB policy. It retained 496
legitimate appended financial events and ten appended experiment events.
Installed identity passed all 252 selected file checks; storage passed 15/15.
A 30.078-second, three-sample recording window passed 8/8 selected checks, with
240 additional captures and 24 additional queue drops. This proves resumption,
not lossless or uninterrupted collection. Financial audit was available and
balanced and paper state was fresh in that window.

Stop-stage to confirmed ready was conservatively at most 97.442 seconds;
restart-stage to ready was at most 71.877 seconds. These are observed bounds,
not exact financial downtime. The reused full comparator retained 12 passing,
two false and two unavailable results; its strict collected/accepted/lifecycle
gates remain false. The handoff observer retained `Task action differs.` and
did not verify the new writer. Direct native TCP-to-database NAT writer mapping
remains unresolved. Populated Library/Reviews and native desktop product
acceptance are separate gaps. The individual receipt review hash is
`ed9c22c957eefef62a2fdf6f0e27380e951921d561c8aff53bdfb8b7e37f3143`.

The installed UI showed the expanded roster and scanner controls, but its
single-interval candle tool and scanner tables did not satisfy Chris's intended
five-chart explanation of recognized patterns. The new visual source proposal
addresses that gap; opening a window alone does not complete desktop goal #65.

### Saved-chart source verification, October 7

The isolated chart lane adds the five native-frame views above the live feed,
original pattern/alert selection, causal zone segments and explicit saved-window
navigation. Accounts now classifies current `autonomous-lab` accounts in the
same Research filter as forward accounts and links retained trial history.
It does not recreate or refund retired accounts. The scanner's three frozen
implementation-source inputs are unchanged from the approved installed base.

The final backend module passed 30 cases without failures or skips, covering
exact native buffers, retained archive identity/checksums, completed cutoffs,
missing observations, original record selection beyond the first 100 records,
bounded pagination, changed-progress refusal, lock release and read-only state.
All-source Ruff, strict Windows mypy (116 source files), TypeScript and the
compiled dashboard build passed. The existing large-bundle warning remains.

The final compiled chart workflow passed all 16 groups against the actual
disposable scanner/API/registry with synthetic native inputs. Eight geometry
samples showed all five chart hosts fixed at 290 pixels and an unchanged
evidence-button position; normal clicks worked. The workflow verified original
patterns and reasons, causal lines, immutable historical inputs and bookmarks,
stale market-response isolation, failed-window recovery, changed-progress HTTP
422 with no substituted candles, an original prospective alert, Accounts
filter/navigation and mobile layout. All 141 browser API requests were GETs.
The 184 native requests were served by the declared MockTransport; eight
explicit QA setup controls are separate from application navigation. All 25
source/compiled hashes matched before and after. Browser/context closure and
the token-authorized fixture stop returned successfully. The browser receipt
SHA-256 is `54fa3adb3237c4ee037971ccf556af7aca4b7ab17b4a5c6447fa964fdea84f6a`.

This fixture processed 360 of 1,000 requested native slots in each of ten dense
market/timeframe scopes, retaining 640 missing slots per scope. A separate 4h
case processed 2,190 synthetic candles with a prospective alert; its other four
timeframes remained missing. Neither case proves a full real-market year,
all-roster capacity, financial-database acceptance, model coexistence or value.

The existing scanner workflow passed all 14 groups on the final build. The
separate candle study has 17 distinct cases covered on that build: a full run
passed 16 and failed its clock-dependent warmed-gap fixture assumption; the two
affected plot cases passed after correcting only that synthetic sequence.
This local union is not a single successful final full 17-case run. Hosted
exact-head checks must separately establish the final combined workflow.

The first chart head `6614cf792d72f3312e70c0b0542b748f63a324e3`, hosted run
`37689414648`, passed the dashboard, runtime ownership, persistent research,
PostgreSQL and browser jobs. Persistent research passed 190 tests; PostgreSQL
passed 1,946 with 98 skips. Its browser job passed all 16 new chart,
14 original scanner and 17 separate candle-study groups. The Windows native
test step passed 1,355 with 254 skips and two existing deselections in 450.90
seconds, but the overall job was cancelled: GitHub's annotation states
`The job has exceeded the maximum execution time of 8m0s`. Setup and cleanup
also consume that limit. This is a failed hosted gate despite the passing
test-step result; it does not establish all-gate completion.

The timing report identifies at least 102.62 seconds in three existing native
recovery files: notice contention, strategy diagnosis and continuous audit.
The CI repair moves exactly those file selectors to a separate Windows
`native-research-recovery` job, preserving their assertions, environment,
pytest options, pinned requirements and eight-minute limit. The remaining
`native` job keeps its name and the original two exact deselections; the
runtime-ownership job still executes those two cases. No test is dropped,
and no product, strategy or admission policy changes. The expected headroom
is a timing projection; only a fresh exact-head run can establish completion.

The partitioned head `29994916421a8b952dd5ae1f261f9ded9a90b481`, run
`37691493663`, passed six jobs: native 1,291/238 skipped/two deselected,
research recovery 64/16 skipped, runtime ownership 75, persistent research 190,
dashboard build and PostgreSQL 1,946/98 skipped. Its first browser attempt
passed all 47 chart/scanner/candle groups but was cancelled after the Ubuntu
dependency download alone took four minutes. A single browser-only retry used
the same source and reused the other six jobs. Setup completed in 40 seconds;
monitoring, account history and all 17 candle groups passed. The legacy scanner
then passed nine groups and timed out waiting for immediate Pause acknowledgment.
The new chart group was not executed in that retry. Both failed attempts and
their separate artifacts remain retained; same-name rerun uploads succeeded
without deleting the earlier artifact.

The failed scanner artifact shows a paused campaign at revision six, the
original stale-Start refusal and an original Pause awaiting acknowledgment.
It lacks the second window's response/DOM and final probe, so the exact lock
interleaving is not established. The existing UI deliberately retains a request
when acknowledgment cleanup cannot obtain its shared Web Lock and offers the
exact saved-result GET. The test correction captures the actual Pause response,
UUID and revision and exercises that existing recovery flow when necessary,
then requires the acknowledgment, final paused state, unchanged original
Start refusal and no repeated control POST. It also retains both windows and
the final probe on failure. No production control or admission policy changes.

Predecessor failures remain retained. The initial chart setup exhausted its
finite processing budget. Later normal UI checks exposed unstable chart-host
geometry: the pinned library's `autoSize` ignores an explicit height unless its
ResizeObserver fails. Static host heights repaired the actual moving-button
defect; removing per-series axis titles repaired crowded labels without dropping
zones. Old screenshot selectors were scoped to their original workspaces.
The scanner's two-second test delay allowed Start to commit before Pause; a
finite synthetic latch now establishes the intended opposite order and verifies
the unchanged stale-revision refusal. An intermediate browser run observed HTTP
422 but hung reading its response body; the final harness bounds body/cleanup
waits, tests explicit bookmark reload and records the matching direct API body
separately. Another run failed an ambiguous empty-state locator before its
scope was corrected. Earlier abrupt-client cleanup was initially unknown; no
successful final run rewrites those predecessor receipts.

Independent reviews cover the backend, frontend/integration and affected
fixture/evidence scopes separately from their authors. No operating installation,
restart, model dispatch, account cutover, research activation or paid request was
performed for this source increment. Installed code remains the approved
`de51151173ae9455521728e5e44ac6fdfac9fdb6` receipt above. The new charts' installed
workflow, actual operating preparation coverage, unresolved NAT writer identity,
populated Library/Reviews and native desktop acceptance remain separate gaps.
