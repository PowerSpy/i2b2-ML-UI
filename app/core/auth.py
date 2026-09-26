"""Accounts and sessions.

Design notes that are not obvious from the code:

**Opaque cookie, not a bearer token.** The frontend is same-origin with the API
in both dev (Vite proxies `/api`) and prod, so an `HttpOnly` cookie works with
no CORS credential handling and `api.js` needs one line. HttpOnly matters here
specifically: `PlotsPanel.jsx` renders blob content into a `data:` URI and
`JobQueue.jsx` renders ETL stack traces, so a token in `localStorage` would be
readable by any XSS on that surface.

**Only the hash of the token is stored.** A stolen copy of `app.db` gives up
password hashes, which are expensive to attack; it must not also give up live
sessions, which would be free.

**CSRF by double submit.** `SameSite=Lax` already blocks a cross-site POST;
this is the second lock, and it is what makes the cookie safe to widen later if
the deployment ever needs `SameSite=None`.

**The i2b2 session id in config.yaml is untouched.** That is the backend's
service credential for talking to the ETL, not a user identity, and it stays
exactly where it is. Conflating the two is the confusion this module exists to
remove.
"""

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core import audit, store
from app.core.authz import Role
from app.core.config import settings

COOKIE_NAME = "i2b2ml_session"
# Readable by JavaScript on purpose - the frontend has to echo it back in a
# header, which is the half of double-submit that proves same-origin.
CSRF_COOKIE = "i2b2ml_csrf"
CSRF_HEADER = "X-CSRF-Token"

TOKEN_BYTES = 32

# A session may slide this far forward on use, but never past MAX_LIFETIME
# from when it was created. Sliding alone means a tab left open is a permanent
# credential.
MAX_LIFETIME = timedelta(days=7)

# Throttling. Per username *and* per IP: the first stops one account being
# ground down, the second stops one host spraying many accounts.
WINDOW = timedelta(minutes=15)
MAX_PER_USER = 10
MAX_PER_IP = 30

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class Principal:
    id: int
    username: str
    role: Role
    display_name: str | None = None

    @property
    def is_custodian(self) -> bool:
        return self.role is Role.CUSTODIAN

    @property
    def is_researcher(self) -> bool:
        return self.role is Role.RESEARCHER


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf8")).hexdigest()


# --------------------------------------------------------------------------
# accounts


def user_count() -> int:
    return store.query("SELECT count(*) AS n FROM app_user")[0]["n"]


def get_user(username: str) -> sqlite3.Row | None:
    rows = store.query(
        "SELECT * FROM app_user WHERE username = ? COLLATE NOCASE", (username,)
    )
    return rows[0] if rows else None


def create_user(username: str, pw_hash: str, role: Role,
                display_name: str | None = None,
                created_by: str | None = None) -> int:
    store.write(
        "INSERT INTO app_user (username, display_name, role, pw_hash,"
        " created_at, created_by) VALUES (?,?,?,?,?,?)",
        (username, display_name, role.value, pw_hash, _iso(_now()), created_by),
    )
    row = get_user(username)
    audit.event("user_created", subject=username, role=role.value,
                created_by=created_by)
    return int(row["id"])


def set_password(username: str, pw_hash: str, by: str | None = None) -> None:
    store.write("UPDATE app_user SET pw_hash = ? WHERE username = ? COLLATE NOCASE",
                (pw_hash, username))
    # Every existing session for that account dies with the old password. A
    # password change that leaves a stolen session working has not changed
    # anything that matters.
    revoke_all_for_user(username)
    audit.event("password_changed", subject=username, changed_by=by)


def set_role(username: str, role: Role, by: str | None = None) -> None:
    store.write("UPDATE app_user SET role = ? WHERE username = ? COLLATE NOCASE",
                (role.value, username))
    # Same reasoning: a demotion must take effect now, not when the session
    # happens to expire.
    revoke_all_for_user(username)
    audit.event("role_changed", subject=username, new_role=role.value, changed_by=by)


def set_disabled(username: str, disabled: bool, by: str | None = None) -> None:
    store.write("UPDATE app_user SET disabled = ? WHERE username = ? COLLATE NOCASE",
                (1 if disabled else 0, username))
    if disabled:
        revoke_all_for_user(username)
    audit.event("user_disabled" if disabled else "user_enabled",
                subject=username, changed_by=by)


def list_users() -> list[sqlite3.Row]:
    return store.query(
        "SELECT id, username, display_name, role, disabled, created_at, created_by"
        " FROM app_user ORDER BY username"
    )


def principal_from_row(row: sqlite3.Row) -> Principal:
    return Principal(id=int(row["id"]), username=row["username"],
                     role=Role(row["role"]), display_name=row["display_name"])


