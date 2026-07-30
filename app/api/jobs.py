from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import cohorts, db, etl_api, ml_blob

router = APIRouter()

JOB_COLUMNS = ("job_type", "status", "output", "error_stack",
               "started_on", "completed_on")


class Build_In(BaseModel):
    path: str


class Apply_In(BaseModel):
    target_patient_set: list[str]
    path: str
    prediction_event_paths: list[str] = []


class Job_Out(BaseModel):
    queued: bool
    message: str
    warnings: list[str] = []


class Job(BaseModel):
    id: int
    job_type: str | None = None
    status: str | None = None
    output: str | None = None
    error_stack: str | None = None
    started_on: str | None = None
    completed_on: str | None = None


def _row_to_job(row: dict) -> Job:
    fields = {}
    for column in JOB_COLUMNS:
        value = row[column]
        fields[column] = value or None
    return Job(id=int(row["id"]), **fields)


def _wipe_warning(path: str) -> str:
    return (
        f"submitting deletes every existing fact under {path} before running "
        "(jobOrchestrator.py:63) — this happens on builds too"
    )


@router.post("/jobs/build", response_model=Job_Out)
def build(body: Build_In) -> Job_Out:
    res = etl_api.post("/etl/job", json={
        "input": {"path": body.path},
        "jobType": "ml",
    })
    return Job_Out(queued=True, message=str(res), warnings=[_wipe_warning(body.path)])


@router.post("/jobs/apply", response_model=Job_Out)
def apply(body: Apply_In) -> Job_Out:
    if not ml_blob.is_built_at_path(body.path):
        raise HTTPException(409, f"no trained model at {body.path} — build it first")

    known = {c["name"] for c in cohorts.list_cohorts()}
    unknown = sorted(set(body.target_patient_set) - known)
    if unknown:
        raise HTTPException(400, f"unknown cohort(s): {', '.join(unknown)}")

    if not body.prediction_event_paths:
        raise HTTPException(
            400,
            "prediction_event_paths cannot be empty — the engine joins it into a "
            "WHERE clause with no fallback, producing invalid SQL "
            "(build_model_ML_helper.py:173)",
        )

    res = etl_api.post("/etl/job", json={
        "input": {
            "path": body.path,
            "target_patient_set": body.target_patient_set,
            "prediction_event_paths": body.prediction_event_paths,
        },
        "jobType": "ml",
    })
    return Job_Out(queued=True, message=str(res), warnings=[_wipe_warning(body.path)])


@router.get("/jobs", response_model=list[Job])
def list_jobs(limit: int = 20) -> list[Job]:
    rows = db.query(
        f"SELECT id, {', '.join(JOB_COLUMNS)} "
        f"FROM i2b2demodata.job ORDER BY id DESC LIMIT {int(limit)};"
    )
    return [_row_to_job(r) for r in rows]


@router.post("/jobs/{job_id}/reset", response_model=Job_Out)
def reset_job(job_id: int) -> Job_Out:
    res = etl_api.post("/etl/update_job", json={
        "jobId": job_id, "pre": "PROCESSING", "post": "PENDING",
    })
    return Job_Out(queued=True, message=str(res))
