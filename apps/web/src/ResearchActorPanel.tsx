import { useEffect, useState, type FormEvent } from "react";

type Grant = { id: string; actor: string; expires: number; revoked: number; output_limit: number; request_limit: number; output_used: number; requests_used: number; scope: { tasks: string[]; processing_location: string } };
type State = { grants: Grant[]; transport: string; data_scope: string; allowance: string; maintenance: string };

export function ResearchActorPanel({ selectedTask }: { selectedTask: string | null }) {
  const [state, setState] = useState<State | null>(null);
  const [actor, setActor] = useState("");
  const [location, setLocation] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await fetch("/api/research/actors/grants", { headers: { "X-Local-Operator": "1" }, cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(6000)]) });
        if (!response.ok) throw new Error("Scoped collaborator status is unavailable. Retry when connected.");
        const value = await response.json() as State;
        if (live) { setState(value); setError(null); }
      } catch (cause) { if (live) setError(cause instanceof Error ? cause.message : "Collaborator status unavailable"); }
      finally { if (live) timer = setTimeout(() => void poll(), 10000); }
    };
    void poll();
    return () => { live = false; controller.abort(); clearTimeout(timer); };
  }, [refresh]);
  const grant = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedTask) return;
    setBusy(true); setError(null); setSecret(null);
    try {
      const response = await fetch("/api/research/actors/grants", { method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" }, body: JSON.stringify({ actor, tasks: [selectedTask], processing_location: location }), signal: AbortSignal.timeout(6000) });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail ?? "Credential could not be issued.");
      setSecret(value.token as string); setRefresh(r => r + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Credential acknowledgment unknown; inspect grants before creating another."); }
    finally { setBusy(false); }
  };
  const revoke = async (identity: string) => {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/research/actors/grants/${encodeURIComponent(identity)}/revoke`, { method: "POST", headers: { "X-Local-Operator": "1" }, signal: AbortSignal.timeout(6000) });
      if (!response.ok) throw new Error("Revocation acknowledgment unavailable; retry or inspect actual status.");
      setSecret(null); setRefresh(r => r + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Revocation unavailable"); }
    finally { setBusy(false); }
  };
  return <section aria-labelledby="collaboration-title" className="research-collaboration">
    <h3 id="collaboration-title">Scoped research collaboration</h3>
    <p>{state?.transport ?? "Loading actual collaborator configuration…"}</p>
    <p>{state?.data_scope}</p><p>{state?.allowance}</p><p>{state?.maintenance}</p>
    {error && <p role="alert">{error} <button type="button" onClick={() => setRefresh(r => r + 1)}>Retry collaborator status</button></p>}
    <details><summary>Issue a limited credential for the selected saved task</summary>
      <p>Declare where a collaborator will process the permitted packet. Issuing access does not start a worker, open a bridge, enable local inference or grant paper funding. An authorized transport must expose only this scoped interface.</p>
      <form onSubmit={e => void grant(e)}>
        <label>Collaborator name <input required pattern="[A-Za-z0-9_-]{3,60}" value={actor} onChange={e => setActor(e.target.value)} /></label>
        <label>Processing location <input required minLength={3} maxLength={150} value={location} onChange={e => setLocation(e.target.value)} /></label>
        <p>Selected task: {selectedTask ?? "Open a saved question first"}. Access lasts one hour, with 20 requests and 65,536 output bytes.</p>
        <button type="submit" disabled={busy || !selectedTask}>Issue scoped credential</button>
      </form>
      {secret && <div><label>Credential shown once <input readOnly type="password" value={secret} autoComplete="off" /></label><p>Copy directly into the authorized worker's private configuration. It is not saved in browser storage or returned by later status reads.</p><button type="button" onClick={() => setSecret(null)}>Dismiss credential</button></div>}
    </details>
    <ul>{state?.grants.map(g => <li key={g.id}><strong>{g.actor}</strong> · {g.revoked ? "Revoked" : g.expires * 1000 <= Date.now() ? "Expired" : "Access granted"} · expires {new Date(g.expires * 1000).toLocaleString()}<p>Processing location: {g.scope.processing_location}. Task scope: {g.scope.tasks.join(", ")}. Requests {g.requests_used}/{g.request_limit}; output {g.output_used}/{g.output_limit} bytes.</p>{!g.revoked && <button type="button" disabled={busy} onClick={() => void revoke(g.id)}>Revoke {g.actor}</button>}</li>)}</ul>
    {state?.grants.length === 0 && <p>No scoped collaborators have been granted access in this registry.</p>}
  </section>;
}
