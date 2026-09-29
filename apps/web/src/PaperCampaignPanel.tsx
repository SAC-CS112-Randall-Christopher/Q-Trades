import { useEffect, useState, type FormEvent } from "react";
import type { Account, PaperSnapshot } from "./PaperPanel";
import { PaperCampaignJournal } from "./PaperCampaignJournal";

type DraftAccount = {
  label: string; starting_cash: "50" | "100"; strategy: string;
  execution_profile: string; operating_daily_usd: string;
};
type Draft = { request_id: string; name: string; accounts: DraftAccount[]; attempted: boolean };
const draftKey = "qtrades-paper-campaign-v1";
const strategies = ["breakout-v1", "responsive-v1", "selective-v1"];
const money = (v: string | undefined | null) => v == null ? "Unavailable" :
  Number(v).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 4 });

function loadDraft(): Draft {
  try {
    const saved = JSON.parse(localStorage.getItem(draftKey) ?? "null") as Draft | null;
    if (saved && typeof saved.request_id === "string" && typeof saved.name === "string" &&
      typeof saved.attempted === "boolean" && Array.isArray(saved.accounts) &&
      [10, 14].includes(saved.accounts.length) && saved.accounts.every(a =>
        typeof a.label === "string" && ["50", "100"].includes(a.starting_cash) &&
        strategies.includes(a.strategy) && typeof a.execution_profile === "string" &&
        typeof a.operating_daily_usd === "string")) return saved;
  } catch { /* An unavailable local draft never changes server-side funding. */ }
  return {
    request_id: crypto.randomUUID(), name: "Spot baseline campaign", attempted: false,
    accounts: Array.from({ length: 10 }, (_, i) => ({
      label: `${strategies[i % 3].replace("-v1", "")} ${Math.floor(i / 3) + 1}`,
      starting_cash: "100", strategy: strategies[i % 3],
      execution_profile: "paper-rest-ioc-v1", operating_daily_usd: "",
    })),
  };
}

function accountStatus(a: Account, globalPause: boolean, unavailable: boolean): string {
  if (unavailable) return "Worker unavailable";
  if (a.fault) return "Processing stopped";
  if (a.failure_pending) return "Failed; retained";
  if (a.drawdown_pause) return "Hard loss stop";
  if (a.entries_paused) return "Account entries paused";
  if (globalPause) return "Global entries paused";
  if (!a.valuation_fresh) return "Holding marks unavailable";
  return a.risk?.blocked ? "Entries blocked" : "Scanning";
}

