import { useEffect, useRef, useState } from "react";
import { HistoricalMatches, type Episode, type MarketOutcome } from "./HistoricalMatches";
import { ReplayPanel } from "./ReplayPanel";

export type EvidenceStatus = {
  state: string; rows?: number; bytes?: number; physical_bytes?: number;
  queue?: number; queue_limit?: number; queue_dropped?: number; dropped?: number;
  reason?: string; retention?: string;
  episodes?: number; outcomes?: number;
};
type EvidenceRow = { id: number; at: number; kind: string; sha256: string; bytes: number };
type Page = { records: EvidenceRow[]; has_more: boolean; next_before: number | null };
type Detail = {
  id: number; sha256: string;
  payload: {
    at: number; kind: string; scope?: string; coverage?: string;
    frames?: Record<string, { source: string; observed: number; exchange_event_ms?: number;
      clock_uncertainty_ms?: number; book_validation_ms?: number;
      raw: { lastUpdateId: number }; }>;
    events?: { account: string; kind: string; body: { symbol?: string; reason?: string } }[];
    stages_ms?: Record<string, number>; receipt_to_dispatch_ms?: Record<string, number>;
    queue_wait_ms?: number;
    feature_timing?: Record<string, {available_at: number; compute_ms: number}>;
    episode?: Episode | string; memory_status?: string;
  };
  original_episode?: Episode;
  subsequent_outcome?: {status?: string; id?: number; payload?: MarketOutcome};
  reproduction: {
    status: string; reason?: string; book_features_match?: boolean;
    closed_bar_features?: Record<string, { matched?: boolean; status?: string; reason?: string }>;
  };
};
const when = (at: number) => new Date(at * 1000).toLocaleString("en-US", {timeZone:"America/Denver"});
const ms = (value: number | undefined) => value == null ? "Unavailable" : `${value.toFixed(3)} ms`;

