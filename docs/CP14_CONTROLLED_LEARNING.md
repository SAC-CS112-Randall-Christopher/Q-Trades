# CP14 controlled growing memory

`growing-memory-v1` is an independent shadow procedure, not an adaptive account.
The immutable plan freezes initial training/calibration, fixed preprocessing,
five-neighbor rules, a 128-group chronological library, eight-group batch cadence,
label rules and all permissions before the protected evaluation. It compares a
frozen library with periodic batch and single-outcome incremental updates under
identical permitted inputs. The initial seed uses training/calibration alone;
availability or counts of later test outcomes cannot change an earlier seed.
Missing seed support means cold start/no additional signal.

The existing research registry stores logical append-only prediction, score and
model-state records. Predictions commit before labels can score their original
forecast. Equal timestamps process predictions first. Maturity and actual feature/
label availability govern events; delayed/reordered outcomes are sorted by when
they became available. Duplicate event groups cannot inflate updates. Every score
references the saved forecast, and every update references its score and full
before/after model identity. A transaction commits scores/updates together. Retry
checks/restores immutable stages, so crashes after prediction or update commit do
not double-train. Full model snapshots and frozen inputs reproduce decisions;
old snapshots are never selected by watching future profits.

Preprocessing/calibration stay fixed; incremental library updates cannot alter the
protected incumbent. Input drift, residual error and Brier diagnostics are distinct
from unavailable execution-cost error. Three consecutive distinct large residuals
or input shifts trigger diagnosis only. No alarm retrains an account, resets losses,
adds funding or promotes a paper role. More arm scores/updates are not more
independent experiences. Real whole-account effect and marginal monetary value
remain unverified, with the CP7 28-day human policy unchanged.

The journal stops at 20,000 retained stage records and the registry's existing
physical ceiling. The bounded child/queue/input limits and two-MiB shadow result
cap apply. Unknown outcomes remain pending and receive no fabricated scores.
This historical causal simulation is not a prospective market test. The normal
AI Lab freezes/reopens results and links paged, hash-checked learning snapshots.
Source/synthetic proof, installation and subsequent account acceptance remain separate.
