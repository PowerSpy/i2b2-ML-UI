from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from app.api.deps import current_principal
from app.core import (audit, authz, cohorts, db, etl_api, ml_blob, redact,
                      spooler)
from app.core.auth import Principal
from app.core.config import settings

router = APIRouter()

# Custodian-only. These are collected on a second router so the policy lives in
# app/api/router.py, in one place a reviewer can read, rather than being spread
# across decorators in nine modules.
custodian_router = APIRouter()

JOB_COLUMNS = ("job_type", "status", "output", "error_stack",
               "started_on", "completed_on")


class Build_In(BaseModel):
    path: str

    @field_validator("path")
    @classmethod
    def _safe(cls, v: str) -> str:
        return db.check_path(v)


class Apply_In(BaseModel):
    target_patient_set: list[str]
    path: str
    prediction_event_paths: list[str] = []

    @field_validator("path")
    @classmethod
    def _safe(cls, v: str) -> str:
        return db.check_path(v)


class Job_Out(BaseModel):
    queued: bool
    message: str
    warnings: list[str] = []
    # The row this submission created. None when it could not be identified,
    # which the caller must treat as "unknown", never as "the newest job".
    job_id: int | None = None


def _max_job_id() -> int:
    return int(db.scalar(f"SELECT COALESCE(MAX(id), 0) FROM {settings.db_schema}.job;") or 0)


def _job_created_after(previous_max: int) -> int | None:
    """The job this submission created, identified by id rather than recency.

    The ETL's queue response carries no id, and reading "the newest row" after
    submitting is a race: the row may not exist yet, in which case the newest
    row is the *previous* job — often already COMPLETED, so the UI reports
    instant success for a build that never ran. Anchoring to the id seen before
    submitting makes that impossible; an unfinished insert yields None, which is
    honest, instead of someone else's job.
    """
    rows = db.query(
        f"SELECT id FROM {settings.db_schema}.job "
        f"WHERE id > {int(previous_max)} ORDER BY id ASC LIMIT 1;"
    )
    return int(rows[0]["id"]) if rows else None


class Job(BaseModel):
    id: int
    job_type: str | None = None
    status: str | None = None
    output: str | None = None
    error_stack: str | None = None
    started_on: str | None = None
    completed_on: str | None = None
    # Set when `output` or `error_stack` was withheld, so the UI can say the
    # detail exists and is not being shown - rather than rendering a blank
    # that reads as "this job said nothing".
    suppressed: list[str] = []
    suppression_note: str | None = None


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


def _assert_may_touch(principal: Principal, path: str) -> None:
    """Refuse a path this account does not own.

    This is the check the whole role split rests on. Submitting a job deletes
    every fact under `path` first (see _wipe_warning), and `path` is whatever
    the caller sent - so without this a researcher could wipe any subtree by
    naming it.
    """
    if authz.may_touch(principal, path=path):
        return

    owner = authz.owner_of_path(path)
    audit.event("authz_denied", subject=principal.username, status="error",
                path=path, reason="not the owner")
    raise HTTPException(
        403,
        f"{path} belongs to {owner}" if owner else
        f"no model at {path} is recorded as yours - submitting would delete "
        "every fact under that path, so only its owner or a custodian may.",
    )


def _assert_transform_can_run(path: str) -> None:
    """Refuse at the door when a transform build cannot possibly work.

    Following the doctrine already set a few lines above: name the fix rather
    than queue something that dies in a worker. A model with a transform built
    against a container without the hook does not error - it trains on the raw
    columns and reports success, which is the outcome worth the most trouble to
    prevent.
    """
    code = ml_blob.code_at_path(path)
    if not code:
        return
    ok, why = spooler.readiness(code)
    if not ok:
        raise HTTPException(409, why)


