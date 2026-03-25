"""Geni.com public profile search crawler."""
from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_GENI_BASE = "https://www.geni.com"
_SEARCH_URL = "https://www.geni.com/api/search/people"


@register("geni_public")
class GeniPublicCrawler(HttpxCrawler):
    platform = "geni_public"
    source_reliability = 0.50
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        """identifier: full name"""
        url = f"{_SEARCH_URL}?names={identifier}&per_page=10"
        response = await self.get(url)

        if response is None or response.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="non_200" if response is not None else "no_response",
            )

        try:
            json_data = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
            )

        # Handle multiple response shapes
        if isinstance(json_data, dict):
            raw_profiles = json_data.get("results") or json_data.get("profiles") or []
        elif isinstance(json_data, list):
            raw_profiles = json_data
        else:
            raw_profiles = []

        profiles = [self._parse_geni_profile(p) for p in raw_profiles]
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=bool(profiles),
            data={"profiles": profiles},
            source_reliability=self.source_reliability,
        )

    def _parse_geni_profile(self, profile: dict) -> dict:
        profile_url = profile.get("url", "") or profile.get("profile_url", "")
        if profile_url and not profile_url.startswith("http"):
            profile_url = f"{_GENI_BASE}{profile_url}"
        return {
            "name": profile.get("name", ""),
            "birth_year": profile.get("birth", {}).get("year", "") if isinstance(profile.get("birth"), dict) else "",
            "death_year": profile.get("death", {}).get("year", "") if isinstance(profile.get("death"), dict) else "",
            "profile_url": profile_url,
            "guid": profile.get("guid", ""),
        }
