import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.core import cohorts, etl_api, ml_blob, ml_registry
from app.core.config import settings

router = APIRouter()

CONCEPT_TYPE = "assertion"


def _coded_path(path: str) -> str:
    """/ML/Foo/bar -> \\ML\\Foo\\bar\\ — how concept_path is stored."""
    return "\\" + path.strip("/").replace("/", "\\") + "\\"
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
    # Read by apply_build_model_ml.py as blob["model_type"] / blob["hyperparameters"]
    # and passed to the registry's build_model(). Values in the override grid are
    # lists because they replace entries in a GridSearchCV param grid; a bare
    # scalar makes the search iterate the value itself.
    model_type: str = "logistic"
    hyperparameters: dict[str, list] = {}
    time_buffer: int = settings.ml_time_buffer
    sample_size_limit: int = settings.ml_sample_size_limit
    test_size: float = settings.ml_test_size
    random_seed: float = settings.ml_random_seed

    @field_validator("model_type")
    @classmethod
    def _known_model(cls, v: str) -> str:
        v = v.lower()
        # build_model() falls back to logistic regression for an unknown key
        # without raising, so an unchecked typo here trains the wrong model and
        # reports success. Reject it at the edge instead.
        known = ml_registry.known_keys()
        if v not in known:
            raise ValueError(f"unknown model_type {v!r}; known: {', '.join(sorted(known))}")
        return v

    @field_validator("hyperparameters")
    @classmethod
    def _grid_keys(cls, v: dict[str, list]) -> dict[str, list]:
        bad = sorted(k for k in v if not k.startswith(ml_registry.GRID_PREFIXES))
        if bad:
            raise ValueError(
                f"hyperparameter key(s) {', '.join(bad)} must start with "
                f"{' or '.join(ml_registry.GRID_PREFIXES)} to match a grid entry"
            )
        empty = sorted(k for k, vals in v.items() if not vals)
        if empty:
            raise ValueError(f"hyperparameter key(s) {', '.join(empty)} have no values")
        # The ETL stores the blob as a Python repr and later repairs it into
        # JSON by swapping quote characters. None survives that intact and is
        # not valid JSON, so one null here makes the whole blob unparseable and
        # the build dies with "Expecting value: line 1 column N". Omit the key
        # instead — the model's default grid for it still applies.
        nulls = sorted(k for k, vals in v.items() if any(x is None for x in vals))
        if nulls:
            raise ValueError(
                f"hyperparameter key(s) {', '.join(nulls)} contain null, which "
                "corrupts the stored blob — omit the key to use the model's default"
            )
        return v


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
    model_type: str | None = None
    # The estimator class actually fitted, recorded at build time. Only set on
    # models built since the registry patch; older ones report None.
    clf_type: str | None = None
    # Whether the features this model was trained on still have facts. None when
    # unknown (not built, or built before feature codes were recorded). False
    # means the model is trained but its data is gone — applying it scores every
    # patient off zero-filled columns.
    features_present: bool | None = None


class Model_Field(BaseModel):
    id: str
    label: str
    grid_key: str | None = None
    min: float
    max: float
    default: float | None = None
    allow_blank: bool = False


class Model_Type(BaseModel):
    key: str
    name: str
    note: str = ""
    fields: list[Model_Field] = []


class Ml_Concept_Out(BaseModel):
    code: str
    warnings: list[str] = []


class Ml_Concept_Deleted(BaseModel):
    code: str
    deleted: bool
    warnings: list[str] = []


class Metrics(BaseModel):
    headline: dict[str, float]
    thresholded: dict[str, float]
    counts: dict[str, float]
    features: list[str]
    build_time_sec: float | None = None
    threshold_note: str
    model_type: str | None = None
    model_name: str | None = None
    clf_type: str | None = None
    hyperparameters: dict[str, list] = {}


class Plots(BaseModel):
    images: dict[str, str]
    # Counts drawn into the plots, which are computed at the 0.5 cutoff the
    # stored model predicts at - not at the F1-optimal threshold the headline
    # metrics use. The two disagree, so they are kept apart deliberately.
    counts_at_half: dict[str, int] = {}
    note: str


@router.get("/ml-model-types", response_model=list[Model_Type])
def list_model_types() -> list[Model_Type]:
    try:
        return [Model_Type(**m) for m in ml_registry.list_model_types()]
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.get("/ml-concepts", response_model=list[Ml_Concept])
def list_ml_concepts(path: str = settings.ml_root) -> list[Ml_Concept]:
    return [Ml_Concept(**c) for c in ml_blob.list_ml_concepts(path)]


