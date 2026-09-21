import { useState } from "react";

import { apiDelete } from "../lib/api.js";
import { count, plural } from "../lib/format.js";
import Button from "../ui/Button.jsx";
import { Status } from "../ui/Status.jsx";
import { Num } from "../ui/Text.jsx";

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
    return <Status tone="accent">deleting {target}…</Status>;
  }

  if (armed) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-[12px] text-text-2">Delete all {target}?</span>
        <Button variant="danger" onClick={run}>
          yes, delete
        </Button>
        <Button onClick={() => setArmed(false)}>cancel</Button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="danger" onClick={() => setArmed(true)}>
          {label}
        </Button>
        {error && <Status tone="danger">{error}</Status>}
        {result?.status === "ok" && (
          <Status tone="positive">
            {result.rows_removed == null ? (
              "deleted"
            ) : (
              <>
                <Num>{count(result.rows_removed)}</Num>{" "}
                {plural(result.rows_removed, "row")} deleted
              </>
            )}
          </Status>
        )}
        {result && result.status !== "ok" && <Status tone="danger">delete failed</Status>}
      </div>

      {/* The CLI's own output, which the endpoint used to discard before
          telling the user to go and read it. */}
      {result && result.status !== "ok" && (result.stderr || result.stdout) && (
        <pre className="max-h-40 overflow-auto rounded-row border border-danger-edge bg-danger-edge/25 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-danger">
          {(result.stderr || result.stdout).slice(-1500)}
        </pre>
      )}
    </div>
  );
}
