import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  BarChart3,
  BrainCircuit,
  ChevronRight,
  CircleHelp,
  Command,
  FileClock,
  LayoutDashboard,
  LockKeyhole,
  Menu,
  Pause,
  Play,
  Search,
  Settings2,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import "./style.css";
import { PaperPanel, type PaperSnapshot } from "./PaperPanel";
import { PaperEconomicsPanel } from "./PaperEconomicsPanel";
import { PaperRiskPanel } from "./PaperRiskPanel";
import { LearningPanel } from "./LearningPanel";
import { OptionsPanel, type OptionsSnapshot } from "./OptionsPanel";
import { ModelTrialsPanel } from "./ModelTrialsPanel";
import { ExperimentLab } from "./ExperimentLab";
import { EvidencePanel } from "./EvidencePanel";
import { ReadinessPanel } from "./ReadinessPanel";
import { MarketStation } from "./MarketStation";
import {
  AccountsView,
  DashboardView,
  GlobalEntryControl,
  OrdersView,
  PerformanceChart,
  RiskOverview,
} from "./WorkspaceViews";
import "./theme.css";

type Snapshot = {
  paper?: PaperSnapshot;
  options?: OptionsSnapshot;
  mode: "paper";
  runtime_state: string;
  paused: boolean;
  generated_at: string;
  storage_error: string | null;
  retry_in_seconds: number;
  capture: {
    retained: number;
    total: number;
    evicted: number;
    capacity: number;
  };
  events: { id: number; observed_at: string; message: string }[];
  events_total: number;
};
const navigation = [
  {
    id: "dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    description: "Account performance and current activity",
  },
  {
    id: "accounts",
    label: "Accounts",
    icon: Wallet,
    description: "Isolated paper accounts and campaigns",
  },
  {
    id: "ai-lab",
    label: "AI Lab",
    icon: BrainCircuit,
    description: "Frozen experiments, learning and model trials",
  },
  {
    id: "strategies",
    label: "Strategies",
    icon: Activity,
    description: "Recorded strategy decisions and evidence",
  },
  {
    id: "orders",
    label: "Orders",
    icon: FileClock,
    description: "Positions, pending paper orders and account history",
  },
  {
    id: "analytics",
    label: "Analytics",
    icon: BarChart3,
    description: "Whole-account returns, fees and cost assumptions",
  },
  {
    id: "risk",
    label: "Risk",
    icon: ShieldCheck,
    description: "Entry limits, hard stops and live readiness",
  },
  {
    id: "settings",
    label: "Settings",
    icon: Settings2,
    description: "Local collector, exports and deferred practice",
  },
] as const;
type Page = (typeof navigation)[number]["id"] | "markets";
const aliases: Record<string, Page> = {
  overview: "dashboard",
  experiment: "accounts",
  "paper-campaigns": "accounts",
  "account-economics": "analytics",
  "experiment-lab": "ai-lab",
  "forward-learning": "ai-lab",
  "model-lab": "ai-lab",
  "strategy-lab": "strategies",
  "live-quotes": "markets",
  "live-readiness": "risk",
  operations: "settings",
  research: "ai-lab",
  roadmap: "settings",
  options: "settings",
};
function currentPage(): Page {
  const hash = location.hash.slice(1);
  return (
    aliases[hash] ??
    (navigation.some((n) => n.id === hash) || hash === "markets"
      ? (hash as Page)
      : "dashboard")
  );
}
const timeLabel = (value?: string) =>
  value
    ? new Date(value).toLocaleString("en-US", {
        timeZone: "America/Denver",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }) + " MT"
    : "Waiting for an observation";

