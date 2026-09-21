from fastapi import APIRouter

from app.api import (
    cohorts,
    concepts,
    delete,
    health,
    jobs,
    loader,
    ml_models,
    predictions,
    quality,
    watcher,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(loader.router, tags=["load"])
api_router.include_router(delete.router, tags=["delete"])
api_router.include_router(concepts.router, tags=["concepts"])
api_router.include_router(cohorts.router, tags=["cohorts"])
api_router.include_router(ml_models.router, tags=["ml-concepts"])
api_router.include_router(watcher.router, tags=["watcher"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(predictions.router, tags=["predictions"])
api_router.include_router(quality.router, tags=["quality"])
