import { useEffect, useState } from "react";
type Report = { assessment: string; recommendation: string; selection_warning: string; attempts: number; failed_attempts: number; external_attempts: number; native_usage: {attempts_with_counts: number; input_tokens: number | null; output_tokens: number | null; unknown_attempts: number; measured_wall_seconds: number | null; basis: string}; economic_value: {reason: string}; matched_research_arms: {arm: string; method: string; reason: string}[] };
export function ResearchQualityPanel({ experimentalPilot = false }: { experimentalPilot?: boolean }) {
  const [report,setReport] = useState<Report | null>(null);
  const [error,setError] = useState<string | null>(null);
  const [refresh,setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    void (async () => {
      try {
        const response = await fetch("/api/research/quality",{cache:"no-store",signal:AbortSignal.any([controller.signal,AbortSignal.timeout(6000)])});
        if (!response.ok) throw new Error("Research quality report is unavailable. No previous count implies current completion.");
        const value = await response.json() as Report;
        if (live) {setReport(value);setError(null);}
      } catch(cause) {if(live) setError(String(cause));}
    })();
    return () => {live=false;controller.abort();};
  },[refresh]);
  return <section aria-labelledby="research-quality-title"><h3 id="research-quality-title">Research usefulness and cost</h3>
    <button type="button" onClick={() => setRefresh(n => n+1)}>Refresh research quality</button>
    {error && <p role="alert">{error}</p>}
    {report && <><p>{report.assessment}</p><p>Recorded attempts {report.attempts} · failed {report.failed_attempts} · external {report.external_attempts}. Endpoint token counts exist for {report.native_usage.attempts_with_counts} attempts; {report.native_usage.unknown_attempts} remain unknown.</p><p>Measured input tokens: {report.native_usage.input_tokens ?? "unknown"}; output tokens: {report.native_usage.output_tokens ?? "unknown"}; measured model seconds: {report.native_usage.measured_wall_seconds ?? "unknown"}.</p><p>{report.native_usage.basis}</p><ul>{report.matched_research_arms.map(a => <li key={a.arm}>{a.arm}: {a.method} · {a.reason}</li>)}</ul><p>{report.economic_value.reason}</p><p>{experimentalPilot ? "The approved experimental paper pilot can collect evidence and retain negative or inconclusive results. These records do not establish qualified-role comparison coverage or economic model usefulness. External activation and promotion remain separate decisions." : report.recommendation}</p><p>{report.selection_warning}</p></>}
  </section>;
}
