import { useEffect, useRef, useState } from "react";
import { useEvidenceRead } from "./useEvidenceRead";

export type PatternComparisonSelection = { daily_id: string; symbol: "BTCUSD"; timeframe: "5m";
  event_kind: "patterns" | "alerts"; event_seq: number };
type Command = PatternComparisonSelection & { request_id: string; expected_finding_sha256: string };
export type PatternComparisonFinding = Record<string, unknown> & { selection: PatternComparisonSelection;
  campaign_id: string; original_event: Record<string, unknown>; coverage: { timeframe: string; progress_sha256: string | null }[] };
type Finding = PatternComparisonFinding;
type Description = { version: string; finding_sha256: string; finding: Finding;
  mapping: Record<string, unknown>; financial_authority: false };
type Receipt = Description & { request_id: string; intent_sha256: string; prepared_at: number;
  status: "supported" | "waiting" | "research_only"; reason: string | null; evaluation: Record<string, unknown>;
  proposal: Record<string, unknown> | null; issued_bundle_sha256: string | null; submitted: false;
  research_only?: true; dispatch_available?: false; dispatch_reason?: string;
  readonly_comparison_template?: Record<string, unknown> | null };
type PreparationSummary = { request_id: string; finding_sha256: string; status: "supported" | "waiting" | "research_only";
  prepared_at: number; issued_bundle_sha256: string; selection: PatternComparisonSelection };
type PreparationPage = { version: string; items: PreparationSummary[]; next_before: string | null; order: string; financial_authority: false };
const endpoint = "/api/research/pattern-scanner/comparisons";
const pendingKey = "qtrades-pattern-comparison-pending-v1";
const completedKey = "qtrades-pattern-comparison-receipt-v1";
const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);
const requestId = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9_-]{8,64}$/.test(value);
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const metric = (value: unknown) => typeof value === "string" || typeof value === "number" ? String(value) : "Unknown";
const nativeTime = (value: unknown) => typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= 8640000000000000 ? new Date(value).toLocaleString() : "Unknown";
const selectionKey = (value: PatternComparisonSelection | null) => value ?
  `${value.daily_id}:${value.symbol}:${value.timeframe}:${value.event_kind}:${value.event_seq}` : "";
const canonicalCommand = (command: Command) => JSON.stringify(Object.fromEntries(
  Object.entries(command).sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)));

