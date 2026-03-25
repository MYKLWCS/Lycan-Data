"""
MeiliSearch indexer.
Indexes Person records with all their identifiers, social profiles, addresses,
and key fields for sub-millisecond full-text + region search.
"""

import logging
from typing import Any

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

PERSONS_INDEX = "persons"
MEILI_SETTINGS = {
    "searchableAttributes": [
        "full_name",
        "aliases",
        "phones",
        "emails",
        "usernames",
        "platforms",
        "addresses_text",
        "city",
        "state_province",
        "country",
        "employer",
        "notes",
    ],
    "filterableAttributes": [
        "risk_tier",
        "wealth_band",
        "has_darkweb",
        "has_sanctions",
        "nationality",
        "platform_count",
        "city",
        "state_province",
        "country",
        "verification_status",
        "has_addresses",
        # Credit / AML / marketing filters
        "alt_credit_score",
        "alt_credit_tier",
        "aml_risk_tier",
        "is_pep",
        "is_sanctioned",
        "marketing_tags_list",
    ],
    "sortableAttributes": [
        "default_risk_score",
        "created_at",
        "platform_count",
        "city",
        "state_province",
        "composite_quality",
        "corroboration_count",
        "alt_credit_score",
        "aml_risk_score",
    ],
    "rankingRules": [
        "words",
        "typo",
        "proximity",
        "attribute",
        "sort",
        "exactness",
    ],
}


class MeiliIndexer:
    def __init__(self):
        self.base = settings.meili_url.rstrip("/")
        self.key = settings.meili_master_key
        self._headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    async def setup_index(self) -> bool:
        """Create index and configure settings. Idempotent."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{self.base}/indexes",
                json={"uid": PERSONS_INDEX, "primaryKey": "id"},
                headers=self._headers,
            )
            if r.status_code not in (200, 201, 202):
                pass  # May already exist — fall through to settings update

            r2 = await client.patch(
                f"{self.base}/indexes/{PERSONS_INDEX}/settings",
                json=MEILI_SETTINGS,
                headers=self._headers,
            )
            return r2.status_code in (200, 202)

    async def index_person(self, doc: dict[str, Any]) -> bool:
        """Add or update a single person document."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{self.base}/indexes/{PERSONS_INDEX}/documents",
                json=[doc],
                headers=self._headers,
            )
            return r.status_code in (200, 202)

    async def index_many(self, docs: list[dict[str, Any]]) -> bool:
        """Batch index multiple person documents."""
        if not docs:
            return True
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{self.base}/indexes/{PERSONS_INDEX}/documents",
                json=docs,
                headers=self._headers,
            )
            return r.status_code in (200, 202)

    async def search(
        self,
        query: str,
        filters: str | None = None,
        sort: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search persons. Returns MeiliSearch response dict."""
        body: dict[str, Any] = {
            "q": query,
            "limit": limit,
            "offset": offset,
            "attributesToHighlight": ["full_name", "emails", "phones", "city"],
        }
        if filters:
            body["filter"] = filters
        if sort:
            body["sort"] = sort

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{self.base}/indexes/{PERSONS_INDEX}/search",
                json=body,
                headers=self._headers,
            )
            if r.status_code == 200:
                return r.json()
            return {"hits": [], "estimatedTotalHits": 0, "query": query}

    async def search_by_region(
        self,
        city: str | None = None,
        state: str | None = None,
        country: str | None = None,
        query: str = "",
        limit: int = 50,
        offset: int = 0,
        sort: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search persons filtered to a geographic region."""
        filter_parts: list[str] = []
        if city:
            safe = city.replace('"', "")
            filter_parts.append(f'city = "{safe}"')
        if state:
            safe = state.replace('"', "")
            filter_parts.append(f'state_province = "{safe}"')
        if country:
            safe = country.replace('"', "")
            filter_parts.append(f'country = "{safe}"')

        filters = " AND ".join(filter_parts) if filter_parts else None
        return await self.search(
            query=query,
            filters=filters,
            sort=sort or ["default_risk_score:desc"],
            limit=limit,
            offset=offset,
        )

    async def delete_person(self, person_id: str) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.delete(
                f"{self.base}/indexes/{PERSONS_INDEX}/documents/{person_id}",
                headers=self._headers,
            )
            return r.status_code in (200, 202)


meili_indexer = MeiliIndexer()


def build_person_doc(
    person_id: str,
    full_name: str | None = None,
    dob: str | None = None,
    phones: list[str] | None = None,
    emails: list[str] | None = None,
    usernames: list[str] | None = None,
    platforms: list[str] | None = None,
    addresses_text: list[str] | None = None,
    city: str | None = None,
    state_province: str | None = None,
    country: str | None = None,
    employer: str | None = None,
    default_risk_score: float | None = None,
    risk_tier: str | None = None,
    wealth_band: str | None = None,
    nationality: str | None = None,
    has_darkweb: bool = False,
    has_sanctions: bool = False,
    has_addresses: bool = False,
    verification_status: str = "unverified",
    composite_quality: float = 0.5,
    corroboration_count: int = 1,
    created_at: str | None = None,
    # Credit / AML / marketing intelligence
    alt_credit_score: int | None = None,
    alt_credit_tier: str | None = None,
    aml_risk_score: float | None = None,
    aml_risk_tier: str | None = None,
    is_pep: bool = False,
    is_sanctioned: bool = False,
    marketing_tags_list: list[str] | None = None,
    **extra,
) -> dict[str, Any]:
    """Build a MeiliSearch document from person data."""
    return {
        "id": person_id,
        "full_name": full_name or "",
        "dob": dob,
        "phones": phones or [],
        "emails": emails or [],
        "usernames": usernames or [],
        "platforms": platforms or [],
        "platform_count": len(platforms or []),
        "addresses_text": addresses_text or [],
        "city": city,
        "state_province": state_province,
        "country": country,
        "employer": employer,
        "default_risk_score": default_risk_score or 0.0,
        "risk_tier": risk_tier or "unknown",
        "wealth_band": wealth_band or "unknown",
        "nationality": nationality,
        "has_darkweb": has_darkweb,
        "has_sanctions": has_sanctions,
        "has_addresses": has_addresses,
        "verification_status": verification_status,
        "composite_quality": composite_quality,
        "corroboration_count": corroboration_count,
        "created_at": created_at,
        # Credit / AML / marketing
        "alt_credit_score": alt_credit_score,
        "alt_credit_tier": alt_credit_tier or "unknown",
        "aml_risk_score": aml_risk_score,
        "aml_risk_tier": aml_risk_tier or "unknown",
        "is_pep": is_pep,
        "is_sanctioned": is_sanctioned,
        "marketing_tags_list": marketing_tags_list or [],
        **extra,
    }
