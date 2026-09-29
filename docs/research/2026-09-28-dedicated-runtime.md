# Dedicated local research runtime

Latest checkpoint, approximately 11:32 Denver: the restarted remaining-case batch
is evaluating on the unchanged six-thread CPU runtime. The one completed trainer
answer was imported without reissuing its request. All supervisors and the paper
and ArcGIS processes were preserved. See [bounded recovery](2026-09-28-resource-resume.md)
and current STATUS for the active freeze and process identities.

Latest checkpoint, approximately 11:05 Denver: both windowless supervisors remain
running, with ArcGIS and paper processes unchanged. The model is unloaded and no
evaluation is active. The remaining-roles batch stopped after one passing trainer
development answer when the paper resource guard activated. No role qualified.
The stop helper now recognizes pythonw.exe and python.exe jobs; this was changed
only after retaining the terminal batch and source archive. See the
[terminal review](2026-09-28-1100-model-result.md).

Historical checkpoint, September 28 10:40 Denver: the first fixed CPU batch ended
incomplete and is preserved. The independently frozen elastic profile now uses six
inference threads with all processors eligible at Windows IDLE priority. Its counting
probe verified actual process priority/affinity and zero GPU use, completing in
71.329 seconds at 2.799 generated tokens/second. The active role batch is
`qualification-qwen14b-remaining-20260928T163843Z`, waiting on paper resource
pressure and testing only trainer/reviewer; no role is qualified yet. The prior
elastic batch's failed researcher answer and stale supervision are retained.
Both scheduled tasks now use project pythonw.exe with `scripts/service_host.py`,
which starts PowerShell with CREATE_NO_WINDOW and preserves logs/exit codes.
Disposable integration tests verified no console on host and child. Both live hosts
also report no console; existing paper and ArcGIS processes are unchanged. The
earlier control-interruption source and sustained unattended reliability remain open.
Before stopping research, inspect pythonw.exe queues as well as python.exe workers.
Start/install with `scripts/Install-ResearchRuntime.ps1 -RuntimeProfile CpuElastic`
only after any prior batch finishes and the owned runtime is stopped. See
[the heartbeat audit](2026-09-28-0954-heartbeat.md) and
[current resource policy](2026-09-28-resource-priority.md).

The initial fixed-profile implementation and measurements below are historical.

Chris authorized separate runtimes on September 28 so ArcGIS and trading research
can progress concurrently. The GPU has 8 GiB and the workstation has approximately
96 GiB of RAM. The initial allocation therefore gives trading background research
CPU resources while preserving the existing GPU-capable ArcGIS service.

Chris subsequently clarified that research should use spare capacity and yield to
incoming ArcGIS work. The current two-processor limit remains fixed for the active
qualification run. The later elastic policy is recorded in
[resource priority](2026-09-28-resource-priority.md); it is not active yet.

| Service | Endpoint | Resources / ownership |
|---|---|---|
| Existing ArcGIS model server | `http://127.0.0.1:11434` | Existing settings and process remain owned by that application. Trading does not stop it or unload its models. |
| Trading research model server | `http://127.0.0.1:11435` | CPU only; two logical processors; below-normal server and model-worker priority; one model/request at a time. |
| Paper application | `http://127.0.0.1:8780` | Existing deterministic engine, database and dashboard. Never waits for an LLM to manage positions. |

The trading instance uses the already installed Ollama 0.34.4 executable and model
directory. It does not copy weights or download additional models. Its environment
settings apply only to its process tree, including `OLLAMA_NO_CLOUD=1`, disabled
CUDA/Vulkan devices, `OLLAMA_NOPRUNE=1`, one concurrent model/request, and a 60-second
idle model lifetime. No user/machine environment variables or firewall rules changed.
Both model services are bound to loopback. Separate processes still share physical
RAM, disk bandwidth and CPU caches; simultaneous full ArcGIS workloads have not yet
been benchmarked, and hardware isolation is not a separate security sandbox.

## Start, status and stop

