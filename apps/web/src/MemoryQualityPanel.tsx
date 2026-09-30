import { useEffect, useRef, useState } from "react";
import type { EvidenceReference } from "./EvidenceReference";

type AccountOutcome = {sample:{cash:string;equity:string;fees:string;liquidation_fee:string};net_account_usd:string|null;trading_net_usd:string|null;common_operating_usd:string|null;incremental_operating_usd:string|null;positions:Record<string,unknown>;closed_trades:number};
const money=(v:string|number|null|undefined)=>v==null?"Unavailable":`$${Number(v).toFixed(4)}`;

type Run = {request_id:string; status:string; reason?:string; manifest?:{execution_status?:string}; result?:{
  status:string; reason:string; train_samples:number; calibration_samples:number; test_samples:number;
  evidence_kind?:string;
  eligible_for_exploratory_paper?:boolean;
  account_comparison?:{status:string;reason?:string;period?:{records:number;declared_start:number;declared_end:number};accounts?:Record<string,AccountOutcome>;passive_benchmark?:{net_account_usd:string|null;state:{cash:string;equity:string;fees:string};kind:string};cash_control?:{net_account_usd:string|null}};
  target_coverage:{opportunities:number;available:number;unknown:number};
  candidate_group:{arm:string;name:string;status:string;reason?:string;artifact?:{sha256:string};metrics?:Record<string,unknown>;
    predictions?:{episode:string;net_bps:number;prediction:{status:string;action:string;expected_net_bps?:number;downside_bps?:number;distinct_groups?:number;profit_probability?:number|null;neighbors?:{episode:string;evidence_reference?:EvidenceReference|null;distance:number}[];illustrations?:{unfavorable:string[];favorable:string[]}}}[]}[];
  contributions:{from:string;to:string;conclusion:string;paired_account_effect:number|string|null;marginal_cost_usd:number|string|null;changed_decisions?:number|string[]}[];
  resources:{elapsed_seconds:number;cpu_seconds:number;paid_usd:string;marginal_operating_usd:number|null};
};};

