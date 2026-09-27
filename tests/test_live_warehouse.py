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


# --------------------------------------------------------------------------
# storing a transform, against the real ETL
#
# A mock passes every one of these while the real thing corrupts the payload,
# because the corruption happens container-side: the blob is read back with an
# unconditional `blob.replace("'", '"')` before `json.loads`.

SCRATCH_CODE = "ztransformtest"
SCRATCH_PATH = "/ML/_test/ztransformtest"

HOSTILE = (
    "def transform(df):\n"
    "    # a researcher's comment with an apostrophe\n"
    '    label = "double \\"quoted\\" text"\n'
    "    win = 'C:\\Users\\x'\n"
    "    note = 'na\u00efve \u00b5g/dL \u2014 caf\u00e9'\n"
    "    return df.assign(ratio=df.iloc[:, 0] / 1.0)\n"
)


@pytest.fixture
def scratch(warehouse):
    """A throwaway model concept, removed however the test ends."""
    from app.core import etl_api, ml_blob

    coded = "\\" + SCRATCH_PATH.strip("/").replace("/", "\\") + "\\"

    def drop():
        try:
            etl_api.delete("/etl/concepts", params={"cpath": coded})
        except Exception:
            pass

    drop()
    try:
        etl_api.post("/etl/concepts", json={
            "code": SCRATCH_CODE, "path": SCRATCH_PATH, "type": "assertion",
            "description": "scratch concept for transform round-trip tests",
            "blob": {"positive_patient_set": ["a"], "negative_patient_set": ["b"],
                     "data_paths": ["/HeartDisease"],
                     "label_paths": ["/HeartDisease/target"],
                     "model_type": "logistic", "hyperparameters": {}},
        })
    except Exception as e:
        pytest.skip(f"cannot create a scratch concept: {type(e).__name__}")

    if not ml_blob.exists(SCRATCH_CODE):
        drop()
        pytest.skip("the ETL accepted the create but nothing was stored")

    yield SCRATCH_CODE, SCRATCH_PATH
    drop()


def test_a_hostile_transform_round_trips_byte_for_byte(scratch):
    """Apostrophes, double quotes, backslashes, newlines and non-ASCII, through
    the real update path and back out of Postgres."""
    from app.core import transform_store as ts

    code, path = scratch
    saved = ts.save(code, path, HOSTILE, author="tester")
    back = ts.load(code)

    assert back["source"] == HOSTILE
    assert back["sha256"] == saved["sha256"]
    assert back["intact"] is True


def test_the_containers_own_repair_still_parses_the_blob(scratch):
    """The decisive check. `BaseEngine.py:53` does
    `json.loads(blob.replace("'", '"'))`, and that is what a build will do to
    this row. If it cannot parse, the build dies naming a character offset."""
    import json

    from app.core import transform_store as ts
    from app.core.config import settings
    from app.core.db import scalar

    code, path = scratch
    saved = ts.save(code, path, HOSTILE, author="tester")

    raw = scalar(f"SELECT concept_blob FROM {settings.db_schema}.concept_dimension "
                 f"WHERE concept_cd = '{code}';")
    repaired = json.loads(raw.replace("'", '"'))

    assert repaired[ts.SHA] == saved["sha256"]
    assert ts.decode(repaired)["source"] == HOSTILE


def test_storing_the_source_unencoded_would_corrupt_the_blob(scratch):
    """Why base64 is required rather than cautious.

    One apostrophe in a comment is enough: the quote swap turns it into a `"`
    in the middle of a JSON string and the parse fails. Asserting the failure
    keeps the justification honest - if this ever stops failing, the encoding
    could be reconsidered.
    """
    import json

    from app.core import etl_api, ml_blob
    from app.core.config import settings
    from app.core.db import scalar

    code, path = scratch
    blob = ml_blob.load_blob_light(code)
    blob["transform_source_raw"] = "def transform(df):\n    # it's a comment\n    return df\n"
    etl_api.put("/etl/concepts", params={
        "cpath": "\\" + path.strip("/").replace("/", "\\") + "\\",
        "blob": json.dumps(blob),
    })

    raw = scalar(f"SELECT concept_blob FROM {settings.db_schema}.concept_dimension "
                 f"WHERE concept_cd = '{code}';")
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw.replace("'", '"'))


def test_a_config_save_keeps_the_transform(scratch):
    """The silent-deletion case, end to end: ModelForm rebuilds the blob from
    scratch and this endpoint writes it whole."""
    import json

    from app.core import etl_api, ml_blob
    from app.core import transform_store as ts

    code, path = scratch
    ts.save(code, path, HOSTILE, author="tester")

    fresh = {"positive_patient_set": ["a"], "negative_patient_set": ["b"],
             "data_paths": ["/HeartDisease"], "label_paths": ["/HeartDisease/target"],
             "model_type": "random_forest", "hyperparameters": {}}
    carried = ts.carry_forward(dict(fresh), ml_blob.load_blob_light(code))
    etl_api.put("/etl/concepts", params={
        "cpath": "\\" + path.strip("/").replace("/", "\\") + "\\",
        "blob": json.dumps(carried),
    })

    assert ml_blob.load_blob_light(code)["model_type"] == "random_forest"
    assert ts.load(code)["source"] == HOSTILE


def test_a_config_save_without_the_carry_forward_destroys_it(scratch):
    """The bug the carry-forward exists to prevent, asserted so the protection
    cannot be removed as redundant."""
    import json

    from app.core import etl_api
    from app.core import transform_store as ts

    code, path = scratch
    ts.save(code, path, HOSTILE, author="tester")

    etl_api.put("/etl/concepts", params={
        "cpath": "\\" + path.strip("/").replace("/", "\\") + "\\",
        "blob": json.dumps({"model_type": "random_forest",
                            "data_paths": ["/HeartDisease"]}),
    })
    assert ts.load(code) is None


def test_clearing_a_transform_removes_every_key(scratch):
    from app.core import ml_blob
    from app.core import transform_store as ts

    code, path = scratch
    ts.save(code, path, HOSTILE, author="tester")
    ts.clear(code, path)

    assert ts.load(code) is None
    remaining = set(ts.KEYS) & set(ml_blob.load_blob_light(code))
    assert not remaining, f"left behind: {remaining}"


def test_the_update_path_refuses_an_oversized_blob_with_a_sentence(scratch):
    """Measured: 64 KB of source is HTTP 414. The raw failure is an HTML error
    page, so it is turned into something a researcher can act on."""
    from app.core import transform_store as ts

    code, path = scratch
    original = ts.MAX_SOURCE_BYTES
    ts.MAX_SOURCE_BYTES = 1024 * 1024          # bypass the local bound only
    try:
        with pytest.raises(ts.TransformError) as e:
            ts.save(code, path, "def transform(df):\n    return df\n# "
                    + "x" * (200 * 1024) + "\n")
        assert "too large" in str(e.value) and "URL" in str(e.value)
    finally:
        ts.MAX_SOURCE_BYTES = original
