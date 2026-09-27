"""What the data looks like, without showing anyone a patient.

A researcher cannot write a feature transform blind. They need column names,
types, ranges, how often a column is populated — the shape of the frame. None
of that requires seeing a row, and this module is how they get it.

Everything here is an aggregate, suppressed below a threshold, and it is the
*only* source the synthetic data generator reads. That is deliberate: the
synthetic frame therefore provably cannot carry anything this module did not
already publish, so it inherits this module's disclosure review rather than
needing its own.

## Two decisions worth knowing

**Statistics are over the last value per patient per concept**, not over every
fact — see `quality.last_value_cte`. The build pivots with `aggfunc='last'`,
so a distribution over all facts describes something nothing is trained on.

**No raw minimum or maximum, ever.** A maximum *is* one patient's value,
exactly, and on a small cohort it is often an identifying one. `low` and
`high` are the 1st and 99th percentiles. This is the single most important
rule in the module and the one most such panels get wrong.
"""

from app.core import quality
from app.core.config import settings
from app.core.db import check_code, check_path, query

SCHEMA = quality.SCHEMA

# Fewer than this many patients and a count is withheld. 11 matches the CMS
# cell-size suppression policy - chosen so there is a published rule to point
# a reviewer at rather than a number we picked.
MIN_CELL = settings.min_cell_size

# Quantiles need meaningfully more than one cell's worth before their shape
# stops being a description of individuals.
MIN_FOR_QUANTILES = 2 * MIN_CELL

# A column with few distinct values is categorical whatever its declared type:
# an integer-coded sex or stage behaves like a level set, not a range.
CATEGORICAL_MAX_DISTINCT = 20

# Per concept. Beyond this the tail is summarised as `other_count`.
MAX_LEVELS = 12


class Scope:
    """Which concepts, over which patients.

    `patients_sql` is a SELECT returning patient_num, or None for "every
    patient who has one of these codes".
    """

    def __init__(self, label: str, codes: list[str],
                 patients_sql: str | None = None, note: str = ""):
        self.label = label
        self.codes = codes
        self.patients_sql = patients_sql
        self.note = note

    def where(self) -> str:
        if not self.codes:
            # No codes means no rows, said explicitly rather than by emitting
            # `IN ()`, which is a syntax error.
            return "false"
        codes = ", ".join(f"'{check_code(c)}'" for c in self.codes)
        clause = f"concept_cd IN ({codes})"
        if self.patients_sql:
            clause += f" AND patient_num IN ({self.patients_sql})"
        return clause


# --------------------------------------------------------------------------
# scopes


def _codes_under(paths: list[str]) -> list[str]:
    """Concept codes beneath any of `paths`, resolved the way the build does.

    The engine turns a data path into `concept_path LIKE '\\Root\\Sub\\%'`
    (build_model_ML_helper.create_data_label_codes), so a path pulls in its
    whole subtree. Matching that exactly is what makes `model_scope` describe
    the frame a build would really assemble rather than one that looks similar.
    """
    if not paths:
        return []
    clauses = []
    for p in paths:
        coded = "\\\\" + check_path(p).strip("/").replace("/", "\\\\") + "\\\\%"
        clauses.append(f"concept_path LIKE '{coded}'")
    rows = query(
        f"SELECT DISTINCT concept_cd AS code FROM {SCHEMA}.concept_dimension "
        f"WHERE {' OR '.join(clauses)} ORDER BY concept_cd;"
    )
    return [r["code"] for r in rows]


def warehouse_scope(root: str | None = None) -> Scope:
    """Every concept under a dataset root, over every patient holding one."""
    if root:
        codes = _codes_under([root])
        label = root
    else:
        rows = query(
            f"SELECT DISTINCT concept_cd AS code FROM {SCHEMA}.concept_dimension"
            " ORDER BY concept_cd;"
        )
        codes = [r["code"] for r in rows]
        label = "the whole warehouse"
    return Scope(label, codes, note="every patient holding one of these codes")


