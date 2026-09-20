import { useState } from "react";

import { apiDelete } from "../lib/api.js";

/**
 * Two-step delete: the first click arms it, the second fires. There is no undo
 * on the backend, so the armed state spells out what is about to be wiped.
 */
export default function DeleteButton({ endpoint, label, target, onDeleted }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiDelete(endpoint);
      setResult(res);
      if (res.status === "ok") onDeleted?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      setArmed(false);
    }
  }

  if (busy) {
    return <span className="text-xs text-neutral-400">deleting {target}…</span>;
  }

  if (armed) {
    return (
      <span className="flex items-center gap-2 text-xs">
        <span className="text-neutral-300">Delete all {target}?</span>
        <button
          onClick={run}
          className="rounded bg-red-900 px-2 py-1 text-red-100 hover:bg-red-800"
        >
          yes, delete
        </button>
        <button
          onClick={() => setArmed(false)}
          className="rounded border border-neutral-700 px-2 py-1 text-neutral-300 hover:border-neutral-500"
        >
          cancel
        </button>
      </span>
    );
  }

  return (
    <span className="flex items-center gap-2 text-xs">
      <button
        onClick={() => setArmed(true)}
        className="rounded border border-red-900 px-2 py-1 text-red-300 hover:bg-red-950/50"
      >
        {label}
      </button>
      {error && <span className="text-red-400">{error}</span>}
      {result && result.status !== "ok" && (
        <span className="text-red-400">
          delete failed
          {/* The CLI's own output, which the endpoint used to discard before
              telling the user to go and read it. */}
          {(result.stderr || result.stdout) && (
            <pre className="mt-1 max-h-40 overflow-auto rounded bg-neutral-900 p-2 whitespace-pre-wrap text-red-300">
              {(result.stderr || result.stdout).slice(-1500)}
            </pre>
          )}
        </span>
      )}
      {result?.status === "ok" && (
        <span className="text-emerald-400">
          {result.rows_removed == null
            ? "deleted"
            : `${result.rows_removed.toLocaleString()} row${
                result.rows_removed === 1 ? "" : "s"
              } deleted`}
        </span>
      )}
    </span>
  );
}
