import { useCallback, useEffect, useRef } from "react";

// Only the current selection may publish a response, error or loading state.
// Aborting a read does not undo server-side evidence disclosure or a saved receipt.
export function useEvidenceRead() {
  const current = useRef<{ generation: number; controller: AbortController | null }>({ generation: 0, controller: null });
  const cancel = useCallback(() => {
    current.current.generation++;
    current.current.controller?.abort();
    current.current.controller = null;
  }, []);
  const begin = useCallback((timeout: number) => {
    cancel();
    const controller = new AbortController();
    current.current.controller = controller;
    const generation = current.current.generation;
    return {
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(timeout)]),
      isCurrent: () => current.current.generation === generation && !controller.signal.aborted,
    };
  }, [cancel]);
  useEffect(() => cancel, [cancel]);
  return { begin, cancel };
}
