from fastapi import APIRouter
from pydantic import BaseModel
from app.core.docker_exec import exec
from app.core.config import settings

router = APIRouter()

CONTAINER = settings.container
DB_CONTAINER = settings.db_container

class Delete(BaseModel):
    status: str


@router.delete("/delete-concepts", response_model=Delete)
def delete_concepts() -> Delete:
    exec_out = exec(CONTAINER, "source /usr/src/app/.venv/bin/activate", "cd /usr/src/app", "python -m i2b2_cdi concept delete")
    return Delete(status="ok" if exec_out.returncode == 0 else "error")

@router.delete("/delete-facts", response_model=Delete)
def delete_facts() -> Delete:
    exec_out = exec(CONTAINER, "source /usr/src/app/.venv/bin/activate", "cd /usr/src/app", "python -m i2b2_cdi fact delete")
    return Delete(status="ok" if exec_out.returncode == 0 else "error")