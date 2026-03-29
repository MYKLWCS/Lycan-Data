"""
spokeo.py — Spokeo people search via FlareSolverr proxy.

Routes requests through FlareSolverr at localhost:8191 to bypass Cloudflare.
Registered as "spokeo".
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit
from shared.config import settings

logger = logging.getLogger(__name__)

_FLARESOLVERR_URL = settings.flaresolverr_url


@register("spokeo")
class SpokeoCrawler(HttpxCrawler):
    """
    Fetches Spokeo people search results via FlareSolverr proxy.
    identifier: full name (e.g. "John Doe")
    """

    platform = "spokeo"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    SOURCE_RELIABILITY = 0.60
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False  # FlareSolverr handles bypass

    async def scrape(self, identifier: str) -> CrawlerResult:
        name = identifier.strip()
        target_url = f"https://www.spokeo.com/search?q={name.replace(' ', '+')}"
        payload = {
            "cmd": "request.get",
            "url": target_url,
            "maxTimeout": 60000,
        }
        resp = await self.post(_FLARESOLVERR_URL, json=payload)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        try:
            data = resp.json()
        except Exception as exc:
            logger.debug("Spokeo FlareSolverr parse error: %s", exc)
            return self._result(identifier, found=False, error="parse_error")

        solution = data.get("solution") or {}
        html = solution.get("response", "")
        if not html:
            return self._result(identifier, found=False)

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.find_all(class_="card-block") or soup.find_all(class_="name-age")
        if not cards:
            cards = soup.select("[class*='person-card'], [class*='result-item']")
        if not cards:
            return self._result(identifier, found=False)

        results = []
        for card in cards[:10]:
            name_tag = card.find(class_="name") or card.find("h3") or card.find("h4")
            addr_tag = card.find(class_="address") or card.find(class_="location")
            results.append(
                {
                    "name": name_tag.get_text(strip=True) if name_tag else "",
                    "address": addr_tag.get_text(strip=True) if addr_tag else "",
                }
            )

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data={"results": results, "count": len(results)},
            profile_url=target_url,
            source_reliability=self.SOURCE_RELIABILITY,
        )
