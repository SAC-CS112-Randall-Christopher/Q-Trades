import { useEffect, useRef, useState } from "react";
import type { Account } from "./PaperPanel";

const originalAccounts = new Set([
  "primary", "breakout-v1", "responsive-v1", "selective-v1",
  "universe-control-v1", "universe-wide-v1",
]);
const catalogVersion = "original-account-redesign-v1";

export function isOriginalAccount(name: string): boolean {
  return originalAccounts.has(name);
}

type Strategy = {
  id: string;
  label: string;
  hypothesis: string;
  feature_seconds: number;
  maximum_hold_seconds: number;
  progress_seconds: number;
  limitations: string;
};
type Catalog = { version: string; strategies: Strategy[] };
type Command = {
  request_id: string;
  strategy: string;
  expected_strategy: string;
  expected_control_version: number;
};
type Receipt = Command & { account: string; from: string; to: string; version: number };
type Saved = { command: Command | null; error: string | null };
const storageKey = (name: string) => `qtrades-original-strategy-pending-v1:${name}`;

async function withPendingLock<T>(name: string, work: () => T): Promise<T> {
  if (!navigator.locks) throw new Error("This window cannot coordinate saved requests. No new change can be sent.");
  return navigator.locks.request(storageKey(name), { ifAvailable: true }, lock => {
    if (!lock) throw new Error("Another window is updating this saved request. Reopen its result before continuing.");
    return work();
  });
}

async function clearPending(name: string, command: Command): Promise<void> {
  await withPendingLock(name, () => {
    const stored = localStorage.getItem(storageKey(name));
    if (stored === null) return;
    if (stored !== JSON.stringify(command)) {
      throw new Error("Saved recovery state changed in another window. Its request is retained; reopen that result.");
    }
    localStorage.removeItem(storageKey(name));
  });
}

function savedCommand(name: string): Saved {
  try {
    const text = localStorage.getItem(storageKey(name));
    if (text === null) return { command: null, error: null };
    const value = JSON.parse(text) as Command;
    if (!value || typeof value.request_id !== "string" ||
        !/^[a-f0-9-]{36}$/.test(value.request_id) ||
        typeof value.strategy !== "string" || !value.strategy ||
        typeof value.expected_strategy !== "string" || !value.expected_strategy ||
        !Number.isSafeInteger(value.expected_control_version) || value.expected_control_version < 0) {
      throw new Error("Invalid saved strategy request");
    }
    return { command: value, error: null };
  } catch {
    return { command: null, error: "A saved strategy request could not be read. Its outcome must be reconciled before another change." };
  }
}

function matchesReceipt(value: Record<string, unknown>, name: string, command: Command): boolean {
  return ["applied", "already_applied"].includes(String(value.status)) &&
    value.account === name && value.request_id === command.request_id &&
    value.strategy === command.strategy && value.to === command.strategy &&
    value.from === command.expected_strategy && value.expected_strategy === command.expected_strategy &&
    value.expected_control_version === command.expected_control_version &&
    Number.isSafeInteger(value.version) && value.version === command.expected_control_version + 1;
}

function validCatalog(value: Catalog): boolean {
  return value?.version === catalogVersion && Array.isArray(value.strategies) &&
    value.strategies.length === 8 &&
    value.strategies.every(row => row && typeof row.id === "string" &&
      /^[a-z-]+-v1$/.test(row.id) && typeof row.label === "string" && !!row.label &&
      typeof row.hypothesis === "string" && typeof row.limitations === "string" &&
      row.feature_seconds === 300 && row.maximum_hold_seconds === 21600 && row.progress_seconds === 7200) &&
    new Set(value.strategies.map(row => row.id)).size === 8;
}

