"""The sandbox runner, driven as a real subprocess.

`docker run` is not available here, but the container is only the *isolation*.
Everything the runner actually does - parse the request, guard the source,
materialise the plan, execute the transform, validate what comes back, and
write exactly one JSON document to stdout - is a subprocess away, so it is
tested as one rather than by importing the pieces and asserting on them
individually.

**What this file does not cover:** `--network none`, the memory limit, the
pids limit, the read-only root, and the OOM-versus-timeout distinction. Those
are properties of the `docker run` line in `app/core/sandbox.py` and need a
reachable daemon. `test_sandbox_args.py` pins the flags; nothing here proves
they work.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from app.core import synthetic

SANDBOX = Path(__file__).resolve().parents[1] / "sandbox"


# --------------------------------------------------------------------------
# harness


def a_plan(n_rows=120, **over):
    """A dictionary payload shaped like the heart data, turned into a plan."""
    columns = [
        {"code": "age", "name": "Age", "kind": "numeric", "fill_rate": 1.0,
         "patients_with_value": 200, "integer_like": True, "suppressed": [],
         "low": 29.0, "p05": 35.0, "p25": 48.0, "p50": 56.0, "p75": 61.0,
         "p95": 68.0, "high": 71.0},
        {"code": "chol", "name": "Cholesterol", "kind": "numeric",
         "fill_rate": 0.7, "patients_with_value": 200, "integer_like": False,
         "suppressed": [], "low": 126.0, "p05": 160.0, "p25": 211.0,
         "p50": 241.0, "p75": 275.0, "p95": 330.0, "high": 409.0},
        {"code": "sex", "name": None, "kind": "categorical", "fill_rate": 1.0,
         "patients_with_value": 200, "integer_like": True, "suppressed": [],
         "levels": [{"value": "1.0", "count": 120, "numeric": True},
                    {"value": "0.0", "count": 80, "numeric": True}],
         "other_count": 0},
        {"code": "rare", "name": None, "kind": "numeric", "fill_rate": None,
         "patients_with_value": None, "integer_like": False,
         "suppressed": ["patients_with_value", "fill_rate", "quantiles"]},
    ]
    doc = {"scope": "test", "note": "", "min_cell": 11,
           "patients_in_scope": 200, "columns": columns, "basis": ""}
    return synthetic.plan(doc, n_rows=n_rows, seed=7, **over)


def run(source, plan=None, timeout=120):
    """Invoke the runner exactly as the container's ENTRYPOINT does."""
    request = json.dumps({"mode": "dry-run", "source": source,
                          "plan": plan or a_plan()})
    p = subprocess.run(
        [sys.executable, "-m", "runner.run"],
        input=request, capture_output=True, text=True,
        cwd=str(SANDBOX), timeout=timeout,
    )
    assert p.stdout.strip(), f"no response. stderr:\n{p.stderr}"
    return json.loads(p.stdout), p


def ok(source, **kw):
    payload, _ = run(source, **kw)
    assert payload["ok"], payload["error"]
    return payload


def refused(source, kind, **kw):
    payload, proc = run(source, **kw)
    assert not payload["ok"], f"expected a refusal, got {payload['report']}"
    assert payload["error"]["kind"] == kind, payload["error"]
    assert proc.returncode == 1
    return payload["error"]["message"]


# --------------------------------------------------------------------------
# the happy path


def test_a_transform_runs_and_reports_what_it_changed():
    payload = ok(
        "def transform(df):\n"
        "    df['chol_per_year'] = df['chol'] / df['age']\n"
        "    return df\n"
    )
    report = payload["report"]

    assert report["changed"] is True
    assert report["columns_added"] == ["chol_per_year"]
    assert report["columns_removed"] == []
    assert report["rows_dropped"] == 0
    assert "chol_per_year" in payload["preview"]["columns"]
    # The frame that went in comes back too - half of reading a diff.
    assert "chol_per_year" not in payload["input_preview"]["columns"]


def test_the_response_is_valid_json_even_though_the_frame_is_full_of_nan():
    """`json.dumps` will happily emit a bare `NaN`, which only Python can read
    back. The preview converts them to null and the runner refuses to
    serialise one that got through."""
    payload = ok("def transform(df):\n    return df\n")
    flat = [v for row in payload["preview"]["rows"] for v in row]

    assert None in flat, "expected some missing values in the preview"
    assert "NaN" not in json.dumps(payload)


