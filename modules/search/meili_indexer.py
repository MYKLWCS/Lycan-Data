"""
MeiliSearch indexer.
Indexes Person records with all their identifiers, social profiles, and key fields
for sub-millisecond full-text search.
"""
import logging
from typing import Any
import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

PERSONS_INDEX = "persons"
MEILI_SETTINGS = {
    "searchableAttributes": [
        "full_name", "aliases", "phones", "emails", "usernames",
        "platforms", "addresses", "employer", "notes",
    ],
    "filterableAttributes": [
        "risk_tier", "wealth_band", "has_darkweb", "has_sanctions",
        "nationality", "platform_count",
    ],
    "sortableAttributes": [
        "default_risk_score", "created_at", "platform_count",
    ],
    "rankingRules": [
        "words", "typo", "proximity", "attribute", "sort", "exactness",
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
            # Create index
            r = await client.post(
                f"{self.base}/indexes",
                json={"uid": PERSONS_INDEX, "primaryKey": "id"},
                headers=self._headers,
            )
            if r.status_code not in (200, 201, 202):
                # May already exist — try updating settings
                pass

            # Configure settings
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
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search persons. Returns MeiliSearch response dict."""
        body: dict[str, Any] = {
            "q": query,
            "limit": limit,
            "offset": offset,
            "attributesToHighlight": ["full_name", "emails", "phones"],
        }
        if filters:
            body["filter"] = filters

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{self.base}/indexes/{PERSONS_INDEX}/search",
                json=body,
                headers=self._headers,
            )
            if r.status_code == 200:
                return r.json()
            return {"hits": [], "estimatedTotalHits": 0, "query": query}

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
    addresses: list[str] | None = None,
    default_risk_score: float | None = None,
    risk_tier: str | None = None,
    wealth_band: str | None = None,
    nationality: str | None = None,
    has_darkweb: bool = False,
    has_sanctions: bool = False,
    created_at: str | None = None,
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
        "addresses": addresses or [],
        "default_risk_score": default_risk_score or 0.0,
        "risk_tier": risk_tier or "unknown",
        "wealth_band": wealth_band or "unknown",
        "nationality": nationality,
        "has_darkweb": has_darkweb,
        "has_sanctions": has_sanctions,
        "created_at": created_at,
        **extra,
    }
