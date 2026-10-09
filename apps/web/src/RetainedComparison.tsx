import { useEffect, useState } from "react";
import { researchTime } from "./ResearchOverview";
import { inContext } from "./productNavigation";

type Proposal = { question: string; strategy: { family: string; version: string }; reference: { family: string; version: string } };
type Score = { outcome: string; reason: string; window_start: number; window_end: number; available_at: number; qualification: string; delta_usd: string | null; net_after_operating_usd: { candidate: string | null; reference: string | null } };
type Admission = { environment: "paper"; trial_id: string; rule_sha256: string; expected_role_version: number; incumbent_configuration_sha256: string; implementation_sha256: string; approve_hypothetical_funding: true };
type Offer = { available: boolean; reason?: string; candidate: string; control: string | null; already_admitted: boolean; admitted_source?: { rule_sha256: string; role_version: number; incumbent_configuration_sha256: string; implementation_sha256: string }; rule_sha256: string; role_version: number; incumbent: string; incumbent_configuration_sha256: string; implementation_sha256: string; starting_capital_each: string; operating_daily_usd_each: string; execution_profile: string; slots: { available: number; used: number; capacity: number }; minimum_daily_blocks: number };
type SavedTrial = { id: number; at: number; body: { id: string; candidate: string; reference: string; contract: { proposal: Proposal; changed: unknown; unchanged: unknown } }; decisions: { kind: string; at: number; body: Score }[]; environment: "paper"; qualification_offer: Offer };
const admissionKey = (trial: string) => `qtrades:paper:qualification:${trial}`;

export function RetainedComparison({ identity }: { identity: string }) {
  const [data, setData] = useState<SavedTrial | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [approved, setApproved] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState<Admission | null>(null);
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError(null); setApproved(false);
    try { setPending(JSON.parse(localStorage.getItem(admissionKey(identity)) ?? "null")); } catch { setPending(null); }
    void fetch(`/api/autonomous/trials/${encodeURIComponent(identity)}`, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(7000)]) })
      .then(async response => { if (!response.ok) throw new Error("The original saved comparison is unavailable. Its identity is retained; current trials cannot replace it."); return response.json() as Promise<SavedTrial>; })
      .then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Original comparison unavailable."); });
    return () => controller.abort();
  }, [identity, refresh]);
  useEffect(() => {
    const saved = data?.qualification_offer.admitted_source;
    if (pending && saved && saved.rule_sha256 === pending.rule_sha256 && saved.role_version === pending.expected_role_version && saved.incumbent_configuration_sha256 === pending.incumbent_configuration_sha256 && saved.implementation_sha256 === pending.implementation_sha256) {
      localStorage.removeItem(admissionKey(identity)); setPending(null); setMessage("The original admission is confirmed. The same prospective pair continues; no duplicate funding was created.");
    }
  }, [data, pending, identity]);
  const offer = data?.qualification_offer;
  const offerIdentity = `${offer?.rule_sha256 ?? ""}:${offer?.role_version ?? ""}:${offer?.incumbent_configuration_sha256 ?? ""}:${offer?.implementation_sha256 ?? ""}`;
  useEffect(() => { if (!pending) setApproved(false); }, [offerIdentity, pending]);
  async function admit() {
    if (!offer?.available || busy || !approved && !pending) return;
    const command: Admission = pending ?? { environment: "paper", trial_id: identity, rule_sha256: offer.rule_sha256, expected_role_version: offer.role_version, incumbent_configuration_sha256: offer.incumbent_configuration_sha256, implementation_sha256: offer.implementation_sha256, approve_hypothetical_funding: true };
    localStorage.setItem(admissionKey(identity), JSON.stringify(command)); setPending(command); setBusy(true); setMessage(null);
    try {
      const response = await fetch("/api/paper/learning/rules", { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" }, body: JSON.stringify(command), signal: AbortSignal.timeout(8000) });
      const value = await response.json();
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) { localStorage.removeItem(admissionKey(identity)); setPending(null); }
        setMessage(`${response.status < 500 ? "Admission rejected" : "Acknowledgment unknown"}: ${value.detail ?? "Refresh the original source before retrying the same admission."}`);
      } else { localStorage.removeItem(admissionKey(identity)); setPending(null); setMessage("The separate prospective paper pair is funded. Original exploratory balances and evidence remain retained."); }
    } catch { setMessage("Funding acknowledgment is unknown. Refresh this original receipt to confirm the saved admission before retrying the same reviewed request."); }
    finally { setBusy(false); setRefresh(n => n + 1); }
  }
  const score = data?.decisions.find(row => row.kind === "lab_trial_scored")?.body;
  return <section className="workspace-card" aria-label="Selected saved paper comparison">
    <p className="eyebrow">PAPER · ORIGINAL SAVED COMPARISON</p>
    <h3>{data?.body.contract.proposal.question ?? "Selected matched comparison"}</h3>
    {error ? <p role="alert" className="warning">{error}</p> : !data ? <p>Opening this original comparison…</p> : <>
      <p>{data.body.contract.proposal.strategy.family.replaceAll("_", " ")} against {data.body.contract.proposal.reference.family.replaceAll("_", " ")}. Reserved {researchTime(data.at)}.</p>
      {score ? <><h4>{score.outcome.replaceAll("_", " ")}</h4><p>{score.reason}</p><p>Window {researchTime(score.window_start)} through {researchTime(score.window_end)}; available {researchTime(score.available_at)}.</p><p>After execution and declared operating costs: candidate ${score.net_after_operating_usd.candidate ?? "unknown"}; reference ${score.net_after_operating_usd.reference ?? "unknown"}; difference ${score.delta_usd ?? "unknown"}.</p><p>{score.qualification}</p></> : <p>No mature score is recorded for this comparison. Its current admission/review state remains with the existing comparison owner.</p>}
      <div className="heading-actions"><a className="text-link" href={inContext("#accounts", { account: data.body.candidate, trial: identity })}>Candidate account and costs</a><a className="text-link" href={inContext("#accounts", { account: data.body.reference, trial: identity })}>Matched reference account and costs</a><a className="text-link" href={inContext("#accounts?view=qualification", { account: data.body.candidate, trial: identity })}>Paper qualification requirements</a></div>
      <details className="startup-review" open={reviewOpen} onToggle={event => setReviewOpen(event.currentTarget.open)}><summary>Review prospective paper qualification</summary>
        {offer?.already_admitted ? <><p>This exact rule already has a separate prospective pair. Its original result remains exploratory.</p>{!offer.available && <p>{offer.reason}</p>}<a href={inContext("#accounts?view=qualification", { account: offer.candidate, trial: identity })}>Open this candidate’s qualification record</a></> : !offer?.available ? <p>{offer?.reason ?? "The original qualification source is unavailable."}</p> : <>
          <p>Freeze this supported rule against the current paper incumbent ({offer.incumbent}). Each new account receives ${offer.starting_capital_each} of separate hypothetical funding and ${offer.operating_daily_usd_each} of declared daily operating allocation, with the original {offer.execution_profile} cost model and existing hard stops.</p>
          <p>The pair uses two of {offer.slots.capacity} managed places; {offer.slots.available} are currently available. It requires {offer.minimum_daily_blocks} complete subsequent daily blocks and the existing after-cost, drawdown, stability and selection checks. The prior exploratory return cannot count toward qualification. No live activation follows.</p>
          <label className="review-choice"><input type="checkbox" checked={approved} disabled={busy || !!pending} onChange={event => setApproved(event.target.checked)} /> Approve the frozen source, matched incumbent and separate hypothetical pair.</label>
          <button type="button" disabled={busy || offer.slots.available < 2 || !approved && !pending} onClick={() => void admit()}>{busy ? "Confirming prospective admission…" : pending ? "Confirm the same reviewed admission" : "Fund reviewed prospective paper pair"}</button>
          {offer.slots.available < 2 && <p>Wait for capacity within the existing policy. This action cannot discard history or expand the account ceiling.</p>}
        </>}
      </details>
      <details><summary>Frozen rules, unchanged controls and original journal receipts</summary><pre>{JSON.stringify(data, null, 2)}</pre></details>
    </>}
    {message && <p role="status">{message}</p>}
    <button type="button" onClick={() => setRefresh(n => n + 1)}>Refresh original receipt</button>
  </section>;
}

