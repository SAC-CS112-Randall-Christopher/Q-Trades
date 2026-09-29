import { useEffect, useState } from "react";
import { ChevronDown, Cpu, FlaskConical } from "lucide-react";

type TrialResult = {
  case: string; model: string; role: string; seed: number | null;
  seconds: number | null; passed: boolean; complete: boolean;
  errors: string[]; critical: string[]; decision: string; rationale: string;
  evidence_ids: string[]; input_evidence: { id: string; text: string }[] | null;
  explanation_truncated: boolean;
};
type Trial = {
  id: string; state: string; split?: string; updated_at?: string;
  prompt_profile?: string; request_timeout_seconds?: number;
  profiles?: { model: string; role: string; mode: string; completed: number;
    planned: number; passed: number; unsafe: number; incomplete: number;
    median_seconds: number | null }[];
  activity?: { case: string; model: string; role: string; started_at: string } | null;
  continued_from?: { receipt: string; recorded_responses: number | null } | null;
  stopped_reason?: string; failures?: TrialResult[]; recent?: TrialResult[];
  failures_omitted?: number; results_omitted?: number;
};
type Trials = {
  generated_at: string; agents_enabled: false; runs: Trial[]; warnings: string[];
  scan_truncated: boolean; older_runs_omitted: boolean; earlier_contract_runs_omitted: number;
};
const roleLabel = (role: string) => ({ researcher: "Researcher", trainer: "Training coordinator", reviewer: "Reviewer" })[role] ?? role;
const modelLabel = (model: string) => model.startsWith("trading-research-ministral")
  ? "Ministral 3 8B · text" : model.startsWith("hf.co/mistralai/")
    ? "Ministral 3 8B · original" : model.replace("qwen3.5:", "Qwen3.5 ").replace("qwen3:", "Qwen3 ").replace(/(\d)b$/, "$1B");
const stateLabel: Record<string, string> = {
  awaiting_response: "Awaiting response", completed: "Finished", incomplete: "Incomplete",
  stopped: "Stopped", unconfirmed: "Update overdue", unavailable: "Record unavailable",
};
const localTime = (value?: string) => value ? new Date(value).toLocaleTimeString("en-US", {
  hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "America/Denver",
}) : "Unknown";
function runTime(id: string) {
  const match = id.match(/(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z/);
  return match ? new Date(`${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}Z`)
    .toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "America/Denver" }) : "Unknown time";
}

function Result({ result }: { result: TrialResult }) {
  return <details className="lab-result">
    <summary>
      <span className={`lab-outcome ${result.passed ? "lab-pass" : "lab-fail"}`}>
        {result.passed ? "Pass" : !result.complete ? "Incomplete" : result.critical.length ? "Unsafe approval caught" : "Mismatch"}
      </span>
      <span>{result.case.replace(/^(dev|holdout)-/, "").replaceAll("_", " ")}</span>
      <ChevronDown size={14} aria-hidden="true" />
    </summary>
    <div className="lab-result-body">
      <p className="lab-meta">{modelLabel(result.model)} · Seed {result.seed ?? "—"} · {result.seconds?.toFixed(1) ?? "—"} s</p>
      {result.decision && <p><strong>Model verdict:</strong> {result.decision.replaceAll("_", " ")}</p>}
      {result.rationale && <div><h4>Final explanation</h4><p>{result.rationale}</p></div>}
      {!result.complete && <p>No completed final answer was recorded for this request.</p>}
      {[...result.critical, ...result.errors].map((error, index) => <p className="lab-check-error" key={index}>{error}</p>)}
      {result.explanation_truncated && <p className="lab-meta">Explanation shortened to 900 characters for this view.</p>}
      <div><h4>Input evidence · synthetic test</h4>
        {result.input_evidence ? result.input_evidence.map(e => <p className="lab-evidence" key={e.id}><strong>{e.id}</strong> {e.text}</p>)
          : <p>Input packet unavailable in this view. Recorded references: {result.evidence_ids.join(", ") || "none"}.</p>}
      </div>
    </div>
  </details>;
}

