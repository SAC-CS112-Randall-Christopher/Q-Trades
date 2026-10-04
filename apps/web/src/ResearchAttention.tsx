import { useEffect, useState } from "react";
import { useEvidenceRead } from "./useEvidenceRead";

type Notice = { key: string; state: string; severity: string; last_confirmed_state: string; current_condition: string; first_observed_at: number; last_actual_occurrence: number | null; last_check_at: number; observations: number; active_observations: number; suppressed_active_observations: number; repeated_source_checks: number; recoveries: number; acknowledged_at: number | null; snoozed_until: number; condition_evidence: { title: string; severity: string; market: string | null; account: string | null; impact: string; next_action: string; link: string; facts: Record<string, unknown> } };
type Notices = { queried_at: number; detector_last_check_at: number | null; detector_error: string | null; operational: (Notice & { source_error?: string | null; invalid_source_checks?: number; last_source_epoch?: string })[]; developments: { id: string; created: number; updated: number; stage: string; status: string }[] | null; findings: { id: string; task: string; family: string; horizon: string; available_at: number }[] | null; basis: string; presentation: string; population: { more_developments: boolean | null; more_findings: boolean | null } };
const stamp = (value: number | null) => value == null ? "Unknown" : new Date(value * 1000).toLocaleString();

export function ResearchAttention() {
  const [data, setData] = useState<Notices | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<unknown>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const detailRead = useEvidenceRead();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const load = async () => {
      try {
        const response = await fetch("/api/research/notices", { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(4000)]) });
        if (!response.ok) throw new Error("Current notices unavailable; retained conditions are unconfirmed");
        const value = await response.json() as Notices;
        if (active) { setData(value); setError(null); }
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "Notices unavailable"); }
    };
    void load(); const timer = setInterval(() => { if (!document.hidden) void load(); }, 15000);
    return () => { active = false; controller.abort(); clearInterval(timer); };
  }, [refresh]);
  const present = async (key: string, action: string, seconds = 0) => {
    setBusy(true); setActionError(null);
    try {
      const response = await fetch("/api/research/notices/presentation", { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" }, body: JSON.stringify({ key, action, seconds }), signal: AbortSignal.timeout(4000) });
      if (!response.ok) throw new Error("Presentation save was not confirmed; reopen before retrying");
      setRefresh(n => n + 1);
    } catch (cause) { setActionError(cause instanceof Error ? cause.message : "Presentation unavailable"); }
    finally { setBusy(false); }
  };
  const inspect = async (key: string, navigate = true) => {
    const request = detailRead.begin(4000);
    setSelectedKey(key); setDetail(null); setDetailError(null); setDetailLoading(true);
    if (navigate) {
      const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
      params.set("notice", key);
      history.pushState(null, "", `${location.hash.split("?")[0] || "#dashboard"}?${params}`);
    }
    try {
      const response = await fetch(`/api/research/notices/${encodeURIComponent(key)}`, { cache: "no-store", signal: request.signal });
      if (!response.ok) throw new Error("Original condition receipts unavailable; retry this read");
      const value = await response.json();
      if (value.key !== key) throw new Error("Condition receipt identity differs");
      if (request.isCurrent()) setDetail(value);
    } catch (cause) { if (request.isCurrent()) setDetailError(cause instanceof Error ? cause.message : "Evidence unavailable"); }
    finally { if (request.isCurrent()) setDetailLoading(false); }
  };
  useEffect(() => {
    const restore = () => {
      const key = new URLSearchParams(location.hash.split("?")[1] ?? "").get("notice");
      if (key) void inspect(key, false);
      else { detailRead.cancel(); setSelectedKey(null); setDetail(null); setDetailError(null); setDetailLoading(false); }
    };
    restore(); window.addEventListener("hashchange", restore); window.addEventListener("popstate", restore);
    return () => { window.removeEventListener("hashchange", restore); window.removeEventListener("popstate", restore); };
  }, []);
  return <section className="research-activity" aria-label="Research attention and findings"><h2>Research attention and findings</h2>
    {error && <p role="alert">{error}. A missing poll does not mean recovery.</p>}
    {data?.detector_error && <p role="alert">{data.detector_error}</p>}
    {actionError && <p role="alert">{actionError}</p>}
    <button type="button" onClick={() => setRefresh(n => n + 1)}>Refresh notices</button>
    <h3>Operational attention</h3>
    {!data && <p>Current conditions are unknown until the notice registry is available.</p>}
    {data && !data.operational.length && <p>No retained operational thread. This does not establish continuous health.</p>}
    {data?.operational.map(row => { const source = row.condition_evidence; return <article className="activity-action" key={row.key} aria-label={source.title}>
      <h4>{source.title}</h4><p><strong>{error || data?.detector_error ? "unavailable" : row.state}</strong> · retained severity {row.severity} · {source.market ?? "shared paper/research service"} · {source.account ?? "affected accounts depend on these inputs"}</p>
      {row.source_error && <p role="alert">Source unconfirmed: {row.source_error}. {row.invalid_source_checks ?? 0} rejected checks; the previous confirmed condition remains recorded.</p>}
      <p>{source.impact}<br />Next: <a href={source.link}>{source.next_action}</a></p>
      <p>First observed {stamp(row.first_observed_at)}; last actual fault {stamp(row.last_actual_occurrence)}; last check {stamp(row.last_check_at)}. Last confirmed state {row.last_confirmed_state}.<br />{row.active_observations} sampled fault observations; {row.suppressed_active_observations} coalesced; {row.repeated_source_checks} unchanged-source checks; {row.recoveries} confirmed recoveries.</p>
      {(row.acknowledged_at !== null || row.snoozed_until > (data?.queried_at ?? 0)) && <p>Presentation: {row.acknowledged_at !== null ? `acknowledged ${stamp(row.acknowledged_at)}` : "unacknowledged"}; snooze until {stamp(row.snoozed_until || null)}. The condition and safety state remain visible.</p>}
      <button type="button" onClick={() => void inspect(row.key)}>Inspect original condition receipts</button>{" "}
      <button type="button" disabled={busy} onClick={() => void present(row.key, "acknowledge")}>Acknowledge presentation</button>{" "}
      <button type="button" disabled={busy} onClick={() => void present(row.key, "snooze", 300)}>Snooze presentation 5 min</button>
      <details><summary>Observed condition facts</summary><pre>{JSON.stringify(source.facts, null, 2)}</pre></details>
      {typeof source.facts.latest_reference === "string" && <a href={`/api/research/storage/evidence?reference=${encodeURIComponent(source.facts.latest_reference)}`} target="_blank" rel="noreferrer">Last retained recording — may precede this condition</a>}
    </article>; })}
    <h3>Research development</h3><p>Ordinary progress; these items do not interrupt or authorize an experiment.</p>
    {data?.developments == null ? <p>Research task metadata unavailable.</p> : !data.developments.length ? <p>No retained investigation.</p> : <ul>{data.developments.map(item => <li key={item.id}><a href={`#role-research?task=${encodeURIComponent(item.id)}`}>Open existing investigation</a> · {item.stage} / {item.status} · last progress {stamp(item.updated)}</li>)}</ul>}
    {data?.population.more_developments && <p>More retained questions remain in Local model research.</p>}
    <h3>Completed findings</h3><p>Open original support, limitations and next test through its existing disclosure path. A recorded finding is not a trade recommendation.</p>
    {data?.findings == null ? <p>Finding metadata unavailable.</p> : !data.findings.length ? <p>No retained mature research finding.</p> : <ul>{data.findings.map(item => <li key={item.id}><a href={`#role-research?task=${encodeURIComponent(item.task)}&lesson=${encodeURIComponent(item.id)}`}>Open recorded finding</a> · {item.family} / {item.horizon} · available {stamp(item.available_at)}</li>)}</ul>}
    {data?.population.more_findings && <p>More findings remain in Supported lessons.</p>}
    {selectedKey && <p>Selected condition: {selectedKey}{detailLoading ? " · reading original receipts…" : ""}</p>}
    {detailError && <p role="alert">{detailError}</p>}
    {detail != null && <details open><summary>Original operational observations</summary><pre>{JSON.stringify(detail, null, 2)}</pre></details>}
    <p className="indicator-readout">Detector checked {stamp(data?.detector_last_check_at ?? null)}. {data?.basis} {data?.presentation}. No off-device notification is promised.</p>
  </section>;
}
