import { href, isActive, Link, useRoute } from "../lib/router.jsx";
import { useWorkspace } from "../lib/workspace.jsx";
import { Dot } from "../ui/Status.jsx";

const NAV = [
  { label: "Projects", to: href.workspace() },
  { label: "Benchmarks", to: href.section("benchmarks") },
  { label: "Models", to: href.section("models") },
];

/**
 * 62px: wordmark, primary nav, the live engine pill, the user chip.
 *
 * The pill is the one thing on screen that is true right now rather than as of
 * the last refresh — a stopped watcher turns every later action into a no-op
 * that still reports success, so it is never more than a glance away.
 */
export default function TopBar() {
  const route = useRoute();

  return (
    <header className="flex h-[62px] shrink-0 items-center justify-between gap-6 border-b border-border bg-panel px-6">
      <div className="flex min-w-0 items-center gap-8">
        <Link
          to={href.workspace()}
          className="font-head text-[16px] font-bold tracking-tight text-text whitespace-nowrap"
        >
          i2b2 ML Workbench
        </Link>

        <nav className="flex items-center gap-1" aria-label="Primary">
          {NAV.map((item) => {
            // "Projects" stays lit on a project page, which is where the
            // Projects tab leads; the others are exact.
            const active =
              item.to === href.workspace()
                ? route.path === "/" || route.path.startsWith("/project/")
                : isActive(route, item.to);
            return (
              <Link
                key={item.to}
                to={item.to}
                aria-current={active ? "page" : undefined}
                className={`flex h-[44px] items-center border-b-2 px-3 text-[13px] transition-colors ${
                  active
                    ? "border-accent text-text"
                    : "border-transparent text-text-3 hover:text-text"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="flex shrink-0 items-center gap-4">
        <EnginePill />
        <UserChip />
      </div>
    </header>
  );
}

function EnginePill() {
  const { health, watcher, watcherError, loading } = useWorkspace();

  const engine = loading
    ? { tone: "idle", text: "engine checking" }
    : health?.data
      ? { tone: "positive", text: "engine up" }
      : { tone: "danger", text: "engine unreachable" };

  // "no watcher" rather than "watcher stopped": the probe counts processes
  // without checking whether the exec itself worked, so zero hits can also
  // mean the container is gone. The alert panel spells that out.
  const poll = watcherError
    ? { tone: "danger", text: "watcher unreachable" }
    : !watcher
      ? { tone: "idle", text: "watcher checking" }
      : watcher.running
        ? watcher.count > 1
          ? { tone: "warn", text: `${watcher.count} watchers polling` }
          : { tone: "positive", text: "watcher polling" }
        : { tone: "danger", text: "no watcher" };

  return (
    <div className="flex h-[34px] items-center gap-2.5 rounded-full border border-border bg-panel-sunk pr-3.5 pl-3 text-[12px]">
      <span className="flex items-center gap-2 text-text-2">
        <Dot tone={engine.tone} />
        {engine.text}
      </span>
      <span aria-hidden="true" className="text-text-muted">
        ·
      </span>
      <span className="flex items-center gap-2 text-text-2">
        <Dot tone={poll.tone} />
        {poll.text}
      </span>
    </div>
  );
}

/**
 * There is no identity endpoint — the backend authenticates to the ETL with a
 * session id from its own config file and never tells the browser who that is.
 * Rendering a plausible name here would be inventing one, so the chip says what
 * it actually knows.
 */
function UserChip() {
  return (
    <div
      className="flex items-center gap-2.5"
      title="The API exposes no current-user endpoint. The backend holds an i2b2 session id in config.yaml and does not surface the account behind it."
    >
      <span
        aria-hidden="true"
        className="flex size-[30px] items-center justify-center rounded-full border border-dashed border-border-strong font-mono text-[12px] text-text-muted"
      >
        —
      </span>
      <span className="text-[11px] leading-tight text-text-muted">
        signed-in user
        <br />
        not reported
      </span>
    </div>
  );
}
