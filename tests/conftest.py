"""Shared fixtures.

The defining constraint: **no test may touch Docker or i2b2.** `docker_exec` is
replaced with a fake that fails the test if a real subprocess would have been
spawned, so the suite runs on a laptop with no containers and cannot quietly
start depending on a live warehouse.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def app_home(tmp_path, monkeypatch):
    """Point the app's own SQLite and audit log at a temp dir."""
    from app.core import audit, store
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_db", tmp_path / "app.db")
    monkeypatch.setattr(settings, "audit_dir", tmp_path / "audit")
    monkeypatch.setattr(settings, "audit_enabled", True)

    store.close()
    store.migrate()
    yield tmp_path
    store.close()


@pytest.fixture
def no_docker(monkeypatch):
    """Fail loudly if anything tries to reach a container.

    Returns a list that records the commands that *would* have run, so a test
    can assert on what the app tried to do without anything happening.
    """
    calls: list[tuple] = []

    def _fail(*args, **kwargs):
        raise AssertionError(
            f"a test reached subprocess.run({args[0] if args else '?'}) - "
            "tests must not touch Docker"
        )

    monkeypatch.setattr("subprocess.run", _fail)
    return calls


@pytest.fixture
def fake_exec(monkeypatch):
    """Stop docker calls at the subprocess boundary, not at docker_exec.

    Patching `docker_exec.exec` does not work: most callers do
    `from app.core.docker_exec import exec`, which binds the name at import
    time, so the module attribute they no longer consult is irrelevant.
    Patching `subprocess.run` catches every caller however it imported, and -
    the point of these tests - leaves docker_exec's own audit hooks running.

    Returns the recorded argv lists.
    """
    import subprocess

    from app.core import docker_exec

    calls: list[list[str]] = []
    real_run = subprocess.run

    def _run(argv, *a, **kw):
        if isinstance(argv, (list, tuple)) and argv and argv[0] == "docker":
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        # Anything else (git, in buildinfo) behaves normally.
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(docker_exec.subprocess, "run", _run)
    return calls


def audit_text(app_home) -> str:
    """Everything the audit sinks wrote, as one searchable string."""
    from app.core import store

    parts = []
    audit_dir = Path(app_home) / "audit"
    if audit_dir.exists():
        for f in sorted(audit_dir.glob("*.jsonl")):
            parts.append(f.read_text(encoding="utf8"))

    rows = store.query("SELECT * FROM audit_event")
    for r in rows:
        parts.append(" ".join("" if v is None else str(v) for v in tuple(r)))
    return "\n".join(parts)