export function OriginalStrategyPanel({ name, account, unavailable }: {
  name: string;
  account: Account;
  unavailable: boolean;
}) {
  const [initial] = useState(() => savedCommand(name));
  const [command, setCommand] = useState<Command | null>(initial.command);
  const [storageError, setStorageError] = useState<string | null>(initial.error);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [selected, setSelected] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rejectedSnapshot, setRejectedSnapshot] = useState<Account | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    async function loadCatalog() {
      try {
        const response = await fetch("/api/paper/strategies", {
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(7000)]),
        });
        if (!response.ok) throw new Error("The strategy choices are unavailable.");
        const value = await response.json() as Catalog;
        if (!validCatalog(value)) throw new Error("The strategy catalog does not match this reviewed version.");
        if (!controller.signal.aborted) { setCatalog(value); setCatalogError(null); }
      } catch (failure) {
        if (!controller.signal.aborted) setCatalogError(failure instanceof Error
          ? failure.message : "The strategy choices are unavailable.");
      }
    }
    void loadCatalog();
    const reconcileStorage = (event: StorageEvent) => {
      if (event.key !== storageKey(name)) return;
      const saved = savedCommand(name);
      if (saved.error) setStorageError(saved.error);
      if (saved.command) {
        setCommand(saved.command); setReceipt(null);
        setNotice("A strategy request was saved in another window. Reopen its exact result before another change.");
      }
    };
    window.addEventListener("storage", reconcileStorage);
    return () => {
      mounted.current = false; controller.abort();
      window.removeEventListener("storage", reconcileStorage);
    };
  }, [name]);

  useEffect(() => {
    if (!command || !receipt || unavailable || account.version !== receipt.to ||
        (account.control_version ?? 0) < receipt.version) return;
    let cancelled = false;
    async function confirm() {
      try {
        await clearPending(name, command!);
        if (cancelled) return;
        setCommand(null); setStorageError(null); setError(null); setSelected("");
        setNotice("The new strategy is confirmed in this account. All earlier losses and funding remain in its history.");
      } catch (failure) {
        if (!cancelled) setStorageError(failure instanceof Error ? failure.message
          : "The confirmed request could not be cleared from saved recovery state. Keep its result open before another change.");
      }
    }
    void confirm();
    return () => { cancelled = true; };
  }, [account.version, account.control_version, command, name, receipt, unavailable]);

  const holding = Object.keys(account.positions).length > 0 || Object.keys(account.pending).length > 0;
  const blocked = unavailable || !account.valuation_fresh || !!account.fault || holding ||
    busy || !!command || !!storageError || !catalog || !navigator.locks || account === rejectedSnapshot;
  const chosen = catalog?.strategies.find(strategy => strategy.id === selected);

  async function send() {
    if (blocked || inFlight.current || !chosen || selected === account.version) return;
    const next: Command = { request_id: crypto.randomUUID(), strategy: selected,
      expected_strategy: account.version, expected_control_version: account.control_version ?? 0 };
    inFlight.current = true; setBusy(true);
    try {
      await withPendingLock(name, () => {
        if (localStorage.getItem(storageKey(name)) !== null) {
          throw new Error("Another saved request is awaiting its result. No new change was sent.");
        }
        localStorage.setItem(storageKey(name), JSON.stringify(next));
      });
    } catch (failure) {
      if (mounted.current) {
        setStorageError(failure instanceof Error ? failure.message : "The request could not be saved for recovery. No change was sent.");
        setBusy(false);
      }
      inFlight.current = false;
      return;
    }
    if (mounted.current) {
      setCommand(next); setReceipt(null); setError(null); setNotice(null);
    }
    try {
      const response = await fetch(`/api/paper/accounts/${encodeURIComponent(name)}/strategy`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-Local-Operator": "1" },
        body: JSON.stringify(next), signal: AbortSignal.timeout(20000),
      });
      const value = await response.json() as Record<string, unknown>;
      if (!response.ok) {
        const reason = typeof value.detail === "string" ? value.detail : "The strategy change was not confirmed.";
        if ([403, 409, 422].includes(response.status)) {
          // These route refusals occur before the submitted change commits.
          // Preserve the known refusal; another request still needs fresh status.
          if (mounted.current) {
            setNotice(`Request ${next.request_id} was rejected (${response.status}): ${reason}`);
            setRejectedSnapshot(account);
          }
          try {
            await clearPending(name, next);
            if (mounted.current) { setCommand(null); setError(reason); }
          } catch (failure) {
            if (mounted.current) setStorageError(failure instanceof Error ? failure.message
              : "The saved request could not be cleared. Its recovery record is retained.");
          }
          return;
        }
        throw new Error(reason);
      }
      if (!matchesReceipt(value, name, next)) throw new Error("The acknowledgment does not identify this exact saved change.");
      if (mounted.current) {
        setReceipt({ ...next, account: name, from: String(value.from), to: String(value.to), version: Number(value.version) });
        setNotice("Change acknowledged. Waiting for the refreshed account to confirm its new strategy.");
      }
    } catch (failure) {
      if (mounted.current) setError(`${failure instanceof Error ? failure.message : "The change was not confirmed."} The original request is retained. Reopen its result; no repeat change is sent.`);
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function reconcile() {
    if (!command || inFlight.current || busy) return;
    inFlight.current = true; setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/paper/accounts/${encodeURIComponent(name)}/strategy/${encodeURIComponent(command.request_id)}`, {
        signal: AbortSignal.timeout(7000),
      });
      if (response.status === 404) {
        if (mounted.current) setError("No retained result was found for this request. Its outcome remains unknown; no repeat change is sent.");
        return;
      }
      const value = await response.json() as Record<string, unknown>;
      if (!response.ok || !matchesReceipt(value, name, command)) {
        throw new Error("The exact saved result could not be verified. Its outcome remains unknown.");
      }
      if (mounted.current) {
        setReceipt({ ...command, account: name, from: String(value.from), to: String(value.to), version: Number(value.version) });
        setNotice("The retained change is verified. Waiting for fresh account status to confirm its strategy.");
      }
    } catch (failure) {
      if (mounted.current) setError(failure instanceof Error ? failure.message : "The retained result is unavailable.");
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return <details className="economics-settings">
    <summary>Choose this account's next strategy</summary>
    <p>A change applies to future entries only, when this account has no holdings or pending orders.
      Funding, previous losses, fees, cash-only limits and entry pauses stay with this account.</p>
    <p className="fine-print">These eight hypotheses use complete five-minute observations, a six-hour maximum hold and a two-hour progress check.
      Protective stops still act immediately on available executable observations.
      The movement-versus-cost check is a volatility proxy, not a return forecast or evidence of profitability.</p>
    <label>Next strategy<select value={selected} disabled={blocked} onChange={event => setSelected(event.target.value)}>
      <option value="">Choose a strategy…</option>
      {catalog?.strategies.map(strategy => <option key={strategy.id} value={strategy.id}>
        {strategy.label}{strategy.id === account.version ? " · current" : ""}</option>)}
    </select></label>
    {chosen && <><p>{chosen.hypothesis}</p><p className="fine-print">{chosen.limitations}</p></>}
    {holding && <p>Wait for the account's existing positions and orders to close before changing its strategy.</p>}
    {!navigator.locks && <p role="alert">This window cannot coordinate saved requests. Use a supported application window before changing strategies.</p>}
    {account === rejectedSnapshot && <p>Wait for refreshed account status before another explicit change.</p>}
    <button type="button" className="button secondary small" disabled={blocked || !chosen || selected === account.version}
      onClick={() => void send()}>{busy ? "Waiting for result…" : "Use selected strategy for future entries"}</button>
    {command && <>
      <p role="status">Saved request {command.request_id}: {command.expected_strategy} → {command.strategy}.</p>
      <button type="button" className="button secondary small" disabled={busy} onClick={() => void reconcile()}>
        Reopen saved strategy result</button>
    </>}
    {receipt && <p className="fine-print">Verified change: {receipt.from} → {receipt.to}, account control version {receipt.version}.</p>}
    {(storageError || error || catalogError) && <p className="error-banner" role="alert">{storageError ?? error ?? catalogError}</p>}
    {notice && <p role="status">{notice}</p>}
  </details>;
}
