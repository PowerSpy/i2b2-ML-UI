"""Who did what, against which data, when.

Nothing in this repo logged anything before this. That is a problem on its own,
but it is a blocker for the researcher role specifically: a boundary you cannot
observe is a boundary you cannot show anyone you enforced.

Two sinks, deliberately:

- `audit_event` in SQLite, so it can be queried.
- append-only JSONL under `var/audit/`, so it is greppable, survives database
  corruption, and can be shipped off-box later without changing this module.

**This module never raises.** An audit failure must not turn a working request
into a 500. It does write to stderr when a sink fails, because a silently dead
audit log is worse than no audit log — the same reasoning the rest of this
codebase applies to loads that report success and do nothing.

## What may never be written

`DENY_KEYS` and `_scrub` are the enforcement, not a convention. Log *shapes* —
counts, hashes, lengths, durations — never contents. Specifically: no password,
no session token, no patient number, no CSV bytes, no concept blob.
"""

import json
import os
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from app.core import buildinfo, store
from app.core.config import settings

# Set by the auth phase. Until then every actor is "anonymous", which is the
# honest description of an API with no authentication.
_actor: ContextVar[object | None] = ContextVar("audit_actor", default=None)
_request_id: ContextVar[str | None] = ContextVar("audit_request_id", default=None)
_http: ContextVar[tuple[str, str] | None] = ContextVar("audit_http", default=None)
_client_ip: ContextVar[str | None] = ContextVar("audit_client_ip", default=None)

_file_lock = threading.Lock()

# Substring match: a key containing any of these is a secret or an identifier
# however it is spelled, so `etl_password` and `session_id` are caught without
# being enumerated.
DENY_SUBSTR = (
    "password", "passwd", "secret", "token", "session", "cookie",
    "authorization", "credential", "blob", "patient_num", "subject_id",
    "mrn", "nval", "tval",
)

# Exact match only. These words name a *container* of data when they stand
# alone ("rows", "patients") but a perfectly safe count when they are part of a
# longer name ("rows_loaded", "row_count", "patients_with_value"). Substring
# matching here redacted `rows_loaded` on every load - which is the single
# number that says whether the load did anything, and the reason the event
# exists at all. Counts are shapes; shapes are what this log is for.
DENY_EXACT = frozenset({
    "rows", "values", "patients", "data", "csv", "content", "payload", "body",
})

REDACTED = "[redacted]"

# Long free text (a SQL string, a shell script) is kept but bounded: the point
# is to know what ran, and 4 KB is more than enough to identify it.
MAX_TEXT = 4000


def _denied(key: str) -> bool:
    k = key.lower()
    return k in DENY_EXACT or any(d in k for d in DENY_SUBSTR)


def _scrub(value, key: str = ""):
    """Recursively drop anything on the denylist and bound what is left."""
    if _denied(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: _scrub(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        # Collections are summarised, never enumerated - a list is the shape a
        # patient identifier arrives in.
        return f"[{len(value)} items]"
    if isinstance(value, str) and len(value) > MAX_TEXT:
        return value[:MAX_TEXT] + f"… (+{len(value) - MAX_TEXT} chars)"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return type(value).__name__


def _actor_fields() -> dict:
    a = _actor.get()
    if a is None:
        return {"actor_id": None, "actor_username": "anonymous", "actor_role": None}
    return {
        "actor_id": getattr(a, "id", None),
        "actor_username": getattr(a, "username", "unknown"),
        "actor_role": getattr(getattr(a, "role", None), "value", None)
        or getattr(a, "role", None),
    }


def _log_path() -> Path:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return Path(settings.audit_dir) / f"audit-{day}.jsonl"


def event(kind: str, *, subject: str | None = None, status: str = "ok",
          duration_ms: float | None = None, **detail) -> None:
    """Record one event. Never raises."""
    if not settings.audit_enabled:
        return

    try:
        method, path = _http.get() or (None, None)
        row = {
            "ts_utc": datetime.now(UTC).isoformat(),
            "request_id": _request_id.get(),
            **_actor_fields(),
            "kind": kind,
            "subject": _scrub(subject, "subject") if subject else None,
            "method": method,
            "path": path,
            "status": status,
            "duration_ms": duration_ms,
            "client_ip": _client_ip.get(),
            "app_version": buildinfo.VERSION,
            "git_sha": buildinfo.git_sha(),
            "git_dirty": buildinfo.git_dirty(),
            "detail": {k: _scrub(v, k) for k, v in detail.items()},
        }
    except Exception as e:  # noqa: BLE001 - constructing a row must not 500
        print(f"[audit] could not build event {kind!r}: {e}", file=sys.stderr)
        return

    # Each sink guards itself, and this guards the contract. The docstring
    # promises this module never raises; that promise has to hold however the
    # sinks are implemented later, not only while they happen to be careful.
    for sink in (_to_jsonl, _to_sqlite):
        try:
            sink(row)
        except Exception as e:  # noqa: BLE001
            print(f"[audit] {sink.__name__} raised: {e}", file=sys.stderr)


def _to_jsonl(row: dict) -> None:
    try:
        p = _log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, default=str, ensure_ascii=False)
        with _file_lock:
            with p.open("a", encoding="utf8") as fh:
                fh.write(line + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"[audit] jsonl sink failed: {e}", file=sys.stderr)


def _to_sqlite(row: dict) -> None:
    try:
        store.write(
            "INSERT INTO audit_event ("
            " ts_utc, request_id, actor_id, actor_username, actor_role, kind,"
            " subject, method, path, status, duration_ms, client_ip,"
            " app_version, git_sha, git_dirty, detail_json"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["ts_utc"], row["request_id"], row["actor_id"],
                row["actor_username"], row["actor_role"], row["kind"],
                row["subject"], row["method"], row["path"], row["status"],
                row["duration_ms"], row["client_ip"], row["app_version"],
                row["git_sha"], int(bool(row["git_dirty"])),
                json.dumps(row["detail"], default=str, ensure_ascii=False),
            ),
        )
    except Exception as e:  # noqa: BLE001
        print(f"[audit] sqlite sink failed: {e}", file=sys.stderr)


@contextmanager
def request_context(request_id: str, method: str, path: str, client_ip: str | None):
    """Bind request-scoped fields so deep call sites can attribute their work.

    `docker_exec` and `db` are five frames below any handler and must not have
    a Request threaded down to them; a ContextVar is what makes "which request
    ran this psql" answerable without that.
    """
    tokens = [
        _request_id.set(request_id),
        _http.set((method, path)),
        _client_ip.set(client_ip),
    ]
    try:
        yield
    finally:
        _request_id.reset(tokens[0])
        _http.reset(tokens[1])
        _client_ip.reset(tokens[2])


def set_actor(principal) -> None:
    """Bind the caller for the rest of this request.

    A plain set rather than a context manager: the ContextVar is already
    scoped to the request by `request_context`, so it does not need unwinding
    and the dependency that calls this has no block to wrap.
    """
    _actor.set(principal)


@contextmanager
def actor(principal) -> None:
    """Bind the caller. Used by the auth phase; a no-op until then."""
    token = _actor.set(principal)
    try:
        yield
    finally:
        _actor.reset(token)


def new_request_id() -> str:
    return os.urandom(8).hex()
