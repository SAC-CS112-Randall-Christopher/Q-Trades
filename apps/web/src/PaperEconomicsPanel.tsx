import { useEffect, useState, type FormEvent } from "react";

type Mark = {
  equity: string; cash: string; available_cash: string; reserved: string; funding: string;
  net_pnl: string | null; realized: string; unrealized: string | null; fees: string;
  fresh: boolean; flat: boolean; settings_version: number; execution_profile: string;
  operating_daily_usd: string | null; starting_capital: string;
};
type Score = {
  total_return: string | null; exposure_total_return: string | null; cash_total_return: string | null;
  return: string | null; net_pnl: string | null; gross_reference_pnl: string | null;
  execution_cost: string | null; fees_paid: string; operating_cost: string | null;
  total_pnl: string | null; exposure_return: string | null; cash_return: string;
  start_equity: string; end_equity: string | null; funding_change: string;
  max_drawdown: string; trades: number; wins: number; reasons: string[];
  eligible: boolean; available: boolean; rank: number | null; cohort: string;
  execution_profile: string; benchmark_status: Record<string, string>;
};
type AccountWindow = { start: number; end: number; complete: boolean; scores: Record<string, Score> };
export type EconomicsSnapshot = {
  started_at: number | null; current: AccountWindow | null; completed: AccountWindow[];
  accounts: Record<string, Mark>; method: string; benchmark: string; cost_basis: string;
  operating_basis: string; retention: string;
};
export type ExecutionProfile = {
  id: string; label: string; checked_at: string | null; taker_fee: string;
  fee_asset: string; fill_policy: string; latency_seconds: number; expiry_seconds: number;
  precision: string; settlement: string; limitations: string;
};
const dollars = (v: string | null | undefined) => v == null ? "Not available" :
  Number(v).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 4 });
const percent = (v: string | null | undefined) => v == null ? "Not available" :
  `${(Number(v) * 100).toFixed(3)}%`;
const when = (v: number) => new Date(v * 1000).toLocaleString("en-US", {
  timeZone: "America/Denver", month: "short", day: "numeric", hour: "numeric", minute: "2-digit"
});

