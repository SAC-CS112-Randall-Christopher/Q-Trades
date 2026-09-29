import { memo, useEffect, useRef, useState } from "react";
import { Activity, ChevronRight, Search, Wrench } from "lucide-react";
import { StrategyLab, type Experiments } from "./StrategyLab";
import "./station.css";

type Quote = { symbol: string; bid: string | null; ask: string | null; state: string; source: string; valid_for_ms: number; received_age_ms: number | null };
type Candle = { open_ms: number; close_ms: number; open: string; high: string; low: string; close: string; volume: string };
type Trade = { id: number; price: string; quantity: string; exchange_ms: number };
type Live = { enabled: boolean; running: boolean; error: string | null; selected_symbol: string; markets: Quote[]; book: { bids: string[][]; asks: string[][]; metrics: { spread_bps: string } } | null; trades: Trade[]; trade_gaps: number };
type ScanRow = { symbol: string; eligible: boolean; confirmed: boolean; reason: string; change_percent?: string; quote_volume?: string };
type Detail = { selected_symbol: string; generated_at: number; scan: { rows: ScanRow[]; total: number; omitted: number; observed_at: number; constrained: boolean; selected: string[] }; candles: Candle[]; candle_gaps: object[]; candles_stale: boolean; experiments?: Experiments; strategy: { primary_market: boolean; version: string; entries_paused: boolean; last_decision: { reason: string; at: number } | null; features?: { volume_ratio?: string; atr?: string; trend_up?: boolean } }; paper_events: { id: number; at: number; kind: string; body: { reason?: string; side?: string; price?: string; quantity?: string } }[] };
type Tool = { id: string; name: string; purpose: string };
type Run = { id: number; tool: string; symbol: string; status: string; started: number; error: string | null; result?: { result: Record<string, unknown> } };
type ToolState = { tools: Tool[]; runs: Run[]; total: number; error: string | null };

const number = (v: string | number | null | undefined, digits = 2) => v == null ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const price = (v: string | null | undefined) => number(v, Math.min(8, Math.max(2, v?.replace(/0+$/, "").split(".")[1]?.length ?? 0)));
const time = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const compact = (v?: string) => v == null ? "—" : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(Number(v));

function usePoll<T>(url: string, interval: number, enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [at, setAt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const load = async () => {
      if (document.hidden) { timer = setTimeout(load, 1000); return; }
      const started = performance.now();
      try {
        const response = await fetch(url, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(3000)]) });
        if (!response.ok) throw new Error("Data unavailable; reconnecting…");
        const result = await response.json() as T;
        if (active) { setData(result); setAt(started); setError(null); }
      } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "Connection unavailable"); }
      finally { if (active) timer = setTimeout(load, Math.max(250, interval - (performance.now() - started))); }
    };
    void load();
    return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [url, interval, enabled]);
  return { data, error, at };
}

