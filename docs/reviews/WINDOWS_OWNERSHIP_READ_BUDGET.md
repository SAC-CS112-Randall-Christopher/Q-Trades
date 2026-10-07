# Bounded Windows ownership-read proposal

PR #80 is merged at `3ee32cbce1c56fec3862ec9c576ffc5fe2c9af75` with an exact
tree match to reviewed head `53757f040cd6d95b2398b8efc21ca6961577275f`.
All six reviewed-head and all six merged-commit checks passed. Its authorized
installation has not started: the unchanged preservation collector could not
complete its native metadata step within eight seconds. The installed version
remains `f9bd8574f71badf7218ace0952ad2709ac1a7461`.

Two pre-captures retain the same native timeout and no usable `before.json`.
The dependent storage read consequently failed for a missing receipt; it did
not observe a quota defect. The separate original-attempt reader passed with
two consumed attempts and two consumed allowances. No updater or restart ran.

One hidden invocation of the unchanged Windows ownership helper completed in
11.218 seconds under a 20-second diagnostic bound. It verified the existing
task, process ownership and loopback listener, exited zero, and retained 717
bytes of stdout with empty stderr. The exact child exited normally. This
measurement identifies an inadequate deadline for that observed metadata
read; it does not identify the underlying Windows delay or establish financial
latency, model capacity, uninterrupted writer ownership or complete acceptance.
Direct database-writer/NAT mapping remains unresolved.

The proposed patch changes only `native_end = time.monotonic() + 8` to `+ 20`
in a **new, separately pinned revision** of the retained read-only collector.
Do not overwrite the original owner or replace its trusted hash silently.
Preserve both failed captures and use a fresh output/binding for a revision.
The original collector SHA256 is
`d9918a027e99e68c1ad50a51011b048fef4a0cb3ef99b60dd1e671d2a0ba2965`.
The unchanged helper SHA256 is
`93c8b83be86e1fb7462b59246fa6a14bd301d0781b1e635ad21a315ad79d3f4a`.

Independent review compared the source and AST: only that assignment's numeric
constant changes. The declared 60-second total collection deadline, 64-KiB
native output checks, exact owned-child cleanup, native identity verification,
read-only financial transaction, current audit, storage and preservation
checks, installed marker and refusal behavior remain unchanged. The existing
total deadline is checked cooperatively; this proposal does not claim a new
hard wall-clock guarantee. Application financial/model guards, admission,
CPU/RSS limits, paper policy and recording/storage reserves are untouched.

Chris's instruction to reuse the unchanged acceptance owner requires an explicit
decision before this revision is applied. The proposed native allowance has
measurement support from the actual helper diagnostic; **the full revised
collector has not run and has no admission/preservation acceptance result**.
After authorization, verify the version/binding with an independent review,
run one fresh complete baseline, and proceed only if its material scope verifies.
Retain any failure without another unchanged retry loop. The already authorized
updater must still fetch and match the full approved merged SHA before build,
backup or shutdown. Record actual installed preservation and workflow results;
do not turn historical failures or missing coverage into passes.

Evidence is retained under
`C:/Projects/outputs/qtrades-operational-66/approved-scanner-rollout-80`:
the two pre-capture logs/failure records, original-attempt before receipt,
`native-baseline-diagnosis-1/diagnosis.json`,
`native-reader-budget-proposal-1.patch`, and
`native-reader-budget-proposal-independent-review-1.json`.
The independent proposal-review SHA256 is
`e9eff10bdd7a5b462cfcf3c61ce52529360acc831511200a7d9b283c8a497f7a`.

