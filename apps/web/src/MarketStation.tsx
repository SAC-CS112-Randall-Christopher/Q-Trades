import { memo, useEffect, useRef, useState } from "react";
import { Activity, ChevronRight, Search, Wrench } from "lucide-react";
import { StrategyLab, type Experiments } from "./StrategyLab";
import "./station.css";
import { MarketChart, type Candle, type Indicators } from "./MarketChart";
import { useEvidenceRead } from "./useEvidenceRead";
import { CandleWorkspace } from "./CandleWorkspace";

const historicalTools = new Set(["input_diagnosis", "cost_diagnosis", "strategy_evidence", "outcome_review"]);

type Quote = { symbol: string; bid: string | null; ask: string | null; state: string; source: string; valid_for_ms: number; received_age_ms: number | null };
type Trade = { id: number; price: string; quantity: string; exchange_ms: number };
type Live = { enabled: boolean; running: boolean; error: string | null; selected_symbol: string; markets: Quote[]; book: { bids: string[][]; asks: string[][]; metrics: { spread_bps: string } } | null; trades: Trade[]; trade_gaps: number };
type ScanRow = { symbol: string; eligible: boolean; confirmed: boolean; reason: string; change_percent?: string; quote_volume?: string };
type Detail = { selected_symbol: string; generated_at: number; scan: { rows: ScanRow[]; total: number; omitted: number; observed_at: number; constrained: boolean; selected: string[] }; candles: Candle[]; indicators?: Indicators; candle_gaps: object[]; candles_stale: boolean; experiments?: Experiments; strategy: { account: string; primary_market: boolean; version: string; entries_paused: boolean; last_decision: { reason: string; at: number } | null; features?: { volume_ratio?: string; atr?: string; trend_up?: boolean } }; paper_events: { id: number; at: number; kind: string; body: { reason?: string; side?: string; price?: string; quantity?: string } }[] };
type Tool = { id: string; name: string; purpose: string };
type Run = { id: number; tool: string; symbol: string; account?: string; status: string; started: number; error: string | null; result?: { result: Record<string, unknown>; envelope?: { account: string; observation_cutoff: number; overview_scope?: string; coverage?: { saved_candles: number; saved_trades?: number } } } };
type ToolState = { tools: Tool[]; runs: Run[]; total: number; error: string | null; next_cursor?: string | null };
type ToolAccounts = { accounts: { account: string; label: string; archived: boolean }[]; next_before?: string | null };
type EvidencePage = { facts?: Record<string, unknown>; events?: { id: number; at: number; body: Record<string, unknown> }[]; total?: number; offset?: number; next_cursor?: string | null };
type Diagnosis = { diagnosis: string; status: string; summary: string; facts: string[]; hypotheses: string[]; unresolved: string[]; next_question: string; population: Record<string, unknown>; problem_counts?: Record<string, number>; current_request_counts?: Record<string, unknown>; rows?: { at: number; source_available_at: number | null; reference: string; problems: string[]; could_evaluate: boolean; decision_meaning: string; recorded_decision: { reason?: string } | null }[]; measured?: { gross_before_recorded_fees_usd: string; recorded_fees_usd: string; net_closed_pnl_usd: string; gross_basis: string; net_basis: string; account_totals_basis?: string; accounting_at?: number | null; closed_trade_cohort?: { account: string; symbol: string; interval: { start: number; end: number }; basis: string }; whole_account: { cash?: string; net_pnl?: string | null }; open_holdings: Record<string, unknown>; original_cost_groups: { version: string | null; execution_profile: string | null; holding_horizon: string | null; trades: number; gross_before_recorded_fees_usd: string; fees: string; net_pnl: string }[]; matched_trial_comparison?: object | null } };

const number = (v: string | number | null | undefined, digits = 2) => v == null ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const price = (v: string | null | undefined) => number(v, Math.min(8, Math.max(2, v?.replace(/0+$/, "").split(".")[1]?.length ?? 0)));
const time = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const compact = (v?: string) => v == null ? "—" : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(Number(v));

