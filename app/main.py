from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.etl_api import Etl_API_Error


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)

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

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
