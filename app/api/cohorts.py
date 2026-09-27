from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import current_principal
from app.core import audit, cohorts, redact
from app.core.auth import Principal

router = APIRouter()

# Custodian-only. These are collected on a second router so the policy lives in
# app/api/router.py, in one place a reviewer can read, rather than being spread
# across decorators in nine modules.
custodian_router = APIRouter()


class Cohort(BaseModel):
    id: int
    name: str
    # Nullable: a cohort of four people is four identifiable people, and a
    # zero here would read as "empty" rather than "withheld".
    size: int | None = None
    # Members that still have facts. Differs from `size` after a reload.
    live: int | None = 0
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
    size: int | None = None
    live: int | None = None
    stale: bool
    suppressed: list[str] = []
    suppression_note: str | None = None


def _redact_cohort(c: dict, hide: bool) -> dict:
    """Sizes small enough to identify the members, withheld.

    `stale` and `duplicate` survive deliberately. They are properties of the
    cohort rather than counts of people, and they are exactly what a researcher
    needs in order to not train a model on the wrong population.
    """
    if not hide:
        return c
    return {**c, "size": redact.count(c.get("size")),
            "live": redact.count(c.get("live"))}


@router.get("/cohorts", response_model=list[Cohort])
def list_cohorts(principal: Principal = Depends(current_principal)) -> list[Cohort]:
    hide = redact.applies_to(principal)
    return [Cohort(**_redact_cohort(c, hide)) for c in cohorts.list_cohorts()]


@custodian_router.post("/cohorts", response_model=Cohort)
def create_cohort(body: Cohort_In) -> Cohort:
    try:
        cohort_id = cohorts.create_cohort(body.name, body.concept_code)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, f"cohort creation failed: {e}")

    audit.event("cohort_created", subject=body.name,
                cohort_id=cohort_id, concept_code=body.concept_code)

    for c in cohorts.list_cohorts():
        if c["id"] == cohort_id:
            return Cohort(**c)
    raise HTTPException(502, f"cohort {cohort_id} was created but is not listed")


@custodian_router.delete("/cohorts", response_model=Cohort_Delete)
def wipe_cohorts() -> Cohort_Delete:
    try:
        deleted = cohorts.wipe_cohorts()
        audit.event("cohort_deleted", subject="*all*", deleted=deleted)
        return Cohort_Delete(deleted=deleted)
    except RuntimeError as e:
        raise HTTPException(502, f"cohort wipe failed: {e}")


@custodian_router.delete("/cohorts/{cohort_id}", response_model=Cohort_Delete)
def delete_cohort(cohort_id: int) -> Cohort_Delete:
    try:
        deleted = cohorts.delete_cohorts([cohort_id])
        audit.event("cohort_deleted", subject=str(cohort_id), deleted=deleted)
        return Cohort_Delete(deleted=deleted)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(502, f"cohort delete failed: {e}")


class Cohort_Definition(BaseModel):
    id: int
    # False when nothing records the concept behind the set. Never a guess:
    # the app's own cohorts carry a placeholder item_key that names an
    # unrelated diagnosis, and reporting it would be worse than silence.
    recorded: bool
    concept_path: str | None = None
    concept_code: str | None = None
    query_name: str | None = None
    master_id: int | None = None
    created: str | None = None
    source: str | None = None
    note: str


@router.get("/cohorts/{cohort_id}/definition", response_model=Cohort_Definition)
def cohort_definition(cohort_id: int) -> Cohort_Definition:
    """The concept a cohort was built from, where that was recorded at all."""
    if not any(c["id"] == cohort_id for c in cohorts.list_cohorts()):
        raise HTTPException(404, f"no cohort with id {cohort_id}")
    return Cohort_Definition(**cohorts.cohort_definition(cohort_id))


@router.get("/cohorts/{cohort_id}/size", response_model=Cohort_Size)
def cohort_size(cohort_id: int,
                principal: Principal = Depends(current_principal)) -> Cohort_Size:
    """Kept for callers that ask about one cohort; /cohorts now carries this
    for every row, so the UI no longer needs a request per cohort."""
    match = next((c for c in cohorts.list_cohorts() if c["id"] == cohort_id), None)
    if match is None:
        raise HTTPException(404, f"no cohort with id {cohort_id}")

    row = _redact_cohort(match, redact.applies_to(principal))
    withheld = [k for k in ("size", "live") if row.get(k) is None]
    return Cohort_Size(id=cohort_id, size=row["size"], live=row["live"],
                       stale=match["stale"], suppressed=withheld,
                       suppression_note=redact.reason(withheld))
