import { useEffect, useState, type FormEvent } from "react";

type Plan = { name: string; mechanism: string; falsification: string; feature: string;
  horizon_minutes: number; test_start: number; test_end: number; as_of: number; request_id: string };
type Run = { seq: number; request_id: string; plan: Plan; status: string; progress: string;
  reason: string | null; attempt: number };
type Lab = { runs: Run[]; counts: Record<string, number>; protected_through: number;
  preflight_result: string; worker_running: boolean; blocked_reason: string | null;
  capacity: number; queue_capacity: number; next_cursor: number | null };
type Result = Run & { plan_sha256: string; code_sha256: string; snapshot_sha256: string;
  manifest: { rows: number; older_rows_omitted: boolean } | null;
  result: { status: string; reason?: string; decision: string; next_action: string;
    train_samples?: number; test_samples?: number; metrics?: Record<string, unknown>;
    limitations?: string[]; model?: Record<string, unknown>; evidence_kind?: string } | null;
  events: { at: number; kind: string; body: string }[] };
const stamp = (seconds: number) => new Date(seconds * 1000).toLocaleString();
const localDate = (seconds: number) => {
  const d = new Date(seconds * 1000);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

export function ExperimentLab() {
  const [lab, setLab] = useState<Lab | null>(null);
  const [before, setBefore] = useState(0);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("Five-minute momentum forecast");
  const [mechanism, setMechanism] = useState("Recent direction may persist beyond the execution cost hurdle.");
  const [falsification, setFalsification] = useState("Reject when out-of-sample forecasts fail the constant baseline or after-cost hurdle.");
  const [feature, setFeature] = useState("momentum_5");
  const [horizon, setHorizon] = useState(5);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState(localDate(Date.now() / 1000 - 60));
  const [retry, setRetry] = useState<Plan | null>(() => {
    try { return JSON.parse(localStorage.getItem("qtrades-experiment-retry") ?? "null") as Plan | null; }
    catch { return null; }
  });
  useEffect(() => {
    let live = true;
    const poll = async () => {
      try {
        const response = await fetch(`/api/lab?before=${before}`, { signal: AbortSignal.timeout(6000) });
        if (!response.ok) throw new Error("Research registry unavailable; paper operation is separate.");
        const data = await response.json() as Lab;
        if (live) { setLab(data); setStart(current => current || localDate(data.protected_through + 3660)); }
      } catch (e) { if (live) setError(e instanceof Error ? e.message : "Research unavailable"); }
    };
    void poll(); const timer = setInterval(() => void poll(), 5000);
    return () => { live = false; clearInterval(timer); };
  }, [before]);
  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    let live = true;
    const poll = async () => {
      const response = await fetch(`/api/lab/experiments/${encodeURIComponent(selected)}`,
        { signal: AbortSignal.timeout(6000) });
      if (!response.ok) throw new Error("Experiment result unavailable");
      const value = await response.json() as Result;
      if (live) setDetail(value);
    };
    void poll().catch(e => setError(String(e)));
    const timer = setInterval(() => void poll().catch(e => setError(String(e))), 5000);
    return () => { live = false; clearInterval(timer); };
  }, [selected]);
  async function post(url: string, body?: unknown) {
    const response = await fetch(url, { method: "POST", signal: AbortSignal.timeout(10000),
      headers: { "X-Local-Operator": "1", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body) });
    if (!response.ok) {
      const value = await response.json().catch(() => ({}));
      throw new Error(typeof value.detail === "string" ? value.detail : "Check the declared evaluation inputs");
    }
    return response.json() as Promise<{ request_id: string }>;
  }
  async function launch(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    const dates = new FormData(event.currentTarget as HTMLFormElement);
    const plan = retry ?? { request_id: crypto.randomUUID(), name, mechanism, falsification,
      feature, horizon_minutes: horizon, test_start: new Date(String(dates.get("test_start"))).getTime() / 1000,
      test_end: new Date(String(dates.get("test_end"))).getTime() / 1000, as_of: Date.now() / 1000 };
    try {
      localStorage.setItem("qtrades-experiment-retry", JSON.stringify(plan)); setRetry(plan);
      const value = await post("/api/lab/experiments", plan); setSelected(value.request_id);
      localStorage.removeItem("qtrades-experiment-retry"); setRetry(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Launch unconfirmed; retry the frozen request"); }
    finally { setBusy(false); }
  }
  return <section id="experiment-lab" className="panel experiment-lab">
    <div className="panel-heading"><div><span className="eyebrow">Protected numerical research</span>
      <h2>Experiments and retained evidence</h2></div><span className="paper-badge">Paper only · paid budget $0</span></div>
    <p>Freeze one hypothesis and evaluation window. Research runs outside order management;
      a rejection remains useful evidence. Changed features and files cannot reuse inspected information.</p>
    {lab && <p className="lab-status">Evidence protected through {stamp(lab.protected_through)}.
      Retained preflight: {lab.preflight_result}. Worker: {lab.worker_running ? "running" : "stopped"}.
      {lab.blocked_reason && ` ${lab.blocked_reason}.`} Queue limit {lab.queue_capacity}; receipt limit {lab.capacity}.</p>}
    {error && <p role="alert">{error}</p>}
    <form onSubmit={event => void launch(event)}><fieldset disabled={busy || !!retry}>
      <label>Hypothesis name<input value={name} onChange={e => setName(e.target.value)} required minLength={3} maxLength={100} /></label>
      <label>Why it might persist<textarea value={mechanism} onChange={e => setMechanism(e.target.value)} required minLength={12} maxLength={1000} /></label>
      <label>What would reject it<textarea value={falsification} onChange={e => setFalsification(e.target.value)} required minLength={12} maxLength={1000} /></label>
      <div className="lab-form-row"><label>Input<select value={feature} onChange={e => setFeature(e.target.value)}>
        <option value="momentum_1">One-minute direction</option><option value="momentum_5">Five-minute direction</option>
        <option value="volatility_5">Recent volatility</option><option value="spread_bps">Observed spread</option></select></label>
        <label>Forecast horizon<select value={horizon} onChange={e => setHorizon(Number(e.target.value))}>
          {[5, 15, 60].map(n => <option key={n} value={n}>{n} minutes</option>)}</select></label>
        <label>Untouched evaluation starts<input name="test_start" type="datetime-local" value={start} onChange={e => setStart(e.target.value)} onInput={e => setStart(e.currentTarget.value)} required /></label>
        <label>Evaluation ends<input name="test_end" type="datetime-local" value={end} onChange={e => setEnd(e.target.value)} onInput={e => setEnd(e.currentTarget.value)} required /></label></div>
      </fieldset><button type="submit" disabled={busy || !lab}>{busy ? "Freezing…" : retry ? "Confirm frozen request" : "Freeze and queue experiment"}</button>
      {retry && <button type="button" onClick={() => { setRetry(null); localStorage.removeItem("qtrades-experiment-retry"); }}>Edit a new plan</button>}
    </form>
    <div className="lab-runs">{lab?.runs.map(run => <button type="button" key={run.request_id}
      onClick={() => setSelected(run.request_id)} aria-pressed={selected === run.request_id}>
      <strong>{run.plan.name}</strong><span>{run.status} · attempt {run.attempt}</span><small>{run.reason ?? run.progress}</small></button>)}</div>
    <div className="lab-form-row"><button type="button" disabled={!before} onClick={() => setBefore(0)}>Latest experiments</button>
      <button type="button" disabled={!lab?.next_cursor} onClick={() => setBefore(lab?.next_cursor ?? 0)}>Older experiments</button></div>
    {detail && <article className="lab-result"><h3>{detail.plan.name}</h3><p>{detail.plan.mechanism}</p>
      <p>Reject when: {detail.plan.falsification}</p><p>{stamp(detail.plan.test_start)} to {stamp(detail.plan.test_end)} · {detail.plan.horizon_minutes}-minute labels</p>
      <p>Status: {detail.status}. {detail.reason ?? detail.result?.reason ?? detail.progress}</p>
      {detail.manifest && <p>{detail.manifest.rows} retained input events. Older rows omitted: {detail.manifest.older_rows_omitted ? "yes" : "no"}.</p>}
      {detail.result && <><h4>Decision: {detail.result.decision}</h4><p>{detail.result.next_action}</p>
        <p>Evidence: {detail.result.evidence_kind === "synthetic_qa" ? "Synthetic QA; never independent validation" : "Observed public quote labels; prospective qualification is separate"}.</p>
        <p>Training examples: {detail.result.train_samples ?? "insufficient"}; test examples: {detail.result.test_samples ?? "insufficient"}. Overlapping labels are correlated.</p>
        {detail.result.metrics && <dl>{Object.entries(detail.result.metrics).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value == null ? "Unavailable" : String(value)}</dd></div>)}</dl>}
        {detail.result.limitations?.map(note => <p key={note}>{note}</p>)}</>}
      <details><summary>Frozen fingerprints and attempt history</summary><p>Plan: {detail.plan_sha256}</p>
        <p>Evaluator: {detail.code_sha256}</p><p>Inputs: {detail.snapshot_sha256 ?? "Unavailable"}</p>
        {detail.events.map((event, i) => <p key={i}>{stamp(event.at)} · {event.kind.replaceAll("_", " ")} · {event.body}</p>)}</details>
      <a href={`/api/lab/experiments/${encodeURIComponent(detail.request_id)}`} download={`experiment-${detail.request_id}.json`}>Export retained receipt</a>
      <button type="button" disabled={busy || !["acquiring", "queued", "running"].includes(detail.status)}
        onClick={() => void post(`/api/lab/experiments/${encodeURIComponent(detail.request_id)}/cancel`).catch(e => setError(String(e)))}>Cancel remaining work</button>
    </article>}
  </section>;
}
