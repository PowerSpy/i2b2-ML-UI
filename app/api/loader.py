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
    container_path = Path(f"/tmp/{host_dir.name}")

    # Save at host_path
    with host_path.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    # Copy the dir into Container — dest is the parent, so it lands as container_path
    copy = exec_cp(CONTAINER, host_dir, Path("/tmp"))
    if copy.returncode != 0:
        return Load_Out(
            status="error",
            stdout=copy.stdout,
            stderr=copy.stderr
        )

    concept_load_cmd = f"python -m i2b2_cdi concept load -i {container_path}"
    exec_out = exec(CONTAINER, "source /usr/src/app/.venv/bin/activate", "cd /usr/src/app", concept_load_cmd)
    return Load_Out(
        status="ok" if exec_out.returncode == 0 else "error",
        stdout=exec_out.stdout,
        stderr=exec_out.stderr,
    )


@router.post("/load-facts", response_model=Load_Out)
def load_facts(file: UploadFile = File(...), mrn_are_patient_numbers = True) -> Load_Out:
    # TODO: normalize filename
    host_dir = Path(tempfile.gettempdir()) / Path(file.filename).stem
    host_dir.mkdir(parents=True, exist_ok=True)
    host_path = host_dir / file.filename
    container_path = Path(f"/tmp/{host_dir.name}")

    # Save at host_path
    with host_path.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    # Copy the dir into Container — dest is the parent, so it lands as container_path
    copy = exec_cp(CONTAINER, host_dir, Path("/tmp"))
    if copy.returncode != 0:
        return Load_Out(
            status="error",
            stdout=copy.stdout,
            stderr=copy.stderr
        )

    concept_load_cmd = f"python -m i2b2_cdi fact load -i {container_path}"
    if mrn_are_patient_numbers:
        concept_load_cmd += " --mrn-are-patient-numbers"
    exec_out = exec(CONTAINER, "source /usr/src/app/.venv/bin/activate", "cd /usr/src/app", concept_load_cmd)
    return Load_Out(
        status="ok" if exec_out.returncode == 0 else "error",
        stdout=exec_out.stdout,
        stderr=exec_out.stderr,
    )

@router.get("/verify-load", response_model=Verify)
def verify_load() -> Verify:
    # -tA strips headers leaving only number in stdout
    fact_out = exec(DB_CONTAINER, "psql -U i2b2 -d i2b2 -tAc \"SELECT count(*) FROM i2b2demodata.observation_fact;\"")
    # Concepts live in their own table — counting them off observation_fact only
    # sees concepts that facts reference, so it drops to 0 when facts are deleted.
    concept_out = exec(DB_CONTAINER, "psql -U i2b2 -d i2b2 -tAc \"SELECT count(*) FROM i2b2demodata.concept_dimension;\"")

    facts = fact_out.stdout.strip()
    concepts = concept_out.stdout.strip()
    ok = fact_out.returncode == concept_out.returncode == 0 and facts.isdigit() and concepts.isdigit()

    return Verify(status="ok" if ok else "error",
                  facts=int(facts) if facts.isdigit() else 0,
                  concepts=int(concepts) if concepts.isdigit() else 0)