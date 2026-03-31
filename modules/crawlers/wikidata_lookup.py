"""
wikidata_lookup.py — Wikidata structured data lookup.

Free API, no key needed. Returns structured biographical data:
DOB, nationality, occupation, employers, education, family members.
"""

from __future__ import annotations

import logging

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_WIKIDATA_SEARCH = "https://www.wikidata.org/w/api.php?action=wbsearchentities&search={query}&language=en&format=json&limit=3&type=item"
_WIKIDATA_ENTITY = "https://www.wikidata.org/w/api.php?action=wbgetentities&ids={qid}&languages=en&format=json&props=claims|labels|descriptions"

# Property IDs for useful biographical fields
_PROPS = {
    "P569": "date_of_birth",
    "P570": "date_of_death",
    "P27": "nationality",
    "P106": "occupation",
    "P108": "employer",
    "P69": "educated_at",
    "P22": "father",
    "P25": "mother",
    "P26": "spouse",
    "P40": "child",
    "P3373": "sibling",
    "P19": "place_of_birth",
    "P20": "place_of_death",
    "P856": "official_website",
    "P2002": "twitter_username",
    "P2003": "instagram_username",
    "P2013": "facebook_id",
    "P2037": "github_username",
    "P2847": "google_plus_id",
    "P4003": "facebook_page",
    "P6634": "linkedin_id",
}


@register("wikidata_lookup")
class WikidataLookupCrawler(HttpxCrawler):
    """Structured biographical data from Wikidata."""

    platform = "wikidata_lookup"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=2.0, burst_size=10, cooldown_seconds=0.0)
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        if not query:
            return self._result(identifier, found=False)

        # Step 1: Search for entity
        search_url = _WIKIDATA_SEARCH.format(query=query.replace(" ", "+"))
        resp = await self.get(search_url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False, error="search_failed")

        try:
            results = resp.json().get("search", [])
        except Exception:
            return self._result(identifier, found=False, error="parse_error")

        if not results:
            return self._result(identifier, found=False)

        qid = results[0].get("id", "")
        label = results[0].get("label", "")
        description = results[0].get("description", "")

        # Step 2: Get entity claims
        entity_url = _WIKIDATA_ENTITY.format(qid=qid)
        resp2 = await self.get(entity_url)
        if not resp2 or resp2.status_code != 200:
            return self._result(
                identifier, found=True, qid=qid, label=label, description=description
            )

        try:
            entities = resp2.json().get("entities", {})
            entity = entities.get(qid, {})
            claims = entity.get("claims", {})
        except Exception:
            return self._result(
                identifier, found=True, qid=qid, label=label, description=description
            )

        # Step 3: Extract structured data
        extracted = {}
        for prop_id, field_name in _PROPS.items():
            if prop_id in claims:
                values = []
                for claim in claims[prop_id]:
                    mainsnak = claim.get("mainsnak", {})
                    datavalue = mainsnak.get("datavalue", {})
                    val_type = datavalue.get("type", "")

                    if val_type == "time":
                        values.append(datavalue.get("value", {}).get("time", ""))
                    elif val_type == "string":
                        values.append(datavalue.get("value", ""))
                    elif val_type == "wikibase-entityid":
                        # Resolve entity label
                        ref_id = datavalue.get("value", {}).get("id", "")
                        values.append(ref_id)  # Just store QID for now
                    elif val_type == "monolingualtext":
                        values.append(datavalue.get("value", {}).get("text", ""))

                if values:
                    extracted[field_name] = values[0] if len(values) == 1 else values

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={
                "qid": qid,
                "label": label,
                "description": description,
                **extracted,
            },
            profile_url=f"https://www.wikidata.org/wiki/{qid}",
            source_reliability=self.source_reliability,
        )
