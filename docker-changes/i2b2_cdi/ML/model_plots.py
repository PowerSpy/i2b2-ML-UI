"""
Diagnostic plot generation for the i2b2-etl ML pipeline.

Renders matplotlib figures at the end of a model build and returns them as
base64-encoded PNGs, so they can be stored in the concept_blob alongside the
existing scalar metrics and displayed directly in the model builder UI via
<img src="data:image/png;base64,...">.

This avoids adding any new endpoint or file-serving path - the plots travel
back on the same poll the UI already performs for accuracy/ROC-AUC.

USAGE (from apply_build_model_ml.py, after predictions are computed):

    from i2b2_cdi.ML.model_plots import generate_plots

    plots = generate_plots(
        y_true=y_test,
        y_pred=y_pred,
        y_proba=y_proba,          # optional; enables ROC / PR / calibration
        model_name=name,
        feature_names=selected_feature_names,   # optional
        importances=importances,                # optional
    )
    blob.update(plots)            # adds plot_confusion_matrix, plot_roc, ...

DESIGN NOTES:
  - Matplotlib runs headless in the container, so the Agg backend is forced
    before pyplot is imported. Importing pyplot without this can fail or hang
    when no display is available.
  - Figures are deliberately small and low-DPI. Every plot is base64 text in
    a database column, so size matters far more than print quality. See
    DEFAULT_DPI / DEFAULT_FIGSIZE and the TOTAL_BUDGET_BYTES guard.
  - Every plot is individually wrapped: a failure to render one figure must
    never fail the model build, which is the expensive part of the job.
  - If matplotlib is not installed, generate_plots() returns confusion matrix
    counts only and logs a warning. The build still succeeds.
"""

import base64
import io
import logging

logger = logging.getLogger(__name__)

# Small figures, low DPI: these are inline diagnostics, not publication output.
# A confusion matrix at these settings is roughly 15-25 KB before base64.
DEFAULT_FIGSIZE = (4.0, 3.2)
DEFAULT_DPI = 80

# Hard ceiling on the combined size of all plots for a single model, after
# base64 encoding. Blobs are stored as text in the database and polled by the
# browser on an interval; an unbounded payload here degrades both. Plots are
# added in priority order and dropped once the budget is exhausted.
TOTAL_BUDGET_BYTES = 400_000

try:
    import matplotlib
    matplotlib.use("Agg")          # must precede the pyplot import
    import matplotlib.pyplot as plt
    _MATPLOTLIB_AVAILABLE = True
except Exception as exc:           # ImportError, or a backend failure
    _MATPLOTLIB_AVAILABLE = False
    logger.warning(
        "matplotlib unavailable (%s); model builds will return confusion "
        "matrix counts but no plot images.", exc
    )


def _fig_to_base64(fig, dpi=DEFAULT_DPI):
    """Serialize a figure to a base64 PNG string and close it."""
    try:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("ascii")
    finally:
        # Always close, even if savefig raised - pyplot keeps a global
        # reference to every open figure, so leaking them in a long-running
        # worker process is a genuine memory leak.
        plt.close(fig)


def _confusion_counts(y_true, y_pred):
    """
    Confusion matrix counts as plain integers.

    Computed independently of matplotlib so the numbers are still available
    when plotting is unavailable, and so the UI can display a text table
    without decoding an image.
    """
    from sklearn.metrics import confusion_matrix

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    return {
        "confusion_tn": int(tn),
        "confusion_fp": int(fp),
        "confusion_fn": int(fn),
        "confusion_tp": int(tp),
    }


