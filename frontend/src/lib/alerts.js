import { count, plural } from "./format.js";
import { clfMismatch } from "./projects.js";
import { href } from "./router.jsx";

/**
 * "Needs attention", derived from data the API already returns.
 *
 * Every entry here is a condition the warehouse will not complain about on its
 * own: each one is a state where a step reports success and the result is
 * wrong. Nothing in this file is a guess about data we do not have — if a
 * check cannot be computed from a real response it is not in the list.
 */

const LEAKAGE_AUC = 0.98;

export function buildAlerts({
  watcher,
  watcherError,
  cohorts = [],
  models = [],
  metrics = {},
  jobs = [],
  projects = [],
  unattributed = [],
}) {
  const alerts = [];
  const projectOf = (code) => projects.find((p) => p.models.some((m) => m.code === code));

  if (watcherError) {
    alerts.push({
      id: "watcher-unreachable",
      tone: "danger",
      title: "watcher unreachable",
      body: `The job watcher could not be probed (${watcherError}). Until this clears, nothing here can tell a queued job from a dead one.`,
    });
  } else if (watcher && !watcher.running) {
    alerts.push({
      id: "watcher-stopped",
      tone: "danger",
      title: "no job watcher running",
      // Not phrased as "the daemon is stopped". watcher_status() reports zero
      // hits without checking its exit code, so a container that is not
      // running answers 200 with count 0 — identical to a live container with
      // a stopped daemon. Starting the watcher fixes one and not the other.
      body: "Jobs queue and never run. Submitting a build still returns success, so this is silent everywhere except here. The probe cannot tell a stopped daemon from a stopped ETL container — if starting it changes nothing, check the container itself.",
      action: { label: "Start watcher", kind: "start-watcher" },
    });
  } else if (watcher && watcher.count > 1) {
    alerts.push({
      id: "watcher-doubled",
      tone: "warn",
      title: "two watchers polling",
      body: `${watcher.count} job watchers are running against one queue. A job can be picked up twice, and two builds of the same model delete each other's facts.`,
    });
  }

  const duplicates = cohorts.filter((c) => c.duplicate);
  if (duplicates.length) {
    const names = [...new Set(duplicates.map((c) => c.name))];
    alerts.push({
      id: "cohort-duplicate",
      tone: "danger",
      title: "duplicate cohort name",
      body: `${names.join(", ")} names more than one patient set. Training resolves a name to every matching set and unions them, so a model trains on a population nobody chose.`,
      to: href.section("cohorts"),
    });
  }

  const drifted = cohorts.filter((c) => c.stale);
  if (drifted.length) {
    const names = drifted.map((c) => c.name);
    alerts.push({
      id: "cohort-drift",
      tone: "warn",
      title: "cohort drift",
      body: `${names.join(", ")} ${plural(names.length, "lists", "list")} members that no longer have facts. Recorded size and live size disagree, so any model trained on ${plural(names.length, "it", "them")} used fewer patients than its size claims.`,
      to: href.section("cohorts"),
    });
  }

  const stranded = models.filter((m) => m.is_built && m.features_present === false);
  if (stranded.length) {
    alerts.push({
      id: "features-gone",
      tone: "danger",
      title: "trained on data that is gone",
      body: `${stranded.map((m) => m.code).join(", ")} ${plural(stranded.length, "is", "are")} still marked built, but the features ${plural(stranded.length, "it", "they")} learned from have no facts left. Applying ${plural(stranded.length, "it", "them")} scores every patient off zero-filled columns.`,
      to: stranded.length === 1 ? href.model(stranded[0].code) : href.section("models"),
    });
  }

  for (const m of models) {
    const mismatch = clfMismatch(metrics[m.code]?.data);
    if (!mismatch) continue;
    alerts.push({
      id: `clf-mismatch-${m.code}`,
      tone: "danger",
      title: "registry not wired through",
      body: `${m.code} asked for ${mismatch.expected} and fitted ${mismatch.actual} instead. build_model() falls back to logistic regression for a key it does not recognise, without erroring — the numbers describe a different model than the one requested.`,
      to: href.model(m.code),
    });
  }

  for (const m of models) {
    const auc = metrics[m.code]?.data?.headline?.roc_auc;
    if (typeof auc !== "number" || auc < LEAKAGE_AUC) continue;
    const project = projectOf(m.code);
    alerts.push({
      id: `leakage-${m.code}`,
      tone: "warn",
      title: "possible leakage",
      body: `${m.code} reaches ${auc.toFixed(2)} ROC AUC. Anything at or above ${LEAKAGE_AUC} on clinical data usually means a feature that is recorded after the outcome, not before it.`,
      to: project ? href.benchmark(project.id) : href.model(m.code),
    });
  }

  const failed = jobs.filter((j) => j.status === "ERROR");
  if (failed.length) {
    alerts.push({
      id: "jobs-failed",
      tone: "danger",
      title: `${failed.length} failed ${plural(failed.length, "job")}`,
      body: `${failed.map((j) => `job ${j.id}`).join(", ")} ended in ERROR. The stack trace on the job row is the only record of why.`,
    });
  }

  if (unattributed.length) {
    alerts.push({
      id: "models-unattributed",
      tone: "warn",
      title: "models outside every project",
      body: `${unattributed.map((m) => m.code).join(", ")} ${plural(unattributed.length, "has", "have")} no readable data path, so ${plural(unattributed.length, "it", "they")} cannot be filed under a concept subtree. ${plural(unattributed.length, "Its", "Their")} config either failed to parse or points nowhere.`,
      to: href.section("models"),
    });
  }

  const unrecorded = models.filter(
    (m) => m.is_built && metrics[m.code]?.data && !metrics[m.code].data.clf_type,
  );
  if (unrecorded.length) {
    alerts.push({
      id: "clf-unrecorded",
      tone: "warn",
      title: "estimator class not recorded",
      body: `${unrecorded.map((m) => m.code).join(", ")} ${plural(unrecorded.length, "was", "were")} built before the registry patch, so what actually trained was never written down. Rebuild to record it.`,
      to: href.section("models"),
    });
  }

  // Danger before warning; otherwise the order the checks happen to run in
  // decides what the reader sees first.
  const rank = { danger: 0, warn: 1 };
  return alerts.sort((a, b) => rank[a.tone] - rank[b.tone]);
}

/** One-line summary for the left rail's data health count. */
export function attentionCount(alerts) {
  return count(alerts.length);
}
