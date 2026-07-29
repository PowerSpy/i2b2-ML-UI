"""Uvicorn entrypoint: `python main.py` or `uvicorn main:app --reload`."""

import uvicorn

from app.main import app  # noqa: F401  (re-exported so `uvicorn main:app` works)
from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )
