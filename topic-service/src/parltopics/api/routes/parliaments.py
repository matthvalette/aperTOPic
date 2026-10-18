from fastapi import APIRouter, Depends

from ..dependencies import Container, container

router = APIRouter(tags=["parliaments"])


@router.get("/parliaments", summary="Names of the parliaments behind body keys")
def parliaments(c: Container = Depends(container)) -> dict[str, dict]:
    return c.parliaments
