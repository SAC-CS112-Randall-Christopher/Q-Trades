import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  BarChart3,
  Check,
  CircleHelp,
  Clock3,
  Cpu,
  Database,
  Eye,
  FlaskConical,
  Layers3,
  LockKeyhole,
  Pause,
  Play,
  Radio,
  ShieldCheck,
  Telescope,
} from "lucide-react";
import "./style.css";
import { PaperPanel, type PaperSnapshot } from "./PaperPanel";
import { OptionsPanel, type OptionsSnapshot } from "./OptionsPanel";
import { ModelTrialsPanel } from "./ModelTrialsPanel";
import { ExperimentLab } from "./ExperimentLab";
import { MarketStation } from "./MarketStation";

type Snapshot = {
  paper?: PaperSnapshot;
  options?: OptionsSnapshot;
  mode: "paper";
  runtime_state: string;
  paused: boolean;
  generated_at: string;
  poll_seconds: number;
  stale_after_seconds: number;
  retry_in_seconds: number;
  storage_error: string | null;
  capture: {
    retained: number;
    total: number;
    evicted: number;
    capacity: number;
  };
  events: { id: number; observed_at: string; message: string }[];
  events_total: number;
};

const format = (value: string | null | undefined, digits = 2) =>
  value == null
    ? "—"
    : Number(value).toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
const timeLabel = (value: string | null | undefined) =>
  value
    ? new Date(value).toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZone: "America/Denver",
      })
    : "Not observed";
const stateLabel = (state: string) => state.replaceAll("_", " ");

