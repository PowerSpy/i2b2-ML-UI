import subprocess
import time

from pydantic import BaseModel
from pathlib import Path

from app.core import audit


class Exec_Output(BaseModel):
    returncode: int
    stdout: str
    stderr: str


def _record(kind: str, container: str, command: str, started: float,
            out: Exec_Output) -> Exec_Output:
    """Audit one container call.

    This is the highest-value hook in the app. Everything that reaches i2b2 —
    every load, every delete, every count, every psql query, every ML registry
    probe, every watcher start — goes through this module, so these rows are
    the ground truth for what actually ran against the data. They are also what
    makes a shell-injection class of bug visible instead of silent.

    The command text is recorded in full (bounded by audit's own limit). It is
    a command, not a result: `audit._scrub` keeps rows and blobs out, and no
    caller passes patient data as an argument.
    """
    audit.event(
        kind,
        subject=container,
        status="ok" if out.returncode == 0 else "error",
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
        command=command,
        returncode=out.returncode,
        stdout_bytes=len(out.stdout),
        stderr_bytes=len(out.stderr),
    )
    return out


def exec(container: str, *cmds: str, timeout: float = 300.0) -> Exec_Output:
    script = " && ".join(cmds)
    started = time.perf_counter()
    p = subprocess.run(
        ["docker", "exec", container, "bash", "-lc", script],
        capture_output=True, text=True, timeout=timeout,
    )

    return _record("container_exec", container, script, started,
                   Exec_Output(returncode=p.returncode, stdout=p.stdout,
                               stderr=p.stderr))


def exec_detached(container: str, *cmds: str, timeout: float = 30.0) -> Exec_Output:
    script = " && ".join(cmds)
    started = time.perf_counter()
    p = subprocess.run(
        ["docker", "exec", "-d", container, "bash", "-lc", script],
        capture_output=True, text=True, timeout=timeout,
    )

    return _record("container_exec_detached", container, script, started,
                   Exec_Output(returncode=p.returncode, stdout=p.stdout,
                               stderr=p.stderr))


def exec_cp_out(container: str, container_path: str, host_path: Path,
                timeout: float = 300.0) -> Exec_Output:
    """Copy a path out of the container onto the host.

    The other direction from `exec_cp`, and needed by the transform spooler:
    the ETL container writes a request that this host has to read. Same
    reasoning about `container_path` being a plain string - a POSIX path
    through `pathlib` on Windows comes out backslash-separated and points at
    nothing.
    """
    started = time.perf_counter()
    p = subprocess.run(
        ["docker", "cp", f"{container}:{container_path}", str(host_path)],
        capture_output=True, text=True, timeout=timeout,
    )

    return _record("container_cp_out", container,
                   f"docker cp {container_path} -> {host_path}", started,
                   Exec_Output(returncode=p.returncode, stdout=p.stdout,
                               stderr=p.stderr))


def exec_cp(container: str, host_path: Path, container_path: str, timeout: float = 300.0) -> Exec_Output:
    """Copy a host path into the container.

    `container_path` is a plain string, deliberately not a Path: paths inside
    the container are POSIX, and on Windows `Path("/tmp/x")` is a WindowsPath
    that renders as `\\tmp\\x`. Interpolated into a command that runs in the
    container, that silently points at somewhere that does not exist.
    """
    started = time.perf_counter()
    p = subprocess.run(
        ["docker", "cp", str(host_path), f"{container}:{container_path}"],
        capture_output=True, text=True, timeout=timeout,
    )

    return _record("container_cp", container,
                   f"docker cp {host_path} -> {container_path}", started,
                   Exec_Output(returncode=p.returncode, stdout=p.stdout,
                               stderr=p.stderr))
