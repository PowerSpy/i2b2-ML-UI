import { useState } from "react";

/**
 * One numbered step. The workflow is strictly sequential and a step run out of
 * order fails silently, so `blocked` explains why rather than just greying out.
 * `help` is the longer "what is this for" text, hidden behind a toggle.
 */
export default function StepCard({ n, title, hint, help, done, blocked, children }) {
  const [showHelp, setShowHelp] = useState(false);

  return (
    <section
      className={`rounded-lg border p-4 ${
        blocked ? "border-neutral-800/60 bg-neutral-950" : "border-neutral-800"
      }`}
    >
      <div className="flex items-baseline gap-3">
        <span
          className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
            done
              ? "bg-emerald-900 text-emerald-200"
              : blocked
                ? "bg-neutral-900 text-neutral-600"
                : "bg-neutral-800 text-neutral-300"
          }`}
        >
          {done ? "✓" : n}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <h2
              className={`text-sm font-medium ${
                blocked ? "text-neutral-600" : "text-neutral-200"
              }`}
            >
              {title}
            </h2>
            {help && (
              <button
                onClick={() => setShowHelp((s) => !s)}
                className="text-xs text-sky-500 hover:text-sky-400"
              >
                {showHelp ? "hide help" : "what is this?"}
              </button>
            )}
          </div>
          {hint && <p className="mt-1 text-xs text-neutral-500">{hint}</p>}
        </div>
      </div>

      {showHelp && help && (
        <div className="mt-3 space-y-2 rounded border border-neutral-800 bg-neutral-900/50 p-3 text-xs leading-relaxed text-neutral-400">
          {help}
        </div>
      )}

      <div className={`mt-4 ${blocked ? "pointer-events-none opacity-40" : ""}`}>
        {blocked ? (
          <p className="text-xs text-neutral-500">{blocked}</p>
        ) : (
          children
        )}
      </div>
    </section>
  );
}
