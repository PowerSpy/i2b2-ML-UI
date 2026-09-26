from fastapi import APIRouter
from pydantic import BaseModel

from app.core import buildinfo
from app.core.config import APP_NAME

router = APIRouter()


class Health(BaseModel):
    status: str
    app: str
    # What code is answering. Every audit row carries the same three, so a log
    # line can be tied back to the build that produced it - and "it's behaving
    # oddly" starts with knowing which version "it" is.
    version: str
    release: str
    git_sha: str
    git_dirty: bool
    started_at: str
    uptime_sec: float


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health(status="ok", app=APP_NAME, **buildinfo.describe())
