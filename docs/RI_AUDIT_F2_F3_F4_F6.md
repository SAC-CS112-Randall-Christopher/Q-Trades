# October 4 diagnosis and selected-evidence repairs

Owner: draft PR #51, issue #48. Original source head:
`17db47fbd18e219ee39ec8239416cd28ffd8df10`.
PR #50's readiness repair is merged into this draft without rewriting history.

| Finding | Original reproduction | Root correction | Verified result | Remaining boundary |
| --- | --- | --- | --- | --- |
| F2: historical diagnosis depends on live catalog/worker | Two missing-current-market and three stopped/error/stale API cases fail on unchanged source | Retained tools validate bounded USD symbol syntax and obtain historical account/source membership through the scoped reader. Only live tools require current catalog and worker freshness. Disk, operator, single-read and disclosure guards remain | Native original-input and accounting reads, exact receipt reopening and live-read refusal pass. Compiled UI can run/open retained diagnosis with empty catalog and stopped worker, while live evidence stays disabled | This does not restore a stopped financial worker or fill missing historical evidence |
| F3: concurrent request counters can abort a saved read | Actual producer insertion while transport/fallback snapshot copies raise dictionary-size errors. An unexpected counter failure leaves a running receipt | Each producer owns a short counter lock around insertion, coupled increments and copying. No lock spans awaits, parsing, I/O or financial work. Transport and fallback snapshots retain independent epochs and transition boundaries. Unexpected reads finish with a redacted terminal error | Concurrent insertion/overflow/coupled updates, independent restart epochs, in-flight reads and cancellation pass. The failed read reopens its exact terminal receipt without driver text | Counts are producer snapshots, not simultaneous cross-producer observations, remote receipt proof or older historical totals |
| F4: late tool response overwrites the current selection | Compiled original UI: delayed receipt A replaces selected B; A's input detail appears under B's cost result | Abort superseded reads and fence response/error/loading by request generation and selected source identity. Receipt identity is retained in the URL for history/reload. Already recorded server disclosures remain | Compiled UI: delayed A leaves B selected; Back/Forward and reload restore exact identity; delayed A error does not affect B or its cost detail | PR #52 owns the corresponding notice/lesson selector repairs and the integrated browser acceptance |
| F6: zero result is called positive and cumulative basis is hidden | Net 0/fees 0/one trade selects positive on original source; compact native result omits original basis/time | Neutral breakeven classification, strict finite known accounting totals, original whole-account basis/valuation time plus separately labeled closed-event interval | No trades, fee-consumed gross, breakeven, negative/positive and invalid/unknown cases pass. Compiled cost view labels cumulative/final basis, original valuation time and selected cohort | Unknown marks/times remain unknown. No period return, extra fee subtraction or original financial-record changes |

Final focused native result: **118 passed in 20.41 seconds**, no skips,
CPython 3.12.10 / owned disposable PostgreSQL 17.2 schemas. One existing
Starlette test-client deprecation warning. Ruff and strict Windows mypy pass
(94 source files). Compiled TypeScript/Vite build passes (1,929 modules).
These are software/API/browser fixtures, including procedural qualification
and software-generated lesson history; there are **zero actual model calls**.

Original receipts include `f2-f3-f6-original.log` (8 failed / 4 passed selected),
`f3-original-receipt.log` and `f6-original-basis.log` (one failed each).
Earlier focused runs and browser fixture setup failures remain retained in the
owned October 4 QA directory. They are not combined into the passing count.
Settled browser checks use actual endpoint reads and immutable disclosures;
an immediate visibility check during asynchronous loading is not acceptance.
The first disposable fixture needed its existing future software clock moved
to a past fixture date without changing any product guard.

All drafts remain unmerged and uninstalled. The final combined audit ledger,
exact tested heads, full-suite and hosted results belong on issue #48.
