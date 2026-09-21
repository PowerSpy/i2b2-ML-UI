import { score } from "../lib/format.js";
import { clfMismatch } from "../lib/projects.js";
import { href, Link } from "../lib/router.jsx";
import { useWorkspace } from "../lib/workspace.jsx";
import { Empty } from "../ui/Callout.jsx";
import Meter from "../ui/Meter.jsx";
import { Status } from "../ui/Status.jsx";
import { Mono, Num, SectionLabel } from "../ui/Text.jsx";

/**
 * A model list, shared by the workspace section and the project page.
 *
 * The flags on a row are the ones that make a headline number untrustworthy:
 * a cohort that drifted after training, features that no longer exist, and an
 * estimator class that does not match the algorithm requested.
 */
export default function ModelsList({ models, showProject = false, empty }) {
  const { metrics, configs, cohorts, projects } = useWorkspace();

  if (!models.length) {
    return <Empty>{empty ?? "No models defined yet."}</Empty>;
  }

  // Best first, then anything built without a recorded AUC, then config-only
  // models. Alphabetical order buried the model you would actually reach for.
  const ordered = [...models].sort((a, b) => {
    const av = metrics[a.code]?.data?.headline?.roc_auc;
    const bv = metrics[b.code]?.data?.headline?.roc_auc;
    if (typeof av === "number" && typeof bv === "number") return bv - av;
    if (typeof av === "number") return -1;
    if (typeof bv === "number") return 1;
    if (a.is_built !== b.is_built) return a.is_built ? -1 : 1;
    return a.code.localeCompare(b.code);
  });

  return (
    <ul className="space-y-2">
      {ordered.map((m) => (
        <ModelRow
          key={m.code}
          model={m}
          metrics={metrics[m.code]?.data}
          config={configs[m.code]?.data}
          cohorts={cohorts}
          project={
            showProject ? projects.find((p) => p.models.some((x) => x.code === m.code)) : null
          }
        />
      ))}
    </ul>
  );
}

function ModelRow({ model, metrics, config, cohorts, project }) {
  const auc = metrics?.headline?.roc_auc;
  const flags = flagsFor({ model, metrics, config, cohorts });

  return (
    <li>
      <Link
        to={href.model(model.code)}
        className="flex items-center gap-4 rounded-row border border-border-soft bg-panel-sunk px-4 py-3.5 transition-colors hover:border-border-strong"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <Mono className="text-[13px] text-text">{model.code}</Mono>
            <span className="text-[13px] text-text-2">
              {metrics?.model_name ?? model.model_type ?? "algorithm not recorded"}
            </span>
            {/* The ETL defaults a model's description to its own code, so
                showing both prints the code twice. */}
            {model.description && model.description !== model.code && (
              <span className="truncate text-[12px] text-text-muted">
                {model.description}
              </span>
            )}
          </div>

          {(flags.length > 0 || project) && (
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
              {project && (
                <span className="text-[11px] text-text-muted">
                  in <span className="text-text-3">{project.name}</span>
                </span>
              )}
              {flags.map((f) => (
                <Status key={f.label} tone={f.tone} className="text-[11px]">
                  {f.label}
                </Status>
              ))}
            </div>
          )}
        </div>

        <div className="w-[150px] shrink-0">
          {model.is_built ? (
            <>
              <div className="flex items-baseline justify-end gap-2">
                <Num
                  className={`text-[17px] ${auc == null ? "text-text-muted" : "text-text"}`}
                >
                  {score(auc)}
                </Num>
                <SectionLabel>roc auc</SectionLabel>
              </div>
              <Meter
                value={auc}
                tone={auc == null ? "neutral" : auc >= 0.8 ? "positive" : auc >= 0.6 ? "warn" : "neutral"}
                className="mt-2"
              />
            </>
          ) : (
            <p className="text-right text-[12px] text-text-muted">config only</p>
          )}
        </div>
      </Link>
    </li>
  );
}

/** Everything about a model that a single AUC would hide. */
function flagsFor({ model, metrics, config, cohorts }) {
  const flags = [];

  if (!model.is_built) {
    flags.push({ tone: "idle", label: "not built" });
  }

  if (model.is_built && model.features_present === false) {
    flags.push({ tone: "danger", label: "training data deleted" });
  }

  const mismatch = clfMismatch(metrics);
  if (mismatch) {
    flags.push({ tone: "danger", label: `fitted ${mismatch.actual}, not ${mismatch.expected}` });
  }

  if (metrics && !metrics.clf_type) {
    flags.push({ tone: "warn", label: "estimator class not recorded" });
  }

  // A cohort that gained or lost members after the model trained no longer
  // describes the set the model claims to have learned from.
  const used = new Set([
    ...(config?.positive_patient_set ?? []),
    ...(config?.negative_patient_set ?? []),
  ]);
  const drifted = cohorts.filter((c) => used.has(c.name) && c.stale).map((c) => c.name);
  if (drifted.length) {
    flags.push({ tone: "warn", label: `trained on drifted cohort ${drifted.join(", ")}` });
  }

  const ambiguous = cohorts.filter((c) => used.has(c.name) && c.duplicate).map((c) => c.name);
  if (ambiguous.length) {
    flags.push({ tone: "danger", label: `ambiguous cohort ${ambiguous.join(", ")}` });
  }

  return flags;
}
