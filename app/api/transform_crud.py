"""Reading, saving and clearing a model's feature transform.

Dedicated routes, **plus** a carry-forward inside the model save itself. The
carry-forward is the safer half: `ModelForm` builds its blob from scratch and
the backend writes it whole, so without it, changing the algorithm would
silently delete the transform and the next build would train a different model
and report success. Relying on every future form to remember is not a plan.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import current_principal
from app.core import authz, ml_blob, transform_store
from app.core.auth import Principal

router = APIRouter()


class Transform(BaseModel):
    code: str
    present: bool
    source: str | None = None
    sha256: str | None = None
    saved_at: str | None = None
    author: str | None = None
    # False when the stored bytes do not match their recorded digest. The
    # source is still returned so it can be inspected and replaced.
    intact: bool = True
    problem: str | None = None
    max_bytes: int = transform_store.MAX_SOURCE_BYTES


class TransformIn(BaseModel):
    # The hard bound lives in `transform_store.validate`; this one keeps an
    # absurd payload from being parsed at all.
    source: str = Field(max_length=transform_store.MAX_SOURCE_BYTES * 2)


class TransformSaved(BaseModel):
    code: str
    sha256: str
    saved_at: str | None = None
    warnings: list[str] = []


def _owned(code: str, principal: Principal) -> str:
    """Check the caller may edit this model, and return its path."""
    if not ml_blob.exists(code):
        raise HTTPException(404, f"no model {code!r}")
    if not authz.may_touch(principal, code=code):
        raise HTTPException(403, "This model belongs to someone else.")

    path = ml_blob.path_of(code)
    if not path:
        raise HTTPException(409, f"{code} has no concept path to write back to.")
    return path


@router.get("/ml-concepts/{code}/transform", response_model=Transform)
def get_transform(code: str,
                  principal: Principal = Depends(current_principal)) -> Transform:
    """The stored source, or `present: false`.

    Readable by any signed-in account, like the rest of a model's metadata.
    Editing is not.
    """
    if not ml_blob.exists(code):
        raise HTTPException(404, f"no model {code!r}")

    record = transform_store.load(code)
    if record is None:
        return Transform(code=code, present=False)
    return Transform(code=code, present=True, **{
        k: record[k] for k in ("source", "sha256", "saved_at", "author",
                               "intact", "problem")
    })


@router.put("/ml-concepts/{code}/transform", response_model=TransformSaved)
def put_transform(code: str, body: TransformIn,
                  principal: Principal = Depends(current_principal)) -> TransformSaved:
    """Store a transform, then read it back to confirm it survived.

    The read-back is not defensive padding. The blob is repaired by a blind
    quote swap when the container loads it, and a payload that was accepted
    and corrupted surfaces much later, inside a build, as an error that names
    nothing.
    """
    path = _owned(code, principal)

    try:
        record = transform_store.save(code, path, body.source,
                                      author=principal.username)
    except transform_store.TransformError as e:
        raise HTTPException(400, str(e))

    warnings = []
    if record.get("discarded_build"):
        # Correct, but never silent: a model trained under a different
        # transform must not be applied under this one.
        warnings.append(
            "The trained model has been discarded. A model fitted before this "
            "transform cannot be applied with it, and the stored estimator "
            "does not fit in the update path. Rebuild to get a model that "
            "matches this code."
        )
    return TransformSaved(code=code, sha256=record["sha256"],
                          saved_at=record["saved_at"], warnings=warnings)


@router.delete("/ml-concepts/{code}/transform", response_model=TransformSaved)
def delete_transform(code: str,
                     principal: Principal = Depends(current_principal)) -> TransformSaved:
    """Remove the transform so the model builds on raw columns again."""
    path = _owned(code, principal)

    if transform_store.load(code) is None:
        raise HTTPException(404, f"{code} has no transform to remove")

    try:
        transform_store.clear(code, path)
    except transform_store.TransformError as e:
        raise HTTPException(400, str(e))

    return TransformSaved(code=code, sha256="", warnings=[
        "The transform has been removed. Builds will now use the raw columns."
    ])
