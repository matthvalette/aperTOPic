from fastapi import APIRouter, Depends

from ..dependencies import Container, container

router = APIRouter(tags=["health"])


@router.get("/health")
def health(c: Container = Depends(container)) -> dict:
    return {
        "status": "ok",
        "search": c.search is not None,
        "classification": c.classification is not None,
        "similar": c.similar is not None,
        "apertus_model": c.settings.apertus_model,
        "jev_model": c.settings.typesafe_model,
    }