function validSelection(value: unknown): value is PatternComparisonSelection {
  return object(value) && typeof value.daily_id === "string" && /^daily-[a-f0-9]{24}$/.test(value.daily_id) &&
    value.symbol === "BTCUSD" && value.timeframe === "5m" && ["patterns", "alerts"].includes(String(value.event_kind)) &&
    Number.isSafeInteger(value.event_seq) && Number(value.event_seq) > 0;
}
function validCommand(value: unknown): value is Command {
  if (!object(value)) return false;
  const row: Record<string, unknown> = value;
  return validSelection(value) && uuid(row.request_id) &&
    hash(row.expected_finding_sha256) && Object.keys(value).length === 7;
}
function savedCommand(key: string): { command: Command | null; error: string | null } {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return { command: null, error: null };
    const value: unknown = JSON.parse(raw);
    if (!validCommand(value)) throw new Error();
    return { command: value, error: null };
  } catch { return { command: null, error: "The original preparation identity is unreadable. No replacement request will be sent." }; }
}
async function preparationLock(work: () => void) {
  if (!navigator.locks) throw new Error("This window cannot safely save a preparation for recovery.");
  await navigator.locks.request(pendingKey, { ifAvailable: true }, lock => {
    if (!lock) throw new Error("Another window is saving a preparation. Reconcile its original request first.");
    work();
  });
}
function validateDescription(value: unknown, selection: PatternComparisonSelection): asserts value is Description {
  if (!object(value) || value.version !== "saved-pattern-comparison-preparation-v1" || !hash(value.finding_sha256) ||
    !object(value.finding) || !validSelection(value.finding.selection) ||
    selectionKey(value.finding.selection) !== selectionKey(selection) ||
    typeof value.finding.campaign_id !== "string" || !/^patterns-[a-f0-9]{24}$/.test(value.finding.campaign_id) ||
    !object(value.finding.original_event) || value.finding.original_event.symbol !== "BTCUSD" ||
    value.finding.original_event.timeframe !== "5m" || !["resistance_breakout", "breakout_retest"].includes(String(value.finding.original_event.kind)) ||
    value.finding.original_event.volume_confirmed !== true || value.finding.original_event.financial_authority !== false ||
    !Number.isSafeInteger(value.finding.original_event.bar_open_ms) || !Array.isArray(value.finding.coverage) || value.finding.coverage.length !== 5 ||
    new Set(value.finding.coverage.map(row => object(row) ? row.timeframe : null)).size !== 5 ||
    value.finding.coverage.some(row => !object(row) || !["5m", "15m", "30m", "1h", "4h"].includes(String(row.timeframe)) || typeof row.status !== "string" || !(row.progress_sha256 === null || hash(row.progress_sha256))) ||
    !value.finding.coverage.some(row => object(row) && row.timeframe === "5m" && hash(row.progress_sha256)) ||
    !object(value.finding.native_proof) || value.finding.native_proof.archive_verified !== true ||
    !hash(value.finding.native_proof.input_window_sha256) || !hash(value.finding.native_proof.pivot_sha256) ||
    !object(value.mapping) || value.mapping.strategy !== "breakout-retest-v1" || value.mapping.reference !== "cost-breakout-v1" ||
    value.mapping.rule_version !== "reviewed-lab-rules-v4" || value.mapping.holding_horizon !== "medium" || value.financial_authority !== false) {
    throw new Error("The returned finding does not match the original daily record. No current finding was substituted.");
  }
}
function validateReceipt(value: unknown, command: Command): asserts value is Receipt {
  if (!object(value)) throw new Error("Preparation acknowledgment is incomplete. Its outcome remains unknown.");
  const row: Record<string, unknown> = value;
  validateDescription(value, command);
  const readonly = row.research_only === true;
  if (row.request_id !== command.request_id || value.finding_sha256 !== command.expected_finding_sha256 ||
    !hash(row.intent_sha256) || typeof row.prepared_at !== "number" || !Number.isFinite(row.prepared_at) ||
    !(readonly ? ["research_only", "waiting"] : ["supported", "waiting"]).includes(String(row.status)) || !(row.reason === null || typeof row.reason === "string") || !object(row.evaluation) ||
    !(row.proposal === null || object(row.proposal)) || !(row.issued_bundle_sha256 === null || hash(row.issued_bundle_sha256)) ||
    row.status === "supported" && (row.evaluation.status !== "supported_exploratory_configuration" || !object(row.proposal) || !hash(row.issued_bundle_sha256)) ||
    row.status === "waiting" && row.evaluation.status !== "waiting" ||
    readonly && (row.proposal !== null || row.dispatch_available !== false || typeof row.dispatch_reason !== "string" || !row.dispatch_reason ||
      !(row.readonly_comparison_template === null || object(row.readonly_comparison_template)) ||
      row.status === "research_only" && (row.evaluation.status !== "supported_research_observation" || !object(row.readonly_comparison_template) || !hash(row.issued_bundle_sha256))) ||
    row.submitted !== false) throw new Error("Preparation acknowledgment does not match the original request and finding. Its outcome remains unknown.");
}
async function validateIntent(value: Receipt, command: Command) {
  // All command keys/values are bounded ASCII; this matches the server's sorted compact JSON.
  const intent = value.research_only === true ? JSON.stringify({ command: JSON.parse(canonicalCommand(command)), research_only: true }) : canonicalCommand(command);
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(intent));
  const digest = [...new Uint8Array(bytes)].map(byte => byte.toString(16).padStart(2, "0")).join("");
  if (value.intent_sha256 !== digest) throw new Error("The saved preparation intent differs from the original exact payload. Its outcome remains unknown.");
}

