"""
people_interpol.py — Interpol Red Notices public API crawler.

Searches the Interpol public Red Notice API for a given full name.
The identifier is split on the first space into forename and surname for the
query parameters. Returns notice list, total count, and individual entity IDs.
Registered as "people_interpol".
"""
from __future__ import annotations
import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_INTERPOL_BASE = (
    "https://ws-public.interpol.int/notices/v1/red"
    "?name={last}&forename={first}&resultPerPage=20"
)
_INTERPOL_HEADERS = {"Accept": "application/json"}


def _parse_notice(notice: dict) -> dict:
    """Extract the relevant fields from a single Red Notice entry."""
    links = notice.get("_links", {})
    self_link = links.get("self", {}).get("href")
    return {
        "entity_id": notice.get("entity_id"),
        "name": notice.get("name"),
        "forename": notice.get("forename"),
        "date_of_birth": notice.get("date_of_birth"),
        "nationalities": notice.get("nationalities", []),
        "charges": notice.get("charges"),
        "notice_url": self_link,
    }


@register("people_interpol")
class PeopleInterpolCrawler(HttpxCrawler):
    """
    Searches the Interpol Red Notice public API for a full name.

    The identifier is split on the first space: the first token becomes the
    forename query parameter and the remainder becomes the name (surname) parameter.
    For single-word identifiers, the entire value is used as the name.

    source_reliability is 0.99 — Interpol notices are authoritative law enforcement data.
    """

    platform = "people_interpol"
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        full_name = identifier.strip()

        parts = full_name.split(" ", 1)
        if len(parts) == 2:
            first, last = parts[0], parts[1]
        else:
            first, last = "", parts[0]

        url = _INTERPOL_BASE.format(
            last=last.replace(" ", "%20"),
            first=first.replace(" ", "%20"),
        )

        response = await self.get(url, headers=_INTERPOL_HEADERS)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
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

        if response.status_code != 200:
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

        embedded = json_data.get("_embedded", {})
        raw_notices = embedded.get("notices", [])
        total = json_data.get("total", len(raw_notices))

        notices = [_parse_notice(n) for n in raw_notices[:20]]
        found = total > 0

        data = {
            "notices": notices,
            "total": total,
            "query": identifier,
        }

        return self._result(identifier, found=found, **data)
