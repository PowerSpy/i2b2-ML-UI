import ast
import json

from app.core.config import settings
from app.core.db import check_code, check_path, query, scalar


def load_blob(code: str) -> dict:
    check_code(code)
    raw = scalar(
        f"SELECT concept_blob FROM {settings.db_schema}.concept_dimension "
        f"WHERE concept_cd = '{code}';"
    )
    if raw is None:
        raise KeyError(f"no concept with code {code!r}")
    if not raw.strip():
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # A blob registered through /etl/concepts is stored as a Python repr, not
    # JSON. literal_eval reads that directly, which matters for None/True/False
    # — the platform's own repair is a blind "'" -> '"' swap, and that leaves a
    # bare None in place to fail the parse.
    try:
        parsed = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        # Fall back to the platform's own repair, so anything it can read here
        # stays readable.
        return json.loads(raw.replace("'", '"'))

    if not isinstance(parsed, dict):
        raise ValueError(f"concept blob is a {type(parsed).__name__}, not an object")
    return parsed


def load_blob_light(code: str) -> dict:
    """The blob without the payload that dwarfs it.

    A built blob is mostly one serialized model and five base64 plot PNGs -
    611 KB on a verified random forest, of which the metrics are 1.2 KB. Reading
    that to show six numbers meant pulling the whole thing through `psql --csv`
    over `docker exec` and discarding 99.8% of it in Python.

    The trim happens in the database instead. Falls back to the full read when
    the blob is not valid JSON, which is the case for a config that has been
    registered but never built - those are small, so nothing is lost.
    """
    check_code(code)
    strip = " - ".join(f"'{k}'" for k in HEAVY)
    try:
        raw = scalar(
            "SELECT (concept_blob::jsonb "
            f"  - {strip} "
            "  - ARRAY(SELECT jsonb_object_keys(concept_blob::jsonb) "
            f"          WHERE jsonb_object_keys LIKE '{PLOT_PREFIX}%'))::text "
            f"FROM {settings.db_schema}.concept_dimension "
            f"WHERE concept_cd = '{code}';"
        )
    except RuntimeError:
        return strip_heavy(load_blob(code))

    if raw is None:
        raise KeyError(f"no concept with code {code!r}")
    if not raw.strip():
        return {}
    return json.loads(raw)


def exists(code: str) -> bool:
    check_code(code)
    hit = scalar(
        f"SELECT 1 FROM {settings.db_schema}.concept_dimension "
        f"WHERE concept_cd = '{code}';"
    )
    return hit is not None


def is_built(code: str) -> bool:
    check_code(code)
    hit = scalar(
        f"SELECT 1 FROM {settings.db_schema}.concept_dimension "
        f"WHERE concept_cd = '{code}' AND concept_blob LIKE '%serialized_model%';"
    )
    return hit is not None


def is_built_at_path(path: str) -> bool:
    check_path(path)
    like = path.strip("/").replace("/", "\\\\")
    hit = scalar(
        f"SELECT 1 FROM {settings.db_schema}.concept_dimension "
        f"WHERE concept_path LIKE '\\\\{like}\\\\%' "
        "AND concept_blob LIKE '%serialized_model%';"
    )
    return hit is not None


# Base64 plot PNGs run ~20-30 KB each and there are up to five of them, so a
# built blob is ~100 KB before the serialized model. Everything here is pulled
# through `psql --csv` over `docker exec`, so anything that does not need the
# images must not carry them.
HEAVY = ("serialized_model", "packages")
PLOT_PREFIX = "plot_"


def strip_heavy(blob: dict) -> dict:
    return {
        k: v for k, v in blob.items()
        if k not in HEAVY and not k.startswith(PLOT_PREFIX)
    }


def plots(blob: dict) -> dict:
    return {k: v for k, v in blob.items() if k.startswith(PLOT_PREFIX)}


# Pulls one scalar out of the blob text without parsing it. Stored blobs are
# usually JSON (double-quoted) but a freshly registered one can still be a
# Python repr with single quotes, so both are matched. Cheaper than loading
# every blob in the list - a built one can reach 1 MB.
def _blob_field(column: str, field: str) -> str:
    return (
        f"substring({column} from "
        f"'[\"'']{field}[\"'']\\s*:\\s*[\"'']([^\"'']+)[\"'']')"
    )


