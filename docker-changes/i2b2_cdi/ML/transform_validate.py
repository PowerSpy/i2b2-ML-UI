"""Whether a returned frame can survive the rest of the pipeline.

Every rule here corresponds to a specific way the build fails *later*, usually
with an error naming something other than the transform. The value of checking
here is attribution: `RobustScaler` raising on a string thirty lines away is a
bad way to learn you forgot to encode a column.

Run in both places. Here it is fast feedback on fake data; in the hook it is
the authoritative gate, because a transform can behave differently on real
values and only the hook sees those.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

# Set by the engine after the transform runs. A transform returning either
# would have it silently overwritten - `label` at apply_build_model_ml.py:171,
# `subject_id` when patient numbers are re-attached.
RESERVED = ("label", "subject_id")

# The selected feature names land in the concept blob, which is a Python repr
# repaired by an unconditional `blob.replace("'", '"')` before `json.loads`
# (BaseEngine.py:53, build_model_ML_helper.py:424). One apostrophe in a column
# name corrupts the entire stored model, and the error names a character
# position in a JSON document nobody wrote.
FORBIDDEN_IN_NAME = ("'", '"', "\\")

MAX_COLUMNS = 2000


class ValidationError(Exception):
    """A refusal with a sentence a researcher can act on."""


def check(out, original: pd.DataFrame) -> dict:
    """Validate `out` against the frame handed in. Returns a report."""
    _shape(out, original)
    _names(out)
    _index(out, original)
    value_warnings = _values(out, original)

    changed = _changed(out, original)
    report = {
        "changed": changed,
        "rows_in": int(len(original)),
        "rows_out": int(len(out)),
        "columns_in": int(original.shape[1]),
        "columns_out": int(out.shape[1]),
        "columns_added": sorted(set(out.columns) - set(original.columns)),
        "columns_removed": sorted(set(original.columns) - set(out.columns)),
        "rows_dropped": int(len(original) - len(out)),
        "warnings": list(value_warnings),
    }

    if not changed:
        # Not an error - a researcher iterating deserves to run a no-op. But
        # "succeeded and did nothing" is the failure this whole feature is
        # meant to make visible, so it does not pass quietly.
        report["warnings"].append(
            "The frame came back unchanged. If that was not deliberate, check "
            "that you are returning the frame you modified - pandas operations "
            "return a new frame rather than editing in place."
        )
    if report["rows_dropped"]:
        report["warnings"].append(
            f"{report['rows_dropped']} rows were dropped. Their labels are "
            "dropped with them, so the model trains on a different population "
            "than the cohort you defined."
        )
    return report


def _shape(out, original) -> None:
    if out is None:
        raise ValidationError(
            "The transform returned None - did you forget to `return df`? "
            "pandas operations return a new frame rather than editing in place, "
            "so the last line has to hand it back."
        )
    if isinstance(out, pd.Series):
        raise ValidationError(
            "The transform returned a Series, not a DataFrame. If that is one "
            "engineered column, add it to the frame and return the frame: "
            "`df['name'] = ...` then `return df`."
        )
    if not isinstance(out, pd.DataFrame):
        raise ValidationError(
            f"The transform returned {type(out).__name__}, not a DataFrame."
        )
    if out.shape[1] == 0:
        raise ValidationError("The returned frame has no columns - nothing to train on.")
    if out.shape[1] > MAX_COLUMNS:
        raise ValidationError(
            f"The returned frame has {out.shape[1]} columns (limit {MAX_COLUMNS}). "
            "The pipeline fits a grid search over every one of them."
        )
    if len(out) == 0:
        raise ValidationError(
            "The returned frame has no rows. A filter removed every patient - "
            f"{len(original)} went in."
        )


def _names(out: pd.DataFrame) -> None:
    for name in out.columns:
        if not isinstance(name, str):
            raise ValidationError(
                f"Column name {name!r} is {type(name).__name__}, not a string. "
                "Column names are stored as text in the model."
            )
        if not name.strip():
            raise ValidationError("A column name is blank.")
        for ch in FORBIDDEN_IN_NAME:
            if ch in name:
                raise ValidationError(
                    f"Column name {name!r} contains {ch!r}. Feature names are "
                    "stored in the model blob, which is repaired by a quote "
                    "swap when it is read back - one of these corrupts the "
                    "whole stored model, and the error will not mention this "
                    "column."
                )
        if name in RESERVED:
            raise ValidationError(
                f"`{name}` is reserved - the engine sets it after the transform "
                "runs, so a column of that name is silently overwritten."
            )

    dupes = sorted({c for c in out.columns if list(out.columns).count(c) > 1})
    if dupes:
        raise ValidationError(
            f"Duplicate column names: {', '.join(dupes)}. Only one of each "
            "would survive into the model, and which one is not defined."
        )


def _index(out: pd.DataFrame, original: pd.DataFrame) -> None:
    """Rows may be dropped; they may not be invented, reordered into
    duplicates, or renumbered.

    Patient numbers are re-attached by this index after the transform returns.
    A new index value has no patient behind it, and a duplicate would attach
    one patient's number to two predictions - which is the failure mode worth
    the most care in this entire feature.
    """
    if out.index.has_duplicates:
        dupes = out.index[out.index.duplicated()].unique().tolist()[:5]
        raise ValidationError(
            f"The returned index has duplicates ({dupes}). Patient numbers are "
            "matched back by index, so a duplicate would label two rows with "
            "the same patient. `reset_index(drop=True)` discards the mapping - "
            "keep the index you were given."
        )
    extra = out.index.difference(original.index)
    if len(extra):
        renumbered = list(extra[:3]) == list(range(len(extra))[:3])
        hint = (
            "That is a 0-based renumbering, so this looks like "
            "`reset_index(drop=True)`. It discards the mapping back to "
            "patients: every row would keep its values and be attributed to "
            "somebody else. Filter the frame and leave the index alone."
            if renumbered else
            "Rows may be filtered out, but new rows have no patient behind "
            "them. Build engineered columns onto the frame you were given "
            "rather than a new one."
        )
        raise ValidationError(
            f"The returned index has {len(extra)} values that were not handed "
            f"in (for example {extra.tolist()[:5]}). {hint}"
        )


def _values(out: pd.DataFrame, original: pd.DataFrame) -> list[str]:
    """Value-level rules, with one deliberate exemption.

    An all-NaN column is normally an error. But the dry-run frame materialises
    every *suppressed* column all-NaN on purpose - the dictionary withheld it,
    so there is nothing to draw from, and leaving the column out entirely would
    be worse because `df['x']` would then raise in development and work in
    production.

    Rejecting those outright would fail every dry run on every model that has
    a sparse concept in it, which is most of them. So a column that arrived
    empty and left empty warns; a column the transform *emptied* still raises.
    In the hook, where no input column is ever all-NaN, the rule stays strict
    with no special case needed.
    """
    warnings: list[str] = []
    empty_on_arrival = {
        name for name in original.columns
        if len(original) and bool(original[name].isna().all())
    }

    for name in out.columns:
        col = out[name]
        if col.dtype == object or pd.api.types.is_string_dtype(col):
            raise ValidationError(
                f"Column {name!r} holds text. Every column is scaled before "
                "training, so a non-numeric one raises inside RobustScaler with "
                "an error that does not name the column. Encode it - "
                "`pd.get_dummies` or a mapping - before returning."
            )
        if not pd.api.types.is_numeric_dtype(col):
            raise ValidationError(
                f"Column {name!r} has dtype {col.dtype}, which is not numeric."
            )

        values = col.to_numpy(dtype="float64", na_value=np.nan)
        if np.isinf(values).any():
            n = int(np.isinf(values).sum())
            raise ValidationError(
                f"Column {name!r} has {n} infinite values. They survive "
                "`fillna(0)` and then break the scaler with an error naming "
                "neither. A division by zero is the usual cause - "
                "`.replace([np.inf, -np.inf], np.nan)` is the usual fix."
            )
        if len(values) and bool(np.isnan(values).all()):
            if name in empty_on_arrival:
                warnings.append(
                    f"Column {name!r} is empty in this frame because the data "
                    "dictionary withheld it - too few patients to describe. It "
                    "is NOT empty in production. Code that skips it here will "
                    "meet real values there."
                )
                continue
            raise ValidationError(
                f"Column {name!r} is entirely NaN. The engine fills missing "
                "values with 0, so this becomes an all-zero column that the "
                "feature selector may still choose - a feature carrying no "
                "information, reported as if it did."
            )

    return warnings


def _changed(out: pd.DataFrame, original: pd.DataFrame) -> bool:
    if out.shape != original.shape or list(out.columns) != list(original.columns):
        return True
    if not out.index.equals(original.index):
        return True
    try:
        return not out.equals(original)
    except (TypeError, ValueError):
        # Comparison can fail on exotic dtypes. Reporting "changed" is the
        # safe direction: the alternative warns that a real change did nothing.
        return True


def preview(df: pd.DataFrame, rows: int = 10) -> dict:
    """A JSON-safe sample. **Only ever called on synthetic data.**

    The real run returns aggregate counts and no frame content whatsoever -
    see `app/core/sandbox.py`. Keeping this function in a module the hook also
    imports is deliberate: one place to look when checking that claim.
    """
    head = df.head(rows)
    return {
        "columns": [str(c) for c in head.columns],
        "dtypes": [str(t) for t in head.dtypes],
        "rows": [[_json_safe(v) for v in row] for row in head.itertuples(index=False)],
        "index": [_json_safe(i) for i in head.index],
        "truncated": bool(len(df) > rows),
    }


def _json_safe(v):
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        # JSON has no NaN or Infinity. `json.dumps` emits them anyway and the
        # result is not parseable by anything but Python.
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    return str(v)