export function EvidencePanel({ status }: { status?: EvidenceStatus }) {
  const [page,setPage] = useState<Page | null>(null);
  const [detail,setDetail] = useState<Detail | null>(null);
  const [kind,setKind] = useState("decision");
  const [pending,setPending] = useState(false);
  const [error,setError] = useState<string | null>(null);
  const [showRaw,setShowRaw] = useState(false);
  const request = useRef<AbortController | null>(null);
  const selected = useRef<HTMLElement | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (detail) {
      selected.current?.scrollIntoView({block:"start", behavior:"auto"});
      selected.current?.focus({preventScroll:true});
    }
  },[detail]);
  async function load(before=0, filter=kind) {
    request.current?.abort();
    const abort = new AbortController(); request.current=abort;
    setPending(true); setError(null);
    try {
      const response=await fetch(`/api/evidence?limit=20&before=${before}&kind=${filter}`,
        {signal:AbortSignal.any([abort.signal,AbortSignal.timeout(7000)]),cache:"no-store"});
      if (!response.ok) throw new Error("Recorded evidence could not load. Earlier inputs stay preserved.");
      const value=await response.json() as Page;
      if (!abort.signal.aborted) {setPage(value); setDetail(null); setShowRaw(false);}
    } catch {if (!abort.signal.aborted) setError("Recorded evidence is unavailable. Reconnect and refresh; earlier inputs stay preserved.");}
    finally {if (!abort.signal.aborted) setPending(false);}
  }
  useEffect(() => {void load(0,kind);},[kind]);
  async function open(id: number) {
    request.current?.abort();
    const abort=new AbortController(); request.current=abort;
    setPending(true); setError(null); setDetail(null); setShowRaw(false);
    try {
      const response=await fetch(`/api/evidence/${id}`,
        {signal:AbortSignal.any([abort.signal,AbortSignal.timeout(10000)]),cache:"no-store"});
      if (!response.ok) throw new Error("This evidence is missing or corrupt. No substitute was inferred.");
      const value=await response.json() as Detail;
      if (!abort.signal.aborted) setDetail(value);
    } catch {if (!abort.signal.aborted) setError("This evidence could not be opened. It may be unavailable or damaged; no substitute was inferred.");}
    finally {if (!abort.signal.aborted) setPending(false);}
  }
  const episode = detail?.original_episode ?? (typeof detail?.payload.episode === "object"
    ? detail.payload.episode : undefined);
  return <section className="workspace-card evidence-panel" aria-label="Recorded decision evidence">
    <div className="card-heading"><div><p className="eyebrow">RESEARCH INPUTS</p>
      <h2>Historical matches & decision evidence</h2></div>
      <button className="button secondary small" disabled={pending} onClick={()=>void load()}>Refresh evidence</button>
    </div>
    <p>Reopen what was available. Fixed representative windows include ordinary and no-trade periods;
      broad summaries continue between them. Missing coverage stays unknown.</p>
    <dl className="summary-values"><div><dt>Acquisition</dt><dd>{status?.state ?? "Not captured"}</dd></div>
      <div><dt>Retained records</dt><dd>{status?.rows ?? "Unavailable"}</dd></div>
      <div><dt>Optional queue</dt><dd>{status?.queue ?? "Unavailable"} / {status?.queue_limit ?? 8}</dd></div>
      <div><dt>Omitted records</dt><dd>{status?.dropped == null ? "Unavailable"
        : status.dropped+(status.queue_dropped ?? 0)}</dd></div></dl>
    <p className="fine-print">Separate local archive · no financial authority. Capacity stops optional
      collection; retained experiment inputs are never evicted. Raw captured data is for local internal use.</p>
    <p className="fine-print">Episodes: {status?.episodes ?? "Unavailable"} · Matured outcomes:
      {status?.outcomes ?? "Unavailable"} · Archive: {status?.physical_bytes == null ? "Unavailable"
      : `${(status.physical_bytes/1024/1024).toFixed(2)} MiB`} / 64 MiB default budget.</p>
    {status?.reason && <p role="status">{status.reason}</p>}
    {error && <p role="alert" className="error-banner">{error}</p>}
    {pending && <p role="status">Loading recorded evidence…</p>}
    <label>Evidence type <select aria-label="Evidence type" value={kind} onChange={e=>setKind(e.target.value)}>
      <option value="decision">Decision bundles</option><option value="summary">Coverage summaries</option>
      <option value="wire">Selected wire observations</option>
      <option value="outcome">Subsequent market outcomes</option></select></label>
    <div className="table-scroll"><table className="market-table" aria-label="Retained evidence records">
      <thead><tr><th>Recorded Denver time</th><th>Input reference</th><th>Type</th><th>Size</th><th/></tr></thead>
      <tbody>{page?.records.map(r=><tr key={r.id}><td>{when(r.at)}</td><td>#{r.id} · {r.sha256.slice(0,12)}</td>
        <td>{r.kind}</td><td>{(r.bytes/1024).toFixed(1)} KiB</td><td>
          <button className="button secondary small" disabled={pending} onClick={()=>void open(r.id)}>
            Inspect evidence {r.id}</button></td></tr>)}</tbody></table></div>
    {page && !page.records.length && <p>No records of this type have been captured. Historical minute quotes
      cannot supply missing executable books.</p>}
    <div className="heading-actions"><button className="button secondary small" disabled={pending}
      onClick={()=>void load()}>Latest evidence</button><button className="button secondary small"
      disabled={pending || !page?.has_more} onClick={()=>void load(page?.next_before ?? 0)}>Older evidence</button></div>
    {detail && <section ref={selected} tabIndex={-1} aria-label="Selected decision evidence">
      <h3>Retained input #{detail.id}</h3><p className="fine-print">SHA-256 {detail.sha256}</p>
      <p>{detail.payload.coverage ?? "Selected raw observation only"}</p><p>{detail.payload.scope}</p>
      {detail.payload.memory_status && <p>{detail.payload.memory_status}</p>}
      {episode && <HistoricalMatches episode={episode} outcome={detail.subsequent_outcome?.payload}
        pending={pending} open={id=>void open(id)} />}
      <p>Reproduction: {detail.reproduction.status}. {detail.reproduction.reason}
        {detail.reproduction.book_features_match !== undefined &&
          ` Book features ${detail.reproduction.book_features_match ? "match" : "differ — inspect before use"}.`}</p>
      {Object.entries(detail.reproduction.closed_bar_features ?? {}).map(([symbol,r])=><p key={symbol}>
        {symbol} closed-bar features: {r.matched===true?"identical":r.matched===false?"differ":r.reason??"unavailable"}.</p>)}
      <div className="table-scroll"><table className="market-table" aria-label="Decision input timing">
        <thead><tr><th>Market / source</th><th>Receipt</th><th>Sequence</th><th>Book validation</th>
          <th>Receipt to dispatch</th><th>Exchange clock uncertainty</th></tr></thead>
        <tbody>{Object.entries(detail.payload.frames ?? {}).map(([symbol,f])=><tr key={symbol}>
          <td>{symbol}<small>{f.source}</small></td><td>{when(f.observed)}</td><td>{f.raw.lastUpdateId}</td>
          <td>{ms(f.book_validation_ms)}</td><td>{ms(detail.payload.receipt_to_dispatch_ms?.[symbol])}</td>
          <td>{ms(f.clock_uncertainty_ms)}</td></tr>)}</tbody></table></div>
      <dl className="summary-values">{Object.entries(detail.payload.stages_ms ?? {}).map(([k,v])=><div key={k}>
        <dt>{k}</dt><dd>{ms(v)}</dd></div>)}<div><dt>Archive queue wait</dt><dd>{ms(detail.payload.queue_wait_ms)}</dd></div></dl>
      {Object.entries(detail.payload.feature_timing ?? {}).map(([symbol,t])=><p key={symbol}>
        {symbol} shared features available {when(t.available_at)} · computation {ms(t.compute_ms)}.</p>)}
      <p>Monotonic durations belong to this local process session. Missing stages stay unavailable.
        Reservation/event timestamps are retained with the raw bundle; they are not broker acknowledgments.</p>
      <ul>{detail.payload.events?.filter(e=>e.kind==="decision" || e.kind==="order_intent").slice(0,40).map((e,i)=><li key={i}>
        {e.account} · {e.body.symbol} · {e.kind} · {e.body.reason ?? "Recorded event"}</li>)}</ul>
      <button className="button secondary small" onClick={()=>setShowRaw(!showRaw)}>
        {showRaw?"Hide retained inputs":"Show retained inputs"}</button>
      {showRaw && <pre className="evidence-raw">{JSON.stringify(detail,null,2)}</pre>}
    </section>}
    <ReplayPanel recordId={detail?.payload.kind==="decision"?detail.id:undefined}/>
  </section>;
}