export function PaperCampaignPanel({ data, unavailable }: {
  data: PaperSnapshot; unavailable: boolean;
}) {
  const [draft, setDraft] = useState(loadDraft);
  const [selected, setSelected] = useState("");
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const campaign = data.campaigns?.[0];
  const names = campaign?.accounts ?? [];
  const name = names.includes(selected) ? selected : names[0];
  const account = data.accounts[name];
  const mark = data.economics?.accounts[name];
  useEffect(() => {
    try { localStorage.setItem(draftKey, JSON.stringify(draft)); } catch { /* Server is authoritative. */ }
  }, [draft]);

  function edit(index: number, field: keyof DraftAccount, value: string) {
    setDraft(d => ({ ...d, accounts: d.accounts.map((a, i) =>
      i === index ? { ...a, [field]: value } as DraftAccount : a) }));
  }

  async function post(url: string, body: unknown) {
    const response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" },
      body: JSON.stringify(body), signal: AbortSignal.timeout(7000),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      if (url.endsWith("/campaigns") && (response.status === 409 || response.status === 422)) {
        setDraft(d => ({ ...d, attempted: false }));
      }
      throw new Error(typeof detail.detail === "string" ? detail.detail :
        "Check the distinct account names, balances and cost assumptions, then try again.");
    }
  }

  async function launch(event: FormEvent) {
    event.preventDefault();
    setPending(true); setError(null); setNotice(null);
    const frozen = { ...draft, attempted: true };
    // Save before dispatch: a lost acknowledgment/reload reuses the exact request.
    setDraft(frozen);
    try {
      localStorage.setItem(draftKey, JSON.stringify(frozen));
      await post("/api/paper/campaigns", {
        request_id: draft.request_id, name: draft.name,
        accounts: draft.accounts.map(a => ({ ...a, operating_daily_usd: a.operating_daily_usd.trim() || null })),
      });
      setNotice("Campaign saved. The account overview updates automatically.");
    } catch (e) {
      setError(e instanceof Error ? `${e.message} Retry the same launch to confirm its result.` :
        "Launch not confirmed. Retry the same launch; no second funding request is created.");
    } finally { setPending(false); }
  }

  async function control(action: "pause" | "resume" | "recover" | "resume_hard_stop") {
    if (!account) return;
    setPending(true); setError(null); setNotice(null);
    try {
      const risk = action === "resume_hard_stop";
      await post(`/api/paper/accounts/${encodeURIComponent(name)}/${risk ? "risk-control" : "control"}`,
        risk ? { action, stop_id: account.risk?.stop_id } :
          { action, expected_version: account.control_version ?? 0 });
      setNotice(`${account.label ?? name}: control saved. Waiting for refreshed status.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Control not confirmed; refresh before retrying.");
    } finally { setPending(false); }
  }

  return <section className="campaign-panel" aria-label="Paper campaigns">
    <div className="economics-heading"><div><p className="eyebrow">SEPARATE PAPER ACCOUNTS · LIMIT 20 TOTAL</p>
      <h3>{campaign ? campaign.name : "Launch a paper campaign"}</h3></div>
      <span className="pill">Paper only · cash only</span></div>
    <p>Each account uses the same BTC/ETH observations with its own money, orders, fees and loss limits.
      Matching copies test capacity; they are correlated comparisons, not independent discoveries.
      Returns cannot be added into a combined portfolio.</p>
    {unavailable && <p className="error-banner" role="alert">Paper worker unavailable or stale. Controls wait for fresh status; retained balances are not current marks.</p>}
    {error && <p className="error-banner" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!campaign ? <form onSubmit={e => void launch(e)}>
      <fieldset disabled={pending || draft.attempted || unavailable}>
        <label>Campaign name<input value={draft.name} required maxLength={60}
          onChange={e => setDraft(d => ({ ...d, name: e.target.value }))} /></label>
        <label>Campaign size<select value={draft.accounts.length} onChange={e => {
          const count = Number(e.target.value);
          setDraft(d => ({ ...d, accounts: Array.from({length: count}, (_, i) => d.accounts[i] ?? {
            label: `${strategies[i % 3].replace("-v1", "")} ${Math.floor(i / 3) + 1}`,
            starting_cash: "100", strategy: strategies[i % 3],
            execution_profile: "paper-rest-ioc-v1", operating_daily_usd: "",
          }) }));
        }}><option value={10}>10 campaign accounts</option><option value={14}>14 campaign + 6 retained = 20 total</option></select></label>
        <div className="campaign-setup">
          {draft.accounts.map((a, i) => <fieldset key={i} className="campaign-draft-account">
            <legend>Account {i + 1}</legend>
            <label>Account name<input aria-label={`Account ${i + 1} name`} required maxLength={40}
              value={a.label} onChange={e => edit(i, "label", e.target.value)} /></label>
            <label>Hypothetical starting balance<select aria-label={`Account ${i + 1} starting balance`}
              value={a.starting_cash} onChange={e => edit(i, "starting_cash", e.target.value)}>
              <option value="50">$50</option><option value="100">$100</option></select></label>
            <label>Frozen strategy<select aria-label={`Account ${i + 1} strategy`} value={a.strategy}
              onChange={e => edit(i, "strategy", e.target.value)}>
              {strategies.map(v => <option key={v}>{v}</option>)}</select></label>
            <label>Execution scenario<select aria-label={`Account ${i + 1} execution scenario`}
              value={a.execution_profile} onChange={e => edit(i, "execution_profile", e.target.value)}>
              {(data.execution_profiles ?? []).map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select></label>
            <label>Estimated operating USD/day<input aria-label={`Account ${i + 1} operating cost`}
              inputMode="decimal" placeholder="Unknown" pattern="[0-9]{1,4}(\.[0-9]{1,6})?"
              value={a.operating_daily_usd} onChange={e => edit(i, "operating_daily_usd", e.target.value)} /></label>
          </fieldset>)}
        </div>
      </fieldset>
      <p className="fine-print">Blank operating cost means unknown; enter 0 only for a declared zero-cost scenario.
        Funding and strategy/cost assumptions are frozen at launch. Hard loss stops cannot add funds or reset losses.
        One campaign and the original accounts remain retained. The total limit is twenty, including exploratory accounts; a larger campaign uses those available places.</p>
      {draft.attempted && <p role="status">This launch is saved for retry. Its configuration stays fixed until the server confirms the outcome.</p>}
      {draft.attempted && <button type="button" disabled={pending || unavailable} onClick={() =>
        setDraft(d => ({...d,request_id:crypto.randomUUID(),attempted:false}))}>Edit a new campaign request</button>}
      <button className="button secondary" type="submit" disabled={pending || unavailable}>
        {pending ? "Confirming launch…" : draft.attempted ? "Retry same campaign launch" : draft.accounts.length === 14 ? "Launch fourteen paper accounts" : "Launch ten paper accounts"}
      </button>
    </form> : <>
      <p className="fine-print">{names.length} accounts · frozen strategies and costs · hard loss stops · no top-ups.
        The global entry control above applies to every paper account. Clearing an account pause cannot clear a global pause or a hard stop.</p>
      <div className="table-scroll"><table className="market-table campaign-table" aria-label="Campaign account overview">
        <thead><tr><th>Account / strategy</th><th>Starting / funded</th><th>Equity / net trading</th>
          <th>Cash / reserved</th><th>Fees</th><th>State</th></tr></thead>
        <tbody>{names.map(n => {
          const a = data.accounts[n], m = data.economics?.accounts[n];
          if (!a) return <tr key={n}><td colSpan={6}>Account state unavailable; refresh.</td></tr>;
          return <tr key={n} aria-selected={n === name}>
            <td><button className="button secondary small" type="button" onClick={() => {
              setSelected(n); setError(null); setNotice(null);
            }}>{a.label ?? n}</button><small>{a.version}</small></td>
            <td>{money(a.starting_capital)}<small>{money(a.funding)} lifetime funding</small></td>
            <td>{!unavailable && a.valuation_fresh ? money(a.equity) : "Mark unavailable"}
              <small>{!unavailable ? money(m?.net_pnl) : "Unconfirmed"} net trading</small></td>
            <td>{money(m?.available_cash)}<small>{money(m?.reserved)} reserved</small></td>
            <td>{money(a.fees)}</td><td>{accountStatus(a, data.paused, unavailable)}</td>
          </tr>;
        })}</tbody></table></div>
      {account && <article className="campaign-inspector" aria-label="Selected campaign account">
        <h4>{account.label ?? name} — account details</h4>
        <p role="status">{account.fault?.reason ?? account.risk?.reason ?? "Waiting for account risk status."}</p>
        <p>{accountStatus(account, data.paused, unavailable)} · {account.closed} closed trades ·
          {money(account.funding)} retained funding · {(Number(account.max_drawdown) * 100).toFixed(2)}% maximum drawdown.</p>
        <p>Execution: {data.execution_profiles?.find(p => p.id === mark?.execution_profile)?.label ?? "Unavailable"} ·
          estimated operating cost: {mark?.operating_daily_usd == null ? "unknown" : `${money(mark.operating_daily_usd)}/day`}.</p>
        <div className="campaign-actions">
          <button className="button secondary small" disabled={pending || unavailable}
            onClick={() => void control(account.entries_paused ? "resume" : "pause")}>
            {account.entries_paused ? "Clear account entry pause" : "Pause this account's entries"}</button>
          {account.fault && <button className="button secondary small" disabled={pending || unavailable}
            onClick={() => void control("recover")}>Retry account processing</button>}
          {account.drawdown_pause && <button className="button secondary small"
            disabled={pending || unavailable || !account.risk?.recoverable}
            onClick={() => void control("resume_hard_stop")}>Resume within existing loss limit</button>}
        </div>
        {account.drawdown_pause && <p>{account.risk?.recovery_reason ?? "Recovery retains the original loss limit."}</p>}
        <PaperCampaignJournal key={name} account={name} />
        <h5>Holdings and reserved orders</h5>
        {!Object.keys(account.positions).length && !Object.keys(account.pending).length ? <p>No holdings or reserved orders.</p> : <>
          {Object.entries(account.positions).map(([s, p]) => <p key={s}>{s}: {p.quantity} owned ·
            entry {money(p.entry)} · stop {money(p.stop)}{p.exit_blocked && ` · ${p.exit_blocked}`}</p>)}
          {Object.entries(account.pending).map(([s, o]) => <p key={s}>{s}: {o.side} {o.quantity} pending.</p>)}
        </>}
        <h5>Latest decisions</h5>
        {Object.keys(account.last_decision).length ? Object.entries(account.last_decision).map(([s, d]) =>
          <p key={s}>{s}: {d.reason}</p>) : <p>Waiting for fresh eligible closed-bar observations.</p>}
        <p className="fine-print">Whole-account economics below includes every campaign account.
          Accounts launched during a window enter comparisons at the next full common window.
          Trading P&amp;L above includes execution costs; estimated operating costs are shown separately in that comparison.</p>
      </article>}
    </>}
  </section>;
}
