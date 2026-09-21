"""Whether the warehouse is healthy or quietly polluted.

Two totals — facts and concepts — cannot tell those apart. On the review
instance 12,549 of 31,912 fact rows were exact duplicates from repeated loads,
and the heart dataset had been loaded several times over with fresh patient
numbers each time, while the UI reported nothing but a larger number.

Every query here is a read. Nothing in this module writes.
"""

from app.core.config import settings
from app.core.db import query, scalar

SCHEMA = settings.db_schema

# What makes two fact rows the same observation. Matches the existing
# of_idx_allobservation_fact index, so the duplicate count is an index scan
# rather than a sort of the whole table.
FACT_KEY = "patient_num, concept_cd, start_date, valtype_cd, tval_char, nval_num"

# Concept paths are stored backslash-delimited; the first segment is the
# dataset a concept belongs to.
ROOT = r"split_part(trim(both '\' from c.concept_path), '\', 1)"


def duplicate_facts() -> dict:
    """Total rows against distinct observations."""
    row = query(
        f"SELECT (SELECT count(*) FROM {SCHEMA}.observation_fact) AS total, "
        f"       (SELECT count(*) FROM (SELECT DISTINCT {FACT_KEY} "
        f"                              FROM {SCHEMA}.observation_fact) d) AS distinct_rows;"
    )[0]
    total = int(row["total"] or 0)
    distinct = int(row["distinct_rows"] or 0)
    return {"total": total, "distinct": distinct, "duplicates": total - distinct}


def per_concept(limit: int = 500) -> list[dict]:
    """Facts and distinct patients per concept code, busiest first."""
    rows = query(
        "SELECT f.concept_cd AS code, count(*) AS facts, "
        "       count(DISTINCT f.patient_num) AS patients "
        f"FROM {SCHEMA}.observation_fact f "
        "GROUP BY f.concept_cd ORDER BY count(*) DESC "
        f"LIMIT {int(limit)};"
    )
    return [
        {"code": r["code"], "facts": int(r["facts"]), "patients": int(r["patients"])}
        for r in rows
    ]


# One row per concept code, carrying its dataset root and how many roots
# declare it. Joining observation_fact straight to concept_dimension instead
# would multiply every fact whose code is declared twice: on the review
# instance `age` sits under both /HeartDisease and /DiabetesSample, and the
# per-dataset facts then summed to more than the table holds.
_CODE_ROOT = (
    "SELECT concept_cd, min(root) AS root, count(*) AS roots "
    f"FROM (SELECT DISTINCT c.concept_cd, {ROOT} AS root "
    f"      FROM {SCHEMA}.concept_dimension c) t "
    "GROUP BY concept_cd"
)


def per_dataset() -> list[dict]:
    """Facts, patients and concepts per top-level concept path.

    Every fact lands in exactly one bucket, so these reconcile: the rows here
    plus `orphan_facts` account for the whole table. Codes declared under more
    than one root cannot be attributed to either and are grouped separately
    rather than counted twice.
    """
    rows = query(
        f"WITH code_root AS ({_CODE_ROOT}) "
        "SELECT CASE WHEN cr.roots > 1 THEN '' ELSE cr.root END AS root, "
        "       max(cr.roots) > 1 AS ambiguous, "
        "       count(*) AS facts, "
        "       count(DISTINCT f.patient_num) AS patients, "
        "       count(DISTINCT f.concept_cd) AS concepts "
        f"FROM {SCHEMA}.observation_fact f "
        "JOIN code_root cr ON cr.concept_cd = f.concept_cd "
        "GROUP BY 1 ORDER BY count(*) DESC;"
    )
    out = []
    for r in rows:
        ambiguous = str(r["ambiguous"]).lower() in ("t", "true")
        out.append({
            "root": "declared under more than one root" if ambiguous else "/" + r["root"],
            "ambiguous": ambiguous,
            "facts": int(r["facts"]),
            "patients": int(r["patients"]),
            "concepts": int(r["concepts"]),
        })
    return out


def colliding_codes() -> list[dict]:
    """Concept codes declared under more than one dataset root.

    A shared code means two datasets write into the same bucket: a cohort or a
    feature path built on one silently picks up the other's patients.
    """
    rows = query(
        "SELECT code, count(*) AS roots, string_agg(root, ', ' ORDER BY root) AS under "
        f"FROM (SELECT DISTINCT c.concept_cd AS code, {ROOT} AS root "
        f"      FROM {SCHEMA}.concept_dimension c) t "
        "GROUP BY code HAVING count(*) > 1 ORDER BY count(*) DESC, code;"
    )
    return [
        {"code": r["code"], "roots": int(r["roots"]),
         "under": ["/" + p for p in (r["under"] or "").split(", ") if p]}
        for r in rows
    ]


def concepts_without_facts() -> list[str]:
    """Declared but never populated — a column the loader silently skipped."""
    rows = query(
        "SELECT c.concept_cd AS code "
        f"FROM {SCHEMA}.concept_dimension c "
        f"LEFT JOIN (SELECT DISTINCT concept_cd FROM {SCHEMA}.observation_fact) f "
        "  ON f.concept_cd = c.concept_cd "
        "WHERE f.concept_cd IS NULL ORDER BY c.concept_cd;"
    )
    # A code can be declared at several paths, so the same one comes back more
    # than once; the interesting fact is the code, not how often it was declared.
    return sorted({r["code"] for r in rows})


def orphan_facts() -> int:
    """Facts whose concept code is not declared in concept_dimension."""
    return int(scalar(
        f"SELECT count(*) FROM {SCHEMA}.observation_fact f "
        f"LEFT JOIN {SCHEMA}.concept_dimension c ON c.concept_cd = f.concept_cd "
        "WHERE c.concept_cd IS NULL;"
    ) or 0)


def patient_overlap() -> list[dict]:
    """Datasets sharing patient numbers.

    Reloading a dataset with fresh patient numbers leaves the old rows behind,
    so the same study appears twice under one root with no patient in common.
    Two roots that share none may be two studies, or one study loaded twice.
    """
    # Only codes belonging to exactly one root count towards an overlap. A code
    # declared under both datasets puts every one of its patients in both sets
    # by construction, which reported 1,197 shared patients on the review
    # instance purely because `age` was declared twice.
    rows = query(
        f"WITH code_root AS ({_CODE_ROOT}), "
        "     pr AS (SELECT DISTINCT cr.root, f.patient_num "
        f"            FROM {SCHEMA}.observation_fact f "
        "            JOIN code_root cr ON cr.concept_cd = f.concept_cd "
        "            WHERE cr.roots = 1) "
        "SELECT a.root AS left_root, b.root AS right_root, count(*) AS shared "
        "FROM pr a JOIN pr b ON b.patient_num = a.patient_num AND b.root > a.root "
        "GROUP BY a.root, b.root ORDER BY count(*) DESC;"
    )
    return [
        {"left": "/" + r["left_root"], "right": "/" + r["right_root"],
         "shared": int(r["shared"])}
        for r in rows
    ]


def report() -> dict:
    return {
        "facts": duplicate_facts(),
        "orphan_facts": orphan_facts(),
        "datasets": per_dataset(),
        "concepts": per_concept(),
        "concepts_without_facts": concepts_without_facts(),
        "colliding_codes": colliding_codes(),
        "patient_overlap": patient_overlap(),
    }
