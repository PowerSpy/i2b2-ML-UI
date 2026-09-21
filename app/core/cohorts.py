import re
import shlex
import tempfile
from collections import Counter
from pathlib import Path

from app.core.config import settings
from app.core.db import check_code, check_name, query, scalar
from app.core.docker_exec import exec, exec_cp

PREFIX = 'Patient Set for "'


SCRIPT = '''import sys
sys.path.insert(0, {app_dir!r})          # required: importdata/ is on sys.path, not repo root
from tests.ML.test_helper import create_patient_set
print(create_patient_set(
    project_id={project!r}, user_id={user!r},
    query_name={name!r},
    sql_patient_query={sql!r},
))
'''


def create_cohort(name: str, concept_code: str) -> int:
    check_name(name)
    check_code(concept_code)
    if any(c["name"] == name for c in list_cohorts()):
        raise ValueError(f"a cohort named {name!r} already exists")

    sql = (f"SELECT patient_num FROM {settings.db_schema}.observation_fact "
           f"WHERE concept_cd = '{concept_code}'")

    host_dir = Path(tempfile.mkdtemp())
    script = host_dir / "make_cohort.py"
    script.write_text(SCRIPT.format(
        app_dir=settings.etl_app_dir,
        project=settings.i2b2_project,
        user=settings.i2b2_user,
        name=name,
        sql=sql,
    ))
    exec_cp(settings.container, script, Path("/tmp/make_cohort.py"))

    out = exec(settings.container,
               f"source {settings.etl_venv}",
               f"cd {settings.etl_app_dir}",
               "python /tmp/make_cohort.py")
    if out.returncode != 0:
        raise RuntimeError(out.stderr)
    return int(out.stdout.strip().splitlines()[-1])


DELETE_SQL = """
CREATE TEMP TABLE _del AS
  SELECT result_instance_id AS rid, query_instance_id AS qiid
  FROM {schema}.qt_query_result_instance
  WHERE result_instance_id IN ({ids});
CREATE TEMP TABLE _delm AS
  SELECT DISTINCT query_master_id AS qmid FROM {schema}.qt_query_instance
  WHERE query_instance_id IN (SELECT qiid FROM _del);
DELETE FROM {schema}.qt_patient_set_collection WHERE result_instance_id IN (SELECT rid FROM _del);
DELETE FROM {schema}.qt_patient_enc_collection WHERE result_instance_id IN (SELECT rid FROM _del);
DELETE FROM {schema}.qt_xml_result WHERE result_instance_id IN (SELECT rid FROM _del);
DELETE FROM {schema}.qt_query_result_instance WHERE result_instance_id IN (SELECT rid FROM _del);
DELETE FROM {schema}.qt_query_instance qi
  WHERE qi.query_instance_id IN (SELECT qiid FROM _del)
    AND NOT EXISTS (SELECT 1 FROM {schema}.qt_query_result_instance r
                    WHERE r.query_instance_id = qi.query_instance_id);
DELETE FROM {schema}.qt_query_master qm
  WHERE qm.query_master_id IN (SELECT qmid FROM _delm)
    AND NOT EXISTS (SELECT 1 FROM {schema}.qt_query_instance qi
                    WHERE qi.query_master_id = qm.query_master_id);
"""


def delete_cohorts(cohort_ids: list[int]) -> int:
    known = {c["id"] for c in list_cohorts()}
    unknown = sorted(set(cohort_ids) - known)
    if unknown:
        raise ValueError(f"not a patient set: {unknown}")
    if not cohort_ids:
        return 0

    ids = ", ".join(str(int(i)) for i in cohort_ids)
    sql = DELETE_SQL.format(schema=settings.db_schema, ids=ids)
    out = exec(settings.db_container,
               f"{settings.psql} -v ON_ERROR_STOP=1 --single-transaction "
               f"-c {shlex.quote(sql)}")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "psql failed")
    return len(cohort_ids)


def wipe_cohorts() -> int:
    return delete_cohorts([c["id"] for c in list_cohorts()])


def list_cohorts() -> list[dict]:
    """Every patient set, with its live membership and whether its name is unique.

    `live` counts only members that still have facts, so a cohort left behind by
    a reload shows the gap. It is computed here, in one query for every cohort,
    rather than per cohort on demand — the pickers in steps 3 and 5 need it as
    much as the cohort list does, and asking per row cost two container round
    trips each.

    `duplicate` matters more than it looks. The build engine resolves a cohort
    *name* to every matching result_instance_id and unions them, so two sets
    called the same thing silently train on the combination. On this instance
    that meant 489 patients against a 297-patient dataset.
    """
    rows = query(
        "SELECT qri.result_instance_id AS id, qri.description, qri.set_size, "
        "  COUNT(psc.patient_num) FILTER (WHERE f.patient_num IS NOT NULL) AS live "
        f"FROM {settings.db_schema}.qt_query_result_instance qri "
        f"LEFT JOIN {settings.db_schema}.qt_patient_set_collection psc "
        "  ON psc.result_instance_id = qri.result_instance_id "
        "LEFT JOIN (SELECT DISTINCT patient_num "
        f"          FROM {settings.db_schema}.observation_fact) f "
        "  ON f.patient_num = psc.patient_num "
        "GROUP BY qri.result_instance_id, qri.description, qri.set_size "
        "ORDER BY qri.result_instance_id DESC;"
    )

    out = []
    for r in rows:
        d = r["description"] or ""
        if d.startswith(PREFIX) and d.endswith('"'):
            size = int(r["set_size"] or 0)
            live = int(r["live"] or 0)
            out.append({"id": int(r["id"]), "name": d[len(PREFIX):-1],
                        "size": size, "live": live, "stale": live != size})

    seen = Counter(c["name"] for c in out)
    for c in out:
        c["duplicate"] = seen[c["name"]] > 1
    return out


