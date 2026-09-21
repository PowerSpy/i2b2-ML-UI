import { ago, firstLine } from "../lib/format.js";
import { useWorkspace } from "../lib/workspace.jsx";
import { Failed } from "../ui/Callout.jsx";
import { Dot, jobTone } from "../ui/Status.jsx";
import { Mono, Num, SectionLabel } from "../ui/Text.jsx";

/**
 * The last 20 rows of the job table, re-read every 10 seconds.
 *
 * The job row is the only record of what a build or an apply did: the POST
 * that created it returns before anything runs, so its response says nothing.
 * PENDING with the watcher stopped means it will sit there forever, which is
 * why the top bar carries the watcher state next to this.
 */
export default function JobQueue() {
  const { jobs, jobsError, jobsLoaded } = useWorkspace();

  return (
    <section>
      <div className="mb-2.5 flex items-baseline justify-between">
        <SectionLabel>Job queue</SectionLabel>
        <Num className="text-[12px] text-text-muted">
          {jobsLoaded ? jobs.length : "—"}
        </Num>
      </div>

      {jobsError ? (
        <Failed what="the job queue" error={jobsError} />
      ) : !jobsLoaded ? (
        // Before the first poll the list is empty because nothing has been
        // read, not because nothing has been queued.
        <p className="rounded-row border border-dashed border-border px-4 py-5 text-center text-[12px] text-text-muted">
          Reading the job table…
        </p>
      ) : jobs.length === 0 ? (
        <p className="rounded-row border border-dashed border-border px-4 py-5 text-center text-[12px] text-text-muted">
          No jobs have been queued. A build or an apply adds a row here.
        </p>
      ) : (
        <ul className="divide-y divide-border-soft">
          {jobs.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
        </ul>
      )}
    </section>
  );
}

function JobRow({ job }) {
  const tone = jobTone(job.status);
  const when = ago(job.completed_on ?? job.started_on);
  const detail =
    job.status === "ERROR"
      ? firstLine(job.error_stack)
      : job.status === "COMPLETED"
        ? firstLine(job.output)
        : null;

  return (
    <li className="py-3">
      <div className="flex items-baseline justify-between gap-3">
        <Mono className="text-[12px] text-text-2">job {job.id}</Mono>
        <span className={`flex shrink-0 items-center gap-2 text-[12px] ${TONE_TEXT[tone]}`}>
          <Dot tone={tone} />
          {(job.status ?? "unknown").toLowerCase()}
        </span>
      </div>

      <p className="mt-1 flex items-center gap-1.5 text-[11px] text-text-muted">
        <Mono>{job.job_type ?? "—"}</Mono>
        {when && (
          <>
            <span aria-hidden="true">·</span>
            <span>{when}</span>
          </>
        )}
      </p>

      {detail && (
        <p
          className={`mt-1.5 line-clamp-2 font-mono text-[11px] leading-snug break-words ${
            job.status === "ERROR" ? "text-danger" : "text-text-muted"
          }`}
        >
          {detail}
        </p>
      )}
    </li>
  );
}

const TONE_TEXT = {
  positive: "text-positive",
  warn: "text-warn",
  danger: "text-danger",
  accent: "text-accent",
  neutral: "text-text-3",
  idle: "text-text-muted",
};