function App() {
  const [page, setPage] = useState<Page>(currentPage);
  const [labTab, setLabTab] = useState("experiments");
  const [riskTab, setRiskTab] = useState("limits");
  const [data, setData] = useState<Snapshot | null>(null);
  const [networkError, setNetworkError] = useState<string | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [accountSearch, setAccountSearch] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const update = () => {
      setPage(currentPage());
      setMenuOpen(false);
      setSearchOpen(false);
      if (location.hash === "#model-lab") setLabTab("models");
      else if (location.hash === "#forward-learning") setLabTab("learning");
      else if (location.hash === "#experiment-lab") setLabTab("experiments");
      if (location.hash === "#live-readiness") setRiskTab("readiness");
      window.scrollTo({ top: 0, behavior: "instant" });
    };
    update();
    window.addEventListener("hashchange", update);
    const keyboard = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInput.current?.focus();
        setSearchOpen(true);
      }
      if (event.key === "Escape") {
        setSearchOpen(false);
        setMenuOpen(false);
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => {
      window.removeEventListener("hashchange", update);
      window.removeEventListener("keydown", keyboard);
    };
  }, []);
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
        if (!response.ok) throw new Error();
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
      if (active) timer = setTimeout(load, document.hidden ? 10000 : 3000);
    };
    void load();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  const paper = data?.paper?.enabled ? data.paper : undefined;
  const unavailable =
    !!networkError || !paper?.running || !!paper?.stale || !!paper?.error;
  const worker = networkError
    ? "Disconnected"
    : !data
      ? "Connecting"
      : !paper
        ? "Paper not enabled"
        : paper.error
          ? "Needs attention"
          : !paper.running
            ? "Stopped"
            : paper.stale
              ? "Stale"
              : "Paper worker running";
  const accountCount = Object.keys(paper?.accounts ?? {}).length;
  const title = navigation.find((n) => n.id === page)?.label ?? "Markets";
  const subtitle: Record<Page, string> = {
    dashboard: "Your paper accounts, performance and research — in one place.",
    accounts:
      "Compare isolated accounts. Keep each balance, strategy and loss limit separate.",
    "ai-lab": "Test an idea. Freeze the evidence. Learn from every outcome.",
    strategies: "Understand the rules, the signals and why a strategy acted.",
    orders: "Every position, pending order and retained account event.",
    analytics: "Whole-account results, measured after modeled execution costs.",
    risk: "Review account limits, retained losses and the path to a live decision.",
    settings:
      "Your local workspace, background collection and retained records.",
    markets:
      "Public market observations and the evidence behind paper decisions.",
  };
  async function collectorControl() {
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
        previous ? { ...previous, paused: result.paused } : previous,
      );
    } catch {
      setCommandError(
        "The collector did not confirm this action. Wait for refreshed status before retrying.",
      );
    } finally {
      setPending(false);
    }
  }
  const matches = query.trim().toLowerCase();
  const matchingPages = navigation.filter((n) =>
    `${n.label} ${n.description}`.toLowerCase().includes(matches),
  );
  const matchingAccounts = Object.entries(paper?.accounts ?? {}).filter(
    ([name, a]) =>
      `${name} ${a.label ?? ""} ${a.version}`.toLowerCase().includes(matches),
  );
  function searchAccounts(value: string) {
    setAccountSearch(value);
    setSearchOpen(false);
    location.hash = "accounts";
  }
  return (
    <div className="app-shell q-workspace">
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      {menuOpen && (
        <button
          className="nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <aside className={`sidebar ${menuOpen ? "is-open" : ""}`}>
        <a
          className="brand"
          href="#dashboard"
          aria-label="QTrades AI dashboard"
        >
          <svg className="q-mark" viewBox="0 0 40 40" aria-hidden="true">
            <defs>
              <linearGradient id="q-gradient" x1="0" x2="1" y1="0" y2="1">
                <stop stopColor="#3cdddb" />
                <stop offset="1" stopColor="#466aff" />
              </linearGradient>
            </defs>
            <circle
              cx="19"
              cy="18"
              r="12"
              fill="none"
              stroke="url(#q-gradient)"
              strokeWidth="6"
            />
            <path
              d="m25 25 9 9"
              stroke="#5984ff"
              strokeWidth="6"
              strokeLinecap="round"
            />
          </svg>
          <span>
            QTrades <b>AI</b>
          </span>
        </a>
        <p className="workspace-label">LOCAL RESEARCH WORKSPACE</p>
        <nav aria-label="Main navigation">
          {navigation.map((n) => (
            <a
              key={n.id}
              href={`#${n.id}`}
              className={page === n.id ? "nav-primary" : ""}
              aria-current={page === n.id ? "page" : undefined}
              onClick={() => {
                setMenuOpen(false);
                if (n.id === "accounts") setAccountSearch("");
              }}
            >
              <n.icon size={19} />
              <span>{n.label}</span>
              {n.id === "accounts" && (
                <span className="nav-count">{accountCount || "—"}</span>
              )}
            </a>
          ))}
          <a
            href="#markets"
            onClick={() => setMenuOpen(false)}
            className={page === "markets" ? "nav-primary" : ""}
            aria-current={page === "markets" ? "page" : undefined}
          >
            <Activity size={19} />
            <span>Markets</span>
          </a>
        </nav>
        <div className="sidebar-note">
          <ShieldCheck size={24} />
          <strong>
            Paper today.
            <br />
            Evidence for tomorrow.
          </strong>
          <p>Separate accounts. Frozen research. Human approval.</p>
          <a href="#risk" onClick={() => setMenuOpen(false)}>
            View safeguards <ArrowRight size={14} />
          </a>
        </div>
        <div className="sidebar-footer">
          <span className="status-dot good" />
          <span>
            Local workspace<small>Paper only · Cash only</small>
          </span>
          <LockKeyhole size={14} />
        </div>
      </aside>
      <main id="main" tabIndex={-1}>
        <header className="topbar">
          <button
            className="mobile-nav"
            aria-label={menuOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(!menuOpen)}
          >
            {menuOpen ? <X size={21} /> : <Menu size={21} />}
          </button>
          <div className="workspace-search">
            <Search size={18} />
            <input
              ref={searchInput}
              type="search"
              placeholder="Search accounts, strategies or pages…"
              aria-label="Search workspace"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setSearchOpen(true);
              }}
              onFocus={() => setSearchOpen(true)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && query.trim())
                  searchAccounts(query.trim());
              }}
            />
            <kbd>
              <Command size={11} /> K
            </kbd>
            {searchOpen && (
              <div
                className="search-results"
                aria-label="Workspace search results"
              >
                <div className="search-results-heading">
                  {matches ? "Matching pages and accounts" : "Quick navigation"}
                  <button
                    type="button"
                    aria-label="Close search"
                    onClick={() => setSearchOpen(false)}
                  >
                    <X size={15} />
                  </button>
                </div>
                {matchingPages.map((n) => (
                  <a
                    key={n.id}
                    href={`#${n.id}`}
                    onClick={() => setSearchOpen(false)}
                  >
                    <n.icon size={17} />
                    <span>
                      {n.label}
                      <small>{n.description}</small>
                    </span>
                    <ChevronRight size={14} />
                  </a>
                ))}
                {matches &&
                  matchingAccounts.slice(0, 5).map(([name, a]) => (
                    <button
                      key={name}
                      onClick={() => searchAccounts(a.label ?? name)}
                    >
                      <Wallet size={17} />
                      <span>
                        {a.label ?? name}
                        <small>{a.version}</small>
                      </span>
                      <ChevronRight size={14} />
                    </button>
                  ))}
                {matches && (
                  <button
                    className="search-all"
                    onClick={() => searchAccounts(query.trim())}
                  >
                    Search all {accountCount} accounts <ArrowRight size={14} />
                  </button>
                )}
              </div>
            )}
          </div>
          <div className="topbar-right">
            <div className="worker-state">
              <span className={`status-dot ${!unavailable ? "good" : ""}`} />
              <span>
                {worker}
                <small>{timeLabel(data?.generated_at)}</small>
              </span>
            </div>
            <span className="pill paper">PAPER ONLY</span>
            <span className="operator-avatar" title="Local operator">
              CR
            </span>
          </div>
        </header>
        <div className="page" data-page={page}>
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                WORKSPACE <ChevronRight size={11} /> {title.toUpperCase()}
              </p>
              <h1>{page === "accounts" ? "Accounts control center" : title}</h1>
              <p className="subtitle">{subtitle[page]}</p>
            </div>
            <div className="heading-actions">
              {page === "dashboard" && (
                <a className="button secondary" href="#markets">
                  <Activity size={16} /> Explore markets
                </a>
              )}
              {(page === "accounts" || page === "risk") && paper && (
                <GlobalEntryControl paper={paper} unavailable={unavailable} />
              )}
            </div>
          </div>
          {(networkError ||
            commandError ||
            data?.storage_error ||
            paper?.error) && (
            <div className="error-banner" role="alert">
              <CircleHelp size={18} />
              {networkError ||
                commandError ||
                data?.storage_error ||
                paper?.error}
            </div>
          )}
          {!data && (
            <div className="connection-note" role="status">
              Connecting to your local workspace…
            </div>
          )}
          {paper?.stale && !networkError && (
            <div className="error-banner" role="alert">
              The paper worker is stale. Current values are unconfirmed;
              historical evidence stays available.
            </div>
          )}
          {page === "dashboard" && (
            <>
              <DashboardView paper={paper} unavailable={unavailable} />
            </>
          )}
          {page === "accounts" && (
            <>
              <AccountsView
                paper={paper}
                unavailable={unavailable}
                initialSearch={accountSearch}
              />
              <details className="workspace-details">
                <summary>Original Tier 3 trial and review history</summary>
                <PaperPanel
                  data={paper}
                  disconnected={!!networkError}
                  integrated={false}
                />
              </details>
            </>
          )}
          {page === "ai-lab" && (
            <>
              <div className="workspace-tabs" aria-label="AI Lab views">
                {[
                  ["experiments", "Numerical research"],
                  ["learning", "Forward learning"],
                  ["history", "Historical matches"],
                  ["models", "Local model trials"],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    className={labTab === id ? "selected" : ""}
                    aria-pressed={labTab === id}
                    onClick={() => setLabTab(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {labTab === "experiments" && <ExperimentLab paper={paper} />}
              {labTab === "learning" && (
                <LearningPanel
                  data={paper?.learning}
                  unavailable={unavailable}
                />
              )}
              {labTab === "models" && <ModelTrialsPanel />}
              {labTab === "history" && <EvidencePanel status={paper?.research_evidence} />}
            </>
          )}
          {(page === "markets" || page === "strategies") && (
            <MarketStation strategyOnly={page === "strategies"} />
          )}
          {page === "orders" && (
            <OrdersView paper={paper} unavailable={unavailable} />
          )}
          {page === "analytics" && (
            <>
              <PerformanceChart paper={paper} unavailable={unavailable} />
              <PaperEconomicsPanel
                data={paper?.economics}
                profiles={paper?.execution_profiles}
                unavailable={unavailable}
              />
            </>
          )}
          {page === "risk" && (
            <>
              <div className="workspace-tabs" aria-label="Risk views">
                <button
                  className={riskTab === "limits" ? "selected" : ""}
                  aria-pressed={riskTab === "limits"}
                  onClick={() => setRiskTab("limits")}
                >
                  Account safeguards
                </button>
                <button
                  className={riskTab === "readiness" ? "selected" : ""}
                  aria-pressed={riskTab === "readiness"}
                  onClick={() => setRiskTab("readiness")}
                >
                  Live readiness
                </button>
              </div>
              {riskTab === "limits" ? (
                <>
                  <RiskOverview paper={paper} unavailable={unavailable} />
                  <PaperRiskPanel
                    accounts={paper?.accounts ?? {}}
                    unavailable={unavailable}
                  />
                </>
              ) : (
                <ReadinessPanel />
              )}
            </>
          )}
          {page === "settings" && (
            <>
              <div className="settings-grid">
                <section className="workspace-card">
                  <div className="card-heading">
                    <h2>Background collection</h2>
                    <span className="pill neutral">
                      {data?.paused
                        ? "Paused"
                        : (data?.runtime_state?.replaceAll("_", " ") ??
                          "Connecting")}
                    </span>
                  </div>
                  <p>
                    Public REST observations for export and offline replay. The
                    paper engine uses its own feed and entry controls.
                  </p>
                  <dl className="summary-values">
                    <div>
                      <dt>Retained observations</dt>
                      <dd>{data?.capture.retained.toLocaleString() ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>Capture capacity</dt>
                      <dd>{data?.capture.capacity.toLocaleString() ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>Expired observations</dt>
                      <dd>{data?.capture.evicted.toLocaleString() ?? "—"}</dd>
                    </div>
                  </dl>
                  <div className="heading-actions">
                    <button
                      className="button secondary"
                      disabled={!data || pending || !!networkError}
                      onClick={() => void collectorControl()}
                    >
                      {data?.paused ? <Play size={15} /> : <Pause size={15} />}
                      {pending
                        ? "Confirming…"
                        : data?.paused
                          ? "Resume collection"
                          : "Pause collection"}
                    </button>
                    <a className="button primary" href="/api/capture">
                      <ArrowDownToLine size={15} /> Export observations
                    </a>
                  </div>
                  {!!data?.retry_in_seconds && (
                    <p role="status">
                      Retry cooldown: {data.retry_in_seconds}s remaining.
                    </p>
                  )}
                  <p className="fine-print">
                    Pause is saved across restarts. Closing this dashboard keeps
                    the local worker running.
                  </p>
                </section>
                <section className="workspace-card">
                  <div className="card-heading">
                    <h2>Workspace boundaries</h2>
                    <LockKeyhole size={19} />
                  </div>
                  <div className="guardrail-list">
                    <p>
                      <ShieldCheck size={19} />
                      <span>
                        <strong>Paper only</strong>Simulated orders and separate
                        hypothetical balances.
                      </span>
                    </p>
                    <p>
                      <Wallet size={19} />
                      <span>
                        <strong>Cash only</strong>No new margin, borrowing or
                        automatic top-ups.
                      </span>
                    </p>
                    <p>
                      <BrainCircuit size={19} />
                      <span>
                        <strong>Research needs evidence</strong>Frozen results
                        and explicit paper-role approval.
                      </span>
                    </p>
                    <p>
                      <LockKeyhole size={19} />
                      <span>
                        <strong>Local operation</strong>Public market feeds.
                        Private records stay on this computer.
                      </span>
                    </p>
                  </div>
                  <a href="#live-readiness" className="text-link">
                    Review live blockers <ArrowRight size={14} />
                  </a>
                </section>
              </div>
              <section className="workspace-card">
                <div className="card-heading">
                  <h2>Collector activity</h2>
                  <span className="subtle-note">
                    Latest {data?.events.length ?? 0} of{" "}
                    {data?.events_total ?? 0}
                  </span>
                </div>
                <ol className="event-list">
                  {data?.events.map((e) => (
                    <li key={e.id}>
                      <span className="event-dot" />
                      <p>{e.message}</p>
                      <time>{timeLabel(e.observed_at)}</time>
                    </li>
                  ))}
                </ol>
                {!data?.events.length && (
                  <p className="empty-state">
                    No collector activity has been recorded.
                  </p>
                )}
              </section>
              <details className="workspace-details">
                <summary>Historical options practice</summary>
                <p className="fine-print">
                  Retained practice evidence is separate from the current
                  cash-only spot research.
                </p>
                <OptionsPanel
                  data={data?.options}
                  disconnected={!!networkError}
                />
              </details>
            </>
          )}
          <footer className="page-footer">
            <span>
              <LockKeyhole size={12} /> LOCAL WORKSPACE <span>·</span> PAPER
              RESEARCH
            </span>
            <p>
              Observed {timeLabel(data?.generated_at)}. Paper results do not
              establish live returns.
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
