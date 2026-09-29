import { useState } from "react";

export type ResearchCampaign = { request_id: string; status: string; iteration: number;
  phase: string; reason: string; active_request: string | null; allocated_wall_seconds: number;
  spec: { name: string; first_test_start: number; iterations: number; worker_wall_budget_seconds: number; expires_at: number } };

export function ResearchCampaignPanel({ campaigns, protectedThrough, blocked, select }: {
  campaigns: ResearchCampaign[]; protectedThrough: number; blocked: string | null;
  select: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [iterations, setIterations] = useState(2);
  const [retry, setRetry] = useState<Record<string, unknown> | null>(() => {
    try { return JSON.parse(localStorage.getItem("qtrades-research-campaign-retry") ?? "null"); }
    catch { return null; }
  });
  async function post(url: string, body?: unknown) {
    setBusy(true); setError("");
    try {
      const response = await fetch(url, {method:"POST",headers:{"X-Local-Operator":"1","Content-Type":"application/json"},
        body: body === undefined ? undefined : JSON.stringify(body),signal:AbortSignal.timeout(7000)});
      if (!response.ok) { const value = await response.json(); throw new Error(String(value.detail)); }
      return true;
    } catch(e) { setError(String(e)); return false; } finally { setBusy(false); }
  }
  async function start() {
    const now = Date.now()/1000;
    const body = retry ?? {request_id:crypto.randomUUID(),name:"Equal family coverage campaign",
      first_test_start:Math.max(now + 60,protectedThrough + 3660),window_minutes:240,iterations,
      expires_at:now + 48*3600,worker_wall_budget_seconds:iterations*50 <= 100 ? 100 : iterations*50 <= 200 ? 200 : 400,
      paid_budget_usd:"0"};
    localStorage.setItem("qtrades-research-campaign-retry",JSON.stringify(body)); setRetry(body);
    if (await post("/api/lab/campaigns",body)) {
      localStorage.removeItem("qtrades-research-campaign-retry"); setRetry(null);
    }
  }
  return <section className="lab-result" aria-label="Autonomous research campaigns"><h3>Research that continues across restarts</h3>
    <p>Observe four untouched hours, evaluate all three fixed families, retain or reject the result, then wait for the next purged window. No automatic account admission or promotion. Optional AI is not required.</p>
    <p>At most two active campaigns, eight iterations each, one fit child, two processors, 256 MiB child memory and 25 seconds per attempt. No GPU or paid calls. Pressure suspends research while financial management continues.</p>
    {blocked && <p role="status">{blocked}</p>}{error && <p role="alert">{error}</p>}
    <label>Finite research iterations<select value={iterations} disabled={busy || !!retry} onChange={e=>setIterations(Number(e.target.value))}>
      {[2,4,8].map(n=><option key={n} value={n}>{n} iterations · {n*50} seconds maximum fit allocation</option>)}</select></label>
    <button type="button" disabled={busy} onClick={()=>void start()}>{retry ? "Confirm frozen research campaign" : "Start bounded research campaign"}</button>
    {retry && <button type="button" onClick={()=>{localStorage.removeItem("qtrades-research-campaign-retry");setRetry(null);}}>Edit a new research campaign</button>}
    {campaigns.map(c=><article className="lab-result" key={c.request_id}><h4>{c.spec.name}</h4>
      <p>{c.status} · {c.phase} · {c.iteration}/{c.spec.iterations} outcomes retained. {c.reason}.</p>
      <p>Attempt allocation {c.allocated_wall_seconds}/{c.spec.worker_wall_budget_seconds} seconds; this is a conservative ceiling, not measured CPU time. Ends {new Date(c.spec.expires_at*1000).toLocaleString()}. Paid spending $0.</p>
      {c.active_request && <button type="button" onClick={()=>select(c.active_request!)}>Inspect current research result</button>}
      <a href={`/api/lab/campaigns/${c.request_id}`} download>Export campaign and learning history</a>
      <button type="button" disabled={busy || c.status!=="active"} onClick={()=>void post(`/api/lab/campaigns/${c.request_id}/cancel`)}>Cancel remaining iterations</button>
    </article>)}
  </section>;
}
