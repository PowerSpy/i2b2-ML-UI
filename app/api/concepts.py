from fastapi import APIRouter
from pydantic import BaseModel

from app.core.db import query

router = APIRouter()

class Concept(BaseModel):
    code: str
    path: str
    name: str | None = None
    type: str | None = None

def humanize(p: str) -> str:
    return "/" + p.strip("\\").replace("\\", "/")

@router.get("/concepts", response_model=list[Concept])
def list_concepts() -> list[Concept]:
    rows = query(
        "SELECT concept_cd, concept_path, name_char, concept_type "
        "FROM i2b2demodata.concept_dimension ORDER BY concept_path;"
    )
    return [Concept(code=r["concept_cd"], path=humanize(r["concept_path"]),
                    name=r["name_char"] or None, type=r["concept_type"] or None)
            for r in rows]

@router.get("/concept-tree", response_model=list[str])
def concept_tree() -> list[str]:
    prefixes = set()
    for c in list_concepts():
        parts = c.path.strip("/").split("/")
        for i in range(1, len(parts)):
            prefixes.add("/" + "/".join(parts[:i]))
    return sorted(prefixes)
