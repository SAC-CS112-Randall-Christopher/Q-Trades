import { useEffect, useState } from "react";

type Plan = {spec:{request_id:string;name:string;starts_at:number;days:number;candidate?:string|null};ends_at:number;components:unknown[]};
type Candidate={account:string;label:string;control:string;component_request:string;purpose:string};
type Report = {status:string;reason:string;complete_windows:number;combined_components:number;configuration_drift:string[];decision:string};
export function ProspectivePanel() {
  const [plans,setPlans]=useState<Plan[]>([]);const [start,setStart]=useState("");
  const [candidates,setCandidates]=useState<Candidate[]>([]);const [candidate,setCandidate]=useState("");
  const [busy,setBusy]=useState(false);const [error,setError]=useState("");const [report,setReport]=useState<Report|null>(null);
  const [pending,setPending]=useState(localStorage.getItem("qtrades-prospective-pending"));
  async function load(){try{const r=await fetch("/api/lab/prospective",{cache:"no-store"});if(!r.ok)throw new Error("Saved reviews unavailable");const v=await r.json() as {plans:Plan[];candidates?:Candidate[]};setPlans(v.plans);setCandidates(v.candidates??[]);}catch(e){setError(e instanceof Error?e.message:"Reviews unavailable");}}
  useEffect(()=>{void load();const reload=()=>void load();window.addEventListener("qtrades-research-admitted",reload);return()=>window.removeEventListener("qtrades-research-admitted",reload);},[]);
  async function freeze(){setBusy(true);setError("");try{
    const selected=candidates.find(c=>c.account===candidate);
    if(candidate&&!selected)throw new Error("Selected paper pair is unavailable; refresh the choices.");
    const body=pending??JSON.stringify({request_id:crypto.randomUUID(),name:selected?"Exploratory memory account review":"Subsequent baseline review",starts_at:new Date(start).getTime()/1000,days:28,candidate:selected?.account??null,purpose:selected?.purpose??"baseline_review",component_requests:selected?[selected.component_request]:[]});
    JSON.parse(body);setPending(body);localStorage.setItem("qtrades-prospective-pending",body);
    const r=await fetch("/api/lab/prospective",{method:"POST",headers:{"Content-Type":"application/json","X-Local-Operator":"1"},body,signal:AbortSignal.timeout(10000)});
    if(!r.ok)throw new Error((await r.json() as {detail:string}).detail);setPending(null);localStorage.removeItem("qtrades-prospective-pending");await load();
  }catch(e){setError(e instanceof Error?e.message:"Review could not be frozen");}finally{setBusy(false);}}
  async function inspect(id:string){setBusy(true);setError("");try{
    const r=await fetch(`/api/lab/prospective/${encodeURIComponent(id)}/inspect`,{method:"POST",headers:{"X-Local-Operator":"1"},signal:AbortSignal.timeout(10000)});
    if(!r.ok)throw new Error((await r.json() as {detail:string}).detail);setReport(await r.json() as Report);
  }catch(e){setError(e instanceof Error?e.message:"Review unavailable");}finally{setBusy(false);}}
  return <section className="workspace-card" aria-label="Prospective system review"><p className="eyebrow">SUBSEQUENT EVIDENCE</p><h2>Freeze a system review</h2>
    <p>Select an admitted memory account and its matched control for a fixed 28-day exploratory review, or retain a baseline review. Choose a start at least 55 minutes ahead. Historical account evidence does not qualify or promote the candidate.</p>
    <label>Account comparison<select value={candidate} disabled={!!pending} onChange={e=>setCandidate(e.target.value)}><option value="">Current baseline accounts</option>{candidates.map(c=><option key={c.account} value={c.account}>{c.label} · matched control</option>)}</select></label>
    <button className="button secondary" disabled={busy} onClick={()=>void load()}>Refresh paper pairs</button>
    <label>Future comparison start<input type="datetime-local" value={start} disabled={!!pending} onInput={e=>setStart(e.currentTarget.value)} onChange={e=>setStart(e.target.value)}/></label>
    <button className="button" disabled={busy||!pending&&!start} onClick={()=>void freeze()}>{pending?"Retry frozen system review":"Freeze 28-day review"}</button>
    {pending&&<button className="button secondary" onClick={()=>{setPending(null);localStorage.removeItem("qtrades-prospective-pending");}}>Edit a new review</button>}
    {error&&<p role="alert" className="error-banner">{error}</p>}
    {plans.map(p=><article key={p.spec.request_id}><h3>{p.spec.name}</h3><p>{new Date(p.spec.starts_at*1000).toLocaleString()} → {new Date(p.ends_at*1000).toLocaleString()} · {p.spec.candidate?"Candidate and matched control":"Baseline review"} · {p.components.length} retained component receipts</p>
      <button className="button secondary" disabled={busy} onClick={()=>void inspect(p.spec.request_id)}>Inspect subsequent evidence</button></article>)}
    {report&&<article><h3>Retained inspection · {report.status}</h3><p>{report.reason}</p><dl className="summary-values"><div><dt>Complete windows</dt><dd>{report.complete_windows}</dd></div><div><dt>Configuration changes</dt><dd>{report.configuration_drift.length}</dd></div></dl><p>Decision: {report.decision.replaceAll("_"," ")}. Whole-account advantage remains unproven. Every inspection is retained.</p></article>}
    <p className="fine-print">Research only. Existing paper-role approval, account limits, costs and failed search history remain in force.</p>
  </section>;
}
