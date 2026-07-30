import json

from app.core.db import check_code, check_path, query, scalar


def load_blob(code: str) -> dict:
    check_code(code)
    raw = scalar(
        "SELECT concept_blob FROM i2b2demodata.concept_dimension "
        f"WHERE concept_cd = '{code}';"
    )
    if raw is None:
        raise KeyError(f"no concept with code {code!r}")
    if not raw.strip():
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(raw.replace("'", '"'))


def is_built(code: str) -> bool:
    check_code(code)
    hit = scalar(
        "SELECT 1 FROM i2b2demodata.concept_dimension "
        f"WHERE concept_cd = '{code}' AND concept_blob LIKE '%serialized_model%';"
    )
    return hit is not None


def is_built_at_path(path: str) -> bool:
    check_path(path)
    like = path.strip("/").replace("/", "\\\\")
    hit = scalar(
        "SELECT 1 FROM i2b2demodata.concept_dimension "
        f"WHERE concept_path LIKE '\\\\{like}\\\\%' "
        "AND concept_blob LIKE '%serialized_model%';"
    )
    return hit is not None


def strip_heavy(blob: dict) -> dict:
    return {k: v for k, v in blob.items() if k not in ("serialized_model", "packages")}


def list_ml_concepts(path_prefix: str) -> list[dict]:
    check_path(path_prefix)
    like = path_prefix.strip("/").replace("/", "\\\\")
    rows = query(
        "SELECT concept_cd, concept_path, name_char, "
        "  (concept_blob LIKE '%serialized_model%') AS built "
        "FROM i2b2demodata.concept_dimension "
        f"WHERE concept_path LIKE '\\\\{like}%' ORDER BY concept_path;"
    )
    return [
        {
            "code": r["concept_cd"],
            "path": "/" + r["concept_path"].strip("\\").replace("\\", "/"),
            "description": r["name_char"],
            "is_built": r["built"] == "t",
        }
        for r in rows
    ]
