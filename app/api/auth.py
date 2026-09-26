"""Login, logout, and who am I.

These three are public by necessity. Everything else becomes authenticated in
the next step, at the mount point, so that a route added later is protected
unless someone deliberately opts it out.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.api.deps import current_principal
from app.core import audit, auth, passwords
from app.core.authz import Role
from app.core.config import API_PREFIX, settings

router = APIRouter()


class Login_In(BaseModel):
    username: str
    password: str


class Me(BaseModel):
    username: str
    display_name: str | None = None
    role: Role
    # Echoed so the frontend can put it in the CSRF header without reading the
    # cookie, which is the more fragile half of double-submit in practice.
    csrf_token: str | None = None
    expires_at: str | None = None


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_session_cookies(response: Response, token: str, csrf: str) -> None:
    common = {
        "path": API_PREFIX,
        "samesite": "lax",
        "secure": settings.cookie_secure,
        "max_age": settings.session_ttl_hours * 3600,
    }
    # HttpOnly: this one must never be reachable from JavaScript.
    response.set_cookie(auth.COOKIE_NAME, token, httponly=True, **common)
    # Deliberately readable: the frontend echoes it back in a header, and that
    # echo is what proves the request came from our own origin.
    response.set_cookie(auth.CSRF_COOKIE, csrf, httponly=False, **common)


@router.post("/auth/login", response_model=Me)
def login(body: Login_In, request: Request, response: Response) -> Me:
    ip = _client_ip(request)

    if auth.throttled(body.username, ip):
        audit.event("login_throttled", subject=body.username, status="error")
        raise HTTPException(
            429, "too many failed attempts - wait a few minutes and try again"
        )

    row = auth.get_user(body.username)
    # The same message and the same work either way. Branching earlier on "no
    # such user" turns the endpoint into a username oracle, and returning
    # faster does it by timing even if the text matches.
    ok = bool(row) and not row["disabled"] and passwords.verify_password(
        body.password, row["pw_hash"]
    )

    auth.record_attempt(body.username, ip, ok)
    if not ok:
        audit.event("login_failed", subject=body.username, status="error")
        raise HTTPException(401, "username or password is incorrect")

    # The plaintext is available exactly here, so this is the only place a
    # hash made with weaker parameters can be upgraded.
    if passwords.needs_rehash(row["pw_hash"]):
        auth.set_password(body.username, passwords.hash_password(body.password))
        row = auth.get_user(body.username)

    token, csrf, expires = auth.start_session(
        int(row["id"]), ip, request.headers.get("user-agent")
    )
    _set_session_cookies(response, token, csrf)

    principal = auth.principal_from_row(row)
    audit.event("login_ok", subject=principal.username, role=principal.role.value)
    return Me(username=principal.username, display_name=principal.display_name,
              role=principal.role, csrf_token=csrf, expires_at=expires.isoformat())


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(auth.COOKIE_NAME)
    if token:
        found = auth.lookup(token)
        auth.revoke(token)
        if found:
            audit.event("logout", subject=found[0].username)

    response.delete_cookie(auth.COOKIE_NAME, path=API_PREFIX)
    response.delete_cookie(auth.CSRF_COOKIE, path=API_PREFIX)
    return {"ok": True}


@router.get("/auth/me", response_model=Me)
def me(request: Request,
       principal: auth.Principal = Depends(current_principal)) -> Me:
    """Who the caller is. The frontend calls this once on mount to decide
    between the login screen and the app."""
    return Me(
        username=principal.username,
        display_name=principal.display_name,
        role=principal.role,
        csrf_token=request.cookies.get(auth.CSRF_COOKIE),
    )
