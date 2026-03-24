"""Fast person search via MeiliSearch — full-text + region + sort."""
from fastapi import APIRouter, Query
from modules.search.meili_indexer import meili_indexer

router = APIRouter()


@router.get("/persons")
async def search_persons(
    q: str = Query("", description="Full-text search query"),
    limit: int = Query(20, le=200),
    offset: int = Query(0, ge=0),
    # Filters
    risk_tier: str | None = None,
    city: str | None = None,
    state: str | None = None,
    country: str | None = None,
    has_darkweb: bool | None = None,
    has_sanctions: bool | None = None,
    # Sort
    sort_by: str = Query("default_risk_score", description="Field to sort by"),
    sort_dir: str = Query("desc", description="asc or desc"),
):
    """
    Full-text + filter search over MeiliSearch persons index.
    Supports region targeting (city/state/country), risk tier,
    dark-web and sanctions flags.
    """
    filter_parts: list[str] = []

    if risk_tier:
        safe = risk_tier.replace('"', '')
        filter_parts.append(f'risk_tier = "{safe}"')
    if city:
        safe = city.replace('"', '')
        filter_parts.append(f'city = "{safe}"')
    if state:
        safe = state.replace('"', '')
        filter_parts.append(f'state_province = "{safe}"')
    if country:
        safe = country.replace('"', '')
        filter_parts.append(f'country = "{safe}"')
    if has_darkweb is not None:
        filter_parts.append(f'has_darkweb = {"true" if has_darkweb else "false"}')
    if has_sanctions is not None:
        filter_parts.append(f'has_sanctions = {"true" if has_sanctions else "false"}')

    filters = " AND ".join(filter_parts) if filter_parts else None

    # Validate sort field against allowed sortable attributes
    allowed_sort = {
        "default_risk_score", "created_at", "platform_count",
        "city", "state_province", "composite_quality", "corroboration_count",
    }
    field = sort_by if sort_by in allowed_sort else "default_risk_score"
    direction = "asc" if sort_dir.lower() == "asc" else "desc"
    sort = [f"{field}:{direction}"]

    return await meili_indexer.search(
        query=q,
        filters=filters,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/region")
async def search_by_region(
    city: str | None = Query(None),
    state: str | None = Query(None),
    country: str | None = Query(None),
    q: str = Query("", description="Optional full-text query within region"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("default_risk_score"),
    sort_dir: str = Query("desc"),
):
    """
    Region-targeted search. Pass city='Dallas' to get everyone in Dallas.
    Optionally narrow with a full-text query.
    """
    if not any([city, state, country]):
        return {"hits": [], "estimatedTotalHits": 0, "error": "Provide at least city, state, or country"}

    allowed_sort = {
        "default_risk_score", "created_at", "platform_count",
        "city", "state_province", "composite_quality", "corroboration_count",
    }
    field = sort_by if sort_by in allowed_sort else "default_risk_score"
    direction = "asc" if sort_dir.lower() == "asc" else "desc"

    return await meili_indexer.search_by_region(
        city=city,
        state=state,
        country=country,
        query=q,
        limit=limit,
        offset=offset,
        sort=[f"{field}:{direction}"],
    )