def model_scope(code: str) -> Scope:
    """The frame a build for `code` would assemble.

    This is the scope that matters: it gives the right column list, patient
    count, fill rates and class balance for the synthetic frame. The warehouse
    scope is a browsing aid.
    """
    from app.core import ml_blob

    blob = ml_blob.load_blob_light(check_code(code))
    data_paths = blob.get("data_paths") or []
    label_paths = blob.get("label_paths") or []

    # data_paths minus label_paths, matching create_data_label_codes: the
    # outcome is not a feature, and including it would describe a frame with
    # the answer in it.
    feature_codes = sorted(set(_codes_under(data_paths)) - set(_codes_under(label_paths)))

    cohorts = (blob.get("positive_patient_set") or []) + \
              (blob.get("negative_patient_set") or [])
    patients_sql = _patients_in_cohorts(cohorts) if cohorts else None

    return Scope(
        f"model {code}", feature_codes, patients_sql,
        note=("the patients and columns a build of this model would use: "
              "its data paths minus its label paths, over its training sets"),
    )


def _patients_in_cohorts(names: list[str]) -> str | None:
    """A SELECT of patient_num for every set carrying one of these names.

    Every matching set, not one - the training engine resolves a cohort name
    to all of them and unions them, so describing only one would describe a
    population the build does not use.
    """
    from app.core import cohorts as cohort_core

    ids = [c["id"] for c in cohort_core.list_cohorts() if c["name"] in set(names)]
    if not ids:
        return None
    joined = ", ".join(str(int(i)) for i in ids)
    return (f"SELECT patient_num FROM {SCHEMA}.qt_patient_set_collection "
            f"WHERE result_instance_id IN ({joined})")


# --------------------------------------------------------------------------
# suppression


def _suppress(n, min_cell: int = MIN_CELL):
    """A count, or None when it is small enough to describe individuals.

    None rather than 0. A reader must not be able to tell "one patient" from
    "no patients", and a zero reads as the second.
    """
    if n is None:
        return None
    return int(n) if int(n) >= min_cell else None


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("t", "true", "1", "yes")


# --------------------------------------------------------------------------
# the report


def describe(scope: Scope, min_cell: int = MIN_CELL) -> dict:
    """Per-concept statistics for `scope`, already suppressed."""
    where = scope.where()
    patients_in_scope = _int(query(
        f"WITH lv AS ({quality.last_value_cte(where)}) "
        "SELECT count(DISTINCT patient_num) AS n FROM lv;"
    )[0]["n"])

    stats = _numeric_stats(where)
    names = _concept_names(scope.codes)
    # The kind has to be settled before the levels query, so it can ask only
    # about the columns that have levels rather than enumerating every distinct
    # value of every continuous column.
    levels = _levels(where, [c for c in scope.codes
                             if _kind(stats.get(c, {})) == "categorical"])

    columns = []
    for code in scope.codes:
        s = stats.get(code, {})
        columns.append(_column(code, names.get(code), s, levels.get(code, []),
                               patients_in_scope, min_cell))

    return {
        "scope": scope.label,
        "note": scope.note,
        "min_cell": min_cell,
        "patients_in_scope": _suppress(patients_in_scope, min_cell),
        "columns": columns,
        "basis": (
            "Statistics are over the last value per patient per concept, which "
            "is what a build sees. Counts below the threshold are withheld, "
            "and no raw minimum or maximum is reported - a maximum is one "
            "patient's value."
        ),
    }


def _concept_names(codes: list[str]) -> dict[str, str]:
    if not codes:
        return {}
    joined = ", ".join(f"'{check_code(c)}'" for c in codes)
    return {
        r["code"]: r["name"]
        for r in query(
            f"SELECT concept_cd AS code, max(name_char) AS name "
            f"FROM {SCHEMA}.concept_dimension WHERE concept_cd IN ({joined}) "
            "GROUP BY concept_cd;"
        )
    }


# Which of the two value columns a row actually carries.
#
# `valtype_cd` is the authority and `tval_char` on its own is not: i2b2 writes
# **'E'** into `tval_char` on every *numeric* fact, as the operator flag for
# "equals". Reading tval_char first therefore collapses every integer-coded
# concept to a single level called 'E' - cp has four real levels and reported
# one - and counting it as text marks every numeric column in the warehouse as
# carrying mixed types.
IS_NUMERIC = "valtype_cd = 'N' AND nval_num IS NOT NULL"
IS_TEXT = f"NOT ({IS_NUMERIC}) AND tval_char IS NOT NULL AND tval_char <> ''"

