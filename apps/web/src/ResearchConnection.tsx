import { useState } from "react";
import { researchControlLock } from "./researchControls";

type Review = { review_identity: string; methods: string[]; markets: string[]; model: string; duration: string; hourly_tokens: number; hourly_wall_seconds: number; timeout_seconds: number };
const connectionKey = "qtrades:paper:model-connection";

export function ResearchConnection({ onSaved }: { onSaved: () => void }) {
  const [directory, setDirectory] = useState(() => localStorage.getItem(connectionKey) ?? "");
  const [review, setReview] = useState<Review | null>(null);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const request = async (save: boolean) => {
    if (!directory.trim() || busy || save && (!review || !approved)) return;
    if (!navigator.locks) { setMessage("Use a local browser that can coordinate settings between windows."); return; }
    await navigator.locks.request(researchControlLock, { ifAvailable: true }, async lock => {
      if (!lock) { setMessage("Another window is saving research settings. Refresh before retrying."); return; }
      setBusy(true); setMessage(null); localStorage.setItem(connectionKey, directory);
      try {
        const response = await fetch(`/api/research/model-connection${save ? "" : "/review"}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" }, body: JSON.stringify(save ? { development_directory: directory.trim(), review_identity: review!.review_identity, approve_recurring_scope: approved } : { development_directory: directory.trim() }), signal: AbortSignal.timeout(10000) });
        const value = await response.json();
        if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "The existing profile could not be verified.");
        if (save) {
          setMessage(value.enabled === false
            ? "The reviewed connection and permission are saved paused. Restart the application to load its existing model owner, then return here to review startup."
            : value.enabled === true
              ? "This configuration was already saved, and its saved research intent is enabled. Refresh Overview to see whether its model owner is active, waiting, or requires a restart."
              : "Configuration was acknowledged. Refresh Overview to reconcile the saved permission and current model owner before another action.");
          onSaved();
        }
        else { setReview(value as Review); setApproved(false); }
      } catch (cause) { setMessage(cause instanceof Error ? cause.message : "Configuration acknowledgment is unknown. Refresh saved setup before another action."); onSaved(); }
      finally { setBusy(false); }
    });
  };
  return <form className="research-connection" onSubmit={event => { event.preventDefault(); void request(false); }} aria-label="Connect a reviewed local research model">
    <p>Connect an existing verified trained-model profile. Setup reads its retained declarations and keeps the existing model loader and resource limits. No model is downloaded or called here.</p>
    <label>Local profile folder<input required value={directory} disabled={busy} onChange={event => { setDirectory(event.target.value); setReview(null); setApproved(false); }} placeholder="Folder containing the saved training and serving declarations" /></label>
    <button type="submit" disabled={busy || !directory.trim()}>Review existing profile</button>
    {review && <div className="startup-review"><h4>New paper research permission</h4><p>{review.model} · experimental and unqualified · {review.markets.join(", ")} · {review.methods.join(" and ")}, each compared with cost breakout.</p><p>{review.duration}. One model request at a time; {review.hourly_tokens.toLocaleString()} reserved tokens and {review.hourly_wall_seconds / 60} allocated minutes per UTC hour, up to {review.timeout_seconds / 60} minutes per request. Independent source selection remains bounded by the existing policy. Model and electricity cost is unknown.</p><p>This is a new explicit recurring paper scope. It cannot replace an existing permission, renew an expired finite grant, change capital or strategy rules, or authorize live execution.</p><label className="review-choice"><input type="checkbox" checked={approved} disabled={busy} onChange={event => setApproved(event.target.checked)} /> Approve this reviewed recurring scope and save its connection paused.</label><button type="button" disabled={busy || !approved} onClick={() => void request(true)}>{busy ? "Confirming saved configuration…" : "Save reviewed paper configuration"}</button></div>}
    {message && <p role="status">{message}</p>}
  </form>;
}
