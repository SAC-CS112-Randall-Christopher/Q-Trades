import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import type { PaperSnapshot } from "./PaperPanel";

type Trade = {
  id: string; event_id: number | null; account: string; label: string; archived: boolean;
  symbol: string; status: "open" | "closed"; opened_at: number; closed_at: number | null;
  version: string | null; reason: string | null; quantity: string | null;
  entry_price: string | null; close_price: string | null; mark_price: string | null;
  mark_at: number | null; pnl: string | null; return_fraction: string | null;
  cost: string | null; proceeds: string | null; fees: string | null;
  unrealized_pnl?: string | null; partial_realized_pnl?: string | null; price_reason: string | null;
};
type Page = {
  records: Trade[]; has_more: boolean; next_before: number; before: number;
  observed_at: number; revision: number; open_count: number; closed_count: number;
};
const amount = (value: string | null | undefined, signed = false, price = false) =>
  value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toLocaleString("en-US", {
    style: "currency", currency: "USD", minimumFractionDigits: 2,
    maximumFractionDigits: price ? 8 : 4, signDisplay: signed ? "exceptZero" : "auto",
  });
const percent = (value: string | null) => value == null || !Number.isFinite(Number(value))
  ? "—" : `${Number(value) > 0 ? "+" : ""}${(Number(value) * 100).toFixed(2)}%`;
const when = (value: number | null) => value == null ? "—" : new Date(value * 1000)
  .toLocaleString("en-US", { timeZone: "America/Denver", month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", second: "2-digit" });
const rowWhen = (value: number | null) => value == null ? "—" : new Date(value * 1000)
  .toLocaleString("en-US", { timeZone: "America/Denver", month: "2-digit", day: "2-digit", year: "numeric",
    hour: "numeric", minute: "2-digit" });

export function TradeHistory({ paper, unavailable }: { paper: PaperSnapshot; unavailable: boolean }) {
  const [account, setAccount] = useState("");
  const [status, setStatus] = useState("all");
  const [cursors, setCursors] = useState<number[]>([0]);
  const [page, setPage] = useState<Page | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [expanded, setExpanded] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clock, setClock] = useState(Date.now() / 1000);
  const sequence = useRef(0);
  const before = cursors[cursors.length - 1];

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (before || pending) return;
    // Keep current open estimates inside the existing five-second book validity.
    const interval = status === "closed" || page?.open_count === 0 ? 10000 : 3000;
    const timer = window.setInterval(() => setRefresh(value => value + 1), interval);
    return () => window.clearInterval(timer);
  }, [before, status, pending, page?.open_count]);
  useEffect(() => {
    const controller = new AbortController();
    const request = ++sequence.current;
    setPending(true);
    const query = new URLSearchParams({ before: String(before), limit: "50", status });
    if (account) query.set("account", account);
    void (async () => {
      try {
        const response = await fetch(`/api/paper/trades?${query}`, {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(7000)]),
        });
        if (!response.ok) throw new Error("Trade history could not load. Retry when connected.");
        const result = await response.json() as Page;
        if (request === sequence.current && !controller.signal.aborted) {
          setPage(result); setError(null);
        }
      } catch (failure) {
        if (!controller.signal.aborted && request === sequence.current) {
          setError(failure instanceof Error ? failure.message : "Trade history could not load.");
        }
      } finally {
        if (request === sequence.current && !controller.signal.aborted) setPending(false);
      }
    })();
    return () => controller.abort();
  }, [account, status, before, refresh]);

  function reset() { setPage(null); setError(null); setCursors([0]); setExpanded(""); }
  const options = new Map(Object.entries(paper.accounts).map(([name, saved]) => [name, saved.label ?? name]));
  for (const trade of page?.records ?? []) options.set(trade.account, trade.label);
  if (account && !options.has(account)) options.set(account, account);

  return <section className="workspace-card trade-history">
    <div className="card-heading">
      <div><h2>Trade history</h2><p>One row per trade · newest activity first · paper only</p></div>
      <button className="button secondary small" disabled={pending} onClick={() => setRefresh(value => value + 1)}>
        <RefreshCw size={13} /> Refresh
      </button>
    </div>
    <div className="trade-history-toolbar">
      <label>Trade account <select value={account} onChange={event => { reset(); setAccount(event.target.value); }}>
        <option value="">All accounts</option>
        {[...options].map(([name, label]) => <option key={name} value={name}>{label}</option>)}
      </select></label>
      <label>Trade status <select value={status} onChange={event => { reset(); setStatus(event.target.value); }}>
        <option value="all">Open &amp; closed</option><option value="open">Open only</option>
        <option value="closed">Closed only</option>
      </select></label>
      <span>{before ? "Older retained trades" : status === "open" ? "All current positions"
        : status === "closed" ? "50 newest closed trades" : "All current positions and the 50 newest closed trades"}</span>
    </div>
    {unavailable && <p className="error-banner">Worker status is unconfirmed. Retained closed results remain historical; open estimates are unavailable.</p>}
    {error && <p className="error-banner" role="alert">{error}</p>}
    {pending && !page && <p role="status">Loading trade history…</p>}
    {page && !error && <>
      <div className="table-scroll"><table className="market-table trade-history-table" aria-label="Paper trade history">
        <thead><tr><th>Account</th><th>Market</th><th>Status</th><th>Entry price</th>
          <th>Close price</th><th>Net P/L · USD / %</th><th>Opened · MT</th><th>Closed · MT</th><th>Details</th>
        </tr></thead>
        <tbody>{page.records.map(trade => {
          const open = trade.status === "open";
          const markOld = open && (trade.mark_at == null || clock - trade.mark_at > 5 || unavailable);
          const pnl = markOld ? null : trade.pnl;
          const tone = open ? "trade-open" : pnl == null || Number(pnl) === 0 ? "trade-flat"
            : Number(pnl) > 0 ? "trade-gain" : "trade-loss";
          const state = open ? "Open" : pnl == null ? "Closed" : Number(pnl) > 0 ? "Closed · gain"
            : Number(pnl) < 0 ? "Closed · loss" : "Closed · flat";
          const visible = expanded === trade.id;
          return <TradeRows key={trade.id} trade={trade} tone={tone} state={state} pnl={pnl}
            markOld={markOld} visible={visible} toggle={() => setExpanded(visible ? "" : trade.id)} />;
        })}</tbody>
      </table></div>
      {!page.records.length && <p className="empty-state">No {status === "all" ? "retained" : status} trades in the selected accounts.</p>}
      <div className="trade-history-pagination">
        <span>{page.open_count} open · {page.closed_count} closed on this page{page.has_more ? " · older trades available" : " · end of retained trades"}</span>
        <div><button className="button secondary small" disabled={pending || cursors.length === 1}
          onClick={() => { setPage(null); setExpanded(""); setCursors([0]); }}>Latest</button>
          <button className="button secondary small" disabled={pending || cursors.length === 1}
            onClick={() => { setPage(null); setExpanded(""); setCursors(values => values.slice(0, -1)); }}>
            <ChevronLeft size={13} /> Newer
          </button>
          <button className="button secondary small" disabled={pending || !page.has_more}
            onClick={() => { setPage(null); setExpanded(""); setCursors(values => [...values, page.next_before]); }}>
            Older <ChevronRight size={13} />
          </button></div>
      </div>
      <p className="fine-print">Read at {when(page.observed_at)} MT. Open estimates expire when their book is stale.
        Older pages stay in place until you choose Latest or Refresh.</p>
    </>}
    <p className="fine-print">Net P/L includes entry and exit fees. Percent uses the original entry cost.
      Partial exits share one trade row; close price is their quantity-weighted average.
      Account operating charges are shown in account economics. The Journal tab retains the complete event history.</p>
  </section>;
}

