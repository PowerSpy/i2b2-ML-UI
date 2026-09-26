import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.router import api_router
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


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME)

    # Before anything can serve a request, so a failure here is a loud startup
    # failure rather than a silently absent audit trail.
    store.migrate()

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

    app.include_router(api_router, prefix=API_PREFIX)
    return app


app = create_app()
