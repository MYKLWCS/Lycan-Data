"""Newspapers Archive crawler — LOC Chronicling America."""
from __future__ import annotations
from urllib.parse import quote_plus
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

_LOC_BASE = "https://chroniclingamerica.loc.gov"

def _parse_loc_entry(entry: dict, name: str) -> dict | None:
    title = entry.get("title", "")
    ocr = (entry.get("ocr_eng") or "").lower()
    url = entry.get("url", "")
    if url and not url.startswith("http"):
        url = _LOC_BASE + url
    if not title and not url:
        return None
    relationship = "memorial" if any(kw in ocr for kw in ("memorial", "tribute", "in memory")) else "obituary"
    return {"full_name": name, "relationship": relationship, "headline": title, "source_url": url}

@register("newspapers_archive")
class NewspapersArchiveCrawler(HttpxCrawler):
    """identifier: full name"""
    platform = "newspapers_archive"
    source_reliability: float = 0.70
    requires_tor: bool = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        name = identifier.strip()
        if not name:
            return CrawlerResult(found=False, platform="newspapers_archive", identifier=identifier, data={})
        parts = name.split(None, 1)
        url = (f"{_LOC_BASE}/search/pages/results/?andtext={quote_plus(parts[0])}"
               f"+{quote_plus(parts[1] if len(parts)>1 else '')}&format=json&rows=5")
        resp = await self.get(url)
        if not resp:
            return CrawlerResult(found=False, platform="newspapers_archive", identifier=identifier, data={})
        try:
            data = resp.json()
        except Exception:
            return CrawlerResult(found=False, platform="newspapers_archive", identifier=identifier, data={})
        items = data.get("items", [])
        if not items:
            return CrawlerResult(found=False, platform="newspapers_archive", identifier=identifier, data={})
        relatives = [r for r in (_parse_loc_entry(i, name) for i in items[:5]) if r]
        return CrawlerResult(found=bool(relatives), platform="newspapers_archive", identifier=identifier,
                             data={"relatives": relatives, "source_url": url})
