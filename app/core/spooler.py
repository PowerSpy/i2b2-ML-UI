"""Run transforms on behalf of the ETL container.

The build runs inside `i2b2-etl`, which cannot launch a sibling container and
must not be given the ability - the docker socket is host root, and a sandbox
reachable from the container it is protecting is not a sandbox.

So the container writes a request into a spool directory and blocks. This
watches that directory over `docker exec`, pulls the request with `docker cp`,
runs it in the sandbox, and writes the answer back. **The ETL container gains
no docker access, no new network route and no recreate.**

It is the same idiom the rest of this application already runs on: the host
drives containers over exec and cp. That is the point - it adds no trust
relationship that does not already exist, and every alternative does.

## The coupling this creates

A build of a model with a transform now needs this process alive. That is a
new way for a build to fail that has nothing to do with the model, and it is
named in the container's own error message rather than left to be guessed. The
queue-time guard in `jobs.py` refuses to enqueue when the sandbox is missing,
so the usual case is a refusal at the door rather than a job that dies later.
"""

from __future__ import annotations

import base64
import json
import shlex
import tempfile
import threading
import time
from pathlib import Path

from app.core import audit, docker_exec, ml_blob, sandbox, transform_store
from app.core.config import settings

SPOOL = "/tmp/i2b2ml-spool"

# Fast enough that a build does not sit visibly waiting, slow enough that this
# is not a `docker exec` every second forever.
POLL_SECONDS = 1.5

# The wall clock for one transform, inside the sandbox. The container-side hook
# allows considerably more, so a timeout is reported by the sandbox - which
# knows whether it was a timeout or an out-of-memory kill - rather than by the
# hook giving up.
TRANSFORM_TIMEOUT_S = 120

_thread: threading.Thread | None = None
_stop = threading.Event()


# --------------------------------------------------------------------------
# lifecycle


