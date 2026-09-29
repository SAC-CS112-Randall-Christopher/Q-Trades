# CP0 local-update preparation verification

Date: September 28, 2026 (Denver). Source base: imported snapshot
`24464451818b8ffc4d5280142e268e4d02c9e85c`. This is a separate Linux development
worktree, not the operating Windows installation.

## Executed

- Full Python suite using this project's dedicated disposable UTF-8 PostgreSQL
  test environment: **248 passed, six Windows-only skips**, one existing Starlette
  TestClient warning. This includes 32 updater tests plus a low-disk recovery/control
  test. See `pytest.txt`; the passing totals are overlapping with earlier runs,
  not additional independent evidence to be added together.
- Ruff passed for maintained code. The exact imported
  `docs/reviews/verification/reproduce_findings.py` artifact is excluded from lint
  rather than rewritten; its original bytes are retained.
- Strict mypy passed for 35 source modules. `compileall` passed for src/scripts/tests.
- Locked Node dependencies installed with lifecycle scripts disabled. TypeScript
  and the Vite production build passed; no runtime dependency was added.
- Real disposable Git repositories tested exact-main selection rather than the
  developer branch; source/asset modifications; incomplete and unsupported
  releases; foreign origins; dirty checkout preservation; private/runtime file
  rejection; failed builds; retained older releases; operation locks; offline
  checks; bounded metadata parsing and credential/text redaction.
- API checks tested operator/origin authorization, no activation route, off-event-
  loop Git work, duplicate-check cooldown, read-only status and failure recovery.
- The actual GitHub main was read, not modified. It still resolved to the initial
  README commit and was correctly reported as lacking an application release.
- Playwright 1.63.0 with the existing local Chromium headless runtime exercised the
  real compiled app/API on loopback port 18871, with collector/paper workers disabled
  and disposable monitor storage. Both 1440px and 360px layouts had no horizontal
  document overflow. Actual main checking, injected version-read failure, periodic
  recovery without reloading, and a visible check failure passed. Zero page errors
  and zero blocked non-loopback browser requests. See `browser-results.json` and
  desktop/phone screenshots. Failure injection is labeled; this is not a Windows
  desktop or financial-result screenshot.

## Important qualifications

The PostgreSQL integration environment is the isolated Linux test cluster using
PostgreSQL 17, not the operating Windows/PostgreSQL 18 deployment. The new Windows
scheduled-task identity test and five existing Windows supervision/ownership cases
remain skipped here. No native task, launcher, service cutover, account migration,
rollback, automatic update, actual account performance or live trading was verified.

The initial full run reproduced the known host-dependent station-test failure:
its supposedly healthy runtime fixture inherited a low-capacity `/tmp` filesystem.
The fixture now explicitly supplies healthy disk capacity, and a separate below-limit
case proves the production guard still rejects optional tools without altering
account state. No resource limit was relaxed to make the test pass.

The final browser rerun used a clean code commit
`a6125f3d2fad7ba6b98b594bbff1427b0b3cb88e` after restarting only the disposable
loopback test server. Its receipt confirms the exact startup identity and unchanged
GitHub main. The final screenshots include the phone-spacing correction and explicit
Denver timestamp. Earlier precommit captures remain in Git history.

A full **real release-preparation rehearsal** also passed at that code commit:
a disposable local bare repository represented merged main, then the default builder
cloned the exact code, created its own venv, installed pinned dependencies and the
application wheel, ran pip check, installed locked npm dependencies without lifecycle
scripts, built TypeScript/Vite, smoke-imported the API and verified unchanged source
and web asset hashes. The retained synthetic runtime sentinel was unchanged.
See `release-preparation.json`. This exercised the actual builder, not the fake
builder used by isolated unit tests. It was **not** a GitHub merge, a Windows run,
an operating account update or native activation. No production origin override
is exposed by the CLI; the local test remote existed only inside this rehearsal.

All operating accounts, financial journals, frozen research evidence, model services
and Windows worktrees were left untouched. CP1's pending regression fixtures are
preserved in their separate worktree. CP0 remains open for actual native activation;
see ../../LOCAL_UPDATES.md for its acceptance criteria.
