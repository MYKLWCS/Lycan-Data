"""Geni Public API crawler."""
from __future__ import annotations
from urllib.parse import quote_plus
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

def _parse_geni_profile(profile: dict, source_url: str) -> list[dict]:
    relatives = []
    for union in profile.get("unions", []):
        for sp in union.get("partners", []):
            name = sp.get("name") or sp.get("full_name")
            if name:
                relatives.append({"full_name": name, "relationship": "spouse_of", "source_url": source_url})
    return relatives

@register("geni_public")
class GeniPublicCrawler(HttpxCrawler):
    """identifier: full name"""
    platform = "geni_public"
    source_reliability: float = 0.50
    requires_tor: bool = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        name = identifier.strip()
        if not name:
            return CrawlerResult(found=False, platform="geni_public", identifier=identifier, data={})
        url = f"https://www.geni.com/api/profile/search?names={quote_plus(name)}"
        resp = await self.get(url)
        if not resp:
            return CrawlerResult(found=False, platform="geni_public", identifier=identifier, data={})
        try:
            data = resp.json()
        except Exception:
            return CrawlerResult(found=False, platform="geni_public", identifier=identifier, data={})
        if "results" in data: profiles = data["results"]
        elif "profiles" in data: profiles = list(data["profiles"].values())
        else: return CrawlerResult(found=False, platform="geni_public", identifier=identifier, data={})
        if not profiles:
            return CrawlerResult(found=False, platform="geni_public", identifier=identifier, data={})
        relatives = []
        for profile in profiles[:5]:
            relatives.extend(_parse_geni_profile(profile, url))
        return CrawlerResult(found=bool(relatives), platform="geni_public", identifier=identifier,
                             data={"relatives": relatives, "source_url": url})
