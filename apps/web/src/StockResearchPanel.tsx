import { useState, type FormEvent } from "react";

type Study = { id: string; identity: {issuer: string; cik: string; ticker: string; history: string}; facts: {tag: string; unit: string; value: string; start: string | null; end: string; accession: string; availability_precision: string; form: string}[]; ratios: {liabilities_to_assets: string | null; reason: string | null}; timeline: {accession: string; form: string; period: string; source_url: string}[]; market: Record<string, unknown>; limitations: string[]; executability: string };
export function StockResearchPanel() {
  const [security, setSecurity] = useState("IBM");
  const [cutoff, setCutoff] = useState(new Date().toISOString().slice(0,16));
  const [market, setMarket] = useState(false);
  const [hypothesis, setHypothesis] = useState("Compare compatible liabilities and assets across reported periods; retain unknown inputs.");
  const [result, setResult] = useState<Study | null>(null);
  const [section, setSection] = useState<unknown>(null);
  const [phrase, setPhrase] = useState("Risk Factors");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent | null, dailyOnly = false) => {
    e?.preventDefault(); setBusy(true); setError(null); setResult(null); setSection(null);
    try {
      const r = await fetch(dailyOnly ? "/api/research/stocks/market-study" : "/api/research/stocks/investigations", {method:"POST",headers:{"Content-Type":"application/json","X-Local-Operator":"1"},body:JSON.stringify({security,as_of:Date.parse(cutoff+"Z")/1000,market:dailyOnly || market,hypothesis}),signal:AbortSignal.timeout(180000)});
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? "Official-source investigation unavailable");
      setResult(body as Study); localStorage.setItem("qtrades-stock-study", (body as Study).id);
    } catch(e) {setError(String(e));} finally {setBusy(false);}
  };
  const reopen = async () => {
    const id = localStorage.getItem("qtrades-stock-study"); if (!id) return;
    try {const r = await fetch(`/api/research/stocks/studies/${encodeURIComponent(id)}`, {signal:AbortSignal.timeout(10000)}); if (!r.ok) throw new Error("Exact saved stock study unavailable"); setResult(await r.json() as Study); setError(null);} catch(e) {setError(String(e));}
  };
  const inspect = async (compare: boolean) => {
    if (!result) return;
    try {const r = await fetch(`/api/research/stocks/studies/${result.id}/section?${new URLSearchParams({phrase,compare:String(compare)})}`,{signal:AbortSignal.timeout(120000)});const body = await r.json();if (!r.ok) throw new Error(body.detail ?? "Exact filing unavailable");setSection(body);setError(null);} catch(e) {setError(String(e));}
  };
  return <section aria-labelledby="stock-research-title"><h3 id="stock-research-title">Stock filing research</h3>
    <p>Read official reported facts at a declared cutoff, inspect original filings and save a reproducible study. Market data is limited to the documented public IBM daily example. No stock execution is available.</p>
    <form onSubmit={e => void submit(e)}><label>Current SEC ticker or CIK <input required value={security} onChange={e => setSecurity(e.target.value.toUpperCase())} /></label><label>Information cutoff (UTC) <input required type="datetime-local" value={cutoff} onChange={e => setCutoff(e.target.value)} /></label><label>Study hypothesis <textarea minLength={12} maxLength={500} required value={hypothesis} onChange={e => setHypothesis(e.target.value)} /></label><label><input type="checkbox" checked={market} onChange={e => setMarket(e.target.checked)} />Include public IBM daily market example</label><button disabled={busy} type="submit">{busy?"Reading bounded official sources…":"Investigate and save study"}</button></form>
    <button type="button" onClick={() => void reopen()}>Reopen saved stock study</button>
    <button type="button" disabled={busy || security !== "IBM"} onClick={() => void submit(null,true)}>Save public IBM daily-only study</button>
    {error && <p role="alert">{error}</p>}
    {result && <article><h4>{result.identity.issuer} · {result.identity.ticker} · CIK {result.identity.cik}</h4><p>{result.identity.history}</p><div className="table-scroll"><table><thead><tr><th>Reported fact</th><th>Original value/unit</th><th>Period</th><th>Source version</th></tr></thead><tbody>{result.facts.map((f,i) => <tr key={i}><td>{f.tag}</td><td>{f.value} {f.unit}</td><td>{f.start ?? "Instant"} → {f.end}</td><td>{f.form} · {f.accession} · {f.availability_precision}</td></tr>)}</tbody></table></div>
      <p>Compatible liabilities/assets: {result.ratios.liabilities_to_assets ?? result.ratios.reason}</p><ul>{result.timeline.map(t => <li key={t.accession}><a href={t.source_url} target="_blank" rel="noreferrer">{t.form} · {t.period} · {t.accession}</a></li>)}</ul>
      <label>Exact filing phrase <input minLength={3} maxLength={100} value={phrase} onChange={e => setPhrase(e.target.value)} /></label><button type="button" onClick={() => void inspect(false)}>Inspect bounded filing excerpt</button><button type="button" disabled={result.timeline.length < 2} onClick={() => void inspect(true)}>Compare two filing excerpts</button>
      {section != null && <details open><summary>Exact filing excerpts and limitations</summary><pre>{JSON.stringify(section,null,2)}</pre></details>}
      <details open><summary>Actual market coverage and calculations</summary><pre>{JSON.stringify(result.market,null,2)}</pre></details><p>{result.executability}</p><ul>{result.limitations.map(l => <li key={l}>{l}</li>)}</ul><details><summary>Saved exact source references and study</summary><pre>{JSON.stringify(result,null,2)}</pre></details>
    </article>}
  </section>;
}
