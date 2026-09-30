import { useEffect, useState, type FormEvent } from "react";
import type { PaperSnapshot } from "./PaperPanel";
import { MemoryQualityPanel } from "./MemoryQualityPanel";
import { ResearchSlicePanel } from "./ResearchSlicePanel";
import { PaperCampaignJournal } from "./PaperCampaignJournal";
import {
  ResearchCampaignPanel,
  type ResearchCampaign,
} from "./ResearchCampaignPanel";
import {
  Activity,
  BrainCircuit,
  Database,
  FlaskConical,
  ShieldCheck,
} from "lucide-react";

type Plan = {
  experiment_mode?: string;
  name: string;
  mechanism: string;
  falsification: string;
  feature: string;
  horizon_minutes: number;
  test_start: number;
  test_end: number;
  as_of: number;
  request_id: string;
};
type Candidate = {
  family: string;
  name: string;
  mechanism: string;
  failure_regimes: string;
  status: string;
  reason?: string;
  qualification?: string;
  execution_replay?: string;
  artifact?: { sha256: string };
  metrics?: Record<string, unknown>;
  train_samples?: number;
  test_samples?: number;
};
type Run = {
  seq: number;
  request_id: string;
  plan: Plan;
  status: string;
  progress: string;
  reason: string | null;
  attempt: number;
};
type Lab = {
  runs: Run[];
  counts: Record<string, number>;
  protected_through: number;
  preflight_result: string;
  worker_running: boolean;
  blocked_reason: string | null;
  capacity: number;
  queue_capacity: number;
  next_cursor: number | null;
  research_campaigns?: ResearchCampaign[];
};
type Result = Run & {
  plan_sha256: string;
  code_sha256: string;
  snapshot_sha256: string;
  manifest: { rows: number; older_rows_omitted: boolean } | null;
  result: {
    status: string;
    reason?: string;
    decision: string;
    next_action: string;
    train_samples?: number;
    test_samples?: number;
    metrics?: Record<string, unknown>;
    limitations?: string[];
    model?: Record<string, unknown>;
    evidence_kind?: string;
    candidate_group?: Candidate[];
    selection_treatment?: string;
  } | null;
  events: { at: number; kind: string; body: string }[];
};
const stamp = (seconds: number) => new Date(seconds * 1000).toLocaleString();
const localDate = (seconds: number) => {
  const d = new Date(seconds * 1000);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
};

