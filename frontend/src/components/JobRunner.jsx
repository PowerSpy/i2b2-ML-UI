import { useEffect, useRef, useState } from "react";

import { apiPost } from "../lib/api.js";
import useJobPoll from "../lib/useJobPoll.js";
import Button from "../ui/Button.jsx";
import Callout from "../ui/Callout.jsx";
import { Dot, jobTone } from "../ui/Status.jsx";
import { Mono, SectionLabel } from "../ui/Text.jsx";

const TONE_TEXT = {
  positive: "text-positive",
  warn: "text-warn",
  danger: "text-danger",
  accent: "text-accent",
  neutral: "text-text-3",
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
  const { job, status, done, error: pollError, gaveUp } = useJobPoll(jobId);
  const notified = useRef(null);

  useEffect(() => {
    // Also on gaveUp: the button is disabled while a job is in flight, and
    // without this a job we stopped watching would leave it disabled for good.
    if (gaveUp) setBusy(false);
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
  }, [done, gaveUp, status, jobId, onDone]);

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

  const tone = jobTone(status);

  return (
    <div className="space-y-3">
      <Button variant="primary" onClick={submit} disabled={disabled || busy}>
        {busy ? "submitting…" : label}
      </Button>

      {warnings.map((w) => (
        <Callout key={w} tone="warn" title="before this runs">
          {w}
        </Callout>
      ))}

      {status && (
        <div className="space-y-3">
          <p className="flex items-center gap-3 text-[12px]">
            <Mono className="text-text-muted">job {jobId ?? "?"}</Mono>
            <span className={`flex items-center gap-2 ${TONE_TEXT[tone] ?? TONE_TEXT.neutral}`}>
              <Dot tone={tone} />
              {status.toLowerCase()}
            </span>
          </p>

          {gaveUp && (
            <Callout tone="warn" title="stopped watching">
              No terminal status after 20 minutes — the job may still be running.
              Check the job queue, or the watcher log if it never left PENDING.
            </Callout>
          )}

          {pollError && (
            <Callout tone="warn" title="lost contact">
              {pollError}. The status above may be out of date. The job is still
              queued; it has not failed.
            </Callout>
          )}

          {status === "PENDING" && !watcherRunning && (
            <Callout tone="danger" title="nothing will pick this up">
              Queued, but the job watcher is stopped. This will never run until
              you start it.
            </Callout>
          )}

          {job?.error_stack && (
            <div>
              <SectionLabel className="mb-1.5">error stack</SectionLabel>
              <pre className="max-h-64 overflow-auto rounded-row border border-danger-edge bg-danger-edge/25 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-danger">
                {job.error_stack}
              </pre>
            </div>
          )}

          {job?.output && status === "COMPLETED" && (
            <div>
              <SectionLabel className="mb-1.5">output</SectionLabel>
              <pre className="max-h-40 overflow-auto rounded-row border border-border-soft bg-panel-sunk p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-text-3">
                {job.output}
              </pre>
            </div>
          )}
        </div>
      )}

      {error && (
        <Callout tone="danger" title="submission failed">
          {error}
        </Callout>
      )}
    </div>
  );
}
