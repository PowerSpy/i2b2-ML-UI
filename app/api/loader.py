from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
import shlex, tempfile, shutil
from pathlib import Path

from app.core import audit
from app.core.config import settings
from app.core.docker_exec import exec, exec_cp
from app.core.upload import safe_upload_name, write_capped

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

TABLE = {"concept": "concept_dimension", "fact": "observation_fact"}


def _stage_and_load(kind: str, file: UploadFile, extra_args: str = "") -> Load_Out:
    """Stage one upload and run the loader over it.

    The staging directory is generated, never derived from the upload. It is
    the directory name - not the filename - that ends up interpolated into the
    command this runs through `bash -lc`, so deriving it from
    `Path(file.filename).stem` put an attacker-controlled string into a shell.
    """
    try:
        name = safe_upload_name(file.filename, kind=kind)
    except ValueError as e:
        raise HTTPException(400, str(e))

    host_dir = Path(tempfile.mkdtemp(prefix="i2b2ml-"))
    # A plain string, not Path: on Windows Path("/tmp/x") is a WindowsPath
    # that interpolates as "\tmp\x", so the container was handed a path
    # that does not exist. The loader then globbed nothing and exited 0,
    # which looked exactly like a successful load.
    container_path = f"/tmp/{host_dir.name}"

    try:
        try:
            write_capped(file.file, host_dir / name)
        except ValueError as e:
            raise HTTPException(413, str(e))

        # dest is the parent, so the directory lands as container_path
        copy = exec_cp(CONTAINER, host_dir, "/tmp")
        if copy.returncode != 0:
            return Load_Out(status="error", stdout=copy.stdout, stderr=copy.stderr)

        before = _count(TABLE[kind])
        # quoted even though container_path is now generated: db.py already
        # establishes shlex.quote as what this codebase does to anything
        # crossing into `bash -lc`, and the loader should not be the exception.
        cmd = (f"python -m i2b2_cdi {kind} load -i "
               f"{shlex.quote(container_path)}{extra_args}")
        exec_out = exec(CONTAINER,
                        f"source {settings.etl_venv}",
                        f"cd {settings.etl_app_dir}",
                        cmd)
        result = _load_result(kind, name, exec_out, before)
        # rows_loaded, not exit status: the CLI exits 0 whether it ingested the
        # file or skipped it, so the exit code is not evidence of a load.
        audit.event("warehouse_write", subject=TABLE[kind],
                    operation=f"{kind} load", status=result.status,
                    rows_loaded=result.rows_loaded, filename=name)
        return result
    finally:
        # Both copies are patient data. Without this they accumulate in host
        # /tmp and container /tmp indefinitely, readable by anything that can
        # docker exec.
        shutil.rmtree(host_dir, ignore_errors=True)
        exec(CONTAINER, f"rm -rf -- {shlex.quote(container_path)}")


@router.post("/load-concepts", response_model=Load_Out)
def load_concepts(file: UploadFile = File(...)) -> Load_Out:
    return _stage_and_load("concept", file)


@router.post("/load-facts", response_model=Load_Out)
def load_facts(file: UploadFile = File(...), mrn_are_patient_numbers = True) -> Load_Out:
    return _stage_and_load(
        "fact", file,
        extra_args=" --mrn-are-patient-numbers" if mrn_are_patient_numbers else "",
    )

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