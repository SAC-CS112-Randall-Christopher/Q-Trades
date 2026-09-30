import { useEffect, useRef, useState } from "react";

type Comparison = {episode:string;status:string;action:string;later_net_trade_bps:number|null;evidence:Record<string,unknown>};
type Run = {request_id:string;status:string;reason?:string;manifest?:{execution_status?:string};result?:{
  mode:string;status:string;reason:string;evidence_kind:string;opportunities:number;labeled:number;unknown_outcomes:number;
  changed_decisions:number|null;missed_positive_taken_trades:number|null;comparisons:Comparison[];
  decision_change_metric?:{label:string;value:number|null;unit?:string;baseline?:string};
  metrics?:Record<string,unknown>;journal?:Record<string,number>;drift_alarms?:unknown[];
  optional_D?:{status:string;reason:string};resources:{elapsed_seconds:number;paid_usd:string};
}};
type LearningPage={records:{seq:number;at:number;kind:string;sha256:string;body:{prediction_at?:number;outcome_available_at?:number;residual_bps?:number|null;model_before?:string;model?:{sha256:string};prediction?:{status:string}}}[];next_cursor:number|null};
type LearningMetric={scored_independent_groups?:number;mean_absolute_net_error_bps?:number|null;brier?:number|null;updates?:number};
const contributionName=(mode:string)=>({context_regime:"Local market conditions",order_flow:"Order-flow entry timing",growing_memory:"Controlled learning",component_exit:"Independent exits",component_size:"Conservative sizing",observation_priority:"Market observation"}[mode]??mode.replaceAll("_"," "));
export function ResearchSlicePanel({requestId,readonly=false}:{requestId?:string;readonly?:boolean}) {
  const [mode,setMode]=useState("context_regime");const [start,setStart]=useState("");const [end,setEnd]=useState("");
  const [run,setRun]=useState<Run|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const [id,setId]=useState(localStorage.getItem("qtrades-slice-request")??"");
  const [pending,setPending]=useState(localStorage.getItem("qtrades-slice-pending"));const current=useRef("");
  const [learning,setLearning]=useState<LearningPage|null>(null);
  useEffect(()=>{if(requestId)void inspect(requestId);return()=>{current.current="";};},[requestId]);
  async function inspect(target=id){current.current=target;setBusy(true);setError("");try{
    const r=await fetch(`/api/lab/experiments/${encodeURIComponent(target)}`,{cache:"no-store",signal:AbortSignal.timeout(10000)});
    if(!r.ok)throw new Error("Saved research is unavailable; retained evidence stays visible.");
    const value=await r.json() as Run;if(current.current===target){setRun(value);setLearning(null);}
  }catch(e){setError(e instanceof Error?e.message:"Research unavailable");}finally{setBusy(false);}}
  async function launch(){setBusy(true);setError("");try{
    const body=pending??JSON.stringify({request_id:crypto.randomUUID(),name:contributionName(mode)+" comparison",
      experiment_mode:mode,horizon_minutes:45,as_of:Date.now()/1000,test_start:new Date(start).getTime()/1000,test_end:new Date(end).getTime()/1000,
      mechanism:"Frozen observable conditions may improve entries under the existing strategy and unchanged financial controls.",
      falsification:"Retain unknown or negative evidence without supported executable costs and matched whole-account improvement."});
    const target=(JSON.parse(body) as {request_id:string}).request_id;setId(target);localStorage.setItem("qtrades-slice-request",target);
    setPending(body);localStorage.setItem("qtrades-slice-pending",body);
    const r=await fetch("/api/lab/experiments",{method:"POST",headers:{"Content-Type":"application/json","X-Local-Operator":"1"},body,signal:AbortSignal.timeout(20000)});
    if(!r.ok){const v=await r.json() as {detail?:string};throw new Error(v.detail??"Plan could not be frozen");}
    setPending(null);localStorage.removeItem("qtrades-slice-pending");await inspect(target);
  }catch(e){setError(e instanceof Error?e.message:"Research unavailable");}finally{setBusy(false);}}
  async function inspectLearning(before=0){if(!run)return;const request=run.request_id;setBusy(true);setError("");try{
    const r=await fetch(`/api/lab/experiments/${encodeURIComponent(request)}/learning?before=${before}`,{cache:"no-store",signal:AbortSignal.timeout(10000)});
    if(!r.ok)throw new Error("Learning snapshots are unavailable; prior evidence stays retained.");
    const value=await r.json() as LearningPage;if(current.current===request)setLearning(value);
  }catch(e){setError(e instanceof Error?e.message:"Learning snapshots unavailable");}finally{setBusy(false);}}
  return <section className="workspace-card" aria-label="Independent research comparisons">
    <p className="eyebrow">LOCAL RESEARCH · SHADOW</p><h2>Independent research and learning</h2>
    <p>Test one contribution at a time. Local conditions describe the observed beginning; order-flow timing requires valid books and observed trade direction. Learning persists the forecast before separately mature outcomes can score and update research memory.</p>
    {!readonly&&<><label>Contribution<select disabled={!!pending} value={mode} onChange={e=>setMode(e.target.value)}>
      <option value="context_regime">Local market conditions</option><option value="order_flow">Order-flow entry timing</option>
      <option value="growing_memory">Frozen, batch and growing memory</option>
      <option value="component_exit">Independent exit comparison</option><option value="component_size">Conservative size comparison</option>
      <option value="observation_priority">Market observation priority</option></select></label>
      <div className="lab-form-row"><label>Untouched test start<input disabled={!!pending} type="datetime-local" value={start} onInput={e=>setStart(e.currentTarget.value)} onChange={e=>setStart(e.target.value)}/></label>
      <label>Untouched test end<input disabled={!!pending} type="datetime-local" value={end} onInput={e=>setEnd(e.currentTarget.value)} onChange={e=>setEnd(e.target.value)}/></label></div>
      <button className="button" disabled={busy||!pending&&(!start||!end)} onClick={()=>void launch()}>{pending?"Retry frozen contribution":"Freeze independent comparison"}</button>
      {pending&&<button className="button secondary" onClick={()=>{setPending(null);localStorage.removeItem("qtrades-slice-pending");}}>Edit a new contribution</button>}
      <button className="button secondary" disabled={busy||!id} onClick={()=>void inspect()}>Reopen contribution</button></>}
    {error&&<p role="alert" className="error-banner">{error}</p>}
    {run&&<article><h3>Saved contribution · {run.status}</h3><p>Reference {run.request_id.slice(0,12)} · {run.reason??run.result?.reason??"Waiting for the bounded worker"}</p>
      <p>{run.manifest?.execution_status}</p>{run.result&&<><p>{run.result.evidence_kind==="synthetic_qa"?"Synthetic test data":"Observed paper evidence"} · {contributionName(run.result.mode)} · {run.result.status.replaceAll("_"," ")}</p>
        <dl className="summary-values"><div><dt>Observed opportunities</dt><dd>{run.result.opportunities}</dd></div><div><dt>Executable labels</dt><dd>{run.result.labeled}</dd></div>
          <div><dt>Unknown outcomes</dt><dd>{run.result.unknown_outcomes}</dd></div><div><dt>{run.result.decision_change_metric?.label??"Changed shadow filters"}</dt><dd>{(run.result.decision_change_metric?.value??run.result.changed_decisions)==null?"Not applicable":run.result.decision_change_metric?.value??run.result.changed_decisions}</dd></div></dl>
        <p>Whole-account effect, turnover and marginal monetary value remain unavailable. Fees in net labels are counted once. No account is promoted or funded.</p>
        {run.result.optional_D&&<p>Optional Decisions: {run.result.optional_D.status} · {run.result.optional_D.reason}</p>}
        {run.result.metrics&&<><h4>Retained learning diagnostics</h4><p>Updates change research memory only. More updates do not establish more independent evidence or an improved account.</p>
          <table className="market-table" aria-label="Learning comparisons"><thead><tr><th>Procedure</th><th>Scored groups</th><th>Net forecast error</th><th>Probability error</th><th>Updates</th></tr></thead><tbody>{Object.entries(run.result.metrics).map(([name,value])=>{const m=value as LearningMetric;return <tr key={name}><td>{name}</td><td>{m.scored_independent_groups??0}</td><td>{m.mean_absolute_net_error_bps==null?"Unavailable":`${m.mean_absolute_net_error_bps.toFixed(2)} bps`}</td><td>{m.brier==null?"Unavailable":m.brier.toFixed(4)}</td><td>{m.updates??0}</td></tr>;})}</tbody></table>
          <p>Drift diagnoses: {run.result.drift_alarms?.length??0}. Original forecasts and model references remain in the saved stages.</p>
          <button className="button secondary" disabled={busy} onClick={()=>void inspectLearning()}>Inspect learning snapshots</button>
          {learning&&<><table className="market-table" aria-label="Saved learning stages"><thead><tr><th>Stage</th><th>Recorded time</th><th>Original forecast / model</th><th>Residual</th></tr></thead>
            <tbody>{learning.records.map(s=><tr key={s.seq}><td>#{s.seq} · {s.kind}</td><td>{new Date(s.at*1000).toLocaleString()}</td>
              <td>{s.body.prediction?.status??s.body.model?.sha256.slice(0,16)??s.body.model_before?.slice(0,16)??"Original score"}<small>{s.sha256.slice(0,16)}</small></td>
              <td>{s.body.residual_bps==null?"Unavailable":`${s.body.residual_bps.toFixed(2)} bps`}</td></tr>)}</tbody></table>
            <button className="button secondary" disabled={busy||!learning.next_cursor} onClick={()=>void inspectLearning(learning.next_cursor!)}>Older learning snapshots</button></>}
          </>}
        {run.result.comparisons.slice(0,12).map(q=><details key={q.episode}><summary>{q.episode.slice(0,20)} · {q.status.replaceAll("_"," ")} · {q.action.replaceAll("_"," ")}</summary>
          <p>Later net trade result: {q.later_net_trade_bps==null?"Unavailable":`${q.later_net_trade_bps.toFixed(2)} bps`}. Recognition confidence and profit probability are separate and unverified.</p>
          <pre className="evidence-raw">{JSON.stringify(q.evidence,null,2)}</pre></details>)}
        <p className="fine-print">First twelve chronological observations shown. All comparisons, frozen rules, delays and unknowns are in the saved receipt.</p>
        <p>Computation: {run.result.resources.elapsed_seconds.toFixed(3)} seconds · paid calls ${run.result.resources.paid_usd}.</p></>}
      <a className="button secondary" href={`/api/lab/experiments/${encodeURIComponent(run.request_id)}`} target="_blank" rel="noreferrer">Open full saved receipt</a></article>}
  </section>;
}
