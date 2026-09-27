from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import current_principal
from app.core import audit, cohorts, db, ml_blob, redact
from app.core.auth import Principal
from app.core.config import settings

router = APIRouter()

NOTE = (
    "Only positive predictions are written as facts. Absence of a fact means "
    "predicted-negative OR never-scored — the two are indistinguishable here."
)


class Predictions(BaseModel):
    code: str
    total: int | None = None
    scored: int | None = None
    patients: list[str]
    note: str = NOTE
    warnings: list[str] = []
    # Named rather than left to be inferred from an empty list, because
    # "no patients were predicted positive" and "you may not see who they
    # are" are completely different facts about the model.
    suppressed: list[str] = []
    suppression_note: str | None = None


@router.get("/predictions/{code}", response_model=Predictions)
def predictions(
    code: str,
    limit: int = Query(100, ge=1, le=settings.max_prediction_rows),
    target_cohort: str | None = None,
    principal: Principal = Depends(current_principal),
) -> Predictions:
    """Who this model predicted positive.

    **Researchers never receive patient numbers here**, whatever the counts
    say. This is the one endpoint in the app that returns identifiers, and a
    per-patient prediction list is the most directly re-identifying payload it
    can produce - a positive prediction is itself a claim about a named person.
    """
    try:
        db.check_code(code)
    except ValueError as e:
        raise HTTPException(400, str(e))

    total = int(db.scalar(
        f"SELECT count(*) FROM {settings.db_schema}.observation_fact "
        f"WHERE concept_cd = '{code}';") or 0)
    rows = db.query(
        f"SELECT patient_num, start_date FROM {settings.db_schema}.observation_fact "
        f"WHERE concept_cd = '{code}' ORDER BY patient_num LIMIT {int(limit)};")

    scored = None
    if target_cohort:
        match = next((c for c in cohorts.list_cohorts() if c["name"] == target_cohort), None)
        if match:
            scored = cohorts.live_size(match["id"])

    warnings = _missing_feature_warnings(code)

    # The one event that answers "did anyone pull patient identifiers, when,
    # and how many". Counts only - the identifiers themselves are precisely
    # what audit's denylist keeps out.
    patients = [r["patient_num"] for r in rows]
    suppressed: list[str] = []

    if redact.applies_to(principal):
        # Unconditional, not cell-size dependent. A large cohort does not make
        # a named positive prediction less identifying.
        patients = []
        suppressed.append("patients")
        total, scored = redact.count(total), redact.count(scored)
        if total is None:
            suppressed.append("total")
        if scored is None and target_cohort:
            suppressed.append("scored")

    # The one event that answers "did anyone pull patient identifiers, when,
    # and how many". Counts only - the identifiers themselves are precisely
    # what audit's denylist keeps out.
    audit.event("patient_read", subject=code,
                rows_returned=len(patients), limit_requested=limit,
                total_available=total, withheld=bool(suppressed))

    note = NOTE
    if "patients" in suppressed:
        note = (NOTE + " Patient numbers are not shown to researcher accounts.")

    return Predictions(code=code, total=total, scored=scored,
                       patients=patients, warnings=warnings, note=note,
                       suppressed=suppressed,
                       suppression_note=redact.reason(
                           [s for s in suppressed if s != "patients"]))


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
            f"SELECT DISTINCT concept_cd FROM {settings.db_schema}.observation_fact "
            "WHERE concept_cd IN ("
            + ", ".join(f"'{db.check_code(f)}'" for f in features) + ");"
        )
    }
    missing = [f for f in features if f not in present]
    if missing:
        return [f"{len(missing)} model feature(s) absent from the data and filled with 0: "
                + ", ".join(missing[:5]) + ("…" if len(missing) > 5 else "")]
    return []
