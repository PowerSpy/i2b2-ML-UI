from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import cohorts, etl_api, ml_blob
from app.core.config import settings

router = APIRouter()

CONCEPT_TYPE = "assertion"
HEADLINE = ["roc_auc", "pr_auc", "test_roc_auc"]
THRESHOLDED = ["accuracy", "precision", "recall", "f1", "specificity", "npv", "mcc",
               "balanced_accuracy"]
COUNTS = ["true_positive", "false_positive", "true_negative", "false_negative",
          "n_pos", "n_neg", "n_samples"]

class Blob_In(BaseModel):
    positive_patient_set: list[str]
    negative_patient_set: list[str]
    data_paths: list[str]
    label_paths: list[str]
    time_buffer: int = settings.ml_time_buffer
    sample_size_limit: int = settings.ml_sample_size_limit
    test_size: float = settings.ml_test_size
    random_seed: float = settings.ml_random_seed


class Ml_Concept_In(BaseModel):
    code: str
    path: str
    description: str
    blob: Blob_In


class Ml_Concept(BaseModel):
    code: str
    path: str
    description: str | None = None
    is_built: bool


class Ml_Concept_Out(BaseModel):
    code: str
    warnings: list[str] = []


class Metrics(BaseModel):
    headline: dict[str, float]
    thresholded: dict[str, float]
    counts: dict[str, float]
    features: list[str]
    build_time_sec: float | None = None
    threshold_note: str


@router.get("/ml-concepts", response_model=list[Ml_Concept])
def list_ml_concepts(path: str = settings.ml_root) -> list[Ml_Concept]:
    return [Ml_Concept(**c) for c in ml_blob.list_ml_concepts(path)]


@router.post("/ml-concepts", response_model=Ml_Concept_Out)
def create_ml_concept(body: Ml_Concept_In) -> Ml_Concept_Out:
    if "'" in body.description:
        raise HTTPException(400, "description cannot contain an apostrophe")

    known = {c["name"] for c in cohorts.list_cohorts()}
    unknown = sorted(
        set(body.blob.positive_patient_set + body.blob.negative_patient_set) - known
    )
    if unknown:
        raise HTTPException(400, f"unknown cohort(s): {', '.join(unknown)}")

    warnings = []
    overlap = sorted(set(body.blob.positive_patient_set) & set(body.blob.negative_patient_set))
    if overlap:
        warnings.append(
            f"cohort(s) {', '.join(overlap)} are in both classes; patients in both are "
            "dropped from both, not assigned to one"
        )
    if ml_blob.is_built(body.code):
        warnings.append("this replaces the existing trained model — no history is kept")

    payload = {
        "code": body.code,
        "path": body.path,
        "type": CONCEPT_TYPE,
        "description": body.description,
        "blob": body.blob.model_dump(),
    }
    etl_api.post("/etl/concepts", json=payload)
    return Ml_Concept_Out(code=body.code, warnings=warnings)


@router.get("/ml-concepts/{code}/config")
def ml_concept_config(code: str) -> dict:
    try:
        return ml_blob.strip_heavy(ml_blob.load_blob(code))
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/ml-concepts/{code}/metrics", response_model=Metrics)
def metrics(code: str) -> Metrics:
    try:
        blob = ml_blob.load_blob(code)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    if "serialized_model" not in blob:
        raise HTTPException(409, "model has not been built yet")

    def pick(keys):
        return {k: blob[k] for k in keys if isinstance(blob.get(k), (int, float))}

    return Metrics(
        headline=pick(HEADLINE),
        thresholded=pick(THRESHOLDED),
        counts=pick(COUNTS),
        features=blob.get("feature_column_codes", []),
        build_time_sec=blob.get("build_time_sec"),
        threshold_note=(
            "All metrics except roc_auc/pr_auc are reported at the F1-optimal threshold; "
            "the stored model predicts at 0.5."
        ),
    )
