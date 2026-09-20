from fastapi import APIRouter
from pydantic import BaseModel
from app.core.docker_exec import exec
from app.core.config import settings

router = APIRouter()

CONTAINER = settings.container
DB_CONTAINER = settings.db_container

class Delete(BaseModel):
    status: str
    # The CLI's own output. Without it the UI could only say "check the backend
    # logs", having thrown away the only record of what went wrong.
    stdout: str = ""
    stderr: str = ""
    rows_removed: int | None = None


def _count(table: str) -> int | None:
    out = exec(DB_CONTAINER,
               f"{settings.psql} -tAc \"SELECT count(*) FROM {settings.db_schema}.{table};\"")
    text = out.stdout.strip()
    return int(text) if out.returncode == 0 and text.isdigit() else None


def _delete(kind: str, table: str) -> Delete:
    before = _count(table)
    out = exec(CONTAINER,
               f"source {settings.etl_venv}",
               f"cd {settings.etl_app_dir}",
               f"python -m i2b2_cdi {kind} delete")
    after = _count(table)
    removed = None if (before is None or after is None) else before - after

    return Delete(
        status="ok" if out.returncode == 0 else "error",
        stdout=out.stdout,
        stderr=out.stderr,
        rows_removed=removed,
    )


@router.delete("/delete-concepts", response_model=Delete)
def delete_concepts() -> Delete:
    return _delete("concept", "concept_dimension")


@router.delete("/delete-facts", response_model=Delete)
def delete_facts() -> Delete:
    return _delete("fact", "observation_fact")
