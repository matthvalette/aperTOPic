from fastapi import APIRouter, Depends, HTTPException

from ...domain.models import Taxonomy
from ..dependencies import Container, container

router = APIRouter(prefix="/taxonomies", tags=["taxonomies"])


@router.get("", summary="List the label sets")
def list_taxonomies(c: Container = Depends(container)) -> list[dict]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "kind": t.kind,
            "topics": len(t.topics),
            "description": t.description,
            "native_bodies": t.native_bodies,
        }
        for t in c.taxonomies.list()
    ]


@router.get("/{taxonomy_id}", summary="One label set with every topic")
def get_taxonomy(taxonomy_id: str, c: Container = Depends(container)) -> Taxonomy:
    try:
        return c.taxonomies.get(taxonomy_id)
    except KeyError as error:
        raise HTTPException(404, str(error)) from None
