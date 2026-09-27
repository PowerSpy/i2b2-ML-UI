"""A recipe for fake data that has the real data's shape and none of its rows.

A researcher writing a feature transform needs a frame to run it against. This
module turns the already-suppressed data dictionary into a **plan** - pure JSON,
no arrays - that the sandbox materialises with the same pandas the real build
uses.

## Why a plan and not a frame

The host has no pandas, and deliberately so: nothing that assembles a
DataFrame should run in the process holding the container credentials. More
importantly, a dtype difference between dev and production must be impossible
by construction. The sandbox builds the frame with the build's own pandas, so
`float64` here means `float64` there.

## Columns are independent, on purpose

There is no covariance in this plan and there should not be. A covariance
matrix over 50 concepts is 1,275 numbers, several of them effectively one
patient's on a small cohort, and suppressing that correctly is a research
problem where suppressing marginals is a constant.

It also buys nothing for the purpose. The frame exists so code can *run* -
names, dtypes, NaN patterns, ranges, row counts. And a correlated generator
creates a worse failure than it fixes: a researcher validates an imputation
against plausible-but-fake correlations, ships it, and the real run quietly
differs while reporting success. Independent marginals are *obviously* fake,
and that obviousness is the honest signal.

**This is not synthetic data in the disclosure-control sense.** It is a shape.
Do not use it to estimate anything.

## What it does preserve

Column names and order, dtypes, fill rates, integer-ness, row count, level
sets, and the adversarial shapes a real frame contains: an all-NaN column, a
constant column, and a wholly-NaN row. Those three break more transforms than
any distribution detail, and the real frame here has all of them.

Nothing in this module reads the warehouse. Its only input is the dictionary
payload, which is already suppressed - so the plan provably cannot carry
anything that was not already published.
"""

from __future__ import annotations

import hashlib

# Enough rows for a groupby to be meaningful, few enough that a slow transform
# fails in the sandbox's time budget rather than at the wall clock.
DEFAULT_ROWS = 400
MIN_ROWS = 20
MAX_ROWS = 20000

# The published grid. p01/p99 are the outermost points the dictionary reports -
# there is no true min or max here and there must not be.
QUANTILES = [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]
QUANTILE_FIELDS = {0.01: "low", 0.05: "p05", 0.25: "p25", 0.50: "p50",
                   0.75: "p75", 0.95: "p95", 0.99: "high"}

PLAN_VERSION = 1

# Row ids are drawn above this. Nothing about the number matters except that a
# frame renumbered by `reset_index(drop=True)` cannot land inside the range -
# see the `index` key in `plan()` for why that is the difference between a
# check that works and one that reads as though it does.
INDEX_FLOOR = 1_000_000


