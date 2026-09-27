"""Tests that need a real warehouse, skipped when there is not one.

Everything else in this suite runs against fabricated rows, and fabricated
rows agree with whatever the code believes. These are here because that turned
out not to be enough: the dictionary's SQL was unit-tested, passing, and wrong
about every categorical column in the database.

What the fabricated rows could not know is how i2b2 actually stores a value -
`tval_char='E'` on every numeric fact, as the operator flag for "equals". The
shaping logic was fine. The assumption underneath it was not.

Run with the stack up. They skip, rather than fail, when it is down, so the
suite stays usable offline - but a green run that skipped these has not
checked the half that has historically been wrong.
"""

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def warehouse():
    """Skip unless the warehouse answers, and decide that quickly.

    The probe goes through `docker_exec` with a short timeout rather than
    `db.query`, which allows 300 seconds. With the daemon down, `docker` does
    not fail - it blocks - so the default would turn "skip these offline" into
    a five-minute stall before the first skip.
    """
    import shlex
    import subprocess

    from app.core.config import settings
    from app.core.docker_exec import exec as container_exec

    # Only the failures that really mean "no stack" skip. A bare
    # `except Exception` here silently disabled all twelve of these tests when
    # this fixture named a setting that does not exist - a green run that had
    # checked nothing, which is the exact failure mode this file was written
    # to close.
    try:
        out = container_exec(
            settings.db_container,
            f"{settings.psql} -tAc {shlex.quote('SELECT 1')}", timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        pytest.skip(f"no warehouse: {type(e).__name__}")
    if out.returncode != 0:
        pytest.skip(f"no warehouse: {(out.stderr or '').strip()[:120]}")

    from app.core import dictionary
    return dictionary


@pytest.fixture(scope="module")
def described(warehouse):
    return warehouse.describe(warehouse.warehouse_scope())


# --------------------------------------------------------------------------
# the SQL runs at all


def test_the_dictionary_sql_executes(described):
    """`percentile_cont`, `FILTER` and `DISTINCT ON` in one statement, which
    had never been executed against Postgres when it was written."""
    assert described["columns"], "no columns came back"
    assert described["patients_in_scope"] is not None


def test_last_value_is_one_row_per_patient_per_concept(warehouse):
    """The build pivots with aggfunc='last'. Statistics over *every* fact
    describe a distribution nothing is ever trained on, and this warehouse
    averages well over one fact per patient per concept."""
    from app.core import quality
    from app.core.db import query

    sql = quality.last_value_cte("concept_cd = 'age'")
    row = query(f"WITH lv AS ({sql}) "
                "SELECT count(*) AS n, count(DISTINCT patient_num) AS p FROM lv;")[0]

    assert int(row["n"]) == int(row["p"]) > 0


# --------------------------------------------------------------------------
# the assumption that was wrong


def test_the_operator_flag_never_becomes_a_level(described):
    """i2b2 writes tval_char='E' on numeric facts. Reading text first made
    every integer-coded concept a single-level category called 'E'."""
    offenders = [
        c["code"] for c in described["columns"]
        if any(str(lv["value"]) == "E" for lv in (c.get("levels") or []))
    ]
    assert not offenders, f"the operator flag leaked in as a level: {offenders}"


def test_integer_coded_categories_report_their_real_levels(described):
    """cp is chest-pain type and has four. Getting one back is the signature
    of reading the operator flag instead of the value."""
    by_code = {c["code"]: c for c in described["columns"]}
    if "cp" not in by_code:
        pytest.skip("no cp concept in this warehouse")

    cp = by_code["cp"]
    assert cp["kind"] == "categorical"
    assert len(cp["levels"]) >= 3, cp["levels"]
    assert all(isinstance(lv["value"], str) for lv in cp["levels"])


def test_not_every_column_is_mixed_type(described):
    """Counting 'E' as a text value marked all 35 columns as carrying both
    numeric and text rows - a red flag on every row of the UI, meaning
    nothing."""
    mixed = [c["code"] for c in described["columns"] if c["mixed_valtype"]]
    assert len(mixed) < len(described["columns"]) / 2, mixed


def test_membership_flags_are_named_rather_than_left_null(described):
    """A concept carrying neither value column reported as numeric with every
    percentile null, which the UI renders the same as "not loaded yet"."""
    flags = [c for c in described["columns"] if c["kind"] == "flag"]
    for c in flags:
        assert c["empty_in_build"] is True
        assert c["build_note"]
        assert c.get("low") is None


def test_every_column_the_build_cannot_read_is_marked(described, warehouse):
    """The pivot reads only nval_num. Any concept with no numeric values is an
    all-NaN feature, and the dictionary has to say so or a researcher will
    write code against levels that exist only in the warehouse."""
    from app.core.db import query

    codes = [c["code"] for c in described["columns"] if c["empty_in_build"]]
    if not codes:
        pytest.skip("every concept here has numeric values")

    joined = ", ".join(f"'{c}'" for c in codes)
    row = query(f"SELECT count(*) AS n FROM {warehouse.SCHEMA}.observation_fact "
                f"WHERE concept_cd IN ({joined}) AND nval_num IS NOT NULL;")[0]
    assert int(row["n"]) == 0, (
        f"{codes} were marked empty in the build but have numeric values")


# --------------------------------------------------------------------------
# suppression, against real counts


def test_no_count_below_the_threshold_reaches_a_real_payload(described):
    """The same recursive sweep the unit tests do, against numbers nobody
    chose."""
    small = []

    def sweep(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                sweep(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                sweep(v, f"{path}[{i}]")
        elif isinstance(node, int) and not isinstance(node, bool):
            if 0 < node < described["min_cell"] and not path.endswith(".other_count"):
                small.append((path, node))

    sweep(described)
    assert not small, f"counts below the threshold reached the payload: {small}"


def test_no_raw_extreme_is_reported(described, warehouse):
    """`low` is p01 and `high` is p99. A true maximum is one patient's value,
    and on a small cohort often an identifying one."""
    from app.core.db import query

    for c in described["columns"]:
        if c.get("low") is None or c["kind"] != "numeric":
            continue
        row = query(f"SELECT min(nval_num) AS lo, max(nval_num) AS hi "
                    f"FROM {warehouse.SCHEMA}.observation_fact "
                    f"WHERE concept_cd = '{c['code']}' AND nval_num IS NOT NULL;")[0]
        if row["lo"] in (None, ""):
            continue
        assert c["low"] >= float(row["lo"]), f"{c['code']} published the true minimum"
        assert c["high"] <= float(row["hi"]), f"{c['code']} published the true maximum"


# --------------------------------------------------------------------------
# the generator, against a real dictionary


def test_a_plan_from_the_real_dictionary_is_serialisable(described):
    """It crosses a process boundary as text. A Decimal from psql or a numpy
    scalar would serialise on the host and fail in the container."""
    import json

    from app.core import synthetic

    p = synthetic.plan(described, n_rows=50)
    assert json.loads(json.dumps(p, allow_nan=False)) == p


def test_every_real_column_survives_into_the_plan(described):
    """A column missing from the frame makes `df['x']` raise in development
    and work in production."""
    from app.core import synthetic

    p = synthetic.plan(described, n_rows=50)
    assert [c["name"] for c in p["columns"]] == [c["code"] for c in described["columns"]]


def test_columns_the_build_cannot_read_are_empty_in_the_plan(described):
    """The worst divergence available: real levels in development against an
    all-NaN column in production."""
    from app.core import synthetic

    p = synthetic.plan(described, n_rows=50)
    by_name = {c["name"]: c for c in p["columns"]}
    for c in described["columns"]:
        if c["empty_in_build"]:
            assert by_name[c["code"]]["kind"] == "empty", c["code"]
