export type FeedDetails = {
  feed: {
    transport: string;
    capture_dropped: number;
    clock_uncertainty_ms: number | null;
    markets: Record<string, {
      interval_ms: number;
      source: string;
      usable: boolean;
      received_age_ms: number | null;
      round_trip_ms: number | null;
      interval_p50_ms: number | null;
      event_age_p95_ms: number | null;
      error: string | null;
      books: number;
    }>;
  };
  universe: {
    markets_scanned: number;
    selected: string[];
    scanned_at: number;
  };
  research_constrained: boolean;
  performance: {
    average_cpu_percent_of_machine: number;
    engine_p95_ms: number | null;
    commit_p95_ms: number | null;
  };
  storage: {
    bytes?: number;
    physical_bytes?: number;
    captured?: number;
    pruned?: number;
    capture_discarded: number;
    projected_uncapped_raw_gib_per_day: number;
    disk_free_gib: number;
    capture_error: string | null;
    postgres: { database_bytes?: number; candles?: number; events?: number };
  };
};

const ms = (value: number | null) => value === null ? "—" : `${value.toFixed(0)} ms`;
const mib = (value = 0) => `${(value / 1024 / 1024).toFixed(1)} MiB`;

export function FeedPanel({ data }: { data: Partial<FeedDetails> }) {
  if (!data.feed || !data.universe || !data.storage || !data.performance) return null;
  const { feed, universe, storage, performance } = data;
  const markets = Object.entries(feed.markets);
  const pushed = markets.filter(([, m]) => m.source === "binance.us-depth-websocket").length;
  const polled = markets.filter(([, m]) => m.source === "binance.us-rest-fallback").length;
  return <section className="feed-panel" aria-label="Market feed and local storage">
    <div className="feed-heading">
      <div><p className="eyebrow">MARKET FEED & LOCAL STORAGE</p>
        <h3>{pushed ? "Streaming market updates" : polled ? "Polling fallback active" : "Waiting for fresh market data"}</h3></div>
      <span className={`pill ${pushed && !polled ? "paper" : "caution"}`}>
        Fresh: {pushed} streamed · {polled} polled
      </span>
    </div>
    <p>{universe.markets_scanned} USD markets screened every minute. Up to four extra candidates
      receive closer observation; qualified candidates and held positions get priority.</p>
    <p className="fine-print">Targets: 1-second candidate stream → 100-millisecond fast stream.
      Polling fallback waits at least 0.5 seconds between fast-market requests, plus request time.
      Research candidates use a 5-second wait until promoted.
      Subscription speed is not a promise of execution speed.</p>
    {data.research_constrained && <p className="feed-warning">Extra research feeds are reduced while processing or storage is constrained. Held positions retain priority.</p>}
    <div className="feed-markets">{markets.map(([symbol, market]) => <article key={symbol}>
      <strong>{symbol}</strong>
      <span>{market.interval_ms === 100 ? "Priority observation" : "Research observation"}</span>
      <span>{market.source === "binance.us-depth-websocket" ? "WebSocket" : market.usable ? "REST fallback" : "No fresh book"}</span>
      <span>{market.received_age_ms === null ? "Awaiting a fresh observation" : `Received ${ms(market.received_age_ms)} ago`}</span>
      <span>{market.source === "binance.us-depth-websocket"
        ? `Event age, p95: ${ms(market.event_age_p95_ms)}`
        : `Request round trip: ${ms(market.round_trip_ms)}`}</span>
    </article>)}</div>
    {!pushed && <p className="feed-warning">No fresh streamed book is available. Polled books have receipt times and sequence numbers, but no exchange event timestamp; changes between snapshots may be missed.</p>}
    <div className="feed-storage">
      <article><p className="eyebrow">BOUNDED RAW CAPTURE</p>
        <h3>{mib(storage.bytes)} / 64 MiB</h3>
        <p>{mib(storage.physical_bytes)} on disk including SQLite overhead.</p>
        <p>{(storage.pruned ?? 0).toLocaleString()} old raw observations pruned. {feed.capture_dropped + storage.capture_discarded} observations dropped before storage.</p>
        <p className="fine-print">At this measured input rate, keeping everything would add about {storage.projected_uncapped_raw_gib_per_day.toFixed(2)} GiB/day. This is a short-run estimate, not actual retained growth.</p>
      </article>
      <article><p className="eyebrow">PERMANENT LEARNING RECORD</p>
        <h3>{mib(storage.postgres.database_bytes)} local database</h3>
        <p>{(storage.postgres.candles ?? 0).toLocaleString()} closed candles · {(storage.postgres.events ?? 0).toLocaleString()} audit events</p>
        <p>Trades, costs, funding, decisions, scans, minute summaries, and review evidence are retained.</p>
        <p className="fine-print">Dedicated trading PostgreSQL. Raw capture pruning never deletes the trade ledger.</p>
      </article>
      <article><p className="eyebrow">MACHINE BUDGET</p>
        <h3>{storage.disk_free_gib.toFixed(1)} GiB free</h3>
        <p>Application CPU average: {performance.average_cpu_percent_of_machine.toFixed(2)}% of this machine</p>
        <p>Engine work, p95: {ms(performance.engine_p95_ms)}</p>
        <p className="fine-print">Raw capture pauses below 5 GiB free. CPU excludes Docker and other processes. Database and backups also require space.</p>
      </article>
    </div>
    {storage.capture_error && <p className="feed-warning">{storage.capture_error}</p>}
  </section>;
}
