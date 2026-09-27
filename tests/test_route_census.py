"""Every route is classified, and anonymous callers are refused.

This is the test that stops the boundary rotting. `ROUTE_POLICY` is the
security decision written down; the census asserts the app matches it. A route
added later with no entry here **fails the build** rather than quietly
inheriting whatever the mount happened to do.

It also catches the opposite mistake: a route deleted from the app but left in
the policy, which would otherwise look like coverage that no longer exists.
"""

import pytest
from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"

# PUBLIC     - reachable with no session at all
# SESSION    - any signed-in account
# CUSTODIAN  - custodian role required
PUBLIC = "public"
SESSION = "session"
CUSTODIAN = "custodian"

ROUTE_POLICY: dict[tuple[str, str], str] = {
    ("GET", "/api/health"): PUBLIC,
    ("POST", "/api/auth/login"): PUBLIC,
    ("POST", "/api/auth/logout"): PUBLIC,
    # Public in the sense of "mounted without the dependency" - it depends on
    # current_principal itself and 401s for an anonymous caller.
    ("GET", "/api/auth/me"): PUBLIC,

    ("POST", "/api/load-concepts"): CUSTODIAN,
    ("POST", "/api/load-facts"): CUSTODIAN,
    ("GET", "/api/verify-load"): SESSION,
    ("DELETE", "/api/delete-concepts"): CUSTODIAN,
    ("DELETE", "/api/delete-facts"): CUSTODIAN,
    ("GET", "/api/concepts"): SESSION,
    ("GET", "/api/concept-tree"): SESSION,
    ("GET", "/api/cohorts"): SESSION,
    ("POST", "/api/cohorts"): CUSTODIAN,
    ("DELETE", "/api/cohorts"): CUSTODIAN,
    ("DELETE", "/api/cohorts/{cohort_id}"): CUSTODIAN,
    ("GET", "/api/cohorts/{cohort_id}/definition"): SESSION,
    ("GET", "/api/cohorts/{cohort_id}/size"): SESSION,
    ("GET", "/api/data-quality"): SESSION,
    ("GET", "/api/ml-model-types"): SESSION,
    ("GET", "/api/ml-concepts"): SESSION,
    ("POST", "/api/ml-concepts"): CUSTODIAN,
    ("DELETE", "/api/ml-concepts/{code}"): CUSTODIAN,
    ("GET", "/api/ml-concepts/{code}/config"): SESSION,
    ("GET", "/api/ml-concepts/{code}/metrics"): SESSION,
    ("GET", "/api/ml-concepts/{code}/plots"): SESSION,
    ("GET", "/api/watcher"): SESSION,
    ("POST", "/api/watcher/start"): CUSTODIAN,
    ("GET", "/api/watcher/log"): CUSTODIAN,
    ("POST", "/api/jobs/build"): CUSTODIAN,
    ("POST", "/api/jobs/apply"): CUSTODIAN,
    ("GET", "/api/jobs"): SESSION,
    ("POST", "/api/jobs/{job_id}/reset"): CUSTODIAN,
    ("GET", "/api/predictions/{code}"): SESSION,
}

IGNORED_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def app_routes() -> set[tuple[str, str]]:
    """Every (method, path) the app serves.

    Read from the OpenAPI schema rather than by walking `app.routes`: this
    FastAPI version wraps an included router in a `_IncludedRouter` that has no
    `.path`, so the obvious walk silently yields nothing - and a census that
    finds no routes passes its "everything is classified" check while testing
    absolutely nothing.
    """
    from app.main import app

    found = set()
    for path, ops in app.openapi()["paths"].items():
        if path in IGNORED_PATHS:
            continue
        for method in ops:
            if method.upper() in ("HEAD", "OPTIONS", "PARAMETERS"):
                continue
            found.add((method.upper(), path))
    return found


def test_every_route_is_classified(app_home):
    """A new route with no policy entry fails here, not in production."""
    unclassified = sorted(app_routes() - set(ROUTE_POLICY))
    assert not unclassified, (
        "these routes have no entry in ROUTE_POLICY - decide whether each is "
        f"public or requires a session, then add it: {unclassified}"
    )