def plan(dictionary: dict, *, n_rows: int | None = None, seed: int | None = None,
         hostile: bool = False) -> dict:
    """A materialisation plan for `dictionary`, as plain JSON.

    `dictionary` is the payload from `dictionary.describe()`. `hostile` halves
    fill rates, widens tails and multiplies the all-NaN rows - the cheapest way
    to make a brittle transform fail here instead of on a job row.
    """
    scope = dictionary.get("scope") or "unknown"
    seed = _seed(scope) if seed is None else int(seed)
    n_rows = _rows(n_rows, dictionary.get("patients_in_scope"))

    columns, warnings = [], []
    for col in dictionary.get("columns") or []:
        spec, warn = _spec(col, hostile=hostile)
        columns.append(spec)
        warnings.extend(warn)

    # A patient in a cohort whose feature facts are all missing produces a row
    # of nothing but NaN, and independent fill rates would essentially never
    # generate one across this many columns. It is forced, because a transform
    # that divides by a row total is the single most common thing that works in
    # dev and raises in production.
    all_nan_rows = min(n_rows // 4, 3 if not hostile else 12) if columns else 0

    return {
        "version": PLAN_VERSION,
        "scope": scope,
        "seed": seed,
        "n_rows": n_rows,
        "hostile": bool(hostile),
        "all_nan_rows": all_nan_rows,
        # Opaque row ids, and **the real hook must do the same**. Two reasons,
        # and the second is the one that matters.
        #
        # Patient numbers must not be the index: handing every transform a
        # list of them buys nothing, and the frame is re-paired by index
        # afterwards either way.
        #
        # But a plain 0..n-1 index is actively unsafe. `reset_index(drop=True)`
        # after a filter produces 0..k-1, which *is* a subset of 0..n-1 - so
        # the "index must be a subset" check passes while every row has been
        # renumbered and every prediction will be attached to the wrong
        # patient. Ids that start above a floor make that renumbering
        # impossible to mistake for a filter.
        "index": "opaque",
        "index_floor": INDEX_FLOOR,
        "columns": columns,
        "warnings": sorted(set(warnings)),
        "basis": (
            "Generated from published aggregates only. Columns are independent "
            "- there is no correlation structure and none is implied. Use this "
            "frame to check that code runs, never to estimate anything."
        ),
    }


def _seed(scope: str) -> int:
    """Stable per scope, so two dry runs of one model give the same frame.

    A researcher comparing two versions of a transform needs the difference to
    be theirs. `hash()` is salted per process and would not do.
    """
    return int.from_bytes(hashlib.sha256(scope.encode()).digest()[:4], "big")


def _rows(requested, patients_in_scope) -> int:
    if requested is not None:
        return max(MIN_ROWS, min(MAX_ROWS, int(requested)))
    if patients_in_scope:
        return max(MIN_ROWS, min(MAX_ROWS, int(patients_in_scope)))
    # Withheld means the cohort is under the threshold. Generating that few
    # rows would republish the count, so it does not.
    return DEFAULT_ROWS


# --------------------------------------------------------------------------
# per column


def _spec(col: dict, *, hostile: bool) -> tuple[dict, list[str]]:
    code = col["code"]
    warnings: list[str] = []
    fill = col.get("fill_rate")
    suppressed = set(col.get("suppressed") or [])

    spec = {
        "name": code,
        "label": col.get("name") or None,
        "integer": bool(col.get("integer_like")),
        # A column the dictionary withheld entirely still has to exist in the
        # frame. If it did not, `df["x"]` would raise in dev and work in
        # production - or the reverse - and either way the dev loop would be
        # lying about the shape of the real frame.
        "fill_rate": 0.0 if fill is None else float(fill),
        "notes": [],
    }

    if "patients_with_value" in suppressed:
        spec["kind"] = "empty"
        spec["fill_rate"] = 0.0
        spec["notes"].append(
            "withheld: too few patients to describe. Materialised all-NaN, but "
            "the real column has values - code that skips it here will not "
            "skip it in production."
        )
        warnings.append(f"{code}: withheld by suppression, all-NaN in this frame")
        return spec, warnings

    if col.get("empty_in_build"):
        # The build's pivot reads only `nval_num`, so this column is all-NaN
        # in the real frame whatever the warehouse holds. Materialising its
        # real levels would be the worst kind of divergence: the researcher
        # writes `pd.get_dummies(df['x'])` against values that work here and
        # meets an empty column on the job row.
        spec["kind"] = "empty"
        spec["fill_rate"] = 0.0
        spec["notes"].append(
            col.get("build_note")
            or "the build reads only the numeric value column; this one is "
               "all-NaN in the real frame too"
        )
        warnings.append(
            f"{code}: empty in the real frame - the build's pivot reads only "
            "the numeric value column, and this concept has no numeric values"
        )
        return spec, warnings

    if hostile:
        spec["fill_rate"] = round(spec["fill_rate"] / 2, 4)

    if col.get("kind") == "categorical":
        levels, warn = _levels(col)
        spec["kind"] = "categorical"
        spec["levels"] = levels
        warnings.extend(warn)
        if len(levels) == 1:
            spec["notes"].append("constant: one level")
    elif "quantiles" in suppressed:
        # Between one cell and two, the count is published but the shape is
        # not. There is nothing to draw from, and inventing a range would be
        # inventing the one thing the dictionary refused to say.
        spec["kind"] = "constant"
        spec["value"] = 0.0
        spec["notes"].append(
            "no distribution published (too few patients). Filled with 0.0 at "
            "the real fill rate - the count is right, the values are not."
        )
        warnings.append(f"{code}: distribution withheld, filled with a constant")
    else:
        grid, warn = _grid(col, hostile=hostile)
        if grid is None:
            spec["kind"] = "empty"
            spec["fill_rate"] = 0.0
            spec["notes"].append("no percentiles reported; materialised all-NaN")
            warnings.append(f"{code}: no percentiles in the dictionary")
        else:
            spec["kind"] = "numeric"
            spec["quantiles"] = grid
            if grid[0][1] == grid[-1][1]:
                spec["notes"].append("constant: p01 equals p99")
        warnings.extend(warn)

    if spec["fill_rate"] <= 0 and spec["kind"] != "empty":
        spec["notes"].append("fill rate 0: every value is NaN")

    return spec, warnings


def _levels(col: dict) -> tuple[list[dict], list[str]]:
    """Level probabilities, renormalised over what was published.

    `other_count` becomes a real level rather than being dropped. Dropping it
    would understate the fill rate, and a NaN there would tell a researcher the
    column is sparser than it is.
    """
    code = col["code"]
    warnings: list[str] = []
    levels = list(col.get("levels") or [])
    other = int(col.get("other_count") or 0)

    total = sum(int(lv["count"]) for lv in levels) + other
    if total <= 0:
        return [], [f"{code}: categorical with no levels published"]

    out = [{"value": _value(lv), "p": round(int(lv["count"]) / total, 6)}
           for lv in levels]

    if other:
        name = _other_name({lv["value"] for lv in out})
        numeric = all(lv.get("numeric") for lv in levels) if levels else False
        out.append({"value": -1.0 if numeric else name,
                    "p": round(other / total, 6)})
        warnings.append(
            f"{code}: {'levels were' if levels else 'all levels were'} too "
            f"small to name; they appear here as a single placeholder level, "
            "so code that branches on level names will see a value production "
            "never produces"
        )

    return out, warnings


def _value(lv: dict):
    """A level value with its real type restored.

    The dictionary carries every level as text because that is how the query
    returns it. Materialising an integer-coded level as the string "1" would
    make `df["sex"] == 1` false in dev and true in production.
    """
    if not lv.get("numeric"):
        return lv["value"]
    try:
        return float(lv["value"])
    except (TypeError, ValueError):
        return lv["value"]


def _other_name(taken: set) -> str:
    name = "other"
    n = 0
    while name in taken:
        n += 1
        name = f"other_{n}"
    return name


def _grid(col: dict, *, hostile: bool) -> tuple[list[list[float]] | None, list[str]]:
    """The published percentiles as an ascending (q, value) grid.

    Postgres returns these monotone, but a column carrying both numeric and
    text rows can produce nulls in the middle of the grid. A non-monotone grid
    would make the inverse-CDF walk in the sandbox run backwards, so it is
    repaired here and said out loud rather than silently producing a
    distribution nobody asked for.
    """
    code = col["code"]
    pairs = []
    for q in QUANTILES:
        v = col.get(QUANTILE_FIELDS[q])
        if v is not None:
            pairs.append([q, float(v)])

    if len(pairs) < 2:
        return None, []

    warnings = []
    for i in range(1, len(pairs)):
        if pairs[i][1] < pairs[i - 1][1]:
            pairs[i][1] = pairs[i - 1][1]
            warnings.append(f"{code}: percentiles were not ascending; clamped")

    if hostile:
        # Widen the tails by a quarter of the published spread each side. The
        # point is to produce values a transform's assumptions do not cover -
        # not to guess the real extremes, which are exactly what the dictionary
        # withholds.
        spread = pairs[-1][1] - pairs[0][1]
        if spread > 0:
            pairs[0][1] -= spread / 4
            pairs[-1][1] += spread / 4

    return pairs, warnings


# --------------------------------------------------------------------------


def summarise(p: dict) -> dict:
    """Counts for the UI, so a researcher can see what they are developing on."""
    kinds: dict[str, int] = {}
    for c in p["columns"]:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    return {
        "n_rows": p["n_rows"],
        "n_columns": len(p["columns"]),
        "kinds": kinds,
        "all_nan_rows": p["all_nan_rows"],
        "warnings": p["warnings"],
    }
