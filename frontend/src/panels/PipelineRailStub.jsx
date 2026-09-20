import { href, Link } from "../lib/router.jsx";
import { Mono, SectionLabel } from "../ui/Text.jsx";

/**
 * The left rail on the benchmark and model pages.
 *
 * These pages are read-only views of a project rather than steps in its
 * pipeline, so the rail gives the way back rather than repeating the five
 * steps. A model whose project could not be determined gets the same rail
 * without the project links, which is why `project` is optional.
 */
export default function PipelineRailStub({ project, active, model }) {
  const items = project
    ? [
        { key: "project", label: "Overview", to: href.project(project.id) },
        { key: "benchmark", label: "Benchmark", to: href.benchmark(project.id) },
      ]
    : [];

  return (
    <>
      <div className="shrink-0 border-b border-border px-4 py-4">
        <Link to={href.workspace()} className="text-[11px] text-text-muted hover:text-text-2">
          ← all projects
        </Link>
        <p className="mt-2 font-head text-[15px] leading-tight font-semibold text-text">
          {project?.name ?? "No project"}
        </p>
        <p className="mt-1 truncate font-mono text-[11px] text-text-3">
          {project?.root ?? "unattributed model"}
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
        <SectionLabel className="mb-3">In this project</SectionLabel>

        <nav className="space-y-0.5">
          {items.map((item) => (
            <Link
              key={item.key}
              to={item.to}
              aria-current={active === item.key ? "page" : undefined}
              className={`flex min-h-[44px] items-center rounded-row border-l-2 pr-3 pl-2.5 text-[13px] transition-colors ${
                active === item.key
                  ? "border-accent bg-panel-sunk text-text"
                  : "border-transparent text-text-3 hover:bg-panel-sunk/60 hover:text-text-2"
              }`}
            >
              {item.label}
            </Link>
          ))}

          {model && (
            <span className="flex min-h-[44px] items-center rounded-row border-l-2 border-accent bg-panel-sunk pr-3 pl-2.5">
              <Mono className="truncate text-[13px] text-text">{model}</Mono>
            </span>
          )}
        </nav>

        {!project && (
          <p className="mt-4 rounded-row border border-border-soft bg-panel-sunk p-3 text-[11px] leading-relaxed text-text-muted">
            This model&apos;s stored config names no readable data path, so it
            cannot be filed under a concept subtree.
          </p>
        )}
      </div>
    </>
  );
}
