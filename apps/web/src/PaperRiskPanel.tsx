import { useState } from "react";

export type RiskStatus = {
  policy: string;
  legacy: boolean;
  blocked: boolean;
  reason: string;
  valuation_issues: Record<string, string>;
  stop_id: number;
  recoverable: boolean;
  recovery_reason: string | null;
  last_recovery: { at: number; reason: string } | null;
  risk_reference: string;
  stop_equity: string;
};

type RiskAccount = { risk?: RiskStatus; drawdown_pause: boolean };

export function PaperRiskPanel({ accounts, unavailable }: {
  accounts: Record<string, RiskAccount>;
  unavailable: boolean;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function command(name: string, risk: RiskStatus, adopt: boolean) {
    if (adopt && !window.confirm(
      `Use hard loss stops and no automatic top-ups for ${name} from now on? ` +
      "Balances, past results and the existing risk reference will not be reset."
    )) return;
    setPending(name);
    setNotice(null);
    setError(null);
    try {
      const response = await fetch(`/api/paper/accounts/${encodeURIComponent(name)}/risk-control`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Local-Operator": "1" },
        body: JSON.stringify({ action: adopt ? "adopt_hard_stop" : "resume_hard_stop", stop_id: risk.stop_id }),
        signal: AbortSignal.timeout(7000),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(typeof detail.detail === "string" ? detail.detail : "Risk action was not confirmed.");
      }
      setNotice(`${name}: request saved. Account status refreshes automatically; no funds or loss budget were added.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Risk action was not confirmed. Refresh before retrying.");
    } finally {
      setPending(null);
    }
  }

  function row(name: string, a: RiskAccount) {
    const risk = a.risk;
    if (!risk) return <p key={name}>{name}: risk status unavailable. Refresh the application.</p>;
    return <article className="risk-account" key={name} aria-label={`${name} risk controls`}>
      <h4>{name === "primary" ? "Primary paper account" : name}</h4>
      <p><strong>{risk.legacy ? "Historical policy" : risk.policy === "cash-spot-hard-stop-v1" ? "Hard-stop policy" : "Unknown policy"}</strong>
        {risk.legacy ? " · Scheduled review and top-up rules are retained until you change this account." : " · No automatic top-ups or loss-limit resets."}</p>
      <p role="status">{unavailable ? "Paper worker unavailable or stale; wait for fresh status." : risk.reason}</p>
      <p className="fine-print">Risk reference ${Number(risk.risk_reference).toFixed(2)} ·
        35% stop at ${Number(risk.stop_equity).toFixed(2)}. Existing positions can still exit when their own data permits.</p>
      {Object.keys(risk.valuation_issues).length > 0 && <p>
        Cancelled buys are not replayed when data returns. A fresh eligible signal must reserve a new order.
      </p>}
      {a.drawdown_pause && !risk.legacy && <p className="fine-print">{risk.recovery_reason || "Current equity is above the unchanged loss limit; recovery is available."}</p>}
      {risk.last_recovery && <p className="fine-print">Last recovery: {new Date(risk.last_recovery.at * 1000).toLocaleString("en-US", { timeZone: "America/Denver" })} Denver · {risk.last_recovery.reason}</p>}
      {(risk.legacy || a.drawdown_pause) && <button className="button secondary small"
        disabled={pending !== null || unavailable || (!risk.legacy && !risk.recoverable)}
        onClick={() => void command(name, risk, risk.legacy)}>
        {pending === name ? "Saving…" : risk.legacy ? "Use hard-stop policy" : "Resume within existing loss limit"}
      </button>}
    </article>;
  }

  return <section className="paper-risk" aria-label="Paper risk and recovery">
    <h3>Risk &amp; recovery</h3>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {accounts.primary && row("primary", accounts.primary)}
    <details><summary>Risk status for comparison accounts</summary>
      {Object.entries(accounts).filter(([name]) => name !== "primary").map(([name, a]) => row(name, a))}
    </details>
  </section>;
}
