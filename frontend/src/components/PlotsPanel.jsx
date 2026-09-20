import { useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";

/*
 * Display order and titles. A key the build did not produce is skipped rather
 * than rendered empty — feature importance is absent for KNN, naive Bayes and
 * the dummy baseline, which expose neither coefficients nor importances.
 */
const PLOTS = [
  ["plot_confusion_matrix", "Confusion matrix"],
  ["plot_roc", "ROC curve"],
  ["plot_pr", "Precision–recall"],
  ["plot_feature_importance", "Feature importance"],
  ["plot_calibration", "Calibration"],
];

/**
 * Diagnostic plots for a built model, fetched separately from the metrics.
 *
 * They are base64 PNGs stored in the concept blob and run to a few hundred KB
 * per model, so this only loads once opened.
 */
export default function PlotsPanel({ code, refreshKey = 0 }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
    setOpen(false);
  }, [code, refreshKey]);

  useEffect(() => {
    if (!open || !code || data) return;
    let alive = true;
    apiGet(`/ml-concepts/${code}/plots`)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [open, code, data]);

  if (!code) return null;

  const available = data
    ? PLOTS.filter(([key]) => data.images[key])
    : [];

  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="text-xs text-neutral-500 hover:text-neutral-300"
      >
        {open ? "hide" : "show"} diagnostic plots
      </button>

      {open && (
        <div className="mt-3 space-y-4">
          {error && <p className="text-xs text-red-400">{error}</p>}
          {!data && !error && (
            <p className="text-xs text-neutral-500">loading plots…</p>
          )}

          {data && available.length === 0 && (
            <p className="text-xs text-neutral-500">
              This build produced no plots — it predates the plotting patch, or
              matplotlib was unavailable when it ran. Rebuild to get them.
            </p>
          )}

          {available.length > 0 && (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                {available.map(([key, title]) => {
                  const src = `data:image/png;base64,${data.images[key]}`;
                  return (
                    <figure key={key} className="space-y-1">
                      <figcaption className="flex items-baseline justify-between text-xs text-neutral-400">
                        <span>{title}</span>
                        <a
                          href={src}
                          download={`${code}_${key.replace("plot_", "")}.png`}
                          className="text-neutral-600 hover:text-neutral-300"
                        >
                          png
                        </a>
                      </figcaption>
                      <img
                        src={src}
                        alt={title}
                        className="w-full rounded border border-neutral-800 bg-white"
                      />
                    </figure>
                  );
                })}
              </div>

              {Object.keys(data.counts_at_half).length > 0 && (
                <div className="space-y-1">
                  <div className="inline-grid grid-cols-3 gap-x-3 gap-y-1 text-xs tabular-nums">
                    <span />
                    <span className="text-neutral-500">pred +</span>
                    <span className="text-neutral-500">pred −</span>
                    <span className="text-neutral-500">actual +</span>
                    <span className="text-emerald-400">{data.counts_at_half.tp}</span>
                    <span className="text-red-400">{data.counts_at_half.fn}</span>
                    <span className="text-neutral-500">actual −</span>
                    <span className="text-red-400">{data.counts_at_half.fp}</span>
                    <span className="text-emerald-400">{data.counts_at_half.tn}</span>
                  </div>
                  <p className="text-xs text-amber-300/70">{data.note}</p>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
