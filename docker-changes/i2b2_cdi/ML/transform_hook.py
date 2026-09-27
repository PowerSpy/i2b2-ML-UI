"""Run a model's feature transform, from inside the ETL container.

The researcher's code does **not** run here. This container holds the
warehouse credentials; running arbitrary Python in it would make every other
control decorative. Instead the frame is written to a spool directory, a
process on the host picks it up, runs it in a container with `--network none`
and no credentials, and writes the answer back.

## Why a spool and not a call

This container cannot launch a sibling container, and the two alternatives are
both worse than the problem:

- Mounting `/var/run/docker.sock` in here is host root. The sandbox would be
  protecting nothing.
- `unshare` in-process needs `CAP_SYS_ADMIN`, and leaves the researcher's code
  one file permission away from the database password.

Writing a file and waiting adds **no new trust relationship**: the host already
drives this container over `docker exec` and `docker cp`, which is how the
whole application works. Every alternative adds one.

## Fail closed

If the transform cannot run, the build fails. It never falls back to the
untransformed frame - that would train a different model from the one the
researcher asked for and report success, which is the worst outcome available
here.
"""

import base64
import hashlib
import io
import json
import os
import time
import uuid

import numpy as np
import pandas as pd

SPOOL = os.environ.get("I2B2ML_SPOOL", "/tmp/i2b2ml-spool")

# How long to wait for the host. Generous, because it covers the host noticing
# the request, starting a container and the transform itself - but finite,
# because a build that hangs forever is worse than one that fails.
WAIT_SECONDS = int(os.environ.get("I2B2ML_TRANSFORM_WAIT", "300"))
POLL_SECONDS = 0.5

# The host is expected to answer within a few seconds of the request appearing.
# Nothing at all in this long means the backend is not running, which is worth
# a different sentence from "your transform was slow".
NO_PICKUP_SECONDS = 45

# Matches `app/core/synthetic.py`. Row ids are handed to the transform above
# this floor so that `reset_index(drop=True)` cannot be mistaken for a filter -
# 0..k-1 is a valid subset of 0..n-1, and accepting it would renumber every row
# and attribute every prediction to the wrong patient.
INDEX_FLOOR = 1_000_000
INDEX_STRIDE = 7

BLOB_SOURCE = "transform_b64"
BLOB_SHA = "transform_sha256"


class TransformFailed(Exception):
    """The build must stop. The message is shown on the job row."""


def has_transform(blob):
    return bool((blob or {}).get(BLOB_SOURCE))


def read_source(blob):
    """The stored source, verified against its recorded digest.

    The digest is checked here rather than trusted because the blob is repaired
    by a blind quote swap on its way out of the database. A transform that
    decoded but changed is not the code anyone approved.
    """
    packed = (blob or {}).get(BLOB_SOURCE)
    if not packed:
        return None, None

    try:
        raw = base64.b64decode(packed, validate=True)
        source = raw.decode("utf-8")
    except Exception as e:
        raise TransformFailed(
            "the stored transform could not be decoded (%s). Re-save it from "
            "the editor." % e
        )

    actual = hashlib.sha256(raw).hexdigest()
    recorded = blob.get(BLOB_SHA)
    if recorded and actual != recorded:
        raise TransformFailed(
            "the stored transform does not match its checksum - it is not the "
            "code that was saved. Re-save it from the editor before building."
        )
    return source, actual


def run_transform(X, y, pt_num_list, blob, ml_code="", job_id="", task="build"):
    """Apply this model's transform to `X`, keeping `y` and `pt_num_list` aligned.

    Returns `(X, y, pt_num_list, report)`. When the model has no transform,
    everything comes back untouched and `report` says so.

    The alignment is the dangerous part. If the transform drops rows, the
    labels and the patient numbers must lose exactly the same rows, in the same
    order - `load_pred_facts` pairs predictions to patients **positionally**.
    """
    if not has_transform(blob):
        return X, y, pt_num_list, {"transform_applied": False}

    source, sha = read_source(blob)
    started = time.time()

    # Opaque, non-contiguous row ids. The transform never sees a patient
    # number, and a renumbering cannot pass as a filter.
    n = len(X)
    ids = INDEX_FLOOR + np.arange(n) * INDEX_STRIDE
    position = {int(i): p for p, i in enumerate(ids)}

    sent = X.copy()
    sent.index = pd.Index(ids)

    response = _exchange(sent, source, sha, ml_code, job_id, task)

    out = _frame_from(response)

    # Re-validated here even though the sandbox already did it. The sandbox is
    # the untrusted side of this exchange - it runs the researcher's code - so
    # its report of its own output is evidence, not proof. This is the same
    # module the sandbox uses, installed by apply.sh, so the two cannot drift
    # into disagreeing about what a valid frame is.
    try:
        from i2b2_cdi.ML import transform_validate
        transform_validate.check(out, sent)
    except ImportError:
        pass
    except Exception as e:
        raise TransformFailed(str(e))

    positions = _positions(out, position, n)

    X_out = out.reset_index(drop=True)
    y_out = y.iloc[positions].reset_index(drop=True)
    pt_out = pd.Series(pt_num_list).iloc[positions].reset_index(drop=True)

    report = dict(response.get("report") or {})
    report.update({
        "transform_applied": True,
        "transform_sha256": sha,
        "transform_seconds": round(time.time() - started, 2),
        "transform_rows_dropped": int(n - len(out)),
    })
    if report.get("warnings"):
        # The blob is read back through a quote swap, so a stray apostrophe in
        # a warning would corrupt the whole model. They are already plain
        # sentences; this makes it impossible for one to not be.
        report["transform_warnings"] = [
            str(w).replace("'", "").replace('"', "") for w in report["warnings"]
        ]
    report.pop("warnings", None)
    return X_out, y_out, pt_out, report