# --------------------------------------------------------------------------
# throttling


def _recent_failures(username: str | None, client_ip: str | None) -> tuple[int, int]:
    since = _iso(_now() - WINDOW)
    by_user = 0
    if username:
        by_user = store.query(
            "SELECT count(*) AS n FROM login_attempt"
            " WHERE ok = 0 AND username = ? COLLATE NOCASE AND ts_utc >= ?",
            (username, since),
        )[0]["n"]
    by_ip = 0
    if client_ip:
        by_ip = store.query(
            "SELECT count(*) AS n FROM login_attempt"
            " WHERE ok = 0 AND client_ip = ? AND ts_utc >= ?",
            (client_ip, since),
        )[0]["n"]
    return int(by_user), int(by_ip)


def throttled(username: str | None, client_ip: str | None) -> bool:
    by_user, by_ip = _recent_failures(username, client_ip)
    return by_user >= MAX_PER_USER or by_ip >= MAX_PER_IP


def record_attempt(username: str | None, client_ip: str | None, ok: bool) -> None:
    store.write(
        "INSERT INTO login_attempt (ts_utc, username, client_ip, ok) VALUES (?,?,?,?)",
        (_iso(_now()), username, client_ip, 1 if ok else 0),
    )


# --------------------------------------------------------------------------
# sessions


def start_session(user_id: int, client_ip: str | None,
                  user_agent: str | None) -> tuple[str, str, datetime]:
    """Returns (session_token, csrf_token, expires_at).

    The session token is returned to the caller once and never stored.
    """
    token = secrets.token_urlsafe(TOKEN_BYTES)
    csrf = secrets.token_urlsafe(TOKEN_BYTES)
    now = _now()
    expires = now + timedelta(hours=settings.session_ttl_hours)

    store.write(
        "INSERT INTO app_session (token_hash, csrf_token, user_id, created_at,"
        " expires_at, last_seen_at, client_ip, user_agent) VALUES (?,?,?,?,?,?,?,?)",
        (token_hash(token), csrf, user_id, _iso(now), _iso(expires),
         _iso(now), client_ip, (user_agent or "")[:300]),
    )
    return token, csrf, expires


def lookup(token: str) -> tuple[Principal, sqlite3.Row] | None:
    """The principal behind a session token, or None.

    Slides the expiry forward on use, bounded by MAX_LIFETIME from creation.
    An expired row is deleted rather than left to accumulate.
    """
    rows = store.query(
        "SELECT s.*, u.username, u.role, u.display_name, u.disabled"
        " FROM app_session s JOIN app_user u ON u.id = s.user_id"
        " WHERE s.token_hash = ?",
        (token_hash(token),),
    )
    if not rows:
        return None
    row = rows[0]

    now = _now()
    if _parse(row["expires_at"]) <= now:
        revoke(token)
        audit.event("session_expired", subject=row["username"])
        return None

    if row["disabled"]:
        revoke(token)
        return None

    hard_stop = _parse(row["created_at"]) + MAX_LIFETIME
    slide_to = min(now + timedelta(hours=settings.session_ttl_hours), hard_stop)
    if slide_to > _parse(row["expires_at"]):
        store.write(
            "UPDATE app_session SET expires_at = ?, last_seen_at = ?"
            " WHERE token_hash = ?",
            (_iso(slide_to), _iso(now), token_hash(token)),
        )
    else:
        store.write(
            "UPDATE app_session SET last_seen_at = ? WHERE token_hash = ?",
            (_iso(now), token_hash(token)),
        )

    # Built by hand rather than via principal_from_row: this is a joined
    # session row, whose `id` column would be the session's if it had one -
    # the user's primary key arrives here as `user_id`.
    principal = Principal(
        id=int(row["user_id"]), username=row["username"],
        role=Role(row["role"]), display_name=row["display_name"],
    )
    return principal, row


def revoke(token: str) -> None:
    store.write("DELETE FROM app_session WHERE token_hash = ?", (token_hash(token),))


def revoke_all_for_user(username: str) -> None:
    store.write(
        "DELETE FROM app_session WHERE user_id IN"
        " (SELECT id FROM app_user WHERE username = ? COLLATE NOCASE)",
        (username,),
    )


def purge_expired() -> int:
    """Housekeeping. Expired rows are also dropped on lookup; this catches the
    ones nobody ever comes back for."""
    before = store.query("SELECT count(*) AS n FROM app_session")[0]["n"]
    store.write("DELETE FROM app_session WHERE expires_at <= ?", (_iso(_now()),))
    after = store.query("SELECT count(*) AS n FROM app_session")[0]["n"]
    return int(before) - int(after)
