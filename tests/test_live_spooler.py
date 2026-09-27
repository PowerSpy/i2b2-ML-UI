"""The spool: the ETL container's only route to the sandbox.

The container writes a request and blocks; this process answers it. These
drive that exchange from the host side by planting a request where the hook
would have put one, which covers the spooler, the wire protocol and the
sandbox's real-data mode without needing a full model build.

Needs the stack and the sandbox image. Slow by construction - each case starts
a container.
"""

import base64
import hashlib
import io
import json
import shlex
import tempfile
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
pd = pytest.importorskip("pandas")

SRC = "def transform(df):\n    return df.assign(doubled=df['a'] * 2)\n"

# Matches the hook's scheme: opaque ids above a floor, non-contiguous, so a
# `reset_index(drop=True)` cannot pass as a filter.
IDS = [1000000, 1000007, 1000014, 1000021]


@pytest.fixture(scope="module")
def box():
    from app.core import sandbox

    ok, why = sandbox.available()
    if not ok:
        pytest.skip(f"sandbox unavailable: {why}")
    return sandbox


@pytest.fixture
def spooling(box):
    """The spooler running, and the spool directory clean either side."""
    from app.core import docker_exec, spooler
    from app.core.config import settings

    def wipe():
        docker_exec.exec(settings.container,
                         f"rm -rf {shlex.quote(spooler.SPOOL)}", timeout=60)

    wipe()
    spooler.start()
    try:
        yield spooler
    finally:
        spooler.stop()
        wipe()


def plant(token, source, frame, *, sha=None, ml_code=""):
    """Write a request into the container exactly as the hook would."""
    from app.core import docker_exec, spooler
    from app.core.config import settings

    buf = io.BytesIO()
    frame.to_parquet(buf, index=True)
    raw = source.encode("utf-8")

    payload = {
        "id": token, "ml_code": ml_code, "job_id": "livetest", "task": "build",
        "source_sha256": sha or hashlib.sha256(raw).hexdigest(),
        "source_b64": base64.b64encode(raw).decode("ascii"),
        "frame_parquet_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
        "rows": int(len(frame)), "columns": int(frame.shape[1]),
    }

    local = Path(tempfile.mkdtemp()) / "req.json"
    local.write_text(json.dumps(payload), encoding="utf-8")
    docker_exec.exec(settings.container,
                     f"mkdir -p {shlex.quote(spooler.SPOOL)}", timeout=60)
    docker_exec.exec_cp(settings.container, local,
                        f"{spooler.SPOOL}/{token}.req.json", timeout=120)


def await_response(token, timeout=300):
    from app.core import docker_exec, spooler
    from app.core.config import settings

    deadline = time.time() + timeout
    out = Path(tempfile.mkdtemp()) / "res.json"
    res = f"{spooler.SPOOL}/{token}.res.json"

    while time.time() < deadline:
        got = docker_exec.exec(
            settings.container,
            f"test -f {shlex.quote(res)} && echo yes || echo no", timeout=60)
        if "yes" in got.stdout:
            docker_exec.exec_cp_out(settings.container, res, out, timeout=120)
            return json.loads(out.read_text(encoding="utf-8"))
        time.sleep(2)
    pytest.fail(f"no response within {timeout}s - the spooler did not answer")


def frame(n=4):
    return pd.DataFrame({"a": [float(i + 1) for i in range(n)]},
                        index=pd.Index(IDS[:n]))


def token():
    return f"livetest-{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------


def test_the_spooler_answers_a_request_from_the_container(spooling):
    """The whole exchange: a request appears inside the ETL container, this
    process notices it, runs the sandbox, and writes the answer back."""
    t = token()
    plant(t, SRC, frame())
    response = await_response(t)

    assert response["ok"], response.get("error")
    assert response["report"]["columns_added"] == ["doubled"]

    out = pd.read_parquet(io.BytesIO(base64.b64decode(response["frame_parquet_b64"])))
    assert list(out.columns) == ["a", "doubled"]
    assert out["doubled"].tolist() == [2.0, 4.0, 6.0, 8.0]


