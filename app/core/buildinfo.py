"""What code is actually running.

Nothing in this repo recorded this. A model's blob stores how long its fit took
but not when it ran; the job row that ran it is not linked to the model; and no
response says which build of the app answered it. Six months from now a log
line or a surprising ROC-AUC cannot be tied back to the code that produced it.

`dirty` is the honest half. A hand-edited box reports `0.1.0+abc1234-dirty`,
which is the truth, rather than a version number that implies a clean checkout.
"""

import subprocess
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

VERSION = "0.1.0"

REPO = Path(__file__).resolve().parents[2]

# Import time, once. Every audit row carries this and the process cannot change
# its own commit while running.
STARTED_AT = datetime.now(UTC)


def _git(*args: str) -> str | None:
    """A git command, or None if git is absent or this is not a checkout."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), *args],
            capture_output=True, text=True, timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


@lru_cache(maxsize=1)
def git_sha() -> str:
    return _git("rev-parse", "--short", "HEAD") or "unknown"


@lru_cache(maxsize=1)
def git_dirty() -> bool:
    # None (no git) is reported as not-dirty rather than dirty: an unknown sha
    # already says the provenance is unavailable, and claiming uncommitted
    # changes we cannot see would be its own kind of lie.
    status = _git("status", "--porcelain")
    return bool(status)


def release() -> str:
    """`0.1.0+abc1234` or `0.1.0+abc1234-dirty`."""
    tail = "-dirty" if git_dirty() else ""
    return f"{VERSION}+{git_sha()}{tail}"


def uptime_sec() -> float:
    return (datetime.now(UTC) - STARTED_AT).total_seconds()


def describe() -> dict:
    return {
        "version": VERSION,
        "release": release(),
        "git_sha": git_sha(),
        "git_dirty": git_dirty(),
        "started_at": STARTED_AT.isoformat(),
        "uptime_sec": round(uptime_sec(), 1),
    }
