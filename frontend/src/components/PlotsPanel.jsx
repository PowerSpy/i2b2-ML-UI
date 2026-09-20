import { useEffect, useState } from "react";

import { apiGet } from "../lib/api.js";

/*
 * Titles for the plots a build can produce. A key the build did not produce is
 * skipped rather than rendered empty — feature importance is absent for KNN,
 * naive Bayes and the dummy baseline, which expose neither coefficients nor
 * importances.
 */
export const PLOT_TITLES = {
  plot_roc: "ROC curve",
  plot_pr: "Precision–recall",
  plot_confusion_matrix: "Confusion matrix",
  plot_feature_importance: "Feature importance",
  plot_calibration: "Calibration",
};

/**
 * Diagnostic plots for a built model.
 *
 * They are base64 PNGs stored in the concept blob and run to a few hundred KB
 * per model, so this is a separate request from the metrics and is only made
 * by the page that shows them.
 */
export function usePlots(code, refreshKey = 0) {
  const [state, setState] = useState({ loading: true });

  useEffect(() => {
    if (!code) {
      setState({ loading: false });
      return;
    }
    let alive = true;
    setState({ loading: true });
    apiGet(`/ml-concepts/${encodeURIComponent(code)}/plots`)
      .then((data) => alive && setState({ loading: false, data }))
      .catch((e) => alive && setState({ loading: false, error: e.message }));
    return () => {
      alive = false;
    };
  }, [code, refreshKey]);

  return state;
}

/** One PNG from the blob, with a download link to the same data URI. */
export function PlotFigure({ code, name, images, className = "" }) {
  const base64 = images?.[name];
  if (!base64) return null;
  const src = `data:image/png;base64,${base64}`;

  return (
    <figure className={className}>
      <img
        src={src}
        alt={PLOT_TITLES[name] ?? name}
        className="w-full rounded-row border border-border-soft bg-white"
      />
      <figcaption className="mt-2 flex items-baseline justify-between text-[11px] text-text-muted">
        <span>{PLOT_TITLES[name] ?? name}</span>
        <a
          href={src}
          download={`${code}_${name.replace("plot_", "")}.png`}
          className="font-mono text-text-muted hover:text-text-2"
        >
          png
        </a>
      </figcaption>
    </figure>
  );
}