def test_row_filtering_is_allowed_and_counted():
    payload = ok(
        "def transform(df):\n"
        "    return df[df['age'].notna() & (df['age'] > 50)]\n"
    )
    assert payload["report"]["rows_dropped"] > 0
    assert payload["report"]["rows_out"] < payload["report"]["rows_in"]


def test_an_unchanged_frame_passes_but_does_not_pass_quietly():
    """"Succeeded and did nothing" is the failure this whole feature exists to
    make visible, so it is not going to be the one thing that slips through."""
    payload = ok("def transform(df):\n    return df\n")

    assert payload["report"]["changed"] is False
    assert any("unchanged" in w for w in payload["report"]["warnings"])


# --------------------------------------------------------------------------
# the print that would corrupt the envelope


def test_a_print_in_the_transform_does_not_corrupt_the_response():
    """The reason `run.py` takes fd 1 away before any user code runs.

    Without it this test's `print` lands in the middle of the JSON document
    and the host reports a parse error at a character offset, with nothing
    pointing at the researcher's debug line.
    """
    payload, proc = run(
        "print('top level noise')\n"
        "def transform(df):\n"
        "    print(df.head())\n"
        "    print('shape', df.shape)\n"
        "    return df.assign(x=1.0)\n"
    )

    assert payload["ok"], payload["error"]
    assert proc.stdout.strip().count("\n") == 0, "stdout is not a single JSON line"
    assert "top level noise" in payload["logs"]
    assert "shape" in payload["logs"]


def test_a_print_in_failing_code_still_returns_its_output():
    """The prints are usually why the researcher added them."""
    payload, _ = run(
        "def transform(df):\n"
        "    print('got here')\n"
        "    raise ValueError('nope')\n"
    )
    assert not payload["ok"]
    assert "got here" in payload["logs"]


def test_a_flood_of_output_is_clipped_rather_than_returned():
    payload = ok(
        "def transform(df):\n"
        "    for i in range(50000):\n"
        "        print('x' * 40)\n"
        "    return df\n"
    )
    assert len(payload["logs"]) < 40000
    assert "suppressed" in payload["logs"]


# --------------------------------------------------------------------------
# refusals before anything runs


def test_a_syntax_error_names_a_line():
    msg = refused("def transform(df)\n    return df\n", "rejected")
    assert "line 1" in msg


def test_a_missing_entrypoint_says_what_was_found_instead():
    msg = refused("def my_transform(df):\n    return df\n", "rejected")
    assert "transform" in msg and "my_transform" in msg


def test_a_blocked_import_names_the_module_and_the_reason():
    msg = refused("import os\ndef transform(df):\n    return df\n", "rejected")
    assert "os" in msg and "no network" in msg


def test_a_blocked_import_is_caught_in_a_from_form_too():
    msg = refused("from socket import socket\n"
                  "def transform(df):\n    return df\n", "rejected")
    assert "socket" in msg


def test_the_allowed_libraries_actually_import():
    """An allowlist that names something the image does not have is a refusal
    dressed as permission."""
    ok("import numpy as np\n"
       "import pandas as pd\n"
       "import math, itertools, collections\n"
       "def transform(df):\n"
       "    return df.assign(z=np.sqrt(df['age'].abs()))\n")


def test_the_wrong_number_of_arguments_is_refused():
    msg = refused("def transform(df, extra):\n    return df\n", "rejected")
    assert "one argument" in msg


# --------------------------------------------------------------------------
# the researcher's own errors


def test_an_exception_shows_the_researchers_frames_and_not_the_runners():
    """A traceback through `run.py` sends people to read the runner looking
    for their bug."""
    msg = refused("def transform(df):\n"
                  "    return df['nope_not_a_column']\n", "raised")

    assert "transform.py" in msg
    assert "run.py" not in msg and "contextlib" not in msg
    assert "nope_not_a_column" in msg


def test_returning_none_gets_its_own_sentence():
    """It will be the most common mistake by a wide margin, and `'NoneType'
    object has no attribute 'shape'` explains nothing."""
    msg = refused("def transform(df):\n    df['x'] = 1.0\n", "invalid_output")
    assert "forget to `return df`" in msg


def test_returning_a_series_says_how_to_fix_it():
    msg = refused("def transform(df):\n    return df['age'] * 2\n",
                  "invalid_output")
    assert "Series" in msg and "return the frame" in msg


# --------------------------------------------------------------------------
# what the rest of the pipeline cannot survive