const Candles = memo(function Candles({ bars, range }: { bars: Candle[]; range: number }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(706);
  useEffect(() => {
    const observer = new ResizeObserver(entries => setChartWidth(Math.max(250, Math.round(entries[0].contentRect.width))));
    if (container.current) observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  const visible = bars.slice(-range);
  if (!visible.length) return <div ref={container} className="station-empty">No recorded candles for this market yet.</div>;
  const plotWidth = chartWidth - 84;
  const low = Math.min(...visible.map(b => Number(b.low)));
  const high = Math.max(...visible.map(b => Number(b.high)));
  const spread = high - low || high * 0.001 || 1;
  const axisDigits = Math.min(8, Math.max(2, Math.ceil(-Math.log10(spread / 4)) + 1));
  const begin = visible[0].open_ms;
  const duration = Math.max(60000, visible[visible.length - 1].open_ms - begin);
  const x = (b: Candle) => 8 + (b.open_ms - begin) / duration * (plotWidth - 16);
  const y = (v: string | number) => 20 + (high - Number(v)) / spread * 153;
  const width = Math.max(1, Math.min(12, (plotWidth - 16) * 60000 / duration * 0.65));
  const volume = Math.max(...visible.map(b => Number(b.volume)), 1);
  const selected = visible[hovered ?? visible.length - 1] ?? visible[visible.length - 1];
  return <div ref={container}>
    <div className="candle-readout"><span>{time(selected.open_ms)}</span><span>O {price(selected.open)}</span><span>H {price(selected.high)}</span><span>L {price(selected.low)}</span><span>C {price(selected.close)}</span></div>
    <svg viewBox={`0 0 ${chartWidth} 250`} role="img" aria-label="Recorded one-minute price candles and volume" onMouseLeave={() => setHovered(null)}>
      {[0, 1, 2, 3, 4].map(i => { const p = low + spread * i / 4; return <g key={i}><line x1="0" x2={plotWidth} y1={y(p)} y2={y(p)} className="chart-grid" /><text x={plotWidth + 10} y={y(p) + 4} className="chart-label">{number(p, axisDigits)}</text></g>; })}
      {visible.map((b, index) => <g key={b.open_ms} className={Number(b.close) >= Number(b.open) ? "candle-up" : "candle-down"}>
        <line x1={x(b)} x2={x(b)} y1={y(b.high)} y2={y(b.low)} />
        <rect x={x(b) - width / 2} y={Math.min(y(b.open), y(b.close))} width={width} height={Math.max(1, Math.abs(y(b.open) - y(b.close)))} />
        <rect x={x(b) - width / 2} y={222 - Number(b.volume) / volume * 28} width={width} height={Number(b.volume) / volume * 28} opacity="0.4" />
        <rect x={x(b) - Math.max(width, 4) / 2} y="8" width={Math.max(width, 4)} height="217" className="candle-hover" onMouseEnter={() => setHovered(index)}><title>{time(b.open_ms)} · O {b.open} H {b.high} L {b.low} C {b.close} · volume {b.volume}</title></rect>
      </g>)}
      <text x="8" y="245" className="chart-label">{time(visible[0].open_ms)}</text><text x={plotWidth} textAnchor="end" y="245" className="chart-label">{time(visible[visible.length - 1].open_ms)}</text>
    </svg>
  </div>;
});

const ToolResult = memo(function ToolResult({ run }: { run: Run }) {
  const result = run.result?.result;
  let summary = run.status === "running" ? "Reading evidence…" : "Evidence saved. Open the receipt to inspect it.";
  if (run.error) summary = run.error;
  else if (run.tool === "cost_hurdle" && result) summary = `The bid would need to rise ${number(String(result.required_bid_move_percent), 3)}% to cover modeled round-trip costs at the top of this book. This is a cost threshold, not a forecast.`;
  else if (run.tool === "strategy_evidence" && result) {
    const decision = result.last_decision as { reason?: string } | null;
    summary = decision?.reason ? `Last recorded decision: ${decision.reason}` : "No primary-account decision has been recorded for this market.";
  } else if (run.tool === "outcome_review" && result) {
    const sample = result.sample_totals as { trades: number; net_pnl: string; fees: string } | undefined;
    summary = sample ? `${sample.trades} recent ${run.symbol.replace(/USD$/, "")} trades: $${number(sample.net_pnl)} net profit / loss, including $${number(sample.fees)} in fees. This is the selected market's sample, not the whole account.` : `${result.retained_market_count} matching closed trades in the retained primary-account window. The receipt separates these from whole-account totals.`;
  }
  else if (run.tool === "market_evidence" && result) {
    const live = result.live as Live | undefined;
    const detail = result.detail as Detail | undefined;
    const quote = live?.markets.find(q => q.symbol === run.symbol);
    summary = `Quote ${quote?.state ?? "unavailable"} at capture. Saved ${detail?.candles.length ?? 0} closed candles and ${live?.trades.length ?? 0} observed trades, with the available order book and strategy evidence.`;
  }
  return <div className="tool-result" role="status"><div className="tool-result-heading"><strong>{run.symbol.replace(/USD$/, " / USD")}</strong><span className={run.status === "completed" ? "station-positive" : "station-muted"}>{run.status}</span></div><p>{summary}</p><details><summary>Evidence / diagnostics</summary><pre>{JSON.stringify(run, null, 2)}</pre></details></div>;
});

export function MarketStation({ strategyOnly = false }: { strategyOnly?: boolean }) {
  const section = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(true);
  const [symbol, setSymbol] = useState("BTCUSD");
  const [search, setSearch] = useState("");
  const [qualifiedOnly, setQualifiedOnly] = useState(false);
  const [range, setRange] = useState(60);
  const [clock, setClock] = useState(performance.now());
  const [latest, setLatest] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [toolError, setToolError] = useState<string | null>(null);
  const livePoll = usePoll<Live>(`/api/station/live?symbol=${symbol}`, strategyOnly ? 10000 : 1000, visible);
  const detailPoll = usePoll<Detail>(`/api/station/detail?symbol=${symbol}`, 10000, visible);
  const toolsPoll = usePoll<ToolState>("/api/research/tools", 10000, visible);
  const live = livePoll.data?.selected_symbol === symbol ? livePoll.data : null;
  const detail = detailPoll.data?.selected_symbol === symbol ? detailPoll.data : null;
  const quote = live?.markets.find(q => q.symbol === symbol);
  const elapsed = Math.max(0, clock - livePoll.at);
  const fresh = !!quote && !livePoll.error && live?.running && !live.error && quote.state === "fresh" && elapsed < quote.valid_for_ms;
  const scanner = detailPoll.data?.scan;
  const rows = scanner?.rows.filter(r => r.symbol.includes(search.toUpperCase()) && (!qualifiedOnly || r.eligible)) ?? [];
  const change = scanner?.rows.find(r => r.symbol === symbol)?.change_percent;

  useEffect(() => {
    const observer = new IntersectionObserver(entries => setVisible(entries[0].isIntersecting), { rootMargin: "200px" });
    if (section.current) observer.observe(section.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible) return;
    const timer = setInterval(() => setClock(performance.now()), 250);
    return () => clearInterval(timer);
  }, [visible]);

  const runTool = async (tool: string) => {
    setBusy(true); setToolError(null);
    try {
      const response = await fetch("/api/research/tools/run", { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" }, body: JSON.stringify({ tool, symbol }), signal: AbortSignal.timeout(7000) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "Tool could not run");
      setLatest(result as Run);
    } catch (cause) { setToolError(cause instanceof DOMException ? "Tool request was not confirmed; check saved runs before retrying." : cause instanceof Error ? cause.message : "Tool request was not confirmed; check saved runs before retrying."); }
    finally { setBusy(false); }
  };
  const openRun = async (id: number) => {
    try {
      const response = await fetch(`/api/research/tools/runs/${id}`, { signal: AbortSignal.timeout(3000) });
      if (!response.ok) throw new Error("Saved receipt unavailable");
      setLatest(await response.json() as Run); setToolError(null);
    } catch { setToolError("Saved receipt unavailable. The journal has not been reset."); }
  };

  return <section ref={section} id="live-quotes" className="market-station" aria-labelledby="station-title">
    <header className="station-heading"><div><p>CRYPTO SPOT · PAPER RESEARCH</p><h2 id="station-title">{strategyOnly ? "Strategy evidence" : "Market command station"}</h2></div>{strategyOnly ? <label>Market <select value={symbol} onChange={e => setSymbol(e.target.value)}>{[...new Set(["BTCUSD", "ETHUSD", ...(scanner?.selected ?? [])])].map(s => <option key={s}>{s}</option>)}</select></label> : <span className="station-local"><Activity size={14} /> Local workspace</span>}</header>
    {!strategyOnly && <>
    <div className="station-workspace">
      <aside className="station-watchlist" aria-label="Market scanner">
        <div className="station-pane-title"><h3>Markets</h3><span>{scanner?.total ?? "—"} screened</span></div>
        <label className="station-search"><Search size={14} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Find a market" aria-label="Find a market" /></label>
        <label className="station-filter"><input type="checkbox" checked={qualifiedOnly} onChange={e => setQualifiedOnly(e.target.checked)} /> Passed liquidity screen</label>
        <div className="watchlist-labels"><span>Market</span><span>24h</span><span>USD vol.</span></div>
        <div className="watchlist-rows">{rows.map(row => <button type="button" key={row.symbol} onClick={() => setSymbol(row.symbol)} className={row.symbol === symbol ? "selected" : ""} aria-pressed={row.symbol === symbol} title={row.reason}><strong>{row.symbol.replace(/USD$/, "")}</strong><span className={Number(row.change_percent) >= 0 ? "station-positive" : "station-negative"}>{row.change_percent == null ? "—" : `${number(row.change_percent)}%`}</span><span>{compact(row.quote_volume)}</span></button>)}</div>
        {!rows.length && <p className="station-empty">{scanner ? "No matching markets." : "Loading the market screen…"}</p>}
        {!!scanner?.omitted && <p className="station-small">{scanner.omitted} markets outside this view.</p>}
        <p className="station-small">{scanner?.constrained ? "Extra streams are temporarily reduced. Priority markets stay active." : "Liquid candidates receive closer observation."}</p>
      </aside>
      <div className="station-market">
        <div className="station-quote-heading"><div><h3>{symbol.replace(/USD$/, " / USD")}</h3><span className={Number(change) >= 0 ? "station-positive" : "station-negative"}>{change == null ? "" : `${number(change)}% over 24h`}</span></div><span className={`station-feed-state ${fresh ? "current" : ""}`}>{livePoll.error ? "Disconnected" : fresh ? (quote?.source.includes("websocket") ? "Live" : "Polling fallback") : quote ? (quote.state === "fresh" ? "Refreshing" : "Stale quote") : !live ? "Connecting…" : "Not streaming"}</span></div>
        <div className="station-prices"><div><span>Best bid</span><strong>{price(quote?.bid)}</strong></div><div><span>Best ask</span><strong>{price(quote?.ask)}</strong></div><div><span>Spread</span><strong>{number(live?.book?.metrics.spread_bps, 2)} <small>bps</small></strong></div></div>
        {live && !quote && <p className="station-inline-note">This market is screened, but has no active quote stream. Selecting it does not override the feed's resource limits.</p>}
        <div className="station-chart">
          <div className="station-pane-title"><h3>Price &amp; volume <span>· 1-minute candles</span></h3><div className="chart-ranges" aria-label="Chart history">{[30, 60, 120].map(n => <button type="button" key={n} className={range === n ? "selected" : ""} onClick={() => setRange(n)} aria-pressed={range === n}>{n === 30 ? "30m" : n === 60 ? "1h" : "2h"}</button>)}</div></div>
          {detail ? <Candles bars={detail.candles} range={range} /> : <div className="station-empty">Loading recorded price history…</div>}
          {detail?.candles_stale && <p className="station-inline-note">Recorded candles are stale; this chart is historical.</p>}
          {!!detail?.candle_gaps.length && <p className="station-inline-note">This chart contains gaps in recorded history.</p>}
          {detailPoll.error && <p className="station-inline-note">Chart and decision evidence could not refresh.</p>}
        </div>
        <div className="station-decision"><div><p className="station-kicker">WHY THE STRATEGY ACTED</p><h4>{detail?.strategy.last_decision?.reason || (detail?.strategy.primary_market === false ? "Observed for the wider-market comparison" : "Awaiting a recorded decision")}</h4><p>{detail?.strategy.last_decision ? `${time(detail.strategy.last_decision.at * 1000)} · ${detail.strategy.version}` : "No primary-account decision is available for this market."}</p></div><button type="button" disabled={busy || !detail} onClick={() => void runTool("strategy_evidence")}>Inspect evidence <ChevronRight size={14} /></button></div>
      </div>
    </div>
    <div className="station-lower">
      <section className="station-depth" aria-label="Visible order book"><div className="station-pane-title"><h3>Order book</h3><span>{fresh ? "Visible liquidity" : "Last observed · may be stale"}</span></div><div className="depth-halves">{(["bids", "asks"] as const).map(side => <div key={side}><div className="depth-labels"><span>{side === "bids" ? "Bid" : "Ask"}</span><span>Quantity</span></div>{(live?.book?.[side] ?? []).slice(0, 8).map(([p, q]) => <div className={`depth-row ${side}`} key={p}><span>{price(p)}</span><span>{number(q, 5)}</span></div>)}</div>)}</div>{!live?.book && <p className="station-empty">No order book is available for this market.</p>}</section>
      <section className="station-tape" aria-label="Recent exchange trades"><div className="station-pane-title"><h3>Recent trades</h3><span>Exchange prints</span></div><div className="tape-labels"><span>Price</span><span>Quantity</span><span>Time</span></div>{live?.trades.slice(0, 8).map(t => <div className="tape-row" key={t.id}><span>{price(t.price)}</span><span>{number(t.quantity, 5)}</span><span>{time(t.exchange_ms)}</span></div>)}{!live?.trades.length && <p className="station-empty">No trades observed since this stream started. A quiet market can still update its quotes.</p>}{!!live?.trade_gaps && <p className="station-small">The observed tape has gaps.</p>}</section>
      <section className="station-events" aria-label="Recent paper activity"><div className="station-pane-title"><h3>Paper activity</h3><span>Primary account</span></div>{detail?.paper_events.slice(0, 5).map(event => <div className="station-event" key={event.id}><div><strong>{event.kind.replaceAll("_", " ")}</strong><time>{time(event.at * 1000)}</time></div><p>{event.body.reason ?? [event.body.side, event.body.quantity, event.body.price].filter(Boolean).join(" · ")}</p></div>)}{!detail?.paper_events.length && <p className="station-empty">No matching activity in the recent account window.</p>}<button className="station-text-button" type="button" disabled={busy || !detail} onClick={() => void runTool("outcome_review")}>Review outcomes <ChevronRight size={14} /></button></section>
    </div>
    </>}
    {strategyOnly && (detail?.experiments ? <StrategyLab data={detail.experiments} symbol={symbol} unavailable={!!detailPoll.error || live?.running !== true || !!live?.error} /> : <p className="station-empty">{detailPoll.error ?? "Waiting for recorded strategy evidence…"}</p>)}
    <section className="station-tools" aria-label="Research tools"><div className="station-pane-title"><h3><Wrench size={15} /> Research tools</h3><span>Read-only · saved results</span></div><div className="station-tool-buttons">{toolsPoll.data?.tools.map(tool => <button key={tool.id} type="button" disabled={busy || !detail} title={tool.purpose} onClick={() => void runTool(tool.id)}>{busy ? "Working…" : tool.name}</button>)}</div>{(toolError || toolsPoll.error || toolsPoll.data?.error) && <p className="station-inline-note" role="alert">{toolError || toolsPoll.error || toolsPoll.data?.error}</p>}{latest && <ToolResult run={latest} />}<div className="station-agents"><span><strong>Researcher · Trainer · Reviewer</strong> — awaiting model qualification</span><a href="#model-lab">View model trials <ChevronRight size={13} /></a></div><details className="station-receipts"><summary>Saved tool runs ({toolsPoll.data?.total ?? 0})</summary>{toolsPoll.data?.runs.map(run => <button key={run.id} type="button" onClick={() => void openRun(run.id)}>{time(run.started * 1000)} · {run.symbol} · {toolsPoll.data?.tools.find(t => t.id === run.tool)?.name ?? run.tool}<span>{run.status}</span></button>)}</details></section>
    <details className="station-diagnostics"><summary>Evidence / diagnostics</summary><p>Prices refresh about once a second; charts and decisions refresh every ten seconds. Screened markets do not all have active streams. Charts contain closed candles, including bootstrap history; exchange prints are an incomplete recent window.</p><pre>{JSON.stringify({ quote, scan_observed_at: scanner?.observed_at, details_observed_at: detail?.generated_at, trade_gaps: live?.trade_gaps, live_error: livePoll.error, detail_error: detailPoll.error }, null, 2)}</pre></details>
  </section>;
}