function App() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [networkError, setNetworkError] = useState<string | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const load = async () => {
      try {
        const response = await fetch("/api/status", {
          signal: AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(7000),
          ]),
          cache: "no-store",
        });
        if (!response.ok) throw new Error("Local service unavailable");
        const next = (await response.json()) as Snapshot;
        if (active) {
          setData(next);
          setNetworkError(null);
        }
      } catch {
        if (active)
          setNetworkError(
            "Dashboard disconnected. Displayed observations are historical until the local service reconnects.",
          );
      }
      if (active) timer = setTimeout(load, 3000);
    };
    void load();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, []);

  const runtimeState = networkError
    ? "disconnected"
    : !data ? "connecting"
    : !data.paper?.enabled ? "not enabled"
    : data.paper.error ? "needs attention"
    : !data.paper.running ? "stopped"
    : data.paper.stale ? "stale" : "running";

  async function control() {
    if (!data) return;
    setPending(true);
    setCommandError(null);
    try {
      const response = await fetch("/api/collector", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Local-Operator": "1",
        },
        body: JSON.stringify({ action: data.paused ? "resume" : "pause" }),
        signal: AbortSignal.timeout(7000),
      });
      if (!response.ok) throw new Error();
      const result = (await response.json()) as { paused: boolean };
      setData((previous) =>
        previous
          ? {
              ...previous,
              paused: result.paused,
              runtime_state: result.paused ? "paused" : "warming_up",
            }
          : previous,
      );
    } catch {
      setCommandError(
        "The collector did not confirm this action. Its state is unchanged until confirmed.",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <a className="brand" href="#overview">
          <span className="brand-mark">
            <BarChart3 size={23} />
          </span>
          <span>
            Trading<span className="brand-sub">RESEARCH PLATFORM</span>
          </span>
        </a>
        <div className="workspace-label">
          LOCAL WORKSPACE <span>01</span>
        </div>
        <nav aria-label="Main navigation">
          <a className="nav-primary" href="#overview">
            <Layers3 size={18} /> Overview <span className="nav-dot" />
          </a>
          <a href="#live-quotes">
            <Activity size={18} /> Command station
          </a>
          <a href="#strategy-lab">
            <Telescope size={18} /> Strategies &amp; learning
          </a>
          <a href="#experiment">
            <FlaskConical size={18} /> $100 paper experiment
          </a>
          <a href="#options">
            <Layers3 size={18} /> Options practice
          </a>
          <a href="#research">
            <FlaskConical size={18} /> Research tiers
          </a>
          <a href="#model-lab">
            <Cpu size={18} /> Model trials
          </a>
          <a href="#operations">
            <Radio size={18} /> Operations
          </a>
          <a href="#roadmap">
            <Telescope size={18} /> Build roadmap
          </a>
        </nav>
        <div className="sidebar-note">
          <ShieldCheck size={21} />
          <strong>Observe. Test. Understand.</strong>
          <p>Build evidence before putting capital to work.</p>
          <span>PAPER ENVIRONMENT</span>
        </div>
        <div className="sidebar-footer">
          <span className="avatar">CR</span>
          <div>
            Chris Randall<small>Owner · Local workspace</small>
          </div>
        </div>
      </aside>
      <main id="main">
        <header className="topbar">
          <div>
            <span className="muted">Workspace</span>
            <span className="slash">/</span>Overview
          </div>
          <div className="topbar-right">
            <span className="pill paper">
              <ShieldCheck size={13} /> PAPER ONLY
            </span>
            <span className="local-tag">
              <LockKeyhole size={13} /> Local
            </span>
          </div>
        </header>
        <div className="page" id="overview">
          <div className="page-heading">
            <div>
              <p className="eyebrow">THE RESEARCH LAB · PAPER ONLY</p>
              <h1>Observe. Trade. Learn.</h1>
              <p className="subtitle">
                Real market observations. Simulated capital. Every outcome
                recorded.
              </p>
            </div>
            <a className="button secondary" href="/api/capture">
              <ArrowDownToLine size={16} /> Export observations
            </a>
          </div>

          {(networkError || commandError || data?.storage_error) && (
            <div className="error-banner" role="alert">
              <CircleHelp size={19} />
              <span>{networkError || commandError || data?.storage_error}</span>
            </div>
          )}

          <section className="status-strip" aria-label="Operating mode">
            <span className="strip-icon">
              <Eye size={20} />
            </span>
            <div>
              <strong>
                {data?.paper?.enabled
                  ? "The $100 Tier 3 experiment is enabled."
                  : "Public market research."}
              </strong>
              <p>
                {data?.paper?.enabled
                  ? "Algorithmic paper execution and a four-hour learning review. No real money or model calls."
                  : "Collecting public market data. Start the authorized experiment to enable paper orders."}
              </p>
            </div>
            <span className="pill neutral">RESEARCH IN PROGRESS</span>
          </section>

          <section className="metrics-grid" aria-label="Workspace summary">
            <article className="metric-card">
              <div className="metric-label">
                Paper worker <Radio size={17} />
              </div>
              <div className="metric-value">
                <span
                  className={
                    "status-dot " +
                    (runtimeState === "running" ? "good" : "")
                  }
                />
                <span className="state-title">{stateLabel(runtimeState)}</span>
              </div>
              <p>
                Market feed and pricing in the command station
              </p>
            </article>
            <article className="metric-card">
              <div className="metric-label">
                Trading capital <LockKeyhole size={17} />
              </div>
              <div className="metric-value">
                {data?.paper?.enabled
                  ? "$" + format(data.paper.accounts.primary.equity)
                  : "Not allocated"}
              </div>
              <p>
                {data?.paper?.enabled
                  ? "Simulated USD · Tier 3"
                  : "No account connected"}
              </p>
            </article>
            <article className="metric-card">
              <div className="metric-label">
                Captured observations <Database size={17} />
              </div>
              <div className="metric-value">
                {data ? data.capture.retained.toLocaleString() : "—"}
                <span className="metric-unit">retained</span>
              </div>
              <p>Public responses, available for offline replay</p>
            </article>
            <article className="metric-card">
              <div className="metric-label">
                Research agents <Cpu size={17} />
              </div>
              <div className="metric-value">
                Disabled
                <span className="off-indicator" />
              </div>
              <p>Local model testing · <a href="#model-lab">View trials</a></p>
            </article>
          </section>

          <MarketStation />
          <PaperPanel data={data?.paper} disconnected={!!networkError} />
          <ExperimentLab />
          <ModelTrialsPanel />
          <OptionsPanel data={data?.options} disconnected={!!networkError} />
          <section id="research" className="research-section">
            <div className="section-heading plain">
              <div>
                <p className="eyebrow">02 / RESEARCH</p>
                <h2>Three questions worth testing.</h2>
              </div>
              <span className="subtle-note">
                Tier 3 is the active paper experiment
              </span>
            </div>
            <div className="tier-grid">
              <article className="tier-card">
                <div className="tier-top">
                  <span className="tier-index">TIER 01</span>
                  <Layers3 size={19} />
                </div>
                <h3>Systematic</h3>
                <p>
                  Stock and ETF strategies with a longer horizon and a benchmark
                  to beat.
                </p>
                <div className="tier-target">
                  Benchmark relative<small>Multi-year research objective</small>
                </div>
                <div className="tier-status">
                  <Clock3 size={13} /> Awaiting broker & point-in-time data
                </div>
              </article>
              <article className="tier-card">
                <div className="tier-top">
                  <span className="tier-index">TIER 02</span>
                  <Activity size={19} />
                </div>
                <h3>Aggressive</h3>
                <p>
                  Selective breakout and continuation research, measured after
                  costs.
                </p>
                <div className="tier-target">
                  10–20% <span>/ week</span>
                  <small>Research target · Attainability unknown</small>
                </div>
                <div className="tier-status">
                  <Clock3 size={13} /> Not active in this experiment
                </div>
              </article>
              <article className="tier-card">
                <div className="tier-top">
                  <span className="tier-index">TIER 03</span>
                  <FlaskConical size={19} />
                </div>
                <h3>Experimental</h3>
                <p>
                  Short-horizon ideas where turnover must justify its costs and
                  risks.
                </p>
                <div className="tier-target">
                  $100 → $1,000
                  <small>Repeatability target · Not a forecast</small>
                </div>
                <div className="tier-status">
                  <Clock3 size={13} /> Continuous paper trial · Four-hour
                  reviews
                </div>
              </article>
            </div>
          </section>

          <div className="bottom-grid">
            <section className="panel operations" id="operations">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">03 / OPERATE</p>
                  <h2>Background REST capture</h2>
                </div>
                <button
                  className="button secondary small"
                  disabled={!data || pending || !!networkError}
                  onClick={() => void control()}
                >
                  {data?.paused ? <Play size={14} /> : <Pause size={14} />}
                  {pending
                    ? "Confirming…"
                    : data?.paused
                      ? "Resume collection"
                      : "Pause collection"}
                </button>
              </div>
              <p className="activity-note">
                Pause is saved across restarts. Closing this dashboard does not
                stop the local collector. This control affects the monitor only;
                the paper engine has its own public feed and entry controls
                above.
              </p>
              {(data?.retry_in_seconds ?? 0) > 0 && (
                <div className="cooldown">
                  Retry cooldown: {data?.retry_in_seconds}s remaining. No
                  immediate retry loop.
                </div>
              )}
              <ol className="event-list">
                {data?.events.map((event) => (
                  <li key={event.id}>
                    <span className="event-dot" />
                    <p>{event.message}</p>
                    <time dateTime={event.observed_at}>
                      {timeLabel(event.observed_at)}
                    </time>
                  </li>
                ))}
              </ol>
              {data?.events.length === 0 && (
                <p className="empty-state">No collector events yet.</p>
              )}
              <div className="activity-footer">
                Latest {data?.events.length ?? 0} of {data?.events_total ?? 0}{" "}
                events · Denver time
              </div>
            </section>
            <section className="panel roadmap" id="roadmap">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">BUILDING WITH INTENT</p>
                  <h2>One checkpoint at a time.</h2>
                </div>
              </div>
              <ol className="roadmap-list">
                <li className="current">
                  <span>
                    <Eye size={16} />
                  </span>
                  <div>
                    <strong>Public market monitor</strong>
                    <p>Public observations, health, and offline replay.</p>
                  </div>
                  <span className="pill success">NOW</span>
                </li>
                <li>
                  <span>2</span>
                  <div>
                    <strong>An honest paper account</strong>
                    <p>Active $100 trial, fees, reservations, recovery.</p>
                  </div>
                </li>
                <li>
                  <span>3</span>
                  <div>
                    <strong>Frozen strategy experiments</strong>
                    <p>Three forward candidates and four-hour reviews.</p>
                  </div>
                </li>
                <li>
                  <span>4</span>
                  <div>
                    <strong>Optional AI research</strong>
                    <p>Bounded explanations and experiments, with approval.</p>
                  </div>
                </li>
              </ol>
              <div className="roadmap-boundary">
                <Check size={15} /> Deterministic execution is the foundation.
              </div>
            </section>
          </div>
          <footer className="page-footer">
            <span>
              TRADING RESEARCH <span className="footer-dot">·</span> LOCAL
              FOUNDATION
            </span>
            <p>
              Background REST capture: {data?.capture.retained ?? 0} /{" "}
              {data?.capture.capacity ?? 2000} records.{" "}
              {data?.capture.evicted ?? 0} older records expired. Export to
              preserve a sample.
            </p>
            <p>
              Background REST exports retain receipt times. The command station
              shows the paper engine’s stream and exchange timestamps.
            </p>
          </footer>
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
