import { useEffect, useState } from "react";

type Packet = {version:string;sources_checked_on:string;generated_at:number;facts_sha256:string;facts:string[];
  blockers:string[];remaining_engineering:string[];sources:{title:string;url:string}[];
  economics:{capital_usd:string;published_fee_only_round_trip_usd:string;
    legacy_fee_only_round_trip_usd:string;two_bp_each_side_price_proxy_usd:string;
    illustrative_one_usd_monthly_operating_percent:string}[];economics_limits:string;
  current_paper_evidence:{evidence_kind:string;research_incumbent:string;retained_report_count:number};
  risk_envelope:{limits:string}};

export function ReadinessPanel() {
  const [data,setData] = useState<Packet|null>(null);
  const [error,setError] = useState("");
  const [refresh,setRefresh] = useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    void fetch("/api/readiness",{cache:"no-store",signal:AbortSignal.any([controller.signal,AbortSignal.timeout(7000)])})
      .then(async response=>{if(!response.ok)throw new Error();return response.json() as Promise<Packet>;})
      .then(value=>{if(!controller.signal.aborted){setData(value);setError("");}})
      .catch(()=>{if(!controller.signal.aborted)setError("Readiness packet unavailable. Retained information may be stale.");});
    return ()=>controller.abort();
  },[refresh]);
  const dollars=(v:string)=>Number(v).toLocaleString("en-US",{style:"currency",currency:"USD",minimumFractionDigits:4});
  return <section id="live-readiness" className="research-section" aria-label="Live readiness decision packet">
    <div className="section-heading plain"><div><p className="eyebrow">LIVE FEASIBILITY</p><h2>Not ready for live trading.</h2></div><span className="subtle-note">Paper only · live disabled</span></div>
    <p>Paper accounts are separate hypothetical experiments. A future $50 or $100 budget would be total settled capital, not funding for every paper portfolio.</p>
    {error && <p role="alert">{error}</p>}
    {data && <>
      <p>Sources checked {data.sources_checked_on}. Paper evidence as of {new Date(data.generated_at*1000).toLocaleString()}: {data.current_paper_evidence.evidence_kind}; {data.current_paper_evidence.retained_report_count} retained reports. Research role: {data.current_paper_evidence.research_incumbent}.</p>
      <h3>What still blocks a separate live decision</h3><ul>{data.blockers.map(v=><li key={v}>{v}</li>)}</ul>
      <h3>Small-account cost scenarios</h3>
      <div className="readiness-table"><table><caption>Illustrative full-capital round trip at unchanged price</caption><thead><tr><th>Total capital</th><th>Published fee scenario</th><th>Legacy fee stress</th><th>Price adversity proxy</th><th>$1/month example</th></tr></thead>
        <tbody>{data.economics.map(v=><tr key={v.capital_usd}><td>${v.capital_usd}</td><td>{dollars(v.published_fee_only_round_trip_usd)}</td><td>{dollars(v.legacy_fee_only_round_trip_usd)}</td><td>{dollars(v.two_bp_each_side_price_proxy_usd)}</td><td>{v.illustrative_one_usd_monthly_operating_percent}% of capital</td></tr>)}</tbody></table></div>
      <p>{data.economics_limits}</p><p>{data.risk_envelope.limits}</p>
      <details><summary>Source facts and remaining engineering</summary><ul>{data.facts.map(v=><li key={v}>{v}</li>)}</ul><ol>{data.remaining_engineering.map(v=><li key={v}>{v}</li>)}</ol>
        <p>{data.sources.map((s,i)=><span key={s.url}>{i>0 ? " · " : ""}<a href={s.url} target="_blank" rel="noreferrer">{s.title}</a></span>)}</p>
        <p>Packet {data.version}. Facts fingerprint {data.facts_sha256}.</p></details>
      <a href="/api/readiness" download="qtrades-readiness.json">Export readiness packet</a>
    </>}
    <button type="button" onClick={()=>setRefresh(v=>v+1)}>Refresh paper evidence</button>
    <p>This packet cannot enable trading, change permissions or submit an order. Any future approval requires its own frozen evidence and account decision.</p>
  </section>;
}
