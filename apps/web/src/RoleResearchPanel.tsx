import { useEffect, useState, type FormEvent } from "react";
import { LessonPanel } from "./LessonPanel";

type RoleState = {
  enabled: boolean;
  contract: string;
  reason: string;
  readiness: {
    qualified: boolean;
    enabled?: boolean;
    reason?: string;
    model?: string;
    digest?: string;
    profile?: unknown;
    roles?: Record<string, { qualified: boolean; reason?: string }>;
  };
  tasks: { id: string; question?: string; created: number; updated: number; stage: string; status: string; reason: string | null }[];
  next_before: number | null;
};
type Task = {
  id: string; stage: string; status: string; updated: number; reason: string | null;
  context: { question: { question: string; horizon: string; parent: string | null }; issued: unknown; tool_evidence: { source_basis: string; security: string; closed_bar_count: number; observed_at: number; features: Record<string, { eligible?: boolean; reason?: string; close?: string; atr?: string }> }; catalog: unknown };
  proposal: { request_id: string; kind: string; strategy: {family: string; lookback: number}; reference: { family: string; lookback: number } } | null;
  evaluation: { input_count: number; evaluated_at: number; feature: { eligible?: boolean; reason?: string }; replay: string; detail_reference?: string } | null;
  result: { proposal_id?: string; trial_id?: string; review?: { action: string; rationale: string }; outcome?: unknown; followup?: { action: string; rationale: string; dependency: string | null } } | null;
  attempts: { stage: string; status: string; started: number; finished: number | null; profile: unknown; response: { answer?: unknown; tokens?: unknown; wall_seconds?: number } | null; reason: string | null }[];
};
type Question = { question: string; horizon: string; parent: string | null; request_id: string };
const stamp = (seconds: number) => new Date(seconds * 1000).toLocaleString();
const stages: Record<string, string> = { idea: "Model investigation", evaluate: "Compute method check", archive_evaluation: "Save exact inputs", review: "Independent review", submit: "Ordinary paper admission", outcome: "Await comparison outcome", followup: "Supported follow-up", data_wait: "Await required data", complete: "Research complete" };

