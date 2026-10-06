import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Pause, Play, RefreshCw } from "lucide-react";
import type { Account } from "./PaperPanel";
import { PaperCampaignJournal } from "./PaperCampaignJournal";

type DiagnosticRun = {
  request_id: string;
  status: string;
  seed?: number;
  max_actions?: number;
  duration_seconds?: number;
  started_at?: number;
  ends_at?: number;
  attempted?: number;
  intents?: number;
  fills?: number;
  cancels?: number;
  errors?: number;
  completed?: number;
  remaining?: number;
  reason?: string | null;
  last_error?: string | null;
  last_control_request_id?: string;
};
type DiagnosticSnapshot = {
  created: boolean;
  account_name: string;
  account: Account | null;
  run: DiagnosticRun | null;
  purpose: "performance_diagnostic";
  fake_capital: string;
  create_request_id?: string;
  last_control_request_id?: string;
  applied_request_ids?: string[];
  entries_allowed?: boolean;
  enabled?: boolean;
  running?: boolean;
  error?: string | null;
  stale?: boolean;
};
type Action = "create" | "start" | "stop";
type Command = { action: Action; body: string };
const commandKey = "qtrades-performance-diagnostic-command-v1";
const rejectionKey = "qtrades-performance-diagnostic-last-rejection-v1";
type Rejection = { action: Action; status: number; reason: string };

function savedRejection(): Rejection | null {
  try {
    const value = JSON.parse(localStorage.getItem(rejectionKey) ?? "null") as Rejection | null;
    return value && typeof value.reason === "string" && typeof value.status === "number" &&
      ["create", "start", "stop"].includes(value.action) ? value : null;
  } catch { return null; }
}

function savedCommand(): { command: Command | null; error: string | null } {
  try {
    const saved = localStorage.getItem(commandKey);
    if (!saved) return { command: null, error: null };
    const value = JSON.parse(saved) as Command;
    const body = JSON.parse(value.body) as Record<string, unknown>;
    if (!["create", "start", "stop"].includes(value.action) ||
        typeof body.request_id !== "string" || !body.request_id ||
        (value.action === "start" && (body.max_actions !== 1000 ||
          body.duration_seconds !== 600 || !Number.isSafeInteger(body.seed)))) {
      throw new Error("Invalid saved diagnostic request");
    }
    return { command: value, error: null };
  } catch {
    return { command: null, error: "The saved diagnostic request could not be read. Its outcome needs to be reconciled before another request." };
  }
}

function confirmed(snapshot: DiagnosticSnapshot, command: Command): boolean {
  const id = (JSON.parse(command.body) as { request_id: string }).request_id;
  return snapshot.applied_request_ids?.includes(id) === true || (command.action === "create" ? snapshot.create_request_id === id
    : command.action === "start" ? snapshot.run?.request_id === id
      : snapshot.last_control_request_id === id || snapshot.run?.last_control_request_id === id);
}
const count = (value: number | undefined) => value == null ? "—" : value.toLocaleString();
const money = (value: string | undefined) => value == null ? "—" : Number(value)
  .toLocaleString("en-US", { style: "currency", currency: "USD" });