function savedScope() {
  const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
  const symbol = params.get("symbol") ?? localStorage.getItem("qtrades-tool-symbol") ?? "BTCUSD";
  const account = params.get("account") ?? localStorage.getItem("qtrades-tool-account") ?? "primary";
  return { symbol: /^[A-Z0-9]{3,24}$/.test(symbol) ? symbol : "UNAVAILABLE", account: /^[a-zA-Z0-9_.-]{1,100}$/.test(account) ? account : "unavailable-requested-account" };
}

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

function DiagnosisResult({ value }: { value: Diagnosis }) {
  return <section aria-label="Recorded strategy diagnosis"><h3>{value.diagnosis === "input_coverage" ? "Could we evaluate?" : "What did the recorded cohort establish?"}</h3><p>{value.summary}</p>
    <h4>Measured facts</h4><ul>{value.facts.map(f => <li key={f}>{f}</li>)}</ul>
    {value.measured && <p>Gross before recorded fees ${number(value.measured.gross_before_recorded_fees_usd)} · fees ${number(value.measured.recorded_fees_usd)} · closed net ${number(value.measured.net_closed_pnl_usd)}.<br />{value.measured.gross_basis}. {value.measured.net_basis}.<br />Whole-account cash ${number(value.measured.whole_account.cash)}; net ${number(value.measured.whole_account.net_pnl)}; {Object.keys(value.measured.open_holdings).length} open holdings. Unknown marks remain unknown.</p>}
    {value.measured && <p>Whole-account basis: {value.measured.account_totals_basis ?? "Original basis unavailable"}. Accounting time: {value.measured.accounting_at == null ? "unknown" : new Date(value.measured.accounting_at * 1000).toLocaleString()}.<br />Selected closed-event cohort: {value.measured.closed_trade_cohort ? `${value.measured.closed_trade_cohort.account} · ${value.measured.closed_trade_cohort.symbol} · ${new Date(value.measured.closed_trade_cohort.interval.start * 1000).toLocaleString()} to ${new Date(value.measured.closed_trade_cohort.interval.end * 1000).toLocaleString()}. ${value.measured.closed_trade_cohort.basis}` : "Original interval unavailable"}.</p>}
    {!!value.measured?.original_cost_groups?.length && <div className="table-scroll"><table className="market-table"><thead><tr><th>Original version / policy</th><th>Closed trades</th><th>Gross / fees / net</th></tr></thead><tbody>{value.measured.original_cost_groups.map((g, i) => <tr key={i}><td>{g.version ?? "Unknown version"}<br />Execution {g.execution_profile ?? "unknown"}; horizon {g.holding_horizon ?? "unknown"}</td><td>{g.trades}</td><td>${number(g.gross_before_recorded_fees_usd)} / ${number(g.fees)} / ${number(g.net_pnl)}</td></tr>)}</tbody></table></div>}
    {value.measured && <p>{value.measured.matched_trial_comparison ? "An original matched trial result is retained in the captured detail." : "No original mature matched trial result is available; this is a closed-event accounting cohort."}</p>}
    {value.rows && <div className="table-scroll"><table className="market-table"><thead><tr><th>Original tick</th><th>Input support</th><th>Why act or wait?</th><th>Evidence</th></tr></thead><tbody>{value.rows.map(row => <tr key={row.reference}><td>{new Date(row.at * 1000).toLocaleString()}<br />Available {row.source_available_at == null ? "unknown" : new Date(row.source_available_at * 1000).toLocaleString()}</td><td>{row.could_evaluate ? "Supported sampled inputs" : row.problems.join(", ")}</td><td>{row.recorded_decision?.reason ?? row.decision_meaning}</td><td><a href={`/api/research/storage/evidence?reference=${encodeURIComponent(row.reference)}`} target="_blank" rel="noreferrer">Original evidence</a></td></tr>)}</tbody></table></div>}
    <h4>Testable hypotheses</h4>{value.hypotheses.length ? <ul>{value.hypotheses.map(h => <li key={h}>{h}</li>)}</ul> : <p>No causal explanation is established by this observation.</p>}
    <h4>Unresolved</h4><ul>{value.unresolved.map(u => <li key={u}>{u}</li>)}</ul><h4>Smallest next question</h4><p>{value.next_question}</p>
    <details><summary>Included, excluded and unknown populations</summary><pre>{JSON.stringify({ population: value.population, problems: value.problem_counts }, null, 2)}</pre></details>
    {value.current_request_counts && <details><summary>Current runtime request counts</summary><p>These restart-scoped observations do not supply missing historical totals. Scheduling checks are not sends; dispatch is not proof of remote receipt.</p><pre>{JSON.stringify(value.current_request_counts, null, 2)}</pre></details>}
  </section>;
}

