import { useEffect, useState, type ReactNode } from "react";
import { Activity, ArrowRight, BrainCircuit, Clock3, FlaskConical, Layers3, LockKeyhole, ScanLine, ShieldCheck, Wallet } from "lucide-react";
import type { PaperSnapshot } from "./PaperPanel";
import { inContext, useAccountScope } from "./productNavigation";

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

type QuoteSnapshot = { running: boolean; error: string | null; markets: { symbol: string; bid: string | null; ask: string | null; state: string; valid_for_ms: number }[] };
function useMarketWatch() {
  const [read, setRead] = useState<{ data: QuoteSnapshot; at: number } | null>(null);
  const [error, setError] = useState(false);
  const [now, setNow] = useState(performance.now());
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const response = await fetch("/api/station/live?symbol=BTCUSD", { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(7000)]) });
        if (!response.ok) throw new Error();
        const data = await response.json() as QuoteSnapshot;
        if (active) { setRead({ data, at: performance.now() }); setError(false); }
      } catch { if (active) setError(true); }
      finally { if (active) timer = setTimeout(() => void poll(), document.hidden ? 30000 : 8000); }
    };
    void poll();
    const clock = setInterval(() => setNow(performance.now()), 1000);
    return () => { active = false; controller.abort(); clearTimeout(timer); clearInterval(clock); };
  }, []);
  return { read, error, now };
}
const money = (value?: string | null) => value != null && Number.isFinite(Number(value)) ? Number(value).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }) : "Unavailable";
function Card({ title, href, action = "View all", className = "", children }: { title: string; href: string; action?: string; className?: string; children: ReactNode }) {
  return <section className={`workspace-card overview-card ${className}`} aria-label={title}>
    <div className="card-heading"><h2>{title}</h2><a className="text-link" href={inContext(href)}>{action} <ArrowRight size={13} /></a></div>{children}
  </section>;
}
export function ResearchOverview({ paper, unavailable }: { paper?: PaperSnapshot; unavailable: boolean }) {
  const { data, error } = useProductOverview();
  const watch = useMarketWatch();
  const [accountName] = useAccountScope("primary");
  const account = paper && Object.hasOwn(paper.accounts, accountName) ? paper.accounts[accountName] : undefined;
  const currentAccount = !unavailable && account?.valuation_fresh;
  const research = !error && data?.research.available ? data.research.data : null;
  const markets = !error && data?.markets.available ? data.markets.data : null;
  const comparisons = !error && data?.comparisons.available ? data.comparisons.data : null;
  const attention = !error && data?.attention.available ? data.attention.data : null;
  const task = research?.current_task ?? research?.active_tasks[0];
  const recovering = research?.supervision.some(row => row.status === "failed" || row.status === "waiting" && (row.phase !== "questions" || row.reason?.startsWith("Research questions unavailable")));
  const modelState = !research ? "Unavailable" : !research.readiness.stages?.policy || research.readiness.stages.policy.state === "unavailable" ? "Unconfigured" : !research.enabled ? "Paused" : recovering ? "Recovering" : research.activity.state === "running" ? "Working" : research.activity.pending_tools > 0 ? "Needs a decision" : "Waiting";
  const marketState = !markets ? "Unavailable" : markets.status === "not_prepared" ? "Unconfigured" : !markets.enabled ? "Paused" : markets.status === "incomplete" ? "Incomplete" : markets.status === "monitoring" ? "Monitoring" : markets.status.replaceAll("_", " ");
  const nextAction = !research ? "Reconnect to confirm the next research action." : modelState === "Unconfigured" ? "Review or choose a research scope in Settings before starting model research." : research.enabled ? research.question_selection.reason : "Research is paused by saved permission. Review the approved scope to resume.";
  const paperState = unavailable ? "Paper status unconfirmed" : paper?.paused ? "Paper entries paused" : "Paper Trading Active";
  const activeNotices = attention?.operational.filter(row => (row.state !== "recovered" && row.state !== "clear") || !!row.source_error) ?? [];
  const priority: Record<string, number> = { critical: 0, error: 1, warning: 2 };
  const notices = [...new Map(activeNotices.map(row => [row.key, row])).values()].sort((a, b) => (priority[a.severity] ?? 3) - (priority[b.severity] ?? 3));
  const attentionCurrent = attention && !attention.detector_error && !!attention.detector_last_check_at && Date.now() / 1000 - attention.detector_last_check_at <= 45;
  const recent = research?.tasks.slice(0, 4) ?? [];
  const stages = [
    ["Data Coverage", markets ? `${markets.progress_counts.monitoring ?? 0} / ${markets.progress_total} scopes monitoring` : "Observation unavailable", "#markets?view=coverage"],
    ["Scanner & Findings", marketState, "#markets?view=scanner"],
    ["Investigations", research ? `${research.history.active} active · ${modelState.toLowerCase()}` : "Observation unavailable", "#research"],
    ["Experiments", comparisons?.configured ? `${comparisons.slots.used} / ${comparisons.slots.capacity} slots occupied` : "Not configured / unavailable", "#results?view=comparisons"],
    ["Paper Qualification", "Review retained evidence", "#results?view=qualification"],
    ["Live Readiness", "Locked · review requirements", "#results?view=readiness"],
  ];
  return <div className="product-overview">
    {error && <p role="alert" className="error-banner">{error} Retained investigations remain available in Research.</p>}
    <div className="overview-grid">
      <section className="workspace-card overview-hero" aria-label="Paper execution">
        <div className="card-heading"><div className="hero-state"><span className={`hero-orb ${!unavailable ? "is-active" : ""}`} /><div><h2>{paperState}</h2><p>{unavailable ? "Reconnect to confirm processing and marks" : "Deterministic paper worker running under saved controls"}</p></div></div><a className="button secondary" href={inContext("#settings?view=system")}>Worker details <ArrowRight size={14} /></a></div>
        <div className="hero-metrics">
          <div><Activity /><span>Market analysis<strong>{marketState}</strong><small>{markets ? `${markets.progress_total} saved scopes` : "Owner unconfirmed"}</small></span></div>
          <div><FlaskConical /><span>Model research<strong>{modelState}</strong><small>{research ? `${research.activity.queued} queued · ${research.activity.pending_outcomes} outcome waits` : "Owner unconfirmed"}</small></span></div>
          <div><Clock3 /><span>Next comparison check<strong>{comparisons?.next_check_at ? researchTime(comparisons.next_check_at) : "Not scheduled"}</strong><small>Check time, not completion</small></span></div>
          <div><ShieldCheck /><span>Attention<strong>{attentionCurrent ? `${notices.length} current items` : "Unconfirmed"}</strong><small><a href={inContext("#overview?view=attention")}>Review decisions</a></small></span></div>
        </div>
        <div className="hero-context">{task ? <><span className="status-dot" /><a className="clamp-one" title={task.question} href={investigationLink(task.id)}>{researchStage[task.stage] ?? task.stage}: {task.question}</a></> : <><span className="status-dot" /><span className="clamp-one">{research?.activity.reason ?? "Research activity is unconfirmed."}</span></>}</div>
      </section>
      <section className="workspace-card overview-compass" aria-label="Research direction"><div><p className="eyebrow">FROM DATA TO DECISIONS</p><h2>Research with discipline.<br />Build on evidence.</h2><p>Systematic research, separate paper accounts and a measured path to live trading.</p><a className="text-link" href={inContext("#results?view=readiness")}>Explore the requirements <ArrowRight size={13} /></a></div><svg viewBox="0 0 400 150" aria-hidden="true"><defs><linearGradient id="mountain-fill" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#167d94" stopOpacity=".35" /><stop offset="1" stopColor="#167d94" stopOpacity="0" /></linearGradient></defs><path d="M0 150 73 105 108 118 175 58 200 72 277 4 330 75 350 63 400 115V150Z" fill="url(#mountain-fill)" stroke="#24596e" /><path d="M25 150 98 124 144 134 209 99 255 106 302 68 343 88 400 126" fill="none" stroke="#3dbb9e" strokeOpacity=".55" /></svg></section>
      <Card title="Research → Live Pipeline" href="#results?view=readiness" action="View requirements" className="overview-pipeline"><p className="card-caption">Each stage retains its own evidence and permission.</p><ol className="journey-stages">{stages.map(([title, state, href], index) => <li key={title}><a href={inContext(href)}><span className={`journey-node ${index === 5 ? "locked" : ""}`}>{index === 5 ? <LockKeyhole size={15} /> : index + 1}</span><strong>{title}</strong><small>{state}</small></a></li>)}</ol></Card>
      <Card title="Attention & Decisions" href="#overview?view=attention" className="overview-attention">
        {!attentionCurrent ? <p className="card-empty">Current attention checks are unavailable or out of date. No all-clear can be established.</p> : !notices.length ? <p className="card-empty"><ShieldCheck size={24} />No current sampled operational fault.<small>Saved permissions and ordinary waits still apply.</small></p> : <ul className="dashboard-list">{notices.slice(0, 4).map(row => <li key={row.key}><span className={`notice-dot ${row.severity}`} /><div><strong title={row.condition_evidence.title} className="clamp-two">{row.condition_evidence.title}</strong><p className="clamp-two">{row.source_error ? "Current condition unconfirmed. " : ""}{row.condition_evidence.impact}</p><a className="text-link" href={row.condition_evidence.link}>{row.condition_evidence.next_action} <ArrowRight size={12} /></a></div></li>)}</ul>}
        <div className="dashboard-next"><span className="eyebrow">NEXT RESEARCH ACTION</span><p className="clamp-three">{nextAction}</p><a className="text-link" href={inContext("#settings?view=setup")}>Review research setup <ArrowRight size={13} /></a>{task && <a className="text-link" href={investigationLink(task.id)}>See the current operation <ArrowRight size={13} /></a>}</div>
      </Card>
      <Card title="Market Watch" href="#markets" action="View markets" className="overview-markets"><p className="card-caption">Best observed bid / ask · public market data</p><ul className="dashboard-list quote-list">{watch.read?.data.markets.slice(0, 4).map(row => {
        const fresh = !watch.error && watch.read!.data.running && !watch.read!.data.error && row.state === "fresh" && watch.now - watch.read!.at < row.valid_for_ms;
        return <li key={row.symbol}><span className="market-token">{row.symbol.slice(0, 1)}</span><a href={inContext("#markets", { symbol: row.symbol })}>{row.symbol}</a><div><strong>{money(row.bid)} <small>/ {money(row.ask)}</small></strong><small className={fresh ? "positive" : "muted"}>{fresh ? "Current observation" : "Last observed · unconfirmed"}</small></div></li>;
      })}</ul>{!watch.read?.data.markets.length && <p className="card-empty">{watch.error ? "Market observations unavailable." : "Waiting for observed quotes…"}</p>}<a className="text-link card-bottom-link" href={inContext("#markets?view=scanner")}>Scanner & findings <ScanLine size={13} /></a></Card>
      <Card title="Account Snapshot" href={`#accounts?account=${encodeURIComponent(accountName)}`} action="View account" className="overview-account"><p className="card-caption"><Wallet size={13} />{account?.label ?? accountName} · separate paper account</p><div className="snapshot-equity"><span>Liquidation equity</span><strong>{currentAccount ? money(account.equity) : "Unconfirmed"}</strong></div><dl className="snapshot-grid"><div><dt>Cash available</dt><dd>{currentAccount ? money(account.cash) : "Unconfirmed"}</dd></div><div><dt>Open positions</dt><dd>{account ? Object.keys(account.positions).length : "Unavailable"}</dd></div><div><dt>Net P&L</dt><dd className={currentAccount && Number(account.net_pnl) >= 0 ? "positive" : ""}>{currentAccount ? money(account.net_pnl) : "Unconfirmed"}</dd></div><div><dt>Recorded fees</dt><dd>{account ? money(account.fees) : "Unavailable"}</dd></div></dl><p className="card-caption">{unavailable ? "Last reported holdings; worker status is unconfirmed." : account ? "Hypothetical balances. Net P&L includes execution fees." : "This exact account is unavailable. No other account was substituted."}</p></Card>
      <Card title="Recent Investigations" href="#research" className="overview-investigations"><p className="card-caption">Saved questions, current stages and original decisions</p><ul className="dashboard-list investigation-rows">{recent.map(row => <li key={row.id}><BrainCircuit size={16} /><div><a className="clamp-one" title={row.question} href={investigationLink(row.id)}>{row.question}</a><p className="clamp-one">{researchStage[row.stage] ?? row.stage}{row.decision_summary ? ` · ${row.decision_summary}` : ""}</p></div><span><span className="pill neutral">{row.status}</span><small>{researchTime(row.updated)}</small></span></li>)}</ul>{!recent.length && <p className="card-empty">{research ? "No investigations in this bounded recent page. Older records remain in Research History." : "Investigations are unavailable until research reconnects."}</p>}</Card>
      <Card title="Recent Journal / Changes" href="#history" className="overview-journal"><p className="card-caption">Recent paper events · original records stay in History</p><ul className="dashboard-list journal-preview">{paper?.events.slice(0, 4).map(row => <li key={row.id}><Layers3 size={15} /><div><strong className="clamp-one">{row.kind.replaceAll("_", " ")}</strong><small>{researchTime(row.at)}{unavailable ? " · last reported" : ""}</small></div><a href={inContext("#history?view=journal")}>Open</a></li>)}</ul>{!paper?.events.length && <p className="card-empty">No events in the latest observed window.</p>}<div className="readiness-note"><LockKeyhole size={18} /><div><strong>Live trading locked</strong><p>Qualification and a separate authorization are required.</p><a href={inContext("#results?view=readiness")}>View all requirements <ArrowRight size={12} /></a></div></div></Card>
    </div>
    <p className="fine-print overview-observed">Operation queried {researchTime(data?.queried_at)}. Query time and worker heartbeat are not a completed research result.</p>
  </div>;
}