def test_an_apostrophe_in_a_column_name_is_refused():
    """It lands in the model blob, which is read back through an unconditional
    `blob.replace("'", '"')`. One of these corrupts the entire stored model
    with an error that names a character offset in JSON nobody wrote."""
    msg = refused("def transform(df):\n"
                  "    df[\"patient's age\"] = df['age']\n"
                  "    return df\n", "invalid_output")
    assert "blob" in msg


def test_a_backslash_in_a_column_name_is_refused():
    msg = refused("def transform(df):\n"
                  "    df['a\\\\b'] = df['age']\n"
                  "    return df\n", "invalid_output")
    assert "corrupt" in msg


def test_label_is_reserved():
    """The engine sets it after the transform runs, so a column of that name
    is silently overwritten."""
    msg = refused("def transform(df):\n"
                  "    df['label'] = 1.0\n    return df\n", "invalid_output")
    assert "reserved" in msg


def test_subject_id_is_reserved():
    msg = refused("def transform(df):\n"
                  "    df['subject_id'] = 1.0\n    return df\n", "invalid_output")
    assert "reserved" in msg


def test_a_text_column_is_refused_before_the_scaler_sees_it():
    msg = refused("def transform(df):\n"
                  "    df['band'] = 'high'\n    return df\n", "invalid_output")
    assert "RobustScaler" in msg


def test_infinities_are_refused():
    """They survive `fillna(0)` and then break the scaler with an error naming
    neither the column nor the division that produced them."""
    msg = refused("def transform(df):\n"
                  "    df['ratio'] = df['age'].fillna(1) / 0\n"
                  "    return df\n", "invalid_output")
    assert "infinite" in msg and "inf" in msg


def test_an_all_nan_column_is_refused():
    """After `fillna(0)` it is an all-zero feature the selector may still
    pick - a column carrying no information, reported as if it did."""
    msg = refused("import numpy as np\n"
                  "def transform(df):\n"
                  "    df['empty'] = np.nan\n    return df\n", "invalid_output")
    assert "entirely NaN" in msg


def test_an_empty_frame_is_refused():
    msg = refused("def transform(df):\n"
                  "    return df[df['age'] > 10000]\n", "invalid_output")
    assert "no rows" in msg


# --------------------------------------------------------------------------
# the index, which is how patient numbers get re-attached


def test_a_reset_index_is_refused():
    """`reset_index(drop=True)` after a filter renumbers the rows. Patient
    numbers are matched back by index, so this is the mistake that would
    attach predictions to the wrong people."""
    msg = refused("def transform(df):\n"
                  "    return df[df['age'].notna()].reset_index(drop=True)\n",
                  "invalid_output")
    assert "index" in msg


def test_duplicated_rows_are_refused():
    msg = refused("import pandas as pd\n"
                  "def transform(df):\n"
                  "    return pd.concat([df, df])\n", "invalid_output")
    assert "duplicates" in msg


def test_keeping_the_index_through_a_filter_is_fine():
    payload = ok("def transform(df):\n"
                 "    out = df[df['age'].notna()].copy()\n"
                 "    out['flag'] = (out['age'] > 55).astype(float)\n"
                 "    return out\n")
    assert payload["report"]["columns_added"] == ["flag"]


# --------------------------------------------------------------------------
# the frame the plan produced


def test_the_frame_has_the_columns_the_plan_asked_for_in_order():
    payload = ok("def transform(df):\n    return df.assign(x=1.0)\n")
    assert payload["input_preview"]["columns"] == ["age", "chol", "sex", "rare"]


def test_a_withheld_column_arrives_all_nan_rather_than_missing():
    """It has to be in the frame. A column that exists in production and not
    in development is the one thing the dev loop must not allow."""
    payload = ok("def transform(df):\n"
                 "    assert 'rare' in df.columns\n"
                 "    assert df['rare'].isna().all()\n"
                 "    return df.assign(x=1.0)\n")
    assert payload["ok"]


def test_a_wholly_nan_row_is_present():
    """The shape that breaks a transform dividing by a row total. Independent
    fill rates would essentially never produce one on their own."""
    ok("def transform(df):\n"
       "    assert df.isna().all(axis=1).any(), 'no all-NaN row'\n"
       "    return df.assign(x=1.0)\n")


def test_an_integer_column_holds_whole_numbers():
    """A wrong answer here produces ages of 54.3718."""
    ok("def transform(df):\n"
       "    ages = df['age'].dropna()\n"
       "    assert (ages == ages.round()).all(), ages.head().tolist()\n"
       "    return df.assign(x=1.0)\n")