@router.post("/ml-concepts", response_model=Ml_Concept_Out)
def create_ml_concept(body: Ml_Concept_In) -> Ml_Concept_Out:
    if "'" in body.description:
        raise HTTPException(400, "description cannot contain an apostrophe")

    all_cohorts = cohorts.list_cohorts()
    referenced = set(body.blob.positive_patient_set + body.blob.negative_patient_set)

    unknown = sorted(referenced - {c["name"] for c in all_cohorts})
    if unknown:
        raise HTTPException(400, f"unknown cohort(s): {', '.join(unknown)}")

    # The engine resolves a cohort name to every result_instance_id that carries
    # it and unions them, so an ambiguous name does not pick one set - it trains
    # on all of them at once, silently.
    ambiguous = sorted(referenced & {c["name"] for c in all_cohorts if c["duplicate"]})
    if ambiguous:
        raise HTTPException(
            400,
            f"cohort name(s) {', '.join(ambiguous)} refer to more than one patient set. "
            "Training resolves a name to every matching set and unions them, so the "
            "model would be trained on a population you did not choose. Delete the "
            "duplicates in step 2, keeping the one you want.",
        )

    stale = sorted(
        c["name"] for c in all_cohorts if c["name"] in referenced and c["stale"]
    )

    # Catch the misconfiguration that otherwise surfaces only after a full
    # training run, as "All the N fits failed ... The target y needs to have
    # more than 1 class" from inside imblearn - a message that names neither
    # the concept nor the path responsible.
    stray = ml_blob.assertion_features(body.blob.data_paths, body.blob.label_paths)
    if stray:
        raise HTTPException(
            400,
            f"data paths pull in assertion concept(s) {', '.join(stray)} as features. "
            "Assertions carry no value, so the build fails partway through with an "
            "unrelated-looking error. Either narrow the data paths, or widen the "
            "label paths to cover them.",
        )

    warnings = []
    overlap = sorted(set(body.blob.positive_patient_set) & set(body.blob.negative_patient_set))
    if overlap:
        warnings.append(
            f"cohort(s) {', '.join(overlap)} are in both classes; patients in both are "
            "dropped from both, not assigned to one"
        )
    if stale:
        warnings.append(
            f"cohort(s) {', '.join(stale)} contain patients that no longer have facts; "
            "the model will train on fewer patients than the cohort size suggests"
        )
    if ml_blob.is_built(body.code):
        warnings.append("this replaces the existing trained model — no history is kept")

    blob = body.blob.model_dump()

    if ml_blob.exists(body.code):
        # POST on an existing code answers 200 and changes nothing, so a
        # re-save would silently keep the old algorithm while reporting
        # success. The update path is a PUT that takes the blob as a query
        # parameter, not in the body (concept_API.py:138).
        etl_api.put(
            "/etl/concepts",
            params={"cpath": _coded_path(body.path), "blob": json.dumps(blob)},
        )
    else:
        etl_api.post("/etl/concepts", json={
            "code": body.code,
            "path": body.path,
            "type": CONCEPT_TYPE,
            "description": body.description,
            "blob": blob,
        })
    return Ml_Concept_Out(code=body.code, warnings=warnings)


@router.delete("/ml-concepts/{code}", response_model=Ml_Concept_Deleted)
def delete_ml_concept(code: str) -> Ml_Concept_Deleted:
    """Remove one model, instead of wiping every concept to be rid of it.

    Until this existed the only removal path was `delete concept`, which
    truncates the whole concept table and takes every other model and every
    loaded dataset with it. The ETL's own endpoint deletes a single concept by
    path, so this is a thin pass-through — with the result read back, because
    that endpoint answers 200 whether or not the row went away.
    """
    match = next(
        (c for c in ml_blob.list_ml_concepts(settings.ml_root) if c["code"] == code),
        None,
    )
    if match is None:
        raise HTTPException(404, f"no model with code {code!r}")

    was_built = match.get("is_built", False)
    etl_api.delete("/etl/concepts", params={"cpath": _coded_path(match["path"])})

    gone = not ml_blob.exists(code)
    warnings = []
    if not gone:
        warnings.append(
            "the ETL reported success but the concept is still present — it was "
            "not deleted, despite the 200"
        )
    if gone and was_built:
        warnings.append("the trained model went with it; there is no history and no undo")
    # Predictions are ordinary facts under their own concept code, so removing
    # the model concept leaves them behind, now pointing at nothing.
    if gone:
        warnings.append(
            f"any prediction facts written under {code} remain in observation_fact "
            "and no longer have a model behind them"
        )

    return Ml_Concept_Deleted(code=code, deleted=gone, warnings=warnings)


@router.get("/ml-concepts/{code}/config")
def ml_concept_config(code: str) -> dict:
    try:
        return ml_blob.load_blob_light(code)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/ml-concepts/{code}/metrics", response_model=Metrics)
def metrics(code: str) -> Metrics:
    try:
        # Trimmed: the metrics are ~1 KB of a blob that reaches 600 KB once the
        # serialized model and plot images are in it.
        blob = ml_blob.load_blob_light(code)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    # serialized_model is one of the keys stripped above, so built-ness is
    # asked of the database rather than inferred from what came back.
    if not ml_blob.is_built(code):
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
        model_type=blob.get("model_type"),
        model_name=blob.get("model_name"),
        clf_type=blob.get("clf_type"),
        hyperparameters=blob.get("hyperparameters") or {},
    )


@router.get("/ml-concepts/{code}/plots", response_model=Plots)
def plots(code: str) -> Plots:
    try:
        blob = ml_blob.load_blob(code)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    if "serialized_model" not in blob:
        raise HTTPException(409, "model has not been built yet")

    counts = {
        k.removeprefix("confusion_"): int(blob[k])
        for k in ("confusion_tp", "confusion_fp", "confusion_tn", "confusion_fn")
        if isinstance(blob.get(k), (int, float))
    }
    return Plots(
        images=ml_blob.plots(blob),
        counts_at_half=counts,
        note=(
            "Plots score the test set at the 0.5 cutoff the stored model predicts at, "
            "so these counts differ from the headline metrics, which use the F1-optimal "
            "threshold."
        ),
    )
