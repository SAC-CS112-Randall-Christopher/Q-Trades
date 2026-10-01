import { useEffect, useRef, useState } from "react";

type Page = { capability: string; artifact_sha256: string; library_count: number; offset: number; next_offset: number | null; library: unknown[]; artifact_metadata: unknown; scope: string };
type Catalog = Record<string, { strategy: { entry_filter?: { artifact: { sha256: string } } } }>;

export function FrozenComponentPanel({ task, catalog }: { task: string; catalog: unknown }) {
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  useEffect(() => { sequence.current++; setPage(null); setError(null); setBusy(false); }, [task]);
  const choices = Object.entries((catalog ?? {}) as Catalog).filter(([, value]) => value.strategy.entry_filter);
  const load = async (capability: string, offset = 0) => {
    const request = ++sequence.current;
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/lab/roles/tasks/${encodeURIComponent(task)}/components/${encodeURIComponent(capability)}?offset=${offset}`, { cache: "no-store", signal: AbortSignal.timeout(6000) });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail ?? "Retained component page unavailable.");
      if (sequence.current === request) setPage(value as Page);
    } catch (cause) { if (sequence.current === request) setError(cause instanceof Error ? cause.message : "Component page unavailable; retry when connected."); }
    finally { if (sequence.current === request) setBusy(false); }
  };
  if (!choices.length) return null;
  return <section aria-label="Retained frozen component">
    {choices.map(([key]) => <button key={key} type="button" disabled={busy} onClick={() => void load(key)}>Open frozen component {key}</button>)}
    {error && <p role="alert">{error}</p>}
    {page && <><h4>Frozen training evidence</h4><p>{page.scope}. Rows {page.offset + 1}–{page.offset + page.library.length} of {page.library_count}. Artifact {page.artifact_sha256}. Reads do not add statistical support.</p>
      <details><summary>Exact artifact contract, calibration and normalization</summary><pre>{JSON.stringify(page.artifact_metadata, null, 2)}</pre></details>
      <pre>{JSON.stringify(page.library, null, 2)}</pre>
      {page.offset > 0 && <button type="button" disabled={busy} onClick={() => void load(page.capability, Math.max(0, page.offset - 8))}>Previous training rows</button>}
      {page.next_offset != null && <button type="button" disabled={busy} onClick={() => void load(page.capability, page.next_offset!)}>Next training rows</button>}
    </>}
  </section>;
}
