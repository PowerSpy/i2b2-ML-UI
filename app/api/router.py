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

from fastapi import APIRouter, Depends

from app.api.deps import custodian_only

from app.api import (
    auth,
    cohorts,
    concepts,
    delete,
    dictionary,
    health,
    jobs,
    loader,
    ml_models,
    predictions,
    quality,
    transform,
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
#
# Two tiers below: anything on `api_router` is open to any signed-in account,
# anything mounted with CUSTODIAN requires that role. The whole role policy is
# these twenty lines, which is the point of collecting it here rather than
# scattering `dependencies=` across decorators in nine modules.

api_router = APIRouter()

CUSTODIAN = [Depends(custodian_only)]

# --- open to any signed-in account -----------------------------------------
# Reads, and the routes whose payload is narrowed by role rather than refused
# outright (that narrowing lands with the suppression work).
api_router.include_router(concepts.router, tags=["concepts"])
api_router.include_router(predictions.router, tags=["predictions"])
api_router.include_router(quality.router, tags=["quality"])
# Aggregate shapes only, already suppressed. It is what lets a researcher
# write code against data they cannot see.
api_router.include_router(dictionary.router, tags=["dictionary"])
# Running a researcher's code - but only ever against fabricated rows built
# from that same suppressed dictionary. The real-data path is not here and
# will not be: it runs inside the ETL container, behind the job queue.
api_router.include_router(transform.router, tags=["transform"])
api_router.include_router(loader.router, tags=["load"])          # verify-load
api_router.include_router(cohorts.router, tags=["cohorts"])      # reads
api_router.include_router(ml_models.router, tags=["ml-concepts"])  # reads
api_router.include_router(watcher.router, tags=["watcher"])      # status only
api_router.include_router(jobs.router, tags=["jobs"])            # the job list

# --- custodian only --------------------------------------------------------
# Everything that writes to the warehouse, destroys something, spawns a
# process in a container, or reads raw container output.

# The whole module: both routes truncate warehouse tables wholesale.
api_router.include_router(delete.router, tags=["delete"], dependencies=CUSTODIAN)

# Uploads are how patient rows enter, and the filename crosses into a shell.
api_router.include_router(loader.custodian_router, tags=["load"],
                          dependencies=CUSTODIAN)

# Creating a patient set runs a generated script inside the ETL container;
# deleting one is destructive and unrecoverable.
api_router.include_router(cohorts.custodian_router, tags=["cohorts"],
                          dependencies=CUSTODIAN)

# /watcher/start spawns a daemon; /watcher/log is raw ETL stdout, which carries
# failing SQL and sample rows.
api_router.include_router(watcher.custodian_router, tags=["watcher"],
                          dependencies=CUSTODIAN)

# Job reset is queue surgery: it flips someone else's PROCESSING row back to
# PENDING, and getting it wrong starts a second worker on a live job.
api_router.include_router(jobs.custodian_router, tags=["jobs"],
                          dependencies=CUSTODIAN)

# Build, apply, and model create/delete are open to any signed-in account and
# gated *inside* the handler on ownership instead. They cannot be decided from
# the route alone: whether a researcher may submit a build depends on whether
# the path they submitted is theirs, which only the body says.
#
# jobs.py:_assert_may_touch and ml_models' authz.may_touch are the real
# boundary for these four; the census test pins them so they cannot quietly
# become open.