export function PatternComparisonPanel({ selection, onOpenFinding, onReviewFinding }: {
  selection: PatternComparisonSelection | null; onOpenFinding: (finding: Finding) => void;
  onReviewFinding: (selection: PatternComparisonSelection) => void;
}) {
  const [description, setDescription] = useState<Description | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [initial] = useState(() => savedCommand(pendingKey));
  const [pending, setPending] = useState(initial.command);
  const [storageError, setStorageError] = useState(initial.error);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [sending, setSending] = useState(false);
  const [page, setPage] = useState<PreparationPage | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [pageBusy, setPageBusy] = useState(false);
  const [requestedOriginal, setRequestedOriginal] = useState<string | null>(null);
  const [reviewNonce, setReviewNonce] = useState(0);
  const [separateObservation, setSeparateObservation] = useState<{ scope: string; requestId: string } | null>(null);
  const mounted = useRef(true); const dispatching = useRef(false);
  const scope = selectionKey(selection); const currentScope = useRef(scope); currentScope.current = scope;
  const originalRead = useEvidenceRead();
  const descriptionRead = useEvidenceRead();
  const pageRead = useEvidenceRead();
  const restoreOriginal = useRef<(id: string) => void>(() => {});
  const refreshSaved = () => {
    const saved = savedCommand(pendingKey); setPending(saved.command); setStorageError(saved.error);
  };
  useEffect(() => {
    mounted.current = true;
    const listener = (event: StorageEvent) => { if (event.key === pendingKey || event.key === completedKey) refreshSaved(); };
    addEventListener("storage", listener);
    return () => { mounted.current = false; removeEventListener("storage", listener); };
  }, []);
  useEffect(() => {
    originalRead.cancel(); setReceipt(null); setDescription(null); setError(null); setNotice(null);
    setReading(false); setRequestedOriginal(null);
    if (!selection) return;
    const requested = selection; const read = descriptionRead.begin(10000); setReading(true);
    const params = new URLSearchParams({ daily_id: requested.daily_id, symbol: requested.symbol, timeframe: requested.timeframe,
      event_kind: requested.event_kind, event_seq: String(requested.event_seq) });
    void (async () => {
      try {
        const response = await fetch(`/api/research/pattern-scanner/comparison-source?${params}`, { cache: "no-store", signal: read.signal });
        if (!response.ok) throw new Error(`Original finding review unavailable (HTTP ${response.status}). No preparation was sent.`);
        const value: unknown = await response.json(); validateDescription(value, requested);
        if (read.isCurrent()) setDescription(value);
      } catch (cause) { if (read.isCurrent()) setError(cause instanceof Error ? cause.message : "Original finding review unavailable."); }
      finally { if (read.isCurrent()) setReading(false); }
    })();
    return descriptionRead.cancel;
  }, [scope, reviewNonce, descriptionRead.begin, descriptionRead.cancel, originalRead.cancel]);
  useEffect(() => { setSeparateObservation(old => old?.scope === scope ? old : null); }, [scope]);
  useEffect(() => {
    const restore = () => {
      const id = new URLSearchParams(location.hash.split("?")[1] ?? "").get("pattern_comparison_request");
      if (id != null) restoreOriginal.current(id);
    };
    restore(); addEventListener("hashchange", restore); addEventListener("popstate", restore);
    return () => { removeEventListener("hashchange", restore); removeEventListener("popstate", restore); };
  }, []);

  async function adopt(value: unknown, command: Command, expectedScope: string, explicitOriginal = false, isCurrent = () => true) {
    validateReceipt(value, command);
    await validateIntent(value, command);
    if (!isCurrent()) return;
    if (value.research_only === true && !explicitOriginal) throw new Error("A read-only observation cannot acknowledge an ordinary preparation request. Its original identity remains retained.");
    if (value.research_only !== true) await preparationLock(() => {
      const saved = savedCommand(pendingKey);
      const completed = savedCommand(completedKey);
      if (saved.error || completed.error) {
        if (!explicitOriginal) throw new Error(saved.error ?? completed.error!);
        return; // A verified read may display; unreadable local ownership is never rewritten.
      }
      const matchesPending = saved.command && canonicalCommand(saved.command) === canonicalCommand(command);
      const matchesCompleted = completed.command && canonicalCommand(completed.command) === canonicalCommand(command);
      if (!matchesPending && !matchesCompleted && !explicitOriginal) {
        throw new Error("The original preparation identity changed before acknowledgment. Its result remains available by UUID.");
      }
      if (matchesPending) { localStorage.setItem(completedKey, JSON.stringify(command)); localStorage.removeItem(pendingKey); }
    });
    if (!mounted.current || !isCurrent()) return;
    refreshSaved();
    if (currentScope.current !== expectedScope || !explicitOriginal && expectedScope !== "" && expectedScope !== selectionKey(command)) {
      setNotice("The other original preparation was acknowledged and retained. This selected finding has not been replaced.");
      return;
    }
    if (explicitOriginal) descriptionRead.cancel();
    setReceipt(value); setDescription(value); setError(null);
    setRequestedOriginal(command.request_id);
    const params = new URLSearchParams(location.hash.split("?")[1] ?? ""); params.set("pattern_comparison_request", command.request_id);
    history.replaceState(null, "", `#markets?${params}`);
    setNotice("The original preparation is retained. Nothing was submitted to the Lab inbox or funded.");
  }

  async function prepare() {
    if (receipt?.research_only === true || !selection || !description || selectionKey(description.finding.selection) !== scope || dispatching.current || pending || storageError) return;
    const expectedScope = scope;
    const command: Command = { ...selection, request_id: crypto.randomUUID(), expected_finding_sha256: description.finding_sha256 };
    const signal = AbortSignal.timeout(30000);
    dispatching.current = true; setSending(true); setError(null); setNotice(null);
    const holder: { response: Promise<Response> | null } = { response: null };
    try {
      await preparationLock(() => {
        if (!mounted.current || currentScope.current !== expectedScope) throw new Error("Selection changed before dispatch. No preparation was sent.");
        const saved = savedCommand(pendingKey); if (saved.error) throw new Error(saved.error);
        if (saved.command) throw new Error("An original preparation is awaiting acknowledgment. Find its saved result first.");
        const completed = savedCommand(completedKey); if (completed.error) throw new Error(completed.error);
        if (completed.command && selectionKey(completed.command) === expectedScope &&
          !(separateObservation?.scope === expectedScope)) throw new Error("This finding already has an original preparation. Reopen that saved result instead.");
        localStorage.setItem(pendingKey, JSON.stringify(command));
        // Persist and dispatch in the same critical section: no unsent orphan after a scope change.
        holder.response = fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" },
          body: JSON.stringify(command), signal });
      });
      if (mounted.current) refreshSaved();
      if (!holder.response) throw new Error("No preparation was dispatched.");
      const response = await holder.response;
      if (!response.ok) throw new Error(`Preparation acknowledgment unavailable (HTTP ${response.status}). Find the original saved result; do not send a replacement.`);
      await adopt(await response.json(), command, expectedScope);
    } catch (cause) {
      if (!mounted.current) return;
      refreshSaved();
      if (currentScope.current !== expectedScope) return;
      setError(cause instanceof Error ? cause.message : "Preparation acknowledgment unavailable.");
    } finally { dispatching.current = false; if (mounted.current) setSending(false); }
  }

  async function recover(command: Command, explicitOriginal = false, summary?: PreparationSummary) {
    if (dispatching.current) return;
    const expectedScope = scope; const read = originalRead.begin(10000); setReading(true); setError(null);
    try {
      const response = await fetch(`${endpoint}/${encodeURIComponent(command.request_id)}`, { cache: "no-store", signal: read.signal });
      if (!response.ok) throw new Error(`Original preparation unavailable (HTTP ${response.status}). Its UUID remains retained; absence does not establish that a pending POST cannot commit.`);
      const value: unknown = await response.json(); validateReceipt(value, command);
      if (summary && (value.status !== summary.status || value.prepared_at !== summary.prepared_at || value.issued_bundle_sha256 !== summary.issued_bundle_sha256)) throw new Error("Original receipt differs from the retained history row. No newer preparation was substituted.");
      if (read.isCurrent()) await adopt(value, command, expectedScope, explicitOriginal, read.isCurrent);
    } catch (cause) { if (read.isCurrent()) setError(cause instanceof Error ? cause.message : "Original preparation unavailable."); }
    finally { if (read.isCurrent()) setReading(false); }
  }
  async function readOriginal(id: string) {
    if (dispatching.current) return;
    const expectedScope = scope; const read = originalRead.begin(10000); setReading(true); setRequestedOriginal(id); setError(null); setReceipt(null); setDescription(null);
    try {
      if (!requestId(id)) throw new Error("Invalid original preparation identity. No latest receipt was substituted.");
      const response = await fetch(`${endpoint}/${encodeURIComponent(id)}`, { cache: "no-store", signal: read.signal });
      if (!response.ok) throw new Error(`Exact original preparation unavailable (HTTP ${response.status}). No current evaluation was substituted.`);
      const value: unknown = await response.json();
      if (!object(value) || !object(value.finding) || !validSelection(value.finding.selection) || !hash(value.finding_sha256)) throw new Error("Original preparation identity is incomplete.");
      const command: Command = { ...value.finding.selection, request_id: id, expected_finding_sha256: value.finding_sha256 };
      if (read.isCurrent()) await adopt(value, command, expectedScope, true, read.isCurrent);
    } catch (cause) { if (read.isCurrent()) setError(cause instanceof Error ? cause.message : "Original preparation unavailable."); }
    finally { if (read.isCurrent()) setReading(false); }
  }
  restoreOriginal.current = id => { void readOriginal(id); };
  async function readPage(before?: string | null) {
    const read = pageRead.begin(10000); setPageBusy(true); setPageError(null);
    try {
      const response = await fetch(`${endpoint}${before ? `?before=${encodeURIComponent(before)}` : ""}`, { cache: "no-store", signal: read.signal });
      if (!response.ok) throw new Error("Saved preparation history unavailable. No empty successful list was substituted.");
      const value = await response.json() as PreparationPage;
      if (value?.version !== "saved-pattern-comparison-preparation-v1" || !Array.isArray(value.items) || value.items.length > 20 ||
        value.financial_authority !== false || new Set(value.items.map(row => row.request_id)).size !== value.items.length ||
        value.order !== "Stable descending request identity, not preparation chronology" || !(value.next_before === null || typeof value.next_before === "string" && /^[A-Za-z0-9_-]{8,64}$/.test(value.next_before)) ||
        value.items.some(row => !requestId(row.request_id) || !validSelection(row.selection) || !hash(row.finding_sha256) || !hash(row.issued_bundle_sha256) ||
          !["supported", "waiting", "research_only"].includes(row.status) || !Number.isFinite(row.prepared_at))) throw new Error("Saved preparation history is incomplete or has a different identity.");
      if (read.isCurrent()) setPage(value);
    } catch (cause) { if (read.isCurrent()) setPageError(cause instanceof Error ? cause.message : "Saved preparations unavailable."); }
    finally { if (read.isCurrent()) setPageBusy(false); }
  }

  const completed = savedCommand(completedKey);
  const alreadyPrepared = !!completed.command && selectionKey(completed.command) === scope && separateObservation?.scope !== scope;
  const reviewed = receipt ?? (description && selectionKey(description.finding.selection) === scope ? description : null);
  const event = reviewed?.finding.original_event;
  const coverage = reviewed?.finding.coverage as (Record<string, unknown> & { timeframe: string })[] | undefined;
  const matched = receipt && object(receipt.evaluation.matched_inputs) ? receipt.evaluation.matched_inputs : null;
  return <section id="pattern-comparison-panel" className="daily-analyzer pattern-comparison-panel" aria-labelledby="pattern-comparison-title">
    <header><div><p className="station-kicker">PROSPECTIVE RESEARCH PREPARATION</p><h4 id="pattern-comparison-title">Review prospective comparison</h4></div><span>BTC / USD · native 5m finding</span></header>
    <p>A saved scanner breakout or retest can motivate a fixed v4 breakout-retest comparison against cost-breakout. The scanner's confirmed pivot zones and the bank's rolling-range retest are different mechanisms. Preparation does not run this experiment or establish an economic result.</p>
    <p>Fixed prospective timing: up to six hours holding, a 24-hour medium-horizon review. Current numerical inputs are captured separately from the original finding; unknown or unavailable inputs remain an explicit wait.</p>
    {(receipt?.finding.selection ?? selection) && <p>Selected original finding: {(receipt?.finding.selection ?? selection)!.daily_id} · BTCUSD · 5m · {(receipt?.finding.selection ?? selection)!.event_kind} #{(receipt?.finding.selection ?? selection)!.event_seq}.</p>}
    {requestedOriginal && <p>Requested original preparation UUID {requestedOriginal}.</p>}
    {reading && <p role="status">Reading exact original comparison evidence…</p>}
    {(error || storageError || completed.error) && <p role="alert">{storageError ?? completed.error ?? error}</p>}
    {notice && <p role="status">{notice}</p>}
    {pending && <div className="scanner-pending" role="status"><p>Original preparation {pending.request_id} for {pending.daily_id}, {pending.event_kind} #{pending.event_seq} is awaiting acknowledgment. Its finding digest and payload remain retained.</p>
      <button type="button" disabled={reading || sending} onClick={() => void recover(pending)}>Find original preparation result</button></div>}
    {!pending && completed.command && <div className="scanner-controls"><button type="button" disabled={reading || sending} onClick={() => void recover(completed.command!, true)}>Reopen original preparation</button>
      {scope && scope !== selectionKey(completed.command) && <button type="button" onClick={() => onReviewFinding(completed.command!)}>Review original preparation finding</button>}
      <span>Saved UUID {completed.command.request_id}</span></div>}
    {reviewed && !receipt && <div className="scanner-controls"><button type="button" disabled={reading || sending || alreadyPrepared || !!pending || !!storageError || !!completed.error || !navigator.locks} onClick={() => void prepare()}>Prepare fixed comparison</button></div>}
    {!navigator.locks && <p role="alert">Safe request coordination is unavailable. Original evidence can still be read; no preparation will be sent.</p>}
    {receipt && <div className="scanner-status" role="status"><strong>{receipt.research_only === true ? receipt.status === "research_only" ? "Read-only research observation" : "Read-only research observation waiting" : receipt.status === "supported" ? "Preparation supported by the captured numerical check" : "Preparation waiting"}</strong>
      <p>{receipt.research_only === true ? receipt.dispatch_reason : receipt.reason ?? "The separate current input check supported this exploratory configuration; no comparison has run."}</p>
      {receipt.research_only === true && receipt.reason && <p>{receipt.reason}</p>}<p>Original UUID {receipt.request_id} · saved {new Date(receipt.prepared_at * 1000).toLocaleString()}.</p>
      <p>Lab inbox submission: no. Account funding: no. Model dispatch: no. A supported input check is not a trading outcome.</p>
      <p>This is the original preparation-time check, not current executable readiness. Its evaluation timestamps and expiry remain in the saved numerical evidence below.</p>
      {matched && <p>Separate current execution inputs: {metric(matched.count)} closed minute candles, {nativeTime(matched.start_ms)} to {nativeTime(matched.end_ms)}. Original matched input SHA256 {metric(matched.sha256)}. This is a current deterministic check, not a replay of the scanner event.</p>}
      <details><summary>Separate current numerical check and original issued bundle</summary><pre>{JSON.stringify(receipt.evaluation, null, 2)}</pre><p>Issued bundle SHA256 {receipt.issued_bundle_sha256 ?? "not issued in this wait"}.</p></details>
      <details><summary>{receipt.research_only === true ? "Read-only fixed comparison template" : "Original prospective proposal"}</summary><pre>{JSON.stringify(receipt.research_only === true ? receipt.readonly_comparison_template : receipt.proposal, null, 2)}</pre></details>
      <p>{receipt.research_only === true ? "Dispatch unavailable. This observation reuses an already-attempted fixed comparison as research evidence. It is not a new Lab submission proposal; this view has no Prepare, submission or activation control." : "The preparation can be inspected before a separately authorized Lab submission through the existing Lab workflow. This panel has no submission or activation control."}</p></div>}
    {receipt?.status === "waiting" && receipt.research_only !== true && <><button type="button" disabled={reading || sending || !!pending} onClick={() => {
      const original = receipt.finding.selection;
      setSeparateObservation({ scope: selectionKey(original), requestId: receipt.request_id });
      onReviewFinding(original); setReviewNonce(value => value + 1);
    }}>Review a separate current observation</button><p>This original wait remains unchanged. A fresh source review performs no submission or numerical evaluation; only an explicit Prepare can save a separate new UUID.</p></>}
    {separateObservation?.scope === scope && !receipt && <p>Reviewing a separate current observation. Original waiting preparation {separateObservation.requestId} remains in saved history; no result has been upgraded.</p>}
    {reviewed && <><button type="button" onClick={() => onOpenFinding(reviewed.finding)}>Return to original daily finding</button>
      <h5>Original {String(event?.kind ?? "pattern").replaceAll("_", " ")}</h5>
      <p>{typeof event?.reason === "string" ? event.reason : "Original explanation unavailable."}</p>
      <p>Native 5m candle {nativeTime(event?.bar_open_ms)}. Original resistance {metric(event?.level_price)}; volume ratio {metric(event?.volume_ratio)}, with recorded volume confirmation. Only the retained local recognition window and pivot inputs were verified; this does not establish full-year coverage.</p>
      <p>Finding SHA256 {reviewed.finding_sha256}.</p>
      <div className="scanner-table-scroll"><table><caption>Original five-frame coverage at finding capture</caption><thead><tr><th>Frame / state</th><th>Recorded / expected</th><th>Missing / gaps</th><th>Captured cutoff</th></tr></thead><tbody>{coverage?.map(row => <tr key={row.timeframe}><td>{row.timeframe} · {metric(row.status)}</td><td>{metric(row.observed_bars)} / {metric(row.expected_bars)}</td><td>{metric(row.missing_bars)} / {metric(row.gap_count)}</td><td>{nativeTime(row.cutoff_ms)}</td></tr>)}</tbody></table></div>
      <details><summary>Frozen original finding, coverage and source</summary><pre>{JSON.stringify(reviewed.finding, null, 2)}</pre></details>
      <details><summary>Explicit scanner-to-bank mapping and limitations</summary><pre>{JSON.stringify(reviewed.mapping, null, 2)}</pre></details></>}
    {!reviewed && !reading && !error && !storageError && <p>Choose an eligible recorded BTCUSD 5m breakout or retest to review its original evidence. No current record has been substituted.</p>}
    <details><summary>Saved immutable preparations</summary><div className="scanner-controls"><button type="button" disabled={pageBusy} onClick={() => void readPage()}>Read saved preparations</button>
      <button type="button" disabled={pageBusy || page?.next_before == null} onClick={() => void readPage(page?.next_before)}>Next preparation page</button></div>
      <p>{page?.order ?? "History is ordered by stable request identity, not newest preparation time."}</p>{pageError && <p role="alert">{pageError}</p>}
      <div className="scanner-table-scroll"><table><caption>Original saved preparations</caption><thead><tr><th>UUID / original finding</th><th>Saved state / time</th><th>Original result</th></tr></thead><tbody>{page?.items.map(row => <tr key={row.request_id}><td>{row.request_id}<br />{row.selection.daily_id} · {row.selection.event_kind} #{row.selection.event_seq}</td><td>{row.status} · {new Date(row.prepared_at * 1000).toLocaleString()}</td><td><button type="button" disabled={reading || sending} onClick={() => void recover({ ...row.selection, request_id: row.request_id, expected_finding_sha256: row.finding_sha256 }, true, row)}>Reopen preparation {row.request_id}</button></td></tr>)}</tbody></table></div>
      {page && page.items.length === 0 && <p>No saved preparations were returned in this exact page.</p>}</details>
  </section>;
}
