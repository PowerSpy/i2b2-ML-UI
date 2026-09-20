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
  const { job, status, done, error: pollError } = useJobPoll(jobId);
  const notified = useRef(null);

  useEffect(() => {
    if (!done) return;
    // Cleared here rather than when the POST returns. Submitting only queues the
    // job, so re-enabling the button then let a second click queue another one —
    // and because a build deletes every existing fact under the path first, that
    // second run destroyed the first one's output mid-flight.
    setBusy(false);
    if (status === "COMPLETED" && notified.current !== jobId) {
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
      // The id comes from the submission itself, anchored to the highest job id
      // seen before it. Reading "the newest row" afterwards used to race: the
      // row might not exist yet, so the newest was the *previous* job — often
      // already COMPLETED, which reported instant success for a job that had
      // not started.
      if (res.job_id == null) {
        throw new Error(
          "the job was queued but could not be identified, so its progress " +
            "cannot be tracked here — check the job list before resubmitting",
        );
      }
      setJobId(res.job_id);
    } catch (e) {
      setError(e.message);
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

          {pollError && (
          <p className="text-xs text-amber-300/80">
            lost contact while watching this job ({pollError}) — the status
            above may be out of date. It is still queued; it has not failed.
          </p>
        )}

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