export function PaperEconomicsPanel({ data, profiles = [], unavailable }: {
  data?: EconomicsSnapshot; profiles?: ExecutionProfile[]; unavailable: boolean;
}) {
  const [account, setAccount] = useState("primary");
  const [selectedWindow, setSelectedWindow] = useState("current");
  const [profile, setProfile] = useState("");
  const [daily, setDaily] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mark = data?.accounts[account];
  useEffect(() => {
    setProfile(mark?.execution_profile ?? "");
    setDaily(mark?.operating_daily_usd ?? "");
  }, [account, mark?.execution_profile, mark?.settings_version, mark?.operating_daily_usd]);
  const window = selectedWindow === "current" ? data?.current :
    data?.completed.find(w => String(w.start) === selectedWindow);
  const score = window?.scores[account];
  const assumption = profiles.find(p => p.id === profile);
  const blockedProfile = !!mark && !mark.flat && profile !== mark.execution_profile;
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!mark) return;
    if (profile !== mark.execution_profile && !globalThis.confirm(
      "Apply this paper execution scenario to future orders only? Original fees and history stay unchanged."
    )) return;
    setPending(true); setError(null); setMessage(null);
    try {
      const response = await fetch(`/api/paper/accounts/${encodeURIComponent(account)}/economics-settings`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" },
        body: JSON.stringify({ execution_profile: profile, operating_daily_usd: daily.trim() || null,
          expected_version: mark.settings_version }), signal: AbortSignal.timeout(7000)
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => null) as { detail?: unknown } | null;
        throw new Error(typeof detail?.detail === "string" ? detail.detail : "Settings were not confirmed. Refresh and retry.");
      }
      setMessage("Saved for future observations. Current window is marked changed; historical results and cash are untouched.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Settings were not confirmed. Retry when connected.");
    } finally { setPending(false); }
  }
  return <section className="economics-panel" id="account-economics" aria-label="Whole-account economics">
    <div className="economics-heading"><div><p className="eyebrow">ACCOUNT RESULTS, NOT WINNING-TRADE AVERAGES</p>
      <h3>Whole-account economics</h3></div>
      <label>Account<select value={account} onChange={e => { setAccount(e.target.value); setError(null); setMessage(null); }}>
        {Object.keys(data?.accounts ?? { primary: null }).map(name => <option key={name}>{name}</option>)}
      </select></label></div>
    {!data && <p>Account economics are not available yet. Waiting for the paper worker.</p>}
    {unavailable && <p className="error-banner" role="alert">Paper worker disconnected or stale. Current values are not confirmed; completed windows remain historical.</p>}
    {mark && <><h4>Current balances and holdings</h4><dl className="economics-values">
      <div><dt>Liquidation equity</dt><dd>{mark.fresh && !unavailable ? dollars(mark.equity) : "Mark unavailable"}</dd></div>
      <div><dt>Available cash</dt><dd>{dollars(mark.available_cash)}</dd></div>
      <div><dt>Reserved cash</dt><dd>{dollars(mark.reserved)}</dd></div>
      <div><dt>Realized trading P&amp;L</dt><dd>{dollars(mark.realized)}</dd></div>
      <div><dt>Open P&amp;L after estimated exits</dt><dd>{!unavailable ? dollars(mark.unrealized) : "Not available"}</dd></div>
      <div><dt>Original hypothetical capital</dt><dd>{dollars(mark.starting_capital)}</dd></div>
    </dl><p className="fine-print">Idle cash is part of account returns. Funding is not profit; reservations do not create extra cash. Cash figures are last reported balances when disconnected.</p></>}
    <label className="economics-window">Comparison window<select value={selectedWindow} onChange={e => setSelectedWindow(e.target.value)}>
      <option value="current">Current window — provisional</option>
      {[...(data?.completed ?? [])].reverse().map(w => <option key={w.start} value={String(w.start)}>{when(w.start)} to {when(w.end)} Denver</option>)}
    </select></label>
    {window ? <><p>{when(window.start)} – {when(window.end)} Denver · {window.complete ? "Completed observation window" : "Collecting; not eligible for ranking"}</p>
      {score ? <><dl className="economics-values">
        <div><dt>Gross reference result</dt><dd>{dollars(score.gross_reference_pnl)}</dd></div>
        <div><dt>Execution-cost attribution</dt><dd>{dollars(score.execution_cost)}</dd></div>
        <div><dt>Net trading result</dt><dd>{dollars(score.net_pnl)}</dd></div>
        <div><dt>Estimated operating allocation</dt><dd>{score.operating_cost === null ? "Not specified / changed" : dollars(score.operating_cost)}</dd></div>
        <div><dt>Total after operating allocation</dt><dd>{dollars(score.total_pnl)}</dd></div>
        <div><dt>Trading account return</dt><dd>{percent(score.return)}</dd></div>
        <div><dt>Return after operating allocation</dt><dd>{percent(score.total_return)}</dd></div>
      </dl>
      <p>{score.reasons.length ? score.reasons.join(" · ") : "Complete matched observations; not evidence of repeatable profitability."}</p>
      <p className="fine-print">{data?.cost_basis} Gross reference is an attribution, not a frictionless strategy backtest. Fees actually paid in this window: {dollars(score.fees_paid)}.</p>
      <p>Trade diagnostics: {score.trades} closed / {score.wins} winners · window drawdown {percent(score.max_drawdown)} · funding change {dollars(score.funding_change)}.</p>
      <p className="fine-print">{data?.benchmark}. Each window control starts from the account’s window-opening equity, pays its own costs and holds until that window ends; it is not a continuously held portfolio. Cash benchmark: 0% before operating allocation; {percent(score.cash_total_return)} after the same allocation. Exposure before allocation: {percent(score.exposure_return)}.</p>
      <p className="fine-print">Benchmark legs: {Object.entries(score.benchmark_status).map(([s, v]) => `${s}: ${v}`).join(" · ") || "Waiting for starting marks"}</p></> : <p>This account joined after this window began. Its first full comparison starts in the next common window.</p>}
      <div className="table-scroll"><table className="market-table economics-table"><thead><tr>
        <th>Account</th><th>Trading return</th><th>After operating allocation</th><th>Exposure after allocation</th><th>Matched rank</th>
      </tr></thead><tbody>{Object.entries(window.scores).map(([name, row]) => <tr key={name}>
        <td>{name}<small>{row.execution_profile}</small></td><td>{percent(row.return)}</td><td>{percent(row.total_return)}</td>
        <td>{percent(row.exposure_total_return)}</td><td>{row.rank ?? "Not ranked"}{row.reasons.length > 0 && <details><summary>Why not ranked?</summary><small>{row.reasons.join("; ")}</small></details>}</td>
      </tr>)}</tbody></table></div>
      <p className="fine-print">Ranks use returns after operating allocation, only within identical original-capital, cumulative-funding, fee-profile, risk-policy and operating-allocation groups. Different groups cannot be ranked against each other. Counterfactual account results must not be summed into a realizable portfolio.</p>
    </> : <p>Waiting for prospective account observations. Old completed-trade averages are not used to reconstruct missing equity windows.</p>}
    {mark && <details className="economics-settings"><summary>Execution and operating-cost assumptions</summary>
      <form onSubmit={e => void save(e)}>
        <label>Execution fee scenario<select value={profile} onChange={e => setProfile(e.target.value)}>
          {profiles.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select></label>
        <label>Estimated operating USD per day<input value={daily} onChange={e => setDaily(e.target.value)}
          placeholder="Unknown — leave blank" type="number" min="0" max="10000" step="0.000001" /></label>
        <p className="fine-print">{data?.operating_basis}. Enter 0 only as an explicit zero-cost scenario. Unspecified is unknown, not free. This allocation is subtracted once in reporting, never from paper cash.</p>
        {assumption && <p className="fine-print">{assumption.fill_policy}. Delay: {assumption.latency_seconds}s; observation window: {assumption.expiry_seconds}s. {assumption.precision}. {assumption.settlement}. {assumption.limitations} {assumption.checked_at ? `Public schedule checked ${assumption.checked_at}; account commissions and eligibility are not verified.` : "Original research assumption retained as fee stress."}</p>}
        {blockedProfile && <p>Changing the execution profile requires this account to be flat with no pending orders. Position exits remain enabled.</p>}
        <button type="submit" className="button secondary small" disabled={pending || unavailable || blockedProfile}>
          {pending ? "Saving…" : "Save future cost assumptions"}</button>
        {error && <p className="error-banner" role="alert">{error}</p>}
        {message && <p role="status">{message}</p>}
      </form></details>}
    <p className="fine-print">{data?.retention}. Two four-hour comparisons support bounded paper selection, not statistical proof; dependence-aware qualification remains separate research work.</p>
  </section>;
}