export function ExperimentLab({ paper }: { paper?: PaperSnapshot }) {
  const [lab, setLab] = useState<Lab | null>(null);
  const [before, setBefore] = useState(0);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("Five-minute momentum forecast");
  const [mechanism, setMechanism] = useState(
    "Recent direction may persist beyond the execution cost hurdle.",
  );
  const [falsification, setFalsification] = useState(
    "Reject when out-of-sample forecasts fail the constant baseline or after-cost hurdle.",
  );
  const [feature, setFeature] = useState("momentum_5");
  const [horizon, setHorizon] = useState(5);
  const [distinct, setDistinct] = useState(false);
  const [forwardCash, setForwardCash] = useState("100");
  const [daily, setDaily] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState(localDate(Date.now() / 1000 - 60));
  const [retry, setRetry] = useState<Plan | null>(() => {
    try {
      return JSON.parse(
        localStorage.getItem("qtrades-experiment-retry") ?? "null",
      ) as Plan | null;
    } catch {
      return null;
    }
  });
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await fetch(`/api/lab?before=${before}`, {
          signal: AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(6000),
          ]),
        });
        if (!response.ok)
          throw new Error(
            "Research registry unavailable; paper operation is separate.",
          );
        const data = (await response.json()) as Lab;
        if (live) {
          setLab(data);
          setStart(
            (current) => current || localDate(data.protected_through + 3660),
          );
        }
      } catch (e) {
        if (live)
          setError(e instanceof Error ? e.message : "Research unavailable");
      }
      if (live) timer = setTimeout(() => void poll(), 5000);
    };
    void poll();
    return () => {
      live = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [before]);
  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    setDetail(null);
    let live = true;
    let terminalSeen = false;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await fetch(
          `/api/lab/experiments/${encodeURIComponent(selected)}`,
          {
            signal: AbortSignal.any([
              controller.signal,
              AbortSignal.timeout(6000),
            ]),
          },
        );
        if (!response.ok) throw new Error("Experiment result unavailable");
        const value = (await response.json()) as Result;
        if (!live) return;
        setDetail(value);
        const terminal = [
          "completed",
          "failed",
          "cancelled",
          "rejected",
        ].includes(value.status);
        // One final short read captures the supervisor's resource receipt.
        if (!terminal || !terminalSeen)
          timer = setTimeout(() => void poll(), terminal ? 500 : 5000);
        terminalSeen = terminal;
      } catch (e) {
        if (live) {
          setError(String(e));
          timer = setTimeout(() => void poll(), 5000);
        }
      }
    };
    void poll();
    return () => {
      live = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [selected]);
  async function post(url: string, body?: unknown) {
    const response = await fetch(url, {
      method: "POST",
      signal: AbortSignal.timeout(10000),
      headers: { "X-Local-Operator": "1", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const value = await response.json().catch(() => ({}));
      throw new Error(
        typeof value.detail === "string"
          ? value.detail
          : "Check the declared evaluation inputs",
      );
    }
    return response.json() as Promise<{ request_id: string }>;
  }
  async function launch(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const dates = new FormData(event.currentTarget as HTMLFormElement);
    const plan = retry ?? {
      request_id: crypto.randomUUID(),
      name,
      mechanism,
      falsification,
      feature,
      experiment_mode: distinct ? "distinct_families" : "quote_ridge",
      horizon_minutes: distinct ? 60 : horizon,
      test_start: new Date(String(dates.get("test_start"))).getTime() / 1000,
      test_end: new Date(String(dates.get("test_end"))).getTime() / 1000,
      as_of: Date.now() / 1000,
    };
    try {
      localStorage.setItem("qtrades-experiment-retry", JSON.stringify(plan));
      setRetry(plan);
      const value = await post("/api/lab/experiments", plan);
      setSelected(value.request_id);
      localStorage.removeItem("qtrades-experiment-retry");
      setRetry(null);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Launch unconfirmed; retry the frozen request",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section id="experiment-lab" className="panel experiment-lab">
      <div className="metrics-grid lab-metrics" aria-label="Research summary">
        <article className="metric-card">
          <div className="metric-label">
            Retained experiments <FlaskConical size={18} />
          </div>
          <div className="metric-value">
            {lab ? Object.values(lab.counts).reduce((a, b) => a + b, 0) : "—"}
          </div>
          <p>Every completed or rejected outcome</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Queued work <Activity size={18} />
          </div>
          <div className="metric-value">
            {lab ? (lab.counts.queued ?? 0) + (lab.counts.acquiring ?? 0) : "—"}
            <span className="metric-unit">/ {lab?.queue_capacity ?? 8}</span>
          </div>
          <p>One bounded fit child at a time</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Completed experiments <Database size={18} />
          </div>
          <div className="metric-value">
            {lab ? (lab.counts.completed ?? 0) : "—"}
          </div>
          <p>Completion does not grant qualification</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Research worker <BrainCircuit size={18} />
          </div>
          <div className="metric-value state-title">
            {!lab
              ? "Connecting"
              : lab.blocked_reason
                ? "Yielding"
                : lab.worker_running
                  ? "Running"
                  : "Stopped"}
          </div>
          <p>Local CPU · paid spending $0</p>
        </article>
        <article className="metric-card">
          <div className="metric-label">
            Paper-role evidence <ShieldCheck size={18} />
          </div>
          <div className="metric-value">
            {paper?.learning?.reports.filter(
              (r) => r.decision === "eligible_for_paper_designation",
            ).length ?? 0}
          </div>
          <p>Reports eligible for human review</p>
        </article>
      </div>
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Protected numerical research</span>
          <h2>Experiments and retained evidence</h2>
        </div>
        <span className="paper-badge">Paper only · paid budget $0</span>
      </div>
      <p>
        Freeze one hypothesis and evaluation window. Research runs outside order
        management; a rejection remains useful evidence. Changed features and
        files cannot reuse inspected information.
      </p>
      {lab && (
        <p className="lab-status">
          Evidence protected through {stamp(lab.protected_through)}. Retained
          preflight: {lab.preflight_result}. Worker:{" "}
          {lab.worker_running ? "running" : "stopped"}.
          {lab.blocked_reason && ` ${lab.blocked_reason}.`} Queue limit{" "}
          {lab.queue_capacity}; receipt limit {lab.capacity}.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      <div className="lab-overview">
        <section className="workspace-card">
          <div className="card-heading">
            <h3>Evidence before adaptation</h3>
            <BrainCircuit size={23} />
          </div>
          <p>
            Three registered mechanisms: slower trend, volatility expansion and
            range-conditioned reversion. A common holdout keeps the search
            visible.
          </p>
          <div className="insight-highlight">
            <ShieldCheck size={25} />
            <div>
              <strong>Frozen inputs. Retained outcomes.</strong>
              <p>
                No automatic funding, live orders or promotion. Insufficient
                results stay insufficient.
              </p>
            </div>
          </div>
        </section>
        <section className="workspace-card">
          <div className="card-heading">
            <h3>Research boundaries</h3>
            <ShieldCheck size={23} />
          </div>
          <dl className="insight-facts">
            <div>
              <dt>Fit child</dt>
              <dd>1 · ≤2 processors</dd>
            </div>
            <div>
              <dt>Child memory</dt>
              <dd>≤256 MiB</dd>
            </div>
            <div>
              <dt>Attempt wall time</dt>
              <dd>≤25 seconds</dd>
            </div>
            <div>
              <dt>GPU / paid calls</dt>
              <dd>None</dd>
            </div>
          </dl>
        </section>
      </div>
      {lab && (
        <details className="workspace-details">
          <summary>
            Finite research campaigns ({lab.research_campaigns?.length ?? 0})
          </summary>
          <ResearchCampaignPanel
            campaigns={lab.research_campaigns ?? []}
            protectedThrough={lab.protected_through}
            blocked={lab.blocked_reason}
            select={setSelected}
          />
        </details>
      )}
      <details className="workspace-details lab-new-plan">
        <summary>Declare a new experiment</summary>
        <form onSubmit={(event) => void launch(event)}>
          <fieldset disabled={busy || !!retry}>
            <label>
              Hypothesis name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                minLength={3}
                maxLength={100}
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={distinct}
                onChange={(e) => setDistinct(e.target.checked)}
              />
              Compare three distinct mechanisms on one protected window
            </label>
            {distinct && (
              <p>
                Slower trend, volatility expansion and range-conditioned
                reversion share one declared holdout. Nine predeclared threshold
                checks remain part of the same search; none grants independent
                confirmation.
              </p>
            )}
            <label>
              Why it might persist
              <textarea
                value={mechanism}
                onChange={(e) => setMechanism(e.target.value)}
                required
                minLength={12}
                maxLength={1000}
              />
            </label>
            <label>
              What would reject it
              <textarea
                value={falsification}
                onChange={(e) => setFalsification(e.target.value)}
                required
                minLength={12}
                maxLength={1000}
              />
            </label>
            <div className="lab-form-row">
              <label>
                Input
                <select
                  disabled={distinct}
                  value={feature}
                  onChange={(e) => setFeature(e.target.value)}
                >
                  <option value="momentum_1">One-minute direction</option>
                  <option value="momentum_5">Five-minute direction</option>
                  <option value="volatility_5">Recent volatility</option>
                  <option value="spread_bps">Observed spread</option>
                </select>
              </label>
              <label>
                Forecast horizon
                <select
                  disabled={distinct}
                  value={distinct ? 60 : horizon}
                  onChange={(e) => setHorizon(Number(e.target.value))}
                >
                  {[5, 15, 60].map((n) => (
                    <option key={n} value={n}>
                      {n} minutes
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Untouched evaluation starts
                <input
                  name="test_start"
                  type="datetime-local"
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                  onInput={(e) => setStart(e.currentTarget.value)}
                  required
                />
              </label>
              <label>
                Evaluation ends
                <input
                  name="test_end"
                  type="datetime-local"
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                  onInput={(e) => setEnd(e.currentTarget.value)}
                  required
                />
              </label>
            </div>
          </fieldset>
          <button type="submit" disabled={busy || !lab}>
            {busy
              ? "Freezing…"
              : retry
                ? "Confirm frozen request"
                : "Freeze and queue experiment"}
          </button>
          {retry && (
            <button
              type="button"
              onClick={() => {
                setRetry(null);
                localStorage.removeItem("qtrades-experiment-retry");
              }}
            >
              Edit a new plan
            </button>
          )}
        </form>
      </details>
      <div className="card-heading">
        <h3>Experiments &amp; retained outcomes</h3>
        <span className="subtle-note">
          Select an experiment to inspect its receipt
        </span>
      </div>
      <div className="lab-runs">
        {lab?.runs.map((run) => (
          <button
            type="button"
            key={run.request_id}
            onClick={() => setSelected(run.request_id)}
            aria-pressed={selected === run.request_id}
          >
            <strong>{run.plan.name}</strong>
            <span>
              {run.status} · attempt {run.attempt}
            </span>
            <small>{run.reason ?? run.progress}</small>
          </button>
        ))}
      </div>
      <div className="lab-form-row">
        <button type="button" disabled={!before} onClick={() => setBefore(0)}>
          Latest experiments
        </button>
        <button
          type="button"
          disabled={!lab?.next_cursor}
          onClick={() => setBefore(lab?.next_cursor ?? 0)}
        >
          Older experiments
        </button>
      </div>
      {detail && (
        <article className="lab-result">
          <h3>{detail.plan.name}</h3>
          <p>{detail.plan.mechanism}</p>
          <p>Reject when: {detail.plan.falsification}</p>
          <p>
            {stamp(detail.plan.test_start)} to {stamp(detail.plan.test_end)} ·{" "}
            {detail.plan.horizon_minutes}-minute labels
          </p>
          <p>
            Status: {detail.status}.{" "}
            {detail.reason ?? detail.result?.reason ?? detail.progress}
          </p>
          {detail.manifest && (
            <p>
              {detail.manifest.rows} retained input events. Older rows omitted:{" "}
              {detail.manifest.older_rows_omitted ? "yes" : "no"}.
            </p>
          )}
          {detail.result && (
            <>
              <h4>Decision: {detail.result.decision}</h4>
              <p>{detail.result.next_action}</p>
              <p>
                Evidence:{" "}
                {detail.result.evidence_kind === "synthetic_qa"
                  ? "Synthetic QA; never independent validation"
                  : "Observed research inputs; prospective qualification is separate"}
                .
              </p>
              {!detail.result.candidate_group && !["context_regime","order_flow","growing_memory","component_exit","component_size","observation_priority"].includes(detail.plan.experiment_mode??"") && (
                <p>
                  Training examples:{" "}
                  {detail.result.train_samples ?? "insufficient"}; test
                  examples: {detail.result.test_samples ?? "insufficient"}.
                  Overlapping labels are correlated.
                </p>
              )}
              {detail.result.metrics && (
                <dl>
                  {Object.entries(detail.result.metrics).filter(([,value])=>value==null||typeof value!=="object").map(([key, value]) => (
                    <div key={key}>
                      <dt>{key.replaceAll("_", " ")}</dt>
                      <dd>{value == null ? "Unavailable" : String(value)}</dd>
                    </div>
                  ))}
                </dl>
              )}
              {detail.result.limitations?.map((note) => (
                <p key={note}>{note}</p>
              ))}
            </>
          )}
          {detail.plan.experiment_mode==="memory_entry" && <MemoryQualityPanel requestId={detail.request_id} readonly/>}
          {["context_regime","order_flow","growing_memory","component_exit","component_size","observation_priority"].includes(detail.plan.experiment_mode??"") && <ResearchSlicePanel requestId={detail.request_id} readonly/>}
          {detail.plan.experiment_mode!=="memory_entry" && detail.result?.candidate_group && (
            <>
              <h4>Frozen candidate families</h4>
              <p>{detail.result.selection_treatment}</p>
              <div className="lab-form-row">
                <label>
                  Forward hypothetical balance
                  <select
                    value={forwardCash}
                    onChange={(e) => setForwardCash(e.target.value)}
                  >
                    <option value="50">$50</option>
                    <option value="100">$100</option>
                  </select>
                </label>
                <label>
                  Forward operating USD/day
                  <input
                    value={daily}
                    onChange={(e) => setDaily(e.target.value)}
                    placeholder="Unknown"
                  />
                </label>
              </div>
              {detail.result.candidate_group.map((candidate) => (
                <article className="lab-result" key={candidate.family}>
                  <h4>{candidate.name}</h4>
                  <p>{candidate.mechanism}</p>
                  <p>Failure regimes: {candidate.failure_regimes}</p>
                  <p>
                    Training examples:{" "}
                    {candidate.train_samples ?? "insufficient"}; matured test
                    examples: {candidate.test_samples ?? "insufficient"}.
                    Overlapping labels are correlated.
                  </p>
                  <p>
                    {candidate.status}:{" "}
                    {candidate.reason ?? candidate.qualification}
                  </p>
                  <p>{candidate.execution_replay}</p>
                  {candidate.metrics && (
                    <dl>
                      {Object.entries(candidate.metrics).map(([key, value]) => (
                        <div key={key}>
                          <dt>{key.replaceAll("_", " ")}</dt>
                          <dd>
                            {value == null ? "Unresolved" : String(value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  {candidate.artifact && (
                    <p>Frozen artifact: {candidate.artifact.sha256}</p>
                  )}
                  <button
                    type="button"
                    disabled={
                      busy ||
                      !candidate.artifact ||
                      !paper?.running ||
                      !!paper.error ||
                      paper.stale
                    }
                    onClick={async () => {
                      setBusy(true);
                      setError(null);
                      try {
                        await post(
                          `/api/lab/experiments/${detail.request_id}/forward`,
                          {
                            family: candidate.family,
                            starting_cash: forwardCash,
                            operating_daily_usd: daily.trim() || null,
                          },
                        );
                      } catch (e) {
                        setError(String(e));
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Freeze {candidate.name} for exploratory paper
                  </button>
                </article>
              ))}
              <p>
                Exploratory accounts do not qualify or replace the primary.
                Their funding, losses, frozen parameters and existing cash-only
                checks remain separate.
              </p>
            </>
          )}
          <details>
            <summary>Frozen fingerprints and attempt history</summary>
            <p>Plan: {detail.plan_sha256}</p>
            <p>Evaluator: {detail.code_sha256}</p>
            <p>Inputs: {detail.snapshot_sha256 ?? "Unavailable"}</p>
            {detail.events.map((event, i) => (
              <p key={i}>
                {stamp(event.at)} · {event.kind.replaceAll("_", " ")} ·{" "}
                {event.body}
              </p>
            ))}
          </details>
          <a
            href={`/api/lab/experiments/${encodeURIComponent(detail.request_id)}`}
            download={`experiment-${detail.request_id}.json`}
          >
            Export retained receipt
          </a>
          <button
            type="button"
            disabled={
              busy ||
              !["acquiring", "queued", "running"].includes(detail.status)
            }
            onClick={() =>
              void post(
                `/api/lab/experiments/${encodeURIComponent(detail.request_id)}/cancel`,
              ).catch((e) => setError(String(e)))
            }
          >
            Cancel remaining work
          </button>
        </article>
      )}
      {Object.entries(paper?.accounts ?? {})
        .filter(([, a]) =>
          ["forward-research", "forward-control"].includes(a.campaign_id ?? ""),
        )
        .map(([accountId, a]) => (
          <article className="lab-result" key={accountId}>
            <h3>{a.label ?? accountId}</h3>
            <p>
              Equity ${a.equity}; funding ${a.funding}; fees ${a.fees}; retained
              net ${a.net_pnl}.
            </p>
            <p>
              {a.risk?.reason ?? "Waiting for eligible frozen signals"}.{" "}
              {a.fault?.reason}
            </p>
            <button
              type="button"
              disabled={!paper?.running || paper.stale || busy}
              onClick={() =>
                void post(`/api/paper/accounts/${accountId}/control`, {
                  action: a.entries_paused ? "resume" : "pause",
                  expected_version: a.control_version ?? 0,
                }).catch((e) => setError(String(e)))
              }
            >
              {a.entries_paused ? "Resume " : "Pause "}
              {a.campaign_id === "forward-control"
                ? "matched control entries"
                : "exploratory entries"}
            </button>
            {a.fault && (
              <button
                type="button"
                onClick={() =>
                  void post(`/api/paper/accounts/${accountId}/control`, {
                    action: "recover",
                    expected_version: a.control_version ?? 0,
                  }).catch((e) => setError(String(e)))
                }
              >
                Recover exploratory processing
              </button>
            )}
            <PaperCampaignJournal account={accountId} />
          </article>
        ))}
    </section>
  );
}