`scripts/Install-ResearchRuntime.ps1` installs and starts the current-user logon task
`TradingResearch-Models-20260928`. It checks the exact existing task action before
reusing its name. `scripts/Run-ResearchRuntime.ps1` owns a named mutex, refuses an
occupied port, records process identities and settings, and supervises its worker.
Ollama explicitly raises its worker priority; the supervisor therefore reapplies
below-normal priority and the two-processor affinity to verified child workers.

`data/research-runtime.json` is the operational status record. Timestamped runtime
logs are under `data/`. `scripts/Stop-ResearchRuntime.ps1` verifies task ownership,
server executable, parent and creation time, refuses active research jobs/resident
models, then stops only this task and its verified process tree. It leaves the
logon task installed; run the installer again to start it. No database or model
file is removed. Stop/start was exercised while ports 11434 and 8780 kept their
original process IDs.

The first launch failed while replacing its status file: Windows PowerShell 5.1
bound a null `File.Replace` backup argument to an invalid empty path. A concrete
previous-state backup fixes this. The failed status receipt remains at
`docs/evidence/research-runtime-start-failure-20260928T152632Z.json`. Stop validation
also compares parsed creation times, supporting PowerShell 7's automatic JSON-date
conversion instead of comparing a DateTime with a formatted string.

## Measurement and qualification

Two infrastructure probes were blocked before inference by the existing paper
resource gate. A subsequent 128-token counting probe completed in **116.14 seconds**,
including loading/prompt work, at **1.583 generated tokens/second**. Ollama reported
**zero GPU bytes** and approximately **10.9 GB** of loaded model/context memory.
These numbers measure a CPU infrastructure check, not research quality or trading.
That initial probe's model worker had Ollama's above-normal default priority; the
subsequent supervisor correction is a separate operational change. Its throughput
is a provisional estimate for the final lower-priority configuration.

The initial shared-runtime queue was stopped while waiting, before any request.
Its freeze and state remain intact, marked `superseded_before_inference`, with the
handoff receipt `qualification-runtime-handoff-20260928T152600Z.json`.

The replacement freeze is
`docs/evidence/qualification-qwen14b-cpu-20260928T154037Z.json`, with separate source
and runtime snapshots. State is
`data/qualification-qwen14b-cpu-20260928T154037Z.state.json`. It uses the same Qwen3
14B digest and unchanged role-contract-v3 prompts, corpus, decoding and output cap.
Its CPU allocation and **600-second request allowance** were declared before any
CPU role evaluation, informed by the infrastructure measurement and the previous
363–460-token researcher development responses. Old 120/300-second results are not
regraded. This changed operational profile must first screen all three roles again.

The batch performs 4 development cases per role, then each passing role gets at
most 36 holdout requests under three frozen seeds. Acceptance still requires 34/36
correct, no authority/citation violations or unsafe approvals, complete coverage,
matching profiles and healthy worker observations. Each CPU response records actual
model placement; missing placement, nonzero GPU use or a mismatched digest prevents
CPU-profile qualification. Continuations cannot silently change origin, placement
profile or a previously recorded server version. No role is enabled automatically.

One trading inference lock remains in force; independent ArcGIS inference is allowed.
The queue gates on the dedicated endpoint, paper health and its existing optional
research constraints. A transient paper constraint can postpone startup. Source drift,
an interrupted process or a stopped evaluation remains visible for review; do not
restart a batch or erase a failed/unfinished response. Reuse verified-prefix recovery
only where the existing continuation contract permits it.

The temporary `report-dedicated-model-test-results` heartbeat checks this batch every
15 minutes and reports the terminal results or blocker before pausing itself. The
four-hour paper-experiment heartbeat is unchanged. The computer must remain awake
for inference; Codex must be running for its scheduled completion follow-up.

No numerical model was installed into the paper decision path. The consumed numeric
test boundary `1790595239.9180105` still must be imported into any later research
journal. Role qualification is followed by rationale review and a real three-role
workflow, persistence/recovery and evidence UI checks.

Sources: [Ollama configuration, concurrency and retention](https://docs.ollama.com/faq),
[CPU-only GPU-selection controls](https://docs.ollama.com/gpu), and
[local scheduled-task requirements](https://learn.chatgpt.com/docs/automations?surface=app).
