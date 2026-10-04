import { useEffect, useState } from "react";
import { useEvidenceRead } from "./useEvidenceRead";

type Lesson = { id: string; claim: string; cause: string; support: unknown; sha256: string; context: {family: string; horizon: string; data_basis: string}; selection: {state: string; reason: string; next_task: string | null} | null };
type Page = { lessons: Lesson[]; next_before: number | null; scope: string };

export function LessonPanel({ openTask }: {openTask: (id: string) => void}) {
  const [page, setPage] = useState<Page | null>(null);
  const [detail, setDetail] = useState<unknown>(null);
  const [text, setText] = useState("");
  const [horizon, setHorizon] = useState("");
  const [outcome, setOutcome] = useState("");
  const [before, setBefore] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selectedLesson, setSelectedLesson] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const detailRead = useEvidenceRead();
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({text, horizon, outcome, before: String(before)});
    void fetch(`/api/research/lessons?${query}`, {signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)])})
      .then(async r => { if (!r.ok) throw new Error("Supported lessons unavailable"); return r.json() as Promise<Page>; })
      .then(p => { if (!controller.signal.aborted) { setPage(p); setError(null); } }).catch(e => { if (!controller.signal.aborted) setError(String(e)); });
    return () => controller.abort();
  }, [text, horizon, outcome, before]);
  const inspect = async (id: string, navigate = true) => {
    const request = detailRead.begin(10000);
    setSelectedLesson(id); setDetail(null); setDetailError(null); setDetailLoading(true);
    if (navigate) {
      const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
      params.set("lesson", id);
      history.pushState(null, "", `#role-research?${params}`);
    }
    try {
      const r = await fetch(`/api/research/lessons/${encodeURIComponent(id)}`, {signal: request.signal});
      if (!r.ok) throw new Error("Exact referenced lesson cannot reopen");
      const value = await r.json();
      if (value.id !== id) throw new Error("Referenced lesson identity differs");
      if (request.isCurrent()) setDetail(value);
    } catch(e) { if (request.isCurrent()) setDetailError(String(e)); }
    finally { if (request.isCurrent()) setDetailLoading(false); }
  };
  useEffect(() => {
    const restore = () => {
      const id = new URLSearchParams(location.hash.split("?")[1] ?? "").get("lesson");
      if (id) void inspect(id, false);
      else { detailRead.cancel(); setSelectedLesson(null); setDetail(null); setDetailError(null); setDetailLoading(false); }
    };
    restore(); window.addEventListener("hashchange", restore); window.addEventListener("popstate", restore);
    return () => { window.removeEventListener("hashchange", restore); window.removeEventListener("popstate", restore); };
  }, []);
  return <section aria-label="Supported research lessons"><h3>Supported lessons and next research</h3>
    <p>These notes cite recorded comparisons. Opening a note records outcome disclosure; access does not add statistical support.</p>
    <label>Find mechanism or source <input maxLength={200} value={text} onChange={e => {setText(e.target.value); setBefore(0);}} /></label>
    <label>Lesson horizon <select value={horizon} onChange={e => {setHorizon(e.target.value); setBefore(0);}}><option value="">All</option><option>short</option><option>medium</option><option>long</option></select></label>
    <label>Recorded outcome <select value={outcome} onChange={e => {setOutcome(e.target.value); setBefore(0);}}><option value="">All, including unsuccessful</option>{["promising", "economically_unsuccessful", "inconclusive", "low_information", "data_blocked", "risk_stopped"].map(x => <option key={x}>{x}</option>)}</select></label>
    {error && <p role="alert">{error}</p>}
    {page?.lessons.length === 0 && <p>No supported recorded comparisons match this query.</p>}
    <ul>{page?.lessons.map(l => <li key={l.id}><button type="button" onClick={() => void inspect(l.id)}>{l.claim}</button><p>{l.context.family} · {l.context.horizon} · {l.context.data_basis}. Cause: {l.cause}.</p>{l.selection && <p>Next: {l.selection.state} · {l.selection.reason} {l.selection.next_task && <button type="button" onClick={() => openTask(l.selection!.next_task!)}>Open justified next question</button>}</p>}</li>)}</ul>
    {!!before && <button type="button" onClick={() => setBefore(0)}>Latest lessons</button>}
    {page?.next_before && <button type="button" onClick={() => setBefore(page.next_before!)}>Older lessons</button>}
    {selectedLesson && <p>Selected lesson: {selectedLesson}{detailLoading ? " · reading original support…" : ""}</p>}
    {detailError && <p role="alert">{detailError}</p>}
    {detail != null && <details open><summary>Exact result, cost, source, unknowns and falsification</summary><pre>{JSON.stringify(detail, null, 2)}</pre></details>}
  </section>;
}
