import { useEffect, useRef, useState } from "react";

import { apiGet, apiPost } from "../lib/api.js";
import useJobPoll from "../lib/useJobPoll.js";
import { Warnings } from "./Warning.jsx";

const TONES = {
  SUBMITTED: "bg-neutral-800 text-neutral-300",
  PENDING: "bg-amber-950 text-amber-300",
  PROCESSING: "bg-sky-950 text-sky-300",
  COMPLETED: "bg-emerald-950 text-emerald-300",
  ERROR: "bg-red-950 text-red-300",
};

/**
 * Submit-then-poll, shared by build and apply. The POST only queues the job, so
 * nothing here reports success off its response.
 */
export default function JobRunner({
  endpoint,
  body,
  label,
  disabled,
  watcherRunning,
  onDone,
}) {
  const [jobId, setJobId] = useState(null);
  const [warnings, setWarnings] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const { job, status, done } = useJobPoll(jobId);
  const notified = useRef(null);

  useEffect(() => {
    if (done && status === "COMPLETED" && notified.current !== jobId) {
      notified.current = jobId;
      onDone?.();
    }
  }, [done, status, jobId, onDone]);

  async function submit() {
    setBusy(true);
    setError(null);
    setJobId(null);
    try {
      const res = await apiPost(endpoint, body);
      setWarnings(res.warnings ?? []);
      // The queue POST does not hand back an id, so take the newest row.
      const jobs = await apiGet("/jobs?limit=1");
      if (!jobs.length) throw new Error("job was submitted but no row appeared");
      setJobId(jobs[0].id);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <button
        onClick={submit}
        disabled={disabled || busy}
        className="rounded bg-sky-800 px-3 py-1.5 text-sm text-sky-50 hover:bg-sky-700 disabled:opacity-40"
      >
        {busy ? "submitting…" : label}
      </button>

      <Warnings items={warnings} />

      {status && (
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-xs">
            <span className="text-neutral-500">job {jobId ?? "?"}</span>
            <span
              className={`rounded px-2 py-0.5 font-medium ${TONES[status] ?? TONES.SUBMITTED}`}
            >
              {status}
            </span>
          </p>

          {status === "PENDING" && !watcherRunning && (
            <p className="text-xs text-red-400">
              queued, but the job watcher is stopped — this will never run until
              you start it.
            </p>
          )}

          {job?.error_stack && (
            <pre className="max-h-64 overflow-auto rounded bg-neutral-900 p-3 text-xs whitespace-pre-wrap text-red-300">
              {job.error_stack}
            </pre>
          )}

          {job?.output && status === "COMPLETED" && (
            <pre className="max-h-40 overflow-auto rounded bg-neutral-900 p-3 text-xs whitespace-pre-wrap text-neutral-400">
              {job.output}
            </pre>
          )}
        </div>
      )}

      {error && (
        <p className="rounded border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
