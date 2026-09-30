import { PaperEconomicsPanel, type EconomicsSnapshot, type ExecutionProfile } from "./PaperEconomicsPanel";
import { useState } from "react";
import { PaperRiskPanel, type RiskStatus } from "./PaperRiskPanel";
import { PaperCampaignPanel } from "./PaperCampaignPanel";
import { LearningPanel, type Learning } from "./LearningPanel";
import { FeedPanel, type FeedDetails } from "./FeedPanel";
import { FuturesPanel, type FuturesSnapshot } from "./FuturesPanel";
import {
  ArrowDownToLine,
  Clock3,
  FlaskConical,
  Pause,
  Play,
  Target,
} from "lucide-react";

type Position = {
  quantity: string;
  entry: string;
  stop: string;
  version: string;
  opened_at: number;
  exit_blocked?: string;
};
type Decision = { symbol: string; at: number; reason: string; version: string };
export type Account = {
  label?: string;
  campaign_id?: string;
  entries_paused?: boolean;
  control_version?: number;
  fault?: { at: number; code: string; reason: string };
  starting_capital?: string;
  risk?: RiskStatus;
  cash: string;
  equity: string;
  funding: string;
  net_pnl: string;
  fees: string;
  max_drawdown: string;
  valuation_fresh: boolean;
  version: string;
  closed: number;
  wins: number;
  replenishments: number;
  cooldown_until: number;
  daily_pause: boolean;
  drawdown_pause: boolean;
  failure_pending: boolean;
  positions: Record<string, Position>;
  pending: Record<string, { side: string; quantity: string }>;
  last_decision: Record<string, Decision>;
  attempt: { number: number; started_at: number; outcome: string };
};
type Review = {
  at: number;
  reason: string;
  selected: string;
  primary_net_pnl: string;
};
type Event = {
  id: number;
  at: number;
  kind: string;
  body: Record<string, unknown>;
};
export type PaperSnapshot = Partial<FeedDetails> & {
  research_evidence?: import("./EvidencePanel").EvidenceStatus;
  economics?: EconomicsSnapshot;
  execution_profiles?: ExecutionProfile[];
  futures_context?: FuturesSnapshot;
  enabled: boolean;
  running: boolean;
  error: string | null;
  stale: boolean;
  paused: boolean;
  feed_errors: Record<string, string>;
  started_at: number;
  next_review: number;
  review_count: number;
  reviews: Review[];
  promotions: number;
  bars_studied: number;
  gaps: number;
  accounts: Record<string, Account>;
  campaigns?: { id: string; name: string; accounts: string[]; created_at: number }[];
  learning?: Learning;
  events: Event[];
  journal: { balanced?: boolean };
  repeatability: {
    won: number;
    failed: number;
    open: number;
    conclusion: string;
  };
  features: Record<
    string,
    Record<
      string,
      {
        atr?: string;
        volume_ratio?: string;
        trend_up?: boolean;
        reason: string;
      }
    >
  >;
  cost_model: string;
  sampling: string;
};

const money = (value: string | number) =>
  Number(value).toLocaleString("en-US", { style: "currency", currency: "USD" });
const when = (value: number) =>
  new Date(value * 1000).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Denver",
  });

function eventDescription(event: Event) {
  const b = event.body;
  if (event.kind === "initial_funding")
    return `Started with ${money(String(b.amount))} in fake USD`;
  if (event.kind === "fill")
    return `${String(b.side).toUpperCase()} ${b.filled_quantity} ${b.symbol} at ${money(String(b.vwap))} · fee ${money(String(b.fee))}${b.partial ? " · partial fill" : ""}`;
  if (event.kind === "trade_closed")
    return `${b.symbol} · net ${money(String(b.pnl))} · ${b.reason}`;
  if (event.kind === "replenishment")
    return `Added ${money(String(b.amount))} after failure review · lifetime fake funding ${money(String(b.total_funding))}`;
  if (event.kind === "failure_review") return String(b.action);
  if (event.kind === "drawdown_stop") return `Drawdown stop at ${money(String(b.equity))}; risk reference ${money(String(b.risk_reference))}`;
  if (event.kind === "risk_policy_changed" || event.kind === "risk_recovered") return String(b.reason);
  if (event.kind === "attempt_won")
    return "$1,000 target reached in this attempt";
  if (event.kind === "attempt_failed")
    return "Attempt ended below $5; loss remains in the record";
  if (event.kind === "entry_control")
    return b.paused
      ? "New entries paused; existing positions still managed"
      : "New entries resumed";
  return String(b.reason ?? b.note ?? event.kind.replaceAll("_", " "));
}

