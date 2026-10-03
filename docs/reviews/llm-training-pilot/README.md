# LLM training pilot — observed software proof

Date: October 2, 2026. Draft PR #41; part of issue #28. Base main `9d45f71`.
The first product source is `5dd2c6285acb69e2ebf4eed8267cf5de02476d47`.
The later source fingerprint file identifies the small CLI/UI corrections exactly;
final commit and hosted result are recorded in the draft and issue.

## Demonstrated user path

Desktop 1440x1000 and mobile 390x844: ordinary navigation to AI Lab -> Local model
research -> saved question -> completed attempt -> private unreviewed export.
Downloaded original answer and packet match the selected synthetic attempt;
pending attempts are disabled. Injected original-record unavailability produces an
explicit error and retry. A successful retry downloads the same original candidate.
Reload, reopening and reselecting the same question retain useful task details.
Both viewports pass with zero browser exceptions and zero external requests.

This browser proof uses the actual compiled frontend and API with a synthetic
role-record adapter. It is not a live Qwen inference, current model qualification,
a mature paper result or installed-Windows proof. Original hot/retained role-worker
export and unchanged financial state are separately covered by native PostgreSQL
integration. `browser-receipt.json` states the exact proof scope.

## Measured stages

| Stage | Observed result |
|---|---|
| Full Linux / Python 3.12.10 / newly owned PostgreSQL 17 suite, first product source | 726 passed, 30 skipped, 225.92 s |
| Focused native role/export/API integration, first product source | 67 passed, 45.16 s |
| CLI correction including requirements-only startup plus API | 37 passed, 3.31 s |
| Whole-repository Ruff | Passed |
| Strict mypy targeting Windows | Passed, 87 source files |
| TypeScript and Vite dashboard build | Passed, 1927 modules |
| Compiled desktop/mobile browser export/retry/reopen | Passed, both viewports |

The full suite's skipped cases stay explicitly skipped. Linux verification does
not stand in for Windows-specific subprocess/lifecycle acceptance. A pre-existing
Starlette/httpx deprecation warning is retained. Hosted CI has its own exact head
and result; do not infer it from these local tests.

## Failures retained and corrected

1. Initial native selection had five failures before export. Unchanged main
   reproduced all five: the shared `/tmp` filesystem had only approximately
   0.64 GiB available and correctly hit the existing research-capacity guard.
   Fresh disposable test storage on the adequately sized workspace volume fixed
   the environment. No resource/risk guard was weakened and no unrelated files
   were deleted. Original failed logs and baseline-control logs remain private.
2. Browser bootstrap initially lacked native shared libraries. The existing
   prepared browser-library directories resolved it. Early navigation selectors
   also used button/exact-name assumptions instead of the real links; those QA
   failures remain recorded and were not product success.
3. Actual UI reselect defect: opening the already selected task cleared detail
   without changing the effect dependency, leaving an empty view until the next
   ten-second poll. Preserve the current detail and explicitly refresh on open.
4. Actual mobile navigation defect: legacy small-screen `display: none` overrode
   the new drawer's transform. The open drawer now explicitly displays as flex.
   No URL manipulation or hidden navigation bypass was used to obtain success.
5. First hosted Windows run 37052697441 / job 110989722783 failed one new CLI test:
   requirements-only checkout lacked the editable `trading` package. The script
   now resolves the repository's own src before importing the role contracts,
   matching the existing repository script convention. A `python -S` regression
   excludes editable/.pth hooks while exposing only dependencies. Initial hosted
   result was 1 failed, 412 passed, 162 skipped; it is not relabeled green.

## Honest boundary

No real reviewed market corpus, tokenizer/loss-mask qualification, LoRA training,
trained checkpoint, operating installation, role activation or economic advantage
is established. The Windows operating host was not connected. No model weights
were downloaded, no paid model call made, and no GIS/GPU or paper account/history
was changed. Dependency/browser setup and a new isolated synthetic PostgreSQL
cluster belong only to the owned Linux QA workspace.

The delivered pilot can turn reviewed original research decisions into reproducible
training/evaluation material. Semantic target review, model-specific training
execution and prospective after-cost comparisons remain the next distinct stages.