export function RoleResearchPanel() {
  const [state, setState] = useState<RoleState | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [selected, setSelected] = useState(() => localStorage.getItem("qtrades-role-task") ?? "");
  const [before, setBefore] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [question, setQuestion] = useState("Does the reviewed range mechanism differ from its matched breakout reference after costs?");
  const [horizon, setHorizon] = useState("short");
  const [parent, setParent] = useState("");
  const [retry, setRetry] = useState<Question | null>(() => {
    try { return JSON.parse(localStorage.getItem("qtrades-role-question-retry") ?? "null") as Question | null; }
    catch { return null; }
  });
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await fetch(`/api/lab/roles?before=${before}`, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) });
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
  }, [selected, before, refresh]);
  const open = (id: string) => { setSelected(id); setTask(null); localStorage.setItem("qtrades-role-task", id); };
  const submit = async (body: Question) => {
    setBusy(true); setError(null); setRetry(body);
    localStorage.setItem("qtrades-role-question-retry", JSON.stringify(body));
    try {
      const response = await fetch("/api/lab/roles/questions", { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" }, body: JSON.stringify(body), signal: AbortSignal.timeout(10000) });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail ?? "Question could not be saved.");
      open((value as Task).id); setTask(value as Task); setRetry(null);
      localStorage.removeItem("qtrades-role-question-retry"); setRefresh(r => r + 1);
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
    <p role="status">{state ? `Research policy ${state.enabled ? "enabled" : "disabled"} · current role contract ${state.readiness.qualified ? "qualified" : "unqualified"}` : "Loading actual role status…"}</p>
    {state?.readiness.model && <p>Model {state.readiness.model}</p>}
    {state?.readiness.reason && <p>{state.readiness.reason}</p>}
    {state?.readiness.roles && <ul>{Object.entries(state.readiness.roles).map(([role, value]) => <li key={role}>{role}: {value.qualified ? "Qualified for this contract" : value.reason}</li>)}</ul>}
    {state?.readiness.profile != null && <details><summary>Exact current model profile and digest</summary><pre>{JSON.stringify(state.readiness.profile, null, 2)}</pre></details>}
    <p>{state?.reason}</p>
    {error && <p role="alert">{error} <button type="button" onClick={() => setRefresh(r => r + 1)}>Retry status</button></p>}
    <form onSubmit={enqueue}>
      <label>Research question <textarea required minLength={12} maxLength={500} value={question} onChange={e => setQuestion(e.target.value)} /></label>
      <label>Holding horizon <select value={horizon} onChange={e => setHorizon(e.target.value)}><option value="short">Short</option><option value="medium">Medium</option><option value="long">Long</option></select></label>
      <label>Preserved parent trial (optional) <input value={parent} maxLength={100} onChange={e => setParent(e.target.value)} /></label>
      <button disabled={busy || !!retry} type="submit">{busy ? "Saving…" : "Save research question"}</button>
      {retry && <button disabled={busy} type="button" onClick={() => void submit(retry)}>Reconcile saved request</button>}
    </form>
    <p>Saving a question does not enable inference. A declared paper policy, current role qualification and separate activation are required.</p>
    <div className="table-scroll"><table><thead><tr><th>Saved question</th><th>Stage</th><th>Status</th><th>Actual last progress</th></tr></thead><tbody>{state?.tasks.map(t => <tr key={t.id}><td><button type="button" onClick={() => open(t.id)}>{t.question ?? t.id}</button></td><td>{stages[t.stage] ?? t.stage}</td><td>{t.status}{t.reason ? ` · ${t.reason}` : ""}</td><td>{stamp(t.updated)}</td></tr>)}</tbody></table></div>
    {before !== 0 && <button type="button" onClick={() => setBefore(0)}>Latest questions</button>}
    {state?.next_before && <button type="button" onClick={() => setBefore(state.next_before!)}>Older questions</button>}
    {task && <article aria-label="Saved research task">
      <h3>{task.context.question.question}</h3><p>{task.context.question.horizon} horizon · {stages[task.stage] ?? task.stage} · {task.status} · progress {stamp(task.updated)}</p>
      {task.reason && <p>{task.reason}</p>}
      {task.status === "failed" && task.attempts.length > 0 && !task.attempts.at(-1)?.response && <button disabled={busy} type="button" onClick={() => void retryTransport()}>Authorize one recorded transport retry</button>}
      <h4>Captured causal evidence</h4><p>{task.context.tool_evidence.security} · {task.context.tool_evidence.closed_bar_count} closed bars · captured {stamp(task.context.tool_evidence.observed_at)} · {task.context.tool_evidence.source_basis}</p>
      <ul>{Object.entries(task.context.tool_evidence.features).map(([key, feature]) => <li key={key}>{key}: {feature.eligible ? "Entry qualified at capture" : "No eligible entry at capture"}. {feature.reason} {feature.close ? `Close $${feature.close}.` : ""}</li>)}</ul>
      <details><summary>Exact evidence, executed input tool and permitted capabilities</summary><pre>{JSON.stringify({ inputs: task.context.tool_evidence, issued: task.context.issued, capabilities: task.context.catalog }, null, 2)}</pre></details>
      {task.evaluation && <><h4>Computed method check</h4><p>{task.evaluation.input_count} causal input bars checked at {stamp(task.evaluation.evaluated_at)}. {task.evaluation.feature.reason} {task.evaluation.replay}</p><details><summary>Exact calculated result and saved input reference</summary><pre>{JSON.stringify(task.evaluation, null, 2)}</pre></details></>}
      {task.result?.review && <p>Independent review: {task.result.review.action} · {task.result.review.rationale}</p>}
      {task.proposal && <><p>Proposed {task.proposal.kind}: {task.proposal.strategy.family} with {task.proposal.strategy.lookback} bars, compared with {task.proposal.reference.family} using {task.proposal.reference.lookback} bars.</p><details><summary>Validated ordinary paper proposal</summary><pre>{JSON.stringify(task.proposal, null, 2)}</pre></details></>}
      {task.result?.proposal_id && <p>Ordinary inbox: {task.result.proposal_id} · pair {task.result.trial_id ?? "awaiting capacity, funding or outcome maturity"}</p>}
      {!!task.result?.outcome && <details open><summary>Recorded comparison outcome</summary><pre>{JSON.stringify(task.result.outcome, null, 2)}</pre></details>}
      {task.result?.followup && <p>Supported follow-up: {task.result.followup.action} · {task.result.followup.rationale} {task.result.followup.dependency}</p>}
      <details><summary>Model attempts, final answers and resource receipts</summary>{task.attempts.map((a, i) => <div key={i}><h4>{a.stage} · {a.status}</h4><p>{stamp(a.started)} {a.finished ? `to ${stamp(a.finished)}` : "completion pending or unknown"} {a.reason}</p><pre>{JSON.stringify({ profile: a.profile, final_response: a.response }, null, 2)}</pre></div>)}</details>
    </article>}
    <LessonPanel openTask={open} />
  </section>;
}
