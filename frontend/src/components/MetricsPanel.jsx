import { useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";

/** Blob metrics for a built model. ROC-AUC leads because it is threshold-free. */
export default function MetricsPanel({ code, refreshKey = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!code) return;
    let alive = true;
    setData(null);
    setError(null);
    apiGet(`/ml-concepts/${code}/metrics`)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [code, refreshKey]);

  if (!code) return null;
  if (error) return <p className="text-xs text-neutral-500">{error}</p>;
  if (!data) return <p className="text-xs text-neutral-500">loading metrics…</p>;

  const roc = data.headline.roc_auc;
  const counts = data.counts;

  return (
    <div className="space-y-4">
      <ModelIdentity data={data} />

      <div className="flex flex-wrap items-end gap-8">
        <div>
          <p className="text-4xl font-semibold tabular-nums text-emerald-400">
            {roc == null ? "—" : roc.toFixed(3)}
          </p>
          <p className="text-xs uppercase tracking-wide text-neutral-500">
            roc-auc
          </p>
        </div>
        {Object.entries(data.headline)
          .filter(([k]) => k !== "roc_auc")
          .map(([k, v]) => (
            <Stat key={k} label={k} value={v.toFixed(3)} />
          ))}
        {data.build_time_sec != null && (
          <Stat label="build time" value={`${data.build_time_sec.toFixed(1)}s`} />
        )}
      </div>

      {Object.keys(data.thresholded).length > 0 && (
        <div>
          <div className="grid grid-cols-2 gap-x-8 gap-y-1 sm:grid-cols-4">
            {Object.entries(data.thresholded).map(([k, v]) => (
              <p key={k} className="flex justify-between text-xs">
                <span className="text-neutral-500">{k}</span>
                <span className="tabular-nums text-neutral-300">
                  {v.toFixed(3)}
                </span>
              </p>
            ))}
          </div>
          <p className="mt-2 text-xs text-neutral-500">{data.threshold_note}</p>
        </div>
      )}

      {counts.true_positive != null && (
        <div className="inline-grid grid-cols-3 gap-x-3 gap-y-1 text-xs tabular-nums">
          <span />
          <span className="text-neutral-500">pred +</span>
          <span className="text-neutral-500">pred −</span>
          <span className="text-neutral-500">actual +</span>
          <span className="text-emerald-400">{counts.true_positive}</span>
          <span className="text-red-400">{counts.false_negative}</span>
          <span className="text-neutral-500">actual −</span>
          <span className="text-red-400">{counts.false_positive}</span>
          <span className="text-emerald-400">{counts.true_negative}</span>
        </div>
      )}

      <div className="flex gap-6 text-xs text-neutral-500">
        {["n_samples", "n_pos", "n_neg"].map(
          (k) =>
            counts[k] != null && (
              <span key={k}>
                {k} <span className="text-neutral-300">{counts[k]}</span>
              </span>
            ),
        )}
      </div>

      {data.features.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-neutral-500">
            {data.features.length} feature(s) selected
          </p>
          <div className="flex flex-wrap gap-1">
            {data.features.map((f) => (
              <span
                key={f}
                className="rounded bg-neutral-800 px-1.5 py-0.5 text-xs text-neutral-300"
              >
                {f}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/*
 * What actually trained, read off the fitted estimator at build time.
 *
 * Worth showing rather than assuming: an unrecognised model_type does not
 * fail the build, it quietly trains logistic regression instead — so the
 * requested algorithm is not evidence of what you got. clf_type is missing on
 * models built before the registry patch, which is itself worth saying.
 */
function ModelIdentity({ data }) {
  const { model_type: type, model_name: name, clf_type: clf } = data;
  const hyper = Object.entries(data.hyperparameters ?? {});

  if (!type && !clf) {
    return (
      <p className="text-xs text-neutral-500">
        Built before model selection existed — algorithm not recorded.
      </p>
    );
  }

  // The registry's own display name for a key, e.g. random_forest →
  // RandomForest; a mismatch against clf_type means the wiring is broken.
  const expected = { RandomForest: "RandomForestClassifier", SVM: "SVC",
    LogisticRegression: "LogisticRegression", XGBoost: "XGBClassifier",
    KNN: "KNeighborsClassifier", NaiveBayes: "GaussianNB",
    DecisionTree: "DecisionTreeClassifier", DummyBaseline: "DummyClassifier",
    ANN: "MLPClassifier" }[name];
  const mismatch = expected && clf && expected !== clf;

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded bg-neutral-800 px-1.5 py-0.5 text-neutral-200">
          {name ?? type}
        </span>
        {clf && (
          <span className={mismatch ? "text-red-400" : "text-neutral-500"}>
            trained {clf}
          </span>
        )}
        {!clf && (
          <span className="text-neutral-600">
            estimator class not recorded for this build
          </span>
        )}
      </div>

      {mismatch && (
        <p className="rounded border border-red-900 bg-red-950/40 p-2 text-xs text-red-300">
          Asked for {name} but {clf} was trained. The registry is not wired
          through — re-apply the model registry patch before trusting these
          numbers.
        </p>
      )}

      {hyper.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {hyper.map(([k, v]) => (
            <span
              key={k}
              className="rounded bg-neutral-800/60 px-1.5 py-0.5 text-[10px] text-neutral-400"
            >
              {k.replace(/^clf__/, "")}={JSON.stringify(v).replace(/^\[|\]$/g, "")}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div>
      <p className="text-lg font-medium tabular-nums text-neutral-200">{value}</p>
      <p className="text-xs uppercase tracking-wide text-neutral-500">{label}</p>
    </div>
  );
}