def _positions(out, position, n):
    """Row positions of the returned frame, or a refusal naming the reason.

    The validator in the sandbox already checked this, but it is checked again
    here because this is the side that would mispair patients, and because a
    sandbox that returned something unexpected must not be trusted about its
    own output.
    """
    missing = [int(i) for i in out.index if int(i) not in position]
    if missing:
        raise TransformFailed(
            "the transform returned %d row ids that were not handed to it "
            "(for example %s). Rows may be filtered out, but new rows have no "
            "patient behind them." % (len(missing), missing[:3])
        )
    positions = [position[int(i)] for i in out.index]
    if len(set(positions)) != len(positions):
        raise TransformFailed(
            "the transform returned the same row more than once, so one "
            "patient would receive two predictions."
        )
    if not positions:
        raise TransformFailed(
            "the transform returned no rows; %d went in." % n
        )
    return positions


def _frame_from(response):
    packed = response.get("frame_parquet_b64")
    if not packed:
        raise TransformFailed("the sandbox returned no frame")
    try:
        return pd.read_parquet(io.BytesIO(base64.b64decode(packed)))
    except Exception as e:
        raise TransformFailed("the transformed frame could not be read: %s" % e)


# --------------------------------------------------------------------------
# the spool


def _exchange(frame, source, sha, ml_code, job_id, task):
    """Write a request, wait for the host, return the parsed response."""
    os.makedirs(SPOOL, exist_ok=True)
    token = "%s-%s" % (job_id or "job", uuid.uuid4().hex[:12])
    req = os.path.join(SPOOL, token + ".req.json")
    res = os.path.join(SPOOL, token + ".res.json")
    claimed = os.path.join(SPOOL, token + ".claimed")

    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=True)

    payload = {
        "id": token, "ml_code": ml_code, "job_id": str(job_id), "task": task,
        "source_sha256": sha,
        "source_b64": base64.b64encode(source.encode("utf-8")).decode("ascii"),
        "frame_parquet_b64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "rows": int(len(frame)), "columns": int(frame.shape[1]),
    }

    # Written elsewhere and renamed, because the host polls this directory and
    # `docker cp` on a half-written file would read a truncated request.
    tmp = req + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, req)

    try:
        return _wait(req, res, claimed)
    finally:
        for path in (req, res, claimed, tmp):
            try:
                os.remove(path)
            except OSError:
                pass


def _wait(req, res, claimed):
    deadline = time.time() + WAIT_SECONDS
    picked_up = False

    while time.time() < deadline:
        if os.path.exists(res):
            with open(res) as fh:
                response = json.load(fh)
            if not response.get("ok"):
                error = response.get("error") or {}
                raise TransformFailed(
                    error.get("message") or "the transform failed"
                )
            return response

        if not picked_up and os.path.exists(claimed):
            picked_up = True

        # Distinguishing "nobody is listening" from "this is taking a while"
        # matters: they need completely different fixes, and a build that sat
        # for five minutes because the backend was down should say so.
        if not picked_up and time.time() > deadline - WAIT_SECONDS + NO_PICKUP_SECONDS:
            raise TransformFailed(
                "no process picked up the transform request within %d seconds. "
                "This model has a feature transform, and transforms are run by "
                "the i2b2 ML UI backend - it has to be running for this build "
                "to work." % NO_PICKUP_SECONDS
            )
        time.sleep(POLL_SECONDS)

    raise TransformFailed(
        "the transform did not come back within %d seconds." % WAIT_SECONDS
    )
