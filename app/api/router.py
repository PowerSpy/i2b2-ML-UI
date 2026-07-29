from fastapi import APIRouter

from app.api import health, loader, delete

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(loader.router, tags=["load-concepts", "load-facts", "verify-load"])
api_router.include_router(delete.router, tags=["delete-concepts", "delete-facts"])
