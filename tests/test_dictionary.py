"""Suppression rules for the data dictionary.

The SQL in `app/core/dictionary.py` cannot be executed here — there is no
warehouse in the test environment — so these drive the shaping logic against
fabricated query results instead. That is the half that decides what is
disclosed, and it is the half worth pinning.

**The SQL itself is unverified by this file.** Whether the percentile and
FILTER syntax is accepted by Postgres, and whether `last_value_cte` really
matches the build's pivot, needs a run against a live warehouse.
"""

import pytest

MIN = 11


def col(**over):
    """A `_numeric_stats` row, as psql --csv would hand it back: all strings."""
    base = {
        "code": "chol", "patients_with_value": "200", "n_numeric": "200",
        "n_text": "0", "n_distinct": "150", "n_zero": "0", "n_negative": "0",
        "integer_like": "f", "mean": "246.5", "sd": "51.2",
        "p01": "126", "p05": "160", "p25": "211", "p50": "241",
        "p75": "275", "p95": "330", "p99": "409",
    }
    base.update({k: str(v) for k, v in over.items()})
    return base


def build(stats, levels=None, patients=200, min_cell=MIN):
    from app.core import dictionary

    return dictionary._column("chol", "Cholesterol", stats, levels or [],
                              patients, min_cell)


# --------------------------------------------------------------------------
# the rule the module exists for


def test_raw_extremes_are_never_reported():
    """A maximum is one patient's value, exactly. `low`/`high` are p01/p99."""
    c = build(col())

    assert c["low"] == 126.0 and c["high"] == 409.0
    for forbidden in ("min", "max", "minimum", "maximum"):
        assert forbidden not in c, f"{forbidden} leaked into the dictionary"


def test_small_columns_are_listed_but_say_nothing():
    """The column's existence is not confidential - a researcher needs its
    name to write code. Its distribution over nine people is."""
    c = build(col(patients_with_value=9))

    assert c["code"] == "chol"          # still listed
    assert c["patients_with_value"] is None
    assert c["fill_rate"] is None
    assert "quantiles" in c["suppressed"]
    assert "fewer than 11" in c["reason"]
    assert "low" not in c and "p50" not in c


def test_a_suppressed_count_is_none_not_zero():
    """A reader must not be able to tell 'one patient' from 'no patients'."""
    from app.core import dictionary

    assert dictionary._suppress(0) is None
    assert dictionary._suppress(1) is None
    assert dictionary._suppress(10) is None
    assert dictionary._suppress(11) == 11


def test_quantiles_need_more_than_one_cell():
    """Between the cell threshold and twice it, the shape of a distribution is
    still a description of individuals."""
    c = build(col(patients_with_value=15))

    assert c["patients_with_value"] == 15     # the count survives
    assert "quantiles" in c["suppressed"]     # the shape does not
    assert "low" not in c

    ok = build(col(patients_with_value=22))
    assert "quantiles" not in ok["suppressed"]
    assert ok["low"] == 126.0


# --------------------------------------------------------------------------
# categorical levels


def test_rare_levels_fold_into_other():
    levels = [{"value": "yes", "count": 120}, {"value": "no", "count": 70},
              {"value": "unknown", "count": 4}]
    c = build(col(n_text=200, n_numeric=0, n_distinct=3), levels)

    shown = {lv["value"] for lv in c["levels"]}
    assert shown == {"yes", "no"}
    assert c["other_count"] == 4
    assert "levels" in c["suppressed"]


def test_one_visible_level_suppresses_the_list_entirely():
    """With one level shown and a total published, the remainder is
    arithmetic - so the list goes rather than the difference being derivable."""
    levels = [{"value": "yes", "count": 190}, {"value": "no", "count": 5},
              {"value": "maybe", "count": 5}]
    c = build(col(n_text=200, n_numeric=0, n_distinct=3), levels)

    assert c["levels"] == []
    assert c["other_count"] == 200
    assert "levels" in c["suppressed"]


# --------------------------------------------------------------------------
# shape detection


def test_a_code_with_both_numeric_and_text_rows_is_flagged():
    """Those rows pivot to NaN and the build never says so."""
    assert build(col(n_numeric=150, n_text=50))["mixed_valtype"] is True
    assert build(col(n_numeric=200, n_text=0))["mixed_valtype"] is False


def test_few_distinct_values_reads_as_categorical():
    """An integer-coded sex or stage is a level set, not a range."""
    assert build(col(n_distinct=2))["kind"] == "categorical"
    assert build(col(n_distinct=150))["kind"] == "numeric"


def test_integer_like_is_carried_through():
    """The synthetic generator rounds on it, so a wrong answer here produces
    fake ages of 54.3718."""
    assert build(col(integer_like="t"))["integer_like"] is True
    assert build(col(integer_like="f"))["integer_like"] is False


# --------------------------------------------------------------------------
# no count below the threshold anywhere in a payload


def test_nothing_below_the_threshold_survives_serialisation():
    """A recursive sweep rather than per-field assertions - the point is that
    no path through the shaping code emits a small count, including ones added
    later."""
    from app.core import dictionary

    payload = {
        "patients_in_scope": dictionary._suppress(200),
        "columns": [
            build(col(patients_with_value=9)),
            build(col(patients_with_value=200, n_zero=3, n_negative=2)),
            build(col(n_text=200, n_numeric=0, n_distinct=3),
                  [{"value": "a", "count": 195}, {"value": "b", "count": 5}]),
        ],
    }

    small = []

    def sweep(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                sweep(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                sweep(v, f"{path}[{i}]")
        elif isinstance(node, int) and not isinstance(node, bool):
            # Percentiles and rates are floats; the ints here are counts.
            if 0 < node < MIN and not path.endswith(".other_count"):
                small.append((path, node))

    sweep(payload)
    assert not small, f"counts below {MIN} reached the payload: {small}"


# --------------------------------------------------------------------------
# scope


def test_empty_scope_emits_false_not_a_syntax_error():
    from app.core.dictionary import Scope

    assert Scope("empty", []).where() == "false"


def test_scope_filters_by_code_and_patients():
    from app.core.dictionary import Scope

    w = Scope("s", ["age", "chol"], "SELECT patient_num FROM x").where()
    assert "concept_cd IN ('age', 'chol')" in w
    assert "patient_num IN (SELECT patient_num FROM x)" in w


def test_scope_rejects_an_unsafe_code():
    """Codes are interpolated into SQL, so they go through check_code."""
    from app.core.dictionary import Scope

    with pytest.raises(ValueError):
        Scope("s", ["ok", "bad'; DROP TABLE x; --"]).where()


def test_last_value_cte_orders_newest_first():
    """The build keeps the *last* value after an ascending sort, so this has
    to take the newest - reversing it would describe the wrong distribution
    while looking entirely plausible."""
    from app.core import quality

    sql = quality.last_value_cte("concept_cd = 'x'")
    assert "DISTINCT ON (patient_num, concept_cd)" in sql
    assert "start_date DESC" in sql
    assert "WHERE concept_cd = 'x'" in sql
