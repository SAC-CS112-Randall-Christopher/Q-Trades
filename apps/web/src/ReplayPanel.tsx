import { useEffect, useState } from "react";

type Row = {request:string; at:number; status:string; error?:string};
type Receipt = {
  request:string; status:string; error?:string;
  plan:{request:{record_id:number|string; records:number}};
  resources?:{wall_seconds:number; peak_rss_bytes:number};
  result?:{
    status:string; data_mode?:string; residual?:string;
    baseline:{record_id:number|string; state_matches:boolean; events_match:boolean; balanced:boolean}[];
    coverage?:{requested:number; supported:number; start:number; end:number; boundary?:{reason:string}};
    remaining_opportunity?:{status:string; reason:string; first_supported_book_at?:number};
    scenarios:{scenario:string; evidence_type:string; balanced:boolean; condition_stressed_ticks:number;
      accounts:{account:string; slice_net_pnl:string|null; additional_fees_usd:string;
        starting:{equity:string; funding:string; fresh:boolean; flat:boolean};
        ending:{equity:string; funding:string; fresh:boolean};
        embedded_drag_usd:string; pending_orders:number; open_positions:number}[];
      fills:{account:string; symbol:string; side:string; filled_quantity:string; fee:string;
        partial:boolean; unfilled_cancelled:string}[];
      observed_paths:{account:string; symbol:string; favorable_bps:string; adverse_bps:string;
        observed_giveback_bps:string; observed_holding_seconds:number; complete_from_open:boolean}[];
    }[];
    attribution?:{measured:string; modeled:string; unavailable:string; residual:string};
    resources?:{elapsed_seconds?:number; supported_ticks_per_second?:number};
  };
};
const amount=(x:string|null)=>x==null?"Unavailable":`${Number(x).toFixed(4)} USD`;
const time=(at:number)=>new Date(at*1000).toLocaleString("en-US",{timeZone:"America/Denver"});
const names:Record<string,string>={recorded:"Recorded assumptions", "delay-3s-v1":"Three-second delay",
  "condition-cost-v1":"Thin / wide-book cost stress"};
const describe=(value:string)=>value.replaceAll("_"," ");

