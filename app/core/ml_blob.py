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
        f"  {_blob_field('concept_blob', 'clf_type')} AS clf_type "
        f"FROM {settings.db_schema}.concept_dimension "
        f"WHERE concept_path LIKE '\\\\{like}%' "
        "  AND concept_blob IS NOT NULL AND concept_blob <> '' "
        "ORDER BY concept_path;"
    )
    return [
        {
            "code": r["concept_cd"],
            "path": "/" + r["concept_path"].strip("\\").replace("\\", "/"),
            "description": r["name_char"],
            "is_built": r["built"] == "t",
            "model_type": r["model_type"] or None,
            "clf_type": r["clf_type"] or None,
        }
        for r in rows
    ]
