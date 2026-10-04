import { useEffect, useState, type FormEvent } from "react";
import { TrainingCandidateExport } from "./TrainingCandidateExport";
import { LessonPanel } from "./LessonPanel";
import { StockResearchPanel } from "./StockResearchPanel";
import { ResearchActorPanel } from "./ResearchActorPanel";
import { ResearchQualityPanel } from "./ResearchQualityPanel";
import { FrozenComponentPanel } from "./FrozenComponentPanel";

type RoleState = {
  enabled: boolean;
  contract: string;
  reason: string;
  readiness: {
    qualification_valid?: boolean; runtime_available?: boolean; ready?: boolean;
    qualified: boolean;
    enabled?: boolean;
    reason?: string;
    model?: string;
    digest?: string;
    profile?: unknown;
    stages?: Record<string, { state: string; next_action: string }>;
    operating_admission?: { state: string; checked_at: number; next_action: string; meaning: string };
    roles?: Record<string, { qualified: boolean; reason?: string }>;
  };
  tasks: { id: string; question?: string; created: number; updated: number; stage: string; status: string; reason: string | null }[];
  next_before: number | null;
  next_before_id: string | null;
  history: { retained: number; archived: number; active: number; hot_limit: number };
};
type Task = {
  id: string; stage: string; status: string; updated: number; reason: string | null;
  execution: {kind: string; actor?: string; lease_until: number | null};
  context: { question: { question: string; horizon: string; parent: string | null }; issued: unknown; tool_evidence: { source_basis: string; security: string; closed_bar_count: number; observed_at: number; features: Record<string, { eligible?: boolean; reason?: string; close?: string; atr?: string }> }; catalog: unknown };
  proposal: { request_id: string; kind: string; strategy: {family: string; lookback: number; entry_filter?: {kind: string; horizon_seconds: number; marginal_daily_usd: string; fallback: string; artifact: {sha256: string}}}; reference: { family: string; lookback: number } } | null;
  evaluation: { input_count: number; evaluated_at: number; feature: { eligible?: boolean; reason?: string }; replay: string; detail_reference?: string } | null;
  result: { proposal_id?: string; trial_id?: string; review?: { action: string; rationale: string }; outcome?: {body: {outcome: string; reason: string; window_start: number; window_end: number; available_at: number; delta_usd: string | null; net_after_operating_usd: {candidate: string; reference: string}; qualification: string}}; followup?: { action: string; rationale: string; dependency: string | null } } | null;
  attempts: { attempt: number; stage: string; status: string; started: number; finished: number | null; profile: unknown; response: { answer?: unknown; tokens?: unknown; wall_seconds?: number } | null; reason: string | null }[];
};
type Question = { question: string; horizon: string; parent: string | null; request_id: string };
type SavedRequest = { body: Question; phase: "unknown" | "rejected"; message?: string };
const stamp = (seconds: number) => new Date(seconds * 1000).toLocaleString();
const stages: Record<string, string> = { idea: "Model investigation", evaluate: "Compute method check", archive_evaluation: "Save exact inputs", review: "Independent review", submit: "Ordinary paper admission", outcome: "Await comparison outcome", followup: "Supported follow-up", data_wait: "Await required data", complete: "Research complete" };

