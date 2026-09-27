"""Run a feature transform against fabricated data.

The whole dev loop with none of the risk: a researcher writes Python, runs it,
sees the frame it produced, and nothing that happens here touches a patient
row. The frame is built from the published data dictionary, which is already
suppressed, so the data on this path was never confidential to begin with.

That is why this endpoint returns frame contents and the real one never will.
The two must not look alike, and the difference is not cosmetic - it is the
line between "debugging aid" and "export".
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import current_principal
from app.core import authz, dictionary, sandbox, synthetic

router = APIRouter()

# Generous for a feature transform and small enough to ride in a request. The
# stored form is bounded separately and more tightly, because on the update
# path a model blob travels in a URL.
MAX_SOURCE_CHARS = 64 * 1024


class DryRunIn(BaseModel):
    source: str = Field(max_length=MAX_SOURCE_CHARS)
    n_rows: int | None = Field(default=None, ge=synthetic.MIN_ROWS,
                               le=synthetic.MAX_ROWS)
    seed: int | None = None
    # Halves fill rates and widens tails. The cheapest way to find out that a
    # transform assumes a column is always populated.
    hostile: bool = False
    timeout_s: int = Field(default=sandbox.DEFAULT_TIMEOUT_S, ge=5, le=300)


class DryRunOut(BaseModel):
    ok: bool
    error: dict | None = None
    report: dict | None = None
    logs: str = ""
    # Both frames, because "what went in" is half of reading a diff. Fake data
    # on both sides.
    input_preview: dict | None = None
    preview: dict | None = None
    plan: dict
    duration_ms: float | None = None
    container_stderr: str = ""


@router.post("/ml-concepts/{code}/transform/dry-run", response_model=DryRunOut)
def dry_run(code: str, body: DryRunIn,
            principal=Depends(current_principal)) -> DryRunOut:
    """Execute `source` against synthetic rows shaped like this model's frame.

    Ownership is enforced even though no data is at stake: a dry run costs a
    container and a CPU second, and more to the point the *shape* it returns is
    this model's column list. That is already published to any signed-in
    account by the data dictionary, but there is no reason for the rule to
    differ between two doors onto the same thing.
    """
    if not authz.may_touch(principal, code=code):
        raise HTTPException(403, "This model belongs to someone else.")

    try:
        described = dictionary.describe(dictionary.model_scope(code))
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    plan = synthetic.plan(described, n_rows=body.n_rows, seed=body.seed,
                          hostile=body.hostile)

    try:
        result = sandbox.run_transform(body.source, plan,
                                       timeout_s=body.timeout_s)
    except sandbox.SandboxUnavailable as e:
        # 409 and the fix, rather than a 500. The same doctrine as the job
        # queue's guards: refuse at the door naming the command, instead of
        # starting something that dies somewhere the caller cannot see.
        raise HTTPException(409, str(e))

    return DryRunOut(plan=plan, **{
        k: v for k, v in result.items()
        if k in DryRunOut.model_fields and k != "plan"
    })


@router.get("/ml-concepts/{code}/transform/frame", response_model=dict)
def frame_plan(code: str, n_rows: int | None = None, hostile: bool = False,
               principal=Depends(current_principal)) -> dict:
    """What the dry-run frame will look like, without running anything.

    Worth its own route because the warnings are the interesting part. A column
    the dictionary withheld arrives here as all-NaN, and a researcher who does
    not know that will write a transform that skips it in development and meets
    real values in production.
    """
    if not authz.may_touch(principal, code=code):
        raise HTTPException(403, "This model belongs to someone else.")
    try:
        described = dictionary.describe(dictionary.model_scope(code))
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    p = synthetic.plan(described, n_rows=n_rows, hostile=hostile)
    available, why = sandbox.available()
    return {**synthetic.summarise(p), "scope": p["scope"], "seed": p["seed"],
            "basis": p["basis"], "sandbox_available": available,
            "sandbox_unavailable_reason": why}
