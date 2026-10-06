# Local Codex research observation

The tools-only observer connects local Codex to the existing installed Q-Trades
paper service at `http://127.0.0.1:8780`. It reads saved scientific status through
ordinary APIs. It does not construct an application, database, model transport,
actor grant, review schedule or financial writer.

This is separate from the existing `/api/research/mcp` scheduled-review adapter.
That adapter uses scoped external-review actor credentials and request accounting;
it is not an oversight connection for the local experimental researcher.

## Tools and meaning

| Tool | Scope |
| --- | --- |
| `research_status` | Current activity/readiness and at most 20 saved questions. Continue history with both returned `next_before` and `next_before_id`; search is bounded. |
| `research_task` | One observed `role-…` ID: original question, saved contract/mode/grant, offered strategy configurations, causal feature facts and hashes, matched-rule evaluation, result, retained attempt answers/failures and typed waits. |
| `research_lessons` | At most 20 supported lessons; continue with `next_before`. Original scientific support stays distinct from access frequency. |
| `research_quality` | Recorded attempts/activity and explicitly unmeasured matched research/economic value. Activity is not a strategy-quality score. |
| `research_capabilities` | Current read-only tool descriptions. Listing a tool does not execute it or grant installation authority. |

Each tool reads installed code identity through `/api/health`, then its fixed GET
route. It returns observation time, code identity, paper-health observations and
the canonical hash of the complete fetched payload. These are sequential reads,
not one atomic snapshot or an uninterrupted trace. Current readiness/applicability
does not rewrite the saved answer, original reason, contract or scientific result.
An enabled and ready worker can still be idle or waiting. Paper health separates
current journal-monitor availability/status/balance/age from the last completed
balanced audit. An unavailable current monitor remains unavailable even when its
last completed audit was balanced; raw audit errors/financial projections are
not exposed.

The response is a selected scientific projection, not a complete model packet.
Private profiles/configuration, model paths/weights, raw packets, training/holdout
payloads, arbitrary files, knowledge contexts and unselected payload fields are
not returned. Existing role evaluations expose their input hashes/counts, not full
candle populations or private artifact manifests. Unknown fields require review
before disclosure. Oversized/unavailable/corrupt observations return explicit
tool errors; they never become empty successful results or a fabricated verdict.

Normal task/lesson reads use the existing disclosure owner. Reading mature
outcomes can legitimately record evidence embargo windows and lesson access.
This observation does not reserve an inference attempt, change financial state,
advance a task, retry an answer or trigger an experiment.

## Reviewable next work

Use the saved task ID, contract/mode/grant, context/response/evidence hashes and
original rationale/falsification to prepare a source-work handoff. `tool_wait`
means implementation review is needed; `data_wait` means eligible new evidence
is needed. The observer's handoff label is guidance. It cannot approve a tool,
change a grant/profile, resolve a wait or create a replacement preferred answer.
Existing worker ownership, causal eligibility, budgets and once-only allowances
remain authoritative. There is no background polling or additional scheduler.

## Durable local installation

The connector owner copies the independently reviewed standalone
`src/trading/research_observer_mcp.py` unchanged into
`C:\Projects\Q-Trades-MCP\research_observer_mcp.py` and retains a manifest binding
its exact source hash/revision, dependencies and installation verification.
Use the verified installed Q-Trades Python interpreter with its existing pinned
`httpx` and `pydantic` dependencies. The artifact has no engine/registry/model
imports and needs neither a development checkout nor another operating update.
Copying/registering the connector does not start or restart the paper service.

The host owner registers a scoped MCP entry using the existing Codex configuration
owner, preserving unrelated entries and secrets. The following is the intended
shape; the interpreter must be verified before replacing the placeholder:

```toml
[mcp_servers.qtrades_research]
command = "<verified installed Q-Trades Python>"
args = ["-I", "-u", 'C:\Projects\Q-Trades-MCP\research_observer_mcp.py']
enabled_tools = ["research_status", "research_task", "research_lessons", "research_quality", "research_capabilities"]
startup_timeout_sec = 15
tool_timeout_sec = 20
```

No credentials or local-operator header are needed. The server has no configurable
origin or arbitrary-fetch tool; redirects and compressed responses are refused.
Each call has at most two GETs, a 10-second observation deadline checked between
chunks and a two-second HTTP operation timeout (a blocked read may finish after
the checked deadline). Responses are bounded to 256 KiB each, output to 96 KiB,
input lines to 16 KiB, scientific nesting to 12 and scientific lists to 128.
An oversized input line exits rather than draining unbounded data. Codex owns
the passive stdio process lifetime; EOF closes its HTTP client.

The protocol uses UTF-8 newline-delimited JSON, `initialize`, the initialized
notification, `ping`, fixed `tools/list`, and `tools/call`. Supported compatible
handshake versions are `2025-03-26`, `2025-06-18`, and `2025-11-25`; other requested
versions negotiate `2025-11-25`. It advertises tools only. It sends no unsolicited
requests, sampling, elicitation, prompts, resources or experimental task handles.

See the authoritative [MCP stdio specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
[lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle),
[tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools), and
[current Codex connection guidance](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
A local connection does not establish ChatGPT-web or remote-account access.

## Proof stages

Offline protocol/HTTP fixtures prove parsing, strict argument refusal, projection,
privacy, bounds and error semantics. They do not establish an installed Codex
connection, model usefulness, autonomous continuation or financial coexistence.
After registration, verify actual initialization/tool discovery in Codex, then
use the tools to reopen actual saved researcher status/results. Retain that
connection evidence separately; do not label mock/stub results as installed proof.