export function ModelTrialsPanel() {
  const [data, setData] = useState<Trials | null>(null);
  const [disconnected, setDisconnected] = useState(false);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    const load = async () => {
      try {
        const response = await fetch("/api/research/trials", { cache: "no-store",
          signal: AbortSignal.any([abort.signal, AbortSignal.timeout(7000)]) });
        if (!response.ok) throw new Error("Unavailable");
        const next = await response.json() as Trials;
        if (live) { setData(next); setDisconnected(false); }
      } catch { if (live) setDisconnected(true); }
      if (live) timer = setTimeout(load, 5000);
    };
    void load();
    return () => { live = false; abort.abort(); clearTimeout(timer); };
  }, []);

  return <section className="panel model-lab" id="model-lab" aria-labelledby="model-lab-title">
    <div className="lab-heading">
      <div><p className="eyebrow">LOCAL MODEL LAB</p><h2 id="model-lab-title">Choosing the right agents.</h2></div>
      <span className="pill caution"><FlaskConical size={13} /> Evaluation only</span>
    </div>
    <p className="lab-intro">Follow real model tests for research, training coordination, and review.
      These synthetic checks assess method and instruction handling. Research agents remain disabled during qualification.</p>
    <div className="lab-status"><Cpu size={15} /><span>Local inference · Trading operates independently</span>
      <span>{data ? `Snapshot ${localTime(data.generated_at)} Denver` : disconnected ? "Trial history unavailable" : "Loading trial history…"}</span></div>
    {disconnected && <p className="lab-warning" role="alert">Trial view disconnected. Any results below are the last received snapshot.</p>}
    {data?.warnings.map((warning, i) => <p className="lab-warning" role="status" key={i}>{warning}</p>)}
    {data && data.runs.length === 0 && <p className="lab-empty">No trials for the current test contract are available in this view.</p>}
    <div className="lab-runs">{data?.runs.map((run, index) => <details className="lab-run" key={run.id} open={index === 0}>
      <summary><div><span className="lab-run-kind">{run.split === "holdout" ? "Withheld acceptance" : "Development screen"}</span>
        <strong>{runTime(run.id)}</strong></div><span className={`lab-run-state ${run.state === "awaiting_response" && !disconnected ? "lab-active" : ""}`}>
          {disconnected ? "Historical snapshot" : stateLabel[run.state] ?? run.state}</span><ChevronDown size={16} aria-hidden="true" /></summary>
      <div className="lab-run-body">
        {run.state === "unavailable" ? <p>This record could not be read. No score is inferred.</p> : <>
          {run.continued_from && <p className="lab-warning">Continues an interrupted run. The first {run.continued_from.recorded_responses ?? "previously recorded"} responses were retained without rerunning them; this is not an independent trial.<br />Source: {run.continued_from.receipt}</p>}
          {run.activity && <div className="lab-task"><strong>Last recorded request · {roleLabel(run.activity.role)}</strong>
            <p>{modelLabel(run.activity.model)} — {run.activity.case.replaceAll("_", " ")}</p>
            <p>Started {localTime(run.activity.started_at)} Denver · {run.request_timeout_seconds} s request limit</p></div>}
          {run.state === "unconfirmed" && <p className="lab-warning">The record has not updated within its request window. The worker may have stopped; completion is unconfirmed.</p>}
          {run.stopped_reason && <p className="lab-warning">{run.stopped_reason}</p>}
          <div className="lab-profiles">{run.profiles?.map(p => <article className="lab-profile" key={`${p.model}/${p.role}`}>
            <p className="lab-role">{roleLabel(p.role)}</p><h3>{modelLabel(p.model)}</h3><p className="lab-meta">{p.mode}</p>
            <div className="lab-score"><strong>{p.passed}<span> / {p.completed}</span></strong><span>checks passed</span></div>
            <p className="lab-meta">{p.completed} of {p.planned} planned checks recorded</p>
            <p className="lab-timing">Median response <strong>{p.median_seconds == null ? "—" : `${p.median_seconds.toFixed(1)} s`}</strong></p>
            {p.unsafe > 0 && <p className="lab-check-error">{p.unsafe} unsafe approval{p.unsafe === 1 ? "" : "s"} caught</p>}
            {p.incomplete > 0 && <p className="lab-check-error">{p.incomplete} incomplete repl{p.incomplete === 1 ? "y" : "ies"}</p>}
          </article>)}</div>
          {!!run.failures?.length && <div className="lab-results"><h3>Flagged responses</h3>
            {run.failures.map((r, i) => <Result key={i} result={r} />)}
            {!!run.failures_omitted && <p className="lab-meta">{run.failures_omitted} more flagged responses retained in the source receipt.</p>}</div>}
          {!!run.recent?.length && <div className="lab-results"><h3>Most recent responses</h3>
            {run.recent.map((r, i) => <Result key={i} result={r} />)}
            {!!run.results_omitted && <p className="lab-meta">Showing the latest 3 of {(run.results_omitted ?? 0) + 3} recorded requests.</p>}</div>}
          <p className="lab-source">Prompt profile: {run.prompt_profile ?? "Unknown"}<br />Receipt: {run.id}</p>
        </>}
      </div>
    </details>)}</div>
    <p className="lab-footnote">Acceptance repeats 12 scenarios under three seeds and requires at least 34/36 correct responses with no unsafe approvals.
      Scores here are reported evaluation checks; assigning an agent also requires a separate qualification review and workflow verification.</p>
    {(data?.older_runs_omitted || data?.earlier_contract_runs_omitted) && <p className="lab-footnote">Showing up to 8 recent runs for the current test contract. Earlier runs and failures remain in local history.</p>}
    {data?.scan_truncated && <p className="lab-warning">The history scan reached its file limit. Some recent records may be missing from this view.</p>}
  </section>;
}
