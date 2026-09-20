import { href, isActive, Link, useRoute } from "../lib/router.jsx";
import { useWorkspace } from "../lib/workspace.jsx";
import { Dot } from "../ui/Status.jsx";
import { Mono, Num, SectionLabel } from "../ui/Text.jsx";

/**
 * The workspace rail: six sections, each with the count it actually holds, and
 * container reachability pinned to the bottom.
 *
 * Counts are read back from the warehouse, never from the response of whatever
 * wrote them — that is the whole reason they are on screen.
 */
export default function WorkspaceRail() {
  const route = useRoute();
  const ws = useWorkspace();

  const items = [
    { label: "Projects", to: href.workspace(), count: ws.projects.length },
    { label: "Concepts", to: href.section("concepts"), count: ws.concepts.length },
    { label: "Cohorts", to: href.section("cohorts"), count: ws.cohorts.length },
    { label: "Models", to: href.section("models"), count: ws.models.length },
    {
      label: "Benchmarks",
      to: href.section("benchmarks"),
      // A project earns a leaderboard as soon as one model in it is built.
      count: ws.projects.filter((p) => p.models.some((m) => m.is_built)).length,
    },
    {
      label: "Data health",
      to: href.section("data-health"),
      count: ws.alerts.length,
      tone: ws.alerts.some((a) => a.tone === "danger")
        ? "danger"
        : ws.alerts.length
          ? "warn"
          : "positive",
    },
  ];

  return (
    <>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-5">
        <SectionLabel className="px-3 pb-3">Workspace</SectionLabel>
        <nav className="space-y-0.5" aria-label="Workspace sections">
          {items.map((item) => {
            const active = isActive(route, item.to);
            return (
              <Link
                key={item.to}
                to={item.to}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-[44px] items-center justify-between gap-2 rounded-row border-l-2 pr-3 pl-2.5 text-[13px] transition-colors ${
                  active
                    ? "border-accent bg-panel-sunk text-text"
                    : "border-transparent text-text-3 hover:bg-panel-sunk/60 hover:text-text-2"
                }`}
              >
                <span>{item.label}</span>
                <span className="flex items-center gap-2">
                  {item.tone && item.count > 0 && <Dot tone={item.tone} />}
                  <Num className="text-[12px] text-text-muted">{item.count}</Num>
                </span>
              </Link>
            );
          })}
        </nav>
      </div>

      <Containers />
    </>
  );
}

const CONTAINER_TONE = {
  reachable: "positive",
  unreachable: "danger",
  checking: "idle",
  unknown: "idle",
  "not determinable": "idle",
};

/**
 * Not a container list — the API has no such endpoint. These are the two
 * containers the backend shells into. Only the database one has a probe that
 * proves anything; the other says so. Uptime is left off rather than invented.
 */
function Containers() {
  const { containers } = useWorkspace();

  return (
    <div className="shrink-0 border-t border-border p-3">
      <div className="rounded-row border border-border-soft bg-panel-sunk p-3">
        <SectionLabel className="mb-2.5">Containers</SectionLabel>
        <ul className="space-y-2">
          {containers.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-2">
              <Mono className="text-[12px] text-text-2" title={c.role}>
                {c.id}
              </Mono>
              <span
                className="flex items-center gap-2 text-right text-[11px] text-text-3"
                title={c.why ?? `proved by the ${c.via}`}
              >
                <Dot tone={CONTAINER_TONE[c.state] ?? "idle"} />
                {c.state}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-2.5 border-t border-border-soft pt-2 text-[10px] leading-relaxed text-text-muted">
          Only the row-count query proves a container answered. The ETL probes
          are unsound, and nothing reports uptime, image or restart count.
        </p>
      </div>
    </div>
  );
}
