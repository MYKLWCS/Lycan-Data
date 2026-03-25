"""Ancestry.com hints crawler — scrapes public hint results for a name+birth year."""
from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.ancestry.com/search/"


@register("ancestry_hints")
class AncestryHintsCrawler(HttpxCrawler):
    platform = "ancestry_hints"
    source_reliability = 0.55
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        """
        identifier: "First Last:YYYY"  e.g. "John Smith:1920"
        """
        parts = identifier.split(":")
        name_part = parts[0].strip()
        year_part = parts[1].strip() if len(parts) > 1 else ""

        name_tokens = name_part.split()
        first = name_tokens[0] if name_tokens else name_part
        last = name_tokens[-1] if len(name_tokens) > 1 else ""

        url = f"{_BASE_URL}?name={first}+{last}&birth={year_part}"
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
            json_data = {}

        records = self._parse_results(json_data)
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=bool(records),
            data={"records": records, "name": name_part, "birth_year": year_part},
            source_reliability=self.source_reliability,
        )

    def _parse_results(self, json_data: dict) -> list[dict]:
        results = []
        for item in json_data.get("hints", []):
            results.append({
                "record_id": item.get("id", ""),
                "title": item.get("title", ""),
                "record_type": item.get("recordType", "census"),
                "year": item.get("year", ""),
                "url": item.get("url", ""),
            })
        return results
