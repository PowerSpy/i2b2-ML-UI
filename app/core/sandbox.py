"""Run a researcher's transform in a container that cannot reach anything.

## The claim, stated precisely

**No egress, not no data access.** On the real path the transform sees every
patient row it transforms - that is what a feature transform is. What it cannot
do is send them anywhere: no network, no credentials, no host mounts, a
read-only root and no capabilities. Anyone approving a run should know which of
those two they are being asked to trust.

This module only implements the **dry run**, against fabricated data from
`synthetic.plan()`. The real path runs inside the ETL container via a hook and
does not exist yet.

## What is actually holding the line

`--network none`. That is the control. Everything else on the command line is
hygiene that turns a mistake into a clean error instead of a confusing one, and
the import allowlist in `guard.py` is ergonomics rather than security - it is
bypassable by anyone who tries, and it says so.

## The privilege this needs

Launching a container means talking to the docker socket, which is
root-equivalent on the host. That is an accepted risk while the app is bound to
loopback and unacceptable once it is not: before public exposure this belongs
behind a small helper with a fixed command allowlist and no shell, with the
public-facing process holding no docker access at all.
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid

from app.core import audit
from app.core.config import settings

IMAGE = getattr(settings, "sandbox_image", "i2b2-ml-sandbox:local")

# Long enough for a grid of pandas operations over a few thousand rows, short
# enough that a runaway is a nuisance rather than an outage. The sandbox has
# no way to ask for more.
DEFAULT_TIMEOUT_S = 60

# The response is JSON with a bounded preview; anything near this is a runner
# bug rather than a large result.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

# Startup, image pull checks and teardown, on top of the transform's own
# budget. Without it a container that never starts looks like a slow transform.
OVERHEAD_S = 20


class SandboxUnavailable(Exception):
    """The sandbox cannot run, with the command that would fix it."""


def docker_args(name: str, timeout_s: int) -> list[str]:
    """The `docker run` line, as a list, so it can be asserted on in a test.

    Deliberately not `--rm`: the container has to survive long enough to be
    inspected, because `OOMKilled` is the only way to tell an out-of-memory
    kill from a timeout kill - both exit 137, and reporting one as the other
    sends a researcher to fix the wrong thing.
    """
    return [
        "docker", "run", "--name", name, "--interactive",
        # The security boundary. Everything below this line is hygiene.
        "--network", "none",
        "--user", "65534:65534",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        # A writable scratch that cannot hold an executable, so a transform
        # that writes a file cannot then run it.
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        # --memory-swap equal to --memory disables swap for the container.
        # Without it an over-allocating transform thrashes instead of dying,
        # and then trips the wall clock - reported as a timeout, which is the
        # wrong diagnosis and the wrong fix.
        "--memory", "2g", "--memory-swap", "2g",
        "--cpus", "1.0",
        "--pids-limit", "128",
        # Nothing the transform prints belongs in the host's log driver.
        "--log-driver", "none",
        "--env", f"SANDBOX_TIMEOUT_S={timeout_s}",
        IMAGE,
    ]


def available() -> tuple[bool, str]:
    """Whether a dry run can be attempted, and why not if it cannot.

    Checked before queueing rather than after failing, and the message names
    the command to run - the same doctrine as `jobs.py`'s existing guards.
    """
    try:
        p = subprocess.run(["docker", "image", "inspect", IMAGE],
                           capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return False, "Docker is not installed on the host running this app."
    except subprocess.TimeoutExpired:
        return False, ("The Docker daemon did not respond within 20 seconds. "
                       "It is probably not running.")
    if p.returncode != 0:
        if "daemon" in (p.stderr or "").lower():
            return False, ("The Docker daemon is not reachable. Start Docker "
                           "and try again.")
        return False, (f"The sandbox image `{IMAGE}` is not built. Build it "
                       "with `./sandbox/build.sh probe` then "
                       "`./sandbox/build.sh` - it pins itself to the library "
                       "versions the real build uses, so it needs the i2b2 "
                       "stack running.")
    return True, ""


def run_transform(source: str, plan: dict, *,
                  timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
    """Run `source` against a frame materialised from `plan`.

    Dry run only. `plan` comes from `synthetic.plan()` and describes fabricated
    data, so the response may carry frame contents; nothing here is ever called
    with real values.
    """
    ok, why = available()
    if not ok:
        raise SandboxUnavailable(why)

    request = json.dumps({"mode": "dry-run", "source": source, "plan": plan})
    name = f"i2b2ml-sandbox-{uuid.uuid4().hex[:12]}"
    started = time.perf_counter()
    timed_out = False

    try:
        try:
            p = subprocess.run(
                docker_args(name, timeout_s),
                input=request, capture_output=True, text=True,
                timeout=timeout_s + OVERHEAD_S,
            )
            code, stdout, stderr = p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(name)
            code, stdout, stderr = 137, "", ""

        oom = _oom_killed(name)
        result = _interpret(code, stdout, stderr, timed_out=timed_out, oom=oom,
                            timeout_s=timeout_s)
    finally:
        _remove(name)

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    audit.event(
        "sandbox_dry_run",
        subject=name,
        status="ok" if result.get("ok") else "error",
        duration_ms=duration_ms,
        source_chars=len(source),
        n_rows=plan.get("n_rows"),
        n_columns=len(plan.get("columns") or []),
        outcome=(result.get("error") or {}).get("kind", "ok"),
    )
    result["duration_ms"] = duration_ms
    return result


# --------------------------------------------------------------------------


def _interpret(code: int, stdout: str, stderr: str, *, timed_out: bool,
               oom: bool, timeout_s: int) -> dict:
    """Turn an exit code into one sentence a researcher can act on.

    The ordering matters. An out-of-memory kill and a timeout kill are both
    exit 137, and a transform that allocates too much *also* runs long - so
    `OOMKilled` is consulted first and the wall clock only when it is false.
    """
    if oom:
        return _error("memory",
                      "The transform ran out of memory (2 GB) and was stopped. "
                      "Look for an operation that expands the frame - a merge "
                      "without a key, or a cross join.", stderr)
    if timed_out:
        return _error("timeout",
                      f"The transform did not finish within {timeout_s} "
                      "seconds and was stopped. A loop over rows is the usual "
                      "cause; a vectorised operation is usually thousands of "
                      "times faster.", stderr)

    if not stdout.strip():
        # The runner writes a response on every path it can reach, so an empty
        # stdout means it never got to run.
        return _error("crashed",
                      "The sandbox produced no response. The container exited "
                      f"with code {code} before the transform was read.", stderr)

    if len(stdout) > MAX_RESPONSE_BYTES:
        return _error("crashed",
                      "The sandbox response was too large to read.", stderr)

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as e:
        # run.py takes fd 1 away from user code precisely so this cannot be
        # caused by a `print`. If it happens anyway it is a runner bug, and
        # saying so beats pointing at the researcher's code.
        return _error("crashed",
                      f"The sandbox response was not valid JSON ({e}). This is "
                      "a bug in the sandbox runner, not in the transform.",
                      stderr)

    payload.setdefault("ok", False)
    payload["container_stderr"] = _tail(stderr)
    return payload


def _error(kind: str, message: str, stderr: str) -> dict:
    return {
        "ok": False,
        "error": {"kind": kind, "message": message, "detail": ""},
        "report": None, "preview": None, "input_preview": None, "logs": "",
        "container_stderr": _tail(stderr),
    }


def _tail(text: str, limit: int = 4000) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def _oom_killed(name: str) -> bool:
    try:
        p = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.OOMKilled}}", name],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and p.stdout.strip().lower() == "true"


def _kill(name: str) -> None:
    _quiet(["docker", "kill", name], timeout=20)


def _remove(name: str) -> None:
    """Always, on every path.

    `--rm` is not used so the container can be inspected, which means nothing
    else deletes it. A leaked container per dry run would be invisible until
    the disk filled.
    """
    _quiet(["docker", "rm", "-f", name], timeout=30)


def _quiet(args: list[str], *, timeout: float) -> None:
    try:
        subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        pass
