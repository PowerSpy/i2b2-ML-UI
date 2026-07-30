import { useState } from "react";

const KEY = "i2b2ml.intro.dismissed";

/**
 * The mental model that makes the rest of the UI legible. Dismissible, because
 * it is only useful once — but worth being open by default the first time.
 */
export default function Intro() {
  const [open, setOpen] = useState(
    () => localStorage.getItem(KEY) !== "1",
  );

  function dismiss() {
    localStorage.setItem(KEY, "1");
    setOpen(false);
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-xs text-sky-500 hover:text-sky-400"
      >
        how does this work?
      </button>
    );
  }

  return (
    <section className="space-y-3 rounded-lg border border-neutral-800 bg-neutral-900/40 p-4 text-xs leading-relaxed text-neutral-400">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-sm font-medium text-neutral-200">
          How this works
        </h2>
        <button
          onClick={dismiss}
          className="shrink-0 text-neutral-500 hover:text-neutral-300"
        >
          dismiss
        </button>
      </div>

      <p>
        <strong className="text-neutral-300">
          i2b2 has no concept of a &ldquo;dataset&rdquo;.
        </strong>{" "}
        There is no table per project. Every value, for every patient, from
        everything you ever load, goes into <em>one</em> table
        (<code className="text-neutral-300">observation_fact</code>) as one row
        per value, tagged with a <em>concept code</em>.
      </p>

      <p>
        So unlike training from a CSV — where the columns simply <em>are</em> the
        features — nothing here can be inferred. Each step below exists to point
        at part of that shared pile: which patients, which columns, which one is
        the answer.
      </p>

      <ol className="space-y-1 pl-4">
        <li>
          <strong className="text-neutral-300">1 Load</strong> — declare your
          columns (concepts) and their per-patient values (facts).
        </li>
        <li>
          <strong className="text-neutral-300">2 Cohorts</strong> — name groups
          of patients. The engine reads these, not your label values.
        </li>
        <li>
          <strong className="text-neutral-300">3 Define</strong> — say which
          concepts are inputs and which is the outcome. Trains nothing.
        </li>
        <li>
          <strong className="text-neutral-300">4 Train</strong> — queue a job.
          A background worker runs it.
        </li>
        <li>
          <strong className="text-neutral-300">5 Apply</strong> — score patients;
          predictions come back as ordinary facts.
        </li>
      </ol>

      <p className="text-neutral-500">
        Most failures in this system are silent — a step can report success and
        do nothing. That is why counts are pinned at the top and every step is
        gated on the previous one.
      </p>
    </section>
  );
}
