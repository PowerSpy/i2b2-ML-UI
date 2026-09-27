"""Roles, and what each one may do.

Two roles, deliberately. A third ("viewer", "admin") is easy to add and hard to
remove, and every one multiplies the route matrix that has to stay correct.

`custodian` is what the app does today: full access, including the destructive
and patient-level routes. `researcher` is the new, narrower one — it exists so
that someone can define, build and inspect their own models without being able
to read patient identifiers, load or delete warehouse data, or touch a model
they do not own.

Enforcement lives in `app/api/router.py` (which routes are custodian-only) and
in the handful of handlers whose *response* changes by role. This module only
defines the vocabulary and the ownership checks.
"""

from datetime import UTC, datetime
from enum import Enum

from app.core import store
from app.core.config import settings


class Role(str, Enum):
    CUSTODIAN = "custodian"
    RESEARCHER = "researcher"


def researcher_namespace(username: str) -> str:
    """Where one researcher's models live: /ML/u/<username>.

    Not cosmetic, and not about tidiness. `POST /jobs/build` deletes every fact
    under the path it is given before it runs, and the path comes from the
    caller. Without a namespace there is nothing to check a researcher's
    request against, and "read-only researcher" would be a warehouse-wide
    delete primitive with extra steps.

    Note this does not move a model out of its project: projects are derived
    from a model's `data_paths`, not from where the model concept itself sits.
    """
    return f"{settings.ml_root.rstrip('/')}/u/{username}"


def in_namespace(path: str, namespace: str) -> bool:
    return path == namespace or path.startswith(f"{namespace}/")


# --------------------------------------------------------------------------
# ownership


def record_owner(code: str, path: str, owner_id: int) -> None:
    """Remember who created a model. Last writer wins, as re-saving does."""
    store.write(
        "INSERT INTO model_owner (code, path, owner_id, created_at)"
        " VALUES (?,?,?,?)"
        " ON CONFLICT(code) DO UPDATE SET path = excluded.path,"
        " owner_id = excluded.owner_id",
        (code, path, owner_id, datetime.now(UTC).isoformat()),
    )


def owner_of(code: str) -> str | None:
    rows = store.query(
        "SELECT u.username FROM model_owner m"
        " JOIN app_user u ON u.id = m.owner_id WHERE m.code = ?",
        (code,),
    )
    return rows[0]["username"] if rows else None


def owner_of_path(path: str) -> str | None:
    rows = store.query(
        "SELECT u.username FROM model_owner m"
        " JOIN app_user u ON u.id = m.owner_id WHERE m.path = ?",
        (path,),
    )
    return rows[0]["username"] if rows else None


def owners() -> dict[str, str]:
    """code -> username, for annotating a whole model list in one query."""
    return {
        r["code"]: r["username"]
        for r in store.query(
            "SELECT m.code, u.username FROM model_owner m"
            " JOIN app_user u ON u.id = m.owner_id"
        )
    }


def may_touch(principal, *, code: str | None = None,
              path: str | None = None) -> bool:
    """Whether `principal` may build, apply, edit or delete this model.

    A custodian may touch anything. A researcher may touch what they own -
    and, deliberately, **not** a model with no owner row. Unowned means it
    predates ownership or was made by a custodian directly; either way it is
    not theirs, and defaulting an unknown to "allowed" is how this kind of
    check ends up meaning nothing.
    """
    if principal.role is Role.CUSTODIAN:
        return True

    owner = owner_of(code) if code is not None else owner_of_path(path)
    return owner is not None and owner == principal.username