def test_the_index_survives_the_round_trip_exactly(spooling):
    """Patient numbers are re-attached by this index after the frame comes
    back. An id that changed in transit would attribute a prediction to the
    wrong patient, and parquet is used precisely so it cannot."""
    t = token()
    plant(t, SRC, frame())
    response = await_response(t)

    out = pd.read_parquet(io.BytesIO(base64.b64decode(response["frame_parquet_b64"])))
    assert list(out.index) == IDS
    assert out.index.dtype == frame().index.dtype


def test_dtypes_survive_the_round_trip(spooling):
    """The whole reason the handover is parquet rather than CSV or JSON. A
    column that leaves as float64 and arrives as object changes what the
    scaler does, silently."""
    t = token()
    sent = frame()
    plant(t, "def transform(df):\n    return df\n", sent)
    response = await_response(t)

    out = pd.read_parquet(io.BytesIO(base64.b64decode(response["frame_parquet_b64"])))
    assert out.dtypes.to_dict() == sent.dtypes.to_dict()


def test_the_real_run_returns_counts_and_never_a_row(spooling):
    """The invariant separating a debugging aid from an export. The dry run
    returns rows because its rows are fabricated; this path sees real patient
    values and publishes only aggregates."""
    t = token()
    plant(t, SRC, frame())
    response = await_response(t)

    assert response["ok"]
    assert response.get("preview") is None
    assert response.get("input_preview") is None
    assert set(response["report"]) <= {
        "changed", "rows_in", "rows_out", "columns_in", "columns_out",
        "columns_added", "columns_removed", "rows_dropped", "warnings"}


def test_a_failing_transform_comes_back_as_a_refusal_not_a_hang(spooling):
    """The container blocks on this file. Whatever goes wrong, something must
    be written, or the build waits out its whole timeout and then reports the
    wrong cause."""
    t = token()
    plant(t, "def transform(df):\n    raise ValueError('nope')\n", frame())
    response = await_response(t)

    assert response["ok"] is False
    assert response["error"]["kind"] == "raised"
    assert "nope" in response["error"]["message"]


def test_a_request_whose_checksum_does_not_match_is_refused(spooling):
    """The spooler prefers the source stored against the model, and falls back
    to the one in the request only when its digest is self-consistent."""
    t = token()
    plant(t, SRC, frame(), sha="0" * 64)
    response = await_response(t)

    assert response["ok"] is False
    assert "checksum" in response["error"]["message"]


def test_the_request_is_cleaned_up_afterwards(spooling):
    """A spool that fills with handled requests would re-run them forever."""
    from app.core import docker_exec, spooler
    from app.core.config import settings

    t = token()
    plant(t, SRC, frame())
    await_response(t)

    left = docker_exec.exec(
        settings.container,
        f"ls -1 {shlex.quote(spooler.SPOOL)} 2>/dev/null || true", timeout=60)
    assert f"{t}.req.json" not in left.stdout


def test_the_request_is_claimed_so_no_pickup_is_distinguishable(spooling):
    """The hook tells "nobody is listening" from "this is taking a while" by
    watching for the claim. They need completely different fixes."""
    from app.core import docker_exec, spooler
    from app.core.config import settings

    t = token()
    plant(t, "def transform(df):\n    return df\n", frame())

    seen = False
    deadline = time.time() + 120
    while time.time() < deadline and not seen:
        out = docker_exec.exec(
            settings.container,
            f"ls -1 {shlex.quote(spooler.SPOOL)} 2>/dev/null || true", timeout=60)
        seen = f"{t}.claimed" in out.stdout or f"{t}.res.json" in out.stdout
        if not seen:
            time.sleep(1)

    assert seen, "the spooler never claimed the request"
    await_response(t)


# --------------------------------------------------------------------------
# refusing at the door


def test_readiness_passes_for_a_model_with_no_transform(spooling):
    """Every model that does not use this feature must be unaffected by all of
    it - including by the spooler being down."""
    from app.core import ml_blob, spooler

    codes = [c["code"] for c in ml_blob.list_ml_concepts("/ML")]
    if not codes:
        pytest.skip("no models in this warehouse")

    ok, why = spooler.readiness(codes[0])
    assert ok, why


def test_the_hook_is_installed_in_the_container(spooling):
    """A model with a transform built against a container without the hook
    does not fail - it trains on the raw columns and reports success. The
    queue-time guard refuses on this, so the check itself has to be right."""
    from app.core import spooler

    assert spooler.hook_installed() is True
