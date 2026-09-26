"""FastAPI dependencies for identity and authorisation.

Kept out of `app/core/auth.py` so that module stays framework-free and
testable without spinning up an app. This is the only place a `Request` is
turned into a `Principal`.

Authorisation is done with the dependency tree, not middleware. Starlette
middleware sees raw paths before routing, so `/cohorts/3` versus `/cohorts`
would have to be pattern-matched by hand, and 422s from validation slip past
before a handler is ever chosen.
"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

from app.core import audit, auth
from app.core.authz import Role


async def current_principal(request: Request) -> auth.Principal:
    """The caller, or 401.

    Also enforces CSRF on unsafe methods, and binds the principal into the
    audit context so `docker_exec` and `db` rows five frames down are
    attributed without a Request being threaded to them.
    """
    # Before any account exists the app is unusable rather than open. 503 with
    # the exact command is better than a first-run web wizard: no race, no
    # default credentials, and nothing to forget to remove.
    if auth.user_count() == 0:
        raise HTTPException(
            503,
            "no accounts exist yet - create one on the server with: "
            "python -m app.cli create-user --username <you> --role custodian",
        )

    token = request.cookies.get(auth.COOKIE_NAME)
    if not token:
        raise HTTPException(401, "not signed in")

    found = auth.lookup(token)
    if found is None:
        raise HTTPException(401, "your session has ended - sign in again")

    principal, row = found

    if request.method in auth.UNSAFE_METHODS:
        sent = request.headers.get(auth.CSRF_HEADER)
        # Double submit. SameSite=Lax already blocks the cross-site POST; this
        # is the second lock and the one that survives a future SameSite
        # relaxation.
        if not sent or not _constant_eq(sent, row["csrf_token"]):
            audit.event("csrf_rejected", subject=principal.username, status="error")
            raise HTTPException(403, "missing or invalid CSRF token")

    request.state.principal = principal
    audit.set_actor(principal)
    return principal


async def optional_principal(request: Request) -> auth.Principal | None:
    """For routes that behave differently when signed in but do not require it."""
    try:
        return await current_principal(request)
    except HTTPException:
        return None


def require_role(*allowed: Role) -> Callable:
    """Dependency factory. Used from `router.py` to gate whole routers."""

    async def dep(principal: auth.Principal = Depends(current_principal)) -> auth.Principal:
        if principal.role not in allowed:
            audit.event(
                "authz_denied", subject=principal.username, status="error",
                required=[r.value for r in allowed], actual=principal.role.value,
            )
            raise HTTPException(
                403, "this account may not perform that action"
            )
        return principal

    return dep


custodian_only = require_role(Role.CUSTODIAN)


def _constant_eq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)
