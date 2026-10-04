import { useEffect, useState } from "react";

type ObjectValue = Record<string, any>;
const skills = [
  "useful_proposal",
  "justified_wait",
  "cost_interpretation",
  "negative_inconclusive",
  "strategy_refinement",
  "followup",
  "chronology",
  "authority",
  "comparison",
];
const headers = { "X-Local-Operator": "1", "Content-Type": "application/json" };
async function api(path: string, body?: unknown) {
  const r = await fetch(`/api/lab/training${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers,
    cache: "no-store",
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(190000),
  });
  const value = await r.json();
  if (!r.ok)
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : "Request refused; original records remain retained.",
    );
  return value;
}
const when = (n: unknown) =>
  typeof n === "number"
    ? new Date(n * 1000).toLocaleString()
    : "Unknown; requires review";
function Original({ value }: { value: unknown }) {
  return (
    <pre className="training-original">{JSON.stringify(value, null, 2)}</pre>
  );
}

function Evaluation({ value }: { value: ObjectValue }) {
  const arms = Object.entries(value.semantic || {}) as [string, ObjectValue][];
  const components = [
    ["appropriate_action", "Adjudicated appropriate action"],
    ["evidence_grounded", "Evidence support"],
    ["native_contract_valid", "Native output contract"],
    ["authority_respected", "Financial authority respected"],
  ];
  return (
    <>
      <p>
        {value.evidence_label}. Mechanical matches do not establish semantic
        correctness.
      </p>
      <div className="training-comparison-table">
        <table>
          <caption>
            Separate coverage, adjudicated quality and grouped contrast measures
          </caption>
          <thead>
            <tr>
              <th>Measure</th>
              {arms.map(([arm]) => (
                <th key={arm}>{arm}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>Requested</th>
              {arms.map(([arm, s]) => (
                <td key={arm}>{s.requested}</td>
              ))}
            </tr>
            <tr>
              <th>Admitted</th>
              {arms.map(([arm]) => (
                <td key={arm}>{value.admitted || "Unavailable"}</td>
              ))}
            </tr>
            <tr>
              <th>Completed</th>
              {arms.map(([arm, s]) => (
                <td key={arm}>
                  {s.components?.completed ?? "Unavailable"}/{s.requested}
                </td>
              ))}
            </tr>
            <tr>
              <th>Fully usable</th>
              {arms.map(([arm, s]) => (
                <td key={arm}>
                  {s.usable}/{s.requested}
                </td>
              ))}
            </tr>
            {components.map(([key, label]) => (
              <tr key={key}>
                <th>{label}</th>
                {arms.map(([arm, s]) => (
                  <td key={arm}>
                    {s.components?.[key] ?? "Unavailable"}/
                    {s.components_assessed?.[key] ?? "Unavailable"}
                  </td>
                ))}
              </tr>
            ))}
            <tr>
              <th>Both contrast answers usable</th>
              {arms.map(([arm, s]) => (
                <td key={arm}>
                  {s.complete_contrast_families}/{s.contrast_families} families
                </td>
              ))}
            </tr>
            <tr>
              <th>Mechanical action matches</th>
              {arms.map(([arm, s]) => (
                <td key={arm}>
                  {s.action_match ?? "Unavailable"}/{s.requested}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        Authority failures remain separate and prevent activation.
        Capability/dependency choice and comparison quality:{" "}
        {value.capability_and_comparison_dimensions}.
      </p>
      <p>
        Paired corrections:{" "}
        {value.paired_changes?.adapter_corrected ?? "Unavailable"}; regressions:{" "}
        {value.paired_changes?.adapter_regressed ?? "Unavailable"}. These are
        grouped historical cases, not trading performance or a fresh evaluation.
      </p>
      <details>
        <summary>
          Frozen adjudications, original flags, disagreements and corrections
        </summary>
        <Original value={value} />
      </details>
    </>
  );
}

export function TrainingResult({ result }: { result: ObjectValue }) {
  const receipt = result.receipt;
  return (
    <section aria-label="Linked Lab result">
      <h3>Lab result: {result.stage}</h3>
      <p>
        Study {result.id}. Preparation, training and evaluation are separate
        stages. This link cannot activate a model.
      </p>
      {result.archive_available === false && (
        <p role="alert">
          Private archive unavailable: {result.archive_reason}. The retained
          receipt is shown, but cannot be reverified.
        </p>
      )}
      {result.reason && <p role="alert">{result.reason}</p>}
      {receipt && (
        <>
          <dl>
            <dt>Model/profile</dt>
            <dd>
              {receipt.model_name || "Qwen3.5-4B"} · {receipt.profile_sha256}
            </dd>
            <dt>Dataset</dt>
            <dd>{receipt.dataset_sha256}</dd>
            <dt>Run</dt>
            <dd>{receipt.run_id}</dd>
            <dt>Stages</dt>
            <dd>
              Prepared: yes · Trained: {receipt.trained ? "yes" : "no"} ·
              Evaluated: {receipt.evaluated ? "yes" : "no"}
            </dd>
          </dl>
          {receipt.masking && (
            <>
              <h4>Actual tokenizer and effective labels</h4>
              <Original value={receipt.masking} />
            </>
          )}
          {receipt.comparison && (
            <>
              <h4>Evaluation evidence</h4>
              <Evaluation value={receipt.comparison} />
            </>
          )}
          <h4>Exact source examples</h4>
          <ul>
            {receipt.source_examples.map((id: string) => (
              <li key={id}>
                {result.historical ? (
                  id
                ) : (
                  <a
                    href={`#teaching:${id}${receipt.source_reviews?.[id] ? `@${receipt.source_reviews[id].revision}` : ""}`}
                  >
                    {id}
                    {receipt.source_reviews?.[id] &&
                      ` · review ${receipt.source_reviews[id].revision}`}
                  </a>
                )}
              </li>
            ))}
          </ul>
          <ul>
            {receipt.limitations.map((text: string, i: number) => (
              <li key={i}>{text}</li>
            ))}
          </ul>
        </>
      )}
      <details>
        <summary>Retained attempt history</summary>
        <Original value={result.attempts} />
      </details>
    </section>
  );
}

