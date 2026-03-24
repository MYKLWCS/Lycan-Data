"""Fast person search via MeiliSearch."""
from fastapi import APIRouter, Query
from modules.search.meili_indexer import meili_indexer

router = APIRouter()


@router.get("/persons")
async def search_persons(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, le=100),
    offset: int = 0,
    risk_tier: str | None = None,
):
    filters = f'risk_tier = "{risk_tier}"' if risk_tier else None
    return await meili_indexer.search(q, filters=filters, limit=limit, offset=offset)
