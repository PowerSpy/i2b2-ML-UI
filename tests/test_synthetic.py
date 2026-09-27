"""The plan the sandbox materialises from.

The rule worth pinning hardest: **the plan can only contain numbers the
dictionary already published.** The dictionary has been through a disclosure
review; the plan inherits it only if it adds nothing, so there is a test that
sweeps every number in a plan and fails on one that is not traceable to the
input.
"""

import pytest

from app.core import synthetic


def numeric(code="chol", **over):
    col = {
        "code": code, "name": "Cholesterol", "kind": "numeric",
        "mixed_valtype": False, "patients_with_value": 200, "fill_rate": 0.8,
        "missing_rate": 0.2, "n_distinct": 150, "integer_like": False,
        "low": 126.0, "p05": 160.0, "p25": 211.0, "p50": 241.0,
        "p75": 275.0, "p95": 330.0, "high": 409.0,
        "mean": 246.5, "sd": 51.2, "suppressed": [],
    }
    col.update(over)
    return col


def categorical(code="sex", levels=None, other=0, **over):
    col = {
        "code": code, "name": None, "kind": "categorical",
        "mixed_valtype": False, "patients_with_value": 200, "fill_rate": 1.0,
        "n_distinct": 2, "integer_like": True, "suppressed": [],
        "levels": levels if levels is not None else [
            {"value": "1.0", "count": 120, "numeric": True},
            {"value": "0.0", "count": 80, "numeric": True},
        ],
        "other_count": other,
    }
    col.update(over)
    return col


def doc(*columns, patients=250):
    return {"scope": "model HD1", "note": "", "min_cell": 11,
            "patients_in_scope": patients, "columns": list(columns),
            "basis": ""}


def spec(plan, name):
    return next(c for c in plan["columns"] if c["name"] == name)


# --------------------------------------------------------------------------
# the rule the module inherits its review from


