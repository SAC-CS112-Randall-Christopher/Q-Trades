import { useEffect, useState } from "react";

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
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({text, horizon, outcome, before: String(before)});
    void fetch(`/api/research/lessons?${query}`, {signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)])})
      .then(async r => { if (!r.ok) throw new Error("Supported lessons unavailable"); return r.json() as Promise<Page>; })
      .then(p => { setPage(p); setError(null); }).catch(e => { if (!controller.signal.aborted) setError(String(e)); });
    return () => controller.abort();
  }, [text, horizon, outcome, before]);
  const inspect = async (id: string) => {
    try {
      const r = await fetch(`/api/research/lessons/${encodeURIComponent(id)}`, {signal: AbortSignal.timeout(10000)});
      if (!r.ok) throw new Error("Exact referenced lesson cannot reopen");
      setDetail(await r.json()); setError(null);
    } catch(e) { setError(String(e)); }
  };
  useEffect(() => {
    const restore = () => { const id = new URLSearchParams(location.hash.split("?")[1] ?? "").get("lesson"); if (id) void inspect(id); };
    restore(); window.addEventListener("hashchange", restore);
    return () => window.removeEventListener("hashchange", restore);
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
    {detail != null && <details open><summary>Exact result, cost, source, unknowns and falsification</summary><pre>{JSON.stringify(detail, null, 2)}</pre></details>}
  </section>;
}