# The value a row contributes, or NULL if it carries none.
VALUE = (f"CASE WHEN {IS_NUMERIC} THEN nval_num::float8::text "
         f"     WHEN {IS_TEXT} THEN tval_char END")


def _numeric_stats(where: str) -> dict[str, dict]:
    rows = query(
        f"WITH lv AS ({quality.last_value_cte(where)}) "
        "SELECT concept_cd AS code, "
        "       count(*) AS patients_with_value, "
        f"       count(*) FILTER (WHERE {IS_NUMERIC}) AS n_numeric, "
        f"       count(*) FILTER (WHERE {IS_TEXT}) AS n_text, "
        f"       count(DISTINCT {VALUE}) AS n_distinct, "
        "       count(*) FILTER (WHERE nval_num = 0) AS n_zero, "
        "       count(*) FILTER (WHERE nval_num < 0) AS n_negative, "
        "       coalesce(bool_and(nval_num = trunc(nval_num)), false) AS integer_like, "
        "       avg(nval_num) AS mean, "
        "       stddev_pop(nval_num) AS sd, "
        "       percentile_cont(0.01) WITHIN GROUP (ORDER BY nval_num) AS p01, "
        "       percentile_cont(0.05) WITHIN GROUP (ORDER BY nval_num) AS p05, "
        "       percentile_cont(0.25) WITHIN GROUP (ORDER BY nval_num) AS p25, "
        "       percentile_cont(0.50) WITHIN GROUP (ORDER BY nval_num) AS p50, "
        "       percentile_cont(0.75) WITHIN GROUP (ORDER BY nval_num) AS p75, "
        "       percentile_cont(0.95) WITHIN GROUP (ORDER BY nval_num) AS p95, "
        "       percentile_cont(0.99) WITHIN GROUP (ORDER BY nval_num) AS p99 "
        "FROM lv GROUP BY concept_cd;"
    )
    return {r["code"]: r for r in rows}


def _levels(where: str, codes: list[str]) -> dict[str, list[dict]]:
    """Distinct values per concept, for the categorical columns.

    **Numeric values count as levels too.** `_column` calls any column with few
    distinct values categorical whatever its declared type, and this dataset is
    full of integer-coded ones - sex, cp, fbs, restecg, exang, slope, ca, thal
    are all small integers. Reading only `tval_char` left every one of them
    described by nothing at all: categorical, so no quantiles, and no levels
    either because the values were in `nval_num`.

    `::float8::text` rather than `::text` because the column is `numeric` and
    a plain cast renders 1 as `1.00000`, which would then be the level name a
    researcher writes code against.
    """
    if not codes:
        return {}
    # Only the categorical columns. A continuous column would return one row
    # per distinct value, which is both useless here and the bulk of the work.
    joined = ", ".join(f"'{check_code(c)}'" for c in codes)
    rows = query(
        f"WITH lv AS ({quality.last_value_cte(where)}) "
        f"SELECT concept_cd AS code, {VALUE} AS value, "
        "       count(*) AS n, "
        f"       count(*) FILTER (WHERE {IS_NUMERIC}) AS n_numeric "
        f"FROM lv WHERE concept_cd IN ({joined}) AND {VALUE} IS NOT NULL "
        f"GROUP BY concept_cd, {VALUE} "
        "ORDER BY concept_cd, count(*) DESC;"
    )
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["code"], []).append({
            "value": r["value"],
            "count": _int(r["n"]),
            # So the synthetic frame reproduces the dtype. A level materialised
            # as "1" where the real frame holds 1.0 makes every comparison in a
            # transform behave differently in dev than in production.
            "numeric": _int(r.get("n_numeric")) >= _int(r["n"]),
        })
    return out


def _kind(s) -> str:
    """Whether a column reads as a level set or a range.

    Split out from `_column` because `describe` has to know this *before* it
    queries levels - see `_levels`.
    """
    n_numeric = _int(s.get("n_numeric"))
    n_text = _int(s.get("n_text"))
    n_distinct = _int(s.get("n_distinct"))

    # Rows exist but neither value column holds anything: a membership flag
    # such as dm_positive, which marks a patient as belonging to a set. Naming
    # it beats calling it numeric and then reporting every percentile as null,
    # which the UI would render identically to "not loaded yet".
    if _int(s.get("patients_with_value")) > 0 and n_numeric == 0 and n_text == 0:
        return "flag"

    return "categorical" if (
        n_text > n_numeric or (0 < n_distinct <= CATEGORICAL_MAX_DISTINCT and n_numeric > 0)
    ) else "numeric"


