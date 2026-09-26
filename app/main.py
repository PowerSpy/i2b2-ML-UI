import sys
import time

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.deps import current_principal
from app.api.router import api_router, public_router
from app.core import audit, store
from app.core.config import API_PREFIX, APP_NAME, settings
from app.core.etl_api import Etl_API_Error


class AuditMiddleware(BaseHTTPMiddleware):
    """Binds request-scoped audit context and records one row per request.

    The per-request row is the spine: every `container_exec` and `db_query`
    below it carries the same `request_id`, so "what did this call actually do
    to the warehouse" is a single query against the audit log rather than a
    guess from timestamps.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = audit.new_request_id()
        client = request.client.host if request.client else None
        started = time.perf_counter()

        with audit.request_context(request_id, request.method,
                                   request.url.path, client):
            try:
                response = await call_next(request)
            except Exception:
                audit.event(
                    "request", status="exception",
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
                raise

            elapsed = round((time.perf_counter() - started) * 1000, 1)
            # Health is polled constantly by the UI and says nothing; logging
            # it would bury the events that matter under its own noise.
            if request.url.path != f"{API_PREFIX}/health":
                audit.event(
                    "request",
                    status="ok" if response.status_code < 400 else "error",
                    duration_ms=elapsed,
                    http_status=response.status_code,
                )
            response.headers["X-Request-Id"] = request_id
            return response


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _warn_if_exposed() -> None:
    """Shout if this is bound off-loopback with loopback settings.

    The bind address is the only thing protecting this app today, and the
    defaults below are correct precisely because of it — a Secure cookie is
    never sent over http://localhost, so `cookie_secure` has to default False
    to work locally at all.

    The failure mode is someone changing `host` to 0.0.0.0 and inheriting
    every local default silently. This does not refuse to start, because
    refusing mid-deploy is its own kind of damage, but it makes the mistake
    impossible to miss in a log.
    """
    if settings.host in LOOPBACK:
        return

    problems = []
    if not settings.cookie_secure:
        problems.append(
            "cookie_secure is False - session cookies will be sent in clear "
            "text. Set it True and terminate TLS in front of this."
        )
    if settings.reload:
        problems.append(
            "reload is True - the server re-executes code on file write, "
            "which is a code-execution path on a writable deployment."
        )
    if any("localhost" in o or "127.0.0.1" in o for o in settings.cors_origins):
        problems.append(
            f"cors_origins still lists a localhost origin ({settings.cors_origins})."
        )

    # Worth saying even when nothing else is wrong: the docker-group privilege
    # this process holds is root-equivalent on the host, and it stops being an
    # accepted local risk the moment the API is reachable from elsewhere.
    problems.append(
        "this process can `docker exec` into the i2b2 containers, which is "
        "root-equivalent on the host - it should not be reachable from an "
        "untrusted network without a privileged-helper split."
    )

    banner = "!" * 72
    print(f"\n{banner}", file=sys.stderr)
    print(f"  bound to {settings.host}:{settings.port}, not loopback", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    print(f"{banner}\n", file=sys.stderr)

    audit.event("exposed_bind", status="error", host=settings.host,
                port=settings.port, problem_count=len(problems))


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME)

    # Before anything can serve a request, so a failure here is a loud startup
    # failure rather than a silently absent audit trail.
    store.migrate()
    _warn_if_exposed()

    @app.exception_handler(Etl_API_Error)
    def etl_error(request: Request, exc: Etl_API_Error) -> JSONResponse:
        return JSONResponse(status_code=502,
                            content={"detail": str(exc), "etl_status": exc.status})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Added last so it is outermost: it should see a request before CORS can
    # reject it, and it should still time a response CORS rewrote.
    app.add_middleware(AuditMiddleware)

    app.include_router(public_router, prefix=API_PREFIX)
    # Fail closed. Every route on api_router requires a session, including any
    # added later - opting out means moving it to public_router in
    # app/api/router.py, which is a visible edit in an obvious place.
    app.include_router(api_router, prefix=API_PREFIX,
                       dependencies=[Depends(current_principal)])
    return app


app = create_app()
