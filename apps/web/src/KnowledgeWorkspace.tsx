import { useEffect, useRef, useState } from "react";
import "./knowledge-workspace.css";

type Meta = {
  title: string;
  author: string;
  origin: string;
  rights: string;
  category: string;
  symbol: string | null;
  horizon: string | null;
  format: string;
  published_at: number | null;
  external_allowed: boolean;
  training_allowed: boolean;
  generated: boolean;
};
type Source = {
  source: string;
  revision: number;
  received_at: number;
  metadata: Meta;
  disposition: { seq: number; state: string; reason: string };
  original?: string;
  text?: string;
};
type Passage = {
  citation: string;
  source: string;
  revision: number;
  title: string;
  text: string;
  status: string;
  received_at: number;
  score: number;
};
type Receipt = {
  id: string;
  mode: string;
  passages: Passage[];
  omitted_matches: number;
  absence: string | null;
  coverage: string;
  context_bytes: number;
};
type Review = {
  id: string;
  state: string;
  reason: string | null;
  task: string;
  updated: number;
  occurrence: string;
  cost_reserved: number;
  cost_actual: number | null;
};
type Policy = {
  model: string;
  reasoning: string;
  project: string;
  enabled: boolean;
  daily_hour: number;
  timezone: string;
  external_data_approved: boolean;
  spending_approved: boolean;
  schedule_owner_approved: boolean;
  supported_profile_verified: boolean;
  daily_requests: number;
  token_reserve: number;
  request_cost_ceiling_usd: number;
  daily_cost_ceiling_usd: number;
  monthly_cost_ceiling_usd: number;
  input_usd_per_million: number;
  output_usd_per_million: number;
  price_source: string;
};
type Status = {
  revision: number;
  policy: Policy | null;
  reviews: Review[];
  next_before: string | null;
  last_completed_at: number | null;
  next_due: number | null;
  blocked_reasons: string[];
  next_action: string;
  background: string;
  transport: string;
  availability: string;
  existing_chatgpt_task: string;
};
type Finding = {
  kind: string;
  claim: string;
  evidence_ids: string[];
  contrary_ids: string[];
  uncertainty: string;
  proposed_question: string | null;
};
type Detail = Review & {
  packet_sha: string;
  packet: { cutoff: number; question: string; knowledge: Receipt };
  delivered_knowledge?: Passage[];
  response: unknown;
  provider_turns: unknown[];
  result: {
    summary: string;
    findings: Finding[];
    coverage: string;
    next_action: string;
    authorship: string;
  } | null;
  decisions: {
    revision: number;
    body: { disposition: string; reason: string };
  }[];
  policy: Policy;
  usage: Record<string, number> | null;
  followups: {
    id: string;
    question: string;
    state: string;
    task: string | null;
    reason: string | null;
  }[];
  correction: { source: string; state: string; reason: string | null }[];
};
type Backup = { backup: string; sha256: string | null; bytes: number };
type Restored = { library: string; sources: Source[]; active_library: string };

const date = (v?: number | null) =>
  v ? new Date(v * 1000).toLocaleString() : "No completed activity";
