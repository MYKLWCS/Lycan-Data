"""Newspapers Archive / Chronicling America obituary crawler."""
from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_LOC_SEARCH = "https://chroniclingamerica.loc.gov/search/pages/results/"

_OBIT_KEYWORDS = {"died", "death", "funeral", "obit"}


@register("newspapers_archive")
class NewspapersArchiveCrawler(HttpxCrawler):
    platform = "newspapers_archive"
    source_reliability = 0.70
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        """identifier: full name"""
        url = f"{_LOC_SEARCH}?andtext={identifier}&format=json&rows=20"
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

        records = []
        for item in json_data.get("items", []):
            parsed = self._parse_loc_entry(item, identifier)
            records.append(parsed)

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=bool(records),
            data={"records": records},
            source_reliability=self.source_reliability,
        )

    def _parse_loc_entry(self, item: dict, name: str) -> dict:
        ocr_text = (item.get("ocr_eng") or "").lower()
        has_obit_keyword = any(kw in ocr_text for kw in _OBIT_KEYWORDS)
        record_type = "obituary" if has_obit_keyword else "memorial"

        return {
            "title": item.get("title", ""),
            "date": item.get("date", ""),
            "url": item.get("url", ""),
            "name": name,
            "record_type": record_type,
            "ocr_snippet": ocr_text[:200],
        }
