from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import APP_NAME

router = APIRouter()


class Health(BaseModel):
    status: str
    app: str


@router.get("/health", response_model=Health)
async def health() -> Health:
    return Health(status="ok", app=APP_NAME)
