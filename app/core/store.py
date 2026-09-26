"""The app's own SQLite database.

Separate from the warehouse on purpose. Everything the app knows about i2b2
goes through `psql` inside a container (`app/core/db.py`); this holds what
belongs to the app itself and must not depend on a container being up — the
audit log especially, which has to keep working while the thing it is
recording is broken.

Migrations are additive and idempotent. Step 1 creates `audit_event`; the auth
phase adds its own tables to the same file without touching this one.
"""

import sqlite3
import threading
from pathlib import Path

from app.core.config import settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def path() -> Path:
    return Path(settings.app_db)


def connect() -> sqlite3.Connection:
    """The process-wide connection, opened on first use.

    One connection guarded by a lock rather than one per call: FastAPI runs
    sync endpoints in a threadpool, and `docker_exec` is audited on every call,
    so connection setup would otherwise land on a hot path.
    """
    global _conn
    with _lock:
        if _conn is not None:
            return _conn

        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(p), check_same_thread=False, timeout=10.0)
        conn.row_factory = sqlite3.Row
        # WAL so a reader (someone running a query against the audit log) does
        # not block the writer.
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        _conn = conn
        return _conn


SCHEMA = [
    # Audit. Written by app/core/audit.py; see the denylist there for what may
    # never appear in `detail_json`.
    """
    CREATE TABLE IF NOT EXISTS audit_event (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_utc        TEXT    NOT NULL,
        request_id    TEXT,
        actor_id      INTEGER,
        actor_username TEXT   NOT NULL DEFAULT 'anonymous',
        actor_role    TEXT,
        kind          TEXT    NOT NULL,
        subject       TEXT,
        method        TEXT,
        path          TEXT,
        status        TEXT    NOT NULL DEFAULT 'ok',
        duration_ms   REAL,
        client_ip     TEXT,
        app_version   TEXT,
        git_sha       TEXT,
        git_dirty     INTEGER,
        detail_json   TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS audit_ts     ON audit_event (ts_utc);",
    "CREATE INDEX IF NOT EXISTS audit_kind   ON audit_event (kind, ts_utc);",
    "CREATE INDEX IF NOT EXISTS audit_actor  ON audit_event (actor_username, ts_utc);",
    "CREATE INDEX IF NOT EXISTS audit_req    ON audit_event (request_id);",
]


def migrate() -> None:
    """Apply the schema. Safe to call on every start."""
    conn = connect()
    with _lock:
        for stmt in SCHEMA:
            conn.execute(stmt)
        conn.commit()

    # 0600 where the platform honours it. On Windows this is a no-op and the
    # file's ACL is the operator's job - said plainly rather than pretending
    # the chmod did something.
    try:
        path().chmod(0o600)
    except (OSError, NotImplementedError):
        pass


def write(sql: str, params: tuple) -> None:
    """One INSERT under the shared lock."""
    conn = connect()
    with _lock:
        conn.execute(sql, params)
        conn.commit()


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = connect()
    with _lock:
        return conn.execute(sql, params).fetchall()


def close() -> None:
    """For tests; the process otherwise holds this open for its lifetime."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