def test_a_categorical_column_holds_only_its_declared_levels():
    ok("def transform(df):\n"
       "    seen = set(df['sex'].dropna().unique())\n"
       "    assert seen <= {0.0, 1.0}, seen\n"
       "    return df.assign(x=1.0)\n")


def test_fill_rates_are_roughly_honoured():
    """Not exact - they are draws. But a column declared 70% populated that
    arrives fully populated would hide every missing-value bug."""
    ok("def transform(df):\n"
       "    rate = df['chol'].notna().mean()\n"
       "    assert 0.5 < rate < 0.85, rate\n"
       "    assert df['age'].notna().mean() > 0.9\n"
       "    return df.assign(x=1.0)\n")


def test_values_outside_the_published_percentiles_occur():
    """`np.interp` clamps, which would put a hard floor at p01 and a ceiling at
    p99. A transform clipping to the observed range would then look correct
    here and silently reshape real data, which has 2% of its values outside."""
    ok("def transform(df):\n"
       "    chol = df['chol'].dropna()\n"
       "    assert (chol < 126.0).any() or (chol > 409.0).any()\n"
       "    return df.assign(x=1.0)\n", plan=a_plan(n_rows=2000))


def test_the_same_seed_gives_the_same_frame():
    """A researcher comparing two versions of a transform needs the difference
    to be theirs."""
    src = ("def transform(df):\n"
           "    return df.assign(total=df['age'].fillna(0) + df['chol'].fillna(0))\n")
    assert ok(src)["preview"] == ok(src)["preview"]


def test_hostile_mode_is_harder_to_survive():
    src = ("def transform(df):\n"
           "    assert df['chol'].notna().mean() > 0.6, 'too sparse'\n"
           "    return df.assign(x=1.0)\n")
    ok(src)
    payload, _ = run(src, plan=a_plan(hostile=True))
    assert not payload["ok"]
    assert "too sparse" in payload["error"]["message"]


# --------------------------------------------------------------------------
# protocol


def test_an_unknown_mode_is_refused_by_name():
    p = subprocess.run(
        [sys.executable, "-m", "runner.run"],
        input=json.dumps({"mode": "sideways", "source": "", "plan": a_plan()}),
        capture_output=True, text=True, cwd=str(SANDBOX), timeout=60,
    )
    payload = json.loads(p.stdout)
    assert payload["error"]["kind"] == "protocol"
    assert "dry-run" in payload["error"]["message"]


def test_the_real_mode_needs_a_frame():
    """`run` is the ETL container's path and carries a parquet frame. Without
    one there is nothing to transform, and saying so beats a traceback."""
    p = subprocess.run(
        [sys.executable, "-m", "runner.run"],
        input=json.dumps({"mode": "run", "source": "def transform(df): return df"}),
        capture_output=True, text=True, cwd=str(SANDBOX), timeout=60,
    )
    payload = json.loads(p.stdout)
    assert payload["error"]["kind"] == "protocol"
    assert "no frame" in payload["error"]["message"]


def test_the_real_mode_returns_no_preview():
    """The invariant that separates a debugging aid from an export, asserted
    where the frame is real. The dry run above returns rows because its rows
    are fabricated."""
    import base64
    import io

    import pandas as pd

    buf = io.BytesIO()
    sent = pd.DataFrame({"a": [1.0, 2.0]}, index=pd.Index([1000000, 1000007]))
    sent.to_parquet(buf, index=True)

    p = subprocess.run(
        [sys.executable, "-m", "runner.run"],
        input=json.dumps({
            "mode": "run",
            "source": "def transform(df):\n    return df.assign(b=1.0)\n",
            "frame_parquet_b64": base64.b64encode(buf.getvalue()).decode(),
        }),
        capture_output=True, text=True, cwd=str(SANDBOX), timeout=120,
    )
    payload = json.loads(p.stdout)

    assert payload["ok"], payload["error"]
    assert payload["preview"] is None
    assert payload["input_preview"] is None
    assert payload["frame_parquet_b64"]


def test_an_unreadable_request_still_produces_an_envelope():
    """Whatever happens, the host gets JSON back. A bare non-zero exit with
    empty stdout is reported as "the sandbox crashed", which is true but
    useless."""
    p = subprocess.run(
        [sys.executable, "-m", "runner.run"],
        input="not json at all", capture_output=True, text=True,
        cwd=str(SANDBOX), timeout=60,
    )
    payload = json.loads(p.stdout)
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "protocol"
