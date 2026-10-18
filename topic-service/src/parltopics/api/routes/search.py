from fastapi import APIRouter, Depends

from ...services.search import SearchOptions, SearchOutcome, SearchService
from ..dependencies import search_service
from ..schemas import SearchRequest

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", summary="Search affairs in every parliament language")
async def search(body: SearchRequest, service: SearchService = Depends(search_service)) -> SearchOutcome:
    """Apertus writes queries in German, French, Italian and Romansh, OpenParlData runs them,
    and the hits are merged per affair. With `rank`, Jev orders them by relevance."""
    options = SearchOptions(**body.model_dump(exclude={"query"}))
    return await service.search(body.query, options)
