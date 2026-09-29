# Reference UI review — September 29, 2026

The implementation follows all three local inspiration images. Design and
workflow mapping are in `../../REFERENCE_UI.md`. Source baseline is audited
9b87dac2dc557a220b7ff5f893418e5582c7c639; the accompanying source receipt records
SHA-256 hashes for the eight implementation/build-gate files and generated assets.

## Observed verification

The full local PostgreSQL suite passed **382 tests, no skips, in 78.53 seconds**.
Lint passed, strict Python typing passed for 47 source files, and the final
TypeScript/Vite production build passed. The final JavaScript asset is 391.95 kB
(114.36 kB gzip); CSS is 74.91 kB (16.11 kB gzip). These sizes are build observations,
not measured page-load performance. `full-tests.txt` retains the suite receipt.

`browser-results.json` records normal in-app-browser checks using an isolated
PostgreSQL schema, synthetic books/1200 numerical observations and a disposable
registry. The checks exercised the original six accounts, ten-account campaign
creation, a $50 campaign account, individual/global pause and refreshed-version
fences, account filtering/pagination, expanded financial history and a completed
three-family frozen experiment. An explicitly exploratory candidate and separately
funded frozen incumbent control bring this QA workspace to eighteen retained
accounts. The synthetic zero-block forward report remains **No promotion** and
paper incumbent approval stays disabled.

The review also observed the chart's range and account selectors, unknown operating
allocations, strategy rules/read-only tools, retained model qualification, Orders,
Settings, the source-dated not-ready packet, and stopped/disconnected state fences.
A campaign account without comparable retained economics windows displays its
actual current balance and waits for checkpoints rather than drawing invented
history. The primary graph shows retained window endpoints and labels their limits.

Native screenshots are retained for Dashboard, Accounts and AI Lab. Phone and
tablet screenshots render the actual application inside 390/768-pixel CSS-width
frames; they verify responsive layout, not physical-device performance. Tables
scroll inside the narrow application viewport. The frame wrapper does not expose
mobile controls to the top-document locator, so mobile menu interaction is not
claimed as separately tested by that harness.

Two visual defects found during the review were corrected: legacy white table
headers and a compressed sidebar information card. Some early browser assertions
expected hidden funding text or read before the next render; their failed probe
results are retained separately from the settled, expanded UI observations. Search
filters accounts; it does not automatically open their inspection panel.

No operating financial records or credentials are included here. All displayed
balances and experiment/report IDs are synthetic. The original trial was not
funded, paused or reset by these browser checks, and no model/provider call was
made.

## Hosted, merge and installation stages

The Windows acceptance workflow now runs for web source and installs pinned web
dependencies before the TypeScript/production build. Its exact UI head must pass
before merging the outstanding dependency stack. A final-main workflow dispatch
verifies the merged revision before the existing CP0 updater relaunches the native
paper task. Private pre/post financial-prefix hashes, account-policy comparisons
and updater logs stay ignored on this workstation.

Those subsequent stages are verified against live GitHub/task/health state, not
implied by this local receipt. The CP0–CP9 measured audit remains a separate receipt.
Neither this interface nor merging/installing supplies 28 subsequent prospective
daily blocks, live execution authority, or 24/7 reliability evidence.
