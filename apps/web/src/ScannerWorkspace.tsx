import { useEffect, useRef, useState } from "react";
import { useEvidenceRead } from "./useEvidenceRead";
import { ScannerChartGrid, type ScannerChartFocus } from "./CandleWorkspace";
import { DailyAnalyzer, validDaily, type DailySelection } from "./DailyAnalyzer";
import { PatternComparisonPanel, type PatternComparisonSelection, type PatternComparisonFinding } from "./PatternComparisonPanel";
import "./scanner-workspace.css";

type Frame = "5m" | "15m" | "30m" | "1h" | "4h";
type Kind = "levels" | "patterns" | "alerts";
type RosterRow = { symbol: string; eligible: boolean; reason: string; selected: boolean; queued: boolean };
type Progress = { symbol: string; timeframe: Frame; requested_start_ms: number; cutoff_ms: number;
  cursor_ms: number; expected_bars: number; observed_bars: number; missing_bars: number;
  pages: number; status: string; error: string | null; gap_count?: number };
type Campaign = { id: string; version?: string;
  requested_start_ms?: number; cutoff_ms?: number; symbols?: string[] };
type CampaignSummary = { id: string; created: number; market_count: number; requested_days: number; timeframes: Frame[] };
type ScannerState = { daily_selection?: DailySelection; version: "year-pattern-scanner-v1"; enabled: boolean; campaign: Campaign | null;
  current_campaign_id: string | null; is_current: boolean;
  revision: number; status: string; reason: string | null;
  roster: { observed_at: number; total: number; eligible: number; selected: number; queued: number; rows: RosterRow[] };
  progress: Progress[]; progress_total: number; progress_omitted: number;
  progress_counts: Record<string, number>; limits: Record<string, unknown>; authority: string };
type Command = { action: "prepare" | "start" | "pause" | "daily_enable" | "daily_pause"; request_id: string;
  symbols?: string[]; campaign_id?: string; expected_revision?: number };
type Receipt = { request_id: string; action: Command["action"]; campaign_id: string; revision: number;
  applied_at: number; applied: true; policy?: string; previous_campaign_id?: string | null; current_status?: ScannerState };
type Row = Record<string, unknown> & { seq: number; id: string; symbol?: string; timeframe?: Frame };
type Page = { campaign_id: string; symbol: string; timeframe: Frame; rows: Row[]; total: number; next_before: number | null };
type ProgressPage = { campaign_id: string; rows: Progress[]; total: number; next_before: number | null };
const frames: Frame[] = ["5m", "15m", "30m", "1h", "4h"];
const endpoint = "/api/research/pattern-scanner";
const pendingKey = "qtrades-year-pattern-scanner-pending-v1";
const isPause = (action: Command["action"]) => action === "pause" || action === "daily_pause";
const safeSymbol = (symbol: unknown): symbol is string => typeof symbol === "string" && /^[A-Z0-9]{3,24}$/.test(symbol);
const number = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : "Unknown";
const date = (ms: unknown) => typeof ms === "number" && Number.isFinite(ms) ? new Date(ms).toLocaleString() : "Unknown";
const words = (value: unknown) => typeof value === "string" ? value.replaceAll("_", " ") : "Unknown";
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const body = (row: Row) => object(row.body) ? { ...row, ...row.body } : row;

function pendingCommands(): { commands: Command[]; error: string | null } {
  try {
    const raw = localStorage.getItem(pendingKey);
    if (!raw) return { commands: [], error: null };
    const values = JSON.parse(raw) as Command[];
    if (!Array.isArray(values) || values.length > 2 || values.some(command => !command ||
      !["prepare", "start", "pause", "daily_enable", "daily_pause"].includes(command.action) ||
      !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(command.request_id) ||
      command.action === "prepare" && (!Array.isArray(command.symbols) || !command.symbols.length || command.symbols.length > 2000 || !command.symbols.every(safeSymbol)) ||
      command.action.startsWith("daily_") && command.symbols != null ||
      command.action === "daily_enable" && command.campaign_id != null && (typeof command.campaign_id !== "string" || !/^patterns-[a-f0-9]{24}$/.test(command.campaign_id)) ||
      command.action !== "prepare" && command.action !== "daily_enable" && (typeof command.campaign_id !== "string" || !command.campaign_id) ||
      (command.action === "start" || command.action === "daily_enable") && (!Number.isSafeInteger(command.expected_revision) || command.expected_revision! < 0)) ||
      new Set(values.map(command => isPause(command.action) ? "pause" : "setup")).size !== values.length) throw new Error();
    return { commands: values, error: null };
  } catch { return { commands: [], error: "Saved scanner control is unreadable. Its outcome must be reconciled before a new control." }; }
}

async function controlLock(work: () => void, waitForTerminalRefusal = false) {
  if (!navigator.locks) throw new Error("This window cannot safely retain scanner controls for recovery.");
  await navigator.locks.request(pendingKey, { ifAvailable: !waitForTerminalRefusal }, lock => {
    if (!lock) throw new Error("Another window is saving a scanner control. Its original request remains retained.");
    work();
  });
}

