import { useState } from "react";

import { href, isActive, Link, useRoute } from "../lib/router.jsx";
import { useSession } from "../lib/session.jsx";
import { useWorkspace } from "../lib/workspace.jsx";
import { Dot } from "../ui/Status.jsx";
import { Mono } from "../ui/Text.jsx";

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

function initials(name) {
  const parts = name.trim().split(/[\s._-]+/).filter(Boolean);
  const letters = parts.length > 1
    ? parts[0][0] + parts[parts.length - 1][0]
    : name.slice(0, 2);
  return letters.toUpperCase();
}

/**
 * Who is signed in, and what they are allowed to be.
 *
 * The role is not decoration. A researcher needs to know *why* half the
 * controls are missing rather than assuming the app is broken, and a custodian
 * needs to know they are the one who can destroy things.
 */
function UserChip() {
  const { user, role, logout } = useSession();
  const [busy, setBusy] = useState(false);

  if (!user) return null;

  const name = user.display_name || user.username;

  async function signOut() {
    setBusy(true);
    try {
      await logout();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-2.5">
        <span
          aria-hidden="true"
          className="flex size-[30px] items-center justify-center rounded-full border border-border-strong bg-panel-sunk font-mono text-[11px] text-text-2"
        >
          {initials(name)}
        </span>
        <span className="leading-tight">
          <span className="block text-[12px] text-text-2">{name}</span>
          <Mono className="block text-[10px] text-text-muted">{role}</Mono>
        </span>
      </div>

      <button
        type="button"
        onClick={signOut}
        disabled={busy}
        className="min-h-[44px] rounded-btn px-2 text-[12px] text-text-3 transition-colors hover:text-text disabled:text-text-muted"
      >
        {busy ? "signing out…" : "sign out"}
      </button>
    </div>
  );
}
