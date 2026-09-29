import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

type Installation = {
  running_commit: string | null;
  running_source_dirty: boolean | null;
  running_source_kind: string;
  main_commit: string | null;
  checked_at: number | null;
  phase: string;
  same_commit: boolean;
  message: string;
  activation: string;
  activation_phase: string;
  last_activation_verified_at: number | null;
  active_release_matches: boolean;
  automatic_activation: boolean;
};

const short = (commit: string | null) => commit?.slice(0, 12) ?? "Not identified";

export function InstallationPanel({ disconnected }: { disconnected: boolean }) {
  const [data, setData] = useState<Installation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [retryAt, setRetryAt] = useState(0);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    async function read() {
      try {
        const response = await fetch("/api/installation", {
          cache: "no-store",
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]),
        });
        if (!response.ok) throw new Error();
        const result = (await response.json()) as Installation;
        if (active) { setData(result); setReadError(null); }
      } catch {
        if (active) setReadError("Version status unavailable. Last displayed details may be stale.");
      }
    }
    void read();
    const timer = setInterval(() => { setNow(Date.now()); void read(); }, 15000);
    return () => { active = false; controller.abort(); clearInterval(timer); };
  }, []);

  async function check() {
    setChecking(true);
    setError(null);
    setRetryAt(Date.now() + 30000);
    try {
      const response = await fetch("/api/installation/check", {
        method: "POST",
        headers: { "X-Local-Operator": "1" },
        signal: AbortSignal.timeout(60000),
      });
      if (!response.ok) throw new Error();
      setData((await response.json()) as Installation);
    } catch {
      setError("Main check was not confirmed. Your running application was not updated. Retry after the cooldown.");
    } finally {
      setChecking(false);
      setNow(Date.now());
    }
  }

  const busy = checking || data?.phase === "preparing";
  return (
    <section className="panel installation-panel" id="installation" aria-label="Local application updates">
      <div className="section-heading">
        <div>
          <p className="eyebrow">GITHUB MAIN → LOCAL APPLICATION</p>
          <h2>Code version &amp; updates</h2>
        </div>
        <button className="button secondary small" onClick={() => void check()}
          disabled={busy || disconnected || now < retryAt}>
          <RefreshCw size={14} /> {checking ? "Checking main…" : "Check GitHub main"}
        </button>
      </div>
      {(error || readError || disconnected) && <p className="error-banner" role="alert">
        {disconnected ? "Dashboard disconnected. Version details may be stale." : error || readError}
      </p>}
      <dl className="installation-values">
        <div><dt>Source at process startup</dt><dd>{short(data?.running_commit ?? null)}
          {data?.running_source_dirty ? " · Local changes present" : ""}</dd></div>
        <div><dt>Last checked main</dt><dd>{short(data?.main_commit ?? null)}</dd></div>
        <div><dt>Last GitHub check</dt><dd>{data?.checked_at
          ? new Date(data.checked_at * 1000).toLocaleString("en-US", { timeZone: "America/Denver" }) + " Denver" : "Not checked"}</dd></div>
        <div><dt>Installation status</dt><dd>{data?.activation_phase?.replaceAll("_", " ") ?? "Not activated"}</dd></div>
        <div><dt>Last verified installation</dt><dd>{data?.last_activation_verified_at
          ? new Date(data.last_activation_verified_at * 1000).toLocaleString("en-US", { timeZone: "America/Denver" }) + " Denver" : "Not verified"}</dd></div>
        <div><dt>Automatic installation</dt><dd>Not enabled</dd></div>
      </dl>
      <p>{data?.message ?? "Loading local version information…"}</p>
      {data?.same_commit && <p>Startup code matches the last checked commit. This is not a fresh GitHub or account-health check.</p>}
      <p className="fine-print">A check never installs code or restarts trading. Preparation builds a separate release;
        installation requires the explicit local activate command. Failed or interrupted updates use recover, never a database reset. Current account reconciliation is shown with the paper accounts.</p>
      {data?.activation_phase === "recovery_required" && <p className="error-banner" role="alert">
        The last update needs recovery. Preserve the local data and run the local recover command; do not reinstall or reset accounts.
      </p>}
      {(busy || now < retryAt) && <p className="fine-print">
        {busy ? "One update operation at a time; paper trading continues independently." : "Checks have a 30-second cooldown."}
      </p>}
    </section>
  );
}