export function ReplayPanel({recordId}:{recordId?:number|string}) {
  const [rows,setRows]=useState<Row[]>([]);
  const [receipt,setReceipt]=useState<Receipt|null>(null);
  const [records,setRecords]=useState(16);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const [count,setCount]=useState(0);
  const [next,setNext]=useState<number|null>(null);
  const [more,setMore]=useState(false);
  async function history(before=0) {
    try {
      const r=await fetch(`/api/replays?before=${before}`,{cache:"no-store",signal:AbortSignal.timeout(7000)});
      if (!r.ok) throw new Error();
      const data=await r.json(); setRows(data.runs); setCount(data.total);
      setNext(data.next_before); setMore(data.has_more);
    } catch {setError("Replay history is unavailable. Earlier receipts stay preserved.");}
  }
  useEffect(()=>{void history();},[]);
  async function open(request:string) {
    setBusy(true); setError(null);
    try {
      const r=await fetch(`/api/replays/${request}`,{cache:"no-store",signal:AbortSignal.timeout(7000)});
      if (!r.ok) throw new Error();
      setReceipt(await r.json() as Receipt); await history();
    } catch {setError("This replay receipt could not open. Refresh after reconnecting.");}
    finally {setBusy(false);}
  }
  async function launch() {
    if (!recordId) return;
    setBusy(true); setError(null);
    try {
      const r=await fetch("/api/replays",{method:"POST",headers:{"Content-Type":"application/json",
        "X-Local-Operator":"1"},body:JSON.stringify({request_id:crypto.randomUUID(),record_id:recordId,
        records}),signal:AbortSignal.timeout(12000)});
      if (!r.ok) throw new Error();
      const job=await r.json(); await open(job.request_id);
    } catch {setError("Replay could not be reserved. Check retained inputs and available capacity.");}
    finally {setBusy(false);}
  }
  const r=receipt?.result;
  return <section className="workspace-card" aria-label="Isolated execution replay">
    <div className="card-heading"><div><p className="eyebrow">EXECUTION EVIDENCE</p>
      <h2>Replay the recorded decision</h2></div>
      <button className="button secondary small" disabled={busy} onClick={()=>void history()}>Refresh replay history</button>
    </div>
    <p>Compare the same recorded inputs through the paper engine, then test a longer delay and
      conservative costs in thin or wide books. Gaps stop the comparison. Missing books stay unavailable.</p>
    <p className="fine-print">One local worker · retained source and input references · no financial
      authority. Stresses are modeled counterfactuals; repeated runs add no independent market evidence.</p>
    <label>Maximum retained observations <select aria-label="Replay slice size" value={records}
      onChange={e=>setRecords(Number(e.target.value))}>
      <option value={1}>One decision</option><option value={16}>16 decisions</option>
      <option value={32}>32 decisions</option></select></label>
    <button className="button secondary small" disabled={busy||!recordId} onClick={()=>void launch()}>
      {busy?"Working…":"Start isolated replay"}</button>
    <p>{recordId?`Selected decision #${recordId}.`:
      "Inspect a decision bundle above to select a starting point."} {count} retained replay attempts.</p>
    {error&&<p className="error-banner" role="alert">{error}</p>}
    <div className="table-scroll"><table className="market-table" aria-label="Retained replay attempts">
      <thead><tr><th>Requested</th><th>Status</th><th/></tr></thead>
      <tbody>{rows.map(row=><tr key={row.request}><td>{time(row.at)}</td><td>{row.status}
        {row.error&&<small>{row.error}</small>}</td><td><button className="button secondary small"
          disabled={busy} onClick={()=>void open(row.request)}>Inspect replay {row.request.slice(0,8)}</button></td></tr>)}</tbody>
    </table></div>
    <div className="heading-actions"><button className="button secondary small" disabled={busy}
      onClick={()=>void history()}>Latest replays</button><button className="button secondary small"
      disabled={busy||!more} onClick={()=>void history(next??0)}>Older replays</button></div>
    {receipt&&<section aria-label="Selected execution replay">
      <h3>Replay of decision #{receipt.plan.request.record_id} · {receipt.status}</h3>
      <p>{receipt.error}</p>
      {receipt.status==="queued"||receipt.status==="running"?<p>Waiting for the bounded research worker.
        <button className="button secondary small" disabled={busy} onClick={()=>void open(receipt.request)}>Refresh selected replay</button></p>:null}
      {r&&<><p>{r.data_mode==="synthetic"?"Synthetic test data":r.data_mode==="paper_observations"?
        "Recorded paper observations":"Data mode unavailable"} · retained inputs only.</p>
        <p>Baseline: {r.status==="reconciliation_failed"?"Needs inspection":describe(r.status)}. {r.baseline.filter(x=>x.state_matches&&x.events_match&&x.balanced).length}
        {" "}recorded decisions match their financial state, events and balanced journal lines.</p>
        {r.coverage&&<p>{r.coverage.supported} supported observations, from {time(r.coverage.start)} to
          {" "}{time(r.coverage.end)}. {r.coverage.boundary?.reason}</p>}
        <p>{r.residual??r.attribution?.residual}</p>
        <p>Remaining opportunity: {r.remaining_opportunity?describe(r.remaining_opportunity.status):"Unavailable"}.
          {" "}{r.remaining_opportunity?.reason}</p>
        <div className="table-scroll"><table className="market-table" aria-label="Matched replay account results">
          <thead><tr><th>Assumptions</th><th>Account</th><th>Liquidation value: start → end</th><th>Net slice P&amp;L</th><th>Fees included</th>
            <th>Execution drag included</th><th>Open / pending</th></tr></thead>
          <tbody>{r.scenarios.flatMap(s=>s.accounts.map(a=><tr key={`${s.scenario}:${a.account}`}>
            <td>{names[s.scenario]??s.scenario}<small>{s.evidence_type}</small></td><td>{a.account}
              <small>{a.starting.flat?"Started flat":"Started with exposure"} · funding {amount(a.ending.funding)}</small></td>
            <td>{amount(a.starting.fresh?a.starting.equity:null)} → {amount(a.ending.fresh?a.ending.equity:null)}</td>
            <td>{amount(a.slice_net_pnl)}</td><td>{amount(a.additional_fees_usd)}</td>
            <td>{amount(a.embedded_drag_usd)}</td><td>{a.open_positions} / {a.pending_orders}</td></tr>))}</tbody>
        </table></div>
        <p>Liquidation values already include estimated closing costs; filling an exit at the
          same price can leave the net slice unchanged while fees become realized. Net values already
          include execution costs. They are finite-slice account values, not full-horizon strategy returns.</p>
        {r.scenarios.map(s=><details key={s.scenario}><summary>{names[s.scenario]} · fills and observed paths</summary>
          <p>{s.balanced?"All replay journal lines balance.":"Reconciliation requires inspection."}</p>
          {s.scenario==="condition-cost-v1"&&<p>{s.condition_stressed_ticks} retained observations
            crossed the declared cost-stress threshold.</p>}
          {s.fills.map((f,i)=><p key={i}>{f.account} · {f.symbol} · {f.side} {f.filled_quantity} ·
            fee {amount(f.fee)} · {f.partial?`Partial; ${f.unfilled_cancelled} unfilled and cancelled`:"Filled"}</p>)}
          {!s.fills.length&&<p>No fill in this supported slice. A positive later market move does not imply execution.</p>}
          {s.observed_paths.map((p,i)=><p key={i}>{p.account} · {p.symbol} · observed holding
            {" "}{p.observed_holding_seconds}s · favorable {Number(p.favorable_bps).toFixed(3)} bps · adverse
            {" "}{Number(p.adverse_bps).toFixed(3)} bps · observed giveback {Number(p.observed_giveback_bps).toFixed(3)} bps.
            {p.complete_from_open?" Includes the recorded open.":" Earlier path unavailable."} Between-book extrema remain unknown.</p>)}
        </details>)}
        <dl className="summary-values"><div><dt>Replay compute</dt><dd>{r.resources?.elapsed_seconds==null?"Unavailable":`${r.resources.elapsed_seconds.toFixed(3)} s`}</dd></div>
          <div><dt>Supported observations / second</dt><dd>{r.resources?.supported_ticks_per_second?.toFixed(2)??"Unavailable"}</dd></div>
          <div><dt>Worker peak memory</dt><dd>{receipt.resources?`${(receipt.resources.peak_rss_bytes/1024/1024).toFixed(2)} MiB`:"Unavailable"}</dd></div></dl>
        {r.attribution?<p>Measured: {r.attribution.measured} Modeled: {r.attribution.modeled}
          {" "}Unavailable: {r.attribution.unavailable}</p>:<p>Baseline mismatch prevents cost, delay
            and path attribution. Original inputs and failed reconciliation remain retained.</p>}
      </>}
    </section>}
  </section>;
}
