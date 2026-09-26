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

from enum import Enum


class Role(str, Enum):
    CUSTODIAN = "custodian"
    RESEARCHER = "researcher"


# Where a researcher's models live. Their model paths are forced under this,
# so `assert_may_touch_path` has something to check against - see the note in
# that function about why this is not cosmetic.
def researcher_namespace(username: str, ml_root: str) -> str:
    return f"{ml_root.rstrip('/')}/u/{username}"
