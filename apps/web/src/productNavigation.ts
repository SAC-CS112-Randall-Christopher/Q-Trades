import { useEffect, useState } from "react";

// Keep explicit paper/account/research context across the five destinations.
// Saved scanner/source URLs retain their full producer-issued parameters.
export function inContext(destination: string, overrides: Record<string, string | null> = {}) {
  const [base, query = ""] = destination.split("?");
  const next = new URLSearchParams(query);
  const current = new URLSearchParams(location.hash.split("?")[1] ?? "");
  for (const key of ["account", "symbol", "task", "trial"]) {
    if (!next.has(key) && current.has(key)) next.set(key, current.get(key)!);
  }
  Object.entries(overrides).forEach(([key, value]) => value === null ? next.delete(key) : next.set(key, value));
  return `${base}?${next.toString()}`;
}

export function useAccountScope(fallback = "") {
  const read = () => new URLSearchParams(location.hash.split("?")[1] ?? "").get("account") ?? fallback;
  const [account, setAccount] = useState(read);
  useEffect(() => {
    const restore = () => setAccount(read());
    window.addEventListener("hashchange", restore);
    window.addEventListener("popstate", restore);
    return () => {
      window.removeEventListener("hashchange", restore);
      window.removeEventListener("popstate", restore);
    };
  }, [fallback]);
  const select = (value: string) => {
    setAccount(value || fallback);
    location.hash = inContext(location.hash, { account: value || null, trial: null });
  };
  return [account, select] as const;
}
