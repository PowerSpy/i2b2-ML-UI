import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { buildAlerts } from "./alerts.js";
import { apiGet, apiPost } from "./api.js";
import { buildProjects } from "./projects.js";

/**
 * Every read the shell needs, in one place.
 *
 * Four routes render off the same handful of endpoints, so fetching per-route
 * would mean the same /concepts call firing on each navigation. This loads the
 * set once, re-runs it when `refresh()` says the warehouse changed, and polls
 * only the two things that move on their own — the watcher and the job queue.
 *
 * Nothing here reports success off a write's own response. Counts come back
 * from the warehouse on the next refresh, because a step in this system can
 * report success and load nothing.
 */

const WorkspaceContext = createContext(null);

const POLL_MS = 10_000;

/** A request whose failure is a value rather than a thrown exception. */
function settle(promise) {
  return promise.then((data) => ({ data }), (e) => ({ error: e.message }));
}

export function WorkspaceProvider({ children }) {
  // Bumped whenever something changed the warehouse, to re-pull everything.
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((n) => n + 1), []);

  const [core, setCore] = useState({ loading: true });
  const [configs, setConfigs] = useState({});
  const [metrics, setMetrics] = useState({});
  // jobsLoaded starts false so an empty list before the first poll is not
  // rendered as "no jobs have ever been queued".
  const [live, setLive] = useState({
    watcher: null,
    watcherError: null,
    jobs: [],
    jobsLoaded: false,
  });

  // The core set: everything that only changes when someone changes it.
  useEffect(() => {
    let alive = true;
    Promise.all([
      settle(apiGet("/health")),
      settle(apiGet("/verify-load")),
      settle(apiGet("/concepts")),
      settle(apiGet("/concept-tree")),
      settle(apiGet("/cohorts")),
      settle(apiGet("/ml-concepts")),
      settle(apiGet("/ml-model-types")),
    ]).then(([health, verify, concepts, tree, cohorts, models, modelTypes]) => {
      if (!alive) return;
      setCore({
        loading: false,
        health,
        verify,
        concepts,
        tree,
        cohorts,
        models,
        modelTypes,
      });
    });
    return () => {
      alive = false;
    };
  }, [version]);

  const models = core.models?.data;

  // Config per model. This is what files a model under a project — the model's
  // own path is under /ML, which says nothing about the data it read.
  useEffect(() => {
    if (!models) return;
    let alive = true;
    Promise.all(
      models.map((m) =>
        settle(apiGet(`/ml-concepts/${encodeURIComponent(m.code)}/config`)).then(
          (r) => [m.code, r],
        ),
      ),
    ).then((entries) => alive && setConfigs(Object.fromEntries(entries)));
    return () => {
      alive = false;
    };
  }, [models]);

  // Metrics for built models only — the endpoint 409s on an unbuilt one, and
  // a wall of expected errors makes a real one impossible to notice.
  useEffect(() => {
    if (!models) return;
    let alive = true;
    Promise.all(
      models
        .filter((m) => m.is_built)
        .map((m) =>
          settle(apiGet(`/ml-concepts/${encodeURIComponent(m.code)}/metrics`)).then(
            (r) => [m.code, r],
          ),
        ),
    ).then((entries) => alive && setMetrics(Object.fromEntries(entries)));
    return () => {
      alive = false;
    };
  }, [models]);

  // The watcher and the job queue move without anyone touching the UI, and a
  // stopped watcher is the single most consequential thing on screen.
  useEffect(() => {
    let alive = true;
    let timer = null;

    async function tick() {
      const [watcher, jobs] = await Promise.all([
        settle(apiGet("/watcher")),
        settle(apiGet("/jobs?limit=20")),
      ]);
      if (!alive) return;
      setLive({
        watcher: watcher.data ?? null,
        watcherError: watcher.error ?? null,
        jobs: jobs.data ?? [],
        jobsError: jobs.error ?? null,
        jobsLoaded: true,
      });
      timer = setTimeout(tick, POLL_MS);
    }

    tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [version]);

  const startWatcher = useCallback(async () => {
    const res = await apiPost("/watcher/start", {});
    setLive((prev) => ({ ...prev, watcher: res, watcherError: null }));
    return res;
  }, []);

  const value = useMemo(() => {
    const concepts = core.concepts?.data ?? [];
    const tree = core.tree?.data ?? [];
    const cohorts = core.cohorts?.data ?? [];
    const modelList = core.models?.data ?? [];

    const { projects, unattributed } = buildProjects({
      concepts,
      tree,
      models: modelList,
      configs,
      metrics,
    });

    const alerts = buildAlerts({
      watcher: live.watcher,
      watcherError: live.watcherError,
      cohorts,
      models: modelList,
      metrics,
      jobs: live.jobs,
      projects,
      unattributed,
    });

    return {
      loading: core.loading,
      version,
      refresh,

      // Raw responses, each carrying its own error rather than one shared
      // "something failed" — a dead psql and a dead ETL API look identical
      // otherwise, and they need different fixes.
      health: core.health,
      verify: core.verify,
      conceptsResult: core.concepts,
      treeResult: core.tree,
      cohortsResult: core.cohorts,
      modelsResult: core.models,
      modelTypesResult: core.modelTypes,

      concepts,
      tree,
      cohorts,
      models: modelList,
      modelTypes: core.modelTypes?.data ?? [],
      configs,
      metrics,

      projects,
      unattributed,
      alerts,

      watcher: live.watcher,
      watcherError: live.watcherError,
      jobs: live.jobs,
      jobsError: live.jobsError,
      jobsLoaded: live.jobsLoaded,
      // The alert set is only meaningful once the reads it is computed from
      // have landed. Until then "no alerts" means "not asked yet".
      alertsKnown: !core.loading && live.jobsLoaded,
      startWatcher,

      containers: containerStates(core, live),
    };
  }, [core, configs, metrics, live, version, refresh, startWatcher]);

  return (
    <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace outside WorkspaceProvider");
  return value;
}

/**
 * Container state, as far as the API can actually prove it.
 *
 * The database container is knowable: /verify-load runs `psql` inside it and
 * reports status "error" when that fails, on every call.
 *
 * The ETL container is not, and this says so rather than guessing. Neither
 * probe that touches it is sound:
 *
 *   /watcher      never checks the exec return code. It parses stdout and
 *                 reports zero hits, so a container that is not running
 *                 returns {running: false, count: 0} with a 200 — byte for
 *                 byte what a live container with a stopped daemon returns.
 *   /ml-model-types  does check the return code, but _registry_pairs is
 *                 wrapped in @lru_cache(maxsize=1). After one success the
 *                 backend never probes again, so it keeps serving the cached
 *                 registry long after the container has gone away.
 *
 * An earlier version of this file read reachability off one and then the
 * other, and both reported a stopped container as "reachable".
 */
function containerStates(core, live) {
  const backendUp = !!core.health?.data;
  const backendKnown = !core.loading;

  function state(ok, via) {
    if (!backendKnown) return { state: "checking", via };
    if (!backendUp) return { state: "unknown", via };
    return { state: ok ? "reachable" : "unreachable", via };
  }

  return [
    {
      id: "postgres",
      role: "database container",
      ...state(core.verify?.data?.status === "ok", "row-count query"),
    },
    {
      id: "etl",
      role: "ETL container",
      state: "not determinable",
      via: "no sound probe",
      why:
        "The watcher probe ignores its exit code and the registry probe is " +
        "cached after its first success, so neither can tell a stopped " +
        "container from a running one.",
    },
  ];
}
