import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.api.deps import current_principal
from app.core import (audit, authz, cohorts, db, etl_api, ml_blob, ml_registry,
                      redact, transform_store)
from app.core.auth import Principal
from app.core.config import settings

router = APIRouter()

# Custodian-only. These are collected on a second router so the policy lives in
# app/api/router.py, in one place a reviewer can read, rather than being spread
# across decorators in nine modules.
custodian_router = APIRouter()

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

    @field_validator("code")
    @classmethod
    def _safe_code(cls, v: str) -> str:
        # This becomes a concept_cd and is interpolated into SQL by ml_blob.
        return db.check_code(v)

    @field_validator("path")
    @classmethod
    def _safe_path(cls, v: str) -> str:
        # Never validated until now, despite flowing into _coded_path, into
        # ETL query params, and back out of the database into ml_blob's
        # queries. data_paths and label_paths were already checked; this was
        # the gap between them.
        return db.check_path(v)


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
    # Who created it, and whether the caller may build, apply, edit or delete
    # it. Sent so the frontend can render the right controls instead of
    # inferring a rule that would then drift from the server's.
    owner: str | None = None
    mine: bool = False


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
    # Nullable because a suppressed cell is null, never zero: a reader must
    # not be able to tell two patients from none.
    counts: dict[str, float | None]
    features: list[str]
    build_time_sec: float | None = None
    threshold_note: str
    model_type: str | None = None
    model_name: str | None = None
    clf_type: str | None = None
    hyperparameters: dict[str, list] = {}
    # Names the figures that were withheld, so a null is never ambiguous
    # between "too few patients", "not applicable" and "not loaded yet".
    suppressed: list[str] = []
    suppression_note: str | None = None


class Plots(BaseModel):
    images: dict[str, str]
    suppressed: list[str] = []
    suppression_note: str | None = None
    # Counts drawn into the plots, which are computed at the 0.5 cutoff the
    # stored model predicts at - not at the F1-optimal threshold the headline
    # metrics use. The two disagree, so they are kept apart deliberately.
    counts_at_half: dict[str, int | None] = {}
    note: str


@router.get("/ml-model-types", response_model=list[Model_Type])
def list_model_types() -> list[Model_Type]:
    try:
        return [Model_Type(**m) for m in ml_registry.list_model_types()]
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.get("/ml-concepts", response_model=list[Ml_Concept])
def list_ml_concepts(
    path: str = settings.ml_root,
    principal: Principal = Depends(current_principal),
) -> list[Ml_Concept]:
    owners = authz.owners()
    out = []
    for c in ml_blob.list_ml_concepts(path):
        owner = owners.get(c["code"])
        out.append(Ml_Concept(
            **c, owner=owner,
            mine=authz.may_touch(principal, code=c["code"]),
        ))
    return out


@router.post("/ml-concepts", response_model=Ml_Concept_Out)
def create_ml_concept(
    body: Ml_Concept_In,
    principal: Principal = Depends(current_principal),
) -> Ml_Concept_Out:
    if "'" in body.description:
        raise HTTPException(400, "description cannot contain an apostrophe")

    # A researcher's models live under their own namespace, and re-saving
    # someone else's is not an edit they may make. Both checks run before
    # anything is written.
    if principal.is_researcher:
        ns = authz.researcher_namespace(principal.username)
        if not authz.in_namespace(body.path, ns):
            raise HTTPException(
                403,
                f"researchers may only create models under {ns} - a build "
                "deletes every fact under the path it is given, so the path "
                "has to be one you own",
            )
        if ml_blob.exists(body.code) and not authz.may_touch(principal, code=body.code):
            raise HTTPException(
                403,
                f"{body.code} belongs to {authz.owner_of(body.code) or 'someone else'}",
            )

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

    # Read once, before the write. Asking afterwards always answers True, and
    # this is also the branch condition - two round trips for one fact.
    existed = ml_blob.exists(body.code)

    if existed:
        # The form builds its blob from scratch and this endpoint writes it
        # whole, so without carrying these four keys across, changing the
        # algorithm or a cohort would **silently delete the model's feature
        # transform** - and the next build would train on raw columns and
        # report success.
        #
        # Done here rather than in the form, so a future form that has never
        # heard of transforms still cannot destroy one.
        transform_store.carry_forward(blob, ml_blob.load_blob_light(body.code))
        if transform_store.SOURCE in blob:
            warnings.append(
                "this model has a feature transform; it has been kept, and the "
                "rebuild will run it"
            )

    if existed:
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
    authz.record_owner(body.code, body.path, principal.id)
    audit.event("model_saved", subject=body.code, path=body.path,
                model_type=body.blob.model_type, replaced=existed,
                owner=principal.username, warning_count=len(warnings))
    return Ml_Concept_Out(code=body.code, warnings=warnings)


@router.delete("/ml-concepts/{code}", response_model=Ml_Concept_Deleted)
def delete_ml_concept(
    code: str,
    principal: Principal = Depends(current_principal),
) -> Ml_Concept_Deleted:
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

    if not authz.may_touch(principal, code=code):
        owner = authz.owner_of(code)
        raise HTTPException(
            403,
            f"{code} belongs to {owner}" if owner else
            f"{code} has no recorded owner, so only a custodian may delete it",
        )

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

    audit.event("model_deleted", subject=code, path=match["path"],
                status="ok" if gone else "error", was_built=was_built)
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
def metrics(code: str,
            principal: Principal = Depends(current_principal)) -> Metrics:
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

    raw_counts = pick(COUNTS)
    suppressed: list[str] = []
    if redact.applies_to(principal):
        # The confusion cells and their totals go as one group. Suppressing a
        # single small cell while publishing the others and n_samples gives it
        # straight back by subtraction.
        raw_counts, suppressed = redact.counts(raw_counts)

    return Metrics(
        headline=pick(HEADLINE),
        thresholded=pick(THRESHOLDED),
        counts=raw_counts,
        suppressed=suppressed,
        suppression_note=redact.reason(suppressed),
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
def plots(code: str,
          principal: Principal = Depends(current_principal)) -> Plots:
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
    images = ml_blob.plots(blob)
    suppressed: list[str] = []
    if redact.applies_to(principal):
        counts, suppressed = redact.plot_counts(counts)
        if suppressed:
            # The confusion-matrix figure has the raw counts *drawn on it*
            # (model_plots.py:103 - "heatmap with raw counts"). Redacting the
            # numbers here and serving that PNG would disclose them anyway, so
            # the image goes with them. The other figures are curves over the
            # whole test set and carry no cell.
            images = {k: v for k, v in images.items()
                      if "confusion" not in k.lower()}
            suppressed.append("plot_confusion_matrix")

    return Plots(
        images=images,
        counts_at_half=counts,
        suppressed=sorted(set(suppressed)),
        suppression_note=redact.reason(suppressed),
        note=(
            "Plots score the test set at the 0.5 cutoff the stored model predicts at, "
            "so these counts differ from the headline metrics, which use the F1-optimal "
            "threshold."
        ),
    )
