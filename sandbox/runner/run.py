"""Sandbox entrypoint: a JSON request on stdin, a JSON response on stdout.

Nothing here is trusted and nothing here has anywhere to send data: the
container runs with `--network none`, no credentials, no host mounts and a
read-only root. See `sandbox/README.md` for what that does and does not buy.

## The one detail that prevents silent corruption

**fd 1 is taken away from user code before any of it runs.** A single
`print(df)` in a transform would otherwise land in the middle of the response
envelope, and the host would report a JSON parse error naming a character
offset - with no hint that a researcher's debug print caused it. The real
stdout is duped to a private descriptor, fd 1 is pointed at stderr, and the
response is written to the private one at the very end.

Both layers are needed. The Python-level redirect captures `print` so it can be
returned as logs; the fd-level one catches anything writing to the descriptor
directly, which `print` does not but a C extension might.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import random
import sys
import time
import traceback

MAX_LOG_CHARS = 20000
USER_FILENAME = "transform.py"


def _timeout_s() -> int:
    """The budget, from the environment the host sets on `docker run`."""
    try:
        return int(os.environ.get("SANDBOX_TIMEOUT_S", "0"))
    except ValueError:
        return 0


def main() -> int:
    # Before anything else, including imports that might print a warning.
    private_stdout = os.dup(1)
    os.dup2(2, 1)
    response_out = os.fdopen(private_stdout, "w", encoding="utf-8")

    started = time.time()
    try:
        request = json.load(sys.stdin)
    except Exception as e:
        return _emit(response_out, _fail("protocol", f"unreadable request: {e}"))

    try:
        result = _handle(request)
    except _Refusal as e:
        result = _fail(e.kind, str(e), logs=e.logs)
    except Exception:
        result = _fail("internal", "the sandbox runner failed",
                       detail=traceback.format_exc())

    result["duration_s"] = round(time.time() - started, 3)
    return _emit(response_out, result)


class _Refusal(Exception):
    def __init__(self, kind: str, message: str, logs: str = ""):
        super().__init__(message)
        self.kind = kind
        self.logs = logs


def _handle(request: dict) -> dict:
    mode = request.get("mode")
    if mode != "dry-run":
        # The real-data path runs inside the ETL container via the hook, not
        # here. Refusing by name beats accepting a mode this runner cannot
        # honour and returning something that looks like a result.
        raise _Refusal("protocol",
                       f"unsupported mode {mode!r}; this runner only does dry-run")

    source = request.get("source") or ""
    plan = request.get("plan") or {}

    # Imported inside the handler so a missing dependency is reported through
    # the envelope rather than killing the process before it can answer.
    from . import guard, materialize, validate

    try:
        guard.check(source)
    except guard.GuardError as e:
        raise _Refusal("rejected", str(e))

    seed = int(plan.get("seed") or 0)
    random.seed(seed)

    frame = materialize.frame(plan)
    original = frame.copy(deep=True)

    fn, logs = _load(source)
    # The host allows this plus container startup; firing here first means
    # a timeout is reported as one rather than inferred from an exit code.
    out, more_logs = _call(fn, frame, _timeout_s())
    logs = _clip(logs + more_logs)

    try:
        report = validate.check(out, original)
    except validate.ValidationError as e:
        raise _Refusal("invalid_output", str(e), logs=logs)

    return {
        "ok": True,
        "error": None,
        "report": report,
        # Safe only because the data is fabricated. The real run returns
        # counts and nothing else - see `app/core/sandbox.py`.
        "input_preview": validate.preview(original),
        "preview": validate.preview(out),
        "logs": logs,
    }


def _load(source: str):
    """Execute the module body and hand back `transform`.

    The body runs in its own namespace with `__name__` set to something that is
    not `__main__`, so a `if __name__ == "__main__":` block pasted in from a
    script does not fire.
    """
    namespace = {"__name__": "transform", "__file__": USER_FILENAME,
                 "__builtins__": __builtins__}
    buffer = io.StringIO()
    try:
        code = compile(source, USER_FILENAME, "exec")
        with contextlib.redirect_stdout(buffer):
            exec(code, namespace)
    except Exception:
        raise _Refusal("raised", _user_traceback(), logs=buffer.getvalue())

    fn = namespace.get("transform")
    if not callable(fn):
        raise _Refusal("rejected",
                       "`transform` is defined but is not a function",
                       logs=buffer.getvalue())
    return fn, buffer.getvalue()


@contextlib.contextmanager
def _deadline(seconds: int):
    """Stop the transform from inside, a little before the host gives up.

    Without this the only limit is the host's `subprocess` timeout, which has
    to allow for container startup on top of the budget - so an 8-second
    timeout took 30 seconds to report. Worse, the host's path has to kill the
    container and then work out from `OOMKilled` what happened; stopping here
    means the answer is simply known.

    `SIGALRM` is POSIX-only. The sandbox is Linux, but the runner is also
    driven directly in tests on Windows, where the host timeout remains the
    only backstop.
    """
    import signal

    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return

    def fire(signum, frame):
        raise TimeoutError(f"exceeded {seconds} seconds")

    previous = signal.signal(signal.SIGALRM, fire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _call(fn, frame, timeout_s: int = 0):
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer), _deadline(timeout_s):
            out = fn(frame)
    except TimeoutError as e:
        raise _Refusal("timeout",
                       f"The transform did not finish in time ({e}) and was "
                       "stopped. A loop over rows is the usual cause; a "
                       "vectorised operation is usually thousands of times "
                       "faster.",
                       logs=buffer.getvalue())
    except MemoryError:
        # Usually the container kills the process before this is reachable;
        # when it is reachable the message beats a bare traceback.
        raise _Refusal("memory",
                       "the transform ran out of memory. Check for an "
                       "operation that expands the frame - a merge without a "
                       "key, or a cross join.",
                       logs=buffer.getvalue())
    except RecursionError:
        raise _Refusal("raised", "the transform recursed too deeply",
                       logs=buffer.getvalue())
    except Exception:
        raise _Refusal("raised", _user_traceback(), logs=buffer.getvalue())
    return out, buffer.getvalue()


def _user_traceback() -> str:
    """The researcher's frames only.

    Runner frames in a traceback send people to read this file looking for
    their bug. Everything below the first `transform.py` frame is theirs.
    """
    exc_type, exc, tb = sys.exc_info()
    frames = traceback.extract_tb(tb)
    mine = [f for f in frames if f.filename == USER_FILENAME]
    lines = traceback.format_list(mine) if mine else []
    lines += traceback.format_exception_only(exc_type, exc)
    return "".join(lines).strip()


def _clip(text: str) -> str:
    if len(text) <= MAX_LOG_CHARS:
        return text
    dropped = len(text) - MAX_LOG_CHARS
    return text[:MAX_LOG_CHARS] + f"\n... {dropped} more characters suppressed"


def _fail(kind: str, message: str, detail: str = "", logs: str = "") -> dict:
    return {
        "ok": False,
        "error": {"kind": kind, "message": message, "detail": detail},
        "report": None,
        "preview": None,
        "input_preview": None,
        "logs": logs,
    }


def _emit(out, payload: dict) -> int:
    # `allow_nan=False` so a NaN that slipped past `validate._json_safe`
    # fails here, where it is attributable, rather than producing a document
    # only Python can parse.
    try:
        body = json.dumps(payload, allow_nan=False)
    except (ValueError, TypeError) as e:
        body = json.dumps(_fail("internal", f"unserialisable response: {e}"))
    out.write(body)
    out.write("\n")
    out.flush()
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
