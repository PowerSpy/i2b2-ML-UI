from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel
import tempfile, shutil
from pathlib import Path

from app.core.config import settings
from app.core.docker_exec import exec, exec_cp

router = APIRouter()

CONTAINER = settings.container
# The ETL container has psql but no local server, so counts run on the DB itself.
DB_CONTAINER = settings.db_container

class Load_Out(BaseModel):
    status: str
    stdout: str
    stderr: str
    # Rows the warehouse actually gained. The CLI globs its input directory for
    # filenames ending `concepts.csv` / `facts.csv`; anything else matches
    # nothing, so it logs its banner, does nothing, and exits 0. Exit status
    # alone therefore cannot tell a successful load from an ignored file.
    rows_loaded: int | None = None
    note: str | None = None


SUFFIX = {"concept": "concepts.csv", "fact": "facts.csv"}


def _count(table: str) -> int | None:
    out = exec(DB_CONTAINER,
               f"{settings.psql} -tAc \"SELECT count(*) FROM {settings.db_schema}.{table};\"")
    text = out.stdout.strip()
    return int(text) if out.returncode == 0 and text.isdigit() else None


def _load_result(kind: str, filename: str, exec_out, before: int | None) -> Load_Out:
    table = "concept_dimension" if kind == "concept" else "observation_fact"
    after = _count(table)
    delta = None if (before is None or after is None) else after - before

    if exec_out.returncode != 0:
        return Load_Out(status="error", stdout=exec_out.stdout, stderr=exec_out.stderr,
                        rows_loaded=delta)

    if delta == 0:
        expected = SUFFIX[kind]
        misnamed = not filename.lower().endswith(expected)
        note = f"{filename!r} added no rows. "
        note += (
            f"The loader only reads files whose name ends {expected!r}, so this one "
            "was skipped entirely."
            if misnamed else
            "The filename is right, so the file was read but every row was rejected "
            "or already present — check the log above."
        )
        return Load_Out(status="error", stdout=exec_out.stdout, stderr=exec_out.stderr,
                        rows_loaded=0, note=note)

    return Load_Out(status="ok", stdout=exec_out.stdout, stderr=exec_out.stderr,
                    rows_loaded=delta)

class Verify(BaseModel):
    status: str
    concepts: int
    facts: int

@router.post("/load-concepts", response_model=Load_Out)
def load_concepts(file: UploadFile = File(...)) -> Load_Out:
    # TODO: normalize filename
    host_dir = Path(tempfile.gettempdir()) / Path(file.filename).stem
    host_dir.mkdir(parents=True, exist_ok=True)
    host_path = host_dir / file.filename
    # A plain string, not Path: on Windows Path("/tmp/x") is a WindowsPath
    # that interpolates as "\tmp\x", so the container was handed a path
    # that does not exist. The loader then globbed nothing and exited 0,
    # which looked exactly like a successful load.
    container_path = f"/tmp/{host_dir.name}"

    # Save at host_path
    with host_path.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    # Copy the dir into Container — dest is the parent, so it lands as container_path
    copy = exec_cp(CONTAINER, host_dir, "/tmp")
    if copy.returncode != 0:
        return Load_Out(
            status="error",
            stdout=copy.stdout,
            stderr=copy.stderr
        )

    before = _count("concept_dimension")
    concept_load_cmd = f"python -m i2b2_cdi concept load -i {container_path}"
    exec_out = exec(CONTAINER, f"source {settings.etl_venv}", f"cd {settings.etl_app_dir}", concept_load_cmd)
    return _load_result("concept", file.filename, exec_out, before)


@router.post("/load-facts", response_model=Load_Out)
def load_facts(file: UploadFile = File(...), mrn_are_patient_numbers = True) -> Load_Out:
    # TODO: normalize filename
    host_dir = Path(tempfile.gettempdir()) / Path(file.filename).stem
    host_dir.mkdir(parents=True, exist_ok=True)
    host_path = host_dir / file.filename
    # A plain string, not Path: on Windows Path("/tmp/x") is a WindowsPath
    # that interpolates as "\tmp\x", so the container was handed a path
    # that does not exist. The loader then globbed nothing and exited 0,
    # which looked exactly like a successful load.
    container_path = f"/tmp/{host_dir.name}"

    # Save at host_path
    with host_path.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    # Copy the dir into Container — dest is the parent, so it lands as container_path
    copy = exec_cp(CONTAINER, host_dir, "/tmp")
    if copy.returncode != 0:
        return Load_Out(
            status="error",
            stdout=copy.stdout,
            stderr=copy.stderr
        )

    before = _count("observation_fact")
    concept_load_cmd = f"python -m i2b2_cdi fact load -i {container_path}"
    if mrn_are_patient_numbers:
        concept_load_cmd += " --mrn-are-patient-numbers"
    exec_out = exec(CONTAINER, f"source {settings.etl_venv}", f"cd {settings.etl_app_dir}", concept_load_cmd)
    return _load_result("fact", file.filename, exec_out, before)

@router.get("/verify-load", response_model=Verify)
def verify_load() -> Verify:
    # -tA strips headers leaving only number in stdout
    fact_out = exec(DB_CONTAINER, f"{settings.psql} -tAc \"SELECT count(*) FROM {settings.db_schema}.observation_fact;\"")
    # Concepts live in their own table — counting them off observation_fact only
    # sees concepts that facts reference, so it drops to 0 when facts are deleted.
    concept_out = exec(DB_CONTAINER, f"{settings.psql} -tAc \"SELECT count(*) FROM {settings.db_schema}.concept_dimension;\"")

    facts = fact_out.stdout.strip()
    concepts = concept_out.stdout.strip()
    ok = fact_out.returncode == concept_out.returncode == 0 and facts.isdigit() and concepts.isdigit()

    return Verify(status="ok" if ok else "error",
                  facts=int(facts) if facts.isdigit() else 0,
                  concepts=int(concepts) if concepts.isdigit() else 0)