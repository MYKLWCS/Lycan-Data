"""
people_familysearch.py — FamilySearch genealogy records crawler.

Uses the FamilySearch Platform API to search historical and living tree records.
If settings.familysearch_api_key is set it is sent as a Bearer token; otherwise
a limited unauthenticated public records endpoint is tried.

The identifier may be:
  - "First Last"            → name search only
  - "First Last YYYY"       → name + birth year filter

Registered as "people_familysearch".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.config import settings
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_TREE_SEARCH = (
    "https://api.familysearch.org/platform/tree/search"
    "?q.givenName={first}&q.surname={last}&q.birthLikeYear={year}&count=10"
)
_RECORDS_SEARCH = (
    "https://api.familysearch.org/platform/records/search"
    "?q.givenName={first}&q.surname={last}&count=5"
)
_TOKEN_URL = "https://ident.familysearch.org/cis-web/oauth2/v3/token"

_FS_ACCEPT = "application/x-fs-v1+json"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_entry(entry: dict) -> dict[str, Any]:
    """Normalise a single FamilySearch search entry into a flat dict."""
    person = entry.get("content", {}).get("gedcomx", {})
    persons_list = person.get("persons", [])
    p = persons_list[0] if persons_list else {}

    # Name
    names = p.get("names", [])
    full_name = ""
    if names:
        for np in names[0].get("nameForms", []):  # pragma: no branch
            full_name = np.get("fullText", "")
            if full_name:
                break

    # Vital facts
    birth_date = birth_place = death_date = None
    for fact in p.get("facts", []):
        ftype = fact.get("type", "")
        if "Birth" in ftype:
            birth_date = fact.get("date", {}).get("original")
            birth_place = fact.get("place", {}).get("original")
        elif "Death" in ftype:  # pragma: no branch
            death_date = fact.get("date", {}).get("original")

    return {
        "id": p.get("id") or entry.get("id"),
        "name": full_name,
        "birth_date": birth_date,
        "birth_place": birth_place,
        "death_date": death_date,
        "record_type": entry.get("title", ""),
    }


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("people_familysearch")
class PeopleFamilySearchCrawler(HttpxCrawler):
    """
    Queries the FamilySearch Platform API for genealogy and historical records.

    identifier: "First Last" or "First Last YYYY" where YYYY is a birth year.

    If settings.familysearch_api_key is present it is used as a Bearer token
    and the full tree/search endpoint is queried.  Without a key a limited
    public records search is attempted and returns fewer fields.

    source_reliability: 0.90 — LDS church records are high quality for genealogy.
    """

    platform = "people_familysearch"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        # Extract optional trailing year: "John Doe 1950"
        year = ""
        m = re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\s*$", query)
        if m:
            year = m.group(1)
            query = query[: m.start()].strip()

        parts = query.split(" ", 1)
        first = quote_plus(parts[0])
        last = quote_plus(parts[1]) if len(parts) > 1 else ""

        api_key: str = getattr(settings, "familysearch_api_key", "")

        headers: dict[str, str] = {"Accept": _FS_ACCEPT}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            url = _TREE_SEARCH.format(first=first, last=last, year=year)
        else:
            url = _RECORDS_SEARCH.format(first=first, last=last)

        response = await self.get(url, headers=headers)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 401:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="auth_required",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if response.status_code not in (200, 206):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{response.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            json_data = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        entries = json_data.get("entries", [])
        persons = [_parse_entry(e) for e in entries]
        found = len(persons) > 0

        return self._result(
            identifier,
            found=found,
            persons=persons,
            total=json_data.get("results", len(persons)),
            query=identifier,
            authenticated=bool(api_key),
        )
