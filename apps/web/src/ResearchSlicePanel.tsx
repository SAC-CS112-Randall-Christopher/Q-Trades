import { useEffect, useRef, useState } from "react";

type Comparison = {episode:string;status:string;action:string;later_net_trade_bps:number|null;evidence:Record<string,unknown>};
type Run = {request_id:string;status:string;reason?:string;manifest?:{execution_status?:string};result?:{
  mode:string;status:string;reason:string;evidence_kind:string;opportunities:number;labeled:number;unknown_outcomes:number;
  changed_decisions:number;missed_positive_taken_trades:number;comparisons:Comparison[];
  optional_D?:{status:string;reason:string};resources:{elapsed_seconds:number;paid_usd:string};
}};
export function ResearchSlicePanel({requestId,readonly=false}:{requestId?:string;readonly?:boolean}) {
  const [mode,setMode]=useState("context_regime");const [start,setStart]=useState("");const [end,setEnd]=useState("");
  const [run,setRun]=useState<Run|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const [id,setId]=useState(localStorage.getItem("qtrades-slice-request")??"");
  const [pending,setPending]=useState(localStorage.getItem("qtrades-slice-pending"));const current=useRef("");
  useEffect(()=>{if(requestId)void inspect(requestId);return()=>{current.current="";};},[requestId]);
  async function inspect(target=id){current.current=target;setBusy(true);setError("");try{
    const r=await fetch(`/api/lab/experiments/${encodeURIComponent(target)}`,{cache:"no-store",signal:AbortSignal.timeout(10000)});
    if(!r.ok)throw new Error("Saved research is unavailable; retained evidence stays visible.");
    const value=await r.json() as Run;if(current.current===target)setRun(value);
  }catch(e){setError(e instanceof Error?e.message:"Research unavailable");}finally{setBusy(false);}}
  async function launch(){setBusy(true);setError("");try{
    const body=pending??JSON.stringify({request_id:crypto.randomUUID(),name:mode==="context_regime"?"Local condition comparison":"Independent entry-timing comparison",
      experiment_mode:mode,horizon_minutes:45,as_of:Date.now()/1000,test_start:new Date(start).getTime()/1000,test_end:new Date(end).getTime()/1000,
      mechanism:"Frozen observable conditions may improve entries under the existing strategy and unchanged financial controls.",
      falsification:"Retain unknown or negative evidence without supported executable costs and matched whole-account improvement."});
    const target=(JSON.parse(body) as {request_id:string}).request_id;setId(target);localStorage.setItem("qtrades-slice-request",target);
    setPending(body);localStorage.setItem("qtrades-slice-pending",body);
    const r=await fetch("/api/lab/experiments",{method:"POST",headers:{"Content-Type":"application/json","X-Local-Operator":"1"},body,signal:AbortSignal.timeout(20000)});
    if(!r.ok){const v=await r.json() as {detail?:string};throw new Error(v.detail??"Plan could not be frozen");}
    setPending(null);localStorage.removeItem("qtrades-slice-pending");await inspect(target);
  }catch(e){setError(e instanceof Error?e.message:"Research unavailable");}finally{setBusy(false);}}
  return <section className="workspace-card" aria-label="Independent research comparisons">
    <p className="eyebrow">LOCAL RESEARCH · SHADOW</p><h2>Conditions and entry timing</h2>
    <p>Test one contribution at a time. Local conditions describe the observed beginning; order-flow timing requires valid books and observed trade direction.</p>
    {!readonly&&<><label>Contribution<select disabled={!!pending} value={mode} onChange={e=>setMode(e.target.value)}>
      <option value="context_regime">Local market conditions</option><option value="order_flow">Order-flow entry timing</option></select></label>
      <div className="lab-form-row"><label>Untouched test start<input disabled={!!pending} type="datetime-local" value={start} onInput={e=>setStart(e.currentTarget.value)} onChange={e=>setStart(e.target.value)}/></label>
      <label>Untouched test end<input disabled={!!pending} type="datetime-local" value={end} onInput={e=>setEnd(e.currentTarget.value)} onChange={e=>setEnd(e.target.value)}/></label></div>
      <button className="button" disabled={busy||!pending&&(!start||!end)} onClick={()=>void launch()}>{pending?"Retry frozen contribution":"Freeze independent comparison"}</button>
      {pending&&<button className="button secondary" onClick={()=>{setPending(null);localStorage.removeItem("qtrades-slice-pending");}}>Edit a new contribution</button>}
      <button className="button secondary" disabled={busy||!id} onClick={()=>void inspect()}>Reopen contribution</button></>}
    {error&&<p role="alert" className="error-banner">{error}</p>}
    {run&&<article><h3>Saved contribution · {run.status}</h3><p>Reference {run.request_id.slice(0,12)} · {run.reason??run.result?.reason??"Waiting for the bounded worker"}</p>
      <p>{run.manifest?.execution_status}</p>{run.result&&<><p>{run.result.evidence_kind==="synthetic_qa"?"Synthetic test data":"Observed paper evidence"} · {run.result.mode.replaceAll("_"," ")}</p>
        <dl className="summary-values"><div><dt>Observed opportunities</dt><dd>{run.result.opportunities}</dd></div><div><dt>Executable labels</dt><dd>{run.result.labeled}</dd></div>
          <div><dt>Unknown outcomes</dt><dd>{run.result.unknown_outcomes}</dd></div><div><dt>Changed entries</dt><dd>{run.result.changed_decisions}</dd></div></dl>
        <p>Whole-account effect, turnover and marginal monetary value remain unavailable. Fees in net labels are counted once. No account is promoted or funded.</p>
        {run.result.optional_D&&<p>Optional Decisions: {run.result.optional_D.status} · {run.result.optional_D.reason}</p>}
        {run.result.comparisons.slice(0,12).map(q=><details key={q.episode}><summary>{q.episode.slice(0,20)} · {q.status.replaceAll("_"," ")} · {q.action.replaceAll("_"," ")}</summary>
          <p>Later net trade result: {q.later_net_trade_bps==null?"Unavailable":`${q.later_net_trade_bps.toFixed(2)} bps`}. Recognition confidence and profit probability are separate and unverified.</p>
          <pre className="evidence-raw">{JSON.stringify(q.evidence,null,2)}</pre></details>)}
        <p className="fine-print">First twelve chronological observations shown. All comparisons, frozen rules, delays and unknowns are in the saved receipt.</p>
        <p>Computation: {run.result.resources.elapsed_seconds.toFixed(3)} seconds · paid calls ${run.result.resources.paid_usd}.</p></>}
      <a className="button secondary" href={`/api/lab/experiments/${encodeURIComponent(run.request_id)}`} target="_blank" rel="noreferrer">Open full saved receipt</a></article>}
  </section>;
}
