from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import cohorts, db, ml_blob

router = APIRouter()

NOTE = (
    "Only positive predictions are written as facts. Absence of a fact means "
    "predicted-negative OR never-scored — the two are indistinguishable here."
)


class Predictions(BaseModel):
    code: str
    total: int
    scored: int | None = None
    patients: list[str]
    note: str = NOTE
    warnings: list[str] = []


@router.get("/predictions/{code}", response_model=Predictions)
def predictions(code: str, limit: int = 100, target_cohort: str | None = None) -> Predictions:
    try:
        db.check_code(code)
    except ValueError as e:
        raise HTTPException(400, str(e))

    total = int(db.scalar(
        "SELECT count(*) FROM i2b2demodata.observation_fact "
        f"WHERE concept_cd = '{code}';") or 0)
    rows = db.query(
        "SELECT patient_num, start_date FROM i2b2demodata.observation_fact "
        f"WHERE concept_cd = '{code}' ORDER BY patient_num LIMIT {int(limit)};")

    scored = None
    if target_cohort:
        match = next((c for c in cohorts.list_cohorts() if c["name"] == target_cohort), None)
        if match:
            scored = cohorts.live_size(match["id"])

    warnings = _missing_feature_warnings(code)
    return Predictions(code=code, total=total, scored=scored,
                       patients=[r["patient_num"] for r in rows], warnings=warnings)


def _missing_feature_warnings(code: str) -> list[str]:
    try:
        blob = ml_blob.load_blob(code)
    except (KeyError, ValueError):
        return []

    features = blob.get("feature_column_codes") or []
    if not features:
        return []

    present = {
        r["concept_cd"] for r in db.query(
            "SELECT DISTINCT concept_cd FROM i2b2demodata.observation_fact "
            "WHERE concept_cd IN ("
            + ", ".join(f"'{db.check_code(f)}'" for f in features) + ");"
        )
    }
    missing = [f for f in features if f not in present]
    if missing:
        return [f"{len(missing)} model feature(s) absent from the data and filled with 0: "
                + ", ".join(missing[:5]) + ("…" if len(missing) > 5 else "")]
    return []
