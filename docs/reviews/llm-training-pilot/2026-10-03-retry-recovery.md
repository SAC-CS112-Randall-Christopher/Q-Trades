# Preparation retry ownership and recovery

The review at source `7bd86108` identified two missing persistence boundaries:
failed-hand-off retries could overlap while the stored stage remained failed,
and interrupted initial creation could leave preparing with no attempt. An
unconditional completion could overwrite a newer attempt list. These findings
do not imply changes to original evidence, weights or financial records.

The repair uses the existing registry's short `BEGIN IMMEDIATE` transaction.
Initial creation persists its attempt in the same commit. Retry rereads the
handoff, checks bounded eligibility and observed attempt history, rechecks the
review fingerprint, and commits one new requested attempt with stage preparing.
No registry or financial lock is held during Lab dispatch. Completion rereads
the current history and updates only its owned job. Superseded completion remains
linked and cannot replace the current claim/result. Prior unknown dispatch stays
explicit; legacy empty history is not filled with a fabricated Lab call.

Regression fixtures use independent registry connections and overlapping callers,
interruption before first dispatch, legacy empty-attempt recovery inside/outside
the existing 190-second wait, late success and failure with a newer pending or
completed job, and a review changed between validation and claim. Existing
sequential retry, archive-integrity, historical-result and review tests remain.
Fixtures are synthetic software proof, not actual concurrent Lab jobs.

Actual application/API acceptance used disposable state and the previously
reviewed retained BTC/USDT local metadata-only interpretation. Original retained
source, timestamps and absent model answer were preserved. The first preparation
failure was deliberately simulated before any Lab dispatch. The explicit retry
used the real unchanged private Lab importer and Qwen3.5-4B tokenizer preparation:
920 input tokens, 148 supervised, 1,068 total, complete target and no truncation;
input/padding labels excluded. Its saved receipt and exact review links reopened,
and repeating build returned the same handoff/attempts. This is prepared only:
no weights loaded, training, inference, qualification or market-value claim.

The earlier 805-case native/database run and ten browser checks remain historical
receipts for their exact revisions. Current native selection (workflow, training,
registry, role worker and API) passed 91 tests, zero skips, 19.21 seconds using an
owned disposable PostgreSQL 17 cluster and Windows Python 3.12.10. Whole-repo
Ruff and strict mypy passed (93 source files); TypeScript/Vite build passed
(1,928 modules, 1.04 seconds). Hosted pushed-head checks are recorded in PR 41;
this selection is not a rerun of the earlier 805-case full suite.
Private receipts preserve unsuccessful verification invocations: a nonexistent
test-file selection ran no tests and JUnit emitted a Windows WMI error; a broader
selection was stopped after its stale default disposable database endpoint timed
out. The corrected native selection explicitly selects a separate owned local
PostgreSQL cluster; operating accounts are never used for testing.

Main `5cf37d3` was integrated as `0fe3f69` without resetting shared work. Its
400 GB temporary / 100 GB retained storage policy is installed by the separately
authorized PR 47 rollout. PR 41 and PR 45 remain draft/unmerged. The private Lab
source and frozen studies are unchanged; detailed receipts/targets stay private.
Installed acceptance for this workflow still needs separate merge/install/restart
approval and an actual operator walkthrough.
