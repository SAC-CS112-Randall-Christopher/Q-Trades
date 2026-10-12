import { StrictMode, Suspense, lazy, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  BrainCircuit,
  ChevronRight,
  CircleHelp,
  Command,
  LockKeyhole,
  Menu,
  Pause,
  Play,
  Search,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import "./style.css";
import { PaperPanel, type PaperSnapshot } from "./PaperPanel";
import { PaperEconomicsPanel } from "./PaperEconomicsPanel";
import { PaperRiskPanel } from "./PaperRiskPanel";
import { LearningPanel } from "./LearningPanel";
import { ProspectivePanel } from "./ProspectivePanel";
import { OptionsPanel, type OptionsSnapshot } from "./OptionsPanel";
import { ModelTrialsPanel } from "./ModelTrialsPanel";
import { ExperimentLab } from "./ExperimentLab";
import { RoleResearchPanel } from "./RoleResearchPanel";
import { inContext, useAccountScope } from "./productNavigation";
import { ResearchActivity } from "./ResearchActivity";
import { ResearchAttention } from "./ResearchAttention";
import { AutonomousPanel } from "./AutonomousPanel";
import { EvidencePanel } from "./EvidencePanel";
import { ReadinessPanel } from "./ReadinessPanel";
import { ResearchOverview } from "./ResearchOverview";
import { ResearchSetup } from "./ResearchSetup";
import { ResearchStoragePanel } from "./ResearchStoragePanel";
import { FeedPanel } from "./FeedPanel";
import { workspaceAreas, workspaceHref, workspaceRoute } from "./workspaceNavigation";
import {
  AccountsView,
  GlobalEntryControl,
  OrdersView,
  PerformanceChart,
  RiskOverview,
} from "./WorkspaceViews";
import "./theme.css";
import "./workspace.css";

const MarketStation = lazy(() =>
  import("./MarketStation").then((module) => ({
    default: module.MarketStation,
  })),
);
const TrainingDataPanel = lazy(() => import("./TrainingDataPanel").then(m => ({default: m.TrainingDataPanel})));
const KnowledgeWorkspace = lazy(() => import("./KnowledgeWorkspace").then(m => ({default: m.KnowledgeWorkspace})));

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

function AccountSafeguards({ paper, unavailable }: { paper?: PaperSnapshot; unavailable: boolean }) {
  const [scope, setScope] = useAccountScope();
  const known = !!paper && (!scope || Object.hasOwn(paper.accounts, scope));
  const scoped = paper && known && scope ? { ...paper, accounts: { [scope]: paper.accounts[scope] } } : paper;
  return <>
    <section className="workspace-card"><div className="card-heading"><h2>Safeguard scope</h2><label>Risk account <select value={scope} onChange={event => setScope(event.target.value)}>
      <option value="">All managed accounts</option>
      {scope && !known && <option value={scope}>{scope} · unavailable</option>}
      {Object.entries(paper?.accounts ?? {}).map(([name, account]) => <option key={name} value={name}>{account.label ?? name}</option>)}
    </select></label></div><p className="fine-print">Entry pauses and loss controls belong to each account. Global entry control remains separate.</p></section>
    {scope && !known ? <p role="status" className="workspace-card">Safeguards for {scope} are unavailable. No other account's controls are shown.</p> :
      <><RiskOverview paper={scoped} unavailable={unavailable} accountName={scope || "primary"} /><PaperRiskPanel key={scope} accounts={scoped?.accounts ?? {}} unavailable={unavailable} focusedAccount={scope || undefined} /></>}
  </>;
}

function App() {
  const [route, setRoute] = useState(() => workspaceRoute(location.hash));
  const { page, lab: labTab } = route;
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
      setRoute(workspaceRoute(location.hash));
      setMenuOpen(false);
      setSearchOpen(false);
      window.scrollTo({ top: 0, behavior: "instant" });
    };
    update();
    window.addEventListener("hashchange", update);
    window.addEventListener("popstate", update);
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
      window.removeEventListener("popstate", update);
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
  const area = workspaceAreas.find(item => item.id === route.area)!;
  const title = area.views.find(item => item[0] === route.view)![1];
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
  const searchPages = workspaceAreas.flatMap(item => item.views.map(([view, label]) => ({
    id: `${item.id}-${view}`, label, description: item.label, icon: item.icon, href: workspaceHref(item.id, view),
  })));
  const matchingPages = searchPages.filter((n) =>
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
          href="#overview"
          aria-label="QTrades AI overview"
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
          {workspaceAreas.map(n => <div className="nav-area" key={n.id}>
            <a href={inContext(workspaceHref(n.id))} className={route.area === n.id ? "nav-primary" : ""}
              aria-current={route.area === n.id ? "true" : undefined}
              onClick={() => { setMenuOpen(false); if (n.id === "accounts") setAccountSearch(""); }}>
              <n.icon size={19} /><span>{n.label}</span>
              {route.area === n.id && <ChevronRight className="nav-chevron" size={14} />}
            </a>
            {route.area === n.id && <div className="nav-subpages" aria-label={`${n.label} pages`}>
              {n.views.map(([id, label]) => <a key={id} href={inContext(workspaceHref(n.id, id))}
                aria-current={route.view === id ? "page" : undefined}>{label}</a>)}
            </div>}
          </div>)}
        </nav>
        <div className="sidebar-note">
          <ShieldCheck size={24} />
          <strong>
            Research today.
            <br />
            Evidence for tomorrow.
          </strong>
          <p>Systematic research. Separate accounts. Measured decisions.</p>
          <a href={inContext("#accounts?view=safeguards")} onClick={() => setMenuOpen(false)}>
            View safeguards <ArrowRight size={14} />
          </a>
        </div>
        <div className="sidebar-footer">
          <span className={`status-dot ${!unavailable ? "good" : ""}`} />
          <span>
            Local workspace<small>Paper only · Cash only</small>
          </span>
          <LockKeyhole size={14} />
        </div>
      </aside>
      <main id="main" tabIndex={-1}>
        {paper?.evidence_kind === "synthetic_qa_continuous" && (
          <p role="status" className="warning">
            Synthetic QA market data · disposable software verification · no
            market-profit evidence
          </p>
        )}
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
              placeholder="Search pages and paper accounts…"
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
                {matchingPages.slice(0, matches ? 12 : 7).map((n) => (
                  <a
                    key={n.id}
                    href={inContext(n.href)}
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
          <nav className="workspace-modes" aria-label="Research and execution environment">
            <a href={inContext("#research")}><BrainCircuit size={15} /> Research</a>
            <span aria-current="true"><ShieldCheck size={15} /> Paper</span>
            <a href={inContext("#results?view=readiness")} title="Review live requirements"><LockKeyhole size={14} /> Live locked</a>
          </nav>
          <div className="topbar-right">
            <div className="worker-state">
              <span className={`status-dot ${!unavailable ? "good" : ""}`} />
              <span>
                {worker}
                <small>{timeLabel(data?.generated_at)}</small>
              </span>
            </div>
            <span className="operator-avatar" title="Local operator">
              <Wallet size={17} />
            </span>
          </div>
        </header>
        <div className="page" data-page={page} data-area={route.area} data-view={route.view}>
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                {area.label} <ChevronRight size={11} /> {title}
              </p>
              <h1>{page === "dashboard" ? "Overview" : title}</h1>
              <p className="subtitle">{area.description}</p>
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
          <nav className="workspace-subnav" aria-label={`${area.label} views`}>
            {area.views.map(([id, label]) => <a key={id} href={inContext(workspaceHref(area.id, id))}
              aria-current={route.view === id ? "page" : undefined}>{label}</a>)}
          </nav>
          {page === "dashboard" && <ResearchOverview paper={paper} unavailable={unavailable} />}
          {page === "attention" && <ResearchAttention />}
          {page === "accounts" && <AccountsView paper={paper} unavailable={unavailable} initialSearch={accountSearch} />}
          {page === "ai-lab" && <>
            {labTab === "autonomous" && <AutonomousPanel />}
            {labTab === "roles" && <RoleResearchPanel integrated />}
            {labTab === "controls" && <><RoleResearchPanel integrated controlsOnly /><details className="workspace-details"><summary>Research supervision and original receipts</summary><ResearchActivity /><ResearchAttention /></details></>}
            {labTab === "knowledge" && <Suspense fallback={<p>Opening persistent knowledge…</p>}><KnowledgeWorkspace /></Suspense>}
            {labTab === "training" && <Suspense fallback={<p>Loading training review…</p>}><TrainingDataPanel /></Suspense>}
            {labTab === "experiments" && <ExperimentLab paper={paper} />}
            {labTab === "learning" && <LearningPanel data={paper?.learning} unavailable={unavailable} />}
            {labTab === "models" && <ModelTrialsPanel />}
            {labTab === "history" && <><EvidencePanel status={paper?.research_evidence} /><ProspectivePanel /></>}
          </>}
          {(page === "markets" || page === "strategies") && <Suspense fallback={<p>Loading market workspace…</p>}>
            <MarketStation strategyOnly={page === "strategies"} view={route.view} />
          </Suspense>}
          {page === "coverage" && <><FeedPanel data={paper ?? {}} /><ResearchStoragePanel /></>}
          {page === "orders" && <OrdersView paper={paper} unavailable={unavailable}
            initialView={route.view === "positions" ? "positions" : route.view === "journal" ? "journal" : "trades"}
            focused={route.view !== "orders"} />}
          {page === "analytics" && (route.view === "costs" ?
            <PaperEconomicsPanel data={paper?.economics} profiles={paper?.execution_profiles} unavailable={unavailable} /> :
            <><PerformanceChart paper={paper} unavailable={unavailable} /><a className="text-link" href={inContext("#results?view=costs")}>Review costs and economics <ArrowRight size={14} /></a></>)}
          {page === "risk" && (route.view === "readiness" ? <ReadinessPanel /> :
            <AccountSafeguards paper={paper} unavailable={unavailable} />)}
          {page === "history" && (route.view === "trials" ?
            <PaperPanel data={paper} disconnected={!!networkError} integrated={false} /> : <>
              <section className="workspace-card"><div className="card-heading"><h2>Recent paper activity</h2><a className="text-link" href={inContext("#history?view=journal")}>Account journal <ArrowRight size={14} /></a></div>
                {unavailable && <p role="status">Last reported activity. Current worker state is unconfirmed.</p>}
                <ol className="event-list">{paper?.events.slice(0, 12).map(event => <li key={event.id}><span className="event-dot" /><p>{event.kind.replaceAll("_", " ")}<small>{JSON.stringify(event.body)}</small></p><time>{timeLabel(new Date(event.at * 1000).toISOString())}</time></li>)}</ol>
                {!paper?.events.length && <p className="empty-state">No activity in the current bounded window. Original records remain in the account journal.</p>}
              </section>
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
            </>)}
          {page === "settings" && <>
            {route.view === "setup" && <ResearchSetup />}
            {route.view === "storage" && <><ResearchStoragePanel />
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
              </>}
            {route.view === "system" && <><ResearchActivity /><FeedPanel data={paper ?? {}} /></>}
            {route.view === "practice" && <><p className="fine-print">Retained practice evidence is separate from current cash-only spot research.</p><OptionsPanel data={data?.options} disconnected={!!networkError} /></>}
          </>}
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
