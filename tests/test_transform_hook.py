"""The container-side hook: keeping labels and patient numbers aligned.

This module lives in `docker-changes/` because it runs inside the ETL
container, but its alignment logic is ordinary Python and the consequence of
getting it wrong is the worst failure available in this feature - one
patient's prediction written against another. So it is tested here rather than
only exercised by a live build.

`load_pred_facts` pairs predictions to patients **positionally**:

    for index, patient_num in enumerate(pt_num_list):
        if Y_pred[index]:

so if a transform drops rows, `y` and `pt_num_list` must lose exactly those
rows, in that order.
"""

import base64
import hashlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docker-changes"))
from i2b2_cdi.ML import transform_hook as hook  # noqa: E402


def blob_for(source: str) -> dict:
    raw = source.encode("utf-8")
    return {"transform_b64": base64.b64encode(raw).decode("ascii"),
            "transform_sha256": hashlib.sha256(raw).hexdigest()}


SRC = "def transform(df):\n    return df\n"


# --------------------------------------------------------------------------
# reading what was stored


def test_a_transform_whose_checksum_does_not_match_is_refused():
    """The blob is repaired by a blind quote swap on its way out of the
    database. Something that decoded but changed is not the code anyone
    approved, and building from it silently is the failure this prevents."""
    b = blob_for(SRC)
    b["transform_sha256"] = "0" * 64

    with pytest.raises(hook.TransformFailed) as e:
        hook.read_source(b)
    assert "does not match its checksum" in str(e.value)


def test_undecodable_source_is_refused_with_a_fix():
    with pytest.raises(hook.TransformFailed) as e:
        hook.read_source({"transform_b64": "not base64!!"})
    assert "Re-save it" in str(e.value)


def test_a_model_without_a_transform_reads_as_none():
    assert hook.read_source({}) == (None, None)
    assert hook.has_transform({}) is False
    assert hook.has_transform(blob_for(SRC)) is True


def test_a_model_without_a_transform_is_left_completely_alone():
    """No spool request, no waiting, no behaviour change for every model that
    does not use this feature."""
    X = pd.DataFrame({"a": [1.0, 2.0]})
    y = pd.Series([0, 1])
    pt = pd.Series([10, 11])

    X2, y2, pt2, report = hook.run_transform(X, y, pt, {})

    assert X2 is X and y2 is y and pt2 is pt
    assert report == {"transform_applied": False}


# --------------------------------------------------------------------------
# the alignment, which is the whole point


def positions_for(returned_index, n=5):
    ids = hook.INDEX_FLOOR + np.arange(n) * hook.INDEX_STRIDE
    position = {int(i): p for p, i in enumerate(ids)}
    out = pd.DataFrame({"a": range(len(returned_index))},
                       index=pd.Index(returned_index))
    return hook._positions(out, position, n)


def test_a_filtered_frame_maps_back_to_the_rows_it_kept():
    ids = hook.INDEX_FLOOR + np.arange(5) * hook.INDEX_STRIDE
    assert positions_for([ids[1], ids[3]]) == [1, 3]


def test_a_renumbered_index_is_refused():
    """`reset_index(drop=True)` after a filter yields 0..k-1. Against a plain
    RangeIndex that is a valid subset and would pass, renumbering every row
    and attributing every prediction to the wrong patient. Ids above a floor
    make it detectable."""
    with pytest.raises(hook.TransformFailed) as e:
        positions_for([0, 1, 2])
    assert "not handed to it" in str(e.value)


def test_a_duplicated_row_is_refused():
    """Two rows carrying one patient's id would write that patient two
    predictions."""
    ids = hook.INDEX_FLOOR + np.arange(5) * hook.INDEX_STRIDE
    with pytest.raises(hook.TransformFailed) as e:
        positions_for([ids[0], ids[0]])
    assert "more than once" in str(e.value)


def test_an_empty_frame_is_refused():
    with pytest.raises(hook.TransformFailed) as e:
        positions_for([])
    assert "no rows" in str(e.value)


def test_the_row_ids_handed_out_are_opaque_and_non_contiguous():
    """Non-contiguous as well as offset, so code assuming `index[i] == i` or
    `index[i] == i + floor` fails in development rather than production."""
    assert hook.INDEX_FLOOR >= 1_000_000
    assert hook.INDEX_STRIDE > 1

    ids = hook.INDEX_FLOOR + np.arange(4) * hook.INDEX_STRIDE
    assert min(ids) >= hook.INDEX_FLOOR
    assert len(set(ids)) == 4
    assert list(np.diff(ids)) != [1, 1, 1]


def test_a_patient_number_never_reaches_the_transform():
    """The ids are derived from row position, not from `pt_num_list`. A
    transform that printed its index would otherwise print patient numbers."""
    pt = pd.Series([555001, 555002, 555003])
    ids = hook.INDEX_FLOOR + np.arange(len(pt)) * hook.INDEX_STRIDE

    assert not set(ids) & set(int(p) for p in pt)


# --------------------------------------------------------------------------
# failing closed


