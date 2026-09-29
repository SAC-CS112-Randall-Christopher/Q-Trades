import { useState } from "react";

type OptionsAccount = {
  cash: string; equity: string; funding: string; net_pnl: string; fees: string;
  available_cash: string; unsettled_cash: string; risk_budget: string;
  version: string; closed: number; wins: number; replenishments: number;
  attempt: number; attempt_wins: number; attempt_failures: number;
  valuation_fresh: boolean; last_decision: string;
  positions: Record<string, { entry_day: string; entry: string; exit_blocked?: string }>;
  pending: Record<string, { side: string; created_day: string }>;
};
export type OptionsSnapshot = {
  enabled: boolean; running?: boolean; error?: string | null; paused?: boolean;
  source?: string; mode?: string; market_day?: string | null; sessions?: number;
  contracts_studied?: number; next_review?: number; review_count?: number;
  accounts?: Record<string, OptionsAccount>; feed_status?: string;
  request_budget?: { used: number; limit: number };
  journal?: { balanced: boolean };
  reviews?: { at: number; selected: string; reason: string }[];
  events?: { id: number; kind: string; body: Record<string, unknown> }[];
};
const money = (value: string | undefined) => Number(value ?? 0).toLocaleString("en-US", {
  style: "currency", currency: "USD",
});

export function OptionsPanel({ data, disconnected }: { data?: OptionsSnapshot; disconnected: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!data?.enabled || !data.accounts) return data?.error ? <p role="alert">{data.error}</p> : null;
  const a = data.accounts.primary;
  const latest = data.reviews?.at(-1);
  async function control() {
    setBusy(true); setError(null);
    try {
      const response = await fetch("/api/options/entries", {
        method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" },
        body: JSON.stringify({ action: data?.paused ? "resume" : "pause" }),
        signal: AbortSignal.timeout(7000),
      });
      if (!response.ok) throw new Error();
    } catch { setError("Options entry control was not confirmed. Check fresh account status."); }
    finally { setBusy(false); }
  }
  return <section className="paper-experiment" id="options" aria-label="Separate options paper account">
    <div className="experiment-heading">
      <div><p className="eyebrow">SEPARATE ACCOUNT · CASH-FUNDED OPTIONS</p>
        <h2>Learn the options market.</h2>
        <p>Free historical research. Its own $100, decisions, losses and four-hour reviews.</p></div>
      <span className="pill warning">Historical replay · not live</span>
    </div>
    {(error || data.error || disconnected || !data.running) && <p className="error-banner" role="alert">
      {error || data.error || (disconnected ? "Dashboard disconnected; account status may be old." : "Options research worker is stopped.")}
    </p>}
    <div className="paper-summary">
      <article className="paper-balance"><span>OPTIONS PAPER ACCOUNT · ATTEMPT {a.attempt}</span>
        <strong>{money(a.equity)}</strong>
        <p>{a.valuation_fresh ? "Value at the replayed historical session" : "Incomplete valuation · missing contract evidence"}</p>
        <progress aria-label="Options progress toward $1,000" max={1000} value={Math.max(0, Math.min(1000, Number(a.equity)))} />
        <div className="goal-label"><span>$100 starting capital</span><span>$1,000 research target</span></div>
      </article>
      <div className="paper-numbers">
        <div><span>Net P&amp;L after funding</span><strong>{money(a.net_pnl)}</strong><small>{money(a.funding)} total fake funding</small></div>
        <div><span>Available settled cash</span><strong>{money(a.available_cash)}</strong><small>{money(a.unsettled_cash)} unsettled</small></div>
        <div><span>Completed option trades</span><strong>{a.closed}</strong><small>{a.wins} wins · {money(a.fees)} fees</small></div>
        <div><span>Full premium risk budget</span><strong>{money(a.risk_budget)}</strong><small>2.5% maximum, including costs</small></div>
      </div>
    </div>
    <div className="feed-panel">
      <div className="feed-heading"><div><p className="eyebrow">FREE DATA · $0 SUBSCRIPTION</p><h3>What it is studying</h3></div>
        <button className="button secondary" disabled={busy || disconnected} onClick={control}>
          {busy ? "Saving…" : data.paused ? "Resume options entries" : "Pause options entries"}
        </button>
      </div>
      <p>{data.source}. Replayed through <strong>{data.market_day ?? "waiting for the first session"}</strong>.</p>
      <div className="feed-markets">
        <article><strong>{data.sessions ?? 0} historical sessions</strong><span>{data.contracts_studied ?? 0} contract observations studied</span></article>
        <article><strong>{data.review_count ?? 0} four-hour reviews</strong><span>Next: {data.next_review ? new Date(data.next_review * 1000).toLocaleTimeString("en-US", { timeZone: "America/Denver", hour: "numeric", minute: "2-digit" }) : "—"} Denver</span></article>
        <article><strong>{data.request_budget?.used ?? 0} / {data.request_budget?.limit ?? 60} requests today</strong><span>Bounded collection · no API key or broker account</span></article>
      </div>
      <p><strong>Latest decision:</strong> {a.last_decision}</p>
      <p>{data.feed_status}</p>
      <p><strong>Learning:</strong> {latest?.reason ?? "Collecting distinct historical sessions. No strategy promotion has been justified."}</p>
      <p className="fine-print">Actual historical bid/ask, sizes, volume and open interest. AAPL only;
        end-of-day snapshots do not support intraday timing. Historical Greeks and implied volatility
        are unavailable. Results cannot be ranked directly against the spot account’s different dates.</p>
    </div>
    <div className="feed-panel"><h3>Positions, decisions &amp; history</h3>
      {!Object.keys(a.positions).length && !Object.keys(a.pending).length && <p>No open option or pending order. The account does not force a trade to produce activity.</p>}
      {Object.entries(a.positions).map(([symbol, p]) => <p key={symbol}><strong>{symbol}</strong> · one purchased contract · opened {p.entry_day}{p.exit_blocked && ` · ${p.exit_blocked}`}</p>)}
      {Object.entries(a.pending).map(([symbol, p]) => <p key={symbol}>{p.side.toUpperCase()} {symbol} · awaiting a later session’s quote</p>)}
      <details><summary>Compare the options research variants</summary>
        {Object.entries(data.accounts).filter(([name]) => name !== "primary").map(([name, account]) => <p key={name}><strong>{name}</strong> · {money(account.equity)} · {account.closed} closed trades · separate fake funding</p>)}
      </details>
      <p><a href="/api/options/journal?limit=1000">Open options journal</a> · {data.journal?.balanced ? "Ledger reconciled" : "Ledger needs attention"}</p>
      <p className="fine-print">Purchased calls/puts only. A standard contract represents 100 shares;
        the simulation charges $0.50 per contract per side. Fills require a later session’s bid/ask
        and sufficient quoted size. Proceeds wait until the next observed session. An unresolved
        expiry freezes the position. No broker orders or stock exercise are sent.</p>
      <p className="fine-print">{a.attempt_wins} target successes · {a.attempt_failures} failed attempts · {a.replenishments} replenishments.
        Below $5: record the failure, reconcile a flat settled account, then restore $100.
        All earlier losses stay in the record.</p>
    </div>
  </section>;
}
