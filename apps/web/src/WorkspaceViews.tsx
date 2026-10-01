import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  BrainCircuit,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  FileClock,
  Pause,
  Play,
  Plus,
  Search,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import type { Account, PaperSnapshot } from "./PaperPanel";
import { PaperCampaignPanel } from "./PaperCampaignPanel";
import { PaperCampaignJournal } from "./PaperCampaignJournal";
import { TradeHistory } from "./TradeHistory";

const money = (value: string | number | null | undefined) =>
  value == null || !Number.isFinite(Number(value))
    ? "—"
    : Number(value).toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
      });
const percent = (value: string | number | null | undefined) =>
  value == null || !Number.isFinite(Number(value))
    ? "—"
    : `${(Number(value) * 100).toFixed(2)}%`;
const stamp = (seconds: number) =>
  new Date(seconds * 1000).toLocaleString("en-US", {
    timeZone: "America/Denver",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
type Status = "active" | "paused" | "attention";
function accountState(
  a: Account,
  paper: PaperSnapshot,
  unavailable: boolean,
): { key: Status; label: string } {
  if (unavailable) return { key: "attention", label: "Unconfirmed" };
  if (a.fault || a.failure_pending || a.drawdown_pause)
    return {
      key: "attention",
      label: a.fault
        ? "Processing stopped"
        : a.failure_pending
          ? "Failed; retained"
          : "Hard stop",
    };
  if (
    paper.paused ||
    a.entries_paused ||
    a.daily_pause ||
    a.cooldown_until > Date.now() / 1000
  )
    return {
      key: "paused",
      label: paper.paused
        ? "Global pause"
        : a.entries_paused
          ? "Paused"
          : a.daily_pause
            ? "Daily loss pause"
            : "Cooldown",
    };
  if (!a.valuation_fresh || a.risk?.blocked)
    return {
      key: "attention",
      label: !a.valuation_fresh ? "Mark unavailable" : "Entries blocked",
    };
  return { key: "active", label: "Scanning" };
}
function totals(paper?: PaperSnapshot, unavailable = true) {
  const accounts = Object.values(paper?.accounts ?? {});
  const confirmed =
    !!accounts.length &&
    !unavailable &&
    accounts.every((a) => a.valuation_fresh);
  const sum = (key: "equity" | "net_pnl" | "fees" | "funding") =>
    accounts.reduce((total, a) => total + Number(a[key]), 0);
  return {
    count: accounts.length,
    confirmed,
    equity: confirmed ? sum("equity") : null,
    pnl: confirmed ? sum("net_pnl") : null,
    fees: accounts.length ? sum("fees") : null,
    funding: accounts.length ? sum("funding") : null,
    active: paper
      ? accounts.filter(
          (a) => accountState(a, paper, unavailable).key === "active",
        ).length
      : 0,
    paused: paper
      ? accounts.filter(
          (a) => accountState(a, paper, unavailable).key === "paused",
        ).length
      : 0,
    attention: paper
      ? accounts.filter(
          (a) => accountState(a, paper, unavailable).key === "attention",
        ).length
      : 0,
  };
}
function EmptyPaper() {
  return (
    <div className="workspace-empty">
      <Wallet size={28} />
      <h2>No paper account status yet</h2>
      <p>
        Account records will appear when the local paper worker is enabled and
        connected.
      </p>
    </div>
  );
}

export function GlobalEntryControl({
  paper,
  unavailable,
}: {
  paper: PaperSnapshot;
  unavailable: boolean;
}) {
  const [pending, setPending] = useState(false);
  const [accepted, setAccepted] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  const waiting = accepted !== null && paper.paused !== accepted;
  async function control() {
    setPending(true);
    setError("");
    try {
      const response = await fetch("/api/paper/entries", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Local-Operator": "1",
        },
        body: JSON.stringify({ action: paper.paused ? "resume" : "pause" }),
        signal: AbortSignal.timeout(7000),
      });
      if (!response.ok)
        throw new Error(
          "Entry control was not confirmed. Wait for refreshed status.",
        );
      setAccepted(!paper.paused);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Entry control was not confirmed.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="global-control">
      <button
        className="button secondary"
        disabled={pending || waiting || unavailable}
        onClick={() => void control()}
      >
        {paper.paused ? <Play size={15} /> : <Pause size={15} />}
        {pending || waiting
          ? "Waiting for status…"
          : paper.paused
            ? "Clear global entry pause"
            : "Pause all paper entries"}
      </button>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}

function AccountDistribution({
  paper,
  unavailable,
}: {
  paper?: PaperSnapshot;
  unavailable: boolean;
}) {
  const t = totals(paper, unavailable);
  const active = t.count ? (t.active / t.count) * 100 : 0;
  const paused = t.count ? (t.paused / t.count) * 100 : 0;
  return (
    <section className="workspace-card distribution-card">
      <div className="card-heading">
        <h2>Account status</h2>
        <span className="subtle-note">{t.count} / 20 places</span>
      </div>
      <div className="distribution-content">
        <div
          className="account-donut"
          role="img"
          aria-label={`${t.active} scanning, ${t.paused} paused, ${t.attention} need attention`}
          style={{
            background: `conic-gradient(var(--green) 0% ${active}%, var(--amber) ${active}% ${active + paused}%, var(--red) ${active + paused}% 100%)`,
          }}
        >
          <div>
            <strong>{t.count || "—"}</strong>
            <span>Accounts</span>
          </div>
        </div>
        <dl className="distribution-legend">
          {[
            ["active", "Scanning", t.active],
            ["paused", "Paused", t.paused],
            ["attention", "Attention", t.attention],
          ].map(([key, label, value]) => (
            <div key={key}>
              <dt>
                <i className={`status-dot ${key}`} />
                {label}
              </dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </div>
      <p className="fine-print">
        Entry state only. Pauses do not cancel risk management or clear a hard
        stop.
      </p>
    </section>
  );
}

export function PerformanceChart({
  paper,
  unavailable,
}: {
  paper?: PaperSnapshot;
  unavailable: boolean;
}) {
  const [account, setAccount] = useState("primary");
  const [range, setRange] = useState(0);
  const [hovered, setHovered] = useState<number | null>(null);
  const gradient = useId().replaceAll(":", "");
  const selected = paper?.accounts[account];
  const points = useMemo(() => {
    const windows = [...(paper?.economics?.completed ?? [])];
    if (!unavailable && paper?.economics?.current)
      windows.push(paper.economics.current);
    windows.sort((a, b) => a.start - b.start);
    const result: {
      at: number;
      value: number;
      gap: boolean;
      provisional: boolean;
    }[] = [];
    let lastEnd = -1;
    for (const w of windows) {
      const s = w.scores[account];
      if (
        !s ||
        s.end_equity == null ||
        !s.available ||
        !Number.isFinite(Number(s.start_equity)) ||
        !Number.isFinite(Number(s.end_equity))
      ) {
        lastEnd = -1;
        continue;
      }
      const gap = lastEnd !== w.start;
      if (gap || result.at(-1)?.value !== Number(s.start_equity))
        result.push({
          at: w.start,
          value: Number(s.start_equity),
          gap: true,
          provisional: !w.complete,
        });
      result.push({
        at: w.end,
        value: Number(s.end_equity),
        gap: false,
        provisional: !w.complete,
      });
      lastEnd = w.end;
    }
    const end = result.at(-1)?.at ?? 0;
    return range ? result.filter((p) => p.at >= end - range) : result;
  }, [paper?.economics, account, range, unavailable]);
  const low = Math.min(...points.map((p) => p.value));
  const high = Math.max(...points.map((p) => p.value));
  const pad = points.length
    ? Math.max((high - low) * 0.16, Math.abs(high) * 0.001, 0.01)
    : 1;
  const min = low - pad,
    max = high + pad;
  const first = points[0]?.at ?? 0,
    duration = Math.max(1, (points.at(-1)?.at ?? 0) - first);
  const x = (p: (typeof points)[number]) =>
    65 + ((p.at - first) / duration) * 680;
  const y = (value: number) => 22 + ((max - value) / (max - min)) * 216;
  const paths: string[] = [];
  for (const p of points) {
    if (p.gap || !paths.length) paths.push(`M ${x(p)} ${y(p.value)}`);
    else paths[paths.length - 1] += ` L ${x(p)} ${y(p.value)}`;
  }
  const focus = points[hovered ?? points.length - 1] ?? points.at(-1);
  const current = !unavailable && selected?.valuation_fresh;
  return (
    <section className="workspace-card performance-card">
      <div className="card-heading">
        <div>
          <h2>Account performance</h2>
          <span className="subtle-note">Reported liquidation equity · USD</span>
        </div>
        <div className="chart-options">
          <label className="sr-only" htmlFor="performance-account">
            Performance account
          </label>
          <select
            id="performance-account"
            value={account}
            onChange={(e) => {
              setAccount(e.target.value);
              setHovered(null);
            }}
          >
            {Object.entries(paper?.accounts ?? { primary: null }).map(
              ([name, a]) => (
                <option key={name} value={name}>
                  {a?.label ?? name}
                </option>
              ),
            )}
          </select>
          <div
            className="workspace-tabs compact"
            aria-label="Performance history"
          >
            {[
              [14400, "4H"],
              [86400, "1D"],
              [604800, "7D"],
              [0, "ALL"],
            ].map(([value, label]) => (
              <button
                key={label}
                className={range === value ? "selected" : ""}
                aria-pressed={range === value}
                onClick={() => {
                  setRange(Number(value));
                  setHovered(null);
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {points.length > 1 ? (
        <div className="performance-plot">
          <div className="chart-readout">
            <span>
              {focus && stamp(focus.at)}{" "}
              {focus?.provisional ? "· provisional window" : "· historical"}
            </span>
            <strong>{money(focus?.value)}</strong>
          </div>
          <svg
            viewBox="0 0 790 275"
            role="img"
            aria-label={`Recorded liquidation-equity checkpoints for ${selected?.label ?? account}; gaps preserved`}
            onMouseLeave={() => setHovered(null)}
          >
            <defs>
              <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
                <stop stopColor="#18d993" stopOpacity=".3" />
                <stop offset="1" stopColor="#18d993" stopOpacity="0" />
              </linearGradient>
            </defs>
            {[0, 1, 2, 3, 4].map((i) => {
              const value = min + ((max - min) * i) / 4;
              return (
                <g key={i}>
                  <line
                    x1="65"
                    x2="745"
                    y1={y(value)}
                    y2={y(value)}
                    className="q-chart-grid"
                  />
                  <text
                    x="53"
                    y={y(value) + 4}
                    textAnchor="end"
                    className="q-chart-label"
                  >
                    {value.toFixed(2)}
                  </text>
                </g>
              );
            })}
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <line
                key={i}
                x1={65 + i * 136}
                x2={65 + i * 136}
                y1="22"
                y2="238"
                className="q-chart-grid"
              />
            ))}
            {paths.map((path, i) => {
              const coordinates = path.split(" ");
              return (
                <g key={i}>
                  {path.includes(" L ") && (
                    <path
                      d={`${path} L ${coordinates.at(-2)} 238 L ${coordinates[1]} 238 Z`}
                      fill={`url(#${gradient})`}
                    />
                  )}
                  <path
                    d={path}
                    fill="none"
                    stroke="var(--green)"
                    strokeWidth="2.4"
                    vectorEffect="non-scaling-stroke"
                  />
                </g>
              );
            })}
            {points.map((p, i) => (
              <circle
                key={`${p.at}-${i}`}
                cx={x(p)}
                cy={y(p.value)}
                r={i === hovered || i === points.length - 1 ? 4 : 2.5}
                fill="var(--green)"
                onMouseEnter={() => setHovered(i)}
              >
                <title>
                  {stamp(p.at)} · {money(p.value)}
                  {p.provisional ? " · provisional" : ""}
                </title>
              </circle>
            ))}
            <text x="65" y="263" className="q-chart-label">
              {stamp(first)}
            </text>
            <text x="745" y="263" textAnchor="end" className="q-chart-label">
              {stamp(points.at(-1)!.at)}
            </text>
          </svg>
        </div>
      ) : (
        <div className="performance-empty">
          <Activity size={31} />
          <h3>Waiting for comparable equity checkpoints</h3>
          <p>
            Recorded whole-account windows will appear here. Missing marks and
            gaps stay visible.
          </p>
        </div>
      )}
      <dl className="performance-stats">
        <div>
          <dt>Lifetime funding</dt>
          <dd>{money(selected?.funding)}</dd>
        </div>
        <div>
          <dt>Current equity</dt>
          <dd>{current ? money(selected.equity) : "Unconfirmed"}</dd>
        </div>
        <div>
          <dt>Net trading P&amp;L</dt>
          <dd
            className={
              current && Number(selected.net_pnl) >= 0 ? "positive" : ""
            }
          >
            {current ? money(selected.net_pnl) : "Unconfirmed"}
          </dd>
        </div>
        <div>
          <dt>Max drawdown</dt>
          <dd>{percent(selected?.max_drawdown)}</dd>
        </div>
        <div>
          <dt>Modeled fees</dt>
          <dd>{money(selected?.fees)}</dd>
        </div>
      </dl>
      <p className="fine-print">
        Lines join contiguous reported windows. Funding changes can move equity.
        This chart contains retained checkpoints, not continuous intrawindow
        prices; operating allocations are in Analytics.
      </p>
    </section>
  );
}

function MarketWatchlist() {
  type Quotes = {
    running: boolean;
    error: string | null;
    markets: {
      symbol: string;
      bid: string | null;
      ask: string | null;
      state: string;
      valid_for_ms: number;
    }[];
  };
  const [quotes, setQuotes] = useState<Quotes | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true,
      timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function load() {
      if (document.hidden) {
        timer = setTimeout(load, 2000);
        return;
      }
      try {
        const response = await fetch("/api/station/live?symbol=BTCUSD", {
          signal: AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(3000),
          ]),
          cache: "no-store",
        });
        if (!response.ok) throw new Error();
        const next = (await response.json()) as Quotes;
        if (active) {
          setQuotes(next);
          setFailed(false);
        }
      } catch {
        if (active) setFailed(true);
      }
      if (active) timer = setTimeout(load, 2000);
    }
    void load();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  return (
    <section className="workspace-card watch-card">
      <div className="card-heading">
        <h2>Market watchlist</h2>
        <a href="#markets" className="text-link">
          Markets <ArrowRight size={13} />
        </a>
      </div>
      <table className="watch-table">
        <thead>
          <tr>
            <th>Market</th>
            <th>Best bid</th>
            <th>At capture</th>
          </tr>
        </thead>
        <tbody>
          {quotes?.markets.map((q) => (
            <tr key={q.symbol}>
              <td>
                <span className="coin-mark">
                  {q.symbol.startsWith("BTC") ? "₿" : q.symbol.slice(0, 1)}
                </span>
                <strong>{q.symbol.replace(/USD$/, " / USD")}</strong>
              </td>
              <td>{money(q.bid)}</td>
              <td>
                <span
                  className={`state-badge ${!failed && quotes.running && !quotes.error && q.state === "fresh" ? "active" : "attention"}`}
                >
                  {failed ? "Historical" : q.state.replaceAll("_", " ")}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!quotes?.markets.length && (
        <p className="empty-state">
          {failed
            ? "Market observations are unavailable."
            : "Waiting for market observations…"}
        </p>
      )}
      <p className="fine-print">
        Public quotes, refreshed every two seconds. Paper fills use their own
        stricter freshness checks.
      </p>
    </section>
  );
}

export function DashboardView({
  paper,
  unavailable,
}: {
  paper?: PaperSnapshot;
  unavailable: boolean;
}) {
  const t = totals(paper, unavailable);
  const learning = paper?.learning;
  const eligible =
    learning?.reports.filter(
      (r) => r.decision === "eligible_for_paper_designation",
    ).length ?? 0;
  const primary = paper?.accounts.primary;
  const recent =
    paper?.events
      .filter((e) =>
        ["fill", "trade_closed", "order_submitted", "order_cancelled"].includes(
          e.kind,
        ),
      )
      .slice(0, 6) ?? [];
  return (
    <>
      <div
        className="metrics-grid dashboard-metrics"
        aria-label="Paper workspace summary"
      >
        <article className="metric-card">
          <div className="metric-label">
            Total paper equity <Wallet size={18} />
          </div>
          <div className="metric-value">{money(t.equity)}</div>
          <p>
            {t.confirmed
              ? `${t.count} separate hypothetical accounts`
              : "Waiting for confirmed marks"}
          </p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Paper net P&amp;L <Activity size={18} />
          </div>
          <div
            className={`metric-value ${t.pnl !== null && t.pnl >= 0 ? "positive" : t.pnl !== null ? "negative" : ""}`}
          >
            {money(t.pnl)}
          </div>
          <p>Sum after modeled fees · funding excluded</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Scanning accounts <Wallet size={18} />
          </div>
          <div className="metric-value">
            {t.active}
            <span className="metric-unit">/ {t.count || "—"}</span>
          </div>
          <p>
            {t.paused} paused · {t.attention} need attention
          </p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Modeled fees <FileClock size={18} />
          </div>
          <div className="metric-value">{money(t.fees)}</div>
          <p>Retained across all paper accounts</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Qualified reports <BrainCircuit size={18} />
          </div>
          <div className="metric-value">
            {eligible}
            <span className="metric-unit">
              / {learning?.reports.length ?? 0}
            </span>
          </div>
          <p>Eligible for paper-role review only</p>
        </article>
      </div>
      <div className="dashboard-grid">
        <div className="dashboard-primary">
          <PerformanceChart paper={paper} unavailable={unavailable} />
          <div className="dashboard-lower">
            <AccountDistribution paper={paper} unavailable={unavailable} />
            <section className="workspace-card">
              <div className="card-heading">
                <h2>Recent paper activity</h2>
                <a className="text-link" href="#orders">
                  View history <ArrowRight size={13} />
                </a>
              </div>
              <div className="recent-activity">
                {recent.map((e) => (
                  <article key={e.id}>
                    <span
                      className={`activity-icon ${e.kind === "trade_closed" && Number(e.body.net_pnl) < 0 ? "negative" : ""}`}
                    >
                      <FileClock size={17} />
                    </span>
                    <div>
                      <strong>{e.kind.replaceAll("_", " ")}</strong>
                      <p>
                        {String(e.body.symbol ?? "Primary account")} ·{" "}
                        {String(
                          e.body.reason ?? e.body.side ?? "Recorded outcome",
                        )}
                      </p>
                    </div>
                    <time>{stamp(e.at)}</time>
                  </article>
                ))}
              </div>
              {!recent.length && (
                <p className="empty-state">
                  No fill or order event in the retained primary-account window.
                </p>
              )}
              <p className="fine-print">
                Primary account only. Complete account histories are in Orders.
              </p>
            </section>
          </div>
        </div>
        <div className="dashboard-secondary">
          <MarketWatchlist />
          <section className="workspace-card research-insights">
            <div className="card-heading">
              <h2>Research insights</h2>
              <a href="#ai-lab" className="text-link">
                AI Lab <ArrowRight size={13} />
              </a>
            </div>
            <div className="insight-highlight">
              <BrainCircuit size={28} />
              <div>
                <strong>
                  {learning?.reports.length
                    ? learning.reports[0].decision === "no_promotion"
                      ? "No promotion"
                      : "Review the retained report"
                    : "Evidence is still developing"}
                </strong>
                <p>
                  {learning?.reports[0]?.reasons[0] ??
                    "No qualified forward result has been established. Keep the original trial and every rejected result."}
                </p>
              </div>
            </div>
            <dl className="insight-facts">
              <div>
                <dt>Paper incumbent</dt>
                <dd>{learning?.incumbent ?? "primary"}</dd>
              </div>
              <div>
                <dt>Forward candidates</dt>
                <dd>{learning?.accounts.length ?? 0}</dd>
              </div>
              <div>
                <dt>Next trial review</dt>
                <dd>{paper ? stamp(paper.next_review) : "—"}</dd>
              </div>
              <div>
                <dt>Confidence</dt>
                <dd>Not calibrated</dd>
              </div>
            </dl>
          </section>
          <section className="workspace-card">
            <div className="card-heading">
              <h2>Risk &amp; exposure</h2>
              <a href="#risk" className="text-link">
                Details <ArrowRight size={13} />
              </a>
            </div>
            <RiskOverview paper={paper} unavailable={unavailable} compact />
            <p className="fine-print">
              Primary account:{" "}
              {primary?.risk?.reason ?? "Waiting for risk status."}
            </p>
          </section>
        </div>
      </div>
    </>
  );
}

function AccountInspector({
  name,
  paper,
  unavailable,
  close,
}: {
  name: string;
  paper: PaperSnapshot;
  unavailable: boolean;
  close: () => void;
}) {
  const a = paper.accounts[name];
  const mark = paper.economics?.accounts[name];
  const [pending, setPending] = useState(false);
  const [version, setVersion] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    panel.current?.scrollIntoView({ block: "start" });
    panel.current?.focus({ preventScroll: true });
  }, []);
  const waiting = version !== null && (a?.control_version ?? 0) < version;
  if (!a) return null;
  async function control(action: "pause" | "resume" | "recover") {
    setPending(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(
        `/api/paper/accounts/${encodeURIComponent(name)}/control`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Local-Operator": "1",
          },
          body: JSON.stringify({
            action,
            expected_version: a.control_version ?? 0,
          }),
          signal: AbortSignal.timeout(7000),
        },
      );
      const value = await response.json();
      if (!response.ok)
        throw new Error(
          typeof value.detail === "string"
            ? value.detail
            : "Control was not confirmed. Refresh and retry.",
        );
      setVersion(value.version);
      setNotice("Saved. Waiting for the refreshed account control version.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Control was not confirmed.");
    } finally {
      setPending(false);
    }
  }
  const state = accountState(a, paper, unavailable);
  return (
    <section
      ref={panel}
      tabIndex={-1}
      className="workspace-card account-inspector"
      aria-label="Selected account details"
    >
      <div className="card-heading">
        <div>
          <p className="eyebrow">SELECTED PAPER ACCOUNT</p>
          <h2>{a.label ?? name}</h2>
        </div>
        <button
          className="icon-button"
          aria-label="Close account details"
          onClick={close}
        >
          <X size={18} />
        </button>
      </div>
      <p>
        <span className={`state-badge ${state.key}`}>{state.label}</span>{" "}
        <span className="subtle-note">{a.version}</span>
      </p>
      <p>
        {a.fault?.reason ??
          a.risk?.reason ??
          "Waiting for retained risk evidence."}
      </p>
      <dl className="summary-values">
        <div>
          <dt>Equity</dt>
          <dd>
            {!unavailable && a.valuation_fresh
              ? money(a.equity)
              : "Unconfirmed"}
          </dd>
        </div>
        <div>
          <dt>Lifetime funding</dt>
          <dd>{money(a.funding)}</dd>
        </div>
        <div>
          <dt>Available cash</dt>
          <dd>{money(mark?.available_cash)}</dd>
        </div>
        <div>
          <dt>Reserved cash</dt>
          <dd>{money(mark?.reserved)}</dd>
        </div>
        <div>
          <dt>Modeled fees</dt>
          <dd>{money(a.fees)}</dd>
        </div>
        <div>
          <dt>Max drawdown</dt>
          <dd>{percent(a.max_drawdown)}</dd>
        </div>
      </dl>
      <div className="heading-actions">
        <button
          className="button secondary"
          disabled={pending || waiting || unavailable}
          onClick={() => void control(a.entries_paused ? "resume" : "pause")}
        >
          {a.entries_paused ? <Play size={15} /> : <Pause size={15} />}
          {pending || waiting
            ? "Waiting for status…"
            : a.entries_paused
              ? "Clear account entry pause"
              : "Pause this account's entries"}
        </button>
        {a.fault && (
          <button
            className="button secondary"
            disabled={pending || waiting || unavailable}
            onClick={() => void control("recover")}
          >
            Retry account processing
          </button>
        )}
        <a href="#risk" className="button secondary">
          <ShieldCheck size={15} /> Review loss controls
        </a>
      </div>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <p className="fine-print">
        Clearing an entry pause does not clear a global pause, hard stop or
        valuation block. Funding and all earlier losses are preserved.
      </p>
      <PaperCampaignJournal key={name} account={name} />
    </section>
  );
}

export function AccountsView({
  paper,
  unavailable,
  initialSearch,
}: {
  paper?: PaperSnapshot;
  unavailable: boolean;
  initialSearch: string;
}) {
  const [query, setQuery] = useState(initialSearch);
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(10);
  const [selected, setSelected] = useState("");
  const [campaignOpen, setCampaignOpen] = useState(false);
  const [sort, setSort] = useState<"name" | "equity">("name");
  useEffect(() => {
    setQuery(initialSearch);
    setPage(0);
  }, [initialSearch]);
  if (!paper) return <EmptyPaper />;
  const t = totals(paper, unavailable);
  const accounts = Object.entries(paper.accounts);
  const research = accounts.filter(([, a]) =>
    a.campaign_id?.startsWith("forward-"),
  ).length;
  const matching = accounts.filter(
    ([name, a]) =>
      `${a.label ?? name} ${a.version}`
        .toLowerCase()
        .includes(query.toLowerCase()) &&
      (filter === "all" ||
        (filter === "research" && a.campaign_id?.startsWith("forward-")) ||
        accountState(a, paper, unavailable).key === filter),
  );
  matching.sort((a, b) =>
    sort === "equity" &&
    !unavailable &&
    a[1].valuation_fresh &&
    b[1].valuation_fresh
      ? Number(b[1].equity) - Number(a[1].equity)
      : (a[1].label ?? a[0]).localeCompare(b[1].label ?? b[0]),
  );
  const maxPage = Math.max(0, Math.ceil(matching.length / pageSize) - 1);
  const shownPage = Math.min(page, maxPage),
    start = shownPage * pageSize;
  return (
    <>
      <div className="metrics-grid account-metrics">
        <article className="metric-card">
          <div className="metric-label">
            Total paper equity <Wallet size={18} />
          </div>
          <div className="metric-value">{money(t.equity)}</div>
          <p>Across separate hypothetical accounts</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Scanning accounts <Activity size={18} />
          </div>
          <div className="metric-value">
            {t.active} <span className="metric-unit">/ {t.count}</span>
          </div>
          <p>Fresh status and entry capacity</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Paused accounts <Pause size={18} />
          </div>
          <div className="metric-value">{t.paused}</div>
          <p>Global, account, daily or cooldown pause</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Needs attention <ShieldCheck size={18} />
          </div>
          <div className="metric-value">{t.attention}</div>
          <p>Stops, missing marks or processing faults</p>
        </article>
      </div>
      <div className="accounts-layout">
        <div>
          <div className="accounts-toolbar">
            <div
              className="workspace-tabs compact"
              aria-label="Account filters"
            >
              {[
                ["all", "All", t.count],
                ["active", "Scanning", t.active],
                ["paused", "Paused", t.paused],
                ["research", "Research", research],
                ["attention", "Attention", t.attention],
              ].map(([id, label, count]) => (
                <button
                  key={id}
                  className={filter === id ? "selected" : ""}
                  aria-pressed={filter === id}
                  onClick={() => {
                    setFilter(String(id));
                    setPage(0);
                  }}
                >
                  {label} <span>{count}</span>
                </button>
              ))}
            </div>
            <label className="account-search">
              <Search size={15} />
              <input
                type="search"
                aria-label="Search accounts"
                placeholder="Search accounts…"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPage(0);
                }}
              />
            </label>
          </div>
          <section className="workspace-card account-table-card">
            <div className="table-scroll">
              <table
                className="market-table accounts-table"
                aria-label="All paper accounts"
              >
                <thead>
                  <tr>
                    <th>#</th>
                    <th>
                      <button
                        className="table-sort"
                        onClick={() => setSort("name")}
                      >
                        Account / strategy
                      </button>
                    </th>
                    <th>
                      <button
                        className="table-sort"
                        onClick={() => setSort("equity")}
                      >
                        Equity ↓
                      </button>
                    </th>
                    <th>Net trading P&amp;L</th>
                    <th>Entry status</th>
                    <th>Risk policy</th>
                    <th>Last decision</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {matching
                    .slice(start, start + pageSize)
                    .map(([name, a], i) => {
                      const state = accountState(a, paper, unavailable),
                        decision = Object.values(a.last_decision).sort(
                          (a, b) => b.at - a.at,
                        )[0];
                      return (
                        <tr key={name} aria-selected={selected === name}>
                          <td className="muted">
                            {String(start + i + 1).padStart(2, "0")}
                          </td>
                          <td>
                            <button
                              className="account-name"
                              onClick={() => setSelected(name)}
                            >
                              {a.label ?? name}
                            </button>
                            <small>{a.version}</small>
                          </td>
                          <td>
                            {!unavailable && a.valuation_fresh
                              ? money(a.equity)
                              : "Unconfirmed"}
                          </td>
                          <td
                            className={
                              !unavailable && a.valuation_fresh
                                ? Number(a.net_pnl) >= 0
                                  ? "positive"
                                  : "negative"
                                : ""
                            }
                          >
                            {!unavailable && a.valuation_fresh
                              ? money(a.net_pnl)
                              : "Unconfirmed"}
                          </td>
                          <td>
                            <span className={`state-badge ${state.key}`}>
                              {state.label}
                            </span>
                          </td>
                          <td>
                            <span className="state-badge neutral">
                              {a.risk?.legacy
                                ? "Historical"
                                : a.risk
                                  ? "Hard stop"
                                  : "Unknown"}
                            </span>
                          </td>
                          <td className="decision-cell">
                            {decision ? (
                              <>
                                <span>{stamp(decision.at)}</span>
                                <small>{decision.reason}</small>
                              </>
                            ) : (
                              <small>No recorded decision</small>
                            )}
                          </td>
                          <td>
                            <button
                              className="icon-button"
                              aria-label={`Inspect ${a.label ?? name}`}
                              onClick={() => setSelected(name)}
                            >
                              <ChevronRight size={17} />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
            {!matching.length && (
              <p className="empty-state">
                No accounts match this filter. Clear the search or choose All.
              </p>
            )}
            <div className="table-pagination">
              <span>
                Showing {matching.length ? start + 1 : 0}–
                {Math.min(start + pageSize, matching.length)} of{" "}
                {matching.length} accounts
              </span>
              <div>
                <button
                  className="icon-button"
                  aria-label="Previous accounts page"
                  disabled={shownPage === 0}
                  onClick={() => setPage(shownPage - 1)}
                >
                  <ChevronLeft size={16} />
                </button>
                <span>
                  {shownPage + 1} / {maxPage + 1}
                </span>
                <button
                  className="icon-button"
                  aria-label="Next accounts page"
                  disabled={shownPage >= maxPage}
                  onClick={() => setPage(shownPage + 1)}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
              <label>
                Rows per page{" "}
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setPage(0);
                  }}
                >
                  <option value={10}>10</option>
                  <option value={20}>20</option>
                </select>
              </label>
            </div>
          </section>
          <p className="fine-print">
            Balances belong to separate simulations. Their returns are not a
            combined portfolio. Failed accounts keep their history and use a
            retained account place.
          </p>
        </div>
        <div className="accounts-aside">
          <AccountDistribution paper={paper} unavailable={unavailable} />
          <section className="workspace-card">
            <div className="card-heading">
              <h2>Account capacity</h2>
              <Wallet size={18} />
            </div>
            <div className="capacity-readout">
              <strong>{t.count}</strong>
              <span>of 20 retained places</span>
            </div>
            <progress
              max={20}
              value={t.count}
              aria-label="Retained account places"
            />
            <p>
              {20 - t.count} places remain. Original accounts, exploratory
              candidates and matched controls all count.
            </p>
            <button
              className="button primary"
              onClick={() => setCampaignOpen(!campaignOpen)}
            >
              <Plus size={16} />
              {paper.campaigns?.length
                ? "Manage campaign"
                : "Create paper campaign"}
            </button>
          </section>
          <section className="workspace-card">
            <div className="card-heading">
              <h2>Review queue</h2>
              <CircleHelp size={18} />
            </div>
            {accounts
              .filter(
                ([, a]) =>
                  accountState(a, paper, unavailable).key === "attention",
              )
              .slice(0, 4)
              .map(([name, a]) => (
                <button
                  className="attention-row"
                  key={name}
                  onClick={() => setSelected(name)}
                >
                  <span className="status-dot attention" />
                  <span>
                    {a.label ?? name}
                    <small>
                      {a.fault?.reason ??
                        a.risk?.reason ??
                        "Status unconfirmed"}
                    </small>
                  </span>
                  <ChevronRight size={14} />
                </button>
              ))}
            {!t.attention && (
              <p>
                No account processing or entry-capacity flag at this
                observation.
              </p>
            )}
            {t.attention > 4 && (
              <button
                className="text-link"
                onClick={() => {
                  setFilter("attention");
                  setQuery("");
                  setPage(0);
                }}
              >
                View all {t.attention} flagged accounts <ArrowRight size={13} />
              </button>
            )}
          </section>
        </div>
      </div>
      {selected && (
        <AccountInspector
          key={selected}
          name={selected}
          paper={paper}
          unavailable={unavailable}
          close={() => setSelected("")}
        />
      )}
      {campaignOpen && (
        <div className="campaign-workspace">
          <PaperCampaignPanel data={paper} unavailable={unavailable} />
        </div>
      )}
    </>
  );
}

export function OrdersView({
  paper,
  unavailable,
}: {
  paper?: PaperSnapshot;
  unavailable: boolean;
}) {
  const [account, setAccount] = useState("all");
  const [journal, setJournal] = useState("primary");
  const [view, setView] = useState("trades");
  if (!paper) return <EmptyPaper />;
  const accounts = Object.entries(paper.accounts).filter(
    ([name]) => account === "all" || account === name,
  );
  const positions = accounts.flatMap(([name, a]) =>
    Object.entries(a.positions).map(([symbol, p]) => ({ name, a, symbol, p })),
  );
  const pending = accounts.flatMap(([name, a]) =>
    Object.entries(a.pending).map(([symbol, p]) => ({ name, a, symbol, p })),
  );
  return (
    <>
      <nav className="workspace-tabs" aria-label="Orders views">
        {[["trades", "Trade history"], ["positions", "Positions & pending"], ["journal", "Journal"]].map(([id, label]) => (
          <button key={id} className={view === id ? "selected" : ""} aria-pressed={view === id}
            onClick={() => setView(id)}>{label}</button>
        ))}
      </nav>
      {view === "trades" && <TradeHistory paper={paper} unavailable={unavailable} />}
      {view === "positions" && <div className="workspace-card">
        <div className="card-heading">
          <h2>Positions &amp; pending orders</h2>
          <label>
            Account{" "}
            <select
              value={account}
              onChange={(e) => setAccount(e.target.value)}
            >
              <option value="all">All accounts</option>
              {Object.entries(paper.accounts).map(([name, a]) => (
                <option key={name} value={name}>
                  {a.label ?? name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {unavailable && (
          <p className="error-banner">
            Last reported holdings; worker status is unconfirmed.
          </p>
        )}
        <div className="table-scroll">
          <table className="market-table orders-table">
            <thead>
              <tr>
                <th>Account</th>
                <th>Market</th>
                <th>State</th>
                <th>Quantity</th>
                <th>Entry</th>
                <th>Stop trigger</th>
                <th>Opened / reason</th>
              </tr>
            </thead>
            <tbody>
              {positions.map(({ name, a, symbol, p }) => (
                <tr key={`${name}-${symbol}-position`}>
                  <td>{a.label ?? name}</td>
                  <td>{symbol}</td>
                  <td>
                    <span className="state-badge active">Owned position</span>
                  </td>
                  <td>{p.quantity}</td>
                  <td>{money(p.entry)}</td>
                  <td>{money(p.stop)}</td>
                  <td>{p.exit_blocked ?? stamp(p.opened_at)}</td>
                </tr>
              ))}
              {pending.map(({ name, a, symbol, p }) => (
                <tr key={`${name}-${symbol}-order`}>
                  <td>{a.label ?? name}</td>
                  <td>{symbol}</td>
                  <td>
                    <span className="state-badge paused">Pending {p.side}</span>
                  </td>
                  <td>{p.quantity}</td>
                  <td colSpan={3}>Waiting for a subsequent executable book</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!positions.length && !pending.length && (
          <p className="empty-state">
            No open position or pending order in the selected accounts. Signals
            and risk checks determine activity.
          </p>
        )}
        <p className="fine-print">
          Paper only. A stop trigger is not a guaranteed exit price. The journal
          retains fills, fees, cancellations and failures.
        </p>
      </div>}
      {view === "journal" && <section className="workspace-card">
        <div className="card-heading">
          <h2>Retained account history</h2>
          <label>
            Journal account{" "}
            <select
              value={journal}
              onChange={(e) => setJournal(e.target.value)}
            >
              {Object.entries(paper.accounts).map(([name, a]) => (
                <option key={name} value={name}>
                  {a.label ?? name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <PaperCampaignJournal key={journal} account={journal} />
      </section>}
    </>
  );
}

export function RiskOverview({
  paper,
  unavailable,
  compact = false,
}: {
  paper?: PaperSnapshot;
  unavailable: boolean;
  compact?: boolean;
}) {
  const primary = paper?.accounts.primary,
    t = totals(paper, unavailable);
  const exposure =
    primary && !unavailable && primary.valuation_fresh
      ? Math.max(0, Number(primary.equity) - Number(primary.cash))
      : null;
  const ratio =
    exposure !== null && primary && Number(primary.equity) > 0
      ? exposure / Number(primary.equity)
      : null;
  const drawdown = primary ? Number(primary.max_drawdown) : null;
  const body = (
    <>
      <div className="risk-gauges">
        <div>
          <span>Primary liquidation exposure</span>
          <strong>{money(exposure)}</strong>
          <div className="meter-track">
            <i style={{ width: `${Math.min(100, (ratio ?? 0) * 100)}%` }} />
          </div>
          <small>
            {ratio === null
              ? "Current mark unconfirmed"
              : `${percent(ratio)} of primary equity`}
          </small>
        </div>
        <div>
          <span>Primary max drawdown</span>
          <strong>{percent(drawdown)}</strong>
          <div className="meter-track amber">
            <i style={{ width: `${Math.min(100, (drawdown ?? 0) * 100)}%` }} />
          </div>
          <small>Funding adjusted · retained</small>
        </div>
      </div>
      {!compact && (
        <div className="guardrail-list horizontal">
          <p>
            <ShieldCheck size={22} />
            <span>
              <strong>{t.attention} accounts need attention</strong>Processing
              failures and entry blocks remain explicit.
            </span>
          </p>
          <p>
            <Wallet size={22} />
            <span>
              <strong>{t.paused} entry pauses</strong>Pausing entries keeps
              position management active.
            </span>
          </p>
          <p>
            <BrainCircuit size={22} />
            <span>
              <strong>Human approval</strong>Qualified evidence changes a paper
              research role only.
            </span>
          </p>
          <p>
            <LockIcon />
            <span>
              <strong>Live execution disabled</strong>Separate account, funding
              and adapter proof is required.
            </span>
          </p>
        </div>
      )}
    </>
  );
  return compact ? (
    body
  ) : (
    <section className="workspace-card">
      <div className="card-heading">
        <h2>Account safeguards</h2>
        <span className="pill paper">PAPER ONLY</span>
      </div>
      {body}
      <p className="fine-print">
        Liquidation exposure is a displayed equity-minus-cash estimate, not
        gross notional or value at risk. Planned limits cannot guarantee a
        maximum loss.
      </p>
    </section>
  );
}
function LockIcon() {
  return <ShieldCheck size={22} />;
}