export function RoleResearchPanel() {
  const [state, setState] = useState<RoleState | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [selected, setSelected] = useState(() => localStorage.getItem("qtrades-role-task") ?? "");
  const [before, setBefore] = useState(0);
  const [beforeId, setBeforeId] = useState("");
  const [search, setSearch] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [question, setQuestion] = useState("Does the reviewed range mechanism differ from its matched breakout reference after costs?");
  const [horizon, setHorizon] = useState("short");
  const [parent, setParent] = useState("");
  const [retry, setRetry] = useState<SavedRequest | null>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("qtrades-role-question-retry") ?? "null") as SavedRequest | Question | null;
      if (!saved) return null;
      return "body" in saved ? saved : { body: saved, phase: "unknown" };
    }
    catch { return null; }
  });
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await fetch(`/api/lab/roles?before=${before}&before_id=${encodeURIComponent(beforeId)}&search=${encodeURIComponent(search)}`, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) });
        if (!response.ok) throw new Error("Role status disconnected. Saved questions and paper operation remain separate.");
        const value = await response.json() as RoleState;
        if (live) { setState(value); setError(null); }
        if (selected) {
          const detail = await fetch(`/api/lab/roles/tasks/${encodeURIComponent(selected)}`, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(6000)]) });
          if (!detail.ok) throw new Error("Saved task detail is unavailable; retry when connected.");
          const saved = await detail.json() as Task;
          if (live) setTask(saved);
        }
      } catch (cause) { if (live) setError(cause instanceof Error ? cause.message : "Role status unavailable"); }
      finally { if (live) timer = setTimeout(() => void poll(), 10000); }
    };
    void poll();
    return () => { live = false; controller.abort(); clearTimeout(timer); };
  }, [selected, before, beforeId, search, refresh]);
  const open = (id: string) => {
    if (id !== selected) setTask(null);
    setSelected(id);
    localStorage.setItem("qtrades-role-task", id);
    setRefresh(r => r + 1);
  };
  const remember = (saved: SavedRequest) => {
    localStorage.setItem("qtrades-role-question-retry", JSON.stringify(saved)); setRetry(saved);
  };
  const forget = () => { localStorage.removeItem("qtrades-role-question-retry"); setRetry(null); };
  const submit = async (body: Question) => {
    setBusy(true); setError(null);
    try {
      remember({ body, phase: "unknown" });
      const response = await fetch("/api/lab/roles/questions", { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" }, body: JSON.stringify(body), signal: AbortSignal.timeout(10000) });
      const value = await response.json();
      if (!response.ok) {
        const receipt = value.detail;
        const sameIntent = receipt?.request_id === body.request_id && receipt?.intent?.question === body.question && receipt?.intent?.horizon === body.horizon && receipt?.intent?.parent === body.parent;
        if (sameIntent && receipt.outcome === "not_created") {
          remember({ body, phase: "rejected", message: receipt.message });
          setRefresh(r => r + 1);
          return;
        }
        if (sameIntent && receipt.outcome === "created" && typeof receipt.task === "string") {
          open(receipt.task); forget(); setRefresh(r => r + 1);
          setError("Your question was saved. Its detail is temporarily unavailable; reopen the saved question when connected.");
          return;
        }
        throw new Error(typeof receipt === "string" ? receipt : receipt?.message ?? "Question acknowledgment is unknown; reconcile the saved request.");
      }
      if (typeof value.id !== "string") throw new Error("Question acknowledgment is incomplete; reconcile the saved request.");
      open((value as Task).id); setTask(value as Task); forget(); setRefresh(r => r + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Question acknowledgment unknown; retry the same saved request."); }
    finally { setBusy(false); }
  };
  const enqueue = (event: FormEvent) => {
    event.preventDefault();
    void submit({ question, horizon, parent: parent || null, request_id: crypto.randomUUID() });
  };
  const retryTransport = async () => {
    if (!task) return;
    setBusy(true);
    try {
      const response = await fetch(`/api/lab/roles/tasks/${encodeURIComponent(task.id)}/retry`, { method: "POST", headers: { "X-Local-Operator": "1" }, signal: AbortSignal.timeout(6000) });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail ?? "This completed verdict cannot be retried.");
      setTask(value as Task); setRefresh(r => r + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Retry acknowledgment unavailable; inspect the retained task."); }
    finally { setBusy(false); }
  };
  return <section id="role-research" className="panel role-research" aria-labelledby="role-title">
    <h2 id="role-title">Local model research</h2>
    <p>Investigate a permitted question, compare reviewed rules, and follow the recorded paper outcome. Numerical calculation and paper admission retain their existing authority.</p>
    <p role="status">{state ? `Research policy ${state.enabled ? "enabled" : "disabled"} · current role qualification ${state.readiness.qualification_valid ? "verified" : "unverified"} · runtime ${state.readiness.stages?.runtime?.state ?? "unverified"} · ${state.readiness.ready ? "ready for bounded dispatch" : "waiting for prerequisites"}` : "Loading actual role status…"}</p>
    {state?.readiness.model && <p>Model {state.readiness.model}</p>}
    {state?.readiness.reason && <p>{state.readiness.reason}</p>}
    {state?.readiness.stages && <div aria-label="Research readiness and recovery"><h3>Readiness and next actions</h3><ul>{Object.entries(state.readiness.stages).map(([name, stage]) => <li key={name}><strong>{name}: {stage.state}</strong> · {stage.next_action}</li>)}</ul></div>}
    {state?.readiness.operating_admission && <p>Operating admission: <strong>{state.readiness.operating_admission.state}</strong> · checked {stamp(state.readiness.operating_admission.checked_at)}.<br />{state.readiness.operating_admission.next_action}<br />{state.readiness.operating_admission.meaning}</p>}
    {state?.readiness.roles && <ul>{Object.entries(state.readiness.roles).map(([role, value]) => <li key={role}>{role}: {value.qualified ? "Qualified for this contract" : value.reason}</li>)}</ul>}
    {state?.readiness.profile != null && <details><summary>Exact current model profile and digest</summary><pre>{JSON.stringify(state.readiness.profile, null, 2)}</pre></details>}
    <p>{state?.reason}</p>
    {error && <p role="alert">{error} <button type="button" onClick={() => setRefresh(r => r + 1)}>Retry status</button></p>}
    <form onSubmit={enqueue}>
      <label>Research question <textarea disabled={busy || !!retry} required minLength={12} maxLength={500} value={retry?.body.question ?? question} onChange={e => setQuestion(e.target.value)} /></label>
      <label>Holding horizon <select disabled={busy || !!retry} value={retry?.body.horizon ?? horizon} onChange={e => setHorizon(e.target.value)}><option value="short">Short</option><option value="medium">Medium</option><option value="long">Long</option></select></label>
      <label>Preserved parent trial (optional) <input disabled={busy || !!retry} value={retry ? retry.body.parent ?? "" : parent} maxLength={100} onChange={e => setParent(e.target.value)} /></label>
      <button disabled={busy || !!retry} type="submit">{busy ? "Saving…" : "Save research question"}</button>
      {retry?.phase === "unknown" && <>
        <p role="status">We do not know whether this question was saved. Reconcile this original request before changing it.</p>
        <button disabled={busy} type="button" onClick={() => void submit(retry.body)}>Reconcile saved request</button>
      </>}
      {retry?.phase === "rejected" && <>
        <p role="status">Your question was not saved. {retry.message} You can correct or discard it.</p>
        <button disabled={busy} type="button" onClick={() => { setQuestion(retry.body.question); setHorizon(retry.body.horizon); setParent(retry.body.parent ?? ""); forget(); setError(null); }}>Edit rejected question</button>
        <button disabled={busy} type="button" onClick={() => { forget(); setError(null); }}>Discard rejected question</button>
        <button disabled={busy} type="button" onClick={() => void submit({ ...retry.body, request_id: crypto.randomUUID() })}>Try rejected question again</button>
      </>}
    </form>
    <p>Saving a question does not enable inference. A declared paper policy, current role qualification and separate activation are required.</p>
    {state?.history && <p>{state.history.retained} retained questions · {state.history.active} active · {state.history.archived} archived. Completed details reopen from their verified original record.</p>}
    <form onSubmit={e => { e.preventDefault(); setSearch(searchDraft.trim()); setBefore(0); setBeforeId(""); }}>
      <label>Search saved questions <input value={searchDraft} maxLength={100} onChange={e => setSearchDraft(e.target.value)} /></label>
      <button type="submit">Search history</button>
      {search && <button type="button" onClick={() => { setSearch(""); setSearchDraft(""); setBefore(0); setBeforeId(""); }}>Show all questions</button>}
    </form>
    <div className="table-scroll"><table><thead><tr><th>Saved question</th><th>Stage</th><th>Status</th><th>Actual last progress</th></tr></thead><tbody>{state?.tasks.map(t => <tr key={t.id}><td><button type="button" onClick={() => open(t.id)}>{t.question ?? t.id}</button></td><td>{stages[t.stage] ?? t.stage}</td><td>{t.status}{t.reason ? ` · ${t.reason}` : ""}</td><td>{stamp(t.updated)}</td></tr>)}</tbody></table></div>
    {before !== 0 && <button type="button" onClick={() => { setBefore(0); setBeforeId(""); }}>Latest questions</button>}
    {state?.next_before && <button type="button" onClick={() => { setBefore(state.next_before!); setBeforeId(state.next_before_id ?? ""); }}>Older questions</button>}
    {task && <article aria-label="Saved research task">
      <h3>{task.context.question.question}</h3><p>{task.context.question.horizon} horizon · {stages[task.stage] ?? task.stage} · {task.status} · progress {stamp(task.updated)}</p>
      <p>Current ownership: {task.execution?.kind ?? "Unknown"}{task.execution?.actor ? ` · ${task.execution.actor}` : ""}{task.execution?.lease_until ? ` · lease ends ${stamp(task.execution.lease_until)}` : ""}. Executed actor and proposal identity appear in the retained attempts below.</p>
      {task.reason && <p>{task.reason}</p>}
      {task.status === "failed" && task.attempts.length > 0 && !task.attempts.at(-1)?.response && <button disabled={busy} type="button" onClick={() => void retryTransport()}>Authorize one recorded transport retry</button>}
      <h4>Captured causal evidence</h4><p>{task.context.tool_evidence.security} · {task.context.tool_evidence.closed_bar_count} closed bars · captured {stamp(task.context.tool_evidence.observed_at)} · {task.context.tool_evidence.source_basis}</p>
      <FrozenComponentPanel task={task.id} catalog={task.context.catalog} />
      <ul>{Object.entries(task.context.tool_evidence.features).map(([key, feature]) => <li key={key}>{key}: {feature.eligible ? "Entry qualified at capture" : "No eligible entry at capture"}. {feature.reason} {feature.close ? `Close $${feature.close}.` : ""}</li>)}</ul>
      <details><summary>Exact evidence, executed input tool and permitted capabilities</summary><pre>{JSON.stringify({ inputs: task.context.tool_evidence, issued: task.context.issued, capabilities: task.context.catalog }, null, 2)}</pre></details>
      {task.evaluation && <><h4>Computed method check</h4><p>{task.evaluation.input_count} causal input bars checked at {stamp(task.evaluation.evaluated_at)}. {task.evaluation.feature.reason} {task.evaluation.replay}</p><details><summary>Exact calculated result and saved input reference</summary><pre>{JSON.stringify(task.evaluation, null, 2)}</pre></details></>}
      {task.result?.review && <p>Independent review: {task.result.review.action} · {task.result.review.rationale}</p>}
      {task.proposal && <><p>Proposed {task.proposal.kind}: {task.proposal.strategy.family} with {task.proposal.strategy.lookback} bars, compared with {task.proposal.reference.family} using {task.proposal.reference.lookback} bars.</p><details><summary>Validated ordinary paper proposal</summary><pre>{JSON.stringify(task.proposal, null, 2)}</pre></details></>}
      {task.result?.proposal_id && <p>Ordinary inbox: {task.result.proposal_id} · pair {task.result.trial_id ?? "awaiting capacity, funding or outcome maturity"}</p>}
      {task.proposal?.strategy.entry_filter && <p>Entry component: frozen historical memory · {task.proposal.strategy.entry_filter.horizon_seconds / 60} minutes · artifact {task.proposal.strategy.entry_filter.artifact.sha256} · marginal ${task.proposal.strategy.entry_filter.marginal_daily_usd}/day · fallback {task.proposal.strategy.entry_filter.fallback}. Baseline exits and financial risk remain authoritative.</p>}
      {task.result?.outcome && <section><h4>Recorded comparison: {task.result.outcome.body.outcome}</h4><p>{task.result.outcome.body.reason}</p><p>Window {stamp(task.result.outcome.body.window_start)} to {stamp(task.result.outcome.body.window_end)} · outcome available {stamp(task.result.outcome.body.available_at)}.</p><p>Whole-account result after declared operating costs: candidate ${task.result.outcome.body.net_after_operating_usd?.candidate ?? "unknown"}; reference ${task.result.outcome.body.net_after_operating_usd?.reference ?? "unknown"}; difference ${task.result.outcome.body.delta_usd ?? "unknown"}. Execution fees remain counted once.</p><p>{task.result.outcome.body.qualification}</p><details><summary>Recorded comparison outcome</summary><pre>{JSON.stringify(task.result.outcome, null, 2)}</pre></details></section>}
      {task.result?.followup && <p>Supported follow-up: {task.result.followup.action} · {task.result.followup.rationale} {task.result.followup.dependency}</p>}
      <details><summary>Model attempts, final answers and resource receipts</summary>{task.attempts.map((a, i) => <div key={i}><h4>{a.stage} · {a.status}</h4><p>{stamp(a.started)} {a.finished ? `to ${stamp(a.finished)}` : "completion pending or unknown"} {a.reason}</p><pre>{JSON.stringify({ profile: a.profile, final_response: a.response }, null, 2)}</pre><TrainingCandidateExport key={`${task.id}-${a.stage}-${a.attempt}`} task={task.id} stage={a.stage} attempt={a.attempt} completed={a.finished !== null && a.response !== null} /></div>)}</details>
    </article>}
    <LessonPanel openTask={open} />
    <StockResearchPanel />
    <ResearchActorPanel selectedTask={selected || null} />
    <ResearchQualityPanel />
  </section>;
}