export function PaperPanel({
  data,
  disconnected,
  integrated = true,
}: {
  data: PaperSnapshot | undefined;
  disconnected: boolean;
  integrated?: boolean;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!data?.enabled) return null;
  const a = data.accounts.primary;
  const stale = data.stale || disconnected;
  const latest = data.reviews.at(-1);
  const halted =
    data.paused ||
    a.risk?.blocked ||
    a.daily_pause ||
    a.drawdown_pause ||
    a.failure_pending ||
    a.cooldown_until > Date.now() / 1000;
  const feedDegraded = !!data.error || Object.keys(data.feed_errors).length > 0;
  const state =
    stale || !data.running
      ? "Needs attention"
      : feedDegraded
        ? "Feed degraded"
        : halted
          ? "Entries paused"
          : "Studying & scanning";
  async function control() {
    if (!data) return;
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/api/paper/entries", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Local-Operator": "1",
        },
        body: JSON.stringify({ action: data.paused ? "resume" : "pause" }),
        signal: AbortSignal.timeout(7000),
      });
      if (!response.ok) throw new Error();
    } catch {
      setError(
        "Entry control was not confirmed. Wait for a fresh account status.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <section
      className="paper-experiment"
      id="experiment"
      aria-label="Tier 3 paper experiment"
    >
      <div className="experiment-heading">
        <div>
          <p className="eyebrow">ACTIVE EXPERIMENT / TIER 03</p>
          <h2>Can {money(a.starting_capital ?? "100")} become $1,000?</h2>
          <p>
            Continuous paper trading. A permanent record of what works, what
            fails, and what changes.
          </p>
        </div>
        <span
          className={`pill ${stale || halted || feedDegraded ? "warning" : "success"}`}
        >
          {state}
        </span>
      </div>
      {(error || data.error || Object.keys(data.feed_errors).length > 0) && (
        <div className="error-banner" role="alert">
          {error ||
            data.error ||
            Object.entries(data.feed_errors)
              .map(([s, e]) => `${s}: ${e}`)
              .join(" · ")}
        </div>
      )}
      <div className="paper-summary">
        <article className="paper-balance">
          <span>PRIMARY PAPER ACCOUNT · ATTEMPT {a.attempt.number}</span>
          <strong>{money(a.equity)}</strong>
          <p>
            {a.valuation_fresh && !stale
              ? "Estimated liquidation value after exit costs"
              : "Last valuation · waiting for fresh, complete data"}
          </p>
          <progress
            aria-label="Progress toward $1,000 target"
            max={1000}
            value={Math.min(1000, Number(a.equity))}
          />
          <div className="goal-label">
            <span>{money(a.starting_capital ?? "100")} starting capital</span>
            <span>
              <Target size={13} /> $1,000 target
            </span>
          </div>
        </article>
        <div className="paper-numbers">
          <div>
            <span>Lifetime net P&L</span>
            <strong>{a.valuation_fresh && !stale ? money(a.net_pnl) : "Mark unavailable"}</strong>
            <small>After all fake funding</small>
          </div>
          <div>
            <span>Available + reserved cash</span>
            <strong>{money(a.cash)}</strong>
            <small>Owned positions valued separately</small>
          </div>
          <div>
            <span>Lifetime fake funding</span>
            <strong>{money(a.funding)}</strong>
            <small>{a.replenishments} replenishments</small>
          </div>
          <div>
            <span>Closed trades / wins</span>
            <strong>
              {a.closed} / {a.wins}
            </strong>
            <small>{money(a.fees)} modeled fees</small>
          </div>
          <div>
            <span>Largest drawdown</span>
            <strong>{(Number(a.max_drawdown) * 100).toFixed(2)}%</strong>
            <small>Funding adjusted · retained across attempts</small>
          </div>
          <div>
            <span>Account attempts</span>
            <strong>
              {data.repeatability.won} won · {data.repeatability.failed} failed
            </strong>
            <small>
              {data.repeatability.open} unresolved · majority not established
            </small>
          </div>
        </div>
      </div>
      <div className="paper-controls">
        <p>
          <strong>{a.version}</strong> ·{" "}
          {data.journal.balanced
            ? "Journal reconciled"
            : "Reconciliation pending"}
          {a.daily_pause ? " · Daily loss pause until next UTC day" : ""}
          {a.drawdown_pause ? " · Drawdown review required" : ""}
          {a.cooldown_until > Date.now() / 1000
            ? ` · Entry cooldown until ${when(a.cooldown_until)}`
            : ""}
        </p>
        <button
          className="button secondary small"
          disabled={pending || stale}
          onClick={() => void control()}
        >
          {data.paused ? <Play size={14} /> : <Pause size={14} />}
          {pending
            ? "Confirming…"
            : data.paused
              ? "Clear global entry pause"
              : "Pause all paper entries"}
        </button>
      </div>
      {integrated && <>
      <PaperCampaignPanel data={data} unavailable={stale || !data.running || !!data.error} />
      <LearningPanel data={data.learning} unavailable={stale || !data.running || !!data.error} />
      <PaperRiskPanel accounts={Object.fromEntries(Object.entries(data.accounts).filter(([, a]) => !a.campaign_id))} unavailable={stale || !data.running || !!data.error} />
      <PaperEconomicsPanel data={data.economics} profiles={data.execution_profiles} unavailable={stale || !data.running || !!data.error} />
      </>}
      <div className="learning-grid">
        <article className="learning-card">
          <Clock3 size={20} />
          <p className="eyebrow">REVIEW EVERY FOUR HOURS</p>
          <h3>
            {when(data.next_review)} <small>Denver</small>
          </h3>
          <p>
            {data.review_count} reviews · {data.promotions} evidence-based
            version changes
          </p>
          <p>
            {latest
              ? latest.reason
              : "Collecting the first forward outcomes. No review or strategy success claimed yet."}
          </p>
          <p className="fine-print">
            {a.risk?.legacy
              ? "Historical review and replenishment rules apply to this account."
              : "Scheduled review cannot lift a hard stop or add funds. Recovery retains the original loss limit."}
          </p>
        </article>
        <article className="learning-card">
          <FlaskConical size={20} />
          <p className="eyebrow">WHAT IT IS STUDYING</p>
          <h3>{data.bars_studied.toLocaleString()} closed bars recorded</h3>
          {Object.entries(a.last_decision).map(([symbol, decision]) => (
            <p key={symbol}>
              <strong>{symbol}</strong> · {decision.reason}
            </p>
          ))}
          {!Object.keys(a.last_decision).length && (
            <p>Warming trend, volatility, volume, and breakout features.</p>
          )}
          <p className="fine-print">
            Three frozen variants and a paired BTC/ETH versus wider-market
            comparison use separate paper accounts. No LLM calls.
          </p>
        </article>
      </div>
      <details className="paper-diagnostics">
        <summary>Feed, storage &amp; performance diagnostics</summary>
        <FeedPanel data={data} />
      </details>
      <FuturesPanel data={data.futures_context} />
      <div className="paper-tables">
        <h3>Open positions & pending orders</h3>
        {!Object.keys(a.positions).length && !Object.keys(a.pending).length ? (
          <p className="empty-state">
            No open position or pending order. Entries require a qualifying
            signal and available risk capacity.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="market-table">
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Quantity</th>
                  <th>Entry</th>
                  <th>Stop trigger</th>
                  <th>Opened / status</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(a.positions).map(([symbol, p]) => (
                  <tr key={symbol}>
                    <td>{symbol}</td>
                    <td>{p.quantity}</td>
                    <td>{money(p.entry)}</td>
                    <td>{money(p.stop)}</td>
                    <td>{p.exit_blocked || when(p.opened_at)}</td>
                  </tr>
                ))}
                {Object.entries(a.pending).map(([symbol, p]) => (
                  <tr key={`${symbol}-pending`}>
                    <td>{symbol}</td>
                    <td>{p.quantity}</td>
                    <td colSpan={3}>
                      Pending {p.side} · waiting for a subsequent executable
                      book
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <details>
          <summary>Compare the paper experiments</summary>
          <p className="fine-print">
            Separate hypothetical portfolios on the same data. These are
            correlated experiments, not three independent successes.
          </p>
          <div className="table-scroll">
            <table className="market-table">
              <thead>
                <tr>
                  <th>Frozen variant</th>
                  <th>Equity</th>
                  <th>Net P&L</th>
                  <th>Closed trades</th>
                  <th>Refills</th><th>Entry status</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.accounts)
                  .filter(([name]) => name !== "primary")
                  .map(([name, s]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td>{s.valuation_fresh ? money(s.equity) : "Mark unavailable"}</td>
                      <td>{s.valuation_fresh ? money(s.net_pnl) : "Not available"}</td>
                      <td>{s.closed}</td>
                      <td>{s.replenishments}</td><td>{s.risk?.reason ?? "Risk status unavailable"}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </details>
        <div className="paper-log-heading">
          <h3>Trades, reviews & funding</h3>
          <a
            className="button secondary small"
            href="/api/paper/journal?limit=1000"
          >
            <ArrowDownToLine size={14} /> Journal page
          </a>
        </div>
        <ol className="paper-events">
          {data.events.slice(0, 15).map((event) => (
            <li key={event.id}>
              <span className="paper-event-kind">
                {event.kind.replaceAll("_", " ")}
              </span>
              <p>{eventDescription(event)}</p>
              <time>{when(event.at)}</time>
            </li>
          ))}
        </ol>
        <p className="fine-print">
          Latest {Math.min(15, data.events.length)} primary events. Full journal
          is retained; export pages include a continuation cursor. No trade is
          manufactured to make the log look active.
        </p>
      </div>
      <div className="paper-policy">
        <strong>
          {a.risk?.legacy
            ? "Historical policy: below-$5 failure review may restore paper funding to $100."
            : "Hard-stop policy: preserve losses, do not refill accounts, and retain the original loss limit."}
        </strong>
        <p>
          Equity includes owned positions. All earlier losses remain visible.{" "}
          {data.cost_model}. {data.sampling}.
        </p>
        <p>
          Keep this computer and Docker running. Closing this dashboard does not
          stop the program. Results describe this simulation, not live
          execution.
        </p>
      </div>
    </section>
  );
}