const ToolResult = memo(function ToolResult({ run }: { run: Run }) {
  const [page, setPage] = useState<EvidencePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { begin, cancel } = useEvidenceRead();
  const selected = useRef(run.id);
  selected.current = run.id;
  useEffect(() => { cancel(); setPage(null); setError(null); setLoading(false); }, [run.id, cancel]);
  const detail = async (cursor?: string | null) => {
    const id = run.id;
    const request = begin(7000);
    const active = () => request.isCurrent() && selected.current === id;
    setLoading(true); setError(null);
    try {
      const response = await fetch(`/api/research/tools/runs/${id}/detail${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`, { cache: "no-store", signal: request.signal });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "Captured detail is unavailable");
      if (active()) setPage(result as EvidencePage);
    } catch (cause) { if (active()) setError(cause instanceof Error ? cause.message : "Captured detail is unavailable; retry."); }
    finally { if (active()) setLoading(false); }
  };
  const result = run.result?.result;
  if (result && (run.tool === "input_diagnosis" || run.tool === "cost_diagnosis")) return <div className="tool-result"><p>{run.symbol} · {run.account} · captured {time(run.started * 1000)} · {run.status}</p><DiagnosisResult value={result as Diagnosis} /><button type="button" disabled={loading} onClick={() => void detail()}>Open captured detail</button>{error && <p role="alert">{error}</p>}{page && <details open><summary>Exact captured diagnosis</summary><pre>{JSON.stringify(page.facts, null, 2)}</pre></details>}<details><summary>Receipt / diagnostics</summary><pre>{JSON.stringify(run, null, 2)}</pre></details></div>;
  let summary = run.status === "running" ? "Reading evidence…" : "Evidence saved. Open the receipt to inspect it.";
  if (run.error) summary = run.error;
  else if ((run.tool === "input_diagnosis" || run.tool === "cost_diagnosis") && result) summary = String(result.summary ?? result.status);
  else if (run.tool === "cost_hurdle" && result) summary = `The bid would need to rise ${number(String(result.required_bid_move_percent), 3)}% to cover modeled round-trip costs at the top of this book. This is a cost threshold, not a forecast.`;
  else if (run.tool === "strategy_evidence" && result) {
    const decision = result.last_decision as { reason?: string } | null;
    summary = decision?.reason ? `Last recorded decision: ${decision.reason}` : "No selected-account decision has been recorded for this market.";
  } else if (run.tool === "outcome_review" && result) {
    const totals = result.market_totals as { trades: number; net_pnl: string; fees: string } | undefined;
    const account = result.account_totals as { net_pnl?: string | null; cash?: string; fresh?: boolean; final?: boolean; final_at?: number } | undefined;
    const basis = account?.final ? `Final historical whole-account net P/L (retired ${new Date(account.final_at! * 1000).toLocaleString()})` : "Whole-account net P/L";
    summary = totals ? `${totals.trades} recorded ${run.symbol.replace(/USD$/, "")} trades: $${number(totals.net_pnl)} net P/L, including $${number(totals.fees)} in fees. ${basis}: ${account?.net_pnl == null ? "unavailable at captured valuation" : `$${number(account.net_pnl)}`}; cash $${number(account?.cash)}. Open holdings and separate-capital comparisons remain in the receipt.` : String(result.reason ?? "Permanent outcome evidence is unavailable.");
  }
  else if (run.tool === "market_evidence" && result) {
    const live = result.live as Live | undefined;
    const detail = result.detail as Detail | undefined;
    const quote = live?.markets.find(q => q.symbol === run.symbol);
    summary = `Quote ${quote?.state ?? "unavailable"} at capture. Saved ${run.result?.envelope?.coverage?.saved_candles ?? detail?.candles.length ?? 0} closed candles and ${run.result?.envelope?.coverage?.saved_trades ?? live?.trades.length ?? 0} observed trades, with the available order book and strategy evidence. Candle and indicator evidence covers up to the latest 120 closed candles for this market; gaps remain visible in the receipt.`;
  }
  return <div className="tool-result" role="status"><div className="tool-result-heading"><strong>{run.symbol.replace(/USD$/, " / USD")} · {run.account ?? "primary"}</strong><span className={run.status === "completed" ? "station-positive" : "station-muted"}>{run.status}</span></div><p>{summary}</p>{run.result?.envelope && <p>Captured {new Date(run.result.envelope.observation_cutoff * 1000).toLocaleString()}. {run.result.envelope.overview_scope}</p>}<button type="button" disabled={loading || run.status !== "completed"} onClick={() => void detail()}>{loading ? "Loading…" : "Open captured detail"}</button>{error && <p role="alert">{error}</p>}{page && <details open><summary>Captured evidence {page.total != null ? `· ${page.total} saved rows` : ""}</summary><pre>{JSON.stringify(page.facts ?? page.events, null, 2)}</pre>{page.next_cursor && <button type="button" disabled={loading} onClick={() => void detail(page.next_cursor)}>Next evidence page</button>}</details>}<details><summary>Receipt / diagnostics</summary><pre>{JSON.stringify(run, null, 2)}</pre></details></div>;
});