const initialPolicy: Policy = {
  model: "",
  reasoning: "medium",
  project: "",
  enabled: false,
  daily_hour: 8,
  timezone: "America/Denver",
  daily_requests: 1,
  token_reserve: 32768,
  request_cost_ceiling_usd: 0.5,
  daily_cost_ceiling_usd: 0.5,
  monthly_cost_ceiling_usd: 5,
  input_usd_per_million: 0,
  output_usd_per_million: 0,
  price_source: "",
  external_data_approved: false,
  spending_approved: false,
  schedule_owner_approved: false,
  supported_profile_verified: false,
};
async function request<T>(
  url: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(url, {
    method: body === undefined ? "GET" : "POST",
    headers:
      body === undefined
        ? {}
        : { "Content-Type": "application/json", "X-Local-Operator": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
    signal: signal ?? AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    const value = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : "Request refused; retained work remains available.",
    );
  }
  return (await response.json()) as T;
}
function linked() {
  const [route, query] = location.hash.slice(1).split("?");
  return {
    tab:
      route === "research-reviews"
        ? "reviews"
        : route === "reviewer-connection"
          ? "connection"
          : "library",
    params: new URLSearchParams(query),
  };
}

export function KnowledgeWorkspace() {
  const [tab, setTab] = useState(linked().tab);
  const [sources, setSources] = useState<Source[]>([]);
  const [more, setMore] = useState<string | null>(null);
  const [cursor, setCursor] = useState("");
  const [reviewCursor, setReviewCursor] = useState("");
  const [libraryCondition, setLibraryCondition] = useState("");
  const [connectionTest, setConnectionTest] = useState<{
    scope: string;
    provider: string;
    credential: string;
  } | null>(null);
  const [selected, setSelected] = useState<string | null>(
    linked().params.get("source"),
  );
  const [revision, setRevision] = useState(
    Number(linked().params.get("revision")) || 1,
  );
  const [source, setSource] = useState<Source | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [review, setReview] = useState<Detail | null>(null);
  const [reviewId, setReviewId] = useState<string | null>(
    linked().params.get("review"),
  );
  const [query, setQuery] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [policy, setPolicy] = useState<Policy>(initialPolicy);
  const credential = useRef<HTMLInputElement>(null);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [restored, setRestored] = useState<Restored | null>(null);
  const [restoredSource, setRestoredSource] = useState<Source | null>(null);
  const [searchMatch, setSearchMatch] = useState("terms");
  const [pdf, setPdf] = useState<string | null>(null);
  const [firstPage, setFirstPage] = useState(1);
  const [lastPage, setLastPage] = useState(1);
  const [sourceUrl, setSourceUrl] = useState("");
  const [urlApproved, setUrlApproved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [decision, setDecision] = useState("pending");
  const [reason, setReason] = useState("");
  const [draft, setDraft] = useState({
    source_id: "",
    title: "",
    author: "",
    origin: "",
    rights: "",
    category: "methods",
    symbol: "",
    horizon: "",
    published_at: "",
    text: "",
    format: "markdown",
    external_allowed: false,
    training_allowed: false,
    generated: false,
  });
  useEffect(() => {
    const change = () => {
      const value = linked();
      setTab(value.tab);
      setSelected(value.params.get("source"));
      setRevision(Number(value.params.get("revision")) || 1);
      setReviewId(value.params.get("review"));
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const [library, state] = await Promise.all([
          request<{
            sources: Source[];
            next_before: string | null;
            backups: Backup[];
            extraction: string;
            index_condition: string;
          }>(
            `/api/research/knowledge?before=${encodeURIComponent(cursor)}`,
            undefined,
            controller.signal,
          ),
          request<Status>(
            `/api/research/reviews?before=${encodeURIComponent(reviewCursor)}`,
            undefined,
            controller.signal,
          ),
        ]);
        if (controller.signal.aborted) return;
        setSources(library.sources);
        setMore(library.next_before);
        setBackups(library.backups);
        setLibraryCondition(
          library.extraction + ". " + library.index_condition,
        );
        setStatus(state);
        setError(null);
        timer = setTimeout(load, 30000);
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(e instanceof Error ? e.message : "Workspace disconnected");
          timer = setTimeout(load, 30000);
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [refresh, cursor, reviewCursor]);
  useEffect(() => {
    setSource(null);
    if (!selected) return;
    const controller = new AbortController();
    void request<Source>(
      `/api/research/knowledge/sources/${encodeURIComponent(selected)}/${revision}`,
      undefined,
      controller.signal,
    )
      .then((v) => {
        if (!controller.signal.aborted) setSource(v);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [selected, revision, refresh]);
  useEffect(() => {
    setReview(null);
    if (!reviewId) return;
    const controller = new AbortController();
    void request<Detail>(
      `/api/research/reviews/results/${encodeURIComponent(reviewId)}`,
      undefined,
      controller.signal,
    )
      .then((v) => {
        if (!controller.signal.aborted) setReview(v);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [reviewId, refresh]);
  const navigate = (target: string, params = "") => {
    location.hash = target + params;
  };
  const open = (s: string, r: number) =>
    navigate("knowledge", `?source=${encodeURIComponent(s)}&revision=${r}`);
  const action = async (work: () => Promise<unknown>, message: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await work();
      setNotice(message);
      setRefresh((v) => v + 1);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Action unconfirmed; inspect saved state before retry",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section
      className="panel knowledge-workspace"
      aria-labelledby="knowledge-title"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">PERSISTENT RESEARCH WORKSPACE</p>
          <h2 id="knowledge-title">Knowledge &amp; reviews</h2>
          <p>
            Keep original sources. Review the evidence. Carry useful corrections
            forward.
          </p>
        </div>
        <span className="badge">FTS5 · local memory</span>
      </div>
      <nav className="workspace-tabs" aria-label="Knowledge workspace views">
        {[
          ["library", "Library", "knowledge"],
          ["reviews", "Research reviews", "research-reviews"],
          ["connection", "Connections & schedule", "reviewer-connection"],
        ].map(([id, label, hash]) => (
          <button
            key={id}
            aria-pressed={tab === id}
            className={tab === id ? "selected" : ""}
            onClick={() => navigate(hash)}
          >
            {label}
          </button>
        ))}
      </nav>
      {error && (
        <p className="warning" role="alert">
          {error}{" "}
          <button onClick={() => setRefresh((v) => v + 1)}>Reconnect</button>
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {tab === "library" && (
        <>
          <p>
            {libraryCondition || "Connecting to the owned reference library…"}
          </p>
          <form
            className="knowledge-search"
            onSubmit={(e) => {
              e.preventDefault();
              void action(async () => {
                setReceipt(
                  await request<Receipt>("/api/research/knowledge/search", {
                    text: query,
                    cutoff: Date.now() / 1000,
                    match: searchMatch,
                  }),
                );
              }, "Retrieved exact eligible passages; citations remain inspectable.");
            }}
          >
            <label>
              Find evidence or theory
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                maxLength={300}
                required
                placeholder="Transaction costs, causality, exact source ID…"
              />
            </label>
            <label>
              Search mode
              <select
                value={searchMatch}
                onChange={(e) => setSearchMatch(e.target.value)}
              >
                <option value="terms">Relevant words</option>
                <option value="phrase">Exact phrase</option>
                <option value="exact_source">Exact source ID</option>
              </select>
            </label>
            <button disabled={busy}>Search library</button>
          </form>
          {receipt && (
            <section aria-label="Search results">
              <p>
                {receipt.mode} · {receipt.context_bytes.toLocaleString()}{" "}
                context bytes · {receipt.omitted_matches} omitted matches
              </p>
              <p>{receipt.absence ?? receipt.coverage}</p>
              {receipt.passages.map((p) => (
                <article className="knowledge-card" key={p.citation}>
                  <h3>
                    <button onClick={() => open(p.source, p.revision)}>
                      {p.title}
                    </button>
                  </h3>
                  <p>
                    {p.status} · received {date(p.received_at)} · version{" "}
                    {p.revision}
                  </p>
                  <p className="source-text">{p.text}</p>
                  <small>
                    Citation {p.citation} · relevance rank supports lookup, not
                    truth
                  </small>
                </article>
              ))}
            </section>
          )}
          <div className="knowledge-columns">
            <section aria-label="Source library">
              <h3>Source library</h3>
              {sources.length === 0 && (
                <p>
                  No sources on this page. Import a permitted section to begin.
                </p>
              )}
              {sources.map((s) => (
                <article className="knowledge-card" key={s.source}>
                  <button onClick={() => open(s.source, s.revision)}>
                    <strong>{s.metadata.title}</strong>
                  </button>
                  <p>
                    {s.metadata.category} · {s.metadata.symbol ?? "All markets"}{" "}
                    · {s.metadata.horizon ?? "All horizons"} ·{" "}
                    {s.disposition.state} · version {s.revision}
                  </p>
                  <p>
                    Received {date(s.received_at)}
                    <br />
                    Published{" "}
                    {s.metadata.published_at
                      ? date(s.metadata.published_at)
                      : "Unknown"}
                  </p>
                  <small>
                    {s.metadata.external_allowed
                      ? "Permitted for approved reviewer scope"
                      : "Local retrieval only"}
                  </small>
                </article>
              ))}
              <div className="toolbar">
                <button disabled={!cursor} onClick={() => setCursor("")}>
                  First page
                </button>
                <button disabled={!more} onClick={() => setCursor(more ?? "")}>
                  More sources
                </button>
              </div>
            </section>
            <section aria-label="Source detail">
              {source ? (
                <>
                  <h3>{source.metadata.title}</h3>
                  <p>
                    {source.metadata.author} · {source.metadata.origin}
                  </p>
                  <p>
                    Version {source.revision} · {source.disposition.state} ·
                    received {date(source.received_at)}
                  </p>
                  <p>{source.metadata.rights}</p>
                  <p>{source.disposition.reason}</p>
                  <pre className="source-text">
                    {source.original ?? source.text}
                  </pre>
                  {source.metadata.format === "pdf" && (
                    <a
                      href={`/api/research/knowledge/sources/${source.source}/${source.revision}/document`}
                    >
                      Download the exact original PDF
                    </a>
                  )}
                  <button
                    disabled={revision <= 1}
                    onClick={() => open(source.source, revision - 1)}
                  >
                    Previous original version
                  </button>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void action(
                        () =>
                          request(
                            `/api/research/knowledge/sources/${encodeURIComponent(source.source)}/disposition`,
                            {
                              revision: source.revision,
                              expected_state: source.disposition.seq,
                              state:
                                decision === "accept_annotation"
                                  ? "accepted"
                                  : decision === "reject"
                                    ? "excluded"
                                    : "disputed",
                              reason,
                            },
                          ),
                        "Disposition appended; original source and earlier contexts retained.",
                      );
                    }}
                  >
                    <label>
                      Source disposition
                      <select
                        value={decision}
                        onChange={(e) => setDecision(e.target.value)}
                      >
                        <option value="pending">Dispute / needs review</option>
                        <option value="accept_annotation">
                          Accept interpretation
                        </option>
                        <option value="reject">Exclude from retrieval</option>
                      </select>
                    </label>
                    <label>
                      Reason
                      <textarea
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        minLength={20}
                        maxLength={1200}
                        required
                      />
                    </label>
                    <button disabled={busy}>Save source disposition</button>
                  </form>
                  <button
                    onClick={() => {
                      const m = source.metadata;
                      setPdf(null);
                      setDraft({
                        source_id: source.source,
                        title: m.title,
                        author: m.author,
                        origin: m.origin,
                        rights: m.rights,
                        category: m.category,
                        symbol: m.symbol ?? "",
                        horizon: m.horizon ?? "",
                        published_at: m.published_at
                          ? new Date(m.published_at * 1000)
                              .toISOString()
                              .slice(0, 10)
                          : "",
                        external_allowed: m.external_allowed,
                        training_allowed: m.training_allowed,
                        generated: m.generated,
                        text: source.original ?? source.text ?? "",
                        format: m.format === "pdf" ? "markdown" : m.format,
                      });
                      document
                        .getElementById("knowledge-import")
                        ?.scrollIntoView();
                    }}
                  >
                    Prepare a corrected version
                  </button>
                </>
              ) : (
                <p>
                  Select a source to inspect its original content and history.
                </p>
              )}
            </section>
          </div>
          <details id="knowledge-import">
            <summary>Import a permitted source or append a correction</summary>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void action(async () => {
                  const body = {
                    ...draft,
                    symbol: draft.symbol || null,
                    horizon: draft.horizon || null,
                    published_at: draft.published_at
                      ? new Date(draft.published_at + "T00:00:00Z").getTime() /
                        1000
                      : null,
                    expected_revision:
                      source?.source === draft.source_id ? source.revision : 0,
                  };
                  const value = await request<{
                    source: string;
                    revision: number;
                  }>(
                    pdf
                      ? "/api/research/knowledge/document"
                      : sourceUrl
                        ? "/api/research/knowledge/acquire"
                        : "/api/research/knowledge/import",
                    pdf
                      ? {
                          ...body,
                          format: "pdf",
                          document_base64: pdf,
                          first_page: firstPage,
                          last_page: lastPage,
                        }
                      : sourceUrl
                        ? {
                            ...body,
                            origin: sourceUrl,
                            url: sourceUrl,
                            acquire_approved: urlApproved,
                          }
                        : body,
                  );
                  open(value.source, value.revision);
                }, "Source imported with actual receipt time; original bytes retained.");
              }}
            >
              {(
                [
                  ["source_id", "Stable source ID"],
                  ["title", "Title"],
                  ["author", "Author / source owner"],
                  ["origin", "Original reference or location"],
                  ["rights", "Rights and retention basis"],
                ] as const
              ).map(([name, label]) => (
                <label key={name}>
                  {label}
                  <input
                    value={draft[name]}
                    onChange={(e) =>
                      setDraft((v) => ({ ...v, [name]: e.target.value }))
                    }
                    required
                    maxLength={
                      name === "rights"
                        ? 500
                        : name === "origin"
                          ? 300
                          : name === "source_id"
                            ? 64
                            : 150
                    }
                  />
                </label>
              ))}
              <label>
                Category
                <select
                  value={draft.category}
                  onChange={(e) =>
                    setDraft((v) => ({ ...v, category: e.target.value }))
                  }
                >
                  {[
                    "theory",
                    "mechanics",
                    "methods",
                    "costs",
                    "risk",
                    "note",
                  ].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
              <label>
                Market applicability (blank means all)
                <input
                  value={draft.symbol}
                  onChange={(e) =>
                    setDraft((v) => ({
                      ...v,
                      symbol: e.target.value.toUpperCase(),
                    }))
                  }
                  maxLength={20}
                />
              </label>
              <label>
                Horizon applicability
                <select
                  value={draft.horizon}
                  onChange={(e) =>
                    setDraft((v) => ({ ...v, horizon: e.target.value }))
                  }
                >
                  <option value="">All horizons</option>
                  {["short", "medium", "long"].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
              <label>
                Source publication date (optional, UTC)
                <input
                  type="date"
                  value={draft.published_at}
                  onChange={(e) =>
                    setDraft((v) => ({ ...v, published_at: e.target.value }))
                  }
                />
              </label>
              <label>
                Format
                <select
                  value={draft.format}
                  onChange={(e) =>
                    setDraft((v) => ({ ...v, format: e.target.value }))
                  }
                >
                  <option value="markdown">Markdown</option>
                  <option value="text">Plain text</option>
                  <option value="html">HTML text extraction</option>
                </select>
              </label>
              <label>
                Open a permitted text or PDF section
                <input
                  type="file"
                  accept=".md,.txt,.html,.htm,.pdf"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    const isPdf = file.name.toLowerCase().endsWith(".pdf");
                    if (file.size > (isPdf ? 131072 : 65536)) {
                      setError(
                        "Choose a complete section within 64 KiB text / 128 KiB PDF.",
                      );
                      return;
                    }
                    setSourceUrl("");
                    setPdf(null);
                    if (isPdf) {
                      const reader = new FileReader();
                      reader.onload = () => {
                        setPdf(String(reader.result).split(",")[1]);
                      };
                      reader.onerror = () =>
                        setError("The selected file could not be read.");
                      reader.readAsDataURL(file);
                    } else
                      void file.text().then((text) =>
                        setDraft((v) => ({
                          ...v,
                          text,
                          format: file.name.endsWith("html")
                            ? "html"
                            : "markdown",
                        })),
                      );
                  }}
                />
              </label>
              {pdf && (
                <>
                  <label>
                    First PDF page
                    <input
                      type="number"
                      min={1}
                      max={1000}
                      value={firstPage}
                      onChange={(e) => setFirstPage(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    Last PDF page (at most six pages)
                    <input
                      type="number"
                      min={firstPage}
                      max={firstPage + 5}
                      value={lastPage}
                      onChange={(e) => setLastPage(Number(e.target.value))}
                    />
                  </label>
                  <p>
                    Native text only. Scanned, encrypted or unreadable pages
                    remain unavailable; original PDF bytes are retained.
                  </p>
                </>
              )}
              <label>
                Optional exact approved public HTTPS document
                <input
                  type="url"
                  value={sourceUrl}
                  onChange={(e) => {
                    setSourceUrl(e.target.value);
                    setPdf(null);
                  }}
                />
              </label>
              {sourceUrl && (
                <label className="check">
                  <input
                    type="checkbox"
                    checked={urlApproved}
                    onChange={(e) => setUrlApproved(e.target.checked)}
                  />
                  Approve acquiring this exact public document under the rights
                  above; redirects, private addresses and credentials are
                  refused
                </label>
              )}
              <label>
                Exact source section
                <textarea
                  value={draft.text}
                  onChange={(e) =>
                    setDraft((v) => ({ ...v, text: e.target.value }))
                  }
                  required={!pdf && !sourceUrl}
                  maxLength={65536}
                  rows={8}
                />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={draft.external_allowed}
                  onChange={(e) =>
                    setDraft((v) => ({
                      ...v,
                      external_allowed: e.target.checked,
                    }))
                  }
                />
                Rights permit disclosure to an approved reviewer
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={draft.generated}
                  onChange={(e) =>
                    setDraft((v) => ({ ...v, generated: e.target.checked }))
                  }
                />
                Model-generated interpretation (requires review)
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={draft.training_allowed}
                  onChange={(e) =>
                    setDraft((v) => ({
                      ...v,
                      training_allowed: e.target.checked,
                    }))
                  }
                />
                Rights permit teaching draft use (preparation and training
                retain their own gates)
              </label>
              <button disabled={busy || Boolean(sourceUrl && !urlApproved)}>
                Save original source
              </button>
            </form>
          </details>
          <div className="toolbar">
            <button
              disabled={busy}
              onClick={() =>
                void action(
                  () => request("/api/research/knowledge/reindex", {}),
                  "Derived index rebuilt; source versions and saved contexts unchanged.",
                )
              }
            >
              Rebuild search index
            </button>
            <button
              disabled={busy}
              onClick={() =>
                void action(
                  () => request("/api/research/knowledge/backup", {}),
                  "Coherent backup saved in the owned research tier, including original bytes.",
                )
              }
            >
              Back up library
            </button>
          </div>
        </>
      )}
      {tab === "library" && (
        <details>
          <summary>Restore a coherent backup to a fresh snapshot</summary>
          <p>
            The active library and original research stay unchanged. A restored
            snapshot retains source IDs and citations and rebuilds its search
            index.
          </p>
          {backups.map((b) => (
            <p key={b.backup}>
              {b.backup} · {b.bytes.toLocaleString()} bytes{" "}
              <button
                disabled={busy || !b.sha256}
                onClick={() =>
                  void action(async () => {
                    setRestored(
                      await request<Restored>(
                        "/api/research/knowledge/restore",
                        { backup: b.backup, sha256: b.sha256 },
                      ),
                    );
                    setRestoredSource(null);
                  }, "Restored into a fresh owned snapshot; active originals preserved.")
                }
              >
                Restore fresh snapshot
              </button>
            </p>
          ))}
          {restored && (
            <>
              <p>{restored.active_library}</p>
              {restored.sources.map((s) => (
                <button
                  key={s.source}
                  onClick={() =>
                    void action(
                      async () =>
                        setRestoredSource(
                          await request<Source>(
                            `/api/research/knowledge/restored/${restored.library}/${s.source}/${s.revision}`,
                          ),
                        ),
                      "Restored original reopened.",
                    )
                  }
                >
                  {s.metadata.title} · version {s.revision}
                </button>
              ))}
              {restoredSource && (
                <pre className="source-text">
                  {restoredSource.original ?? restoredSource.text}
                </pre>
              )}
            </>
          )}
        </details>
      )}
      {tab === "reviews" && (
        <>
          <p>Last completed review: {date(status?.last_completed_at)}</p>
          <p>
            {status?.next_action ??
              "Connecting to the retained review registry…"}
          </p>
          <button
            disabled={busy || !status?.policy?.enabled}
            onClick={() =>
              void action(
                () => request("/api/research/reviews/run", {}),
                "Review status refreshed; inspect the retained occurrence.",
              )
            }
          >
            Run due review now
          </button>
          <div className="knowledge-columns">
            <section>
              <h3>Retained reviews</h3>
              {status?.reviews.length === 0 && (
                <p>
                  No app-scheduled reviews yet. Connection and schedule approval
                  remain visible.
                </p>
              )}
              {status?.reviews.map((r) => (
                <article key={r.id} className="knowledge-card">
                  <button
                    onClick={() =>
                      navigate(
                        "research-reviews",
                        `?review=${encodeURIComponent(r.id)}`,
                      )
                    }
                  >
                    {r.occurrence} · {r.state}
                  </button>
                  <p>{r.reason ?? "Inspect original evidence and findings"}</p>
                  <p>
                    {date(r.updated)} · reserved ${r.cost_reserved.toFixed(2)} ·
                    actual{" "}
                    {r.cost_actual === null
                      ? "unavailable"
                      : `$${r.cost_actual.toFixed(4)}`}
                  </p>
                </article>
              ))}
              <div className="toolbar">
                <button
                  disabled={!reviewCursor}
                  onClick={() => setReviewCursor("")}
                >
                  First reviews
                </button>
                <button
                  disabled={!status?.next_before}
                  onClick={() => setReviewCursor(status?.next_before ?? "")}
                >
                  Older reviews
                </button>
              </div>
            </section>
            <section>
              {review ? (
                <>
                  <h3>{review.packet.question}</h3>
                  <p>
                    {review.state} · frozen evidence cutoff{" "}
                    {date(review.packet.cutoff)}
                  </p>
                  <p>
                    {review.policy.model} · {review.policy.reasoning} ·{" "}
                    {review.result?.authorship ??
                      "Original answer unavailable or rejected"}
                  </p>
                  <p>{review.result?.summary ?? review.reason}</p>
                  {review.result?.findings.map((f, i) => (
                    <article className="knowledge-card" key={i}>
                      <h4>{f.kind}</h4>
                      <p>{f.claim}</p>
                      <p>Uncertainty: {f.uncertainty}</p>
                      <p>
                        Support: {f.evidence_ids.join(", ")} · contrary:{" "}
                        {f.contrary_ids.join(", ") || "None supplied"}
                      </p>
                      {f.proposed_question && (
                        <p>Proposed next question: {f.proposed_question}</p>
                      )}
                    </article>
                  ))}
                  <p>{review.result?.coverage}</p>
                  <p>{review.result?.next_action}</p>
                  <h4>Saved continuation</h4>
                  {review.correction.map((c) => (
                    <p key={c.source}>
                      Annotation {c.state}: {c.reason ?? c.source}
                    </p>
                  ))}
                  {review.followups.map((q) => (
                    <p key={q.id}>
                      {q.question} · {q.state} ·{" "}
                      {q.reason ??
                        q.task ??
                        "Waiting for the existing research worker"}
                    </p>
                  ))}
                  {["unknown", "reserved"].includes(review.state) && (
                    <form onSubmit={(e) => e.preventDefault()}>
                      <label>
                        Reconciliation reason
                        <textarea
                          value={reason}
                          onChange={(e) => setReason(e.target.value)}
                          minLength={20}
                          maxLength={1200}
                        />
                      </label>
                      <p>
                        Unknown spend stays reserved. Reconciliation does not
                        repeat a provider request.
                      </p>
                      {review.state === "unknown" && (
                        <button
                          disabled={busy || reason.length < 20}
                          onClick={() =>
                            void action(
                              () =>
                                request(
                                  `/api/research/reviews/results/${review.id}/reconcile`,
                                  {
                                    expected_state: "unknown",
                                    action: "validate_retained",
                                    reason,
                                  },
                                ),
                              "Already retained final response revalidated locally.",
                            )
                          }
                        >
                          Recover retained final answer
                        </button>
                      )}
                      <button
                        disabled={busy || reason.length < 20}
                        onClick={() =>
                          void action(
                            () =>
                              request(
                                `/api/research/reviews/results/${review.id}/reconcile`,
                                {
                                  expected_state: review.state,
                                  action:
                                    review.state === "unknown"
                                      ? "abandon_unknown"
                                      : "cancel_reserved",
                                  reason,
                                },
                              ),
                            "Attempt reconciled; original history and budget reservation retained.",
                          )
                        }
                      >
                        {review.state === "unknown"
                          ? "Acknowledge unknown completion"
                          : "Cancel undispatched review"}
                      </button>
                    </form>
                  )}
                  <h4>Original retrieved context</h4>
                  {[
                    ...new Map(
                      (
                        review.delivered_knowledge ??
                        review.packet.knowledge.passages
                      ).map((p) => [p.citation, p]),
                    ).values(),
                  ].map((p) => (
                    <article key={p.citation}>
                      <button onClick={() => open(p.source, p.revision)}>
                        {p.title} · version {p.revision}
                      </button>
                      <p className="source-text">{p.text}</p>
                      <small>{p.citation}</small>
                    </article>
                  ))}
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void action(
                        () =>
                          request(
                            `/api/research/reviews/results/${encodeURIComponent(review.id)}/decision`,
                            {
                              expected_revision:
                                review.decisions.at(-1)?.revision ?? 0,
                              disposition: decision,
                              reason,
                            },
                          ),
                        "Attributed disposition appended; original review retained.",
                      );
                    }}
                  >
                    <label>
                      Review disposition
                      <select
                        value={decision}
                        onChange={(e) => setDecision(e.target.value)}
                      >
                        <option value="pending">
                          Pending independent check
                        </option>
                        <option value="accept_annotation">
                          Accept nonfinancial annotation
                        </option>
                        <option value="dispute">Dispute</option>
                        <option value="reject">Reject</option>
                      </select>
                    </label>
                    <label>
                      Reason
                      <textarea
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        minLength={20}
                        maxLength={1200}
                        required
                      />
                    </label>
                    <button disabled={busy || review.state !== "completed"}>
                      Save disposition
                    </button>
                  </form>
                  <details>
                    <summary>Create an instructional teaching draft</summary>
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        void action(async () => {
                          const saved = await request<{ id: string }>(
                            "/api/lab/training/select",
                            {
                              kind: "review_annotation",
                              identity: review.id,
                              role: "reviewer",
                              rights_reason: reason,
                            },
                          );
                          location.hash = "teaching:" + saved.id;
                        }, "Teaching candidate retained; target review and preparation use the existing workflow.");
                      }}
                    >
                      <p>
                        Accepted model-assisted annotations stay instructional.
                        All cited sources need explicit teaching rights. No
                        target approval or training occurs here.
                      </p>
                      <label>
                        Teaching rights basis
                        <textarea
                          value={reason}
                          onChange={(e) => setReason(e.target.value)}
                          minLength={20}
                          maxLength={1000}
                          required
                        />
                      </label>
                      <button
                        disabled={
                          busy ||
                          review.decisions.at(-1)?.body.disposition !==
                            "accept_annotation"
                        }
                      >
                        Create teaching draft
                      </button>
                    </form>
                  </details>
                  <a href="#training-data">
                    Open existing Training data workflow
                  </a>
                  <details>
                    <summary>Original packet and measured usage</summary>
                    <pre>
                      {JSON.stringify(
                        {
                          packet_sha: review.packet_sha,
                          packet: review.packet,
                          original_response: review.response,
                          provider_turns: review.provider_turns,
                          usage: review.usage,
                          decisions: review.decisions,
                          followups: review.followups,
                          correction: review.correction,
                        },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </>
              ) : (
                <p>
                  Select a review to reopen its saved evidence and attributed
                  findings.
                </p>
              )}
            </section>
          </div>
        </>
      )}
      {tab === "connection" && (
        <>
          <p>{status?.background}</p>
          <p>{status?.availability}</p>
          <p>{status?.transport}</p>
          <p>
            Existing ChatGPT Learning Review: {status?.existing_chatgpt_task}
          </p>
          <p>
            Next due:{" "}
            {status?.policy?.enabled
              ? date(status.next_due)
              : "Paused / not activated"}
          </p>
          <ul>
            {status?.blocked_reasons.map((v) => (
              <li key={v}>{v}</li>
            ))}
          </ul>
          <button
            disabled={busy}
            onClick={() =>
              void action(
                async () =>
                  setConnectionTest(
                    await request("/api/research/reviews/connection-test", {}),
                  ),
                "Scoped app-local discovery and read completed; temporary claim revoked.",
              )
            }
          >
            Test scoped connection
          </button>
          {connectionTest && (
            <p role="status">
              {connectionTest.scope}. {connectionTest.provider}.{" "}
              {connectionTest.credential}.
            </p>
          )}
          <button onClick={() => setPolicy(status?.policy ?? initialPolicy)}>
            Load saved setup
          </button>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void action(
                () =>
                  request("/api/research/reviews/configure", {
                    expected_revision: status?.revision ?? 0,
                    policy,
                  }),
                "Connection policy saved; no inferred provider or schedule permission.",
              );
            }}
          >
            {(
              [
                ["model", "Exact verified API model ID"],
                ["project", "Approved provider project"],
                ["price_source", "Verified model price source"],
              ] as const
            ).map(([name, label]) => (
              <label key={name}>
                {label}
                <input
                  value={policy[name]}
                  onChange={(e) =>
                    setPolicy((v) => ({ ...v, [name]: e.target.value }))
                  }
                  required
                />
              </label>
            ))}
            <label>
              Reasoning setting
              <select
                value={policy.reasoning}
                onChange={(e) =>
                  setPolicy((v) => ({ ...v, reasoning: e.target.value }))
                }
              >
                {["none", "low", "medium", "high"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            {(
              [
                ["daily_hour", "Daily hour (America/Denver)"],
                ["daily_requests", "Maximum reviews per rolling 24 hours"],
                ["token_reserve", "Total request and tool token allowance"],
                ["request_cost_ceiling_usd", "Maximum dollars per review"],
                [
                  "daily_cost_ceiling_usd",
                  "Maximum dollars per rolling 24 hours",
                ],
                [
                  "monthly_cost_ceiling_usd",
                  "Maximum dollars per rolling 30 days",
                ],
                [
                  "input_usd_per_million",
                  "Verified input dollars per million tokens",
                ],
                [
                  "output_usd_per_million",
                  "Verified output dollars per million tokens",
                ],
              ] as const
            ).map(([name, label]) => (
              <label key={name}>
                {label}
                <input
                  type="number"
                  step={name.includes("usd") ? "0.0001" : "1"}
                  value={policy[name]}
                  onChange={(e) =>
                    setPolicy((v) => ({ ...v, [name]: Number(e.target.value) }))
                  }
                  required
                />
              </label>
            ))}
            {(
              [
                [
                  "external_data_approved",
                  "Approve disclosure of explicitly eligible research/reference sections to this provider",
                ],
                [
                  "spending_approved",
                  "Approve these bounded API spending limits",
                ],
                [
                  "schedule_owner_approved",
                  "Approve Q-Trades as the single execution owner; existing ChatGPT task has been reconciled",
                ],
                [
                  "supported_profile_verified",
                  "Actual API model/settings and prices have been verified",
                ],
                ["enabled", "Enable app-owned scheduled reviews"],
              ] as const
            ).map(([name, label]) => (
              <label className="check" key={name}>
                <input
                  type="checkbox"
                  checked={policy[name]}
                  onChange={(e) =>
                    setPolicy((v) => ({ ...v, [name]: e.target.checked }))
                  }
                />
                {label}
              </label>
            ))}
            <p>
              Saving a paused policy makes no model call. Provider retention
              remains subject to the actual account controls.
            </p>
            <button disabled={busy}>Save consolidated setup</button>
          </form>
          <details>
            <summary>Protected provider credential</summary>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const value = credential.current?.value ?? "";
                if (credential.current) credential.current.value = "";
                void action(
                  () =>
                    request("/api/research/reviews/credential", {
                      credential: value,
                    }),
                  "Credential stored under the current Windows identity; no model request sent.",
                );
              }}
            >
              <label>
                API credential
                <input
                  type="password"
                  autoComplete="off"
                  ref={credential}
                  required
                  maxLength={512}
                />
              </label>
              <button disabled={busy}>Save protected credential</button>
            </form>
            <p>
              Credentials are not retained in browser storage or sent to models.
              A different Windows identity requires connection repair.
            </p>
          </details>
          <div className="toolbar">
            <button
              disabled={busy}
              onClick={() =>
                void action(
                  () => request("/api/research/reviews/pause", {}),
                  "Optional reviews paused; memory and paper processing continue.",
                )
              }
            >
              Pause reviews
            </button>
            <button
              disabled={busy}
              onClick={() =>
                void action(
                  () => request("/api/research/reviews/disconnect", {}),
                  "Provider disconnected; sources and review history retained.",
                )
              }
            >
              Disconnect reviewer
            </button>
          </div>
        </>
      )}
    </section>
  );
}