@router.post("/jobs/build", response_model=Job_Out)
def build(body: Build_In,
          principal: Principal = Depends(current_principal)) -> Job_Out:
    _assert_may_touch(principal, body.path)

    # Without this the job queues happily and then dies in the worker with
    # "'NoneType' object has no attribute 'replace'", which says nothing about
    # the actual problem: there is no model config at this path.
    if not ml_blob.has_config_at_path(body.path):
        raise HTTPException(
            409,
            f"no model config at {body.path} — define the model in step 3 first. "
            "(Folders in the concept tree are not models.)",
        )

    _assert_transform_can_run(body.path)

    before = _max_job_id()
    res = etl_api.post("/etl/job", json={
        "input": {"path": body.path},
        "jobType": "ml",
    })
    job_id = _job_created_after(before)
    # Recorded at submission, not completion: a job that strands at
    # PROCESSING leaves no other trace that it was ever asked for.
    audit.event("job_submitted", subject=body.path, job_type="build",
                job_id=job_id)
    return Job_Out(queued=True, message=str(res), job_id=job_id,
                   warnings=[_wipe_warning(body.path)])


@router.post("/jobs/apply", response_model=Job_Out)
def apply(body: Apply_In,
          principal: Principal = Depends(current_principal)) -> Job_Out:
    _assert_may_touch(principal, body.path)

    if not ml_blob.is_built_at_path(body.path):
        raise HTTPException(409, f"no trained model at {body.path} — build it first")

    # Apply runs the transform too, so the same prerequisites hold. The
    # container additionally refuses if the stored transform is not the one the
    # model was trained with; this only catches the case where it could not run
    # at all.
    _assert_transform_can_run(body.path)

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

    before = _max_job_id()
    res = etl_api.post("/etl/job", json={
        "input": {
            "path": body.path,
            "target_patient_set": body.target_patient_set,
            "prediction_event_paths": body.prediction_event_paths,
        },
        "jobType": "ml",
    })
    job_id = _job_created_after(before)
    audit.event("job_submitted", subject=body.path, job_type="apply",
                job_id=job_id, target_sets=len(body.target_patient_set))
    return Job_Out(queued=True, message=str(res), job_id=job_id,
                   warnings=[_wipe_warning(body.path)])


# The message a researcher gets instead of a stack trace. It has to be enough
# to act on, which for a job means: what failed, and who can see why.
TRACEBACK_WITHHELD = (
    "This job's output is not shown to researcher accounts. ETL tracebacks "
    "carry the failing SQL and sample rows from the data. A custodian can read "
    "the full output."
)

# The one exception, and the reason for it: a transform failure is the
# researcher's own code failing, and the message is written by this
# application rather than by the ETL. Withholding it would leave someone
# unable to debug the one thing they are responsible for.
TRANSFORM_MARKER = "TRANSFORM FAILED:"


def _redact_job(job: Job) -> Job:
    """Withhold ETL output, keeping the part that is the caller's own.

    This is the least obvious disclosure surface in the app. `error_stack`
    carries Python tracebacks out of the ETL container, and those include the
    SQL that failed and, when a load fails mid-row, the row - and `JobQueue.jsx`
    polls this endpoint every ten seconds.
    """
    withheld = []
    for field in ("output", "error_stack"):
        value = getattr(job, field)
        if not value:
            continue
        if TRANSFORM_MARKER in value:
            # Sliced from the marker to the end of *that line*, not the whole
            # line and not the rest of the text. A traceback that arrives on
            # one line would otherwise carry the container's SQL along with
            # the sentence this application wrote.
            tail = value[value.index(TRANSFORM_MARKER):]
            setattr(job, field, tail.splitlines()[0].strip())
            continue
        setattr(job, field, TRACEBACK_WITHHELD)
        withheld.append(field)

    job.suppressed = withheld
    if withheld:
        job.suppression_note = TRACEBACK_WITHHELD
    return job


@router.get("/jobs", response_model=list[Job])
def list_jobs(
    limit: int = Query(20, ge=1, le=settings.max_job_rows),
    principal: Principal = Depends(current_principal),
) -> list[Job]:
    rows = db.query(
        f"SELECT id, {', '.join(JOB_COLUMNS)} "
        f"FROM {settings.db_schema}.job ORDER BY id DESC LIMIT {int(limit)};"
    )
    jobs = [_row_to_job(r) for r in rows]
    if redact.applies_to(principal):
        jobs = [_redact_job(j) for j in jobs]
    return jobs


@custodian_router.post("/jobs/{job_id}/reset", response_model=Job_Out)
def reset_job(job_id: int) -> Job_Out:
    res = etl_api.post("/etl/update_job", json={
        "jobId": job_id, "pre": "PROCESSING", "post": "PENDING",
    })
    return Job_Out(queued=True, message=str(res))
