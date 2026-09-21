import { titleFromSegment } from "./format.js";

/**
 * Projects, derived rather than stored.
 *
 * The backend has no notion of a project — i2b2 has one concept table and one
 * fact table for everything. What it does have is a concept path per concept,
 * so the top-level segment of that path is the only grouping in the data. A
 * project here *is* that subtree: /HeartDisease is one project, /DiabetesSample
 * another. Nothing is invented; if two datasets share a root they are one
 * project, because as far as the warehouse is concerned they are.
 *
 * Models do not live under it — they are concepts under /ML — so a model is
 * attributed to a project by the root of its own data and label paths, read
 * from its stored config.
 */

/** Where models are stored. Mirrors `ml_root` in app/core/config.py. */
export const ML_ROOT = "/ML";

export function rootOf(path) {
  if (typeof path !== "string") return null;
  const segment = path.replace(/^\/+/, "").split("/")[0];
  return segment ? `/${segment}` : null;
}

export function under(path, root) {
  return typeof path === "string" && (path === root || path.startsWith(`${root}/`));
}

function isModelRoot(root) {
  return root === ML_ROOT;
}

/**
 * The project a model belongs to, or null when it cannot be told.
 *
 * A config that failed to load, or one whose paths are all under /ML, leaves
 * the model unattributed — which is surfaced rather than guessed at, because
 * silently filing it under the first project would be a lie about what it was
 * trained on.
 */
export function projectRootForModel(config) {
  if (!config) return null;
  const paths = [...(config.data_paths ?? []), ...(config.label_paths ?? [])];
  for (const p of paths) {
    const root = rootOf(p);
    if (root && !isModelRoot(root)) return root;
  }
  return null;
}

/**
 * @param concepts  /api/concepts
 * @param tree      /api/concept-tree
 * @param models    /api/ml-concepts
 * @param configs   code -> { data, error } from /api/ml-concepts/{code}/config
 * @param metrics   code -> { data, error } from /api/ml-concepts/{code}/metrics
 */
export function buildProjects({
  concepts = [],
  tree = [],
  models = [],
  configs = {},
  metrics = {},
}) {
  const byRoot = new Map();

  function ensure(root) {
    if (!byRoot.has(root)) {
      byRoot.set(root, {
        id: root.replace(/^\//, ""),
        root,
        name: titleFromSegment(root.replace(/^\//, "")),
        concepts: [],
        paths: [],
        models: [],
      });
    }
    return byRoot.get(root);
  }

  for (const c of concepts) {
    const root = rootOf(c.path);
    // /ML holds the models themselves, not data. It is a store, not a project.
    if (!root || isModelRoot(root)) continue;
    ensure(root).concepts.push(c);
  }

  for (const p of tree) {
    const root = rootOf(p);
    if (!root || isModelRoot(root) || !byRoot.has(root)) continue;
    byRoot.get(root).paths.push(p);
  }

  const unattributed = [];
  for (const m of models) {
    const root = projectRootForModel(configs[m.code]?.data);
    // A root the concepts no longer mention still gets a project: the model
    // was trained against it, and hiding it would hide the model too.
    if (root) ensure(root).models.push(m);
    else unattributed.push(m);
  }

  for (const project of byRoot.values()) {
    project.paths.sort();
    project.concepts.sort((a, b) => a.path.localeCompare(b.path));
    project.models.sort((a, b) => a.code.localeCompare(b.code));
    project.best = bestModel(project.models, metrics);
    project.roles = pathRoles(project, configs);
  }

  const projects = [...byRoot.values()].sort((a, b) => a.root.localeCompare(b.root));
  return { projects, unattributed };
}

export function findProject(projects, id) {
  return projects.find((p) => p.id === id) ?? null;
}

/** Highest ROC AUC among this project's built models. */
export function bestModel(models, metrics) {
  let best = null;
  for (const m of models) {
    const data = metrics[m.code]?.data;
    const auc = data?.headline?.roc_auc;
    if (typeof auc !== "number") continue;
    if (!best || auc > best.auc) {
      // The registry's display name where it was recorded, falling back to the
      // key that was requested. Those disagree exactly when the registry is
      // miswired, which is flagged separately.
      best = { model: m, auc, name: data.model_name ?? m.model_type ?? m.code };
    }
  }
  return best;
}

/**
 * Which paths this project's models read as features and which as the label.
 *
 * A path can be both — the label subtree is often nested inside the data
 * subtree — so this returns a set per role rather than one role per path.
 */
export function pathRoles(project, configs) {
  const feature = new Set();
  const label = new Set();

  for (const m of project.models) {
    const cfg = configs[m.code]?.data;
    if (!cfg) continue;
    for (const p of cfg.data_paths ?? []) if (under(p, project.root)) feature.add(p);
    for (const p of cfg.label_paths ?? []) if (under(p, project.root)) label.add(p);
  }
  return { feature, label };
}

/** Rank a project's built models by ROC AUC, for the benchmark leaderboard. */
export function leaderboard(models, metrics) {
  return models
    .map((m) => ({ model: m, metrics: metrics[m.code]?.data ?? null }))
    .filter((row) => row.metrics)
    .sort((a, b) => {
      const av = a.metrics.headline?.roc_auc ?? -1;
      const bv = b.metrics.headline?.roc_auc ?? -1;
      return bv - av;
    });
}

/**
 * The registry's display name for a model key against the estimator class it
 * should produce. A mismatch means build_model() fell through to its logistic
 * regression default, which it does silently for an unknown key.
 */
export const EXPECTED_CLF = {
  RandomForest: "RandomForestClassifier",
  SVM: "SVC",
  LogisticRegression: "LogisticRegression",
  XGBoost: "XGBClassifier",
  KNN: "KNeighborsClassifier",
  NaiveBayes: "GaussianNB",
  DecisionTree: "DecisionTreeClassifier",
  DummyBaseline: "DummyClassifier",
  ANN: "MLPClassifier",
};

export function clfMismatch(metrics) {
  const expected = EXPECTED_CLF[metrics?.model_name];
  const actual = metrics?.clf_type;
  return expected && actual && expected !== actual ? { expected, actual } : null;
}
