import { createContext, useContext, useEffect, useMemo, useState } from "react";

/**
 * A ~100 line history router, in place of a dependency.
 *
 * The app has nine routes and no nesting, data loading or code splitting, so
 * the only thing react-router would add here is a package. Vite's dev server
 * and `vite preview` both fall back to index.html for unknown paths, so deep
 * links work without any server config.
 */

// Segment count is part of the match, so /project/:id and
// /project/:id/benchmark cannot collide and order does not matter.
const PATTERNS = [
  { name: "workspace", pattern: "/" },
  { name: "concepts", pattern: "/concepts" },
  { name: "cohorts", pattern: "/cohorts" },
  { name: "models", pattern: "/models" },
  { name: "benchmarks", pattern: "/benchmarks" },
  { name: "data-health", pattern: "/data-health" },
  { name: "project", pattern: "/project/:id" },
  { name: "project-benchmark", pattern: "/project/:id/benchmark" },
  { name: "model", pattern: "/model/:code" },
];

function segments(path) {
  return path.replace(/\/+$/, "").split("/").filter(Boolean);
}

export function matchRoute(path) {
  const parts = segments(path);
  for (const { name, pattern } of PATTERNS) {
    const want = segments(pattern);
    if (want.length !== parts.length) continue;

    const params = {};
    let ok = true;
    for (let i = 0; i < want.length; i++) {
      if (want[i].startsWith(":")) {
        // Ids are concept path segments and model codes, which are escaped
        // into the URL and have to come back out the same.
        params[want[i].slice(1)] = decodeURIComponent(parts[i]);
      } else if (want[i] !== parts[i]) {
        ok = false;
        break;
      }
    }
    if (ok) return { name, params, path };
  }
  return { name: "not-found", params: {}, path };
}

function here() {
  return window.location.pathname;
}

/**
 * pushState does not fire popstate, so nothing would re-render on an in-app
 * navigation without dispatching one ourselves.
 */
export function navigate(to, { replace = false } = {}) {
  if (to === here()) return;
  window.history[replace ? "replaceState" : "pushState"]({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

const RouteContext = createContext(matchRoute("/"));

export function Router({ children }) {
  const [path, setPath] = useState(here);

  useEffect(() => {
    const onPop = () => setPath(here());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Scroll position is per-rail, not per-window, but a route change still has
  // to reset the centre column — otherwise a deep link from a long page opens
  // the next one halfway down.
  useEffect(() => {
    document.getElementById("centre")?.scrollTo(0, 0);
  }, [path]);

  const route = useMemo(() => matchRoute(path), [path]);

  return (
    <RouteContext.Provider value={route}>{children}</RouteContext.Provider>
  );
}

export function useRoute() {
  return useContext(RouteContext);
}

/** True when `to` is the current route, or an ancestor of it. */
export function isActive(route, to) {
  if (to === "/") return route.path === "/";
  return route.path === to || route.path.startsWith(`${to}/`);
}

/**
 * An anchor that navigates in-app on a plain left click and behaves like an
 * ordinary link otherwise — cmd/ctrl-click, middle click and "open in new tab"
 * all still work because the href is real.
 */
export function Link({ to, children, className, onClick, ...rest }) {
  function handle(e) {
    onClick?.(e);
    if (
      e.defaultPrevented ||
      e.button !== 0 ||
      e.metaKey ||
      e.ctrlKey ||
      e.shiftKey ||
      e.altKey
    ) {
      return;
    }
    e.preventDefault();
    navigate(to);
  }

  return (
    <a href={to} onClick={handle} className={className} {...rest}>
      {children}
    </a>
  );
}

/** URL builders, so no route string is spelled out twice. */
export const href = {
  workspace: () => "/",
  section: (name) => `/${name}`,
  project: (id) => `/project/${encodeURIComponent(id)}`,
  benchmark: (id) => `/project/${encodeURIComponent(id)}/benchmark`,
  model: (code) => `/model/${encodeURIComponent(code)}`,
};
