# Local model trial dashboard

September 28, 2026. Open the local dashboard's **Model trials** link, or
`http://127.0.0.1:8780/#model-lab` on this machine.

This view reads actual evaluation receipts. It is not an enabled three-agent
workflow, a qualification certificate, or evidence of profitable trading.
It shows the last recorded request, model/role, timing, reported check results,
final explanation, supplied synthetic evidence, and failures. It never displays
private reasoning transcripts. Model output is rendered as text, not executable HTML.

The view preserves historical results when disconnected and labels them as a
snapshot. An unfinished receipt becomes overdue after its request allowance plus
45 seconds; it never claims indefinitely that a dead worker is still running.
Malformed/unreadable records show unavailable, never a fabricated score of zero.
Continuation is labeled: earlier answers retained in a later receipt are not
additional independent evidence. Actual qualification recomputes every response
and checks complete coverage, identity, safety and paper-worker health separately.

The GET-only endpoint has a five-second cache, scans at most 500 directory entries,
reads at most 24 matching files of no more than 2 MB each, and returns up to eight
current-contract runs. Each run exposes up to six flagged and three recent answers.
All history stays on disk; viewer truncation is disclosed. Evidence text is shown
only when the receipt's corpus hash matches the current stored corpus. Oversized
input packets are omitted with an unavailable message. Final explanations over
900 characters are explicitly marked as shortened. None of this retention policy
is applied to the financial journal.

## Verification

- 149 application tests passed; one existing Starlette/httpx deprecation warning.
- Ruff, mypy (including evaluator/qualifier) and production dashboard build passed.
- Browser checked actual records, expanding an answer and its evidence, current
  activity, disconnected historical snapshots, automatic recovery and overdue state.
- A temporary loopback GET-only preview rendered the real dashboard in a
  430-CSS-pixel iframe. The heading, activity, scores and overdue warning fit without
  clipping. This is a browser layout check, not testing on Chris's physical phone.
- A Windows sharing violation was reproduced during evaluation while the viewer
  was active. Checkpoint writes now retry that specific error for a bounded period;
  permanent failure retains the prior receipt and temporary file. Tests cover both
  paths and continuation with preserved failures, identity and prefix verification.
- The project-owned supervisor reloaded the view at about 05:18 and continuation
  metadata at about 05:30 Denver. No other project's process was restarted.
  After each restart, the dedicated paper journal reconciled and funding, attempts
  and replenishment history remained intact. At revision 69299, the primary held
  $99.3224263613, with five closed trades, no positions and no replenishments.
  The earlier open ETH position closed through the existing ATR-stop logic between
  before/after observations; its loss remains recorded. No trades were inserted by tests.

Evidence: `model-lab-*-20260928.json` and
`research-checkpoint-recovery-20260928.json` under `docs/evidence`.
The temporary preview is not a second paper engine and does not send POST requests.
The actual service remains bound to loopback; no internet hosting was added.