def test_a_failed_response_raises_rather_than_returning_the_frame(tmp_path, monkeypatch):
    """Never fall back to the untransformed frame. That would train a
    different model from the one requested and report success - strictly worse
    than failing, because nothing downstream could tell."""
    monkeypatch.setattr(hook, "SPOOL", str(tmp_path))

    def refuse(*a, **k):
        return {"ok": False, "error": {"message": "the transform raised"}}

    monkeypatch.setattr(hook, "_wait", lambda *a, **k: refuse())

    X = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    with pytest.raises(hook.TransformFailed):
        hook.run_transform(X, pd.Series([0, 1, 0]), pd.Series([1, 2, 3]),
                           blob_for(SRC), ml_code="x")


def test_a_missing_frame_in_the_response_is_refused():
    with pytest.raises(hook.TransformFailed) as e:
        hook._frame_from({"ok": True})
    assert "no frame" in str(e.value)


def test_no_pickup_is_reported_differently_from_a_slow_transform(tmp_path, monkeypatch):
    """"The backend is not running" and "your code is slow" need completely
    different fixes, and a build that sat waiting should say which it was."""
    monkeypatch.setattr(hook, "SPOOL", str(tmp_path))
    monkeypatch.setattr(hook, "WAIT_SECONDS", 2)
    monkeypatch.setattr(hook, "NO_PICKUP_SECONDS", 0)
    monkeypatch.setattr(hook, "POLL_SECONDS", 0.01)

    with pytest.raises(hook.TransformFailed) as e:
        hook._wait(str(tmp_path / "a.req.json"), str(tmp_path / "a.res.json"),
                   str(tmp_path / "a.claimed"))
    assert "picked up" in str(e.value) and "backend" in str(e.value)


def test_the_request_is_renamed_into_place(tmp_path, monkeypatch):
    """The host polls this directory, and `docker cp` on a half-written file
    reads a truncated request."""
    monkeypatch.setattr(hook, "SPOOL", str(tmp_path))
    seen = {}

    def capture(req, res, claimed):
        seen["contents"] = Path(req).read_text()
        seen["tmp_left"] = list(tmp_path.glob("*.tmp"))
        return {"ok": True, "frame_parquet_b64": None}

    monkeypatch.setattr(hook, "_wait", capture)

    frame = pd.DataFrame({"a": [1.0]}, index=pd.Index([hook.INDEX_FLOOR]))
    try:
        hook._exchange(frame, SRC, "abc", "code", "job", "build")
    except Exception:
        pass

    assert "frame_parquet_b64" in seen["contents"]
    assert seen["tmp_left"] == [], "a .tmp file was visible to the poller"


def test_warnings_are_stripped_of_quotes(tmp_path, monkeypatch):
    """They are written into the model blob, which is read back through a
    quote swap. One apostrophe in a warning corrupts the stored model."""
    monkeypatch.setattr(hook, "SPOOL", str(tmp_path))

    import io

    frame = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    ids = hook.INDEX_FLOOR + np.arange(3) * hook.INDEX_STRIDE
    out = frame.copy()
    out.index = pd.Index(ids)
    buf = io.BytesIO()
    out.to_parquet(buf, index=True)

    monkeypatch.setattr(hook, "_exchange", lambda *a, **k: {
        "ok": True,
        "frame_parquet_b64": base64.b64encode(buf.getvalue()).decode(),
        "report": {"changed": False, "warnings": ["it's unchanged, \"really\""]},
    })

    _, _, _, report = hook.run_transform(
        frame, pd.Series([0, 1, 0]), pd.Series([7, 8, 9]), blob_for(SRC))

    assert "warnings" not in report
    for w in report["transform_warnings"]:
        assert "'" not in w and '"' not in w


# --------------------------------------------------------------------------
# two writers, two keys


def build_script() -> str:
    return (Path(__file__).resolve().parents[1] / "docker-changes" / "i2b2_cdi"
            / "ML" / "apply_build_model_ml.py").read_text(encoding="utf-8")


def test_the_build_stamps_a_key_the_editor_does_not_write():
    """The apply guard is worthless if both sides write the same key.

    `transform_store.save()` writes `transform_sha256` on every save. If the
    build stamped that key too, the apply branch would compare the stored
    source against itself, always agree, and never refuse - which is what it
    did until a live apply proved it. A model built with transform A and
    applied with B would have scored every patient off a zero column and
    returned success.

    Asserted against the source because the build script cannot be imported
    here, and because the failure mode is somebody tidying two similar names
    into one.
    """
    from app.core import transform_store as ts

    source = build_script()

    assert "model_transform_sha256" in source
    assert ts.SHA == "transform_sha256"
    assert "model_transform_sha256" not in ts.KEYS, (
        "the editor must not write the key the build stamps, or the apply "
        "guard compares a value with itself")


def test_the_apply_branch_compares_the_two_different_keys():
    source = build_script()

    assert "trained_sha = concept_blob.get('model_transform_sha256')" in source
    assert "applied_sha = transform_report.get('transform_sha256')" in source


def test_the_apply_branch_raises_rather_than_filling_zeros():
    """Stock behaviour fills any absent trained feature with zeros and returns
    success. On a transform mismatch that is every engineered column."""
    source = build_script()
    guard = source[source.index("trained_sha ="):source.index("print(X.columns.to_list())")]

    assert "raise RuntimeError" in guard
    assert "TRANSFORM FAILED" in guard
