"""Census Records crawler — FamilySearch US census records."""
from __future__ import annotations
from urllib.parse import quote_plus
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

@register("census_records")
class CensusRecordsCrawler(HttpxCrawler):
    """identifier: full name"""
    platform = "census_records"
    source_reliability: float = 0.85
    requires_tor: bool = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        parts = identifier.strip().split(None, 1)
        if len(parts) < 2:
            return CrawlerResult(found=False, platform="census_records", identifier=identifier, data={})
        first, last = parts[0], parts[1]
        url = (f"https://familysearch.org/search/records/results"
               f"?q.givenName={quote_plus(first)}&q.surname={quote_plus(last)}&q.collectionId=1803959")
        resp = await self.get(url)
        if not resp:
            return CrawlerResult(found=False, platform="census_records", identifier=identifier, data={})
        try:
            data = resp.json()
        except Exception:
            return CrawlerResult(found=False, platform="census_records", identifier=identifier, data={})
        entries = data.get("entries", [])
        if not entries:
            return CrawlerResult(found=False, platform="census_records", identifier=identifier, data={})
        relatives = []
        for entry in entries[:10]:
            rels = entry.get("content", {}).get("gedcomx", {}).get("relationships", [])
            names = {p.get("id"): " ".join(n.get("fullText","") for n in p.get("names",[{}]))
                     for p in entry.get("content",{}).get("gedcomx",{}).get("persons",[])}
            for rel in rels:
                rtype = rel.get("type", "")
                p2_id = rel.get("person2", {}).get("resourceId")
                p1_id = rel.get("person1", {}).get("resourceId")
                if "Couple" in rtype: relationship = "spouse_of"
                elif "ParentChild" in rtype: relationship = "parent_of"
                else: continue
                name = names.get(p2_id) or names.get(p1_id) or ""
                if name:
                    relatives.append({"full_name": name.strip(), "relationship": relationship, "source_url": url})
        return CrawlerResult(found=bool(relatives), platform="census_records", identifier=identifier,
                             data={"relatives": relatives, "source_url": url})
