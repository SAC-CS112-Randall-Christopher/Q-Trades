import { useEffect, useState, type FormEvent } from "react";
import { RetainedComparison } from "./RetainedComparison";
import "./market-chart.css";
import { ResearchStoragePanel } from "./ResearchStoragePanel";

type Proposal = { request_id: string; kind: string; parent_trial: string | null; strategy: { family: string; lookback: number }; mechanism: string; question: string };
type Score = { outcome: string; reason: string; available_at: number; delta_usd: string | null; net_after_operating_usd: Record<string, string | null> };
type Trial = { id: string; candidate: string; reference: string; status: string; review_at?: number; contract: { proposal: Proposal; changed: unknown; unchanged: unknown }; score?: Score };
type Account = { equity: string; net_pnl: string | null; fresh: boolean; protected: boolean; draining: boolean; entries_paused: boolean; risk_stop_id: string | null };
type Lab = { policy: { starting_cash: string; horizon_seconds: number; daily_operating_usd: string; daily_trials: number; hourly_steps: number; hourly_compute_seconds: number; registry_mib: number }; proposals_paused: boolean; entries_paused: boolean; phase: string; reason: string; next_action_at: number; last_score_at: number | null; historical_trials: number; initial_hypothetical_funding: string; retired_net_usd: string; retired_count: number; trials: Record<string, Trial>; budget: { trials: number; steps: number; compute_seconds: number; measured_seconds: number } };
type Snapshot = { enabled: boolean; lab: Lab | null; accounts: Record<string, Account>; slots: { used: number; capacity: number; managed: number; reserved: number; draining: number; available: number }; inbox: { proposals: { seq: number; request_id: string; status: string; reason: string | null }[] }; last_error: string | null };
type History = { trials: { id: number; at: number; body: Trial; decisions: { kind: string; at: number; body: Score }[] }[]; has_more: boolean; next_before: number };
const stamp = (at: number | null | undefined) => at == null ? "No completed activity" : new Date(at * 1000).toLocaleString();
const dollars = (v: string | null | undefined) => v == null ? "Unavailable" : Number(v).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 4 });
async function get(path: string) { const r = await fetch(path, { cache: "no-store" }); const b = await r.json(); if (!r.ok) throw new Error(b.detail ?? "Service unavailable"); return b; }
async function post(path: string, body: unknown) { const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" }, body: JSON.stringify(body) }); const b = await r.json(); if (!r.ok) throw new Error(b.detail ?? "Control unavailable"); return b; }

export function AutonomousPanel() {
  const [selectedTrial, setSelectedTrial] = useState(() => new URLSearchParams(location.hash.split("?")[1] ?? "").get("trial"));
  useEffect(() => { const restore = () => setSelectedTrial(new URLSearchParams(location.hash.split("?")[1] ?? "").get("trial")); window.addEventListener("hashchange", restore); window.addEventListener("popstate", restore); return () => { window.removeEventListener("hashchange", restore); window.removeEventListener("popstate", restore); }; }, []);
  const [data, setData] = useState<Snapshot | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [cursor, setCursor] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [inspection, setInspection] = useState<unknown>(null);
  const [proposal, setProposal] = useState("");
  const [limits, setLimits] = useState({ slots: 20, family_slots: 6, independent_slots: 4, daily_trials: 8, hourly_steps: 120, hourly_compute_seconds: 30, registry_mib: 512, minimum_disk_gib: 5 });
  const [capital, setCapital] = useState("100");
  const [hours, setHours] = useState(4);
  const [cost, setCost] = useState("");
  const [horizons, setHorizons] = useState(["short", "medium", "long"]);
  const [identity] = useState(() => "policy-" + crypto.randomUUID());
  const [exportAfter, setExportAfter] = useState(0);
  const refresh = async () => { const state = await get("/api/autonomous"); setData(state); setError(null); };
  useEffect(() => { let stopped = false; const update = async () => { try { const b = await get("/api/autonomous"); if (!stopped) { setData(b); setError(null); } } catch (e) { if (!stopped) setError(String(e)); } }; void update(); const timer = window.setInterval(update, 5000); return () => { stopped = true; clearInterval(timer); }; }, []);
  useEffect(() => { let stopped = false; get("/api/autonomous/history?before=" + cursor).then(b => { if (!stopped) setHistory(b); }).catch(e => { if (!stopped) setError(String(e)); }); return () => { stopped = true; }; }, [cursor, data?.lab?.historical_trials, data?.lab?.last_score_at, data?.lab?.retired_count]);
  const act = async (run: () => Promise<unknown>) => { setBusy(true); try { await run(); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); } };
  const control = (action: string, target?: string) => act(() => post("/api/autonomous/control", { action, target }));
  const inspect = (path: string) => act(async () => setInspection(await get(path)));
  const start = (e: FormEvent) => { e.preventDefault(); void act(() => post("/api/autonomous/start", { request_id: identity, ...limits, starting_cash: capital, horizon_seconds: hours * 3600, daily_operating_usd: cost, holding_horizons: horizons })); };
  const lab = data?.lab;
  const exportPage = () => act(async () => { const page = await get("/api/autonomous/export?after=" + exportAfter); const blob = new Blob([JSON.stringify(page, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `paper-lab-journal-after-${exportAfter}.json`; link.click(); URL.revokeObjectURL(url); if (page.next_after != null) setExportAfter(page.next_after); });
  return <section className="panel autonomous-panel" aria-label="Continuous paper research">
    {selectedTrial && <RetainedComparison key={selectedTrial} identity={selectedTrial} />}
    <details className="workspace-details" open={!selectedTrial}><summary>Current paper comparisons and retained history</summary>
    <div className="section-heading"><div><p className="eyebrow">CONTINUOUS PAPER RESEARCH</p><h2>Preserve useful parents. Test the next question.</h2></div><span className="badge">Exploration only</span></div>
    <p>One declared policy runs in the application worker. Frozen paired trials use equal funding, costs, risk and subsequent observations. Outcomes can be promising, unsuccessful, low information, inconclusive, data blocked or risk stopped. Qualification and human promotion keep their existing requirements.</p>
    {error && <p role="alert" className="warning">{error}</p>}
    {!data ? <p>Reading durable lab status…</p> : !lab ? <form onSubmit={start} className="lab-start-form">
      <label>Initial hypothetical USD per account<select value={capital} onChange={e => setCapital(e.target.value)}><option>100</option><option>50</option></select></label>
      <label>Fixed review horizon (hours)<input type="number" min="1" max="168" value={hours} onChange={e => setHours(Number(e.target.value))} required /></label>
      <label>Operating USD per account / day<input type="number" min="0" max="10" step="0.01" value={cost} onChange={e => setCost(e.target.value)} required /></label>
      <fieldset><legend>Declared holding horizons</legend>{[["short", "Short: 1m features, 45m hold, ≥1h review"], ["medium", "Medium: 5m features, 6h hold, ≥24h review"], ["long", "Long: 15m features, 3d hold, ≥7d review"]].map(([key, label]) => <label key={key}><input type="checkbox" checked={horizons.includes(key)} onChange={e => setHorizons(old => e.target.checked ? [...old, key] : old.filter(x => x !== key))} />{label}</label>)}<p>Each preset freezes warmup, outcome maturity, progress exits and retention together. Slower trials wait for adequate observed history and their full review window.</p></fieldset>
      <details className="lab-policy-limits"><summary>Allocation and resource budgets</summary><div className="lab-start-form">
        {([['slots', 'Concurrent managed/reserved slots', 10, 20], ['family_slots', 'Slots per family group (including its controls)', 2, 10], ['independent_slots', 'Slots reserved for independent ideas', 2, 8], ['daily_trials', 'Paired trials per UTC day', 1, 24], ['hourly_steps', 'Work steps per UTC hour', 4, 240], ['hourly_compute_seconds', 'Allocated work seconds per UTC hour', 1, 60], ['registry_mib', 'Retained registry capacity (MiB)', 32, 512], ['minimum_disk_gib', 'Free-space floor (GiB)', 1, 20]] as [keyof typeof limits, string, number, number][]).map(([key, label, min, max]) => <label key={key}>{label}<input type="number" min={min} max={max} value={limits[key]} onChange={e => setLimits(old => ({ ...old, [key]: Number(e.target.value) }))} required /></label>)}
      </div><p>Family and independent allocations must fit around the protected original six. The policy freezes on start; one optional job at a time and no paid calls.</p></details>
      <button disabled={busy} type="submit">Start declared paper lab</button>
    </form> : <>
      <div className="lab-metrics">
        <div><strong>{data.slots.used} / {data.slots.capacity}</strong><span>Concurrent slots · {data.slots.managed} managed · {data.slots.reserved} reserved · {data.slots.draining} draining · {data.slots.available} available</span></div>
        <div><strong>{lab.historical_trials}</strong><span>Historical trials · {lab.retired_count} retired accounts · initial lab allocations {dollars(lab.initial_hypothetical_funding)}</span></div>
        <div><strong>{dollars(lab.retired_net_usd)}</strong><span>Retired trading P/L after execution costs; before declared operating charges. Separate allocations are not pooled returns.</span></div>
      </div>
      <p><strong>Current action: {lab.phase}</strong> · {lab.reason}<br />Last scored outcome: {stamp(lab.last_score_at)} · Next check: {stamp(lab.next_action_at)}</p>
      <p>Policy: {dollars(lab.policy.starting_cash)} per account · {lab.policy.horizon_seconds / 3600} hour fixed reviews · {dollars(lab.policy.daily_operating_usd)} operating / day. UTC budgets used: {lab.budget.trials}/{lab.policy.daily_trials} trial admissions; {lab.budget.steps}/{lab.policy.hourly_steps} work steps; {lab.budget.compute_seconds.toFixed(2)}/{lab.policy.hourly_compute_seconds}s allocated ({lab.budget.measured_seconds.toFixed(3)}s measured). Crash reservations retain their allowance.</p>
      <div className="lab-controls">
        <button disabled={busy} onClick={() => void control(lab.proposals_paused ? "resume_proposals" : "pause_proposals")}>{lab.proposals_paused ? "Resume proposals" : "Pause proposals"}</button>
        <button disabled={busy} onClick={() => void control(lab.entries_paused ? "resume_entries" : "pause_entries")}>{lab.entries_paused ? "Resume lab entries" : "Pause lab new entries"}</button>
      </div>
      <div className="lab-trials">{Object.values(lab.trials).map(t => {
        const a = data.accounts[t.candidate], r = data.accounts[t.reference], p = t.contract.proposal;
        return <article className="lab-trial" key={t.id}><div className="section-heading"><h3>{p.strategy.family.replaceAll("_", " ")} · {p.kind}</h3><span className="badge">{t.status}</span></div>
          <p>{t.id}<br />{p.parent_trial ? `Parent: ${p.parent_trial}` : "Separately identified hypothesis"} · Lookback {p.strategy.lookback}<br />{p.question}</p>
          <p>Candidate equity {a?.fresh ? dollars(a.equity) : "Unavailable current mark"} · trading P/L {a?.fresh ? dollars(a.net_pnl) : "Unavailable"}<br />Matched reference {r?.fresh ? dollars(r.equity) : t.score ? "Completed; see frozen review" : "Awaiting fresh mark"} · Review {stamp(t.review_at)}</p>
          {!!a?.risk_stop_id && <p className="warning">Hard stop retained: {a.risk_stop_id}</p>}
          {t.score && <p><strong>{t.score.outcome}</strong> · {t.score.reason}<br />Fixed-window after operating: child {dollars(t.score.net_after_operating_usd.candidate)}, reference {dollars(t.score.net_after_operating_usd.reference)}, difference {dollars(t.score.delta_usd)}. Scored {stamp(t.score.available_at)}.</p>}
          <div className="lab-controls"><button onClick={() => setInspection(t)}>Inspect trial and exact changes</button><button onClick={() => void inspect("/api/autonomous/accounts/" + t.candidate)}>Account evidence</button>
            {a && !a.draining && <button disabled={busy} onClick={() => void control(a.protected ? "unprotect" : "protect", t.candidate)}>{a.protected ? "Unprotect experimental parent" : "Protect experimental parent"}</button>}
            <button disabled={busy || a?.protected || t.status === "draining"} onClick={() => void control("retire", t.id)}>Retire trial safely</button></div>
        </article>;
      })}</div>
    </>}
    <details><summary>Proposal inbox and permitted research evidence</summary><p>External workers use the same reviewed validator, evidence receipt, evaluation and admission path. Inputs are training information; sibling results are correlated.</p>
      <button disabled={busy} onClick={() => void inspect("/api/autonomous/bundle")}>Inspect permitted research bundle</button>
      <label>Reviewed proposal JSON<textarea rows={5} value={proposal} onChange={e => setProposal(e.target.value)} placeholder="Paste a proposal using the exact issued bundle hash" /></label>
      <button disabled={busy || !lab || !proposal} onClick={() => void act(() => post("/api/autonomous/proposals", JSON.parse(proposal)))}>Validate and submit proposal</button>
      {data?.inbox.proposals.map(p => <p key={p.seq}><button onClick={() => void inspect("/api/autonomous/proposals/" + p.request_id)}>{p.request_id}</button> · {p.status} {p.reason}</p>)}
    </details>
    <details><summary>Retained trial history and journal export</summary><p>Historical evidence remains after retirement. Each page is bounded; account records and financial journals retain their original identity.</p>
      {history?.trials.map(t => <article key={t.id} className="lab-history-row"><strong>{t.body.contract.proposal.kind} · {t.body.contract.proposal.strategy.family}</strong> · {stamp(t.at)}<br />{t.body.id} · {t.decisions.map(d => d.body.outcome ?? d.kind.replaceAll("_", " ")).join(" · ") || "Awaiting completion"}<div className="lab-controls"><button onClick={() => setInspection(t)}>Inspect retained trial</button><button onClick={() => void inspect("/api/autonomous/accounts/" + t.body.candidate)}>Candidate financial history</button><button onClick={() => void inspect("/api/autonomous/proposals/" + t.body.contract.proposal.request_id)}>Frozen inputs and evaluation</button></div></article>)}
      <div className="lab-controls"><button onClick={() => setCursor(0)}>Latest history</button><button disabled={!history?.has_more} onClick={() => setCursor(history!.next_before)}>Earlier history</button><button disabled={busy} onClick={() => void exportPage()}>Export next journal page (up to 500)</button></div><p>Next export cursor: {exportAfter}. Complete history is retrieved page by page.</p>
    </details>
    {inspection != null && <details open className="lab-inspection"><summary>Selected evidence</summary><button onClick={() => setInspection(null)}>Close evidence</button><pre>{JSON.stringify(inspection, null, 2)}</pre></details>}
    <ResearchStoragePanel />
    </details>
  </section>;
}
