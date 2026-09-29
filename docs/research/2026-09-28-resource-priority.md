# Resource priority for local research

September 28, 2026. Chris requested elastic resource use: trading research may use
spare workstation capacity, but an incoming ArcGIS request takes priority. This
document records the implementation direction and its current limits.

At approximately 11:32 Denver, the requested continuation is evaluating under
`qualification-qwen14b-resume-20260928T173007Z`. The original trainer prefix is
unchanged. A separately versioned scheduler now persists bounded resource waits
and requires 30 seconds of recovery; the CPU profile and paper guard remain intact.
See [resource-yield recovery](2026-09-28-resource-resume.md). Preserve active frozen
files. Actual ArcGIS response latency and a real wait/recovery cycle remain unmeasured.

At approximately 11:05 Denver, no evaluation is active. The remaining-roles batch
stopped after one passing trainer development answer because the existing paper
resource guard activated. Both supervisors remain running; the model is unloaded.
The working stop helper now recognizes windowless Python jobs. The next step is
bounded waiting/recovery that preserves completed evidence when research yields;
the guard and inference profile have not been relaxed. See the
[terminal review](2026-09-28-1100-model-result.md).

At approximately 10:22 Denver, the **CPU policy is implemented** through the Windows
scheduler: six model threads may use all 12 logical processors at IDLE priority,
below the observed ArcGIS Normal and paper BelowNormal priorities. The server and
worker settings were independently verified through Windows process APIs, including
executable identity and creation time to reject reused process IDs. A counting
probe completed in 71.329 seconds at 2.799 generated tokens/second with zero GPU
bytes, then unloaded successfully. This is one infrastructure measurement under
observed workstation load, not a controlled comparison or proof of concurrent
ArcGIS response latency. The existing paper resource gate still controls admission.

**GPU handoff and request-coordinated cancellation/retry remain unimplemented.**
CPU priority is best-effort scheduling, not a hard latency or memory-bandwidth
reservation. No ArcGIS process, configuration, model or private data was changed.
The first elastic batch stopped at 10:23 after a failed researcher answer and stale
supervision. Its terminal receipt remains. Both supervisors now use tested
windowless hosts. The current freeze is
`qualification-qwen14b-remaining-20260928T163843Z`, limited to previously untested
trainer/reviewer roles, with the same six-thread resource policy. Preserve its
configuration until completion. A fresh supervisor/server identity check now gates
dispatch; actual server and model-worker settings still gate each recorded result.
At 10:40, the queue waits on paper resource pressure. Long-duration supervision and
simultaneous ArcGIS response latency remain unmeasured.

## Initial fixed profile (historical)

Trading has a dedicated CPU-only Ollama server on 11435 with two logical processors
and below-normal model-worker priority. ArcGIS retains its server on 11434 and GPU
access. The frozen qualification batch `qualification-qwen14b-cpu-20260928T154037Z`
kept that allocation throughout. Its first development request
started at 15:43:43 UTC. Do not edit its frozen files, change its allocation or
interrupt it merely to adopt this policy. Failures and incomplete requests remain
part of the record. It stopped at 15:53:43 UTC with one 600.015-second incomplete
response, followed by the existing paper resource constraint. Its complete source
archive and terminal receipt remain intact; later resource changes do not regrade it.

The paper worker's existing resource gate blocks admission of optional work. It
does not establish a general mid-generation preemption mechanism. Separate model
servers still share RAM, memory bandwidth, storage and processors.

## Next operational policy

1. Protect deterministic market handling, accounting and position management.
2. Give interactive ArcGIS inference priority over optional trading research.
3. Let research use available capacity when those services are healthy and idle.
4. Retain completed research stages, interrupted attempts and reasons for yielding.

CPU scheduling was the first implementation step after the fixed batch terminated.
Use a versioned profile with a measured thread budget and wider processor affinity;
do not assume maximum threads means maximum throughput. Research workers must run
at lower CPU priority than the protected work. Both trading and paper processes were
observed at BelowNormal during this checkpoint, so merely removing the affinity cap
would not establish priority over the paper worker. Choose and measure the research
priority explicitly, without changing ArcGIS processes. Continue enforcing the
existing paper health, disk and resource gates and one trading inference request.

GPU borrowing is a separate step. An idle/resident-model listing does not prove that
no ArcGIS request is arriving. A request coordinator must observe interactive demand
before admitting background GPU work and prevent new background requests while
ArcGIS is waiting or active. Until that integration is verified, reserve the GPU
for ArcGIS; do not describe polling alone as reliable request preemption.

On interactive demand, a future coordinator must persist the research attempt,
cancel only its own generation, verify cancellation and release of its GPU memory,
and then allow interactive inference. A disconnect or cancel request alone is not
proof of release. After an idle grace period and health checks, retry the interrupted
stage with a new attempt ID linked to its predecessor. A model generation may need
to restart; there is no promise of an instant pause/resume or zero handoff latency.
If release cannot be verified, leave research stopped and report the failure.

Use request IDs and resource state only at the coordination boundary. Trading does
not need ArcGIS prompts, private GIS data, credentials or application files. Do not
silently redirect existing ArcGIS clients or take over its running server. Keep the
current isolated endpoints available as the recovery path.

## Evidence needed before enabling the policy

Measure background throughput and ArcGIS response delay with research idle, active,
yielding and resuming. Exercise repeated arrivals, coordinator restart, failed
cancellation, failed unload and stale activity observations. Observe paper event
age, engine latency and resource constraints throughout; retain adverse results.
Record model digest, runtime version, thread count, priority and placement for each
profile. A different resource profile requires its own operational evidence; no old
timeout or incomplete evaluation becomes a passing result because resources change.

Persist the research stage and every attempt before dispatch. The dashboard should
show Working, Waiting for ArcGIS, Yielding, Retrying or Failed with a concise reason,
elapsed time and completed evidence. UI state must come from recorded transitions.
No raw internal reasoning or new financial permissions are part of this work.

The four-hour project follow-up owns continuation after the frozen batch finishes.
The separate completion watcher reports that batch's terminal result first. An
active batch always takes precedence over changing its runtime configuration.

Sources: [Windows scheduling priorities](https://learn.microsoft.com/en-us/windows/win32/procthread/scheduling-priorities)
and [Ollama concurrency, memory and model lifetime](https://docs.ollama.com/faq).
