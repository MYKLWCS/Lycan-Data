"""Fast person search via Typesense — full-text + region + sort."""

from fastapi import APIRouter, Query

from modules.search.meili_indexer import meili_indexer

router = APIRouter()

_ALLOWED_SORT = {
    "default_risk_score",
    "created_at",
    "platform_count",
    "city",
    "state_province",
    "composite_quality",
    "corroboration_count",
    "alt_credit_score",
    "aml_risk_score",
    "enrichment_score",
}


def _safe(v: str) -> str:
    return v.replace("'", "\\'").replace("`", "")


@router.get("/persons")
async def search_persons(
    q: str = Query("", description="Full-text search query"),
    limit: int = Query(20, le=200),
    offset: int = Query(0, ge=0),
    # Geographic filters
    city: str | None = None,
    state: str | None = None,
    country: str | None = None,
    # Risk / compliance filters
    risk_tier: str | None = None,
    has_darkweb: bool | None = None,
    has_sanctions: bool | None = None,
    is_pep: bool | None = None,
    is_sanctioned: bool | None = None,
    # Credit score range (300-850)
    credit_min: int | None = Query(None, ge=300, le=850, description="Min alt credit score"),
    credit_max: int | None = Query(None, ge=300, le=850, description="Max alt credit score"),
    alt_credit_tier: str | None = Query(
        None,
        description="excellent | good | fair | poor | very_poor",
    ),
    # AML filters
    aml_risk_tier: str | None = Query(
        None, description="AML risk tier: low | medium | high | critical"
    ),
    # Marketing tag filter (comma-separated, AND logic)
    tags: str | None = Query(
        None, description="Comma-separated marketing tags — all must match"
    ),
    # Sort
    sort_by: str = Query("default_risk_score", description="Field to sort by"),
    sort_dir: str = Query("desc", description="asc or desc"),
):
    """
    Full-text + filter search over Typesense persons collection.

    Credit/AML/marketing filters layer on top of existing region and risk filters.
    All filters are AND-combined.
    """
    filter_parts: list[str] = []

    # Geographic (Typesense filter_by syntax: field:=value)
    if city:
        filter_parts.append(f"city:='{_safe(city)}'")
    if state:
        filter_parts.append(f"state_province:='{_safe(state)}'")
    if country:
        filter_parts.append(f"country:='{_safe(country)}'")

    # Risk / compliance
    if risk_tier:
        filter_parts.append(f"risk_tier:='{_safe(risk_tier)}'")
    if has_darkweb is not None:
        filter_parts.append(f"has_darkweb:={'true' if has_darkweb else 'false'}")
    if has_sanctions is not None:
        filter_parts.append(f"has_sanctions:={'true' if has_sanctions else 'false'}")
    if is_pep is not None:
        filter_parts.append(f"is_pep:={'true' if is_pep else 'false'}")
    if is_sanctioned is not None:
        filter_parts.append(f"is_sanctioned:={'true' if is_sanctioned else 'false'}")

    # Credit score range (Typesense uses :>= and :<= for numeric ranges)
    if credit_min is not None:
        filter_parts.append(f"alt_credit_score:>={credit_min}")
    if credit_max is not None:
        filter_parts.append(f"alt_credit_score:<={credit_max}")
    if alt_credit_tier:
        filter_parts.append(f"alt_credit_tier:='{_safe(alt_credit_tier)}'")

    # AML tier
    if aml_risk_tier:
        filter_parts.append(f"aml_risk_tier:='{_safe(aml_risk_tier)}'")

    # Marketing tags — each tag must exist in the person's marketing_tags_list
    if tags:
        for raw_tag in tags.split(","):
            tag = _safe(raw_tag.strip())
            if tag:
                filter_parts.append(f"marketing_tags_list:='{tag}'")

    filters = " && ".join(filter_parts) if filter_parts else None

    field = sort_by if sort_by in _ALLOWED_SORT else "default_risk_score"
    direction = "asc" if sort_dir.lower() == "asc" else "desc"

    return await meili_indexer.search(
        query=q or "*",
        filters=filters,
        sort=[f"{field}:{direction}"],
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
        return {
            "hits": [],
            "estimatedTotalHits": 0,
            "error": "Provide at least city, state, or country",
        }

    field = sort_by if sort_by in _ALLOWED_SORT else "default_risk_score"
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


@router.get("/by-tag")
async def search_by_marketing_tag(
    tag: str = Query(..., description="Marketing tag, e.g. title_loan_candidate"),
    credit_min: int | None = Query(None, ge=300, le=850),
    credit_max: int | None = Query(None, ge=300, le=850),
    aml_risk_tier: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("alt_credit_score"),
    sort_dir: str = Query("desc"),
):
    """
    Retrieve all persons matching a specific marketing tag.

    Optionally narrow by credit score range or AML tier.
    Useful for campaign targeting.
    """
    filter_parts = [f"marketing_tags_list:='{_safe(tag)}'"]

    if credit_min is not None:
        filter_parts.append(f"alt_credit_score:>={credit_min}")
    if credit_max is not None:
        filter_parts.append(f"alt_credit_score:<={credit_max}")
    if aml_risk_tier:
        filter_parts.append(f"aml_risk_tier:='{_safe(aml_risk_tier)}'")

    field = sort_by if sort_by in _ALLOWED_SORT else "alt_credit_score"
    direction = "asc" if sort_dir.lower() == "asc" else "desc"

    return await meili_indexer.search(
        query="*",
        filters=" && ".join(filter_parts),
        sort=[f"{field}:{direction}"],
        limit=limit,
        offset=offset,
    )