export function MarketStation({ strategyOnly = false }: { strategyOnly?: boolean }) {
  const section = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(true);
  const [symbol, setSymbol] = useState(() => savedScope().symbol);
  const [account, setAccount] = useState(() => savedScope().account);
  const [accountPage, setAccountPage] = useState("");
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [qualifiedOnly, setQualifiedOnly] = useState(false);
  const [range, setRange] = useState(60);
  const [clock, setClock] = useState(performance.now());
  const [latest, setLatest] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [toolError, setToolError] = useState<string | null>(null);
  const [diagnosisMinutes, setDiagnosisMinutes] = useState(5);
  const receiptRead = useEvidenceRead();
  const selectedReceipt = useRef<number | null>(null);
  const rememberReceipt = (id: number, replace = false) => {
    localStorage.setItem("qtrades-tool-receipt", String(id));
    const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
    params.set("receipt", String(id));
    const target = `#${strategyOnly ? "strategies" : "markets"}?${params}`;
    if (replace) history.replaceState(null, "", target);
    else history.pushState(null, "", target);
  };
  const livePoll = usePoll<Live>(`/api/station/live?symbol=${symbol}`, strategyOnly ? 10000 : 1000, visible);
  const detailPoll = usePoll<Detail>(`/api/station/detail?symbol=${symbol}&account=${encodeURIComponent(account)}`, 10000, visible);
  const accountsPoll = usePoll<ToolAccounts>(`/api/research/tools/accounts?before=${encodeURIComponent(accountPage)}`, 10000, visible);
  const toolsPoll = usePoll<ToolState>(`/api/research/tools${historyCursor ? `?cursor=${encodeURIComponent(historyCursor)}` : ""}`, 10000, visible);
  const rolesPoll = usePoll<{ enabled: boolean; paper_pilot?: boolean; readiness: { qualification_valid?: boolean; runtime_available?: boolean; reason?: string } }>("/api/lab/roles", 30000, visible);
  const live = livePoll.data?.selected_symbol === symbol ? livePoll.data : null;
  const detail = detailPoll.data?.selected_symbol === symbol && detailPoll.data.strategy.account === account ? detailPoll.data : null;
  const quote = live?.markets.find(q => q.symbol === symbol);
  const elapsed = Math.max(0, clock - livePoll.at);
  const fresh = !!quote && !livePoll.error && live?.running && !live.error && quote.state === "fresh" && elapsed < quote.valid_for_ms;
  const scanner = detailPoll.data?.scan;
  const rows = scanner?.rows.filter(r => r.symbol.includes(search.toUpperCase()) && (!qualifiedOnly || r.eligible)) ?? [];
  const change = scanner?.rows.find(r => r.symbol === symbol)?.change_percent;

  const chooseScope = (market: string, owner: string, candleId?: number) => {
    receiptRead.cancel(); setBusy(false);
    if (busy) setToolError("The earlier read may have finished; check saved runs before retrying.");
    localStorage.setItem("qtrades-tool-symbol", market); localStorage.setItem("qtrades-tool-account", owner);
    const params = new URLSearchParams({ symbol: market, account: owner });
    if (candleId != null) params.set("candle_run", String(candleId));
    if (selectedReceipt.current != null) params.set("receipt", String(selectedReceipt.current));
    location.hash = `${strategyOnly ? "strategies" : "markets"}?${params}`;
    setSymbol(market); setAccount(owner);
  };
  useEffect(() => {
    if (!location.hash.includes("?")) history.replaceState(null, "", `#${strategyOnly ? "strategies" : "markets"}?${new URLSearchParams(savedScope())}`);
    const restore = () => { const scope = savedScope(); setSymbol(scope.symbol); setAccount(scope.account); };
    window.addEventListener("hashchange", restore);
    return () => window.removeEventListener("hashchange", restore);
  }, [strategyOnly]);

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
    const request = receiptRead.begin(7000);
    setBusy(true); setToolError(null);
    try {
      const diagnostic = tool === "input_diagnosis" || tool === "cost_diagnosis";
      const response = await fetch("/api/research/tools/run", { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" }, body: JSON.stringify({ tool, symbol, account, request_id: crypto.randomUUID(), ...(diagnostic ? { start: Date.now() / 1000 - diagnosisMinutes * 60 } : {}) }), signal: request.signal });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "Tool could not run");
      if (request.isCurrent()) { selectedReceipt.current = result.id; setLatest(result as Run); rememberReceipt(result.id); }
    } catch (cause) { if (request.isCurrent()) setToolError(cause instanceof DOMException ? "Tool request was not confirmed; check saved runs before retrying." : cause instanceof Error ? cause.message : "Tool request was not confirmed; check saved runs before retrying."); }
    finally { if (request.isCurrent()) setBusy(false); }
  };
  const openRun = async (id: number, navigate = true) => {
    const request = receiptRead.begin(3000);
    selectedReceipt.current = id;
    setLatest(null); setToolError(null); setBusy(false);
    if (navigate) rememberReceipt(id);
    try {
      const response = await fetch(`/api/research/tools/runs/${id}`, { cache: "no-store", signal: request.signal });
      if (!response.ok) throw new Error("Saved receipt unavailable");
      const result = await response.json() as Run;
      if (result.id !== id) throw new Error("Saved receipt identity differs");
      if (request.isCurrent() && result.tool === "candle_patterns") {
        const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
        params.delete("receipt"); params.set("candle_run", String(id)); params.set("symbol", result.symbol);
        if (localStorage.getItem("qtrades-tool-receipt") === String(id)) localStorage.removeItem("qtrades-tool-receipt");
        location.hash = `markets?${params}`;
        setLatest(null); setToolError(null);
        return;
      }
      if (request.isCurrent() && selectedReceipt.current === id) { setLatest(result); setToolError(null); }
    } catch { if (request.isCurrent()) setToolError("Saved receipt unavailable. The journal has not been reset."); }
  };

  useEffect(() => {
    const restore = () => {
      const id = new URLSearchParams(location.hash.split("?")[1] ?? "").get("receipt");
      if (id && /^\d+$/.test(id)) { if (selectedReceipt.current !== Number(id)) void openRun(Number(id), false); }
      else { receiptRead.cancel(); selectedReceipt.current = null; setLatest(null); setToolError(null); setBusy(false); }
    };
    const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
    const saved = localStorage.getItem("qtrades-tool-receipt");
    if (!params.has("receipt") && saved && /^\d+$/.test(saved)) rememberReceipt(Number(saved), true);
    restore();
    window.addEventListener("hashchange", restore); window.addEventListener("popstate", restore);
    return () => { window.removeEventListener("hashchange", restore); window.removeEventListener("popstate", restore); };
  }, []);

  return <section ref={section} id="live-quotes" className="market-station" aria-labelledby="station-title">
    <header className="station-heading"><div><p>CRYPTO SPOT · PAPER RESEARCH</p><h2 id="station-title">{strategyOnly ? "Strategy evidence" : "Market command station"}</h2></div>{strategyOnly ? <label>Market <select aria-label="Market" value={symbol} onChange={e => chooseScope(e.target.value, account)}>{[...new Set([symbol, "BTCUSD", "ETHUSD", ...(scanner?.selected ?? [])])].map(s => <option key={s}>{s}</option>)}</select></label> : <span className="station-local"><Activity size={14} /> Local workspace</span>}</header>
    {!strategyOnly && <>
    <div className="station-workspace">
      <aside className="station-watchlist" aria-label="Market scanner">
        <div className="station-pane-title"><h3>Markets</h3><span>{scanner?.total ?? "—"} screened</span></div>
        <label className="station-search"><Search size={14} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Find a market" aria-label="Find a market" /></label>
        <label className="station-filter"><input type="checkbox" checked={qualifiedOnly} onChange={e => setQualifiedOnly(e.target.checked)} /> Passed liquidity screen</label>
        <div className="watchlist-labels"><span>Market</span><span>24h</span><span>USD vol.</span></div>
        <div className="watchlist-rows">{rows.map(row => <button type="button" key={row.symbol} onClick={() => chooseScope(row.symbol, account)} className={row.symbol === symbol ? "selected" : ""} aria-pressed={row.symbol === symbol} title={row.reason}><strong>{row.symbol.replace(/USD$/, "")}</strong><span className={Number(row.change_percent) >= 0 ? "station-positive" : "station-negative"}>{row.change_percent == null ? "—" : `${number(row.change_percent)}%`}</span><span>{compact(row.quote_volume)}</span></button>)}</div>
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
          {detail ? <MarketChart bars={detail.candles} range={range} indicators={detail.indicators} stale={detail.candles_stale} symbol={symbol} /> : <div className="station-empty">Loading recorded price history…</div>}
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
    {!strategyOnly && <CandleWorkspace symbol={symbol} savedRuns={toolsPoll.data?.runs ?? []} onChooseMarket={(market, id) => chooseScope(market, account, id)} />}
    {strategyOnly && (detail?.experiments ? <StrategyLab data={detail.experiments} symbol={symbol} unavailable={!!detailPoll.error || live?.running !== true || !!live?.error} /> : <p className="station-empty">{detailPoll.error ?? "Waiting for recorded strategy evidence…"}</p>)}
    <section className="station-tools" aria-label="Research tools">
      <div className="station-pane-title"><h3><Wrench size={15} /> Research tools</h3><span>Read-only · saved results</span></div>
      <label>Evidence account <select aria-label="Evidence account" value={account} onChange={e => chooseScope(symbol, e.target.value)}>
        {!accountsPoll.data?.accounts.some(a => a.account === account) && <option value={account}>{account} · identity awaiting lookup</option>}
        {accountsPoll.data?.accounts.map(a => <option key={a.account} value={a.account}>{a.label || a.account}{a.archived ? " · retired" : ""} · {a.account}</option>)}
      </select></label>
      {accountsPoll.data?.next_before && <button type="button" onClick={() => setAccountPage(accountsPoll.data!.next_before!)}>More retired accounts</button>}
      {accountPage && <button type="button" onClick={() => setAccountPage("")}>First account page</button>}
      {accountsPoll.error && <p role="alert">{accountsPoll.error}</p>}
      <p>New tools use {account}. Saved receipts keep their original account and capture date.</p>
      <label>Diagnosis interval <select aria-label="Diagnosis interval" value={diagnosisMinutes} onChange={e => setDiagnosisMinutes(Number(e.target.value))}>{[5, 15, 30].map(minutes => <option key={minutes} value={minutes}>Last {minutes} minutes</option>)}</select></label>
      <div className="station-tool-buttons">{toolsPoll.data?.tools.filter(tool => tool.id !== "candle_patterns").map(tool => <button key={tool.id} type="button" disabled={busy || (!historicalTools.has(tool.id) && (!detail || live?.running !== true || !!live?.error))} title={tool.purpose} onClick={() => void runTool(tool.id)}>{busy ? "Working…" : tool.name}</button>)}</div>
      {(toolError || toolsPoll.error || toolsPoll.data?.error) && <p className="station-inline-note" role="alert">{toolError || toolsPoll.error || toolsPoll.data?.error}</p>}
      {latest && <ToolResult run={latest} />}
      <div className="station-agents"><span><strong>Local research roles</strong> · {rolesPoll.error ? "Status unavailable" : rolesPoll.data ? rolesPoll.data.paper_pilot ? `Experimental paper pilot · unqualified · worker ${rolesPoll.data.enabled ? "enabled" : "disabled"}` : `Qualification ${rolesPoll.data.readiness.qualification_valid ? "verified" : "unverified"} · runtime ${rolesPoll.data.readiness.runtime_available ? "available" : "unavailable"} · policy ${rolesPoll.data.enabled ? "enabled" : "disabled"}` : "Loading actual status…"}</span><a href="#role-research">View AI Lab <ChevronRight size={13} /></a></div>
      <details className="station-receipts"><summary>Saved tool runs ({toolsPoll.data?.total ?? 0})</summary>
        {toolsPoll.data?.runs.map(run => <button key={run.id} type="button" onClick={() => void openRun(run.id)}>{time(run.started * 1000)} · {run.account ?? "primary"} · {run.symbol} · {toolsPoll.data?.tools.find(t => t.id === run.tool)?.name ?? run.tool}<span>{run.status}</span></button>)}
        {toolsPoll.data?.next_cursor && <button type="button" onClick={() => setHistoryCursor(toolsPoll.data!.next_cursor!)}>Older saved runs</button>}
        {historyCursor && <button type="button" onClick={() => setHistoryCursor(null)}>Newest saved runs</button>}
      </details>
    </section>
    <details className="station-diagnostics"><summary>Evidence / diagnostics</summary><p>Prices refresh about once a second; charts and decisions refresh every ten seconds. Screened markets do not all have active streams. Charts contain closed candles, including bootstrap history; exchange prints are an incomplete recent window.</p><pre>{JSON.stringify({ quote, scan_observed_at: scanner?.observed_at, details_observed_at: detail?.generated_at, trade_gaps: live?.trade_gaps, live_error: livePoll.error, detail_error: detailPoll.error }, null, 2)}</pre></details>
  </section>;
}
