import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { AutonomousPanel } from "./AutonomousPanel";
import { researchTime, useProductOverview } from "./ResearchOverview";
import { ResearchConnection } from "./ResearchConnection";
import { pilotControlKey, researchControlLock, startupKey } from "./researchControls";

type Startup = { scope_identity: string; control_revision: string; policy_identity: string; comparison_revision: number; resume_comparisons: boolean };
type ComponentResult = { component: string; state: string; reason?: string };
const pendingKey = startupKey;
const existingPilotControl = pilotControlKey;
function savedStartup(): Startup | null {
  try { return JSON.parse(localStorage.getItem(pendingKey) ?? "null") as Startup | null; }
  catch { return null; }
}

export function ResearchSetup() {
  const [refresh, setRefresh] = useState(0);
  const { data, error } = useProductOverview(refresh);
  const [reviewed, setReviewed] = useState(false);
  const [resumeComparisons, setResumeComparisons] = useState(false);
  const [pending, setPending] = useState<Startup | null>(savedStartup);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [results, setResults] = useState<ComponentResult[]>([]);
  const scope = !error && data?.scope.available ? data.scope.data : null;
  const comparisons = !error && data?.comparisons.available ? data.comparisons.data : null;
  const research = !error && data?.research.available ? data.research.data : null;
  const identity = `${scope?.identity ?? ""}:${scope?.control_revision ?? ""}:${comparisons?.policy_identity ?? ""}:${comparisons?.control_revision ?? ""}:${comparisons?.proposals_paused ?? ""}`;
  useEffect(() => { if (!pending) { setReviewed(false); setResumeComparisons(false); } }, [identity, pending]);
  useEffect(() => {
    const reconcile = () => setPending(savedStartup());
    window.addEventListener("storage", reconcile);
    return () => window.removeEventListener("storage", reconcile);
  }, []);
  useEffect(() => {
    if (pending && scope?.identity === pending.scope_identity && scope.configured_enabled === true && research?.enabled === true && comparisons?.policy_identity === pending.policy_identity && comparisons.proposals_paused === false) {
      if (localStorage.getItem(pendingKey) === JSON.stringify(pending)) localStorage.removeItem(pendingKey);
      setPending(null);
      setMessage("The reviewed research scope is saved as enabled. The component status below shows whether work can proceed or is waiting.");
    }
  }, [pending, scope, comparisons, research]);
  const missing = error ? "Reconnect before reviewing or changing startup." : !scope ? "The approved local model scope is unavailable. Connect its existing reviewed profile and permission before starting." : scope.start_refusal ? scope.start_refusal : scope.requires_restart ? "The saved model connection is paused and needs an application restart to load its owner. Reopen setup after restart; it will not start work." : !scope.automatic_questions ? "This saved grant requires manual questions. An explicit automatic selection scope must be approved; this flow cannot widen that grant." : !comparisons?.configured ? "Declare the paper comparison policy below before enabling research." : comparisons.proposals_paused && !(pending?.resume_comparisons ?? resumeComparisons) ? "Review the saved comparison pause and choose whether to resume its existing policy." : localStorage.getItem(existingPilotControl) ? "Reconcile the saved research pause/resume command in Research first." : null;
  const start = async () => {
    if (!scope || !comparisons?.policy_identity || !reviewed || missing || busy) return;
    const body = pending ?? { scope_identity: scope.identity, control_revision: scope.control_revision, policy_identity: comparisons.policy_identity, comparison_revision: comparisons.control_revision!, resume_comparisons: resumeComparisons };
    if (body.scope_identity !== scope.identity || body.policy_identity !== comparisons.policy_identity) {
      setMessage("The unresolved startup refers to older settings. Keep the current saved controls, then review those settings again."); return;
    }
    if (!navigator.locks) { setMessage("This browser cannot coordinate startup between windows. Use a supported local browser."); return; }
    await navigator.locks.request(researchControlLock, { ifAvailable: true }, async lock => {
      if (!lock) { setMessage("Another window is saving research controls. Refresh its saved status before retrying."); return; }
      if (localStorage.getItem(existingPilotControl)) { setMessage("A research control is unresolved. Reconcile it in Research first."); return; }
      const existing = savedStartup();
      if (existing && JSON.stringify(existing) !== JSON.stringify(body)) { setPending(existing); setMessage("Another window has an unresolved startup. Reconcile that saved scope first."); return; }
      setBusy(true); setMessage(null); setResults([]);
      localStorage.setItem(pendingKey, JSON.stringify(body)); setPending(body);
      try {
        const response = await fetch("/api/research/supervised-start", { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" }, body: JSON.stringify(body), signal: AbortSignal.timeout(15000) });
        const value = await response.json();
        if (!response.ok) {
          if ([400, 403, 409, 422].includes(response.status)) {
            if (localStorage.getItem(pendingKey) === JSON.stringify(body)) localStorage.removeItem(pendingKey);
            setPending(null);
            throw new Error(typeof value.detail === "string" ? `Startup rejected: ${value.detail}` : "Startup rejected. Review the inline requirements.");
          }
          throw new Error("Startup acknowledgment is unavailable. Refresh and reconcile the same reviewed settings.");
        }
        const receipts = value.components as ComponentResult[];
        setResults(receipts);
        if (receipts.some(result => result.state === "rejected")) {
          if (localStorage.getItem(pendingKey) === JSON.stringify(body)) localStorage.removeItem(pendingKey);
          setPending(null); setReviewed(false);
        }
        setMessage("Startup returned component receipts. Refreshing the saved permission and policy; readiness and ordinary waits are shown separately.");
      } catch (cause) { setMessage(cause instanceof Error ? cause.message : "Startup acknowledgment is unknown. Reconcile its saved state."); }
      finally { setBusy(false); setRefresh(n => n + 1); }
    });
  };
  return <section className="workspace-card research-setup" aria-label="Research setup and resume">
    <div className="card-heading"><div><p className="eyebrow">SET UP ONCE · REVIEW SAVED CHOICES</p><h2>Supervised paper research</h2></div><a href="#overview" className="text-link">See current operation <ArrowRight size={14} /></a></div>
    <p>Review what is already saved. This flow reuses the existing allocation, model permission and research history. Optional external review and Training Lab work have separate settings.</p>
    {error && <p role="alert" className="warning">{error}</p>}
    <ol className="setup-review">
      <li><h3>Research scope and model</h3>{scope ? <><p>{scope.markets.join(", ")} · {scope.methods.join(" and ")} against {scope.reference}. {scope.duration}.</p><p>{scope.model} · experimental, unqualified paper research · {scope.concurrency} model request at a time. Each request reserves its declared allowance; unsuccessful attempts stay consumed.</p><p>{scope.hourly_tokens.toLocaleString()} reserved tokens and {scope.hourly_wall_seconds / 60} allocated model minutes per UTC hour; {scope.timeout_seconds / 60} minutes maximum per request. Measured model/electricity cost: {scope.model_cost_usd ?? "unknown"}.</p>{scope.finite_test && <p>Original finite window: {researchTime(scope.finite_test.not_before)} through {researchTime(scope.finite_test.expires_at)} · {scope.finite_test.max_requests} total reserved requests. Restart does not renew it.</p>}</> : <ResearchConnection onSaved={() => setRefresh(n => n + 1)} />}</li>
      <li><h3>Paper allocation, comparisons and costs</h3>{comparisons?.policy ? <><p>${comparisons.policy.starting_cash} hypothetical starting cash per separate account · {comparisons.policy.horizon_seconds / 3600}-hour policy review · declared operating allocation ${comparisons.policy.daily_operating_usd} per account/day.</p><p>{comparisons.slots.used} of {comparisons.slots.capacity} managed/reserved slots used · {comparisons.slots.available} available. Existing cash, positions, costs and frozen rules stay with their accounts.</p><p>{comparisons.policy.daily_trials} paired trial admissions per UTC day · {comparisons.policy.hourly_steps} work steps and {comparisons.policy.hourly_compute_seconds}s allocated deterministic work per UTC hour.</p><p>New comparison proposals: {comparisons.proposals_paused ? "paused" : "enabled"}. New paper entries: {comparisons.entries_paused ? "paused" : "permitted under their existing controls"}. Startup does not clear an entry pause or a hard stop.</p>{comparisons.proposals_paused && <label className="review-choice"><input type="checkbox" checked={resumeComparisons} disabled={busy || !!pending} onChange={e => { setResumeComparisons(e.target.checked); setReviewed(false); }} /> Resume this saved comparison policy, including its existing deterministic discovery, to admit eligible proposals.</label>}</> : <><p>The existing comparison policy needs configuration. The original owner’s form is available here; no accounts are funded merely by opening it.</p><details className="workspace-details"><summary>Declare the paper comparison policy</summary><AutonomousPanel /></details></>}</li>
      <li><h3>Inputs, schedule and recovery</h3><p>Market analysis: {data?.markets.available ? data.markets.data?.status.replaceAll("_", " ") : "unavailable"}. Research uses eligible retained evidence and separately checked current execution inputs. Paused analysis is resumed explicitly in <a href="#markets">Markets</a>; this action does not start an acquisition campaign.</p><p>While enabled, the existing application worker selects permitted questions and advances checks, review, paper admission, outcomes and lessons. It releases the model while waiting for real results. Closing this page leaves app-owned work running; restart retains pauses, expiry, attempts and controls.</p><p>Local research does not require an optional external provider or a new weight-training run. External review, training, promotion and any broader scope retain their own decisions.</p></li>
    </ol>
    <div className="startup-review">
      <h3>What “Start supervised paper research” enables</h3>
      <p>Resume only the existing reviewed model scope{resumeComparisons ? " and the saved comparison proposal policy" : ""}. It can select supported questions without manual seed text or proposal JSON. Deterministic admission still controls every financial effect. This action does not fund new capital, change a strategy or risk limit, enable live trading, or renew finite permission.</p>
      {research && <p>Current saved model permission: {research.enabled ? "enabled" : "paused / disabled"}. Current readiness: {research.readiness.ready ? "ready for bounded work" : "waiting for protected prerequisites"}. {research.readiness.operating_admission?.next_action}</p>}
      {missing && <p role="status" className="warning">{missing}</p>}
      <label className="review-choice"><input type="checkbox" checked={reviewed} disabled={busy || !!missing} onChange={e => setReviewed(e.target.checked)} /> I reviewed this saved scope and the startup actions above.</label>
      <div className="heading-actions"><button className="button primary" disabled={busy || !reviewed || !!missing} onClick={() => void start()}>{busy ? "Confirming component startup…" : pending ? "Reconcile reviewed startup" : "Start supervised paper research"}</button><button className="button secondary" disabled={busy} onClick={() => setRefresh(n => n + 1)}>Refresh saved state</button></div>
      {pending && <p role="status">Startup acknowledgment is unresolved. Refresh reads the saved owners without replaying startup. <button type="button" disabled={busy} onClick={() => { localStorage.removeItem(pendingKey); setPending(null); setReviewed(false); setMessage("The current saved controls are retained. Review them before any new startup action."); }}>Keep current saved controls</button></p>}
      {message && <p role="status">{message}</p>}
      {results.map(result => <p key={result.component}><CheckCircle2 size={14} /> {result.component === "model_research" ? "Model research" : "Paper comparisons"}: {result.state === "saved" ? "operating intent saved" : result.state}. {result.reason}</p>)}
    </div>
  </section>;
}
