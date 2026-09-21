from fastapi import APIRouter
from pydantic import BaseModel

from app.core import quality

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
    facts: int
    patients: int
    concepts: int


class Concept_Count(BaseModel):
    code: str
    facts: int
    patients: int


class Collision(BaseModel):
    code: str
    roots: int
    under: list[str]


class Overlap(BaseModel):
    left: str
    right: str
    shared: int


class Quality(BaseModel):
    facts: Fact_Counts
    # Facts whose concept code was never declared. The loader does not reject
    # them, so they sit in the table unreachable by any path-based selection.
    orphan_facts: int
    datasets: list[Dataset]
    concepts: list[Concept_Count]
    concepts_without_facts: list[str]
    colliding_codes: list[Collision]
    patient_overlap: list[Overlap]


@router.get("/data-quality", response_model=Quality)
def data_quality() -> Quality:
    """Whether the warehouse is healthy or quietly polluted.

    Read-only, and deliberately several queries rather than one: each answers a
    different way a load can go wrong, and a total that looks fine can hide any
    of them.
    """
    return Quality(**quality.report())
