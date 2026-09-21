import { count, score } from "../lib/format.js";
import { href, Link } from "../lib/router.jsx";
import { Status } from "../ui/Status.jsx";
import { Heading, Mono, Num, SectionLabel } from "../ui/Text.jsx";

/**
 * One project: a concept subtree, its models, and the state of the pipeline
 * around it.
 *
 * Two of the four counts are warehouse-wide rather than project-scoped, and
 * are dimmed and footnoted to say so. i2b2 stores one fact table and one
 * patient-set table for everything, and no endpoint slices either by concept
 * path — a per-project fact count would have to be made up.
 */
export default function ProjectCard({ project, facts, cohorts }) {
  const built = project.models.filter((m) => m.is_built);
  const state = stateOf({ project, built, cohorts });

  return (
    <Link
      to={href.project(project.id)}
      className="group block rounded-card border border-border bg-panel p-[18px] transition-colors hover:border-border-strong"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Heading level={3} className="truncate text-[15px] leading-tight">
            {project.name}
          </Heading>
          <Mono className="mt-1 block truncate text-[12px] text-text-3" title={project.root}>
            {project.root}
          </Mono>
        </div>
        <Status tone={state.tone} className="shrink-0 whitespace-nowrap">
          {state.label}
        </Status>
      </div>

      <div className="mt-4 grid grid-cols-4 gap-3">
        <Tile value={count(facts)} label="facts" scoped={false} />
        <Tile value={count(project.concepts.length)} label="concepts" />
        <Tile value={count(cohorts)} label="cohorts" scoped={false} />
        <Tile value={count(project.models.length)} label="models" />
      </div>

      <p className="mt-2.5 text-[10px] leading-relaxed text-text-muted">
        Dimmed counts are warehouse-wide. Facts and patient sets are not scoped
        to a concept subtree by any endpoint.
      </p>

      <div className="mt-3.5 flex items-baseline justify-between gap-3 border-t border-border-soft pt-3">
        <p className="min-w-0 truncate text-[12px] text-text-3">
          {project.best ? (
            <>
              best — <Mono className="text-text-2">{project.best.name}</Mono>
              , AUC <Num className="text-positive">{score(project.best.auc)}</Num>
            </>
          ) : built.length ? (
            "built, but no ROC AUC recorded"
          ) : (
            "no built models yet"
          )}
        </p>
        <span className="shrink-0 text-[11px] text-text-muted">
          no timestamp reported
        </span>
      </div>
    </Link>
  );
}

function Tile({ value, label, scoped = true }) {
  return (
    <div>
      <Num className={`block text-[20px] leading-none ${scoped ? "text-text" : "text-text-3"}`}>
        {value}
      </Num>
      <SectionLabel className="mt-1.5">{label}</SectionLabel>
    </div>
  );
}

function stateOf({ project, built, cohorts }) {
  if (cohorts === 0) return { tone: "warn", label: "no cohorts" };
  if (project.models.length === 0) return { tone: "warn", label: "no models" };
  if (built.length === 0) return { tone: "warn", label: "nothing built" };
  return { tone: "positive", label: "active" };
}
