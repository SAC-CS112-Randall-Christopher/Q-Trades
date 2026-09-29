import { useEffect, useRef, useState } from "react";

type JournalEvent = { id: number; at: number; kind: string; body: Record<string, unknown>;
  journal: { asset: string; bucket: string; amount: string }[] };
type Page = { records: JournalEvent[]; has_more: boolean; next_after: number };
const when = (at: number) => new Date(at * 1000).toLocaleString("en-US", { timeZone: "America/Denver" });
const buckets: Record<string, string> = { cash: "Cash", reserved: "Reserved cash", fees: "Fees",
  fake_funding: "Hypothetical funding", realized_pnl: "Realized trading result", inventory: "Inventory" };

export function PaperCampaignJournal({ account }: { account: string }) {
  const [page, setPage] = useState<Page | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  async function load(after: number) {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setPending(true); setError(null);
    try {
      const response = await fetch(`/api/paper/journal?account=${encodeURIComponent(account)}&after=${after}&limit=100`,
        { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(7000)]) });
      if (!response.ok) throw new Error("Account history could not load. Retry when connected.");
      const result = await response.json() as Page;
      if (!controller.signal.aborted) setPage(result);
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Account history could not load.");
    } finally { if (!controller.signal.aborted) setPending(false); }
  }

  return <details className="campaign-journal" onToggle={e => {
    if (e.currentTarget.open && !page && !pending) void load(0);
  }}><summary>Account history and balances changed</summary>
    <p>Permanent account history, oldest first. Each page holds up to 100 events; earlier records stay retained.</p>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {pending && <p role="status">Loading account history…</p>}
    {page && <><div className="table-scroll"><table className="market-table" aria-label="Selected account history">
      <thead><tr><th>Denver time</th><th>Event</th><th>Result / reason</th></tr></thead>
      <tbody>{page.records.map(event => <tr key={event.id}>
        <td>{when(event.at)}</td><td>{event.kind.replaceAll("_", " ")}</td>
        <td>{String(event.body.reason ?? event.body.note ?? event.body.purpose ?? event.body.action ?? "Recorded observation")}
          {event.body.amount != null && <small>{String(event.body.amount)} USD</small>}
          {event.journal.length > 0 && <details><summary>Balances changed</summary>
            <ul>{event.journal.map((line, i) => <li key={i}>{buckets[line.bucket] ?? line.bucket}:
              {" "}{line.amount} {line.asset}</li>)}</ul></details>}</td>
      </tr>)}</tbody></table></div>
      {!page.records.length && <p>No account events on this page.</p>}
      <p className="fine-print">Showing {page.records.length} retained events{page.has_more ? "; more history follows." : "; end of retained history."}</p>
    </>}
    <div className="campaign-actions">
      <button className="button secondary small" disabled={pending} onClick={() => void load(0)}>First history page</button>
      {page?.has_more && <button className="button secondary small" disabled={pending}
        onClick={() => void load(page.next_after)}>Next history page</button>}
    </div>
  </details>;
}