def _plot_confusion_matrix(y_true, y_pred, model_name):
    """
    Confusion matrix heatmap with raw counts and row-normalized percentages.

    Both are shown because they answer different questions: counts show how
    many patients are involved, percentages show the error profile
    independent of class balance - which matters here, since the pipeline
    applies SMOTE and the underlying cohorts are often imbalanced.
    """
    import numpy as np
    from sklearn.metrics import confusion_matrix

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    row_sums = cm.sum(axis=1, keepdims=True)
    # A class absent from the test set gives a zero row sum. Supplying an
    # explicit zeroed `out` matters: `where` alone leaves the skipped cells
    # uninitialized rather than zero.
    cm_pct = np.zeros(cm.shape, dtype=float)
    np.divide(cm, row_sums, out=cm_pct, where=row_sums != 0)
    cm_pct *= 100

    fig, ax = plt.subplots(figsize=DEFAULT_FIGSIZE)
    im = ax.imshow(cm_pct, cmap="Blues", vmin=0, vmax=100)

    labels = ["Negative", "Positive"]
    ax.set_xticks([0, 1], labels=labels)
    ax.set_yticks([0, 1], labels=labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title("Confusion Matrix - %s" % model_name, fontsize=10)

    for i in range(2):
        for j in range(2):
            # White text on dark cells, dark text on light ones.
            color = "white" if cm_pct[i, j] > 50 else "black"
            ax.text(
                j, i,
                "%d\n(%.1f%%)" % (cm[i, j], cm_pct[i, j]),
                ha="center", va="center", color=color, fontsize=9,
            )

    fig.colorbar(im, ax=ax, label="% of actual class")
    return _fig_to_base64(fig)


def _plot_roc_curve(y_true, y_proba, model_name):
    """ROC curve with AUC, against the no-skill diagonal."""
    from sklearn.metrics import roc_curve, roc_auc_score

    fpr, tpr, _ = roc_curve(y_true, y_proba)
    auc = roc_auc_score(y_true, y_proba)

    fig, ax = plt.subplots(figsize=DEFAULT_FIGSIZE)
    ax.plot(fpr, tpr, linewidth=2, label="AUC = %.3f" % auc)
    ax.plot([0, 1], [0, 1], linestyle="--", linewidth=1,
            color="grey", label="No skill")
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("ROC Curve - %s" % model_name, fontsize=10)
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(alpha=0.3)
    return _fig_to_base64(fig)


def _plot_pr_curve(y_true, y_proba, model_name):
    """
    Precision-recall curve with average precision.

    More informative than ROC on imbalanced cohorts: the no-skill baseline
    is the positive class prevalence rather than a fixed diagonal, so it is
    drawn explicitly for reference.
    """
    import numpy as np
    from sklearn.metrics import precision_recall_curve, average_precision_score

    precision, recall, _ = precision_recall_curve(y_true, y_proba)
    ap = average_precision_score(y_true, y_proba)
    prevalence = float(np.mean(y_true))

    fig, ax = plt.subplots(figsize=DEFAULT_FIGSIZE)
    ax.plot(recall, precision, linewidth=2, label="AP = %.3f" % ap)
    ax.axhline(prevalence, linestyle="--", linewidth=1, color="grey",
               label="No skill (%.3f)" % prevalence)
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title("Precision-Recall - %s" % model_name, fontsize=10)
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(alpha=0.3)
    return _fig_to_base64(fig)


def _plot_calibration(y_true, y_proba, model_name, n_bins=8):
    """
    Calibration curve: are predicted probabilities trustworthy as risk
    estimates?

    Relevant for clinical use, where a model's "70% risk" should mean roughly
    70 of 100 such patients have the outcome. Note that SMOTE in the pipeline
    distorts calibration by design, so poor calibration here is expected and
    is a reason to calibrate before deployment rather than a bug.
    """
    from sklearn.calibration import calibration_curve

    # Few bins for small test sets, otherwise the curve is mostly noise.
    n_bins = max(3, min(n_bins, len(y_true) // 10))

    prob_true, prob_pred = calibration_curve(y_true, y_proba, n_bins=n_bins)

    fig, ax = plt.subplots(figsize=DEFAULT_FIGSIZE)
    ax.plot(prob_pred, prob_true, marker="o", linewidth=2, label=model_name)
    ax.plot([0, 1], [0, 1], linestyle="--", linewidth=1,
            color="grey", label="Perfectly calibrated")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed frequency")
    ax.set_title("Calibration - %s" % model_name, fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.3)
    return _fig_to_base64(fig)


def _plot_feature_importance(feature_names, importances, model_name, top_n=15):
    """
    Horizontal bar chart of the strongest features.

    Accepts either tree importances or linear coefficients; ranking is by
    absolute value so negative coefficients are not buried at the bottom.
    Bars are signed where the underlying values are signed, so direction of
    effect stays visible.
    """
    import numpy as np

    names = list(feature_names)
    values = np.asarray(importances, dtype=float).ravel()

    if len(names) != len(values):
        logger.warning(
            "feature_names (%d) and importances (%d) length mismatch; "
            "skipping feature importance plot.", len(names), len(values)
        )
        return None

    order = np.argsort(np.abs(values))[::-1][:top_n]
    top_names = [names[i] for i in order][::-1]
    top_values = values[order][::-1]

    height = max(DEFAULT_FIGSIZE[1], 0.25 * len(top_names) + 1.0)
    fig, ax = plt.subplots(figsize=(DEFAULT_FIGSIZE[0] + 1.5, height))

    colors = ["#c44e52" if v < 0 else "#4c72b0" for v in top_values]
    ax.barh(range(len(top_values)), top_values, color=colors)
    ax.set_yticks(range(len(top_names)), labels=top_names, fontsize=8)
    ax.set_xlabel("Importance / coefficient")
    ax.set_title("Top features - %s" % model_name, fontsize=10)
    ax.grid(axis="x", alpha=0.3)
    return _fig_to_base64(fig)


def generate_plots(
    y_true,
    y_pred,
    y_proba=None,
    model_name="model",
    feature_names=None,
    importances=None,
    include=None,
):
    """
    Build the diagnostic plot set for one trained model.

    Args:
        y_true:        ground-truth labels for the held-out test set.
        y_pred:        predicted labels.
        y_proba:       predicted probability of the positive class. Optional;
                       ROC, PR and calibration plots are skipped without it.
        model_name:    display name, used in figure titles.
        feature_names: names of features fed to the classifier. Optional.
        importances:   importances or coefficients aligned with feature_names.
        include:       optional list restricting which plots are produced,
                       e.g. ["confusion_matrix", "roc"]. Defaults to all.

    Returns:
        dict suitable for merging into concept_blob. Always contains the four
        confusion matrix counts. Image entries are base64 PNG strings under
        keys prefixed "plot_", and are omitted where unavailable.

    This function never raises: a plotting failure degrades the result to
    fewer plots rather than failing a model build that has already done the
    expensive work.
    """
    out = {}

    # Counts first - cheap, useful on their own, and independent of matplotlib.
    try:
        out.update(_confusion_counts(y_true, y_pred))
    except Exception as exc:
        logger.warning("Could not compute confusion matrix counts: %s", exc)

    if not _MATPLOTLIB_AVAILABLE:
        return out

    # ROC, PR and calibration are undefined when the test set contains a
    # single class - sklearn returns NaN AUCs and warns. Rendering them anyway
    # produces a plausible-looking but meaningless figure, so skip them and
    # leave the confusion matrix, which is still valid.
    try:
        import numpy as np
        n_classes = len(np.unique(np.asarray(y_true)))
    except Exception:
        n_classes = 2

    if n_classes < 2:
        logger.warning(
            "Test set contains a single class; skipping threshold-based "
            "plots (ROC, PR, calibration)."
        )

    has_proba = y_proba is not None and n_classes >= 2

    # Ordered by diagnostic value, since the size budget is applied in order.
    candidates = [
        ("confusion_matrix", lambda: _plot_confusion_matrix(y_true, y_pred, model_name)),
    ]
    if has_proba:
        candidates += [
            ("roc", lambda: _plot_roc_curve(y_true, y_proba, model_name)),
            ("pr", lambda: _plot_pr_curve(y_true, y_proba, model_name)),
        ]
    if feature_names is not None and importances is not None:
        candidates.append(
            ("feature_importance",
             lambda: _plot_feature_importance(feature_names, importances, model_name))
        )
    if has_proba:
        candidates.append(
            ("calibration", lambda: _plot_calibration(y_true, y_proba, model_name))
        )

    if include is not None:
        wanted = set(include)
        candidates = [c for c in candidates if c[0] in wanted]

    used = 0
    for key, render in candidates:
        try:
            encoded = render()
            if not encoded:
                continue
            if used + len(encoded) > TOTAL_BUDGET_BYTES:
                logger.warning(
                    "Plot budget (%d bytes) reached; skipping '%s' and any "
                    "remaining plots.", TOTAL_BUDGET_BYTES, key
                )
                break
            out["plot_" + key] = encoded
            used += len(encoded)
        except Exception as exc:
            # One bad plot must not cost the caller a completed model build.
            logger.warning("Failed to render '%s' plot: %s", key, exc)

    return out


def extract_feature_info(pipeline, feature_names):
    """
    Pull feature names and importances out of a fitted pipeline, if the
    classifier exposes them.

    The pipeline is scale -> SMOTE -> feature selection -> classifier, so the
    classifier only ever sees the subset the selector kept. This maps back
    through the selector's support mask to recover the original names.

    Returns (names, importances), or (None, None) when the classifier exposes
    neither coefficients nor importances - which is the case for KNN, Naive
    Bayes, and the dummy baseline.
    """
    try:
        clf = pipeline.named_steps.get("clf")
        selector = pipeline.named_steps.get("selector")

        if clf is None:
            return None, None

        if hasattr(clf, "feature_importances_"):
            values = clf.feature_importances_
        elif hasattr(clf, "coef_"):
            values = clf.coef_
        else:
            return None, None

        names = list(feature_names)
        if selector is not None and hasattr(selector, "get_support"):
            mask = selector.get_support()
            names = [n for n, keep in zip(names, mask) if keep]

        return names, values

    except Exception as exc:
        logger.warning("Could not extract feature importances: %s", exc)
        return None, None
