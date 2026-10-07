import { useEffect, useRef, useState } from "react";
import { useEvidenceRead } from "./useEvidenceRead";

type Frame = "5m" | "15m" | "30m" | "1h" | "4h";
type Coverage = { timeframe: Frame; status: string; requested_start_ms?: number; cutoff_ms?: number;
  cursor_ms?: number; expected_bars?: number; observed_bars?: number; missing_bars?: number;
  pages?: number; gap_count?: number; latest_close_ms?: number | null; error?: string | null;
  source_sha256?: string; progress_sha256: string | null };
type Evidence = { kind: "patterns" | "alerts"; seq: number; timeframe: Frame; body: Record<string, unknown>; progress_sha256?: string };
type Pick = { rank: number; symbol: string; campaign_id: string; basis: "recognized_setup" | "analyzed_no_setup" | "history_pending";
  reason: string; quote_volume: string; spread_bps: string; trades: number; captured_at: number;
  coverage: Coverage[]; prepared_timeframes?: Frame[]; evidence: Evidence[]; observed_eligible: true };
type Roster = { available: boolean; observed_at: number | null; rows: { symbol: string; eligible: boolean; reason: string }[] };
export type DailySelection = { policy: "daily-pattern-research-v1"; enabled: boolean; state: string; reason: string | null;
  next_due_at: number | null; active_day: number | null; latest_id: string | null; campaign_id: string | null; current_roster: Roster };
type Snapshot = { id: string; campaign_id: string; utc_day: number; generated_at: number; as_of: number;
  policy: Record<string, unknown>; policy_sha256: string; roster: Roster; pool: Record<string, number>;
  enrolled_today: string[]; picks: Pick[]; limitations: string[] };
type Summary = { seq: number; id: string; campaign_id: string; utc_day: number; generated_at: number; picks: Pick[] };
type Page = { rows: Summary[]; total: number; next_before: number | null };
const endpoint = "/api/research/pattern-scanner/daily/shortlists";
const frames: Frame[] = ["5m", "15m", "30m", "1h", "4h"];
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const symbolId = (v: unknown): v is string => typeof v === "string" && /^[A-Z0-9]{3,24}$/.test(v);
const dailyId = (v: unknown): v is string => typeof v === "string" && /^daily-[a-f0-9]{24}$/.test(v);
const campaignId = (v: unknown): v is string => typeof v === "string" && /^patterns-[a-f0-9]{24}$/.test(v);
const count = (v: unknown) => typeof v === "number" && Number.isFinite(v) ? v.toLocaleString() : "Unknown";
const localTime = (seconds: unknown) => typeof seconds === "number" && Number.isFinite(seconds) ? new Date(seconds * 1000).toLocaleString() : "Unknown";
const nativeTime = (ms: unknown) => typeof ms === "number" && Number.isFinite(ms) ? new Date(ms).toLocaleString() : "Unknown";
const utcDay = (day: number) => new Date(day * 86400000).toISOString().slice(0, 10);
const words = (v: unknown) => typeof v === "string" ? v.replaceAll("_", " ") : "Unknown";
const metric = (v: unknown) => typeof v === "string" || typeof v === "number" ? String(v) : "Unknown";

export function validDaily(value: unknown): value is DailySelection {
  if (!object(value) || value.policy !== "daily-pattern-research-v1" || typeof value.enabled !== "boolean" ||
    typeof value.state !== "string" || !(value.reason === null || typeof value.reason === "string") ||
    !(value.next_due_at === null || typeof value.next_due_at === "number" && Number.isFinite(value.next_due_at) && Math.abs(value.next_due_at) <= 8640000000000) ||
    !(value.active_day === null || Number.isSafeInteger(value.active_day) && Number(value.active_day) >= 0 && Number(value.active_day) <= 1000000) ||
    !(value.latest_id === null || dailyId(value.latest_id)) || !(value.campaign_id === null || campaignId(value.campaign_id))) return false;
  const roster = value.current_roster;
  return object(roster) && typeof roster.available === "boolean" && (roster.observed_at === null || typeof roster.observed_at === "number" && Number.isFinite(roster.observed_at)) &&
    Array.isArray(roster.rows) && roster.rows.length <= 2000 && roster.rows.every(row => object(row) &&
      symbolId(row.symbol) && typeof row.eligible === "boolean" && typeof row.reason === "string");
}

