"""The set of models the container can actually build, and their knobs.

The list is read out of the container's MODEL_REGISTRY rather than hardcoded
here, because the two can drift: model_registry.py is installed by a patch and
can be edited in place to add a model. A stale list here would be worse than no
list, since build_model() silently falls back to logistic regression for an
unknown key instead of raising - so an option we offered but the container does
not have would train the wrong model and report success.
"""

import json
import shlex
from functools import lru_cache

from app.core.config import settings
from app.core.docker_exec import exec

# Emits [[key, display_name], ...] for whatever is registered right now. Each
# factory is called because the display name only exists as build_model()'s
# third return value; that just constructs estimators, it does not fit them.
PROBE = """
import json
from i2b2_cdi.ML.model_registry import MODEL_REGISTRY, build_model
out = []
for key in MODEL_REGISTRY:
    try:
        out.append([key, build_model(key)[2]])
    except Exception:
        # A model whose dependency is missing (e.g. xgboost) stays out of the
        # list rather than being offered and failing at build time.
        pass
print(json.dumps(out))
"""

# Per-model hyperparameter fields, ported from HYPERPARAM_FIELDS in the
# reference webclient (CUSTOM_view_ModelBuilder.js) so both UIs expose the same
# knobs under the same grid keys.
#
# grid_key is the key sent in the overrides dict and must match
# model_registry.py's "clf__..." / "selector__..." convention. It is null for
# the two ANN layer fields, which are combined into a single
# clf__hidden_layer_sizes value rather than sent individually.
#
# allow_blank means the field may be left empty, which sends no override at all
# and leaves the model's own default grid for that key in place. It notably does
# NOT send null for "unlimited depth": the ETL stores blobs as Python reprs and
# repairs them into JSON by swapping quotes, so a None reaches the parser intact
# and breaks the entire blob. Every other field is required once its model is
# chosen.
MODEL_FIELDS: dict[str, list[dict]] = {
    "logistic": [
        {"id": "C", "label": "C (regularization)", "grid_key": "clf__C",
         "min": 0.001, "max": 1000, "default": 1},
    ],
    "svm": [
        {"id": "C", "label": "C (regularization)", "grid_key": "clf__C",
         "min": 0.001, "max": 1000, "default": 1},
    ],
    "random_forest": [
        {"id": "n_estimators", "label": "number of trees",
         "grid_key": "clf__n_estimators", "min": 1, "max": 2000, "default": 100},
        {"id": "max_depth", "label": "max depth (blank = default range)",
         "grid_key": "clf__max_depth", "min": 1, "max": 100, "default": None,
         "allow_blank": True},
    ],
    "xgboost": [
        {"id": "n_estimators", "label": "number of trees",
         "grid_key": "clf__n_estimators", "min": 1, "max": 2000, "default": 100},
        {"id": "max_depth", "label": "max depth", "grid_key": "clf__max_depth",
         "min": 1, "max": 100, "default": 5},
    ],
    "knn": [
        {"id": "n_neighbors", "label": "number of neighbors",
         "grid_key": "clf__n_neighbors", "min": 1, "max": 100, "default": 5},
    ],
    "naive_bayes": [
        {"id": "var_smoothing", "label": "variance smoothing",
         "grid_key": "clf__var_smoothing", "min": 1e-9, "max": 1, "default": 1e-9},
    ],
    "decision_tree": [
        {"id": "max_depth", "label": "max depth (blank = default range)",
         "grid_key": "clf__max_depth", "min": 1, "max": 100, "default": None,
         "allow_blank": True},
        {"id": "min_samples_split", "label": "min samples split",
         "grid_key": "clf__min_samples_split", "min": 2, "max": 100, "default": 2},
    ],
    "ann": [
        {"id": "layer_1", "label": "hidden layer 1 neurons", "grid_key": None,
         "min": 1, "max": 512, "default": 16},
        {"id": "layer_2", "label": "hidden layer 2 neurons (0 = none)",
         "grid_key": None, "min": 0, "max": 512, "default": 0},
        {"id": "alpha", "label": "alpha (regularization)", "grid_key": "clf__alpha",
         "min": 1e-6, "max": 1, "default": 0.0001},
        {"id": "learning_rate_init", "label": "learning rate",
         "grid_key": "clf__learning_rate_init", "min": 0.0001, "max": 1,
         "default": 0.001},
    ],
    "dummy": [],
}

# One-line note on what each model is for, so the dropdown is not just jargon.
MODEL_NOTES: dict[str, str] = {
    "logistic": "Linear baseline. Fast, and the coefficients are readable.",
    "svm": "Good on small, clean datasets. Slow as patient count grows.",
    "random_forest": "Strong general default. Handles mixed-scale features.",
    "xgboost": "Usually the best raw scores; more prone to overfitting small data.",
    "knn": "Predicts from nearest patients. Needs well-scaled features.",
    "naive_bayes": "Very fast, assumes features are independent.",
    "decision_tree": "A single readable tree. Individually weak but easy to explain.",
    "dummy": "Predicts the majority class. A sanity check, not a model — "
             "its ROC-AUC should land at ~0.5.",
    "ann": "Small neural net. Needs more data than the others to pay off.",
}

GRID_PREFIXES = ("clf__", "selector__")


@lru_cache(maxsize=1)
def _registry_pairs() -> tuple[tuple[str, str], ...]:
    out = exec(settings.container,
               f"cd {settings.etl_app_dir}",
               f".venv/bin/python -c {shlex.quote(PROBE)}")
    if out.returncode != 0:
        raise RuntimeError(
            "could not read MODEL_REGISTRY from the container — the model "
            f"registry patch may not be installed: {out.stderr.strip()[:300]}"
        )
    # The probe's JSON is the last line; loguru and friends may print first.
    line = next(
        (ln for ln in reversed(out.stdout.splitlines()) if ln.strip().startswith("[")),
        None,
    )
    if line is None:
        raise RuntimeError(f"unexpected registry probe output: {out.stdout[:300]}")
    return tuple((k, n) for k, n in json.loads(line))


def list_model_types() -> list[dict]:
    return [
        {
            "key": key,
            "name": name,
            "note": MODEL_NOTES.get(key, ""),
            "fields": MODEL_FIELDS.get(key, []),
        }
        for key, name in _registry_pairs()
    ]


def known_keys() -> set[str]:
    return {k for k, _ in _registry_pairs()}


def refresh() -> None:
    """Drop the cache, for after a registry edit + container restart."""
    _registry_pairs.cache_clear()
