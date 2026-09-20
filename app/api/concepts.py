from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
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
        f"FROM {settings.db_schema}.concept_dimension ORDER BY concept_path;"
    )
    return [Concept(code=r["concept_cd"], path=humanize(r["concept_path"]),
                    name=r["name_char"] or None, type=r["concept_type"] or None)
            for r in rows]

@router.get("/concept-tree", response_model=list[str])
def concept_tree(include_models: bool = False) -> list[str]:
    """Selectable path prefixes, for the feature and label pickers.

    The ml_root subtree is left out by default. Models are stored there as
    concepts, so it shows up as an ordinary branch and can be picked as a
    feature source — which feeds serialized model blobs in as features. The
    app's help text says not to; this makes it impossible rather than
    discouraged. Pass include_models=true to get the raw tree.
    """
    ml_root = settings.ml_root.rstrip("/")

    prefixes = set()
    for c in list_concepts():
        parts = c.path.strip("/").split("/")
        for i in range(1, len(parts)):
            prefixes.add("/" + "/".join(parts[:i]))

    if not include_models:
        prefixes = {
            p for p in prefixes
            if p != ml_root and not p.startswith(f"{ml_root}/")
        }
    return sorted(prefixes)