export function PerformanceDiagnosticPanel({ unavailable }: { unavailable: boolean }) {
  const [initial] = useState(savedCommand);
  const [command, setCommand] = useState<Command | null>(initial.command);
  const [snapshot, setSnapshot] = useState<DiagnosticSnapshot | null>(null);
  const [error, setError] = useState<string | null>(initial.error);
  const [storageError, setStorageError] = useState<string | null>(initial.error);
  const [readError, setReadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [rejection, setRejection] = useState<Rejection | null>(savedRejection);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [clock, setClock] = useState(Date.now() / 1000);
  const [receivedAt, setReceivedAt] = useState(0);
  const [seed, setSeed] = useState(1);
  const request = useRef<AbortController | null>(null);
  const latestSnapshot = useRef<DiagnosticSnapshot | null>(null);
  const mounted = useRef(true);
  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setRefreshing(true);
    try {
      const response = await fetch("/api/paper/diagnostics", {
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(7000)]),
      });
      if (!response.ok) throw new Error("Performance status could not load. Refresh before sending a request.");
      const value = await response.json() as DiagnosticSnapshot;
      if (!controller.signal.aborted && mounted.current) {
        latestSnapshot.current = value;
        setSnapshot(value); setReadError(null); setReceivedAt(Date.now() / 1000);
      }
    } catch (failure) {
      if (!controller.signal.aborted && mounted.current) setReadError(failure instanceof Error
        ? failure.message : "Performance status could not load.");
    } finally {
      if (!controller.signal.aborted && mounted.current) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load();
    const timer = window.setInterval(() => { setClock(Date.now() / 1000); }, 1000);
    const refresh = window.setInterval(() => { void load(); }, 5000);
    const reconcileStorage = (event: StorageEvent) => {
      if (event.key !== commandKey) return;
      const current = savedCommand();
      setStorageError(current.error);
      if (current.command) setCommand(current.command);
      void load();
    };
    window.addEventListener("storage", reconcileStorage);
    return () => {
      mounted.current = false; request.current?.abort();
      window.clearInterval(timer); window.clearInterval(refresh);
      window.removeEventListener("storage", reconcileStorage);
    };
  }, [load]);

  useEffect(() => {
    if (!command || !snapshot || !confirmed(snapshot, command)) return;
    try {
      const stored = localStorage.getItem(commandKey);
      if (stored !== null && stored !== JSON.stringify(command)) {
        setStorageError("Another tab has a different saved diagnostic request. Its recovery state is retained; reload to reconcile it.");
        setCommand(null);
        return;
      }
      if (stored !== null) localStorage.removeItem(commandKey);
      setCommand(null); setStorageError(null); setError(null);
      setNotice(command.action === "create" ? "The performance account is saved."
        : command.action === "start" ? "The finite performance run is saved; progress appears below."
          : "Stopping new diagnostic entries. Existing positions and orders remain managed.");
    } catch {
      setStorageError("The confirmed request could not be cleared from saved recovery state. Keep this account status open before sending another request.");
    }
  }, [command, snapshot]);

  async function send(action: Action) {
    if (busy || storageError || (command && command.action !== action)) return;
    const saved = command ?? { action, body: JSON.stringify({ request_id: crypto.randomUUID(),
      ...(action === "start" ? { seed, max_actions: 1000, duration_seconds: 600 } : {}) }) };
    setError(null); setNotice(null);
    try {
      // Freeze intent before dispatch; reloads and lost acknowledgments reuse these bytes.
      const serialized = JSON.stringify(saved);
      const stored = localStorage.getItem(commandKey);
      if (stored !== null && stored !== serialized) {
        setStorageError("Another tab has a saved diagnostic request. No new request was sent; reload to reconcile the existing request.");
        return;
      }
      localStorage.setItem(commandKey, serialized);
    } catch {
      setStorageError("The diagnostic request could not be saved for recovery. No request was sent.");
      return;
    }
    setCommand(saved); setBusy(true);
    try {
      const response = await fetch(`/api/paper/diagnostics/${saved.action}`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" },
        body: saved.body, signal: AbortSignal.timeout(20000),
      });
      const value = await response.json().catch(() => ({})) as { detail?: unknown };
      if (!response.ok) {
        const reason = typeof value.detail === "string" ? value.detail
          : response.status === 422 ? "The diagnostic settings were rejected." : "The diagnostic request was not confirmed.";
        if ([403, 409, 422].includes(response.status)) {
          const rejected = { action: saved.action, status: response.status, reason };
          if (mounted.current) { setRejection(rejected); setError(reason); }
          // These routes reject before commit or roll back their transaction.
          // Preserve the reason while releasing only this known-rejected intent.
          try {
            localStorage.setItem(rejectionKey, JSON.stringify(rejected));
            const stored = localStorage.getItem(commandKey);
            if (stored === JSON.stringify(saved)) {
              localStorage.removeItem(commandKey);
              if (mounted.current) setCommand(null);
            } else if (stored !== null && mounted.current) {
              setStorageError("Another tab has a different saved diagnostic request. Its recovery state is retained; reload to reconcile it.");
            }
          } catch {
            if (mounted.current) setStorageError("The rejected request could not be reconciled with saved recovery state. Its original settings remain retained.");
          }
          return;
        }
        throw new Error(reason);
      }
      if (mounted.current) setNotice("Request acknowledged. Checking its saved outcome…");
    } catch (failure) {
      if (mounted.current) {
        if (latestSnapshot.current && confirmed(latestSnapshot.current, saved)) {
          setError(null); setNotice("The saved request was confirmed by refreshed account status.");
        } else setError(`${failure instanceof Error ? failure.message : "The request was not confirmed."} The saved request is retained; refresh status, then retry that same request if needed.`);
      }
    } finally {
      if (mounted.current) { setBusy(false); await load(); }
    }
  }

  const stale = unavailable || !!readError || !snapshot || snapshot.stale === true ||
    snapshot.enabled === false || snapshot.running === false || clock - receivedAt > 12;
  const account = snapshot?.account;
  const run = snapshot?.run;
  const active = !!run && ["active", "running", "draining"].includes(run.status);
  const controlsBlocked = stale || !!snapshot?.error || busy || !!command || !!storageError;
  const remainingTime = run?.ends_at == null ? null : Math.max(0, Math.ceil(run.ends_at - clock));

  return <section className="workspace-card performance-diagnostic" aria-label="Performance diagnostic account">
    <div className="card-heading">
      <div><p className="eyebrow">PERFORMANCE ONLY · FAKE MONEY</p><h2>Performance diagnostic account</h2></div>
      <Activity size={20} />
    </div>
    <p>A separate cash-only account with {money(snapshot?.fake_capital ?? "1000000")} in fake starting money.
      Varied test orders exercise the application. Trades stay in shared history, labeled random performance activity.
      Their returns do not count toward strategy rankings or promotions.</p>
    <p className="fine-print">One retained account place. Trading uses available public-market data, modeled fees and ordinary accounting.
      A filled order is performance activity, not evidence that a strategy works.</p>
    {(storageError || error || readError || snapshot?.error) && <p className="error-banner" role="alert">
      {storageError ?? error ?? readError ?? snapshot?.error}</p>}
    {stale && <p role="status">Current performance status is unconfirmed. Retained balances and progress may be old.</p>}
    {notice && <p role="status">{notice}</p>}
    {rejection && <p className="fine-print">Last rejected {rejection.action} request: {rejection.reason}</p>}
    <div className="heading-actions">
      <button className="button secondary small" disabled={refreshing} onClick={() => void load()}>
        <RefreshCw size={14} /> {refreshing ? "Refreshing…" : "Refresh performance status"}</button>
      {!snapshot?.created && <button className="button secondary" disabled={controlsBlocked}
        onClick={() => void send("create")}>Create performance account</button>}
      {snapshot?.created && <>
        <label>Test sequence seed <input type="number" min={0} max={2147483647} step={1} value={seed}
          disabled={busy || !!command || active} onChange={event => setSeed(Number(event.target.value))} /></label>
        <button className="button secondary" disabled={controlsBlocked || snapshot.entries_allowed === false || active || !Number.isSafeInteger(seed) || seed < 0 || seed > 2147483647}
          onClick={() => void send("start")}><Play size={14} /> Start ten-minute performance run</button>
        <button className="button secondary" disabled={!snapshot || !!readError || busy || !!command || !!storageError || !active || run?.status === "draining"}
          onClick={() => void send("stop")}><Pause size={14} /> Stop new entries and drain</button>
      </>}
      {command && <button className="button secondary" disabled={busy || !!readError || !snapshot || !!storageError ||
        (command.action !== "stop" && (stale || !!snapshot.error || (command.action === "start" && snapshot.entries_allowed === false)))}
        onClick={() => void send(command.action)}>{busy ? "Confirming saved request…" : `Retry same ${command.action} request`}</button>}
    </div>
    {command && <p role="status">A saved request is awaiting confirmation. A retry uses its original identity and settings; another run is not created.</p>}
    {account && <>
      <dl className="summary-values">
        <div><dt>Fake cash, including reserves</dt><dd>{money(account.cash)}</dd></div>
        <div><dt>Liquidation equity</dt><dd>{!stale && account.valuation_fresh ? money(account.equity) : "Unconfirmed"}</dd></div>
        <div><dt>Lifetime fake funding</dt><dd>{money(account.funding)}</dd></div>
        <div><dt>Modeled fees</dt><dd>{money(account.fees)}</dd></div>
        <div><dt>Open positions</dt><dd>{Object.keys(account.positions).length}</dd></div>
        <div><dt>Pending orders</dt><dd>{Object.keys(account.pending).length}</dd></div>
      </dl>
      {account.fault && <p className="error-banner" role="alert">{account.fault.reason}</p>}
      <p>Orders, trades and balances also appear in Accounts, trade history and the permanent Journal.</p>
      <PaperCampaignJournal account={snapshot?.account_name ?? "performance-diagnostic"} />
    </>}
    {run ? <div aria-label="Performance run progress">
      <p role="status"><strong>{run.status.replaceAll("_", " ")}</strong>
        {remainingTime != null && active && run.status !== "draining" ? ` · ${remainingTime} seconds left for new activity` : ""}
        {run.reason ? ` · ${run.reason}` : ""}</p>
      {run.last_error && <p className="error-banner" role="alert">{run.last_error}</p>}
      <dl className="summary-values">
        {([ ["Actions attempted", run.attempted], ["Order intents", run.intents], ["Fills", run.fills],
          ["Cancellations", run.cancels], ["Errors", run.errors], ["Closed trades", run.completed],
          ["Actions remaining", run.remaining] ] as [string, number | undefined][]).map(([label, value]) =>
          <div key={label}><dt>{label}</dt><dd>{count(value)}</dd></div>)}
      </dl>
      <p className="fine-print">At most {count(run.max_actions ?? 1000)} actions over {count(run.duration_seconds ?? 600)} seconds. Stopping ends new activity;
        existing orders and holdings are drained without erasing history. Fresh market data and resource capacity determine actual volume.
        Missing counters remain unavailable.</p>
    </div> : <p>No performance run has been retained yet.</p>}
  </section>;
}
