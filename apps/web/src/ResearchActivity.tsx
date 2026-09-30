import { useEffect, useState } from "react";
import "./market-chart.css";
type Activity = { maturity?: { state: string; reason: string; checked_at: number; next_check_at?: number } | null; full_evidence: { latest: { at: number } | null; capacity: { state: string } | null } | null; queried_at: number; market: { at: number } | null; candle: { open_ms: number } | null; processing: number | null; signal: { at: number } | null; training_input: { available: number } | null; mature_outcome: { available: number; status: string } | null; available_outcome: { available: number } | null; completed_learning: { at?: number; finished?: number } | null; next_action: string; resource_reason?: string; warnings: string[] };
const when = (v?: number | null) => v == null ? "No retained record" : new Date(v * 1000).toLocaleString("en-US", { timeZone: "America/Denver", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" }) + " MT";
export function ResearchActivity() {
  const [data, setData] = useState<Activity | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    const read = async () => { try { const r = await fetch("/api/research/activity", { cache: "no-store", signal: AbortSignal.timeout(6000) }); if (!r.ok) throw new Error("Activity unavailable"); const p = await r.json() as Activity; if (active) { setData(p); setError(null); } } catch { if (active) setError("Activity query disconnected; retained dates below may be old"); } };
    void read(); const timer = setInterval(() => { if (!document.hidden) void read(); }, 15000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  return <section className="research-activity" aria-label="Collection and learning activity"><h2>Collection and learning activity</h2>
    {error && <p role="alert">{error}</p>}
    <div className="activity-stages">
      <p><strong>Durable market data</strong>{when(data?.market?.at)}<br />Closed candle: {when(data?.candle ? (data.candle.open_ms + 60000) / 1000 : null)}</p>
      <p><strong>Paper processing</strong>{when(data?.processing)}<br />Last signal evaluation: {when(data?.signal?.at)}</p>
      <p><strong>Durable replay evidence</strong>{when(data?.full_evidence?.latest?.at)}<br />Archive: {data?.full_evidence?.capacity?.state ?? "Unavailable"}</p>
      <p><strong>Research inputs and outcomes</strong>Input: {when(data?.training_input?.available)}<br />Mature outcome: {when(data?.mature_outcome?.available)} ({data?.mature_outcome?.status ?? "unknown"})<br />Last executable label: {when(data?.available_outcome?.available)}</p>
      <p><strong>Completed learning</strong>{when(data?.completed_learning?.at ?? data?.completed_learning?.finished)}<br />Saved model qualification runs have historical result dates.</p>
    </div><p className="activity-action">{data?.next_action ?? "Reading retained activity…"}{data?.resource_reason && <><br />{data.resource_reason}</>}</p>
    {data?.maturity && <p className="activity-action">Delayed outcomes: {data.maturity.state} · {data.maturity.reason}<br />Checked {when(data.maturity.checked_at)}; next bounded check {when(data.maturity.next_check_at)}. This check is separate from new evidence acquisition.</p>}
    {data?.warnings.map(w => <p className="activity-action" key={w}>{w}</p>)}
    <p className="indicator-readout">Activity queried {when(data?.queried_at)}. This query time is not a market observation or a completed learning result.</p>
  </section>;
}