export function RetainedAccount({ name }: { name: string }) {
  const [data, setData] = useState<{ state: Record<string, unknown>; retired_at: number | null; environment: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError(null);
    void fetch(`/api/autonomous/accounts/${encodeURIComponent(name)}`, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(7000)]) }).then(async response => {
      if (!response.ok) throw new Error("This original account is unavailable. No current account has been substituted."); return response.json();
    }).then(value => { if (!controller.signal.aborted) setData(value); }).catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [name]);
  const amount = (key: string) => typeof data?.state[key] === "string" ? `$${data.state[key]}` : "Unknown";
  return <section className="workspace-card" aria-label="Selected retained paper account"><p className="eyebrow">PAPER · ORIGINAL ACCOUNT</p><h3>{typeof data?.state.label === "string" ? data.state.label : name}</h3>{error ? <p role="alert">{error}</p> : !data ? <p>Opening the saved account…</p> : <><p>{data.retired_at ? `Retired ${researchTime(data.retired_at)}.` : "Active account observed."} Its balances, funding, fees, orders and history belong to this original hypothetical account.</p><dl className="setup-facts"><div><dt>Hypothetical funding</dt><dd>{amount("funding")}</dd></div><div><dt>Recorded cash</dt><dd>{amount("cash")}</dd></div><div><dt>Paid execution fees</dt><dd>{amount("fees")}</dd></div><div><dt>Declared daily operating allocation</dt><dd>{amount("operating_daily_usd")}</dd></div></dl><p>Recorded strategy: {String(data.state.version ?? "Unavailable")}. A retired cash balance is historical; it is not capital available to another account.</p><details><summary>Retained account financial record</summary><pre>{JSON.stringify(data, null, 2)}</pre></details></>}</section>;
}
