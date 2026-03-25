"""Ancestry Hints crawler."""
from __future__ import annotations
from urllib.parse import quote_plus
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

@register("ancestry_hints")
class AncestryHintsCrawler(HttpxCrawler):
    """identifier: full name"""
    platform = "ancestry_hints"
    source_reliability: float = 0.55
    requires_tor: bool = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        parts = identifier.strip().split(None, 1)
        if len(parts) < 2:
            return CrawlerResult(found=False, platform="ancestry_hints", identifier=identifier, data={})
        first, last = parts[0], parts[1]
        url = f"https://www.ancestry.com/search/?name={quote_plus(first)}+{quote_plus(last)}"
        resp = await self.get(url, headers={"Accept": "application/json"})
        if not resp:
            return CrawlerResult(found=False, platform="ancestry_hints", identifier=identifier, data={})
        try:
            data = resp.json()
        except Exception:
            return CrawlerResult(found=False, platform="ancestry_hints", identifier=identifier, data={})
        results = data.get("results", [])
        if not results:
            return CrawlerResult(found=False, platform="ancestry_hints", identifier=identifier, data={})
        relatives = []
        for r in results[:10]:
            name = r.get("name") or r.get("full_name")
            rel = r.get("relationship")
            if name and rel:
                relatives.append({"full_name": name, "relationship": rel,
                                   "birth_year": r.get("birth_year"), "source_url": r.get("url", url)})
        return CrawlerResult(found=bool(relatives), platform="ancestry_hints", identifier=identifier,
                             data={"relatives": relatives, "source_url": url})
