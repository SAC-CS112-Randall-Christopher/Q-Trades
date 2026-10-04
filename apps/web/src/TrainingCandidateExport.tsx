import { useEffect, useRef, useState } from "react";

type Props = {
  task: string;
  stage: string;
  attempt: number;
  completed: boolean;
};

export function TrainingCandidateExport({
  task,
  stage,
  attempt,
  completed,
}: Props) {
  const request = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => () => request.current?.abort(), []);
  const download = async () => {
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const response = await fetch(
        `/api/lab/roles/tasks/${encodeURIComponent(task)}/training-candidate?stage=${encodeURIComponent(stage)}&attempt=${attempt}`,
        {
          headers: { "X-Local-Operator": "1" },
          cache: "no-store",
          signal: AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(10000),
          ]),
        },
      );
      if (!response.ok)
        throw new Error(
          "The original attempt could not be exported. It remains saved; retry when available.",
        );
      const value = await response.json();
      if (
        !value.candidate?.candidate_sha256 ||
        value.review !== null ||
        value.target !== null
      ) {
        throw new Error(
          "The export was incomplete. No training data was accepted.",
        );
      }
      if (controller.signal.aborted) return;
      const blob = new Blob([JSON.stringify(value, null, 2) + "\n"], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `qtrades-candidate-${stage}-${attempt}-${value.candidate.candidate_sha256.slice(0, 12)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      if (!controller.signal.aborted) setSaved(true);
    } catch (cause) {
      if (!controller.signal.aborted)
        setError(
          cause instanceof Error
            ? cause.message
            : "Export failed. Retry the retained attempt.",
        );
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };
  return (
    <div className="training-candidate-export">
      <button
        type="button"
        disabled={!completed || busy}
        onClick={() => {
          setBusy(true);
          setError(null);
          void fetch("/api/lab/training/candidates", {
            method: "POST",
            headers: {
              "X-Local-Operator": "1",
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              kind: "model_attempt",
              identity: task,
              stage,
              attempt,
            }),
            signal: AbortSignal.timeout(10000),
          })
            .then(async (response) => {
              const value = await response.json();
              if (!response.ok)
                throw new Error(
                  value.detail || "Retained attempt unavailable; retry.",
                );
              location.hash = `teaching:${value.id}`;
            })
            .catch((cause) =>
              setError(
                cause instanceof Error
                  ? cause.message
                  : "Review could not open.",
              ),
            )
            .finally(() => setBusy(false));
        }}
      >
        Review teaching example
      </button>
      <button
        type="button"
        disabled={!completed || busy}
        onClick={() => void download()}
      >
        {busy
          ? "Preparing private candidate…"
          : error
            ? "Retry candidate export"
            : "Export training candidate"}
      </button>
      {!completed && (
        <p>
          A completed, retained answer is required. A pending call is not
          training evidence.
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {saved && (
        <p role="status">
          Unreviewed candidate prepared for download. Save privately in your
          research storage. Review the target, source timing, related
          experiments and data rights before training. The model has not
          changed.
        </p>
      )}
    </div>
  );
}
