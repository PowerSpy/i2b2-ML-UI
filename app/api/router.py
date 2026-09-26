"""Route mounting, and the security boundary.

Two routers, and the split is the whole point:

- `public_router` is the short, explicit list of things reachable without a
  session. It is meant to be read in one glance and to be hard to add to by
  accident.
- `api_router` is everything else. `app/main.py` mounts it behind
  `Depends(current_principal)`, so **a route added to any module below is
  authenticated without anyone remembering to do anything.** Opting out is a
  deliberate edit to this file, in the one place a reviewer will look.

That default matters more than the line it costs. The alternative - a
decorator on each handler - is correct exactly until someone adds the
thirty-first route and forgets.
"""

from fastapi import APIRouter

from app.api import (
    auth,
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

# ---------------------------------------------------------------------------
# Public. Anything added here is reachable by anyone who can open a socket.

public_router = APIRouter()

# Liveness. Carries the build stamp, which is safe on an internal service and
# is the first thing wanted when something is behaving oddly.
public_router.include_router(health.router, tags=["health"])

# Login has to be reachable to log in. /auth/me and /auth/logout live here too
# and enforce their own session handling: me() depends on current_principal and
# 401s on its own, and logout must work even from a session that has expired.
public_router.include_router(auth.router, tags=["auth"])


# ---------------------------------------------------------------------------
# Authenticated. Mounted in app/main.py behind current_principal.

api_router = APIRouter()

api_router.include_router(loader.router, tags=["load"])
api_router.include_router(delete.router, tags=["delete"])
api_router.include_router(concepts.router, tags=["concepts"])
api_router.include_router(cohorts.router, tags=["cohorts"])
api_router.include_router(ml_models.router, tags=["ml-concepts"])
api_router.include_router(watcher.router, tags=["watcher"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(predictions.router, tags=["predictions"])
api_router.include_router(quality.router, tags=["quality"])