def test_the_plan_adds_no_number_the_dictionary_did_not_publish():
    """A recursive sweep, not per-field assertions.

    Per-field checks pass while a field added later leaks. What matters is
    that *no* path through the builder can introduce a value, so the whole
    payload is walked.
    """
    d = doc(numeric(), categorical(),
            numeric("rare", patients_with_value=None, fill_rate=None,
                    suppressed=["patients_with_value", "fill_rate", "quantiles"]))
    p = synthetic.plan(d, seed=1)

    published = set()

    def collect(node):
        if isinstance(node, dict):
            for v in node.values():
                collect(v)
        elif isinstance(node, list):
            for v in node:
                collect(v)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            published.add(round(float(node), 6))

    collect(d)
    # Derived quantities that are functions of published numbers, not new
    # information: the quantile grid positions, level probabilities, the seed
    # and the row-count bookkeeping.
    allowed = published | {q for q in synthetic.QUANTILES} | {
        p["seed"], p["n_rows"], p["all_nan_rows"], p["version"],
        p["index_floor"], 0.0, 1.0,
        0.6, 0.4,  # 120/200 and 80/200
    }

    leaked = []

    def sweep(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                sweep(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                sweep(v, f"{path}[{i}]")
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            if round(float(node), 6) not in allowed:
                leaked.append((path, node))

    sweep(p)
    assert not leaked, f"the plan invented numbers: {leaked}"


def test_no_field_named_min_or_max_survives():
    p = synthetic.plan(doc(numeric()), seed=1)
    text = repr(p)
    for forbidden in ("'min'", "'max'", "minimum", "maximum"):
        assert forbidden not in text


# --------------------------------------------------------------------------
# suppressed columns still have to exist


def test_a_withheld_column_is_present_and_empty():
    """It must be in the frame. A column that exists in production and not in
    development makes `df['x']` behave differently in the two places, which is
    the one thing the dev loop is supposed to rule out."""
    d = doc(numeric("rare", patients_with_value=None, fill_rate=None,
                    suppressed=["patients_with_value", "fill_rate", "quantiles"]))
    p = synthetic.plan(d, seed=1)
    s = spec(p, "rare")

    assert s["kind"] == "empty"
    assert s["fill_rate"] == 0.0
    assert any("withheld" in w for w in p["warnings"])
    # And the researcher is told, because code that skips an all-NaN column
    # here will not skip it in production.
    assert any("production" in n for n in s["notes"])


def test_a_column_with_a_count_but_no_shape_becomes_a_constant():
    """Between one cell and two the dictionary publishes the count and withholds
    the distribution. Inventing a range here would invent exactly the thing it
    refused to say."""
    d = doc(numeric("bp", patients_with_value=15, fill_rate=0.06,
                    suppressed=["quantiles"],
                    low=None, p05=None, p25=None, p50=None, p75=None,
                    p95=None, high=None))
    p = synthetic.plan(d, seed=1)
    s = spec(p, "bp")

    assert s["kind"] == "constant"
    assert s["fill_rate"] == 0.06     # the published fact survives
    assert any("filled with a constant" in w for w in p["warnings"])


# --------------------------------------------------------------------------
# levels


def test_integer_coded_levels_keep_their_type():
    """`df['sex'] == 1` has to mean the same thing in both places. A level
    materialised as the string "1" would make it false here and true there."""
    p = synthetic.plan(doc(categorical()), seed=1)
    values = [lv["value"] for lv in spec(p, "sex")["levels"]]

    assert values == [1.0, 0.0]
    assert all(isinstance(v, float) for v in values)


def test_text_levels_stay_text():
    d = doc(categorical(levels=[{"value": "M", "count": 120, "numeric": False},
                                {"value": "F", "count": 80, "numeric": False}]))
    assert [lv["value"] for lv in spec(synthetic.plan(d, seed=1), "sex")["levels"]] \
        == ["M", "F"]


def test_other_becomes_a_level_and_is_flagged():
    """Dropping it would understate the fill rate, and a NaN there would say
    the column is sparser than it is. But it is a value production never
    produces, so it does not go in quietly."""
    d = doc(categorical(levels=[{"value": "M", "count": 120, "numeric": False},
                                {"value": "F", "count": 60, "numeric": False}],
                        other=20))
    p = synthetic.plan(d, seed=1)
    s = spec(p, "sex")

    assert [lv["value"] for lv in s["levels"]] == ["M", "F", "other"]
    assert s["levels"][-1]["p"] == pytest.approx(0.1)
    assert any("placeholder level" in w for w in p["warnings"])


def test_probabilities_sum_to_one():
    d = doc(categorical(levels=[{"value": "a", "count": 33, "numeric": False},
                                {"value": "b", "count": 33, "numeric": False},
                                {"value": "c", "count": 34, "numeric": False}]))
    ps = [lv["p"] for lv in spec(synthetic.plan(d, seed=1), "sex")["levels"]]
    assert sum(ps) == pytest.approx(1.0, abs=1e-5)


def test_a_placeholder_never_collides_with_a_real_level():
    d = doc(categorical(levels=[{"value": "other", "count": 150, "numeric": False},
                                {"value": "M", "count": 30, "numeric": False}],
                        other=20))
    values = [lv["value"] for lv in spec(synthetic.plan(d, seed=1), "sex")["levels"]]
    assert values == ["other", "M", "other_1"]
    assert len(set(values)) == len(values)


# --------------------------------------------------------------------------
# the grid


def test_the_grid_is_ascending_and_built_from_p01_to_p99():
    g = spec(synthetic.plan(doc(numeric()), seed=1), "chol")["quantiles"]

    assert [q for q, _ in g] == synthetic.QUANTILES
    assert [v for _, v in g] == sorted(v for _, v in g)
    assert g[0][1] == 126.0 and g[-1][1] == 409.0


def test_a_non_monotone_grid_is_clamped_and_said_out_loud():
    """A column carrying both numeric and text rows can produce a grid that
    goes backwards, and the sandbox's inverse-CDF walk would then run in
    reverse while looking entirely plausible."""
    d = doc(numeric(p50=100.0))     # below p25
    p = synthetic.plan(d, seed=1)
    g = spec(p, "chol")["quantiles"]

    assert [v for _, v in g] == sorted(v for _, v in g)
    assert any("not ascending" in w for w in p["warnings"])


def test_a_partial_grid_still_works():
    d = doc(numeric(p05=None, p25=None, p95=None))
    g = spec(synthetic.plan(d, seed=1), "chol")["quantiles"]
    assert [q for q, _ in g] == [0.01, 0.50, 0.75, 0.99]


def test_too_few_percentiles_becomes_an_empty_column():
    d = doc(numeric(low=None, p05=None, p25=None, p50=None, p75=None,
                    p95=None, high=None))
    p = synthetic.plan(d, seed=1)
    assert spec(p, "chol")["kind"] == "empty"
    assert any("no percentiles" in w for w in p["warnings"])


# --------------------------------------------------------------------------
# shape of the frame


def test_row_count_follows_the_published_patient_count():
    assert synthetic.plan(doc(numeric(), patients=250), seed=1)["n_rows"] == 250


def test_a_withheld_patient_count_does_not_become_a_row_count():
    """Generating 9 rows because the cohort has 9 patients would republish the
    number the dictionary withheld."""
    p = synthetic.plan(doc(numeric(), patients=None), seed=1)
    assert p["n_rows"] == synthetic.DEFAULT_ROWS


def test_row_count_is_bounded():
    assert synthetic.plan(doc(numeric()), n_rows=10**9)["n_rows"] == synthetic.MAX_ROWS
    assert synthetic.plan(doc(numeric()), n_rows=1)["n_rows"] == synthetic.MIN_ROWS


def test_wholly_nan_rows_are_forced():
    """Independent fill rates would essentially never produce one, and the real
    frame has them - a cohort patient with a label and no feature facts."""
    assert synthetic.plan(doc(numeric(), categorical()), seed=1)["all_nan_rows"] > 0


def test_the_index_is_opaque_ids_not_patient_numbers_and_not_a_range():
    """Not a RangeIndex, and that is not a detail. `reset_index(drop=True)`
    after a filter gives 0..k-1, which is a valid subset of 0..n-1 - so the
    validator would accept a frame in which every row had been renumbered and
    every prediction would go to the wrong patient. Ids above a floor make
    that renumbering impossible to mistake for a filter."""
    p = synthetic.plan(doc(numeric()), seed=1)
    assert p["index"] == "opaque"
    assert p["index_floor"] >= 1_000_000


def test_the_seed_is_stable_across_processes():
    """A researcher comparing two versions of a transform needs the difference
    to be theirs. `hash()` is salted per process and would not do."""
    a = synthetic.plan(doc(numeric()))
    b = synthetic.plan(doc(numeric()))
    assert a["seed"] == b["seed"]
    assert synthetic.plan(doc(numeric(), patients=9))["seed"] == a["seed"]
    assert synthetic.plan({**doc(numeric()), "scope": "model HD2"})["seed"] != a["seed"]


def test_hostile_mode_makes_the_frame_worse_not_different():
    normal = synthetic.plan(doc(numeric()), seed=1)
    mean = synthetic.plan(doc(numeric()), seed=1, hostile=True)

    assert spec(mean, "chol")["fill_rate"] < spec(normal, "chol")["fill_rate"]
    assert spec(mean, "chol")["quantiles"][0][1] < spec(normal, "chol")["quantiles"][0][1]
    assert spec(mean, "chol")["quantiles"][-1][1] > spec(normal, "chol")["quantiles"][-1][1]
    assert mean["all_nan_rows"] > normal["all_nan_rows"]


def test_integerness_is_carried():
    """The sandbox rounds on it. A wrong answer produces ages of 54.3718."""
    assert spec(synthetic.plan(doc(numeric(integer_like=True))), "chol")["integer"]
    assert not spec(synthetic.plan(doc(numeric(integer_like=False))), "chol")["integer"]


def test_the_plan_is_json_and_nothing_but_json():
    """It crosses a process boundary as text. A numpy scalar or a Decimal here
    would serialise on the host and fail in the container."""
    import json

    p = synthetic.plan(doc(numeric(), categorical()), seed=1)
    assert json.loads(json.dumps(p, allow_nan=False)) == p


def test_a_column_order_matches_the_dictionary():
    """The frame's column order is part of its shape, and the dictionary's
    order is the build's."""
    d = doc(numeric("a"), categorical("b"), numeric("c"))
    assert [c["name"] for c in synthetic.plan(d)["columns"]] == ["a", "b", "c"]
