import { useEffect, useState, type ReactNode } from "react";
import { ArrowRight, BrainCircuit, Clock3, ScanLine, ShieldCheck } from "lucide-react";
import type { PaperSnapshot } from "./PaperPanel";
import { PerformanceChart } from "./WorkspaceViews";
import { ResearchAttention } from "./ResearchAttention";

export type Observation<T> = { available: boolean; observed_at: number; data: T | null; reason?: string };
export type ResearchTask = { id: string; question: string; created: number; updated: number; stage: string; status: string; reason: string | null; decision_summary?: string | null; retry_at?: number; market?: string; horizon?: string };
export type ResearchState = {
  enabled: boolean; paper_pilot: boolean; reason: string; current_task: ResearchTask | null; active_tasks: ResearchTask[];
  activity: { state: string; reason: string; checked_at: number; queued: number; pending_tools: number; pending_data: number; pending_outcomes: number };
  question_selection: { state: string; reason: string; policy: string | null; task?: string };
  tasks: ResearchTask[]; history: { retained: number; archived: number; active: number };
  readiness: { ready?: boolean; configured_enabled?: boolean; stages?: Record<string, { state: string; next_action: string }>; operating_admission?: { state: string; next_action: string }; reason?: string };
  supervision: { phase: string; status: string; reason: string | null; retry_at: number; updated: number }[];
};
export type ResearchScope = { identity: string; control_revision: string; start_refusal: string | null; requires_restart: boolean; grant_id: string; configured_enabled: boolean; automatic_questions: boolean; question_policy: string | null; methods: string[]; markets: string[]; reference: string; model: string; qualified: boolean; concurrency: number; duration: string; finite_test: { not_before: number; expires_at: number; max_requests: number } | null; hourly_tokens: number; hourly_wall_seconds: number; timeout_seconds: number; model_cost_usd: string | null };
export type ComparisonState = { configured: boolean; policy_identity: string | null; control_revision: number | null; policy: { starting_cash: string; horizon_seconds: number; daily_operating_usd: string; daily_trials: number; hourly_steps: number; hourly_compute_seconds: number; slots: number; holding_horizons: string[] } | null; proposals_paused: boolean | null; entries_paused: boolean | null; phase: string | null; reason: string | null; next_check_at: number | null; last_score_at: number | null; slots: { used: number; capacity: number; available: number }; last_error: string | null };
type Markets = { enabled: boolean; status: string; reason: string | null; progress_counts: Record<string, number>; progress_total: number; current_campaign_id: string | null };
type Notice = { key: string; state: string; severity: string; source_error?: string | null; current_condition: string; condition_evidence: { title: string; impact: string; next_action: string; link: string }; last_check_at: number };
type Attention = { operational: Notice[]; detector_last_check_at: number | null; detector_error: string | null };
export type ProductOverview = { queried_at: number; research: Observation<ResearchState>; scope: Observation<ResearchScope>; comparisons: Observation<ComparisonState>; markets: Observation<Markets>; attention: Observation<Attention> };

export const researchTime = (value?: number | null) => value && Number.isFinite(value) ? new Date(value * 1000).toLocaleString("en-US", { timeZone: "America/Denver", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " MT" : "Not scheduled";
export const researchStage: Record<string, string> = { idea: "Investigating the evidence", evaluate: "Checking the proposed method", archive_evaluation: "Retaining the exact check", review: "Reviewing the hypothesis", submit: "Admitting the matched paper comparison", outcome: "Waiting for the comparison result", followup: "Interpreting the result", data_wait: "Waiting for required inputs", tool_wait: "Waiting for a supported capability", complete: "Decision retained" };
export const investigationLink = (id: string) => `#research?task=${encodeURIComponent(id)}`;

export function useProductOverview(refresh = 0) {
  const [data, setData] = useState<ProductOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const read = async () => {
      try {
        const response = await fetch("/api/research/overview", { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(7000)]) });
        if (!response.ok) throw new Error("Current operation is unavailable. Reconnect to confirm the saved state.");
        const value = await response.json() as ProductOverview;
        if (active) { setData(value); setError(null); }
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "Current operation unavailable"); }
      finally { if (active) timer = setTimeout(() => void read(), document.hidden ? 30000 : 8000); }
    };
    void read();
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [refresh]);
  return { data, error };
}

function Operation({ title, state, reason, link, children }: { title: string; state: string; reason: string; link: string; children?: ReactNode }) {
  return <article className="workspace-card operation-card" aria-label={title} data-state={state}>
    <div className="card-heading"><h2>{title}</h2><span className="pill neutral">{state}</span></div>
    <p>{reason}</p>{children}<a className="text-link" href={link}>Inspect {title.toLowerCase()} <ArrowRight size={14} /></a>
  </article>;
}

