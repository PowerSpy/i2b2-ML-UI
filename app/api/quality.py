from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import current_principal
from app.core import quality, redact
from app.core.auth import Principal

router = APIRouter()


class Fact_Counts(BaseModel):
    total: int
    distinct: int
    # Exact repeats: same patient, concept, date and value. Repeated loads of
    # the same CSV produce these, and every count in the app counts them.
    duplicates: int


class Dataset(BaseModel):
    root: str
    # True for the bucket holding codes declared under more than one root.
    # Those facts belong to no single dataset and are not attributed to one.
    ambiguous: bool = False
    facts: int | None = None
    patients: int | None = None
    concepts: int | None = None


class Concept_Count(BaseModel):
    code: str
    facts: int | None = None
    patients: int | None = None


class Collision(BaseModel):
    code: str
    roots: int
    under: list[str]


class Overlap(BaseModel):
    left: str
    right: str
    shared: int | None = None


class Quality(BaseModel):
    facts: Fact_Counts
    # Facts whose concept code was never declared. The loader does not reject
    # them, so they sit in the table unreachable by any path-based selection.
    orphan_facts: int | None = None
    datasets: list[Dataset]
    concepts: list[Concept_Count]
    concepts_without_facts: list[str]
    colliding_codes: list[Collision]
    patient_overlap: list[Overlap]
    suppressed: list[str] = []
    suppression_note: str | None = None


# Counts that say something about how many people are involved.
#
# `patients` and `shared` are people directly. `facts` is here because a small
# fact count *bounds* the patient count: a dataset with three facts has at most
# three patients, so publishing it discloses that the population is below the
# threshold even though `patients` itself was withheld. That is complementary
# suppression across fields rather than within a group.
#
# `concepts` is deliberately not here. It counts concept codes - columns - and
# a dataset having one column says nothing about any person.
PATIENT_COUNTS = ("patients", "shared", "facts")


@router.get("/data-quality", response_model=Quality)
def data_quality(principal: Principal = Depends(current_principal)) -> Quality:
    """Whether the warehouse is healthy or quietly polluted.

    Read-only, and deliberately several queries rather than one: each answers a
    different way a load can go wrong, and a total that looks fine can hide any
    of them.

    Custodians see the raw numbers. Withholding a count of four orphan facts
    from the person whose job is to go and fix those four facts would make this
    page useless for its only purpose, and protect nothing they cannot already
    read through the loader.
    """
    report = quality.report()
    if not redact.applies_to(principal):
        return Quality(**report)

    withheld: list[str] = []

    def scrub(rows: list[dict]) -> list[dict]:
        out = []
        for row in rows:
            row = dict(row)
            for key in PATIENT_COUNTS:
                if key in row and redact.small(row[key]):
                    row[key] = None
                    withheld.append(key)
            out.append(row)
        return out

    report["datasets"] = scrub(report["datasets"])
    report["concepts"] = scrub(report["concepts"])
    report["patient_overlap"] = scrub(report["patient_overlap"])

    # An orphan count below the threshold is a handful of identifiable
    # patients sitting outside every path-based selection.
    if redact.small(report.get("orphan_facts")):
        report["orphan_facts"] = None
        withheld.append("orphan_facts")

    return Quality(**report, suppressed=sorted(set(withheld)),
                   suppression_note=redact.reason(withheld))
