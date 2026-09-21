import { href, Link } from "../lib/router.jsx";
import { SectionLabel } from "../ui/Text.jsx";

/**
 * The five steps as a vertical pipeline.
 *
 * Every step is gated on the one above it, and a step run out of order fails
 * silently rather than loudly, so the rail shows what each one actually
 * produced instead of only whether it was visited. `current` is the first step
 * whose output does not exist yet.
 */
export default function PipelineRail({ steps, selected, onSelect, project }) {
  return (
    <>
      <div className="shrink-0 border-b border-border px-4 py-4">
        <Link
          to={href.workspace()}
          className="text-[11px] text-text-muted hover:text-text-2"
        >
          ← all projects
        </Link>
        <p className="mt-2 font-head text-[15px] leading-tight font-semibold text-text">
          {project.name}
        </p>
        <p className="mt-1 truncate font-mono text-[11px] text-text-3" title={project.root}>
          {project.root}
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
        <SectionLabel className="mb-3">Pipeline</SectionLabel>

        <button
          type="button"
          onClick={() => onSelect("overview")}
          className={`mb-3 flex min-h-[44px] w-full items-center rounded-row border-l-2 pr-3 pl-2.5 text-left text-[13px] transition-colors ${
            selected === "overview"
              ? "border-accent bg-panel-sunk text-text"
              : "border-transparent text-text-3 hover:bg-panel-sunk/60 hover:text-text-2"
          }`}
        >
          Overview
        </button>

        <ol className="relative">
          {/*
            The 1px spine. Absolutely positioned behind the circles rather than
            drawn per-row, so it stays continuous whatever height a summary
            wraps to.
          */}
          <span
            aria-hidden="true"
            className="absolute top-4 bottom-4 left-[21px] w-px bg-border"
          />

          {steps.map((step) => {
            const active = selected === step.n;
            return (
              <li key={step.n} className="relative">
                <button
                  type="button"
                  onClick={() => onSelect(step.n)}
                  aria-current={active ? "step" : undefined}
                  // Same accent bar as the Overview item above: on a rail
                  // where every row already carries a coloured circle, a
                  // background tint alone was not a legible selection.
                  className={`flex w-full items-start gap-3 rounded-row border-l-2 py-2.5 pr-2 pl-2 text-left transition-colors ${
                    active
                      ? "border-accent bg-panel-sunk"
                      : "border-transparent hover:bg-panel-sunk/60"
                  }`}
                >
                  <StepCircle state={step.state} n={step.n} />
                  <span className="min-w-0 flex-1 pt-0.5">
                    <span
                      className={`block text-[13px] leading-tight ${
                        step.state === "idle" ? "text-text-muted" : "text-text"
                      }`}
                    >
                      {step.title}
                    </span>
                    <span
                      className={`mt-1 block text-[11px] leading-snug ${
                        step.state === "current" ? "text-text-3" : "text-text-muted"
                      }`}
                    >
                      {step.summary}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        <p className="mt-5 rounded-row border border-border-soft bg-panel-sunk p-3 text-[11px] leading-relaxed text-text-muted">
          Every step is gated on the one above it. Nothing here infers your
          columns — i2b2 stores one row per value, so each step points at part of
          that pile: which patients, which columns, which one is the answer.
        </p>
      </div>
    </>
  );
}

const CIRCLE = {
  done: "border-positive bg-positive-edge text-positive",
  current: "border-accent bg-accent/10 text-accent",
  idle: "border-border-strong bg-panel-sunk text-text-muted",
};

function StepCircle({ state, n }) {
  return (
    <span
      className={`relative z-10 flex size-[22px] shrink-0 items-center justify-center rounded-full border font-mono text-[11px] ${
        CIRCLE[state] ?? CIRCLE.idle
      }`}
    >
      {n}
    </span>
  );
}