def _column(code, name, s, levels, patients_in_scope, min_cell) -> dict:
    with_value = _int(s.get("patients_with_value"))
    n_numeric = _int(s.get("n_numeric"))
    n_text = _int(s.get("n_text"))
    n_distinct = _int(s.get("n_distinct"))

    # A code carrying both numeric and text rows pivots to NaN for the text
    # ones - an invisible data bug the build never mentions, so it is named.
    mixed = n_numeric > 0 and n_text > 0
    kind = _kind(s)

    # The build's pivot is `values='value'`, and `value` is `nval_num`
    # renamed (apply_build_model_ml.py:155-164). **`tval_char` is never read.**
    # So a concept with no numeric values is an all-NaN column in the frame
    # however interesting it looks here - a text-valued category, or a
    # membership flag like dm_positive that carries no value at all.
    #
    # Saying so is the difference between a researcher writing
    # `pd.get_dummies(df['x'])` against levels that exist in the warehouse and
    # finding out on a job row that the column was empty the whole time.
    empty_in_build = with_value > 0 and n_numeric == 0

    col = {
        "code": code,
        "name": name or None,
        "kind": kind,
        "mixed_valtype": mixed,
        "empty_in_build": empty_in_build,
        "build_note": (
            "The build reads only the numeric value column, so this one "
            "arrives as an all-NaN feature no matter what it holds here."
            if empty_in_build else None
        ),
        "patients_with_value": _suppress(with_value, min_cell),
        "fill_rate": (round(with_value / patients_in_scope, 4)
                      if patients_in_scope and with_value >= min_cell else None),
        "missing_rate": (round(1 - with_value / patients_in_scope, 4)
                         if patients_in_scope and with_value >= min_cell else None),
        "n_distinct": _suppress(n_distinct, min_cell),
        "integer_like": _truthy(s.get("integer_like")),
        "suppressed": [],
    }

    if with_value < min_cell:
        # Listed, but with nothing attached. The column's *existence* is not
        # confidential and a researcher needs its name to write code against
        # it; its distribution over a handful of people is.
        col["suppressed"] = ["patients_with_value", "fill_rate", "quantiles",
                             "levels", "n_distinct"]
        col["reason"] = f"fewer than {min_cell} patients have a value"
        return col

    if kind == "numeric":
        if with_value >= MIN_FOR_QUANTILES:
            col.update({
                # p01/p99 stand in for min/max. A real minimum is one
                # patient's value and often an identifying one.
                "low": _num(s.get("p01")),
                "high": _num(s.get("p99")),
                "p05": _num(s.get("p05")), "p25": _num(s.get("p25")),
                "p50": _num(s.get("p50")), "p75": _num(s.get("p75")),
                "p95": _num(s.get("p95")),
                "mean": _num(s.get("mean")), "sd": _num(s.get("sd")),
                "n_zero": _suppress(_int(s.get("n_zero")), min_cell),
                "n_negative": _suppress(_int(s.get("n_negative")), min_cell),
            })
        else:
            col["suppressed"].append("quantiles")
            col["reason"] = (
                f"a distribution needs at least {MIN_FOR_QUANTILES} patients "
                "before its shape stops describing individuals"
            )
    else:
        col["levels"], col["other_count"], suppressed = _suppress_levels(levels, min_cell)
        if suppressed:
            col["suppressed"].append("levels")

    return col


def _suppress_levels(levels, min_cell):
    """Level counts, with the small ones folded into `other`.

    If folding leaves a single visible level, the list goes entirely: with one
    level shown and a total published, the hidden remainder is arithmetic.
    """
    kept = [lv for lv in levels if lv["count"] >= min_cell][:MAX_LEVELS]
    other = sum(lv["count"] for lv in levels if lv not in kept)

    if len(kept) <= 1 and other:
        return [], other + sum(lv["count"] for lv in kept), True
    return kept, other, len(kept) < len(levels)
