"""
Typesense indexer.
Indexes Person records with all their identifiers, social profiles, addresses,
and key fields for sub-millisecond full-text + region search.

Migrated from MeiliSearch (BSL 1.1) to Typesense (GPL-3) for licensing compliance.
"""

import logging
from typing import Any

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

PERSONS_COLLECTION = "persons"
IDENTIFIERS_COLLECTION = "identifiers"
SOCIAL_PROFILES_COLLECTION = "social_profiles"

# Typesense collection schemas
PERSONS_SCHEMA = {
    "name": PERSONS_COLLECTION,
    "fields": [
        {"name": "full_name", "type": "string", "optional": True},
        {"name": "aliases", "type": "string[]", "optional": True},
        {"name": "phones", "type": "string[]", "optional": True},
        {"name": "emails", "type": "string[]", "optional": True},
        {"name": "usernames", "type": "string[]", "optional": True},
        {"name": "platforms", "type": "string[]", "optional": True},
        {"name": "addresses_text", "type": "string[]", "optional": True},
        {"name": "city", "type": "string", "optional": True},
        {"name": "state_province", "type": "string", "optional": True},
        {"name": "country", "type": "string", "optional": True},
        {"name": "employer", "type": "string", "optional": True},
        {"name": "notes", "type": "string", "optional": True},
        {"name": "dob", "type": "string", "optional": True},
        {"name": "first_name", "type": "string", "optional": True},
        {"name": "last_name", "type": "string", "optional": True},
        {"name": "location", "type": "string", "optional": True},
        # Filterable numeric / string fields
        {"name": "risk_tier", "type": "string", "facet": True, "optional": True},
        {"name": "wealth_band", "type": "string", "facet": True, "optional": True},
        {"name": "has_darkweb", "type": "bool", "facet": True, "optional": True},
        {"name": "has_sanctions", "type": "bool", "facet": True, "optional": True},
        {"name": "nationality", "type": "string", "facet": True, "optional": True},
        {"name": "platform_count", "type": "int32", "optional": True},
        {"name": "verification_status", "type": "string", "facet": True, "optional": True},
        {"name": "has_addresses", "type": "bool", "facet": True, "optional": True},
        # Credit / AML / marketing
        {"name": "alt_credit_score", "type": "int32", "optional": True},
        {"name": "alt_credit_tier", "type": "string", "facet": True, "optional": True},
        {"name": "aml_risk_score", "type": "float", "optional": True},
        {"name": "aml_risk_tier", "type": "string", "facet": True, "optional": True},
        {"name": "is_pep", "type": "bool", "facet": True, "optional": True},
        {"name": "is_sanctioned", "type": "bool", "facet": True, "optional": True},
        {"name": "marketing_tags_list", "type": "string[]", "facet": True, "optional": True},
        # Sortable numeric fields
        {"name": "default_risk_score", "type": "float"},
        {"name": "composite_quality", "type": "float", "optional": True},
        {"name": "corroboration_count", "type": "int32", "optional": True},
        {"name": "created_at", "type": "string", "optional": True},
        {"name": "enrichment_score", "type": "float", "optional": True},
    ],
    "default_sorting_field": "default_risk_score",
}

IDENTIFIERS_SCHEMA = {
    "name": IDENTIFIERS_COLLECTION,
    "fields": [
        {"name": "person_id", "type": "string", "facet": True},
        {"name": "type", "type": "string", "facet": True},
        {"name": "value", "type": "string"},
        {"name": "confidence", "type": "float", "optional": True},
    ],
}

SOCIAL_PROFILES_SCHEMA = {
    "name": SOCIAL_PROFILES_COLLECTION,
    "fields": [
        {"name": "person_id", "type": "string", "facet": True},
        {"name": "platform", "type": "string", "facet": True},
        {"name": "username", "type": "string", "optional": True},
    ],
}


