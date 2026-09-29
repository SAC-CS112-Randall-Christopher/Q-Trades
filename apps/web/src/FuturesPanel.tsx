export type FuturesRow = {
  status: "observed" | "unavailable" | "stale";
  reason?: string;
  contract?: string;
  base?: string;
  premium_bps?: string;
  open_interest_base?: string;
  open_interest_change_pct?: string | null;
  change_interval_seconds?: number | null;
  funding_est_bps_hour?: string;
  funding_direction?: string;
  age_seconds?: number;
};

export type FuturesSnapshot = {
  enabled: boolean;
  poll_seconds: number;
  error: string | null;
  markets: Record<string, FuturesRow>;
};

const numeric = (value: string | number | undefined | null, digits = 2) =>
  value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });

export function FuturesPanel({ data }: { data?: FuturesSnapshot }) {
  if (!data?.enabled) return null;
  const markets = Object.entries(data.markets);
  const observed = markets.filter(([, row]) => row.status === "observed").length;
  return <section className="feed-panel" aria-label="Futures market context">
    <div className="feed-heading">
      <div><p className="eyebrow">MARKET CONTEXT · OBSERVATION ONLY</p>
        <h3>What are futures showing?</h3></div>
      <span className={`pill ${observed ? "paper" : "caution"}`}>{observed} current observations</span>
    </div>
    <p>Kraken perpetual futures, sampled every {data.poll_seconds} seconds. These observations
      are recorded alongside paper trades and included in four-hour reviews.</p>
    <div className="feed-markets">{markets.map(([symbol, row]) => <article key={symbol}>
      <strong>{symbol.replace(/USD$/, "")} · futures context</strong>
      {row.status === "observed" ? <>
        <span>Mark vs index: {numeric(row.premium_bps)} bps</span>
        <span>Funding: {row.funding_direction} · ~{numeric(Number(row.funding_est_bps_hour) / 100, 5)}% / hour</span>
        <span>Open interest: {numeric(row.open_interest_base, 1)} {row.base}</span>
        <span>{row.open_interest_change_pct == null ? "Open-interest change: awaiting comparison" :
          `Change: ${numeric(row.open_interest_change_pct)}% over ${numeric(row.change_interval_seconds, 0)}s`}</span>
        <span>Observed {numeric(row.age_seconds, 0)}s ago · {row.contract}</span>
      </> : <span>{row.status === "stale" ? "Stale" : "Unavailable"}: {row.reason}</span>}
    </article>)}</div>
    {!markets.length && <p>Waiting for the first public futures observation.</p>}
    {data.error && <p className="feed-warning">{data.error}</p>}
    <p className="fine-print">One venue’s positioning is only part of the market. Funding is
      approximately normalized to the current index; predicted rates are not realized payments.
      Futures cannot place orders or change the running strategy. Liquidations, CME futures and
      options-chain data are not connected.</p>
  </section>;
}