export function TrainingDataPanel() {
  const [list, setList] = useState<ObjectValue | null>(null);
  const [detail, setDetail] = useState<ObjectValue | null>(null);
  const [draft, setDraft] = useState<ObjectValue | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<ObjectValue | null>(null);
  const [check, setCheck] = useState<ObjectValue | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState(
    "What does this retained result support, and what evidence should the next experiment obtain?",
  );
  const [author, setAuthor] = useState("");
  const [role, setRole] = useState("researcher");
  const [trainEnd, setTrainEnd] = useState(
    new Date(Date.now() + 60000).toISOString().slice(0, 16),
  );
  const [validationEnd, setValidationEnd] = useState(
    new Date(Date.now() + 3660000).toISOString().slice(0, 16),
  );
  const [preparationOnly, setPreparationOnly] = useState(true);
  const [retirementStudy, setRetirementStudy] = useState(""),
    [retirementReason, setRetirementReason] = useState("");
  const refresh = async () => setList(await api(""));
  const open = async (link: string) => {
    const [id, revision] = link.split("@");
    if (revision && !/^[1-9][0-9]*$/.test(revision))
      throw new Error("Invalid saved review revision");
    const d = await api(
      `/examples/${encodeURIComponent(id)}${revision ? `?revision=${revision}` : ""}`,
    );
    setDetail(d);
    setResult(null);
    const reviewer = d.candidate.role === "reviewer";
    const target =
      d.candidate.original_answer &&
      typeof d.candidate.original_answer === "object"
        ? d.candidate.original_answer
        : reviewer
          ? {
              action: "inconclusive",
              evidence_ids: [],
              issues: [],
              rationale: "",
            }
          : {
              action: "no_change",
              evidence_ids: [],
              capability: null,
              mechanism: "",
              falsification: "",
              rationale: "",
              dependency: null,
            };
    setDraft(
      d.saved
        ? { ...d.saved, revision: d.revision }
        : {
            revision: d.revision,
            disposition: "draft",
            reason: "",
            lesson: "",
            rights_reason: "",
            review: d.review_template,
            target,
          },
    );
    localStorage.setItem("training-example", link);
    window.location.hash = `teaching:${link}`;
  };
  const work = async (f: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await f();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Request failed. Retry the retained record.",
      );
    } finally {
      setBusy(false);
    }
  };
  const openReceipt = async (id: string, historical: boolean) => {
    setResult(
      await api(
        `/${historical ? "historical" : "results"}/${encodeURIComponent(id)}`,
      ),
    );
    setDetail(null);
  };
  const receiptRoute = (id: string, historical: boolean) => {
    const hash = `#${historical ? "lab-comparison" : "lab-result"}:${id}`;
    if (window.location.hash === hash)
      void work(async () => openReceipt(id, historical));
    else window.location.hash = hash;
  };
  const navigate = async (restore = false) => {
    const hash = window.location.hash;
    if (hash.startsWith("#lab-result:"))
      await openReceipt(hash.slice(12), false);
    else if (hash.startsWith("#lab-comparison:"))
      await openReceipt(hash.slice(16), true);
    else if (hash.startsWith("#teaching:")) await open(hash.slice(10));
    else if (restore) {
      const id = localStorage.getItem("training-example");
      if (id) await open(id);
    }
  };
  useEffect(() => {
    void work(async () => {
      await refresh();
      await navigate(true);
    });
    const changed = () => void work(async () => navigate());
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  const edit = (key: string, value: unknown) =>
    setDraft((d) => d && { ...d, [key]: value });
  const review = (key: string, value: unknown) =>
    setDraft((d) => d && { ...d, review: { ...d.review, [key]: value } });
  const target = (key: string, value: unknown) =>
    setDraft((d) => d && { ...d, target: { ...d.target, [key]: value } });
  const selection = () => ({
    ids: selected,
    train_end: Date.parse(trainEnd + "Z") / 1000,
    validation_end: Date.parse(validationEnd + "Z") / 1000,
    embargo_seconds: 2700,
    preparation_only: preparationOnly,
  });
  const pick = async (source: ObjectValue) => {
    const d = await api("/candidates", source);
    await refresh();
    await open(d.id);
  };
  return (
    <section className="training-panel" aria-label="Training data review">
      <h2>Review experience for the Training Lab</h2>
      <p>
        Inspect original evidence, decide what it should teach, then prepare
        reviewed examples privately. Preparation does not train or qualify a
        model.
      </p>
      <button disabled={busy} onClick={() => void work(refresh)}>
        Refresh retained records
      </button>
      {busy && <p role="status">Working through the bounded local request…</p>}
      {error && (
        <p role="alert">
          {error}{" "}
          <button disabled={busy} onClick={() => void work(refresh)}>
            Retry refresh
          </button>
        </p>
      )}
      <details open={!detail}>
        <summary>Select original experience</summary>
        <h3>Observed numerical episodes</h3>
        <p>
          These observations did not have an LLM question or answer. Author a
          new question for a later interpretation; the original observation
          times remain unchanged. No original execution or fill claim is
          admitted through this route.
        </p>
        <label>
          New question
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </label>
        <label>
          Question author
          <input value={author} onChange={(e) => setAuthor(e.target.value)} />
        </label>
        <label>
          Teaching role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="researcher">Researcher</option>
            <option value="reviewer">Reviewer</option>
          </select>
        </label>
        <h4>Retained public market observations</h4>
        <ul>
          {list?.observations.map((e: ObjectValue) => (
            <li key={e.id}>
              {e.symbol} · original local receipt {e.observed_at}{" "}
              <button
                disabled={busy || author.trim().length < 3}
                onClick={() =>
                  void work(async () =>
                    pick({
                      kind: "market_observation",
                      identity: String(e.id),
                      question,
                      author,
                      role,
                    }),
                  )
                }
              >
                Review observed market evidence
              </button>
            </li>
          ))}
        </ul>
        <h4>Numerical results</h4>
        <ul>
          {list?.episodes.map((e: ObjectValue) => (
            <li key={e.id}>
              <strong>{e.name || e.id}</strong> · {e.status} · {e.basis} ·
              available {when(e.finished)}{" "}
              <button
                disabled={busy || author.trim().length < 3}
                onClick={() =>
                  void work(async () =>
                    pick({
                      kind: "observed_episode",
                      identity: e.id,
                      question,
                      author,
                      role,
                    }),
                  )
                }
              >
                Review this episode
              </button>
            </li>
          ))}
        </ul>
        {!list?.episodes.length && (
          <p>
            No retained terminal episode is available in this application state.
          </p>
        )}
        <h3>Retained model attempts</h3>
        <ul>
          {list?.attempts.map((a: ObjectValue) => (
            <li key={`${a.id}:${a.stage}:${a.attempt}`}>
              {a.id} · {a.stage} #{a.attempt} · {when(a.finished)}{" "}
              <button
                disabled={busy}
                onClick={() =>
                  void work(async () =>
                    pick({
                      kind: "model_attempt",
                      identity: a.id,
                      stage: a.stage,
                      attempt: a.attempt,
                    }),
                  )
                }
              >
                Review original attempt
              </button>
            </li>
          ))}
        </ul>
      </details>
      <h3>Saved teaching reviews</h3>
      <ul>
        {list?.examples.map((e: ObjectValue) => (
          <li key={e.id}>
            <label>
              <input
                type="checkbox"
                aria-label={`Select for dataset ${e.id}`}
                checked={selected.includes(e.id)}
                onChange={(event) => {
                  setSelected((ids) =>
                    event.target.checked
                      ? [...ids, e.id]
                      : ids.filter((id) => id !== e.id),
                  );
                  setCheck(null);
                }}
              />
              Select for dataset
            </label>{" "}
            <button
              disabled={busy}
              onClick={() => void work(async () => open(e.id))}
            >
              {e.lesson}
            </button>{" "}
            · {e.disposition} · revision {e.revision || 0}
          </li>
        ))}
      </ul>
      {detail && draft && (
        <section aria-label="Teaching review">
          <h3>Original evidence and review</h3>
          <dl>
            <dt>Source</dt>
            <dd>
              {detail.candidate.source_kind || "model_attempt"} ·{" "}
              {detail.candidate.task_id}
            </dd>
            <dt>Observation interval</dt>
            <dd>
              {detail.candidate.observed_source
                ? `${when(detail.candidate.observed_source.observed_start)} — ${when(detail.candidate.observed_source.observed_end)}`
                : "Declared during review; inspect the evidence"}
            </dd>
            <dt>Fact availability</dt>
            <dd>
              {when(detail.candidate.observed_source?.available_at)} ·
              authored/decision {when(detail.candidate.decision_at)}
            </dd>
          </dl>
          <h4>
            Question{" "}
            {detail.candidate.observed_source
              ? "authored later"
              : "originally supplied"}
          </h4>
          <p>{detail.candidate.packet.question}</p>
          <details open>
            <summary>Original evidence and offered capabilities</summary>
            <Original value={detail.candidate.packet} />
          </details>
          {detail.candidate.observed_source?.original_record && (
            <details>
              <summary>Unchanged original retained record</summary>
              <Original
                value={detail.candidate.observed_source.original_record}
              />
              <p>
                The market teaching prompt uses local receipt/identity metadata;
                raw exchange prices/depth remain in this provenance record and
                are excluded from the training prompt.
              </p>
            </details>
          )}
          <details>
            <summary>Unchanged original model answer</summary>
            {detail.candidate.original_answer === null ? (
              <p>
                No original LLM answer exists. The target below is newly
                authored.
              </p>
            ) : (
              <Original value={detail.candidate.original_answer} />
            )}
          </details>
          <p>
            Unknowns: candle/quote observations do not establish fills.
            Model-attempt timing bounds prefilled from the decision require
            source review. Rights and reviewer identity are never inferred.
          </p>
          {detail.historical_revision && (
            <p role="status">
              Read-only saved review {detail.revision}. The latest review is{" "}
              {detail.current_revision}.
              <button
                disabled={busy}
                onClick={() => void work(async () => open(detail.id))}
              >
                Open latest review
              </button>
            </p>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void work(async () => {
                const saved = await api(`/examples/${detail.id}/review`, {
                  revision: detail.revision,
                  review: draft.review,
                  target: draft.target,
                  reason: draft.reason,
                  lesson: draft.lesson,
                  disposition: draft.disposition,
                  rights_reason: draft.rights_reason,
                });
                await refresh();
                setCheck(null);
                setDetail(saved);
                setDraft({ ...saved.saved, revision: saved.revision });
              });
            }}
          >
            <fieldset disabled={busy || detail.historical_revision}>
              <legend>Teaching target and review</legend>
              <label>
                Disposition
                <select
                  aria-label="Disposition"
                  value={draft.disposition}
                  onChange={(e) => edit("disposition", e.target.value)}
                >
                  <option value="draft">Draft — not approved</option>
                  <option value="accept">Accept target</option>
                  <option value="correct">Accept corrected target</option>
                  <option value="pending">Pending specific evidence</option>
                  <option value="exclude">Exclude</option>
                </select>
              </label>
              <label>
                Intended lesson
                <textarea
                  aria-label="Intended lesson"
                  value={draft.lesson}
                  onChange={(e) => edit("lesson", e.target.value)}
                  required
                  minLength={12}
                />
              </label>
              <label>
                Review decision / specific pending or exclusion reason
                <textarea
                  aria-label="Review decision / specific pending or exclusion reason"
                  value={draft.reason}
                  onChange={(e) => edit("reason", e.target.value)}
                  required
                  minLength={20}
                />
              </label>
              <div className="training-fields">
                <label>
                  Reviewer type
                  <select
                    aria-label="Reviewer type"
                    value={draft.review.reviewer_kind || ""}
                    onChange={(e) =>
                      review("reviewer_kind", e.target.value || null)
                    }
                  >
                    <option value="">Choose explicitly</option>
                    <option value="human">Human</option>
                    <option value="delegated_semantic">
                      Authorized model-assisted semantic review
                    </option>
                  </select>
                </label>
                <label>
                  Reviewer identity
                  <input
                    value={draft.review.reviewer || ""}
                    onChange={(e) => review("reviewer", e.target.value)}
                  />
                </label>
                <label>
                  Reviewer also authored this material?
                  <select
                    aria-label="Reviewer also authored this material?"
                    value={
                      draft.review.reviewer_authored_material === null
                        ? ""
                        : String(draft.review.reviewer_authored_material)
                    }
                    onChange={(e) =>
                      review(
                        "reviewer_authored_material",
                        e.target.value === ""
                          ? null
                          : e.target.value === "true",
                      )
                    }
                  >
                    <option value="">Choose explicitly</option>
                    <option value="true">Yes</option>
                    <option value="false">No</option>
                  </select>
                </label>
                <label>
                  Evidence basis
                  <select
                    aria-label="Evidence basis"
                    value={draft.review.data_basis}
                    onChange={(e) => review("data_basis", e.target.value)}
                  >
                    {[
                      "instructional",
                      "synthetic",
                      "observed",
                      "historical_replay",
                      "prospective",
                    ].map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Claim scope
                  <select
                    aria-label="Claim scope"
                    value={draft.review.claim_scope}
                    onChange={(e) => review("claim_scope", e.target.value)}
                  >
                    {[
                      "interpretation",
                      "price_path",
                      "original_execution",
                      "counterfactual",
                    ].map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </label>
              </div>
              <label>
                Applicable usage permission and remaining restrictions
                <textarea
                  aria-label="Applicable usage permission and remaining restrictions"
                  value={draft.rights_reason}
                  onChange={(e) => edit("rights_reason", e.target.value)}
                />
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={draft.review.rights_confirmed}
                  onChange={(e) => review("rights_confirmed", e.target.checked)}
                />
                I reviewed the applicable rights for this private training use
              </label>
              <fieldset>
                <legend>Lesson skills</legend>
                {skills.map((skill) => (
                  <label key={skill}>
                    <input
                      type="checkbox"
                      checked={draft.review.categories.includes(skill)}
                      onChange={(e) =>
                        review(
                          "categories",
                          e.target.checked
                            ? [...draft.review.categories, skill]
                            : draft.review.categories.filter(
                                (v: string) => v !== skill,
                              ),
                        )
                      }
                    />
                    {skill.replaceAll("_", " ")}
                  </label>
                ))}
              </fieldset>
              <label>
                Related family identifiers (original source groups remain
                protected)
                <input
                  value={draft.review.family_ids.join(", ")}
                  onChange={(e) =>
                    review(
                      "family_ids",
                      e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    )
                  }
                />
              </label>
              <details>
                <summary>Source availability and causal window</summary>
                {["episode_start", "episode_end", "target_available_at"].map(
                  (field) => (
                    <label key={field}>
                      {field.replaceAll("_", " ")}
                      <input
                        type="number"
                        step="any"
                        value={draft.review[field]}
                        onChange={(e) => review(field, Number(e.target.value))}
                      />
                    </label>
                  ),
                )}
                {Object.keys(detail.candidate.packet.evidence).map((id) => (
                  <label key={id}>
                    {id} available at
                    <input
                      type="number"
                      step="any"
                      value={draft.review.evidence_available_at[id]}
                      onChange={(e) =>
                        review("evidence_available_at", {
                          ...draft.review.evidence_available_at,
                          [id]: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                ))}
              </details>
              <fieldset>
                <legend>Reviewed structured teaching target</legend>
                <button
                  type="button"
                  onClick={() =>
                    edit(
                      "target",
                      detail.candidate.role === "reviewer"
                        ? {
                            action: "inconclusive",
                            evidence_ids: [],
                            issues: [],
                            rationale: "",
                          }
                        : {
                            action: "no_change",
                            evidence_ids: [],
                            capability: null,
                            mechanism: "",
                            falsification: "",
                            rationale: "",
                            dependency: null,
                          },
                    )
                  }
                >
                  Start a fresh teaching target
                </button>
                <p>
                  This edits the teaching draft. The unchanged original answer
                  remains above.
                </p>
                <label>
                  Action
                  <select
                    aria-label="Target action"
                    value={draft.target?.action || ""}
                    onChange={(e) => target("action", e.target.value)}
                  >
                    {(detail.candidate.role === "reviewer"
                      ? ["reject", "inconclusive", "exploratory_paper_only"]
                      : [
                          "propose_experiment",
                          "request_data",
                          "no_change",
                          "unsupported_capability",
                        ]
                    ).map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </label>
                <div>
                  Supplied evidence references
                  {Object.keys(detail.candidate.packet.evidence).map((id) => (
                    <label key={id}>
                      <input
                        type="checkbox"
                        checked={(draft.target?.evidence_ids || []).includes(
                          id,
                        )}
                        onChange={(e) =>
                          target(
                            "evidence_ids",
                            e.target.checked
                              ? [...(draft.target?.evidence_ids || []), id]
                              : draft.target?.evidence_ids.filter(
                                  (v: string) => v !== id,
                                ),
                          )
                        }
                      />
                      {id}
                    </label>
                  ))}
                </div>
                {detail.candidate.role === "researcher" ? (
                  <>
                    <label>
                      Offered capability
                      <select
                        aria-label="Offered capability"
                        value={draft.target?.capability || ""}
                        onChange={(e) =>
                          target("capability", e.target.value || null)
                        }
                      >
                        <option value="">None</option>
                        {Object.keys(detail.candidate.packet.capabilities).map(
                          (id) => (
                            <option key={id}>{id}</option>
                          ),
                        )}
                      </select>
                    </label>
                    {[
                      "mechanism",
                      "falsification",
                      "dependency",
                      "rationale",
                    ].map((field) => (
                      <label key={field}>
                        {field}
                        <textarea
                          aria-label={field}
                          value={draft.target?.[field] || ""}
                          onChange={(e) =>
                            target(
                              field,
                              e.target.value ||
                                (field === "dependency" ? null : ""),
                            )
                          }
                        />
                      </label>
                    ))}
                  </>
                ) : (
                  <>
                    <label>
                      Detected method issues
                      <input
                        value={(draft.target?.issues || []).join(", ")}
                        onChange={(e) =>
                          target(
                            "issues",
                            e.target.value
                              .split(",")
                              .map((s) => s.trim())
                              .filter(Boolean),
                          )
                        }
                      />
                    </label>
                    <label>
                      Rationale
                      <textarea
                        aria-label="Rationale"
                        value={draft.target?.rationale || ""}
                        onChange={(e) => target("rationale", e.target.value)}
                      />
                    </label>
                  </>
                )}
              </fieldset>
              <button disabled={busy} type="submit">
                Save {draft.disposition} review
              </button>
              <button
                disabled={busy}
                type="button"
                onClick={() => void work(async () => open(detail.id))}
              >
                Reopen saved revision
              </button>
            </fieldset>
          </form>
          <details>
            <summary>Saved review history</summary>
            <ul>
              {detail.history.map((r: ObjectValue) => (
                <li key={r.revision}>
                  <a href={`#teaching:${detail.id}@${r.revision}`}>
                    Review {r.revision} · {r.disposition} · {when(r.saved)}
                  </a>
                </li>
              ))}
            </ul>
            <Original value={detail.history} />
          </details>
        </section>
      )}
      <section aria-label="Dataset preparation">
        <h3>Preflight and prepare selected examples</h3>
        <p>
          {selected.length} selected. Every row must pass review and protection
          checks; no partial admission.
        </p>
        <label>
          <input
            type="checkbox"
            checked={preparationOnly}
            onChange={(e) => {
              setPreparationOnly(e.target.checked);
              setCheck(null);
            }}
          />
          Preparation-only training handoff; independent validation and test
          remain unprovided
        </label>
        <label>
          Train cutoff (UTC)
          <input
            type="datetime-local"
            value={trainEnd}
            onChange={(e) => {
              setTrainEnd(e.target.value);
              setCheck(null);
            }}
          />
        </label>
        <label>
          Validation cutoff (UTC)
          <input
            type="datetime-local"
            value={validationEnd}
            onChange={(e) => {
              setValidationEnd(e.target.value);
              setCheck(null);
            }}
          />
        </label>
        <p>
          {list?.configuration.available
            ? `Configured existing Lab: ${list.configuration.model}`
            : `Lab unavailable: ${list?.configuration.reason || "loading configuration"}`}
        </p>
        <button
          disabled={busy || !selected.length}
          onClick={() =>
            void work(async () =>
              setCheck(await api("/preflight", selection())),
            )
          }
        >
          Run read-only preflight
        </button>
        {check && (
          <>
            <p role="status">
              {check.eligible
                ? "All selected rows passed preflight."
                : "Build blocked; review every listed problem."}
            </p>
            <ul>
              {check.problems.map((p: ObjectValue, i: number) => (
                <li key={i}>
                  {p.id || "Dataset"}: {p.code} — {p.reason}
                </li>
              ))}
            </ul>
            <Original value={check.coverage} />
            <Original value={check.exposure?.limitations || []} />
          </>
        )}
        <button
          disabled={busy || !check?.eligible}
          onClick={() =>
            void work(async () => {
              const r = await api("/prepare", selection());
              if (r.stage === "refused") setCheck(r.preflight);
              else {
                setResult(r);
                window.location.hash = `lab-result:${r.id}`;
              }
              await refresh();
            })
          }
        >
          Build reviewed corpus and prepare in Lab
        </button>
      </section>
      <h3>Linked preparation and evaluation receipts</h3>
      <ul>
        {list?.handoffs.map((r: ObjectValue) => (
          <li key={r.id}>
            <button disabled={busy} onClick={() => receiptRoute(r.id, false)}>
              {r.id} · {r.stage}
            </button>
          </li>
        ))}
      </ul>
      <ul>
        {list?.configuration.comparisons?.map((link: ObjectValue) => (
          <li key={link.id}>
            <button disabled={busy} onClick={() => receiptRoute(link.id, true)}>
              {link.label} · original dataset
            </button>
          </li>
        ))}
      </ul>
      {result && (
        <>
          <TrainingResult result={result} />
          {["failed", "preparing"].includes(result.stage) && (
            <button
              disabled={busy}
              onClick={() =>
                void work(async () => {
                  setResult(await api(`/results/${result.id}/retry`, {}));
                  await refresh();
                })
              }
            >
              Retry incomplete preparation
            </button>
          )}
        </>
      )}
      <details>
        <summary>Retire a consumed evaluation population</summary>
        <p>
          This explicitly loses its freshness for future evaluation and retains
          its original study. Sealed material cannot be retired here.
        </p>
        <label>
          Study
          <select
            value={retirementStudy}
            onChange={(e) => setRetirementStudy(e.target.value)}
          >
            <option value="">Choose a consumed study</option>
            {list?.configuration.studies
              ?.filter((s: ObjectValue) => !s.sealed)
              .map((s: ObjectValue) => (
                <option key={s.id}>{s.id}</option>
              ))}
          </select>
        </label>
        <label>
          Retirement reason
          <textarea
            value={retirementReason}
            onChange={(e) => setRetirementReason(e.target.value)}
          />
        </label>
        <label>
          Operator identity
          <input value={author} onChange={(e) => setAuthor(e.target.value)} />
        </label>
        <button
          disabled={
            busy ||
            !retirementStudy ||
            author.length < 3 ||
            retirementReason.length < 20
          }
          onClick={() =>
            void work(async () => {
              await api("/retire-evaluation", {
                study: retirementStudy,
                reviewer: author,
                reason: retirementReason,
              });
              await refresh();
            })
          }
        >
          Record retirement into training/regression use
        </button>
      </details>
    </section>
  );
}