class TypesenseIndexer:
    def __init__(self):
        self.base = settings.typesense_url.rstrip("/")
        self.key = settings.typesense_api_key
        self._headers = {
            "X-TYPESENSE-API-KEY": self.key,
            "Content-Type": "application/json",
        }

    async def setup_index(self) -> bool:
        """Create collections if they don't exist. Idempotent."""
        success = True
        async with httpx.AsyncClient(timeout=10.0) as client:
            for schema in [PERSONS_SCHEMA, IDENTIFIERS_SCHEMA, SOCIAL_PROFILES_SCHEMA]:
                try:
                    r = await client.get(
                        f"{self.base}/collections/{schema['name']}",
                        headers=self._headers,
                    )
                    if r.status_code == 200:
                        continue  # already exists
                except Exception:
                    pass

                try:
                    r = await client.post(
                        f"{self.base}/collections",
                        json=schema,
                        headers=self._headers,
                    )
                    if r.status_code in (200, 201, 202):
                        logger.info("Created Typesense collection: %s", schema["name"])
                    elif r.status_code == 409:
                        pass  # already exists
                    else:
                        logger.warning(
                            "Failed to create collection %s: %s %s",
                            schema["name"], r.status_code, r.text[:200],
                        )
                        success = False
                except Exception as exc:
                    logger.warning("Typesense collection create error: %s", exc)
                    success = False
        return success

    async def index_person(self, doc: dict[str, Any]) -> bool:
        """Add or update a single person document via upsert."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{self.base}/collections/{PERSONS_COLLECTION}/documents?action=upsert",
                json=doc,
                headers=self._headers,
            )
            return r.status_code in (200, 201, 202)

    async def index_many(self, docs: list[dict[str, Any]]) -> bool:
        """Batch upsert multiple person documents using JSONL import."""
        if not docs:
            return True
        import json
        jsonl = "\n".join(json.dumps(d) for d in docs)
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{self.base}/collections/{PERSONS_COLLECTION}/documents/import?action=upsert",
                content=jsonl,
                headers={**self._headers, "Content-Type": "text/plain"},
            )
            return r.status_code == 200

    async def search(
        self,
        query: str,
        filters: str | None = None,
        sort: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search persons. Returns Typesense-compatible response dict."""
        params: dict[str, Any] = {
            "q": query or "*",
            "query_by": "full_name,aliases,phones,emails,usernames,platforms,addresses_text,city,state_province,country,employer",
            "per_page": limit,
            "page": (offset // limit) + 1 if limit > 0 else 1,
            "highlight_full_fields": "full_name,emails,phones,city",
        }
        if filters:
            params["filter_by"] = filters
        if sort:
            # Convert MeiliSearch sort format (field:dir) to Typesense format (field:dir)
            params["sort_by"] = ",".join(sort)

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{self.base}/collections/{PERSONS_COLLECTION}/documents/search",
                params=params,
                headers=self._headers,
            )
            if r.status_code == 200:
                data = r.json()
                # Normalize response to common format
                hits = [h.get("document", h) for h in data.get("hits", [])]
                return {
                    "hits": hits,
                    "estimatedTotalHits": data.get("found", 0),
                    "query": query,
                }
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
            safe = city.replace("'", "\\'")
            filter_parts.append(f"city:='{safe}'")
        if state:
            safe = state.replace("'", "\\'")
            filter_parts.append(f"state_province:='{safe}'")
        if country:
            safe = country.replace("'", "\\'")
            filter_parts.append(f"country:='{safe}'")

        filters = " && ".join(filter_parts) if filter_parts else None
        return await self.search(
            query=query or "*",
            filters=filters,
            sort=sort or ["default_risk_score:desc"],
            limit=limit,
            offset=offset,
        )

    async def delete_person(self, person_id: str) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.delete(
                f"{self.base}/collections/{PERSONS_COLLECTION}/documents/{person_id}",
                headers=self._headers,
            )
            return r.status_code in (200, 202, 204)


# Module-level singleton (name kept as meili_indexer for backward compat with tests/imports)
meili_indexer = TypesenseIndexer()

# Backward-compatible alias so tests importing MeiliIndexer still work
MeiliIndexer = TypesenseIndexer


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
    enrichment_score: float | None = None,
    **extra,
) -> dict[str, Any]:
    """Build a Typesense document from person data."""
    # Split full_name into first/last for the schema
    first_name = ""
    last_name = ""
    if full_name:
        parts = full_name.strip().split()
        first_name = parts[0] if parts else ""
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    location = ", ".join(p for p in [city, state_province, country] if p)

    return {
        "id": person_id,
        "full_name": full_name or "",
        "first_name": first_name,
        "last_name": last_name,
        "dob": dob or "",
        "phones": phones or [],
        "emails": emails or [],
        "usernames": usernames or [],
        "platforms": platforms or [],
        "platform_count": len(platforms or []),
        "addresses_text": addresses_text or [],
        "city": city or "",
        "state_province": state_province or "",
        "country": country or "",
        "location": location,
        "employer": employer or "",
        "default_risk_score": default_risk_score or 0.0,
        "risk_tier": risk_tier or "unknown",
        "wealth_band": wealth_band or "unknown",
        "nationality": nationality or "",
        "has_darkweb": has_darkweb,
        "has_sanctions": has_sanctions,
        "has_addresses": has_addresses,
        "verification_status": verification_status,
        "composite_quality": composite_quality if composite_quality is not None else 0.0,
        "corroboration_count": corroboration_count if corroboration_count is not None else 0,
        "created_at": created_at or "",
        # Credit / AML / marketing
        "alt_credit_score": alt_credit_score or 0,
        "alt_credit_tier": alt_credit_tier or "unknown",
        "aml_risk_score": aml_risk_score or 0.0,
        "aml_risk_tier": aml_risk_tier or "unknown",
        "is_pep": is_pep,
        "is_sanctioned": is_sanctioned,
        "marketing_tags_list": marketing_tags_list or [],
        "enrichment_score": enrichment_score or 0.0,
        **extra,
    }
