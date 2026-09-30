export type MarketOutcome = {
  status: string;
  reason?: string;
  label_type?: string;
  return_bps?: string;
  favorable_excursion_bps?: string;
  adverse_excursion_bps?: string;
  available_at?: number;
  horizon_at?: number;
  ambiguity?: string;
  execution_reason?: string;
};

export type Episode = {
  episode: string;
  action: string;
  available_at: number;
  retrieval_ms: number;
  descriptor: {
    status: string;
    reason?: string;
    cutoff: number;
    data_mode: string;
    returns_bps?: number[];
    raw_closes?: string[];
    contract: { strategy: string; lookback_seconds: number; horizon_seconds: number };
  };
  retrieval: {
    status: string;
    reason?: string;
    earliest_action_at: number;
    expires_at?: number;
    distinct_groups?: number;
    economic_evidence: string;
    classification: string;
    fallback: string;
    support_note?: string;
    matches: {
      episode: string;
      record_id: number;
      distance_bps: number;
      cutoff: number;
      group_id: string;
      context: { book?: { spread_bps?: string }; closed_bar?: { volume_ratio?: string } };
      outcome_status: string;
      outcome?: MarketOutcome;
    }[];
  };
};

const when = (at?: number) => at == null ? "Unavailable" :
  new Date(at * 1000).toLocaleString("en-US", { timeZone: "America/Denver" });
const bps = (value?: string) => value == null ? "Unavailable" :
  Number(value).toLocaleString("en-US", { maximumFractionDigits: 4 }) + " bps";

export function HistoricalMatches({ episode, outcome, pending, open }: {
  episode: Episode;
  outcome?: MarketOutcome;
  pending: boolean;
  open: (id: number) => void;
}) {
  const { descriptor: d, retrieval: r } = episode;
  return <>
    <section className="memory-prefix" aria-label="As-seen historical matches">
      <p className="eyebrow">AS-SEEN PREFIX · {d.data_mode}</p>
      <h3>{d.contract.strategy} · BTC / USD</h3>
      <p>Cutoff: {when(d.cutoff)} · Lookback: {d.contract.lookback_seconds / 60} minutes ·
        Declared market horizon: {d.contract.horizon_seconds / 60} minutes.</p>
      <p>{episode.action}</p>
      <dl className="summary-values">
        <div><dt>Recognition confidence</dt><dd>Not estimated</dd></div>
        <div><dt>Historical support</dt><dd>{r.distinct_groups ?? "Unavailable"} event groups</dd></div>
        <div><dt>Local lookup</dt><dd>{episode.retrieval_ms.toFixed(3)} ms</dd></div>
        <div><dt>Result</dt><dd>{r.status.replaceAll("_", " ")}</dd></div>
      </dl>
      <p>{r.economic_evidence}. {r.support_note}</p>
      <p>Result usable from {when(r.earliest_action_at)}.
        {r.expires_at != null && ` Entry evidence expires ${when(r.expires_at)}.`}
        {r.reason ?? d.reason}</p>
      <p className="fine-print">{r.classification}. {r.fallback}.</p>
      {d.raw_closes && <details><summary>Numerical prefix in original units</summary>
        <p>USD closes, oldest first: {d.raw_closes.join(", ")}</p>
        <p>One-minute returns in basis points: {d.returns_bps?.map(v => v.toFixed(4)).join(", ")}</p>
      </details>}
      {r.matches.length > 0 ? <div className="table-scroll">
        <table className="market-table" aria-label="Historical neighborhood">
          <thead><tr><th>Earlier cutoff</th><th>Shape distance</th><th>Observed context</th>
            <th>Outcome available at query</th><th /></tr></thead>
          <tbody>{r.matches.map(m => <tr key={m.episode}>
            <td>{when(m.cutoff)}<small>Event group {m.group_id}</small></td>
            <td>{m.distance_bps.toFixed(4)} bps</td>
            <td>Spread: {bps(m.context.book?.spread_bps)}
              <small>Volume ratio: {m.context.closed_bar?.volume_ratio ?? "Unavailable"}</small></td>
            <td>{m.outcome?.status === "available" ? `${bps(m.outcome.return_bps)} market move` :
              m.outcome?.reason ?? m.outcome_status.replaceAll("_", " ")}</td>
            <td><button className="button secondary small" disabled={pending}
              onClick={() => open(m.record_id)}>Reopen earlier prefix</button></td>
          </tr>)}</tbody>
        </table>
      </div> : <p>No eligible comparable history in this frozen query.
        Missing opposing examples do not establish safety.</p>}
    </section>
    <section className="memory-outcome" aria-label="Subsequent market outcome">
      <p className="eyebrow">SUBSEQUENT OUTCOME · AVAILABLE LATER</p>
      <h3>{outcome?.status === "available" ? "Matured market path" :
        outcome?.reason ?? "Outcome pending"}</h3>
      {outcome ? <>
        <p>{outcome.label_type}</p>
        <p>Available: {when(outcome.available_at)} · Horizon ended: {when(outcome.horizon_at)}</p>
        {outcome.status === "available" && <dl className="summary-values">
          <div><dt>Market move from prefix close</dt><dd>{bps(outcome.return_bps)}</dd></div>
          <div><dt>Favorable excursion</dt><dd>{bps(outcome.favorable_excursion_bps)}</dd></div>
          <div><dt>Adverse excursion</dt><dd>{bps(outcome.adverse_excursion_bps)}</dd></div>
        </dl>}
        <p>{outcome.execution_reason}. {outcome.ambiguity}</p>
      </> : <p>The declared horizon has not produced a retained outcome.
        Archive capacity or gaps can leave it unavailable.</p>}
      <p className="fine-print">Later observations do not change the saved prefix or original match
        receipt. Executable opportunity after result availability and realized P&amp;L remain unavailable.</p>
    </section>
  </>;
}