function validateSnapshot(value: Snapshot, id: string) {
  if (value?.id !== id || !dailyId(value.id) || !campaignId(value.campaign_id) ||
    !Number.isSafeInteger(value.utc_day) || value.utc_day < 0 || value.utc_day > 1000000 || !Number.isFinite(value.generated_at) || !Number.isFinite(value.as_of) ||
    !object(value.policy) || value.policy.version !== "daily-pattern-research-v1" || !/^[a-f0-9]{64}$/.test(value.policy_sha256) ||
    !object(value.roster) || !Number.isFinite(value.roster.observed_at) || !Array.isArray(value.roster.rows) || !object(value.pool) ||
    !Array.isArray(value.enrolled_today) || !value.enrolled_today.every(symbolId) ||
    !Array.isArray(value.limitations) || !value.limitations.every(v => typeof v === "string") ||
    !Array.isArray(value.picks) || value.picks.length > 5 || new Set(value.picks.map(p => p.symbol)).size !== value.picks.length ||
    value.picks.some((p, index) => !symbolId(p.symbol) || p.campaign_id !== value.campaign_id || p.rank !== index + 1 ||
      !["recognized_setup", "analyzed_no_setup", "history_pending"].includes(p.basis) || typeof p.reason !== "string" ||
      p.prepared_timeframes != null && (!Array.isArray(p.prepared_timeframes) || p.prepared_timeframes.some(f => !frames.includes(f)) || new Set(p.prepared_timeframes).size !== p.prepared_timeframes.length) ||
      p.observed_eligible !== true || !Number.isFinite(p.captured_at) || !Array.isArray(p.coverage) || p.coverage.length !== 5 ||
      new Set(p.coverage.map(c => c.timeframe)).size !== 5 || p.coverage.some(c => !frames.includes(c.timeframe) || typeof c.status !== "string" || !(c.progress_sha256 === null || typeof c.progress_sha256 === "string" && /^[a-f0-9]{64}$/.test(c.progress_sha256))) ||
      !Array.isArray(p.evidence) || p.evidence.some(e => !["patterns", "alerts"].includes(e.kind) || !Number.isSafeInteger(e.seq) || e.seq <= 0 || !frames.includes(e.timeframe) || !object(e.body)) ||
      p.basis === "recognized_setup" && (p.evidence.length === 0 || p.evidence.some(e => !p.coverage.find(c => c.timeframe === e.timeframe)?.progress_sha256)))) {
    throw new Error("The saved daily shortlist is incomplete or has a different identity. No current shortlist was substituted.");
  }
}