function TradeRows({ trade, tone, state, pnl, markOld, visible, toggle }: {
  trade: Trade; tone: string; state: string; pnl: string | null; markOld: boolean;
  visible: boolean; toggle: () => void;
}) {
  const open = trade.status === "open";
  const note = [trade.reason, markOld ? "Fresh executable mark unavailable; the position remains open."
    : trade.price_reason].filter(Boolean).join(" · ");
  return <>
    <tr className={tone}>
      <td className="trade-account" title={trade.account}>{trade.label}{trade.archived && <span className="trade-archived">Retired</span>}</td>
      <td>{trade.symbol.replace(/USD$/, " / USD")}</td>
      <td><span className="trade-status">{state}</span></td>
      <td title={trade.entry_price ?? trade.price_reason ?? "Unavailable"}>{amount(trade.entry_price, false, true)}</td>
      <td title={open ? "Still open; no closing fill" : trade.close_price ?? trade.price_reason ?? "Unavailable"}>
        {open ? "—" : amount(trade.close_price, false, true)}
      </td>
      <td className="trade-result" title={pnl ?? trade.price_reason ?? "Unavailable"}>
        {pnl == null ? "Unavailable" : <>{amount(pnl, true)} <span>/ {percent(trade.return_fraction)}</span></>}
        {open && <span className="trade-estimate">{pnl == null ? "Awaiting fresh mark" : "Est. net"}</span>}
      </td>
      <td title={when(trade.opened_at)}>{rowWhen(trade.opened_at)}</td>
      <td title={when(trade.closed_at)}>{rowWhen(trade.closed_at)}</td>
      <td><button className="trade-detail-button" aria-expanded={visible}
        aria-controls={`detail-${trade.id}`} aria-label={`Details for ${trade.account} ${trade.symbol} trade ${trade.id}`}
        onClick={toggle}><ChevronDown size={14} /></button></td>
    </tr>
    {visible && <tr className="trade-detail-row"><td colSpan={9} id={`detail-${trade.id}`}>
      <dl className="trade-breakdown">
        <div><dt>Account identity</dt><dd>{trade.account}</dd></div>
        <div><dt>Frozen strategy</dt><dd>{trade.version ?? "Unavailable"}</dd></div>
        <div><dt>{open ? "Remaining quantity" : "Entry quantity"}</dt><dd>{trade.quantity ?? "Unavailable"}</dd></div>
        <div><dt>Original entry cost</dt><dd>{amount(trade.cost)}</dd></div>
        <div><dt>Received exit proceeds</dt><dd>{amount(trade.proceeds)}</dd></div>
        <div><dt>Paid entry / exit fees</dt><dd>{amount(trade.fees)}</dd></div>
        {open && <>
          <div><dt>Partial realized P/L</dt><dd>{amount(trade.partial_realized_pnl, true)}</dd></div>
          <div><dt>Remaining unrealized P/L</dt><dd>{markOld ? "Unavailable" : amount(trade.unrealized_pnl, true)}</dd></div>
          <div><dt>Estimated liquidation price</dt><dd>{markOld ? "Unavailable" : amount(trade.mark_price, false, true)}</dd></div>
          <div><dt>Estimate observed · MT</dt><dd>{when(trade.mark_at)}</dd></div>
        </>}
      </dl>
      {note && <p>{note}</p>}
      {open && <p>Estimated net result combines realized partial exits with liquidation of the remaining holding, including estimated exit fees. It is not a completed trade.</p>}
    </td></tr>}
  </>;
}