def _prefix_clause(column: str, paths: list[str]) -> str:
    """OR of prefix matches, mirroring how the build engine resolves paths."""
    parts = []
    for p in paths:
        check_path(p)
        like = p.strip("/").replace("/", "\\\\")
        parts.append(f"{column} LIKE '\\\\{like}\\\\%'")
    return " OR ".join(parts)


def assertion_features(data_paths: list[str], label_paths: list[str]) -> list[str]:
    """Assertion concepts that would be fed in as model features.

    The build engine resolves both path sets to concept codes and subtracts the
    label codes from the data codes (build_model_ML_helper.create_data_label_codes),
    so data paths that fully contain the label subtree are harmless. What is not
    harmless is a data path that pulls in an assertion the label paths do not
    cover: assertions carry no numeric value, so the column arrives empty and
    the run dies deep inside the pipeline with "The target y needs to have more
    than 1 class" - which names neither the concept nor the path that caused it.

    Returns the offending codes so the caller can say which ones.
    """
    if not data_paths:
        return []

    data_clause = _prefix_clause("concept_path", data_paths)
    sql = (
        "SELECT concept_cd "
        f"FROM {settings.db_schema}.concept_dimension "
        f"WHERE ({data_clause}) AND concept_type = 'assertion'"
    )
    if label_paths:
        label_clause = _prefix_clause("concept_path", label_paths)
        sql += (
            " AND concept_cd NOT IN ("
            "SELECT concept_cd "
            f"FROM {settings.db_schema}.concept_dimension "
            f"WHERE {label_clause})"
        )
    rows = query(sql + " ORDER BY concept_cd;")
    return [r["concept_cd"] for r in rows]


def has_config_at_path(path: str) -> bool:
    check_path(path)
    like = path.strip("/").replace("/", "\\\\")
    hit = scalar(
        f"SELECT 1 FROM {settings.db_schema}.concept_dimension "
        f"WHERE concept_path LIKE '\\\\{like}\\\\%' "
        "AND concept_blob IS NOT NULL AND concept_blob <> '';"
    )
    return hit is not None


def list_ml_concepts(path_prefix: str) -> list[dict]:
    check_path(path_prefix)
    like = path_prefix.strip("/").replace("/", "\\\\")
    # The blob is what makes a concept a model. Everything under /ML also
    # includes the tree's folder nodes (/ML itself, /ML/HeartDisease), which
    # carry a NULL blob — listing those offers the user something that looks
    # selectable but has no config, and building one dies inside the engine
    # with "'NoneType' object has no attribute 'replace'".
    rows = query(
        "SELECT concept_cd, concept_path, name_char, "
        "  (concept_blob LIKE '%serialized_model%') AS built, "
        f"  {_blob_field('concept_blob', 'model_type')} AS model_type, "
        f"  {_blob_field('concept_blob', 'clf_type')} AS clf_type, "
        "  substring(concept_blob from "
        "    '\"feature_column_codes\"\\s*:\\s*\\[([^\\]]*)\\]') AS feature_codes "
        f"FROM {settings.db_schema}.concept_dimension "
        f"WHERE concept_path LIKE '\\\\{like}%' "
        "  AND concept_blob IS NOT NULL AND concept_blob <> '' "
        "ORDER BY concept_path;"
    )

    # Being "built" only means a serialized model is stored. That blob survives
    # `wipe all facts`, so without this every model still reads (built) after the
    # warehouse is cleared, step 5 stays unblocked, and a model whose features are
    # all gone can be applied. One extra query covers the whole list.
    live_codes = {
        r["concept_cd"]
        for r in query(
            "SELECT DISTINCT concept_cd "
            f"FROM {settings.db_schema}.observation_fact;"
        )
    }

    out = []
    for r in rows:
        built = r["built"] == "t"
        features = [
            c.strip().strip('"').strip("'")
            for c in (r["feature_codes"] or "").split(",")
            if c.strip()
        ]
        # Unknown rather than False when the model predates feature recording.
        has_data = None if not (built and features) else any(
            f in live_codes for f in features
        )
        out.append({
            "code": r["concept_cd"],
            "path": "/" + r["concept_path"].strip("\\").replace("\\", "/"),
            "description": r["name_char"],
            "is_built": built,
            "model_type": r["model_type"] or None,
            "clf_type": r["clf_type"] or None,
            "features_present": has_data,
        })
    return out
