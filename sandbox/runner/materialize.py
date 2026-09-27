"""Turn a plan into a DataFrame.

Runs in the sandbox rather than on the host, with the same pandas the real
build uses, so a dtype cannot differ between the frame a researcher develops
against and the frame their transform meets in production. That is the whole
reason this is not done on the host.

The plan carries percentiles, level probabilities and fill rates - see
`app/core/synthetic.py` for why it carries nothing else.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def frame(plan: dict) -> pd.DataFrame:
    rng = np.random.default_rng(plan["seed"])
    n = int(plan["n_rows"])

    data = {}
    for spec in plan["columns"]:
        data[spec["name"]] = _column(rng, n, spec)

    # Built first, labelled second. Passing `index=` to the constructor would
    # *reindex* each Series onto those labels rather than rename them, and
    # since none of the generated values carry an opaque id, every one of them
    # would come out NaN - a frame of the right shape holding nothing.
    df = pd.DataFrame(data)
    df.index = _index(rng, n, plan)
    return _blank_rows(rng, df, int(plan.get("all_nan_rows") or 0))


def _index(rng, n: int, plan: dict) -> pd.Index:
    """Opaque, non-contiguous row ids starting above a floor.

    Not a RangeIndex, and the reason is the whole point of the index rule:
    `reset_index(drop=True)` after a filter gives 0..k-1, which is a perfectly
    valid subset of 0..n-1. The validator would accept it, every row would be
    renumbered, and each prediction would be written against the wrong
    patient - silently. Ids above a floor make that renumbering detectable
    rather than plausible.
    """
    if plan.get("index") != "opaque":
        return pd.RangeIndex(n)
    floor = int(plan.get("index_floor") or 0)
    # Non-contiguous as well as offset, so code that assumes `index[i] == i +
    # floor` fails here rather than in production.
    ids = floor + rng.choice(max(n * 4, n + 1), size=n, replace=False)
    return pd.Index(np.sort(ids), name=None)


def _column(rng, n: int, spec: dict):
    kind = spec["kind"]
    if kind == "empty":
        return pd.Series(np.full(n, np.nan), dtype="float64")

    if kind == "constant":
        values = pd.Series(np.full(n, float(spec.get("value", 0.0))), dtype="float64")
    elif kind == "numeric":
        values = pd.Series(_numeric(rng, n, spec["quantiles"]), dtype="float64")
        if spec.get("integer"):
            values = values.round(0)
    elif kind == "categorical":
        values = _categorical(rng, n, spec.get("levels") or [])
    else:
        raise ValueError(f"unknown column kind: {kind!r}")

    return _punch_holes(rng, values, float(spec.get("fill_rate", 1.0)))


def _numeric(rng, n: int, grid: list) -> np.ndarray:
    """Inverse-CDF sampling over the published percentile grid.

    `np.interp` clamps outside the grid, which would put a hard floor at p01
    and a hard ceiling at p99 - so a transform that clips at the observed range
    would look correct here and silently reshape real data, which has 2% of its
    values outside those points. The tails are extrapolated along the slope of
    the outermost segment instead. That is not a guess at the real extremes,
    which the dictionary withholds on purpose; it is a guarantee that values
    outside the published range exist.
    """
    qs = np.array([g[0] for g in grid], dtype="float64")
    vs = np.array([g[1] for g in grid], dtype="float64")
    u = rng.random(n)
    out = np.interp(u, qs, vs)

    low = u < qs[0]
    if low.any():
        slope = _slope(qs[0], qs[1], vs[0], vs[1])
        out[low] = vs[0] - (qs[0] - u[low]) * slope
    high = u > qs[-1]
    if high.any():
        slope = _slope(qs[-2], qs[-1], vs[-2], vs[-1])
        out[high] = vs[-1] + (u[high] - qs[-1]) * slope
    return out


def _slope(q0, q1, v0, v1) -> float:
    span = q1 - q0
    return 0.0 if span <= 0 else (v1 - v0) / span


def _categorical(rng, n: int, levels: list) -> pd.Series:
    if not levels:
        return pd.Series(np.full(n, np.nan), dtype="float64")

    values = [lv["value"] for lv in levels]
    p = np.array([float(lv["p"]) for lv in levels], dtype="float64")
    total = p.sum()
    # Rounding each probability to six places leaves a remainder that
    # `rng.choice` rejects outright.
    p = p / total if total > 0 else np.full(len(values), 1 / len(values))

    picked = rng.choice(len(values), size=n, p=p)
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return pd.Series(np.array(values, dtype="float64")[picked], dtype="float64")
    return pd.Series([values[i] for i in picked], dtype="object")


def _punch_holes(rng, values: pd.Series, fill_rate: float) -> pd.Series:
    """Missingness at the published rate.

    Object columns have to go through `astype(object)` first: assigning NaN
    into an object Series is fine, but pandas will not hold NaN in some narrow
    dtypes without the cast, and a silent dtype promotion here is exactly the
    dev/production difference this frame exists to prevent.
    """
    if fill_rate >= 1.0:
        return values
    if fill_rate <= 0.0:
        return pd.Series(np.full(len(values), np.nan),
                         dtype="float64" if values.dtype != object else "object")

    missing = rng.random(len(values)) >= fill_rate
    out = values.astype(object) if values.dtype == object else values.copy()
    out[missing] = np.nan
    return out


def _blank_rows(rng, df: pd.DataFrame, k: int) -> pd.DataFrame:
    """Force `k` rows to be entirely NaN.

    With independent fill rates across this many columns the chance of one
    arising is effectively zero, and the real frame has them: a patient in the
    cohort whose label fact exists and whose feature facts do not. A transform
    that divides by a row total is the most common thing that passes in dev and
    raises in production, and this is what catches it.
    """
    if k <= 0 or df.empty:
        return df
    rows = rng.choice(len(df), size=min(k, len(df)), replace=False)
    df.iloc[rows, :] = np.nan
    return df