export function DailyAnalyzer({ selection, statusError, checked, enableDisabled, pauseDisabled, onEnable, onPause, onOpen }:
  { selection: DailySelection | null; statusError: string | null; checked: number | null;
    enableDisabled: boolean; pauseDisabled: boolean; onEnable: () => void; onPause: () => void;
    onOpen: (campaign: string, symbol: string, snapshot: string, evidence?: Evidence) => void }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [requested, setRequested] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState<Page | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [listBusy, setListBusy] = useState(false);
  const [chosen, setChosen] = useState("");
  const detailRead = useEvidenceRead(); const listRead = useEvidenceRead();
  const latestId = selection?.latest_id ?? null;
  const latestRef = useRef(latestId); latestRef.current = latestId;
  const explicit = useRef(false); const openRef = useRef<(id: string, remember?: boolean) => void>(() => {});

  async function open(id: string, remember = true) {
    explicit.current = remember || explicit.current;
    setRequested(id); setSnapshot(null); setError(null);
    const read = detailRead.begin(7000); setBusy(true);
    if (remember) {
      const params = new URLSearchParams(location.hash.split("?")[1] ?? ""); params.set("daily_shortlist", id);
      history.replaceState(null, "", `#markets?${params}`);
    }
    try {
      if (!dailyId(id)) throw new Error("Invalid saved daily identity. No latest shortlist was substituted.");
      const response = await fetch(`${endpoint}/${encodeURIComponent(id)}`, { cache: "no-store", signal: read.signal });
      if (!response.ok) throw new Error("The exact saved daily shortlist is unavailable. Its picks have not been replaced.");
      const value = await response.json() as Snapshot; validateSnapshot(value, id);
      if (read.isCurrent()) setSnapshot(value);
    } catch (cause) { if (read.isCurrent()) setError(cause instanceof Error ? cause.message : "Saved shortlist unavailable."); }
    finally { if (read.isCurrent()) setBusy(false); }
  }
  openRef.current = (id, remember) => { void open(id, remember); };
  useEffect(() => {
    const restore = () => {
      const id = new URLSearchParams(location.hash.split("?")[1] ?? "").get("daily_shortlist");
      explicit.current = id !== null;
      if (id !== null) openRef.current(id, false);
      else if (latestRef.current) openRef.current(latestRef.current, false);
      else { detailRead.cancel(); setRequested(null); setSnapshot(null); setError(null); setBusy(false); }
    };
    restore(); addEventListener("hashchange", restore); addEventListener("popstate", restore);
    return () => { removeEventListener("hashchange", restore); removeEventListener("popstate", restore); };
  }, [detailRead.cancel]);
  useEffect(() => { if (latestId && !explicit.current) openRef.current(latestId, false); }, [latestId]);

  async function readList(before?: number | null) {
    const read = listRead.begin(7000); setListBusy(true); setListError(null);
    try {
      const response = await fetch(`${endpoint}${before == null ? "" : `?before=${before}`}`, { cache: "no-store", signal: read.signal });
      if (!response.ok) throw new Error("Saved daily history is unavailable; no empty successful list was substituted.");
      const value = await response.json() as Page;
      if (!Array.isArray(value.rows) || value.rows.length > 100 || !Number.isSafeInteger(value.total) || value.total < value.rows.length ||
        !(value.next_before === null || Number.isSafeInteger(value.next_before) && value.next_before > 0) ||
        value.rows.some(row => !dailyId(row.id) || !campaignId(row.campaign_id) || !Number.isSafeInteger(row.seq) || !Number.isSafeInteger(row.utc_day) || !Array.isArray(row.picks))) throw new Error("Saved daily history is incomplete.");
      if (read.isCurrent()) { setPage(value); setChosen(value.rows[0]?.id ?? ""); }
    } catch (cause) { if (read.isCurrent()) { setPage(null); setChosen(""); setListError(cause instanceof Error ? cause.message : "Daily history unavailable."); } }
    finally { if (read.isCurrent()) setListBusy(false); }
  }

  return <section className="daily-analyzer" aria-labelledby="daily-analyzer-title">
    <header><div><p className="station-kicker">DAILY RESEARCH PRIORITIES</p><h4 id="daily-analyzer-title">Daily crypto analyzer</h4></div><span>Up to five · all five native frames</span></header>
    <p>Each UTC day, the existing scanner assesses eligible USD markets and saves an immutable research shortlist. Recognized setups, analyzed markets without a setup, and markets awaiting history have different evidence. A rank is a research priority, not a win probability.</p>
    <div className="scanner-status" role="status"><strong>{statusError ? "Daily status unavailable" : selection ? words(selection.state) : "Daily policy unavailable"}</strong>
      <span>{statusError ? "Last observed" : "Observed"} {checked == null ? "unknown" : new Date(checked).toLocaleString()}</span>
      <p>{selection?.reason ?? (selection ? selection.enabled ? "The daily producer follows recorded progress and protected admission; each UTC assessment remains separately saved." : "Daily analysis is disabled. Enable explicitly to assess and prepare eligible markets through the existing scanner." : "Daily policy activity is unknown until a complete status observation is available.")}</p>
      {selection && <p>{selection.enabled ? "Daily producer enabled" : "Daily producer paused / disabled"} · UTC assessment due {selection.next_due_at == null ? "not scheduled in this observation" : new Date(selection.next_due_at * 1000).toISOString()} (local {localTime(selection.next_due_at)}).{selection.active_day != null && ` Assessing UTC day ${utcDay(selection.active_day)}.`}</p>}
    </div>
    <div className="scanner-controls"><button type="button" disabled={enableDisabled || !selection || selection.enabled} onClick={onEnable}>Enable daily analysis</button>
      <button type="button" disabled={pauseDisabled || !selection?.campaign_id} onClick={onPause}>Pause daily analysis</button>
      <button type="button" disabled={!latestId || busy} onClick={() => {
        explicit.current = false; const params = new URLSearchParams(location.hash.split("?")[1] ?? ""); params.delete("daily_shortlist");
        history.replaceState(null, "", `#markets?${params}`); if (latestId) void open(latestId, false);
      }}>Show latest daily shortlist</button></div>
    <p>Enable is an explicit control. Reloading this workspace only reads saved results. Pause stops the daily producer and its campaign; retained picks and charts remain readable.</p>
    {busy && <p role="status">Reading exact saved daily shortlist…</p>}{error && <p role="alert">{error}</p>}
    {!snapshot && !busy && !error && <p>{requested ? "The requested shortlist has no confirmed result in this view." : "No saved daily shortlist is available in this observation. No five picks or patterns have been invented."}</p>}
    {snapshot && <div data-daily-id={snapshot.id}>
      <h5>{utcDay(snapshot.utc_day)} UTC · {snapshot.picks.length} saved research candidates</h5>
      <p>{snapshot.id} · {snapshot.id === latestId ? "Latest observed daily record" : "Earlier saved daily record"}. Assessment as of {localTime(snapshot.as_of)}; saved {localTime(snapshot.generated_at)}. Original market screen {localTime(snapshot.roster.observed_at)}.</p>
      <p>Captured pool: {count(snapshot.pool.eligible)} eligible · {count(snapshot.pool.analyzed)} analyzed · {count(snapshot.pool.pending)} history pending · {count(snapshot.pool.excluded)} excluded. Newly enrolled today: {snapshot.enrolled_today.length ? snapshot.enrolled_today.join(", ") : "none recorded"}.</p>
      <div className="daily-picks">{snapshot.picks.map(pick => {
        const current = !statusError && selection?.current_roster.available ? selection.current_roster.rows.find(row => row.symbol === pick.symbol) : null;
        return <article key={pick.symbol} aria-label={`Daily candidate ${pick.rank} ${pick.symbol}`}>
          <header><h5>#{pick.rank} · {pick.symbol.replace(/USD$/, " / USD")}</h5><strong className={`daily-basis ${pick.basis}`}>{pick.basis === "history_pending" ? "History pending · liquidity priority" : pick.basis === "recognized_setup" ? "Recorded setup" : "Analyzed · no qualifying recent setup"}</strong></header>
          <p>{pick.reason}</p><p>Original 24-hour quote volume (USD): {metric(pick.quote_volume)} · spread {metric(pick.spread_bps)} bps · trades {count(pick.trades)}. Candidate observation {localTime(pick.captured_at)}.</p>
          <p className="daily-current">Current eligibility: {current ? current.eligible ? "Eligible in the separate current screen" : "Currently ineligible" : "Unknown / unavailable"}{current ? ` · ${current.reason}` : ""}. Screen observed {localTime(selection?.current_roster.observed_at)}; the saved rank above is unchanged.</p>
          <button type="button" onClick={() => onOpen(snapshot.campaign_id, pick.symbol, snapshot.id)}>Inspect current saved charts for {pick.symbol}</button>
          <p>Recorded prepared frames at capture: {pick.prepared_timeframes ? pick.prepared_timeframes.length ? pick.prepared_timeframes.join(", ") : "none" : "unknown"}. Preparation status does not certify gap-free year coverage.</p>
          <div className="scanner-table-scroll"><table><caption>Saved five-frame coverage at candidate capture</caption><thead><tr><th>Frame / state</th><th>Actual / expected</th><th>Missing / gaps</th><th>Source / cutoff</th></tr></thead><tbody>{pick.coverage.map(row => <tr key={row.timeframe}><td>{row.timeframe} · {words(row.status)}{row.error && <p>{row.error}</p>}</td><td>{count(row.observed_bars)} / {count(row.expected_bars)}</td><td>{count(row.missing_bars)} / {count(row.gap_count)}</td><td>{nativeTime(row.requested_start_ms)} to {nativeTime(row.cutoff_ms)}<br />Processed through {nativeTime(row.cursor_ms)}; last native close {nativeTime(row.latest_close_ms)}</td></tr>)}</tbody></table></div>
          {pick.basis === "history_pending" && <p>No detected setup or completed-year claim follows from this history priority.</p>}
          {pick.evidence.map(event => <details key={`${event.kind}:${event.timeframe}:${event.seq}`}><summary>{words(event.body.kind)} · {event.timeframe} · original #{event.seq}</summary>
            <p>{typeof event.body.reason === "string" ? event.body.reason : "No original explanation recorded."}</p>
            <p>The original record below remains frozen. Its captured-progress chart may be unavailable after processing advances; no current window will be substituted. Use Inspect current saved charts explicitly to read newer progress.</p>
            <p>Native candle {nativeTime(event.body.bar_open_ms)} · volume confirmation {event.body.volume_confirmed === true ? "recorded" : event.body.volume_confirmed === false ? "not met" : "unknown"} · volume ratio {metric(event.body.volume_ratio)}.</p>
            <button type="button" onClick={() => onOpen(snapshot.campaign_id, pick.symbol, snapshot.id, { ...event, progress_sha256: pick.coverage.find(row => row.timeframe === event.timeframe)?.progress_sha256 ?? undefined })}>Try captured chart for original pattern</button><pre>{JSON.stringify(event, null, 2)}</pre></details>)}
          <details><summary>Original candidate inputs and source identities</summary><pre>{JSON.stringify(pick, null, 2)}</pre></details>
        </article>;
      })}</div>
      <details><summary>Frozen ranking policy and limitations</summary><pre>{JSON.stringify(snapshot.policy, null, 2)}</pre><p>Policy SHA256 {snapshot.policy_sha256}.</p><ul>{snapshot.limitations.map((limit, i) => <li key={i}>{limit}</li>)}</ul></details>
    </div>}
    <details><summary>Earlier immutable daily shortlists</summary><div className="scanner-controls"><button type="button" disabled={listBusy} onClick={() => void readList()}>Read saved daily shortlists</button>
      <label>Saved UTC day <select aria-label="Saved daily shortlist" value={chosen} onChange={event => setChosen(event.target.value)}><option value="">Choose a saved day</option>{page?.rows.map(row => <option key={row.id} value={row.id}>{utcDay(row.utc_day)} · {row.picks.length} picks · {row.id}</option>)}</select></label>
      <button type="button" disabled={busy || !chosen} onClick={() => void open(chosen)}>Reopen exact daily shortlist</button><button type="button" disabled={listBusy || page?.next_before == null} onClick={() => void readList(page?.next_before)}>Older daily shortlists</button></div>
      {page && <p>{page.rows.length} saved days on this page / {count(page.total)} total.</p>}{listError && <p role="alert">{listError}</p>}</details>
  </section>;
}
