from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import dictionary

router = APIRouter()


class Level(BaseModel):
    value: str
    count: int
    # Whether the underlying value is a number. Integer-coded levels are the
    # common case here, and the synthetic frame has to reproduce the dtype or
    # every comparison in a transform behaves differently in dev.
    numeric: bool = False


class Column(BaseModel):
    code: str
    name: str | None = None
    kind: str
    # A code carrying both numeric and text rows pivots to NaN for the text
    # ones. The build never mentions it, so the dictionary does.
    mixed_valtype: bool = False

    patients_with_value: int | None = None
    fill_rate: float | None = None
    missing_rate: float | None = None
    n_distinct: int | None = None
    integer_like: bool = False

    # p01 and p99. Deliberately not the true extremes: a maximum is one
    # patient's value, exactly.
    low: float | None = None
    high: float | None = None
    p05: float | None = None
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    p95: float | None = None
    mean: float | None = None
    sd: float | None = None
    n_zero: int | None = None
    n_negative: int | None = None

    levels: list[Level] = []
    other_count: int = 0

    # Names the fields that were withheld, so a null is never ambiguous
    # between "small" and "not applicable".
    suppressed: list[str] = []
    reason: str | None = None


class Dictionary(BaseModel):
    scope: str
    note: str
    min_cell: int
    patients_in_scope: int | None = None
    columns: list[Column]
    basis: str


@router.get("/data-dictionary", response_model=Dictionary)
def data_dictionary(root: str | None = None) -> Dictionary:
    """Column shapes for a dataset root, or the whole warehouse.

    A browsing aid. For writing code against a specific model, the model-scoped
    version below is the one that matches what a build actually assembles.
    """
    try:
        return Dictionary(**dictionary.describe(dictionary.warehouse_scope(root)))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/ml-concepts/{code}/data-dictionary", response_model=Dictionary)
def model_data_dictionary(code: str) -> Dictionary:
    """The exact frame a build of this model would see.

    Its data paths minus its label paths, over its training cohorts - resolved
    the same way `create_data_label_codes` resolves them inside the container,
    so the column list matches the one the model is really fitted on.
    """
    try:
        return Dictionary(**dictionary.describe(dictionary.model_scope(code)))
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
