import subprocess

from pydantic import BaseModel
from pathlib import Path


class Exec_Output(BaseModel):
    returncode: int
    stdout: str
    stderr: str


def exec(container: str, *cmds: str, timeout: float = 300.0) -> Exec_Output:
    script = " && ".join(cmds)
    p = subprocess.run(
        ["docker", "exec", container, "bash", "-lc", script],
        capture_output=True, text=True, timeout=timeout,
    )

    return Exec_Output(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)


def exec_detached(container: str, *cmds: str, timeout: float = 30.0) -> Exec_Output:
    script = " && ".join(cmds)
    p = subprocess.run(
        ["docker", "exec", "-d", container, "bash", "-lc", script],
        capture_output=True, text=True, timeout=timeout,
    )

    return Exec_Output(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)


def exec_cp(container: str, host_path: Path, container_path: Path, timeout: float = 300.0) -> Exec_Output:
    p = subprocess.run(
        ["docker", "cp", str(host_path), f"{container}:{container_path}"],
        capture_output=True, text=True, timeout=timeout,
    )

    return Exec_Output(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
