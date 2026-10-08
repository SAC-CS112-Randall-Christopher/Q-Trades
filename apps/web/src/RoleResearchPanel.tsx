import { useEffect, useRef, useState, type FormEvent } from "react";
import { TrainingCandidateExport } from "./TrainingCandidateExport";
import { LessonPanel } from "./LessonPanel";
import { StockResearchPanel } from "./StockResearchPanel";
import { ResearchActorPanel } from "./ResearchActorPanel";
import { ResearchQualityPanel } from "./ResearchQualityPanel";
import { FrozenComponentPanel } from "./FrozenComponentPanel";

type RoleState = {
  enabled: boolean;
  contract: string | null;
  reason: string;
  paper_pilot?: boolean;
  experimental?: boolean;
  execution_mode?: string;
  current_task?: { id: string; question: string; stage: string; status: string; updated: number; reason: string | null } | null;
  activity?: {
    state: "running" | "waiting" | "queued" | "idle" | "paused" | "unavailable";
    reason: string;
    checked_at: number;
    pending_tools: number;
    pending_data: number;
    pending_outcomes: number;
    queued: number;
  };
  question_selection?: {
    policy: string | null;
    state: "selected" | "waiting" | "disabled" | "unavailable";
    reason: string;
    task?: string;
    evidence?: unknown;
  };
  supervision?: { phase: string; status: string; reason: string | null; retry_at: number; updated: number }[];
  readiness: {
    qualification_valid?: boolean; runtime_available?: boolean; ready?: boolean;
    qualified: boolean;
    enabled?: boolean;
    configured_enabled?: boolean;
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
type ToolRequest = {
  kind: "strategy_family" | "feature" | "analysis_tool";
  identifier: string;
  purpose: string;
  required_inputs: string[];
  acceptance_checks: string[];
};
type QuestionSelection = {
  authority: {
    question_policy: string;
    grant_id: string;
    grant_sha: string;
    profile_sha: string;
    contract_version: string;
    contract_sha: string;
  };
  scope_sha: string;
  selection_sha?: string;
  method: "r1" | "p0";
  horizon: string;
  source_sha: string;
  source_start: number;
  source_end: number;
  source_count: number;
  source_basis?: string;
  strategy_sha: string;
  reference_sha: string;
  lesson?: { id: string; sha256: string } | null;
  reason: string;
  falsification: string;
  limitations: string[];
};
type PatternComparison = {
  preparation_request_id: string;
  issued_bundle_sha256: string;
  finding_sha256: string;
  selection: { daily_id: string; symbol: string; timeframe: string; event_kind: "patterns" | "alerts"; event_seq: number };
  campaign_id: string;
  captured_at: number;
  prepared_at: number;
  original_event: { id: string; kind: string; bar_open_ms: number; bar_close_ms?: number; level_id: string; level_price: string; volume_confirmed: boolean | null; volume_ratio: string | null; reason: string };
  coverage: { timeframe: string; status: string; observed_bars?: number; expected_bars?: number; missing_bars?: number; gap_count?: number; progress_sha256: string | null }[];
  native_proof: { archive_verified: boolean; recognition_rows: number; pivot_rows: number; contiguous_relevant_window: boolean; recognition_start_ms: number; recognition_end_ms: number; input_window_sha256: string; pivot_sha256: string; coverage_claim: string };
  mapping: { strategy: string; reference: string; rule_version: string; holding_horizon: string; limits: string[]; source_sha256: Record<string, string> };
  original_evaluation: { status: string; evaluated_at?: number; expires_at?: number; matched_inputs?: Pick<CurrentInputs, "count" | "sha256" | "cutoff" | "archive_verified"> };
  financial_authority: false;
};
type CurrentInputs = { count: number; sha256: string; cutoff: number; start_ms: number; end_ms: number; archive_verified: boolean; retained_at?: number };
type FixedControls = Record<string, unknown> & { entry: string; exit: { feature_seconds: number; maximum_hold: number; review: number }; evaluation: { seconds: number } };
type FixedMethod = { candidate: FixedControls; reference: FixedControls; source_sha256: Record<string, string>; current_inputs: CurrentInputs };
type Task = {
  id: string; stage: string; status: string; updated: number; reason: string | null;
  contract_applicability?: {
    state: "matching" | "different" | "unavailable";
    reason: string;
    recorded_contract: string;
    selected_contract: string | null;
  };
  execution: {kind: string; actor?: string; lease_until: number | null};
  context: { execution_mode?: string; experimental?: boolean; question_selection?: QuestionSelection; pattern_comparison?: PatternComparison; fixed_comparison?: { p0: FixedMethod }; question: { question: string; horizon: string; parent: string | null }; issued: unknown; tool_evidence: { source_basis: string; security: string; closed_bar_count: number; closed_bar_sha256?: string; observed_at: number; features: Record<string, { eligible?: boolean; reason?: string; close?: string; atr?: string }> }; catalog: unknown };
  proposal: { request_id: string; kind: string; strategy: {version?: string; family: string; lookback: number; entry_filter?: {kind: string; horizon_seconds: number; marginal_daily_usd: string; fallback: string; artifact: {sha256: string}}}; reference: { family: string; lookback: number } } | null;
  evaluation: { input_count: number; evaluated_at: number; feature: { eligible?: boolean; reason?: string }; replay: string; detail_reference?: string } | null;
  result: { action?: string; tool_request?: ToolRequest | null; evidence_ids?: string[]; rationale?: string; falsification?: string; proposal_id?: string; trial_id?: string; review?: { action: string; rationale: string }; outcome?: {body: {outcome: string; reason: string; window_start: number; window_end: number; available_at: number; delta_usd: string | null; net_after_operating_usd: {candidate: string; reference: string}; qualification: string}}; followup?: { action: string; rationale: string; dependency: string | null } } | null;
  attempts: { attempt: number; stage: string; status: string; started: number; finished: number | null; profile: unknown; response: { answer?: unknown; tokens?: unknown; wall_seconds?: number } | null; reason: string | null }[];
};
type Question = { question: string; horizon: string; parent: string | null; request_id: string };
type SavedRequest = { body: Question; phase: "unknown" | "rejected"; message?: string };
type PilotControl = "pause" | "resume";
const pilotControlKey = "qtrades-paper-pilot-control";
const savedControl = (): PilotControl | null => {
  const action = localStorage.getItem(pilotControlKey);
  return action === "pause" || action === "resume" ? action : null;
};
const controlConfirmed = (value: RoleState, action: PilotControl) => value.paper_pilot === true
  && value.readiness.stages?.policy?.state === "declared"
  && value.readiness.configured_enabled === (action === "resume")
  && (action === "pause" || value.readiness.enabled === true);
type ActionError = { kind: "question"; message: string } | { kind: "task-detail" | "task-retry"; task: string; message: string };
const stamp = (seconds: number) => new Date(seconds * 1000).toLocaleString();
const stages: Record<string, string> = { idea: "Model investigation", evaluate: "Compute method check", archive_evaluation: "Save exact inputs", review: "Independent review", submit: "Ordinary paper admission", outcome: "Await comparison outcome", followup: "Supported follow-up", data_wait: "Await required data", tool_wait: "Await tool implementation review", complete: "Research complete" };
const activityLabels: Record<NonNullable<RoleState["activity"]>["state"], string> = {
  running: "Working on a saved question", waiting: "Waiting", queued: "Work queued",
  idle: "Idle", paused: "Paused", unavailable: "Unavailable",
};
const selectionLabels: Record<NonNullable<RoleState["question_selection"]>["state"], string> = {
  selected: "Saved evidence-driven question", waiting: "Waiting for eligible evidence or prior work",
  disabled: "Automatic question selection disabled", unavailable: "Question selection unavailable",
};
const toolKinds: Record<ToolRequest["kind"], string> = {
  strategy_family: "Strategy method", feature: "Feature", analysis_tool: "Analysis tool",
};

const linkedTask = () => new URLSearchParams(location.hash.split("?")[1] ?? "").get("task");

function patternLinks(pattern: PatternComparison) {
  const selection = pattern.selection;
  if (!/^patterns-[a-f0-9]{24}$/.test(pattern.campaign_id) ||
    !/^daily-[a-f0-9]{24}$/.test(selection.daily_id) || selection.symbol !== "BTCUSD" || selection.timeframe !== "5m" ||
    !["patterns", "alerts"].includes(selection.event_kind) || !Number.isSafeInteger(selection.event_seq) || selection.event_seq < 1) return null;
  const finding = new URLSearchParams({ symbol: selection.symbol, scanner_campaign: pattern.campaign_id, daily_shortlist: selection.daily_id });
  const progress = pattern.coverage.find(row => row.timeframe === selection.timeframe)?.progress_sha256;
  if (typeof progress === "string" && /^[a-f0-9]{64}$/.test(progress) && Number.isSafeInteger(pattern.original_event.bar_open_ms)) {
    finding.set("scanner_chart_frame", selection.timeframe);
    finding.set("scanner_chart_at_ms", String(pattern.original_event.bar_open_ms));
    finding.set("scanner_chart_kind", selection.event_kind);
    finding.set("scanner_chart_seq", String(selection.event_seq));
    finding.set("scanner_chart_progress_sha256", progress);
  }
  const preparation = new URLSearchParams({ symbol: selection.symbol });
  const requestValid = /^[A-Za-z0-9_-]{8,64}$/.test(pattern.preparation_request_id);
  if (requestValid) preparation.set("pattern_comparison_request", pattern.preparation_request_id);
  return { finding: `#markets?${finding}`, preparation: requestValid ? `#markets?${preparation}` : null, capturedChart: finding.has("scanner_chart_progress_sha256") };
}

function PatternTaskEvidence({ pattern, fixed }: { pattern: PatternComparison; fixed?: FixedMethod }) {
  const links = patternLinks(pattern);
  const original = pattern.original_evaluation;
  return <section aria-label="Saved pattern research evidence">
    <h4>Original native finding and fixed comparison</h4>
    <p>This saved scanner finding motivates an experimental comparison. The scanner's level detector and the fixed bank method differ; recognition and numerical eligibility do not establish a trading advantage.</p>
    <p><strong>Original finding:</strong> {pattern.selection.symbol} · {pattern.selection.timeframe} · {pattern.original_event.kind} · {new Date(pattern.original_event.bar_open_ms).toLocaleString()}.</p>
    <p>{pattern.original_event.reason}</p>
    <p>Recorded level ${pattern.original_event.level_price} · volume ratio {pattern.original_event.volume_ratio ?? "unknown"} · volume confirmation {pattern.original_event.volume_confirmed === true ? "recorded" : pattern.original_event.volume_confirmed === false ? "not confirmed" : "unknown"}. Daily evidence captured {stamp(pattern.captured_at)}.</p>
    {links ? <p><a href={links.finding}>Reopen original daily finding</a>{links.preparation && <> · <a href={links.preparation}>Reopen original preparation</a></>}</p> : <p>Original navigation identity is unavailable; the retained evidence remains below.</p>}
    <p>{links?.capturedChart ? "The historical chart link keeps the captured progress hash. Later scanner progress may refuse that original window; it does not replace the saved finding." : "A captured chart progress hash is unavailable; the finding link opens its original daily record without claiming an exact historical chart window."} Reopening these records does not prepare or submit another comparison.</p>
    <h5>Original captured coverage</h5>
    <ul>{pattern.coverage.map(row => <li key={row.timeframe}>{row.timeframe}: {row.status} · {row.observed_bars ?? "unknown"} of {row.expected_bars ?? "unknown"} bars · {row.missing_bars ?? "unknown"} missing · {row.gap_count ?? "unknown"} gaps.</li>)}</ul>
    <h5>Preparation-time proof and numerical check</h5>
    <p>Prepared {stamp(pattern.prepared_at)}. Original numerical status: <strong>{original.status}</strong>{original.evaluated_at != null ? ` · evaluated ${stamp(original.evaluated_at)}` : ""}{original.expires_at != null ? ` · original expiry ${stamp(original.expires_at)}` : ""}. This retained check is not current admission or an economic outcome.</p>
    <p>Native archive verification: {pattern.native_proof.archive_verified === true ? "recorded" : "unverified"} · {pattern.native_proof.recognition_rows} recognition rows · {pattern.native_proof.pivot_rows} pivot rows · relevant window {pattern.native_proof.contiguous_relevant_window === true ? "contiguous" : "unknown or incomplete"}. {pattern.native_proof.coverage_claim}</p>
    {original.matched_inputs && <p>Original preparation used {original.matched_inputs.count} matched closed-minute inputs · cutoff {stamp(original.matched_inputs.cutoff)} · archive verification {original.matched_inputs.archive_verified === true ? "recorded" : "unverified"}.</p>}
    <details><summary>Original finding, preparation digests and proof</summary><pre>{JSON.stringify({ selection: pattern.selection, campaign_id: pattern.campaign_id, original_event: pattern.original_event, coverage: pattern.coverage, preparation_request_id: pattern.preparation_request_id, issued_bundle_sha256: pattern.issued_bundle_sha256, finding_sha256: pattern.finding_sha256, native_proof: pattern.native_proof, original_evaluation: original }, null, 2)}</pre></details>
    <h5>Frozen method and separately captured execution inputs</h5>
    <p>{pattern.mapping.rule_version}: {pattern.mapping.strategy} compared with {pattern.mapping.reference} · {pattern.mapping.holding_horizon} holding horizon. The exact entry, exit, timing and cost controls are retained below. Legacy lookback and common volume-multiple fields are inapplicable to this fixed v4 method.</p>
    {fixed ? <>
      <p>Fixed candidate entry: {fixed.candidate.entry} Reference entry: {fixed.reference.entry}</p>
      <p>{fixed.candidate.exit.feature_seconds / 60}-minute closed-candle features · maximum holding time {fixed.candidate.exit.maximum_hold / 3600} hours · fixed review {fixed.candidate.exit.review / 3600} hours · comparison evaluation window {fixed.candidate.evaluation.seconds / 3600} hours.</p>
      <p>At task capture: {fixed.current_inputs.count} separate closed-minute inputs · cutoff {stamp(fixed.current_inputs.cutoff)} · archive verification {fixed.current_inputs.archive_verified === true ? "recorded" : "unverified"}. Native scanner candles were not substituted for these execution inputs.</p>
      <details><summary>Fixed candidate and reference controls with task input identity</summary><pre>{JSON.stringify(fixed, null, 2)}</pre></details>
    </> : <p>The task's fixed controls or separate input identity are unavailable. The original preparation does not supply a current check.</p>}
    <ul>{pattern.mapping.limits.map((limit, index) => <li key={index}>{limit}</li>)}</ul>
  </section>;
}

export function RoleResearchPanel() {
  const [state, setState] = useState<RoleState | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [selected, setSelected] = useState(() => linkedTask() ?? localStorage.getItem("qtrades-role-task") ?? "");
  const selectedTask = useRef(selected);
  selectedTask.current = selected;
  const [before, setBefore] = useState(0);
  const [beforeId, setBeforeId] = useState("");
  const [search, setSearch] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [error, setError] = useState<ActionError | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [statusObservedAt, setStatusObservedAt] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [controlBusy, setControlBusy] = useState(false);
  const [controlPending, setControlPending] = useState<PilotControl | null>(savedControl);
  const [controlError, setControlError] = useState<string | null>(null);
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
        try {
          const response = await fetch(`/api/lab/roles?before=${before}&before_id=${encodeURIComponent(beforeId)}&search=${encodeURIComponent(search)}`, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) });
          if (!response.ok) throw new Error("Role status disconnected. Saved questions and paper operation remain separate.");
          const value = await response.json() as RoleState;
          if (live) {
            setState(value); setStatusError(null); setStatusObservedAt(Date.now() / 1000);
            const pending = savedControl();
            if (pending && controlConfirmed(value, pending)) {
              if (localStorage.getItem(pilotControlKey) === pending) localStorage.removeItem(pilotControlKey);
              setControlPending(null); setControlError(null);
            }
          }
        } catch (cause) {
          if (live) setStatusError(cause instanceof Error ? cause.message : "Role status unavailable");
          return;
        }
        if (selected) {
          try {
            const detail = await fetch(`/api/lab/roles/tasks/${encodeURIComponent(selected)}`, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(6000)]) });
            if (!detail.ok) throw new Error("Saved task detail is unavailable; retry when connected.");
            const saved = await detail.json() as Task;
            if (live) {
              setTask(saved); setTaskError(null);
              setError(current => current?.kind === "task-detail" && current.task === saved.id ? null : current);
            }
          } catch (cause) {
            if (live) setTaskError(cause instanceof Error ? cause.message : "Saved task detail unavailable");
          }
        }
      } finally { if (live) timer = setTimeout(() => void poll(), 10000); }
    };
    void poll();
    return () => { live = false; controller.abort(); clearTimeout(timer); };
  }, [selected, before, beforeId, search, refresh]);
  const open = (id: string) => {
    selectedTask.current = id;
    if (id !== selected) { setTask(null); setTaskError(null); }
    setSelected(id);
    localStorage.setItem("qtrades-role-task", id);
    setRefresh(r => r + 1);
    const params = new URLSearchParams({ task: id });
    location.hash = `role-research?${params}`;
  };
  useEffect(() => {
    const restore = () => { const id = linkedTask(); if (id !== null) { selectedTask.current = id; setTask(null); setTaskError(null); setSelected(id); } };
    window.addEventListener("hashchange", restore);
    return () => window.removeEventListener("hashchange", restore);
  }, []);
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
          setError({ kind: "task-detail", task: receipt.task, message: "Your question was saved. Its detail is temporarily unavailable; reopen the saved question when connected." });
          return;
        }
        throw new Error(typeof receipt === "string" ? receipt : receipt?.message ?? "Question acknowledgment is unknown; reconcile the saved request.");
      }
      if (typeof value.id !== "string") throw new Error("Question acknowledgment is incomplete; reconcile the saved request.");
      open((value as Task).id); setTask(value as Task); forget(); setRefresh(r => r + 1);
    } catch (cause) { setError({ kind: "question", message: cause instanceof Error ? cause.message : "Question acknowledgment unknown; retry the same saved request." }); }
    finally { setBusy(false); }
  };
  const enqueue = (event: FormEvent) => {
    event.preventDefault();
    if (busy || retry || !manualQuestions) return;
    void submit({ question, horizon, parent: parent || null, request_id: crypto.randomUUID() });
  };
  const retryStage = async () => {
    if (!task) return;
    const identity = task.id;
    setBusy(true);
    try {
      const response = await fetch(`/api/lab/roles/tasks/${encodeURIComponent(identity)}/retry`, { method: "POST", headers: { "X-Local-Operator": "1" }, signal: AbortSignal.timeout(6000) });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail ?? "This completed verdict cannot be retried.");
      if (value.id !== identity) throw new Error("Retry acknowledgment belongs to another task; inspect the retained task.");
      if (selectedTask.current === identity) setTask(value as Task);
      setRefresh(r => r + 1);
      setError(current => current?.kind === "task-retry" && current.task === identity ? null : current);
    } catch (cause) { setError({ kind: "task-retry", task: identity, message: cause instanceof Error ? cause.message : "Retry acknowledgment unavailable; inspect the retained task." }); }
    finally { setBusy(false); }
  };
  const controlPilot = async (action: PilotControl) => {
    const retained = savedControl();
    if (retained && retained !== action) {
      setControlPending(retained); setControlError("Reconcile the earlier pilot control before changing it."); return;
    }
    setControlBusy(true); setControlError(null);
    localStorage.setItem(pilotControlKey, action); setControlPending(action);
    try {
      const response = await fetch("/api/lab/roles/control", {
        method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" },
        body: JSON.stringify({ action }), signal: AbortSignal.timeout(10000),
      });
      const value = await response.json();
      if (!response.ok) {
        if (response.status === 403 || response.status === 409 || response.status === 422) {
          if (localStorage.getItem(pilotControlKey) === action) localStorage.removeItem(pilotControlKey);
          setControlPending(null);
        }
        throw new Error(typeof value.detail === "string" ? value.detail : "Pilot control acknowledgment unavailable; refresh its current status.");
      }
      setState(value as RoleState); setStatusObservedAt(Date.now() / 1000); setStatusError(null);
      if (controlConfirmed(value as RoleState, action)) {
        if (localStorage.getItem(pilotControlKey) === action) localStorage.removeItem(pilotControlKey);
        setControlPending(null);
      }
    } catch (cause) { setControlError(cause instanceof Error ? cause.message : "Pilot control acknowledgment unavailable; refresh its current status."); }
    finally { setControlBusy(false); setRefresh(r => r + 1); }
  };
  const pilot = state?.paper_pilot === true;
  const patternQuestions = state?.contract === "reviewed-rule-role-v8";
  const manualQuestions = !statusError && !!state?.contract && ["reviewed-rule-role-v5", "reviewed-rule-role-v6", "reviewed-rule-role-v7"].includes(state.contract);
  const stageLabel = (stage: string) => pilot && stage === "review" ? "Model review" : stages[stage] ?? stage;
  return <section id="role-research" className="panel role-research" aria-labelledby="role-title">
    <h2 id="role-title">Local model research</h2>
    <p>Investigate a permitted question, compare reviewed rules, and follow the recorded paper outcome. Numerical calculation and paper admission retain their existing authority.</p>
    {pilot && <section aria-label="Experimental paper research pilot">
      <h3>Experimental paper research pilot</h3>
      <p>Find improvements supported by evidence, compare alternatives in paper trading, retain unsuccessful experiments, and use recorded results to choose the next question.</p>
      <p>This trained model is experimental and unqualified. Its approved paper research permissions are separate from model qualification and promotion.</p>
      <button type="button" disabled={controlBusy || !!controlPending || (!!statusError && !state?.enabled)} onClick={() => void controlPilot(state!.enabled ? "pause" : "resume")}>{controlBusy ? "Saving pilot control…" : state?.enabled ? "Pause paper research" : "Resume approved paper pilot"}</button>
      <p>Pause stops new model requests and cancels an owned active request. Saved questions, answers and paper history remain available. Resume rechecks the same approved profile and current protected prerequisites.</p>
      {controlPending && <p role="status">The {controlPending} acknowledgment is unresolved. Refresh status, then reconcile this same control if needed. <button type="button" disabled={controlBusy} onClick={() => setRefresh(r => r + 1)}>Refresh pilot status</button> <button type="button" disabled={controlBusy || !!statusError} onClick={() => void controlPilot(controlPending)}>Reconcile pilot control</button></p>}
      {controlError && <p role="alert">{controlError}</p>}
      {state?.current_task && <p>{statusError ? "Last observed task" : "Current task"}: <button type="button" onClick={() => open(state.current_task!.id)}>{state.current_task.question}</button> · {stageLabel(state.current_task.stage)} · {state.current_task.status}. {state.current_task.reason}</p>}
    </section>}
    <p role="status">{statusError ? "Research status unavailable · current runtime and dispatch readiness are unverified" : state ? pilot ? `Experimental paper pilot · worker ${state.enabled ? "enabled" : "disabled"} · model setup ${state.readiness.stages?.runtime?.state ?? "unverified"} · ${state.readiness.ready ? "ready for bounded paper research" : "waiting for prerequisites"}` : `Research policy ${state.enabled ? "enabled" : "disabled"} · declared profile qualification ${state.readiness.qualification_valid ? "verified" : "unverified"} · runtime ${state.readiness.stages?.runtime?.state ?? "unverified"} · ${state.readiness.ready ? "ready for bounded dispatch" : "waiting for prerequisites"}` : "Loading actual role status…"}</p>
    <section aria-label="Research activity">
      {state?.activity ? <>
        <p role="status">{statusError ? "Last observed activity" : "Current activity"}: <strong>{activityLabels[state.activity.state]}</strong> · {state.activity.reason}</p>
        <p>{statusError ? "Last observed pending work" : "Pending work"}: {state.activity.pending_tools} tool requests · {state.activity.pending_data} data dependencies · {state.activity.pending_outcomes} comparison outcomes · {state.activity.queued} queued questions. Checked {stamp(state.activity.checked_at)}.</p>
      </> : <p role="status">{!state && !statusError ? "Loading actual research activity…" : "Current research activity is unavailable."}</p>}
    </section>
    <section aria-label="Evidence-driven question selection">
      {state?.question_selection ? <>
        <p role="status">{statusError ? "Last observed question selection" : "Current question selection"}: <strong>{selectionLabels[state.question_selection.state]}</strong> · {state.question_selection.reason}</p>
        {state.question_selection.task && <p><button type="button" onClick={() => open(state.question_selection!.task!)}>Open the selected saved question</button></p>}
        {state.question_selection.evidence != null && <details><summary>{statusError ? "Last observed selection evidence" : "Selection evidence"}</summary><pre>{JSON.stringify(state.question_selection.evidence, null, 2)}</pre></details>}
      </> : <p role="status">{!state && !statusError ? "Loading question selection status…" : "Automatic question selection status is unavailable."}</p>}
    </section>
    {statusError && state && statusObservedAt !== null && <p>Retained observation from {stamp(statusObservedAt)}: research policy {state.enabled ? "enabled" : "disabled"} · declared profile qualification {state.readiness.qualification_valid ? "verified" : "unverified"}. Reconnect before treating these observations as current.</p>}
    {state?.readiness.model && <p>{statusError ? "Last observed model" : "Model"} {state.readiness.model}</p>}
    {state?.readiness.reason && <p>{statusError ? "Last observed reason: " : ""}{state.readiness.reason}</p>}
    {state?.readiness.stages && <div aria-label="Research readiness and recovery"><h3>{statusError ? "Last observed readiness and next actions" : "Readiness and next actions"}</h3><ul>{Object.entries(state.readiness.stages).map(([name, stage]) => <li key={name}><strong>{statusError ? "Last observed " : ""}{name}: {stage.state}</strong> · {stage.next_action}</li>)}</ul></div>}
    {state?.readiness.operating_admission && <p>{statusError ? "Last observed operating admission" : "Operating admission"}: <strong>{state.readiness.operating_admission.state}</strong> · checked {stamp(state.readiness.operating_admission.checked_at)}.<br />{state.readiness.operating_admission.next_action}<br />{state.readiness.operating_admission.meaning}</p>}
    {state?.readiness.roles && <ul>{Object.entries(state.readiness.roles).map(([role, value]) => <li key={role}>{statusError ? "Last observed " : ""}{role}: {value.qualified ? "Qualified for the declared profile" : value.reason}</li>)}</ul>}
    {state?.readiness.profile != null && <details><summary>{statusError ? "Last observed model profile and digest" : "Exact current model profile and digest"}</summary><pre>{JSON.stringify(state.readiness.profile, null, 2)}</pre></details>}
    <p>{statusError ? "Last observed policy: " : ""}{state?.reason}</p>
    {!!state?.supervision?.length && <section aria-label="Research worker recovery"><h3>{statusError ? "Last observed worker recovery" : "Worker recovery"}</h3><ul>{state.supervision.map(item => <li key={item.phase}><strong>{item.phase}: {item.status}</strong> · {item.reason} · recorded {stamp(item.updated)}{item.retry_at > 0 ? ` · next bounded retry ${stamp(item.retry_at)}` : ""}</li>)}</ul></section>}
    {statusError && <p role="alert">{statusError} <button type="button" onClick={() => setRefresh(r => r + 1)}>Retry status</button></p>}
    {taskError && <p role="alert">{taskError} <button type="button" onClick={() => setRefresh(r => r + 1)}>Retry task detail</button></p>}
    {error && <p role="alert">{error.message} <button type="button" onClick={() => setRefresh(r => r + 1)}>Retry status</button></p>}
    {patternQuestions && <section aria-label="Pattern research questions">
      <h3>{statusError ? "Last observed question mode: saved patterns" : "Questions selected from saved patterns"}</h3>
      {statusError && <p>The current research mode is unverified. New manual questions remain unavailable until status reconnects.</p>}
      <p>This research mode selects new questions automatically from saved native pattern findings. It waits when evidence or operating prerequisites are unavailable. Manual questions are not supported in this mode.</p>
      {retry && <p>Your earlier manual request remains below for recovery. It has not been replaced by an automatic question.</p>}
    </section>}
    {(!patternQuestions || retry) && <form onSubmit={enqueue}>
      {!manualQuestions && !patternQuestions && <p role="status">The current research mode is unverified. Reconnect status before saving a new question. Recovery of an original request remains available.</p>}
      <label>Research question <textarea disabled={busy || !!retry} required minLength={12} maxLength={500} value={retry?.body.question ?? question} onChange={e => setQuestion(e.target.value)} /></label>
      <label>Holding horizon <select disabled={busy || !!retry} value={retry?.body.horizon ?? horizon} onChange={e => setHorizon(e.target.value)}><option value="short">Short</option><option value="medium">Medium</option><option value="long">Long</option></select></label>
      <label>Preserved parent trial (optional) <input disabled={busy || !!retry} value={retry ? retry.body.parent ?? "" : parent} maxLength={100} onChange={e => setParent(e.target.value)} /></label>
      <button disabled={busy || !!retry || !manualQuestions} type="submit">{busy ? "Saving…" : "Save research question"}</button>
      {retry?.phase === "unknown" && <>
        <p role="status">We do not know whether this question was saved. Reconcile this original request before changing it.</p>
        <button disabled={busy} type="button" onClick={() => void submit(retry.body)}>Reconcile saved request</button>
      </>}
      {retry?.phase === "rejected" && <>
        <p role="status">Your question was not saved. {retry.message} You can correct or discard it.</p>
        <button disabled={busy} type="button" onClick={() => { setQuestion(retry.body.question); setHorizon(retry.body.horizon); setParent(retry.body.parent ?? ""); forget(); setError(null); }}>Edit rejected question</button>
        <button disabled={busy} type="button" onClick={() => { forget(); setError(null); }}>Discard rejected question</button>
        {!patternQuestions && <button disabled={busy || !manualQuestions} type="button" onClick={() => { if (manualQuestions) void submit({ ...retry.body, request_id: crypto.randomUUID() }); }}>Try rejected question again</button>}
      </>}
    </form>}
    <p>{patternQuestions ? "Automatic selection does not enable model inference. Each dispatch still requires its declared permissions, activation, current inputs and resource limits." : pilot ? "Saved and evidence-driven questions use the approved experimental paper pilot. Each request rechecks its permissions, current inputs and resource limits; unavailable inputs remain a recorded wait." : "Saving a question does not enable inference. A declared paper policy, current role qualification and separate activation are required."}</p>
    {state?.history && <p>{state.history.retained} retained questions · {state.history.active} active · {state.history.archived} archived. Completed details reopen from their verified original record.</p>}
    <form onSubmit={e => { e.preventDefault(); setSearch(searchDraft.trim()); setBefore(0); setBeforeId(""); }}>
      <label>Search saved questions <input value={searchDraft} maxLength={100} onChange={e => setSearchDraft(e.target.value)} /></label>
      <button type="submit">Search history</button>
      {search && <button type="button" onClick={() => { setSearch(""); setSearchDraft(""); setBefore(0); setBeforeId(""); }}>Show all questions</button>}
    </form>
    <div className="table-scroll"><table><thead><tr><th>Saved question</th><th>Stage</th><th>Status</th><th>Actual last progress</th></tr></thead><tbody>{state?.tasks.map(t => <tr key={t.id}><td><button type="button" onClick={() => open(t.id)}>{t.question ?? t.id}</button></td><td>{stageLabel(t.stage)}</td><td>{t.status}{t.reason ? ` · ${t.reason}` : ""}</td><td>{stamp(t.updated)}</td></tr>)}</tbody></table></div>
    {before !== 0 && <button type="button" onClick={() => { setBefore(0); setBeforeId(""); }}>Latest questions</button>}
    {state?.next_before && <button type="button" onClick={() => { setBefore(state.next_before!); setBeforeId(state.next_before_id ?? ""); }}>Older questions</button>}
    {task && <article aria-label="Saved research task">
      <h3>{task.context.question.question}</h3><p>{task.context.question.horizon} horizon · {stageLabel(task.stage)} · {task.status} · progress {stamp(task.updated)}</p>
      <p>{statusError || taskError ? "Last observed ownership" : "Current ownership"}: {task.execution?.kind ?? "Unknown"}{task.execution?.actor ? ` · ${task.execution.actor}` : ""}{task.execution?.lease_until ? ` · lease ends ${stamp(task.execution.lease_until)}` : ""}. Executed actor and proposal identity appear in the retained attempts below.</p>
      {task.reason && <p>{task.reason}</p>}
      {task.contract_applicability && task.contract_applicability.state !== "matching" && <p role="status" aria-label="Saved question format applicability">{statusError || taskError ? "Last observed research format" : "Current research format"}: <strong>{task.contract_applicability.state === "different" ? "Saved question inactive for the selected format" : "Current format unknown"}</strong>. {task.contract_applicability.reason}</p>}
      {task.context.question_selection && <section aria-label="Why this research question was selected">
        <h4>Evidence-driven question · experimental paper research</h4>
        <p>This saved investigation is unqualified research. Its selection does not establish strategy value or authorize promotion.</p>
        <p><strong>Why this question:</strong> {task.context.question_selection.reason}</p>
        <p><strong>What would disprove the idea:</strong> {task.context.question_selection.falsification}</p>
        <p><strong>Captured source:</strong> {task.context.question_selection.source_count} closed bars · {stamp(task.context.question_selection.source_start)} to {stamp(task.context.question_selection.source_end)} · {task.context.question_selection.horizon} horizon.</p>
        {task.context.question_selection.source_basis && <p><strong>Recorded source basis:</strong> {task.context.question_selection.source_basis}</p>}
        <p><strong>Prior lesson reference:</strong> {task.context.question_selection.lesson?.id ?? (task.context.question_selection.lesson === null ? "No prior lesson used for this selection." : "Unavailable in this saved selection.")}</p>
        {!!task.context.question_selection.limitations.length && <><h5>Uncertainties and limits</h5><ul>{task.context.question_selection.limitations.map((limit, index) => <li key={index}>{limit}</li>)}</ul></>}
        <details><summary>Saved selection provenance and frozen comparison identities</summary><pre>{JSON.stringify(task.context.question_selection, null, 2)}</pre></details>
      </section>}
      {task.context.pattern_comparison && <PatternTaskEvidence pattern={task.context.pattern_comparison} fixed={task.context.fixed_comparison?.p0} />}
      {task.result?.action === "request_tool" && task.result.tool_request && <section aria-label="Requested research tool">
        <h4>Tool requested · pending implementation review</h4>
        <p><strong>{toolKinds[task.result.tool_request.kind]}:</strong> {task.result.tool_request.identifier}</p>
        <p><strong>Purpose:</strong> {task.result.tool_request.purpose}</p>
        <p>The saved request remains attached to this question while implementation review is pending.</p>
        <h5>Needed inputs</h5>
        <ul>{task.result.tool_request.required_inputs.map((input, index) => <li key={index}>{input}</li>)}</ul>
        <h5>Acceptance checks</h5>
        <ul>{task.result.tool_request.acceptance_checks.map((check, index) => <li key={index}>{check}</li>)}</ul>
        <p><strong>Supporting evidence from the saved question:</strong> {task.result.evidence_ids?.join(", ") ?? "References unavailable"}</p>
        {task.result.rationale && <p><strong>Reason for the request:</strong> {task.result.rationale}</p>}
        {task.result.falsification && <p><strong>What would disprove the idea:</strong> {task.result.falsification}</p>}
      </section>}
      {task.status === "failed" && task.stage === "archive_evaluation" && (!pilot || task.context.execution_mode === "paper_research_pilot") && <button disabled={busy} type="button" onClick={() => void retryStage()}>Retry saved evidence archive</button>}
      {task.status === "failed" && ["idea", "review", "followup"].includes(task.stage) && task.attempts.length > 0 && !task.attempts.at(-1)?.response && (!pilot || task.context.execution_mode === "paper_research_pilot") && <button disabled={busy} type="button" onClick={() => void retryStage()}>Authorize one recorded transport retry</button>}
      <h4>{task.context.pattern_comparison ? "Separate execution evidence at task capture" : "Captured causal evidence"}</h4><p>{task.context.tool_evidence.security} · {task.context.tool_evidence.closed_bar_count} closed bars · captured {stamp(task.context.tool_evidence.observed_at)} · {task.context.tool_evidence.source_basis}</p>
      <FrozenComponentPanel task={task.id} catalog={task.context.catalog} />
      <ul>{Object.entries(task.context.tool_evidence.features).map(([key, feature]) => <li key={key}>{key}: {feature.eligible ? "Entry qualified at capture" : "No eligible entry at capture"}. {feature.reason} {feature.close ? `Close $${feature.close}.` : ""}</li>)}</ul>
      <details><summary>{task.context.pattern_comparison ? "Execution evidence summary and permitted capabilities" : "Exact evidence, executed input tool and permitted capabilities"}</summary>{task.context.pattern_comparison && <p>The complete inputs remain retained with this task. This display preserves the captured count and digest without exposing archive file paths.</p>}<pre>{JSON.stringify({ inputs: task.context.pattern_comparison ? { security: task.context.tool_evidence.security, source_basis: task.context.tool_evidence.source_basis, closed_bar_count: task.context.tool_evidence.closed_bar_count, closed_bar_sha256: task.context.tool_evidence.closed_bar_sha256, observed_at: task.context.tool_evidence.observed_at, features: task.context.tool_evidence.features, matched_inputs: task.context.fixed_comparison?.p0.current_inputs } : task.context.tool_evidence, issued: task.context.issued, capabilities: task.context.catalog }, null, 2)}</pre></details>
      {task.evaluation && <><h4>{task.context.pattern_comparison ? "Numerical evaluation for this task" : "Computed method check"}</h4><p>{task.evaluation.input_count} causal input bars checked at {stamp(task.evaluation.evaluated_at)}. {task.evaluation.feature.reason} {task.evaluation.replay}</p>{task.context.pattern_comparison && <p>This task-stage calculation is separate from the original preparation-time check. Its recorded time does not establish current readiness or a measured trading result.</p>}<details><summary>Exact calculated result and saved input reference</summary><pre>{JSON.stringify(task.evaluation, null, 2)}</pre></details></>}
      {task.result?.review && <p>{task.context.execution_mode === "paper_research_pilot" ? "Experimental model review" : "Independent review"}: {task.result.review.action} · {task.result.review.rationale}</p>}
      {task.proposal && <><p>{task.proposal.strategy.version === "reviewed-lab-rules-v4" ? `Proposed ${task.proposal.kind}: fixed ${task.proposal.strategy.family}, compared with fixed ${task.proposal.reference.family}.` : `Proposed ${task.proposal.kind}: ${task.proposal.strategy.family} with ${task.proposal.strategy.lookback} bars, compared with ${task.proposal.reference.family} using ${task.proposal.reference.lookback} bars.`}</p><details><summary>Validated ordinary paper proposal</summary><pre>{JSON.stringify(task.proposal, null, 2)}</pre></details></>}
      {task.result?.proposal_id && <p>Ordinary inbox: {task.result.proposal_id} · pair {task.result.trial_id ?? "awaiting capacity, funding or outcome maturity"}</p>}
      {task.proposal?.strategy.entry_filter && <p>Entry component: frozen historical memory · {task.proposal.strategy.entry_filter.horizon_seconds / 60} minutes · artifact {task.proposal.strategy.entry_filter.artifact.sha256} · marginal ${task.proposal.strategy.entry_filter.marginal_daily_usd}/day · fallback {task.proposal.strategy.entry_filter.fallback}. Baseline exits and financial risk remain authoritative.</p>}
      {task.result?.outcome && <section><h4>Recorded comparison: {task.result.outcome.body.outcome}</h4><p>{task.result.outcome.body.reason}</p><p>Window {stamp(task.result.outcome.body.window_start)} to {stamp(task.result.outcome.body.window_end)} · outcome available {stamp(task.result.outcome.body.available_at)}.</p><p>Whole-account result after declared operating costs: candidate ${task.result.outcome.body.net_after_operating_usd?.candidate ?? "unknown"}; reference ${task.result.outcome.body.net_after_operating_usd?.reference ?? "unknown"}; difference ${task.result.outcome.body.delta_usd ?? "unknown"}. Execution fees remain counted once.</p><p>{task.result.outcome.body.qualification}</p><details><summary>Recorded comparison outcome</summary><pre>{JSON.stringify(task.result.outcome, null, 2)}</pre></details></section>}
      {task.result?.followup && <p>Supported follow-up: {task.result.followup.action} · {task.result.followup.rationale} {task.result.followup.dependency}</p>}
      <details><summary>Model attempts, final answers and resource receipts</summary>{task.attempts.map((a, i) => <div key={i}>
        <h4>{a.stage} · {a.status}</h4>
        <p>{stamp(a.started)} {a.finished ? `to ${stamp(a.finished)}` : "completion pending or unknown"} {a.reason}</p>
        {a.stage.startsWith("development_") && <p>Development-only attempt. Any retained answer is unqualified and has no financial or operating authority.</p>}
        <pre>{JSON.stringify({ profile: a.profile, final_response: a.response }, null, 2)}</pre>
        {["idea", "review", "followup"].includes(a.stage) && task.context.execution_mode !== "paper_research_pilot" && <TrainingCandidateExport key={`${task.id}-${a.stage}-${a.attempt}`} task={task.id} stage={a.stage} attempt={a.attempt} completed={a.finished !== null && a.response !== null} />}
      </div>)}</details>
    </article>}
    <LessonPanel openTask={open} />
    <StockResearchPanel />
    <ResearchActorPanel selectedTask={selected || null} />
    <ResearchQualityPanel experimentalPilot={pilot} />
  </section>;
}