# The item_key tests/ML/test_helper.py writes into every query it creates.
# It is a fixed string in that helper, not a description of the cohort: every
# patient set this app has ever made carries it, including heart-disease sets,
# where it claims a Type 2 Diabetes ICD-10 code. It must never be shown as a
# cohort's definition.
HELPER_ITEM_KEY = "\\i2b2\\Diagnoses\\ICD10\\E11\\"

# What the CRC writes into generated_sql when it resolves a panel. This is the
# real selection — it is the SQL that chose the patients.
_PATH_LIKE = re.compile(r"concept_path\s+LIKE\s+'([^']+)'", re.I)
_CODE_EQ = re.compile(r"concept_cd\s*=\s*'([^']+)'", re.I)
_ITEM_KEY = re.compile(r"<item_key>([^<]*)</item_key>")


def cohort_definition(cohort_id: int) -> dict:
    """What a cohort was built from, or an honest statement that it is unknown.

    A patient set stores a name and a size; the concept behind it lives on the
    query master that produced it. Two kinds exist here and they are not
    equally trustworthy:

    - Sets built through the CRC have `generated_sql` naming the concept path
      the panel resolved to. That is the actual selection and is reported.
    - Sets built by this app go through the ETL's test helper, which leaves
      `generated_sql` empty and stamps a hardcoded item_key into request_xml.
      Nothing about the real concept is recorded, so this reports that rather
      than the placeholder.
    """
    rows = query(
        "SELECT m.query_master_id AS master_id, m.name, m.create_date, "
        "  m.generated_sql, m.request_xml "
        f"FROM {settings.db_schema}.qt_query_result_instance ri "
        f"JOIN {settings.db_schema}.qt_query_instance qi "
        "  ON qi.query_instance_id = ri.query_instance_id "
        f"JOIN {settings.db_schema}.qt_query_master m "
        "  ON m.query_master_id = qi.query_master_id "
        f"WHERE ri.result_instance_id = {int(cohort_id)} "
        "ORDER BY m.query_master_id DESC LIMIT 1;"
    )
    if not rows:
        return {
            "id": cohort_id,
            "recorded": False,
            "note": "no query master is linked to this patient set, so nothing "
                    "records how it was built",
        }

    row = rows[0]
    sql = row.get("generated_sql") or ""
    xml = row.get("request_xml") or ""

    def first(pattern: re.Pattern, text: str) -> str | None:
        m = pattern.search(text)
        return m.group(1) if m else None

    item_key = first(_ITEM_KEY, xml)
    path = first(_PATH_LIKE, sql)
    code = first(_CODE_EQ, sql)

    out = {
        "id": cohort_id,
        "master_id": int(row["master_id"]),
        "query_name": row.get("name") or None,
        "created": row.get("create_date") or None,
    }

    if path or code:
        out.update({
            "recorded": True,
            "concept_path": _humanize(path) if path else None,
            "concept_code": code,
            "source": "generated_sql",
            "note": "read from the SQL the query actually ran",
        })
        return out

    placeholder = item_key is not None and item_key.strip() == HELPER_ITEM_KEY
    out.update({
        "recorded": False,
        "concept_path": None,
        "concept_code": None,
        "source": None,
        "note": (
            "This set was created through the ETL's test helper, which records no "
            "concept. The item_key stored alongside it is a fixed placeholder the "
            "helper writes into every query it makes, so it describes nothing about "
            "this cohort and is deliberately not shown."
            if placeholder else
            "The query master carries no resolved SQL, so the concept behind this "
            "set was never recorded."
        ),
    })
    return out


def _humanize(coded: str) -> str:
    """'\\\\HeartDisease\\\\label\\\\%' -> '/HeartDisease/label'."""
    return "/" + coded.rstrip("%").strip("\\").replace("\\\\", "\\").replace("\\", "/").strip("/")


def duplicate_names() -> list[str]:
    return sorted({c["name"] for c in list_cohorts() if c["duplicate"]})

def live_size(cohort_id: int) -> int:
    return int(scalar(
        f"SELECT count(*) FROM {settings.db_schema}.qt_patient_set_collection "
        f"WHERE result_instance_id = {int(cohort_id)} "
        f"AND patient_num IN (SELECT DISTINCT patient_num "
        f"FROM {settings.db_schema}.observation_fact);"
    ) or 0)