export function MemoryQualityPanel({requestId,readonly=false,onOpenEvidence}:{requestId?:string;readonly?:boolean;onOpenEvidence?:(reference:EvidenceReference)=>void}={}) {
  const [start,setStart]=useState(""); const [end,setEnd]=useState("");
  const [run,setRun]=useState<Run|null>(null); const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [cash,setCash]=useState("100");const [common,setCommon]=useState("");const [numeric,setNumeric]=useState("");const [context,setContext]=useState("");const [cpuRate,setCpuRate]=useState("");
  const [forwardDaily,setForwardDaily]=useState("");const [admission,setAdmission]=useState("");
  const [request,setRequest]=useState(localStorage.getItem("qtrades-memory-request") ?? "");
  const [retry,setRetry]=useState<string|null>(localStorage.getItem("qtrades-memory-pending"));
  const selected=useRef("");
  useEffect(()=>{if(requestId) void inspect(requestId);return ()=>{selected.current="";};},[requestId]);
  async function inspect(id=request) {
    selected.current=id;
    setError("");setBusy(true);
    try {const response=await fetch(`/api/lab/experiments/${id}`,{cache:"no-store",signal:AbortSignal.timeout(10000)});
      if(!response.ok) throw new Error("Saved memory comparison is unavailable; earlier evidence stays retained.");
      const value=await response.json() as Run;if(selected.current===id)setRun(value);
    } catch(e) {setError(e instanceof Error?e.message:"Comparison unavailable");}
    finally{setBusy(false);}
  }
  async function launch() {
    setBusy(true);setError("");
    try {
    const body=retry ?? JSON.stringify({request_id:crypto.randomUUID(),name:"Historical entry-quality comparison",experiment_mode:"memory_entry",horizon_minutes:45,
        account_comparison:true,starting_cash:cash,common_daily_usd:common||null,numerical_daily_usd:numeric||null,contextual_daily_usd:context||null,cpu_hour_usd:cpuRate||null,
        mechanism:"Comparable as-seen prefixes may predict subsequent filled-trade quality after embedded costs.",
        falsification:"Reject or retain inconclusive evidence without sufficient executable labels and matched whole-account improvement.",
        test_start:new Date(start).getTime()/1000,test_end:new Date(end).getTime()/1000,as_of:Date.now()/1000});
    const id=(JSON.parse(body) as {request_id:string}).request_id;
    setRequest(id); localStorage.setItem("qtrades-memory-request",id);
    setRetry(body); localStorage.setItem("qtrades-memory-pending",body);
    const response=await fetch("/api/lab/experiments",{method:"POST",headers:{"Content-Type":"application/json","X-Local-Operator":"1"},
      body,signal:AbortSignal.timeout(20000)});
      if(!response.ok) {const body=await response.json() as {detail?:string};throw new Error(body.detail ?? "Plan could not be frozen");}
      setRetry(null);localStorage.removeItem("qtrades-memory-pending");await inspect(id);
    }catch(e){setError(e instanceof Error?e.message:"Comparison unavailable");}
    finally{setBusy(false);}
  }
  async function admit(arm:string){if(!run)return;setBusy(true);setError("");try{
    const r=await fetch(`/api/lab/experiments/${run.request_id}/forward`,{method:"POST",headers:{"Content-Type":"application/json","X-Local-Operator":"1"},body:JSON.stringify({family:"memory_entry",arm,starting_cash:cash,operating_daily_usd:forwardDaily||null}),signal:AbortSignal.timeout(20000)});
    if(!r.ok)throw new Error((await r.json() as {detail?:string}).detail??"Paper admission unconfirmed; retry the same funding assumptions.");
    setAdmission(`${arm} admitted with a matched control. Select the pair below to freeze its 28-day exploratory review.`);window.dispatchEvent(new Event("qtrades-research-admitted"));
  }catch(e){setError(e instanceof Error?e.message:"Paper admission unavailable");}finally{setBusy(false);}}
  return <section className="workspace-card" aria-label="Memory trade quality">
    <div className="card-heading"><div><p className="eyebrow">LOCAL RESEARCH · SHADOW</p><h2>Is historical memory useful?</h2></div></div>
    <p>Compare the existing strategy (A), numerical history (B), and local context (C).
      Executable outcomes use linked paper fills and proceeds. Price direction, resemblance and recognition confidence stay separate.</p>
    <p className="fine-print">Frozen 45-minute horizon · seven-day chronological calibration · training-only scaling · protected test and overlap purge.
      Missing or unfamiliar memory supplies no additional signal. Existing risk controls and position management apply.</p>
    {!readonly && <><div className="lab-form-row"><label>Untouched test start<input disabled={!!retry} type="datetime-local" value={start} onChange={e=>setStart(e.target.value)} onInput={e=>setStart(e.currentTarget.value)}/></label>
      <label>Untouched test end<input disabled={!!retry} type="datetime-local" value={end} onChange={e=>setEnd(e.target.value)} onInput={e=>setEnd(e.currentTarget.value)}/></label></div>
    <div className="lab-form-row"><label>Starting paper balance<select value={cash} disabled={!!retry} onChange={e=>setCash(e.target.value)}><option value="100">$100</option><option value="50">$50</option></select></label>
      <label>Common daily cost ($)<input type="number" min="0" step="any" value={common} disabled={!!retry} onChange={e=>setCommon(e.target.value)}/></label>
      <label>Numerical memory daily addition ($)<input type="number" min="0" step="any" value={numeric} disabled={!!retry} onChange={e=>setNumeric(e.target.value)}/></label>
      <label>Context memory daily addition ($)<input type="number" min="0" step="any" value={context} disabled={!!retry} onChange={e=>setContext(e.target.value)}/></label>
      <label>Compute cost per CPU hour ($)<input type="number" min="0" step="any" value={cpuRate} disabled={!!retry} onChange={e=>setCpuRate(e.target.value)}/></label></div>
    <p className="fine-print">Daily allocations include collection, storage and routine host costs. Rates are declared assumptions; inference time is measured. Leave an unknown cost blank; enter zero only for an explicit zero-cost scenario. Complete priced evidence is required for exploratory admission.</p>
    <button className="button" disabled={busy||!retry&&(!start||!end)} onClick={()=>void launch()}>{retry?"Retry frozen memory request":"Freeze memory comparison"}</button>
    {retry && <button className="button secondary" onClick={()=>{setRetry(null);localStorage.removeItem("qtrades-memory-pending");}}>Edit a new comparison</button>}
    <button className="button secondary" disabled={busy||!request} onClick={()=>void inspect()}>Reopen memory comparison</button></>}
    {error && <p role="alert" className="error-banner">{error}</p>}
    {run && <article aria-label="Saved memory quality result"><h3>Saved comparison · {run.status.replaceAll("_"," ")}</h3>
      <p>Reference {run.request_id.slice(0,8)} · {run.reason ?? run.result?.reason ?? "Frozen inputs are waiting for the bounded worker."}</p>
      {run.manifest?.execution_status && <p>{run.manifest.execution_status}</p>}
      {run.result && <p>{run.result.evidence_kind==="synthetic_qa"?"Synthetic test data":run.result.evidence_kind==="observed_public_quotes"?"Observed paper evidence":"Data mode unknown"} · source and plan retained · recognition confidence unavailable</p>}
      {run.result && <><dl className="summary-values"><div><dt>Available executable labels</dt><dd>{run.result.target_coverage.available} / {run.result.target_coverage.opportunities}</dd></div>
        <div><dt>Unknown or pending</dt><dd>{run.result.target_coverage.unknown}</dd></div><div><dt>Train / calibrate / test</dt><dd>{run.result.train_samples} / {run.result.calibration_samples} / {run.result.test_samples}</dd></div></dl>
        {run.result.candidate_group.map(c=><div key={c.arm}><h4>{c.arm} · {c.name}</h4><p>{c.status.replaceAll("_"," ")} · {c.reason ?? "Retain this comparison before any subsequent paper review."}</p>
          {c.artifact && <p>Frozen artifact: {c.artifact.sha256.slice(0,16)}</p>}
          {c.metrics && <dl className="summary-values">{Object.entries(c.metrics).map(([k,v])=><div key={k}><dt>{k.replaceAll("_"," ")}</dt><dd>{v==null?"Unavailable":typeof v==="number"?v.toFixed(3):String(v)}</dd></div>)}</dl>}
          {c.predictions?.slice(0,8).map(q=><details key={q.episode}><summary>{q.episode.slice(0,16)} · {q.prediction.status.replaceAll("_"," ")} · {q.prediction.action.replaceAll("_"," ")}</summary>
            <p>Groups: {q.prediction.distinct_groups ?? "Unavailable"} · expected net: {q.prediction.expected_net_bps?.toFixed(2) ?? "Unavailable"} bps · lowest neighbor: {q.prediction.downside_bps?.toFixed(2) ?? "Unavailable"} bps.</p>
            <p>Calibrated positive-outcome probability: {q.prediction.profit_probability==null?"Unavailable":`${(q.prediction.profit_probability*100).toFixed(1)}%`} · later recorded net trade outcome: {q.net_bps.toFixed(2)} bps.</p>
            <p className="fine-print">Chronological test result; later outcome did not choose the neighborhood. Trade forecasts are distinct from whole-account value.</p>
            {q.prediction.illustrations && <p>Illustrations: {q.prediction.illustrations.favorable.length} favorable, {q.prediction.illustrations.unfavorable.length} unfavorable. {q.prediction.illustrations.unfavorable.length===0?"No close failure analogue; safety is not established.":"Both endings remain represented in the full selected distribution."}</p>}
            {q.prediction.neighbors?.map(n=><p key={n.episode}>{n.episode.slice(0,16)} · distance {n.distance.toFixed(3)} {onOpenEvidence&&n.evidence_reference&&<button onClick={()=>onOpenEvidence(n.evidence_reference!)}>Inspect underlying prefix</button>}{!n.evidence_reference&&" · Exact archive reference unavailable in this saved receipt"}</p>)}
          </details>)}
          {(c.predictions?.length??0)>8&&<p>Showing the first eight chronological predictions. Export the saved receipt for all retained predictions.</p>}</div>)}
        {run.result.account_comparison?.accounts?<><h3>Complete account interval</h3><p>{run.result.account_comparison.period?.records} reconciled observations · {run.result.account_comparison.status.replaceAll("_"," ")}. Each arm starts with the same balance and keeps its cash and holdings throughout the interval.</p>
          <div className="table-scroll"><table><thead><tr><th>Arm</th><th>Cash</th><th>Final equity</th><th>Open positions</th><th>Trading net</th><th>Common cost</th><th>Memory cost</th><th>Account net</th></tr></thead><tbody>{Object.entries(run.result.account_comparison.accounts).map(([arm,a])=><tr key={arm}><td>{arm}</td><td>{money(a.sample.cash)}</td><td>{money(a.sample.equity)}</td><td>{Object.keys(a.positions).length}</td><td>{money(a.trading_net_usd)}</td><td>{money(a.common_operating_usd)}</td><td>{money(a.incremental_operating_usd)}</td><td>{money(a.net_account_usd)}</td></tr>)}</tbody></table></div>
          <p>Continuous passive benchmark: {money(run.result.account_comparison.passive_benchmark?.net_account_usd)} after declared common cost. Cash control: {money(run.result.account_comparison.cash_control?.net_account_usd)}. The passive holding starts once and is held through this interval; the existing four-hour reset exposure control is separate.</p>
          {run.result.contributions.map(c=><p key={c.to}>{c.from} → {c.to}: paired account effect {money(c.paired_account_effect)} · marginal operating cost {money(c.marginal_cost_usd)} · {c.conclusion.replaceAll("_"," ")}{typeof c.changed_decisions==="number"?` · ${c.changed_decisions} different entry decisions or times`:""}.</p>)}
          <p className="fine-print">Equity includes executable marks for open holdings. Fees and liquidation costs are embedded once. This is a historical cost scenario; an observed host bill, independent validation and a trading advantage remain unverified.</p>
        </>:<p>Whole-account effect: {run.result.account_comparison?.reason??"Unavailable in this saved receipt."}</p>}
        {!readonly&&run.result.eligible_for_exploratory_paper&&<div><h3>Start a separate paper comparison</h3><label>Daily operating allocation for the paper pair ($)<input type="number" min="0" step="any" value={forwardDaily} onChange={e=>setForwardDaily(e.target.value)}/></label><p>Each action funds a fresh ${cash} candidate and a separate ${cash} matched control. Original accounts and their history stay intact. An unfavorable historical result is permitted for exploration; no qualification or promotion is granted.</p>{run.result.candidate_group.filter(c=>c.artifact).map(c=><button key={c.arm} className="button secondary" disabled={busy} onClick={()=>void admit(c.arm)}>Fund exploratory {c.arm} paper pair</button>)}</div>}
        {admission&&<p role="status">{admission}</p>}
        <p className="fine-print">Recorded taken-trade labels retain selection bias; absent unexecuted outcomes remain unknown. This comparison does not promote or fund an account.</p>
        <p>Measured fitting: {run.result.resources.elapsed_seconds.toFixed(3)} seconds · paid provider cost ${run.result.resources.paid_usd}. Host rates are declared assumptions.</p>
      </>}
    </article>}
  </section>;
}
