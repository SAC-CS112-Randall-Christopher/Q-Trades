# Clean workspace UI — October 12, 2026

Chris requests a second UI overhaul: make the supplied dashboard's visual
hierarchy real in Q-Trades, reduce overwhelming pages and give every capability
a clear home. This is an increment of the existing coherent-product Goal.

The source baseline is merged PR93 `f0c104d77ce40c15e48cab33abed546135189894`.
The isolated branch is `codex/clean-workspace-ui-66`, reusing the clean existing
coherent-product checkout after confirming PR93's complete tree is preserved in
main. Other PR owners and checkouts remain separate.

## Completion and evidence

- Seven main destinations: Overview, Markets, Research, Accounts, Results,
  History and Settings, with focused discoverable subpages and selected states.
- Compact Overview: actual execution/research states, linked workflow stages,
  attention, market observations, selected-account snapshot, investigations and
  recent retained decisions. Never sum hypothetical accounts into a portfolio,
  invent evidence percentages or infer live readiness from paper health.
- Existing original task/trial/account/source URLs still open the exact record;
  account selection survives cross-area navigation, Back and reload.
- Large research/setup/detail surfaces disclose detail progressively. Navigation
  alone never activates research, changes financial controls or creates work.
- Compiled desktop and narrow browser checks cover real navigation, errors,
  empty states, context and normal polling using owned disposable resources.
- Relevant build, owner and map checks plus independent review pass; failures
  remain recorded. Source publication is separate from installed acceptance.

## Current result

The source implementation and affected local verification are complete.
Independent Codex source review has no remaining material findings. PR94's first
hosted browser-monitoring run failed on an older UI selector; the native and
synthetic harnesses now follow the focused homes while preserving their original
record and accounting assertions. A fresh exact-head hosted gate remains required.
Chris explicitly approved PR94 merge, installation and relaunch when ready on
October 12. The operating installation is still the healthy PR93 revision at this
source checkpoint. No operating model call, research
activation, qualification, training, funding or live operation follows from
this UI change.

| Area | Focused homes |
| --- | --- |
| Overview | Dashboard; Attention & Decisions |
| Markets | Market Watch; Charts; Scanner & Findings; Data Coverage |
| Research | Investigations; Numerical Research; Strategies; Knowledge & Lessons; Training Preparation; Research Controls |
| Accounts | Account Summary; Positions; Orders & Trades; Risk & Safeguards |
| Results | Performance; Costs & Economics; Matched Comparisons; Paper Qualification; Live Readiness |
| History | Recent Activity; Trade History; Account Journal; Research History; Historical Matches; Original Trial History |
| Settings | Setup & Resume; Model Connections; Data & Storage; System Health; Retained Practice |

The shared shell provides a selected sidebar section, local page navigation,
page/account search, actual worker status and a locked live destination. The
Overview has eight bounded cards using existing observations. Account Summary
shows the exact selected account's actual strategy version, positions, cash and
performance. Investigation records have Summary, Evidence, Checks & Review,
Comparison and Outcome & Next Decision views. Scanner Findings, Saved Charts,
Preparation & Coverage and All Saved Evidence have separate URL-backed views.
Long source/coverage/raw-record details remain accessible through disclosures.
The existing desktop launcher opens Overview; legacy experiment/account bookmarks
continue resolving to their original account home through the route aliases.

## Verification record

Private receipts and screenshots are retained under
`C:\Projects\outputs\qtrades-clean-workspace-ui-66`; they are not repository
data. These checks use actual native software owners with synthetic market
inputs, clock advances and model callbacks. Actual model calls were zero.
They establish software behavior, not trading advantage, real model usefulness,
full-year/all-market capacity, 28-day qualification or installed acceptance.

| Check | Observed result and scope |
| --- | --- |
| TypeScript and Vite production build | Passed on the final UI; the existing greater-than-500-kB chunk warning remains nonfatal. |
| Existing desktop opener | Its single URL now opens Overview; PowerShell parsing passed. Task validation, health checks and worker-start behavior are unchanged. Installed `-CheckOnly` verification remains a later stage. |
| Product/station/map owner tests | `owner-map-tests-03`: 45 passed, 1 skipped, 1 deprecation warning. The skip requires real symlink privilege. No Python application behavior changed afterward. |
| Compiled product workflow | `browser-09`: all 8 groups passed. Covers seven areas; horizontal scanner tabs and disclosed original coverage; saved configuration/refusal/lost acknowledgment; native worker/comparison/outcome cold reopening; original mixed preparation/chart bookmark; selected/retired/unknown accounts and exact strategy; narrow controls; outage/recovery and ordinary polling. |
| Saved scanner charts | `scanner-charts-06`: all 18 groups passed on final UI. Actual five-frame plots and causal selections; exact progress/cursor pins; older manual evidence retained through pane Back; newer chart window survives leaving and returning; refused/unknown sources, recovery, bounded concurrency and zero automatic POST/acquisition. |
| Scanner control/progress workflow | `scanner-02`: all 14 groups passed at its recorded source manifest, before the final local-pane/disclosure refinements. Covers native cooperative processing, paging, exact archived campaign, lost acknowledgment, outages, Pause over delayed Start, cold reopening and narrow navigation. |
| Separate candle study | `candle-04`: all 18 groups passed at its recorded source manifest, before later scanner-only refinements. Covers five native intervals, plots/gaps, exact receipt recovery, cross-market/account context, narrow layout and a legacy mixed candle/scanner bookmark. |
| Actual Vite development / React StrictMode | `dev-strict-03`: all 3 groups passed on final UI. An actually canceled initial campaign GET is replaced, all five native charts and current status render, same-lifecycle pane Back avoids campaign replacement, unavailable originals permit retry and cold reload succeeds. |
| Account history/status regression | `account-history-04`: passed with fully intercepted synthetic API data. Three rendered Equity refreshes preserve singular history/strategy disclosures, original cursor paging and account-switch reset. No operating or financial proof is inferred. |
| Existing native archive retry | `legacy-archive-01`: all 5 groups passed with disposable original registry/archive owners. Evidence-tab retry, lost acknowledgment, late publication and mismatched acknowledgment assertions remain intact; zero model calls or financial database. |
| Existing native comparison recovery | `legacy-comparison-01`: all 10 groups passed; `legacy-observation-01`: all 9 groups passed. Original Charts return, explicit Findings navigation, exact retained preparation identity and immutable ordinary/read-only recovery use synthetic native/current inputs. |
| Existing saved-task evidence | `legacy-role-01`: all 7 groups passed. Evidence/detail reload, original source/progress bookmarks, narrow rendering and current-profile/manual-form outage rules; hidden-DOM absence assertions and zero API writes retained. |
| Code-to-product map | Explicitly refreshed from baseline `f0c104d77ce40c15e48cab33abed546135189894`: 426 files, 475 references, 62 tasks. Final `--check` passed. |
| Independent Codex source review | No remaining material findings after repairing legacy bookmark precedence, campaign lifecycle cancellation, polling controller ownership and scanner layout/disclosures. This is source review, separate from execution evidence. |

