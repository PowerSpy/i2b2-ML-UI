from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter()


class Health(BaseModel):
    status: str
    app: str


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health(status="ok", app=settings.app_name)