def test_policy_has_no_stale_entries(app_home):
    """Coverage for a route that no longer exists is not coverage."""
    missing = sorted(set(ROUTE_POLICY) - app_routes())
    assert not missing, f"ROUTE_POLICY lists routes the app does not serve: {missing}"


NEEDS_SESSION = sorted(p for p, kind in ROUTE_POLICY.items() if kind != PUBLIC)
CUSTODIAN_ONLY = sorted(p for p, kind in ROUTE_POLICY.items() if kind == CUSTODIAN)


def _concrete(path: str) -> str:
    return (path.replace("{cohort_id}", "1")
                .replace("{job_id}", "1")
                .replace("{code}", "x"))


def _sign_in(role, tolerate_errors: bool = False):
    """A client signed in as `role`.

    `tolerate_errors` turns a handler exception into a 500 response instead of
    re-raising. Needed where the assertion is about the *status* and the
    handler legitimately blows up against a warehouse that is not there - an
    IndexError from psql returning nothing is not an authorisation result.
    """
    from app.core import auth, passwords
    from app.main import app

    auth.create_user("u", passwords.hash_password(PASSWORD), role)
    client = TestClient(app, raise_server_exceptions=not tolerate_errors)
    res = client.post("/api/auth/login", json={"username": "u", "password": PASSWORD})
    assert res.status_code == 200, res.text
    return client


@pytest.mark.parametrize("method,path", NEEDS_SESSION)
def test_session_routes_refuse_anonymous_callers(app_home, method, path, fake_exec):
    """The point of the fail-closed mount, asserted route by route.

    `fake_exec` is present so that a route which *did* let an anonymous caller
    through would be caught here rather than blowing up on a stopped container
    and looking like an unrelated failure.
    """
    from app.core import auth, passwords
    from app.core.authz import Role
    from app.main import app

    # An account must exist, or every route answers 503 (no accounts) and this
    # would pass without testing anything.
    auth.create_user("alice", passwords.hash_password(PASSWORD), Role.CUSTODIAN)

    res = TestClient(app).request(method, _concrete(path))

    assert res.status_code == 401, (
        f"{method} {path} answered {res.status_code} for an anonymous caller"
    )


def test_public_routes_are_reachable_anonymously(app_home):
    from app.main import app

    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    # Wrong credentials, but it is reachable - a 401 here is the endpoint
    # working, not the mount rejecting it.
    assert client.post("/api/auth/login",
                       json={"username": "nobody", "password": "x" * 12}
                       ).status_code in (401, 503)


@pytest.mark.parametrize("method,path", CUSTODIAN_ONLY)
def test_custodian_routes_refuse_researchers(app_home, method, path, fake_exec):
    """403, and - the part that matters - *before* the side effect.

    A check that runs after the handler has already copied a file into the
    container or queued a job has not prevented anything. `fake_exec` records
    every container call, and this asserts none happened.
    """
    from app.core.authz import Role

    client = _sign_in(Role.RESEARCHER)
    res = client.request(method, _concrete(path),
                         headers={"X-CSRF-Token": client.cookies.get("i2b2ml_csrf", "")})

    assert res.status_code == 403, (
        f"{method} {path} answered {res.status_code} for a researcher"
    )
    assert not fake_exec, (
        f"{method} {path} reached a container before authz rejected it: {fake_exec}"
    )


@pytest.mark.parametrize(
    "method,path",
    sorted(p for p, kind in ROUTE_POLICY.items() if kind == SESSION),
)
def test_session_routes_allow_researchers(app_home, method, path, fake_exec):
    """The other half: a researcher must not be locked out of the reads.

    A role that cannot do anything is not a role, it is a disabled account.
    These may still 500 against a stopped warehouse - what matters is that the
    answer is not 403.
    """
    from app.core.authz import Role

    client = _sign_in(Role.RESEARCHER, tolerate_errors=True)
    res = client.request(method, _concrete(path),
                         headers={"X-CSRF-Token": client.cookies.get("i2b2ml_csrf", "")})

    assert res.status_code != 403, f"{method} {path} refused a researcher"
    assert res.status_code != 401, f"{method} {path} did not accept the session"