The final product probe confirms balanced native financial state, preserved
preexisting accounting prefix, unchanged bound source hashes and no background
errors. The QA database before/after audit (`pg-04`) confirms the same two
preexisting schemas, zero other clients, no surviving test schema, unchanged
Python source and the unchanged original failed-run state digest.

All owned browser/API/development servers exited and their loopback listeners
were absent. The disposable PostgreSQL owner is stopped only after verifying
its PID, birth, command line, data path, idle audit and loopback listener. Its
data and historical failed evidence are retained. No operating service,
scheduled task or installation was changed.

## Failures retained and repaired

- Owner-test attempts 01 and 02 remain separate: sandbox temporary-directory
  access errors, then a stalled default-sandbox test process stopped after its
  recorded deadline. Attempt 03 uses an explicit owned temporary directory and
  completes the relevant combined suite; earlier failures are not relabeled.
- Earlier compiled browser runs retain their original receipts. Findings led to
  correcting test expectations for the eight-card layout, native QA instrument
  handoff, a funding wait and the saved-question control. Actual defects repaired
  include narrow select overflow, view loss on account changes, missing market
  identity in saved chart bookmarks and stale manual chart focus.
- Independent review identified legacy preparation/chart precedence and a
  canceled campaign restoration guard. Targeted browser assertions now retain
  and reopen the actual original UUID/finding digest and verify page/window
  preservation through Back.
- `dev-strict-01` reproduced stranded scanner status polling after cancellation.
  Controller cleanup and completion now check ownership; attempts 02 and 03
  passed. These are development checks, distinct from production browser proof.
- PR94 head `abd492b15a6723a27327835263e0b72c4548b8ee` retains its failed
  hosted browser-monitoring result: it expected the removed original-trial-history
  disclosure. The harness now opens History / Original Trial History, where the
  same journal-monitoring owner lives. Account-history attempts 01 through 03
  retain their failed selector/synthetic-display receipts; attempt 04 passes.
  The remaining old research harnesses now open native Evidence/disclosures and
  Findings explicitly. Independent review accepted the test-only refinements;
  no application behavior was changed by these harness repairs.

## Publication and operating boundary

PR94 merged as `bfb99dd16ca2c00246ccf532e4c3836b9e65df61` after all nine
checks passed at reviewed head `76c8ed02b6cd859479a540f16085030d29773c37`.
The merged tree matches that head. The existing updater installed the exact
merged revision and the task, health, source/assets and launcher checks passed.
Private before/after preservation checks passed for the existing financial,
configuration, evidence and research owners, with no new attempt or allowance.

Installed browser acceptance passed desktop navigation, original account context,
scanner panes and retained investigation/history views. It then found account-list
overflow at 390px: the narrow grid's automatic minimum expanded to the account
table's minimum width. The failed installed receipt remains unchanged locally.

The bounded follow-up reuses this checkout on `codex/installed-ui-fit-66`, based
on merged PR94. It changes the existing narrow grid track to `minmax(0, 1fr)`;
the table retains its own horizontal scrolling and all columns. Account-history
attempt 05 reproduces the original overflow with the extended synthetic browser
regression. The regression also requires inner table scrolling, a reachable
inspection control, exact selected-account history and the original rendered
status refresh/paging checks. The corrected production build and attempt 06 pass:
the document is 390px wide while the 765px table scrolls inside its 356px panel.
The actual inspection control opens `responsive-v1` and the original status,
paging and account-history reset assertions pass without API writes or JavaScript
errors. Independent Codex source review found no remaining material findings.
These are compiled synthetic source checks; corrected installed acceptance is
still pending at this source checkpoint.

Keep the worktree while review and installed verification are active. Existing
separate setup, MCP oversight, model-resource, compression, RAM and coexistence
owners remain untouched. Reuse the existing updater with the verified merged
follow-up revision, retain fresh before/after private preservation receipts, and
retire the physical lane once verification and durable preservation permit it.
The broader coherent trading-product Goal still requires its remaining model,
operating and prospective evidence.