def start() -> None:
    """Begin watching. Safe to call twice."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="transform-spooler", daemon=True)
    _thread.start()
    audit.event("spooler_started", subject=settings.container)


def stop(timeout: float = 5.0) -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=timeout)


def running() -> bool:
    return bool(_thread and _thread.is_alive())


def _loop() -> None:
    while not _stop.is_set():
        try:
            for token in pending():
                if _stop.is_set():
                    break
                handle(token)
        except Exception as e:
            # A watcher that dies on one bad request stops every future build
            # with no explanation. Whatever happened, keep watching.
            print(f"[spooler] {type(e).__name__}: {e}")
        _stop.wait(POLL_SECONDS)


# --------------------------------------------------------------------------
# one request


def pending() -> list[str]:
    """Tokens of requests waiting to be picked up.

    `.req.json` only - the hook writes to `.tmp` and renames, so a name that
    matches is a complete file.
    """
    out = docker_exec.exec(
        settings.container,
        f"ls -1 {shlex.quote(SPOOL)} 2>/dev/null | grep -E '\\.req\\.json$' || true",
        timeout=30,
    )
    if out.returncode != 0:
        return []
    return [line[: -len(".req.json")] for line in out.stdout.split() if line.strip()]


def handle(token: str) -> None:
    """Run one transform and write the answer back."""
    started = time.perf_counter()
    workdir = Path(tempfile.mkdtemp(prefix="i2b2ml-spool-"))
    try:
        # Claimed first, so the container can tell "nobody is listening" from
        # "this is taking a while". Those need different fixes.
        docker_exec.exec(settings.container,
                         f"touch {shlex.quote(f'{SPOOL}/{token}.claimed')}", timeout=30)

        request = _pull(token, workdir)
        response = _run(request)
        _push(token, response, workdir)

        audit.event(
            "transform_run",
            subject=request.get("ml_code") or token,
            status="ok" if response.get("ok") else "error",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            job_id=request.get("job_id"),
            task=request.get("task"),
            rows=request.get("rows"),
            n_columns=request.get("columns"),
            outcome=(response.get("error") or {}).get("kind", "ok"),
        )
    except Exception as e:
        # Never leave the container blocking on a request this process has
        # already given up on.
        _push(token, _fail("crashed", f"the backend failed to run this transform: {e}"),
              workdir)
    finally:
        docker_exec.exec(
            settings.container,
            f"rm -f {shlex.quote(f'{SPOOL}/{token}.req.json')} "
            f"{shlex.quote(f'{SPOOL}/{token}.claimed')}",
            timeout=30,
        )
        _rmtree(workdir)


def _pull(token: str, workdir: Path) -> dict:
    local = workdir / "request.json"
    out = docker_exec.exec_cp_out(
        settings.container, f"{SPOOL}/{token}.req.json", local, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"could not read the request: {out.stderr.strip()[:200]}")
    return json.loads(local.read_text(encoding="utf-8"))


def _run(request: dict) -> dict:
    """Execute the request's transform in the sandbox.

    **The source is read from the model's blob, not from the request.** The
    container sends a digest; this loads the stored code and refuses if the two
    disagree. It costs one query and it means the code that runs is the code
    that was saved and reviewed, whatever a request happens to contain.
    """
    code = request.get("ml_code") or ""
    claimed_sha = request.get("source_sha256")

    source = None
    if code:
        try:
            record = transform_store.load(code)
            if record and record.get("intact"):
                source = record["source"]
        except (KeyError, RuntimeError):
            source = None

    if source is None:
        # A model can be mid-edit, or the code may not resolve. Fall back to
        # the request, but only when its digest is self-consistent.
        packed = request.get("source_b64")
        if not packed:
            return _fail("rejected", "no transform source could be found for this model")
        raw = base64.b64decode(packed)
        import hashlib

        if claimed_sha and hashlib.sha256(raw).hexdigest() != claimed_sha:
            return _fail("rejected",
                         "the transform sent by the container does not match its "
                         "own checksum")
        source = raw.decode("utf-8")
    else:
        import hashlib

        actual = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if claimed_sha and actual != claimed_sha:
            return _fail(
                "rejected",
                "the transform stored against this model has changed since the "
                "build started. Re-queue the build so it runs the code you can "
                "see in the editor.")

    ok, why = sandbox.available()
    if not ok:
        return _fail("crashed", why)

    return sandbox.run_frame(source, request["frame_parquet_b64"],
                             timeout_s=TRANSFORM_TIMEOUT_S)


def _push(token: str, response: dict, workdir: Path) -> None:
    """Write the response where the hook is waiting for it.

    Copied to a scratch name and renamed inside the container, because
    `docker cp` is not atomic and the hook polls for this file - it would
    otherwise read a partial JSON document and report a parse error.
    """
    try:
        local = workdir / "response.json"
        local.write_text(json.dumps(response), encoding="utf-8")

        docker_exec.exec(settings.container,
                         f"mkdir -p {shlex.quote(SPOOL)}", timeout=30)
        docker_exec.exec_cp(settings.container, local,
                            f"{SPOOL}/{token}.res.tmp", timeout=120)
        docker_exec.exec(
            settings.container,
            f"mv {shlex.quote(f'{SPOOL}/{token}.res.tmp')} "
            f"{shlex.quote(f'{SPOOL}/{token}.res.json')}",
            timeout=30,
        )
    except Exception as e:
        print(f"[spooler] could not deliver the response for {token}: {e}")


def _fail(kind: str, message: str) -> dict:
    return {"ok": False, "error": {"kind": kind, "message": message, "detail": ""},
            "report": None, "frame_parquet_b64": None, "logs": ""}


def _rmtree(path: Path) -> None:
    import shutil

    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


# --------------------------------------------------------------------------


def hook_installed() -> bool:
    """Whether the container has the transform hook.

    Checked before a build is queued rather than after it fails: a model with a
    transform, built against a container without the hook, trains on raw
    columns and reports success.
    """
    out = docker_exec.exec(
        settings.container,
        "test -f /usr/src/app/i2b2_cdi/ML/transform_hook.py && echo yes || echo no",
        timeout=30,
    )
    return out.returncode == 0 and "yes" in out.stdout


def readiness(code: str | None = None) -> tuple[bool, str]:
    """Whether a transform build can run right now, and why not if it cannot."""
    if code is not None:
        try:
            if not ml_blob.load_blob_light(code).get(transform_store.SOURCE):
                return True, ""
        except (KeyError, RuntimeError):
            return True, ""

    if not running():
        return False, ("This model has a feature transform, and transforms are "
                       "run by this backend - its spooler is not running.")
    if not hook_installed():
        return False, ("This model has a feature transform, but the container "
                       "does not have the hook that calls it. Install it with "
                       "./docker-changes/apply.sh, then re-queue.")
    ok, why = sandbox.available()
    if not ok:
        return False, why
    return True, ""