function validateState(value: ScannerState) {
  if (value?.version !== "year-pattern-scanner-v1" || typeof value.enabled !== "boolean" ||
    !(value.campaign === null || object(value.campaign)) || typeof value.is_current !== "boolean" ||
    !(value.current_campaign_id === null || typeof value.current_campaign_id === "string") ||
    !Array.isArray(value.roster?.rows) || !Array.isArray(value.progress) || !object(value.limits) ||
    typeof value.status !== "string" || !Number.isSafeInteger(value.progress_total) ||
    value.progress_total < value.progress.length || !object(value.progress_counts) ||
    value.roster.rows.some(row => !safeSymbol(row.symbol) || typeof row.eligible !== "boolean" ||
      typeof row.selected !== "boolean" || typeof row.queued !== "boolean" || typeof row.reason !== "string") ||
    !Number.isSafeInteger(value.revision) || value.revision < 0 ||
    value.campaign && typeof value.campaign.id !== "string") {
    throw new Error("Scanner status is incomplete. Preparation and readiness remain unknown.");
  }
}

export function ScannerWorkspace({ symbol, onInspect, onChooseMarket }: { symbol: string; onInspect: (symbol: string) => void; onChooseMarket: (symbol: string) => void }) {
  const [state, setState] = useState<ScannerState | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [checked, setChecked] = useState<number | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [rosterPage, setRosterPage] = useState(0);
  const [initial] = useState(pendingCommands);
  const [pending, setPending] = useState(initial.commands);
  const [storageError, setStorageError] = useState(initial.error);
  const [controlError, setControlError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState<Kind>("levels");
  const [market, setMarket] = useState(symbol);
  const [frame, setFrame] = useState<Frame>("5m");
  const [chartFocus, setChartFocus] = useState<ScannerChartFocus | null>(null);
  const [comparison, setComparison] = useState<PatternComparisonSelection | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [pageBusy, setPageBusy] = useState(false);
  const [progressPage, setProgressPage] = useState<ProgressPage | null>(null);
  const [progressError, setProgressError] = useState<string | null>(null);
  const [progressBusy, setProgressBusy] = useState(false);
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [savedCampaign, setSavedCampaign] = useState("");
  const [historicalState, setHistoricalState] = useState<ScannerState | null>(null);
  const [requestedCampaign, setRequestedCampaign] = useState<string | null>(null);
  const [campaignError, setCampaignError] = useState<string | null>(null);
  const [campaignBusy, setCampaignBusy] = useState(false);
  const statusAbort = useRef<AbortController | null>(null);
  const refreshAgain = useRef<() => void>(() => {});
  const mounted = useRef(true);
  const sending = useRef(false);
  const details = useEvidenceRead();
  const progressRead = useEvidenceRead();
  const campaignRead = useEvidenceRead();
  const displayState = requestedCampaign ? historicalState : state;
  const campaign = displayState?.campaign;
  useEffect(() => { setMarket(symbol); setChartFocus(null); }, [symbol]);
  useEffect(() => { setChartFocus(null); }, [campaign?.id, market]);
  const pageScope = `${campaign?.id ?? ""}:${kind}:${market}:${frame}`;
  const currentPageScope = useRef(pageScope); currentPageScope.current = pageScope;
  useEffect(() => {
    mounted.current = true;
    const listener = (event: StorageEvent) => {
      if (event.key !== pendingKey) return;
      const value = pendingCommands(); setPending(value.commands); setStorageError(value.error);
    };
    addEventListener("storage", listener);
    return () => { mounted.current = false; removeEventListener("storage", listener); };
  }, []);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      if (!active || statusAbort.current) return;
      if (document.hidden) { timer = setTimeout(() => void refresh(), 1000); return; }
      const controller = new AbortController(); statusAbort.current = controller;
      try {
        const response = await fetch(endpoint, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(7000)]) });
        if (!response.ok) throw new Error("Scanner status is unavailable. Last observed progress may be stale.");
        const value = await response.json() as ScannerState; validateState(value);
        if (active) { setState(value); setStatusError(null); setChecked(Date.now()); }
      } catch (cause) { if (active) setStatusError(cause instanceof Error ? cause.message : "Scanner status unavailable."); }
      finally { statusAbort.current = null; if (active) timer = setTimeout(() => void refresh(), 5000); }
    };
    refreshAgain.current = () => { if (timer) clearTimeout(timer); void refresh(); };
    void refresh();
    return () => { active = false; if (timer) clearTimeout(timer); statusAbort.current?.abort(); };
  }, []);
  useEffect(() => { details.cancel(); setPage(null); setPageError(null); setPageBusy(false); }, [pageScope, details.cancel]);
  useEffect(() => { progressRead.cancel(); setProgressPage(null); setProgressError(null); setProgressBusy(false); }, [campaign?.id, progressRead.cancel]);

  async function acceptReceipt(value: Receipt, command: Command) {
    const dailyControl = command.action === "daily_enable" || command.action === "daily_pause";
    const dailyBound = !dailyControl || value?.policy === "daily-pattern-research-v1" &&
      value.previous_campaign_id === (command.campaign_id ?? null);
    const newDailyCampaign = command.action === "daily_enable" && dailyBound &&
      typeof value?.campaign_id === "string" && /^patterns-[a-f0-9]{24}$/.test(value.campaign_id);
    if (value?.request_id !== command.request_id || value.action !== command.action || value.applied !== true ||
      typeof value.campaign_id !== "string" || !Number.isSafeInteger(value.revision) || !dailyBound ||
      command.campaign_id != null && value.campaign_id !== command.campaign_id && !newDailyCampaign) throw new Error("The control acknowledgment does not match the original request. Its outcome remains unknown.");
    await controlLock(() => {
      const saved = pendingCommands(); if (saved.error) throw new Error(saved.error);
      const original = saved.commands.find(item => item.request_id === command.request_id);
      if (!original || JSON.stringify(original) !== JSON.stringify(command)) throw new Error("Saved control identity changed in another window. Its record remains retained.");
      const rest = saved.commands.filter(item => item.request_id !== command.request_id);
      if (rest.length) localStorage.setItem(pendingKey, JSON.stringify(rest)); else localStorage.removeItem(pendingKey);
    });
    if (!mounted.current) return;
    setPending(pendingCommands().commands);
    setNotice(`${words(command.action)} was acknowledged for the original request. Preparation and current evaluation still follow the recorded progress.`);
    if (value.current_status) {
      try { validateState(value.current_status); setState(value.current_status); setStatusError(null); setChecked(Date.now()); }
      catch { setStatusError("The original control was acknowledged, but current scanner status is unavailable."); }
    }
    refreshAgain.current();
  }

  async function control(action: Command["action"]) {
    if (sending.current || storageError || pending.some(command => isPause(action) ? isPause(command.action) : true)) return;
    const command: Command = { action, request_id: crypto.randomUUID() };
    if (action === "prepare") command.symbols = [...chosen].sort();
    else {
      if (!state?.campaign && action !== "daily_enable") return;
      if (state?.campaign) command.campaign_id = state.campaign.id;
      if (action === "start" || action === "daily_enable") command.expected_revision = state?.revision ?? 0;
    }
    sending.current = true; setBusy(true); setControlError(null); setNotice(null);
    const holder: { response: Promise<Response> | null } = { response: null };
    try {
      await controlLock(() => {
        if (!mounted.current) throw new Error("This view closed before the control was saved. No request was sent.");
        const saved = pendingCommands(); if (saved.error) throw new Error(saved.error);
        if (saved.commands.some(item => isPause(action) ? isPause(item.action) : true)) throw new Error("An original control is awaiting acknowledgment. Find its saved result first.");
        localStorage.setItem(pendingKey, JSON.stringify([...saved.commands, command]));
        holder.response = fetch(`${endpoint}/control`, { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" },
          body: JSON.stringify(command), signal: AbortSignal.timeout(15000) });
      });
      if (mounted.current) setPending(pendingCommands().commands);
      if (!holder.response) throw new Error("No scanner control was dispatched.");
      const response = await holder.response;
      const value = await response.json() as Receipt & { detail?: string };
      if ([400, 403, 409, 422].includes(response.status)) {
        await controlLock(() => {
          const saved = pendingCommands(); if (saved.error) throw new Error(saved.error);
          const original = saved.commands.find(item => item.request_id === command.request_id);
          if (!original || JSON.stringify(original) !== JSON.stringify(command)) throw new Error("Saved control identity changed; recovery remains retained.");
          localStorage.setItem("qtrades-year-pattern-scanner-refusal-v1", JSON.stringify({ command, status: response.status, detail: value.detail, at: Date.now() }));
          const rest = saved.commands.filter(item => item.request_id !== command.request_id);
          if (rest.length) localStorage.setItem(pendingKey, JSON.stringify(rest)); else localStorage.removeItem(pendingKey);
        }, true);
        if (mounted.current) { setPending(pendingCommands().commands); setControlError(typeof value.detail === "string" ? value.detail : "The original control was refused before changing scanner state."); }
        refreshAgain.current(); return;
      }
      if (!response.ok) throw new Error("The scanner control was not confirmed. Its original request remains saved.");
      await acceptReceipt(value, command);
    } catch (cause) {
      if (mounted.current) {
        const saved = pendingCommands(); setPending(saved.commands); setStorageError(saved.error);
        setControlError(`${cause instanceof Error ? cause.message : "Control outcome unknown."} ${saved.commands.some(item => item.request_id === command.request_id) ? "Find the exact saved result; no automatic repeat is sent." : holder.response ? "The dispatched outcome remains unconfirmed." : "No new control was sent."}`);
      }
    } finally { sending.current = false; if (mounted.current) setBusy(false); }
  }

  async function recover(command: Command) {
    if (sending.current) return;
    sending.current = true; setBusy(true); setControlError(null);
    try {
      const response = await fetch(`${endpoint}/requests/${encodeURIComponent(command.request_id)}`, { cache: "no-store", signal: AbortSignal.timeout(7000) });
      if (response.status === 404) throw new Error("No original control receipt is available yet; the earlier request may still apply. Its outcome remains unknown.");
      if (!response.ok) throw new Error("The exact saved control cannot be reopened right now.");
      await acceptReceipt(await response.json() as Receipt, command);
    } catch (cause) { if (mounted.current) setControlError(cause instanceof Error ? cause.message : "Recovery unavailable."); }
    finally { sending.current = false; if (mounted.current) setBusy(false); }
  }

  async function inspect(before?: number | null) {
    if (!campaign) return;
    const scope = pageScope; const request = details.begin(10000);
    const query = new URLSearchParams({ campaign_id: campaign.id, symbol: market, timeframe: frame });
    if (before != null) query.set("before", String(before));
    setPageBusy(true); setPageError(null);
    try {
      const response = await fetch(`${endpoint}/${kind}?${query}`, { cache: "no-store", signal: request.signal });
      if (!response.ok) throw new Error("Saved scanner evidence is unavailable. No empty successful page was substituted.");
      const value = await response.json() as Page;
      if (value.campaign_id !== campaign.id || value.symbol !== market || value.timeframe !== frame ||
        !Array.isArray(value.rows) || value.rows.length > 100 || !Number.isSafeInteger(value.total) || value.total < value.rows.length ||
        value.rows.some(row => !Number.isSafeInteger(row.seq) || row.symbol != null && row.symbol !== market || row.timeframe != null && row.timeframe !== frame)) throw new Error("Saved evidence scope differs from this campaign, market or interval.");
      if (request.isCurrent() && currentPageScope.current === scope) setPage(value);
    } catch (cause) { if (request.isCurrent() && currentPageScope.current === scope) { setPage(null); setPageError(cause instanceof Error ? cause.message : "Evidence unavailable."); } }
    finally { if (request.isCurrent() && currentPageScope.current === scope) setPageBusy(false); }
  }

  async function inspectProgress(before?: number | null) {
    if (!campaign) return;
    const id = campaign.id; const request = progressRead.begin(10000);
    const query = new URLSearchParams({ campaign_id: id }); if (before != null) query.set("before", String(before));
    setProgressBusy(true); setProgressError(null);
    try {
      const response = await fetch(`${endpoint}/progress?${query}`, { cache: "no-store", signal: request.signal });
      if (!response.ok) throw new Error("Full preparation progress is unavailable; saved coverage was not substituted.");
      const value = await response.json() as ProgressPage;
      if (value.campaign_id !== id || !Array.isArray(value.rows) || value.rows.length > 100 || !Number.isSafeInteger(value.total)) throw new Error("Preparation progress identity differs.");
      if (request.isCurrent()) setProgressPage(value);
    } catch (cause) { if (request.isCurrent()) { setProgressPage(null); setProgressError(cause instanceof Error ? cause.message : "Progress unavailable."); } }
    finally { if (request.isCurrent()) setProgressBusy(false); }
  }

  async function readCampaigns() {
    const request = campaignRead.begin(7000); setCampaignBusy(true); setCampaignError(null);
    try {
      const response = await fetch(`${endpoint}/campaigns`, { cache: "no-store", signal: request.signal });
      if (!response.ok) throw new Error("Saved campaign list is unavailable; no empty list was substituted.");
      const value = await response.json() as { rows: CampaignSummary[]; total: number };
      if (!Array.isArray(value.rows) || value.rows.length > 32 || value.total !== value.rows.length ||
        value.rows.some(row => typeof row.id !== "string" || !Number.isFinite(row.created) || !Number.isSafeInteger(row.market_count))) throw new Error("Saved campaign identity is incomplete.");
      if (request.isCurrent()) { setCampaigns(value.rows); setSavedCampaign(old => value.rows.some(row => row.id === old) ? old : value.rows[0]?.id ?? ""); }
    } catch (cause) { if (request.isCurrent()) setCampaignError(cause instanceof Error ? cause.message : "Saved campaigns unavailable."); }
    finally { if (request.isCurrent()) setCampaignBusy(false); }
  }

  async function reopenCampaign(id = savedCampaign, remember = true) {
    if (!id) return;
    setRequestedCampaign(id); setHistoricalState(null);
    if (remember) {
      const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
      if (params.get("scanner_campaign") !== id) for (const key of [...params.keys()]) {
        if (key.startsWith("scanner_chart_")) params.delete(key);
      }
      params.set("scanner_campaign", id);
      history.replaceState(null, "", `#markets?${params}`);
    }
    const request = campaignRead.begin(7000); setCampaignBusy(true); setCampaignError(null);
    try {
      const response = await fetch(`${endpoint}?campaign_id=${encodeURIComponent(id)}`, { cache: "no-store", signal: request.signal });
      if (!response.ok) throw new Error("The original campaign cannot be reopened right now.");
      const value = await response.json() as ScannerState; validateState(value);
      if (value.campaign?.id !== id) throw new Error("Saved campaign identity differs from the selected record.");
      if (request.isCurrent()) setHistoricalState(value);
    } catch (cause) { if (request.isCurrent()) setCampaignError(cause instanceof Error ? cause.message : "Campaign unavailable."); }
    finally { if (request.isCurrent()) setCampaignBusy(false); }
  }

  useEffect(() => {
    const restore = () => {
      const id = new URLSearchParams(location.hash.split("?")[1] ?? "").get("scanner_campaign");
      if (id == null) {
        campaignRead.cancel(); setRequestedCampaign(null); setHistoricalState(null); setCampaignBusy(false); setCampaignError(null);
      } else if (!/^patterns-[a-f0-9]{24}$/.test(id)) {
        campaignRead.cancel(); setRequestedCampaign(id); setHistoricalState(null); setCampaignBusy(false); setCampaignError("The saved campaign identity is invalid. No current campaign was substituted.");
      } else void reopenCampaign(id, false);
    };
    restore(); addEventListener("hashchange", restore); addEventListener("popstate", restore);
    return () => { removeEventListener("hashchange", restore); removeEventListener("popstate", restore); };
  }, [campaignRead.cancel]);

  function openDaily(campaignId: string, nextSymbol: string, snapshotId: string,
    evidence?: { timeframe: Frame; kind: "patterns" | "alerts"; seq: number; body: Record<string, unknown>; progress_sha256?: string }) {
    onChooseMarket(nextSymbol);
    const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
    for (const key of [...params.keys()]) if (key.startsWith("scanner_chart_")) params.delete(key);
    params.set("symbol", nextSymbol); params.set("scanner_campaign", campaignId); params.set("daily_shortlist", snapshotId);
    history.replaceState(null, "", `#markets?${params}`);
    setMarket(nextSymbol);
    void reopenCampaign(campaignId, false);
    if (evidence && typeof evidence.body.bar_open_ms === "number") {
      // URL scope restores the original event after the exact campaign read settles.
      params.set("scanner_chart_frame", evidence.timeframe); params.set("scanner_chart_at_ms", String(evidence.body.bar_open_ms));
      params.set("scanner_chart_kind", evidence.kind); params.set("scanner_chart_seq", String(evidence.seq));
      if (evidence.progress_sha256 && /^[a-f0-9]{64}$/.test(evidence.progress_sha256)) params.set("scanner_chart_progress_sha256", evidence.progress_sha256);
      history.replaceState(null, "", `#markets?${params}`);
    }
    document.getElementById("scanner-chart-grid")?.scrollIntoView({ block: "start" });
  }

  function reviewComparison(selection: PatternComparisonSelection) {
    const params = new URLSearchParams(location.hash.split("?")[1] ?? ""); params.delete("pattern_comparison_request");
    history.replaceState(null, "", `#markets?${params}`);
    setComparison({ daily_id: selection.daily_id, symbol: selection.symbol, timeframe: selection.timeframe,
      event_kind: selection.event_kind, event_seq: selection.event_seq });
    // This is a read-only source review; preparation remains a separate explicit button.
    requestAnimationFrame(() => document.getElementById("pattern-comparison-panel")?.scrollIntoView({ block: "start" }));
  }
  function openComparisonFinding(finding: PatternComparisonFinding) {
    const original = finding.selection;
    openDaily(finding.campaign_id, original.symbol, original.daily_id, { timeframe: original.timeframe,
      kind: original.event_kind, seq: original.event_seq, body: finding.original_event,
      progress_sha256: finding.coverage.find(row => row.timeframe === original.timeframe)?.progress_sha256 ?? undefined });
    // replaceState alone does not notify the daily shortlist's ordinary URL restore.
    dispatchEvent(new HashChangeEvent("hashchange"));
  }

  const daily = validDaily(state?.daily_selection) ? state.daily_selection : null;
  const dailyCampaign = state?.campaign?.version === "year-pattern-scanner-v2";
  const roster = state?.roster.rows ?? [];
  const chosen = selected.filter(name => roster.some(row => row.symbol === name && row.eligible));
  const prepareAllowed = !statusError && state != null && chosen.length > 0 && chosen.length <= 2000 && !state.enabled && !dailyCampaign;
  const setupBusy = busy || !!storageError || pending.length > 0 || !navigator.locks;
  const visibleRows = roster.slice(rosterPage * 24, rosterPage * 24 + 24);
  const visibleProgress = progressPage?.rows ?? displayState?.progress ?? [];
  return <section className="scanner-workspace" aria-labelledby="pattern-scanner-title">
    <header><div><p className="station-kicker">SHARED HISTORY · DESCRIPTIVE ALERTS</p><h3 id="pattern-scanner-title">Year pattern scanner</h3></div><span>5m · 15m · 30m · 1h · 4h</span></header>
    <p>Prepare native closed candles for a fixed 365-day window, then inspect recorded levels and pattern candidates across eligible USD markets. Historical patterns describe price behavior; they do not establish validated profitability or place orders.</p>
    <p>Automatic pattern research currently supports only saved BTCUSD 5m resistance breakouts or retests with recorded volume confirmation. It checks a bounded set of recent daily captures, original archives, distinct-event spacing and current executable inputs. Other markets, timeframes and chart patterns remain observations; the research panel reports the current selection or wait reason.</p>
    <div className="scanner-status" role="status"><strong>{statusError ? "Status unavailable" : state ? words(state.status) : "Reading scanner status…"}</strong>
      <span>{statusError ? `Last observed ${checked == null ? "unknown" : date(checked)}` : `Observed ${checked == null ? "unknown" : date(checked)}`}</span>
      <p>{state?.reason ?? (campaign ? "Saved progress is retained; actual source gaps and current criteria remain below." : state ? "No campaign has been prepared. Choose eligible markets below." : "Coverage and activity remain unknown until status is available.")}</p>
      {state?.campaign && <p>Current campaign {state.campaign.id} · revision {state?.revision} · {state?.enabled ? "Worker enabled" : "Worker paused"}. Restarted preparation requires an explicit Start; saved history remains retained.</p>}
    </div>
    {statusError && <p role="alert">{statusError}</p>}
    <DailyAnalyzer selection={daily} statusError={statusError} checked={checked}
      enableDisabled={setupBusy || !!statusError || !!state?.enabled && !dailyCampaign}
      pauseDisabled={busy || !!storageError || !navigator.locks || pending.some(command => isPause(command.action))}
      onEnable={() => void control("daily_enable")} onPause={() => void control("daily_pause")} onOpen={openDaily}
      onReviewComparison={reviewComparison} onSnapshotChange={id => setComparison(old => old?.daily_id === id ? old : null)} />
    <PatternComparisonPanel selection={comparison} onOpenFinding={openComparisonFinding} onReviewFinding={reviewComparison} />
    <div className="scanner-filters"><label>Analysis market <select aria-label="Analysis chart market" value={market} onChange={event => onChooseMarket(event.target.value)}>{[...new Set([market, ...(campaign?.symbols ?? []), ...roster.map(row => row.symbol)])].map(name => <option key={name}>{name}</option>)}</select></label></div>
    <ScannerChartGrid campaignId={campaign?.id ?? null} symbol={market} focus={chartFocus} />
    <div className="scanner-controls"><button type="button" disabled={setupBusy || !prepareAllowed} onClick={() => void control("prepare")}>Prepare selected markets</button>
      <button type="button" disabled={setupBusy || !!statusError || !state?.campaign || state?.enabled === true || dailyCampaign} onClick={() => void control("start")}>Start / resume scanner</button>
      <button type="button" disabled={busy || !!storageError || !state?.campaign || dailyCampaign || !navigator.locks || pending.some(command => isPause(command.action))} onClick={() => void control("pause")}>Pause scanner</button>
      <button type="button" onClick={() => refreshAgain.current()}>Refresh status</button></div>
    {pending.map(command => <div className="scanner-pending" role="status" key={command.request_id}><p>Original {words(command.action)} control is awaiting acknowledgment. Its saved identity is retained.</p><button type="button" disabled={busy} onClick={() => void recover(command)}>Find saved {words(command.action)} result</button></div>)}
    {(controlError || storageError) && <p role="alert">{storageError ?? controlError}</p>}{notice && <p role="status">{notice}</p>}
    {!navigator.locks && <p role="alert">Control recovery coordination is unavailable in this window. Saved evidence can still be inspected.</p>}
    <section aria-label="Retained scanner campaigns"><h4>Saved campaigns</h4><p>Controls apply to the current campaign above. Earlier maps keep their original scope and evidence and can be inspected here.</p>
      <div className="scanner-controls"><button type="button" disabled={campaignBusy} onClick={() => void readCampaigns()}>Read saved campaigns</button>
        <label>Campaign <select aria-label="Saved scanner campaign" value={savedCampaign} onChange={event => setSavedCampaign(event.target.value)}><option value="">Choose a saved campaign</option>{campaigns.map(row => <option key={row.id} value={row.id}>{date(row.created * 1000)} · {row.market_count} markets · {row.id}</option>)}</select></label>
        <button type="button" disabled={campaignBusy || !savedCampaign} onClick={() => void reopenCampaign()}>Reopen saved campaign</button>
        <button type="button" disabled={!requestedCampaign} onClick={() => {
          campaignRead.cancel(); setHistoricalState(null); setRequestedCampaign(null); setCampaignBusy(false); setCampaignError(null);
          const params = new URLSearchParams(location.hash.split("?")[1] ?? ""); params.delete("scanner_campaign");
          for (const key of [...params.keys()]) if (key.startsWith("scanner_chart_")) params.delete(key);
          location.hash = `markets?${params}`;
        }}>Inspect current campaign</button></div>
      {requestedCampaign && !historicalState && <p role="status">Requested saved campaign {requestedCampaign} is {campaignBusy ? "being read" : "unavailable"}. Its chart scope has not been replaced with the current campaign.</p>}
      {historicalState && <p role="status">Inspecting saved campaign {historicalState.campaign?.id}. This snapshot was reopened on request; its original coverage does not imply current readiness.</p>}
      {campaignError && <p role="alert">{campaignError}</p>}</section>
    <details className="scanner-roster" open><summary>{state?.campaign ? "Frozen market roster" : "Eligible market roster"} · {state ? number(state.roster.eligible) : "unknown"} eligible / {state ? number(state.roster.total) : "unknown"} observed</summary>
      <p>Market screen observed {state?.roster.observed_at == null ? "unknown" : date(state.roster.observed_at * 1000)}.{state?.campaign && " This is the campaign's original screen, not a fresh eligibility claim."} Every new preparation rechecks current market eligibility.</p>
      <p>{chosen.length} markets selected from this observed eligible roster for the next preparation. Preparation reads one bounded native page at a time across all five intervals. {state ? number(roster.filter(row => row.queued).length) : "Unknown"} observed markets remain queued or unprepared; they are not claimed to have full history.</p>
      <div className="scanner-controls"><button type="button" disabled={setupBusy || !!statusError || !roster.some(row => row.eligible)} onClick={() => setSelected(roster.filter(row => row.eligible).map(row => row.symbol))}>Select all eligible markets</button><button type="button" disabled={setupBusy || !selected.length} onClick={() => setSelected([])}>Clear selection</button></div>
      <div className="scanner-roster-grid">{visibleRows.map(row => <label key={row.symbol}><input type="checkbox" checked={chosen.includes(row.symbol)} disabled={!row.eligible || setupBusy}
        onChange={event => setSelected(old => event.target.checked ? [...new Set([...old, row.symbol])] : old.filter(item => item !== row.symbol))} /><strong>{row.symbol.replace(/USD$/, " / USD")}</strong>
        <span>{row.eligible ? row.selected ? "Selected in campaign" : row.queued ? "Queued / unprepared" : "Eligible" : "Ineligible"}</span><small>{row.reason}</small></label>)}</div>
      <div className="scanner-pagination"><button type="button" disabled={rosterPage === 0} onClick={() => setRosterPage(rosterPage - 1)}>Previous markets</button><span>Page {rosterPage + 1} of {Math.max(1, Math.ceil(roster.length / 24))}</span><button type="button" disabled={(rosterPage + 1) * 24 >= roster.length} onClick={() => setRosterPage(rosterPage + 1)}>More markets</button></div>
    </details>
    <section aria-label="Full-year preparation progress"><h4>Full-year preparation</h4><p>Each interval keeps its original cutoff and actual source coverage. Queued, missing and failed scopes remain visible; a progress count is not proof that every requested candle exists.</p>
      <p>{visibleProgress.length} displayed / {number(progressPage?.total ?? displayState?.progress_total)} saved market/interval scopes.{progressPage && " This is a saved page captured when inspected; Refresh progress reads its latest state."}</p>
      <div className="scanner-table-scroll"><table><thead><tr><th>Market / interval</th><th>State</th><th>Actual / expected</th><th>Missing / gaps / pages</th><th>Frozen history / current cursor</th></tr></thead><tbody>{visibleProgress.map(row => <tr key={`${row.symbol}:${row.timeframe}`}><td>{row.symbol}<br />{row.timeframe}</td><td>{words(row.status)}{row.error && <p>{row.error}</p>}</td><td>{number(row.observed_bars)} / {number(row.expected_bars)}</td><td>{number(row.missing_bars)} / {number(row.gap_count)} / {number(row.pages)}</td><td>{date(row.requested_start_ms)} to {date(row.cutoff_ms)}<br />Read through {date(row.cursor_ms)}</td></tr>)}</tbody></table></div>
      {!visibleProgress.length && <p>No prepared scope is available in the observed status.</p>}
      {progressError && <p role="alert">{progressError}</p>}<div className="scanner-pagination"><button type="button" disabled={!campaign || progressBusy} onClick={() => { setProgressPage(null); void inspectProgress(); }}>First / refresh progress</button><button type="button" disabled={!campaign || progressBusy || !progressPage || progressPage.next_before == null} onClick={() => void inspectProgress(progressPage?.next_before)}>Next progress page</button></div>
    </section>
    <section aria-label="Saved scanner levels and alerts"><h4>Every saved level and candidate</h4><p>Pages retain the complete detected set; they are not a highest-scoring shortlist. Alert evaluation is descriptive and preserves missing current inputs and reasons.</p>
      <div className="scanner-filters"><label>Evidence <select aria-label="Scanner evidence type" value={kind} onChange={event => setKind(event.target.value as Kind)}><option value="levels">Historical levels</option><option value="patterns">Historical pattern candidates</option><option value="alerts">Current alerts and evaluation</option></select></label>
        <label>Market <select aria-label="Scanner evidence market" value={market} onChange={event => onChooseMarket(event.target.value)}>{[...new Set([market, ...(campaign?.symbols ?? []), ...roster.map(row => row.symbol)])].map(name => <option key={name}>{name}</option>)}</select></label>
        <label>Interval <select aria-label="Scanner evidence interval" value={frame} onChange={event => setFrame(event.target.value as Frame)}>{frames.map(name => <option key={name}>{name}</option>)}</select></label>
        <button type="button" disabled={!campaign || pageBusy} onClick={() => void inspect()}>Inspect saved evidence</button><button type="button" onClick={() => onInspect(market)}>Open bounded candle chart</button></div>
      <p>The candle chart is a separate bounded study of up to 5,000 candles. Choose its interval and Load to inspect that market; opening it does not start a new historical download or claim the full prepared year is displayed.</p>
      {pageError && <p role="alert">{pageError}</p>}{pageBusy && <p role="status">Reading the selected evidence page…</p>}
      {page && <><p>{page.rows.length} saved rows on this page / {number(page.total)} in this selected scope.</p><div className="scanner-evidence-list">{page.rows.map(row => {
        const facts = body(row); const evaluation = object(facts.evaluation) ? facts.evaluation : null;
        const reasons = evaluation?.reasons;
        return <article key={row.seq}><h5>#{row.seq} · {words(facts.kind ?? facts.pattern_kind)} · {page.symbol} · {page.timeframe}</h5>
          <p>Level {typeof facts.price === "string" ? facts.price : typeof facts.level_price === "string" ? facts.level_price : "Unknown"} · candle {date(facts.bar_open_ms ?? facts.pivot_open_ms)}{kind === "levels" && ` · confirmed ${date(facts.confirmed_at_ms)} · first usable ${date(facts.first_usable_ms)}`}</p>
          {typeof facts.reason === "string" && <p>{facts.reason}</p>}
          {typeof (facts.bar_open_ms ?? facts.pivot_open_ms) === "number" && <button type="button" onClick={() => {
            setChartFocus(previous => ({ timeframe: page.timeframe, atMs: Number(facts.bar_open_ms ?? facts.pivot_open_ms), levelId: typeof facts.level_id === "string" ? facts.level_id : row.id, kind, seq: row.seq, nonce: (previous?.nonce ?? 0) + 1 }));
            document.getElementById("scanner-chart-grid")?.scrollIntoView({ block: "start" });
          }}>Show this {kind === "levels" ? "level" : "pattern"} on chart</button>}
          {kind === "alerts" && <div><strong>Current evaluation: {evaluation ? words(evaluation.status) : "Unavailable"}</strong>
            {Array.isArray(reasons) ? <ul>{reasons.filter(reason => typeof reason === "string").map((reason, i) => <li key={i}>{String(reason)}</li>)}</ul> : <p>{typeof evaluation?.reason === "string" ? evaluation.reason : typeof evaluation?.criteria === "string" ? evaluation.criteria : "No complete current criteria are available in this record."}</p>}
            {object(evaluation?.checks) && <ul>{Object.entries(evaluation.checks).map(([name, passed]) => <li key={name}>{words(name)}: {passed === true ? "Met" : passed === false ? "Not met" : "Unknown"}</li>)}</ul>}
            {Array.isArray(evaluation?.unknowns) && <ul>{evaluation.unknowns.filter(item => typeof item === "string").map((item, i) => <li key={i}>{String(item)}</li>)}</ul>}</div>}
          <details><summary>Original evidence and criteria</summary><pre>{JSON.stringify(row, null, 2)}</pre></details></article>;
      })}</div>{!page.rows.length && <p>No saved records in this specific campaign, market and interval page.</p>}<div className="scanner-pagination"><button type="button" disabled={pageBusy} onClick={() => void inspect()}>First evidence page</button><button type="button" disabled={pageBusy || page.next_before == null} onClick={() => void inspect(page.next_before)}>Next evidence page</button></div></>}
    </section>
    {state && <details><summary>Resource bounds and authority</summary><p>{state.authority}. Current scanner availability does not change trading, research-model or financial permissions.</p><pre>{JSON.stringify(state.limits, null, 2)}</pre></details>}
  </section>;
}
