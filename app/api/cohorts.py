from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import cohorts

router = APIRouter()


class Cohort(BaseModel):
    id: int
    name: str
    size: int
    # Members that still have facts. Differs from `size` after a reload.
    live: int = 0
    stale: bool = False
    # Another patient set shares this name. The build engine unions same-named
    # sets rather than picking one, so this is a correctness problem, not cosmetic.
    duplicate: bool = False


class Cohort_In(BaseModel):
    name: str
    concept_code: str


class Cohort_Delete(BaseModel):
    deleted: int


class Cohort_Size(BaseModel):
    id: int
    size: int
    live: int
    stale: bool


@router.get("/cohorts", response_model=list[Cohort])
def list_cohorts() -> list[Cohort]:
    return [Cohort(**c) for c in cohorts.list_cohorts()]


@router.post("/cohorts", response_model=Cohort)
def create_cohort(body: Cohort_In) -> Cohort:
    try:
        cohort_id = cohorts.create_cohort(body.name, body.concept_code)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, f"cohort creation failed: {e}")

    for c in cohorts.list_cohorts():
        if c["id"] == cohort_id:
            return Cohort(**c)
    raise HTTPException(502, f"cohort {cohort_id} was created but is not listed")


@router.delete("/cohorts", response_model=Cohort_Delete)
def wipe_cohorts() -> Cohort_Delete:
    try:
        return Cohort_Delete(deleted=cohorts.wipe_cohorts())
    except RuntimeError as e:
        raise HTTPException(502, f"cohort wipe failed: {e}")


@router.delete("/cohorts/{cohort_id}", response_model=Cohort_Delete)
def delete_cohort(cohort_id: int) -> Cohort_Delete:
    try:
        return Cohort_Delete(deleted=cohorts.delete_cohorts([cohort_id]))
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(502, f"cohort delete failed: {e}")


@router.get("/cohorts/{cohort_id}/size", response_model=Cohort_Size)
def cohort_size(cohort_id: int) -> Cohort_Size:
    """Kept for callers that ask about one cohort; /cohorts now carries this
    for every row, so the UI no longer needs a request per cohort."""
    match = next((c for c in cohorts.list_cohorts() if c["id"] == cohort_id), None)
    if match is None:
        raise HTTPException(404, f"no cohort with id {cohort_id}")

    return Cohort_Size(id=cohort_id, size=match["size"], live=match["live"],
                       stale=match["stale"])