export function ResearchOverview({ paper, unavailable }: { paper?: PaperSnapshot; unavailable: boolean }) {
  const { data, error } = useProductOverview();
  const [showNotices, setShowNotices] = useState(() => new URLSearchParams(location.hash.split("?")[1] ?? "").has("notice"));
  useEffect(() => {
    const restore = () => { if (new URLSearchParams(location.hash.split("?")[1] ?? "").has("notice")) setShowNotices(true); };
    window.addEventListener("hashchange", restore);
    return () => window.removeEventListener("hashchange", restore);
  }, []);
  const research = !error && data?.research.available ? data.research.data : null;
  const markets = !error && data?.markets.available ? data.markets.data : null;
  const comparisons = !error && data?.comparisons.available ? data.comparisons.data : null;
  const attention = !error && data?.attention.available ? data.attention.data : null;
  const scope = !error && data?.scope.available ? data.scope.data : null;
  const task = research?.current_task ?? research?.active_tasks[0];
  const recovery = (row: ResearchState["supervision"][number]) => row.status === "failed" || row.status === "waiting" && (row.phase !== "questions" || row.reason?.startsWith("Research questions unavailable"));
  const recovering = research?.supervision.some(recovery);
  const modelState = !research ? "Unavailable" : !research.readiness.stages?.policy || research.readiness.stages.policy.state === "unavailable" ? "Unconfigured" : !research.enabled ? "Paused" : recovering ? "Recovering" : research.activity.state === "running" ? "Working" : research.activity.pending_tools > 0 ? "Blocked" : research.activity.state === "queued" && !research.readiness.ready ? "Waiting for resources" : "Waiting";
  const marketState = !markets ? "Unavailable" : markets.status === "not_prepared" ? "Unconfigured" : !markets.enabled ? "Paused" : markets.status === "incomplete" ? "Blocked" : markets.status === "monitoring" ? "Waiting for closed candles" : "Working";
  const paperState = unavailable ? "Unavailable" : paper?.paused ? "New entries paused" : "Running";
  const activeNotices = attention?.operational.filter(row => row.state !== "recovered" && row.state !== "clear" || !!row.source_error) ?? [];
  const priority: Record<string, number> = { critical: 0, error: 1, warning: 2 };
  const notices = [...new Map(activeNotices.map(row => [row.key, row])).values()].sort((a, b) => (priority[a.severity] ?? 3) - (priority[b.severity] ?? 3));
  const recent = research?.tasks.filter(row => ["done", "failed"].includes(row.status)).slice(0, 5) ?? [];
  return <div className="product-overview">
    <section className="workspace-card product-intro" aria-label="Supervised paper research">
      <div><p className="eyebrow">SUPERVISED PAPER RESEARCH</p><h2>Understand the work. Follow the evidence.</h2><p>Paper execution, market analysis and model research have separate controls. A wait for useful evidence can be normal operation.</p></div>
      <a href="#settings?view=setup" className="button primary">Review research setup <ArrowRight size={16} /></a>
    </section>
    {error && <p role="alert" className="error-banner">{error} Retained investigations remain available in Research.</p>}
    <div className="operation-grid">
      <Operation title="Paper execution" state={paperState} reason={unavailable ? "Current processing and marks are unconfirmed. Inspect the financial status before acting." : paper?.paused ? "Position management and reconciliation continue under the saved entry pause." : "The deterministic engine manages orders, cash, positions and risk."} link="#accounts">
        <p className="fine-print">{Object.keys(paper?.accounts ?? {}).length} separate hypothetical accounts. Their balances are not one investable portfolio.</p>
      </Operation>
      <Operation title="Market analysis" state={marketState} reason={markets?.reason ?? (marketState === "Unconfigured" ? "Choose the approved saved market-analysis scope in Markets." : markets?.status === "monitoring" ? "Saved scopes are waiting for new closed candles; the application checks them while enabled." : markets ? "The saved analysis scope retains its coverage and controls." : "The market-analysis owner could not be observed.")} link="#markets">
        {!!markets?.progress_total && <p>{markets.progress_counts.monitoring ?? 0} of {markets.progress_total} market/timeframe scopes monitoring. Incomplete coverage stays recorded.</p>}
      </Operation>
      <Operation title="Model research" state={modelState} reason={research?.activity.reason ?? "Current model activity and permission are unconfirmed."} link="#research">
        {research && <p>{research.activity.queued} queued · {research.activity.pending_data} input waits · {research.activity.pending_outcomes} comparison waits · {research.activity.pending_tools} capability decisions.</p>}
        {scope && <p className="fine-print">{scope.methods.join(" / ")} against {scope.reference.toLowerCase()}. {scope.duration}.</p>}
      </Operation>
    </div>
    <div className="product-columns">
      <section className="workspace-card" aria-label="Current investigation and next action">
        <div className="card-heading"><h2><BrainCircuit size={18} /> Current investigation</h2><a className="text-link" href="#research">All research <ArrowRight size={14} /></a></div>
        {task ? <><h3><a href={investigationLink(task.id)}>{task.question}</a></h3><p>{researchStage[task.stage] ?? task.stage} · {task.status}</p><p>Began {researchTime(task.created)} · last meaningful task update {researchTime(task.updated)}.</p>{task.reason && <p>{task.reason}</p>}</> : <p>{research ? research.activity.reason : "No current investigation can be confirmed until research status reconnects."}</p>}
        <h3><Clock3 size={16} /> What happens next</h3>
        {research ? <><p>{research.question_selection.state === "selected" ? "The application will continue the selected investigation under the saved scope as its required inputs, capacity and outcomes become available." : research.question_selection.reason}</p>{research.question_selection.task && <p><a href={investigationLink(research.question_selection.task)}>Follow the saved selected investigation</a></p>}
          <p>{research.enabled ? "The application owns permitted continuations, including while this page is closed. New requests still recheck the saved permission, current inputs and resources." : "Research stays paused until you explicitly resume its approved scope. Opening a page does not resume it."}</p></> : <p>The next research action is unavailable.</p>}
        <details><summary>Comparison and scheduling details</summary>
          {comparisons?.configured && <p>All paper comparisons: {comparisons.reason ?? comparisons.phase}. Next scheduled check {researchTime(comparisons.next_check_at)}. This is a check time, not promised completion.{comparisons.proposals_paused && " New comparison proposals remain paused."}</p>}
          {research?.supervision.map(row => <p key={row.phase}>{recovery(row) ? "Recovery" : "Scheduled investigation check"}: {row.reason ?? row.status} · next bounded check {researchTime(row.retry_at)}.</p>)}
        </details>
      </section>
      <section className="workspace-card" aria-label="Decisions requiring attention">
        <div className="card-heading"><h2><ShieldCheck size={18} /> Do I need to act?</h2></div>
        {!attention || attention.detector_error || !attention.detector_last_check_at || Date.now() / 1000 - attention.detector_last_check_at > 45 ? <p role="status">Current attention checks are unavailable or out of date. No all-clear can be established.</p> : !notices.length ? <p>No current sampled operational fault. Saved permissions and ordinary waits are shown beside the work.</p> : notices.slice(0, 5).map(row => <article className="attention-item" key={row.key}><h3>{row.condition_evidence.title}</h3><p>{row.source_error ? "Current condition unconfirmed. " : ""}{row.condition_evidence.impact}</p><a href={row.condition_evidence.link}>{row.condition_evidence.next_action}</a></article>)}
        {!!notices.length && <p className="fine-print">Routine evidence waits do not authorize a retry or a preferred-answer search.</p>}
        {!scope && <p><a href="#settings?view=setup">Review the model connection and approved operating scope.</a></p>}
        {comparisons?.proposals_paused && <p><a href="#settings?view=setup">Review the saved comparison pause before resuming new proposals.</a></p>}
        <details open={showNotices} onToggle={event => setShowNotices(event.currentTarget.open)}><summary>Retained operational history and original receipts</summary>{showNotices && <ResearchAttention />}</details>
      </section>
    </div>
    <section className="workspace-card" aria-label="Recent research decisions">
      <div className="card-heading"><h2><ScanLine size={18} /> What happened</h2><a href="#research" className="text-link">Research history <ArrowRight size={14} /></a></div>
      {recent.length ? <ul className="investigation-list">{recent.map(row => <li key={row.id}><div><a href={investigationLink(row.id)}>{row.question}</a><p>{row.status === "done" ? row.decision_summary ?? "Open the retained decision, its evidence and limitations." : row.reason ?? "Interrupted work remains retained."}</p></div><span>{row.status === "failed" ? "Interrupted / failed; retained" : "Decision retained"}<small>{researchTime(row.updated)}</small></span></li>)}</ul> : <p>{research ? "No completed investigation appears in this bounded recent page. Older and interrupted work remains in Research history." : "Recent decisions are unavailable until research reconnects."}</p>}
    </section>
    <details className="workspace-details"><summary>Selected paper account performance</summary><PerformanceChart paper={paper} unavailable={unavailable} /><p>Funding, execution fees and the chosen window belong to this account. Operating-cost comparisons are in Accounts &amp; Results.</p></details>
    <p className="fine-print">Operation queried {researchTime(data?.queried_at)}. Query time and worker heartbeat are not a completed research result.</p>
  </div>;
}
