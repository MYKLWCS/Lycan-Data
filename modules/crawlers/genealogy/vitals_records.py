"""FamilySearch vitals records crawler (birth, death, marriage certs)."""
from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_API_BASE = "https://api.familysearch.org/platform/records/search"

_FACT_TYPE_MAP = {
    "Birth": "birth_cert",
    "Death": "obituary",
    "Marriage": "memorial",
}


@register("vitals_records")
class VitalsRecordsCrawler(HttpxCrawler):
    platform = "vitals_records"
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        """identifier: "First Last:YYYY" """
        parts = identifier.split(":")
        name_part = parts[0].strip()
        year_part = parts[1].strip() if len(parts) > 1 else ""

        url = f"{_API_BASE}?q.givenName={name_part}&q.birthLikeDate.years={year_part}&collection_id=2285338"
        response = await self.get(url, headers={"Accept": "application/x-gedcomx-v1+json"})

        if response is None or response.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="non_200" if response is not None else "no_response",
            )

        try:
            gedcomx = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
            )

        records = []
        for entry in gedcomx.get("entries", []):
            parsed = self._parse_vitals_entry(entry)
            if parsed:
                records.append(parsed)

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=bool(records),
            data={"records": records},
            source_reliability=self.source_reliability,
        )

    def _parse_vitals_entry(self, entry: dict) -> dict | None:
        content = entry.get("content", {})
        gedcomx = content.get("gedcomx", {})
        persons = gedcomx.get("persons", [])
        if not persons:
            return None

        person = persons[0]
        names = person.get("names", [])
        full_name = ""
        if names:
            parts = names[0].get("nameForms", [{}])[0].get("parts", [])
            full_name = " ".join(p.get("value", "") for p in parts).strip()

        record_type = "birth_cert"  # default
        event_date = ""
        for fact in person.get("facts", []):
            ftype = fact.get("type", "")
            for key, rtype in _FACT_TYPE_MAP.items():
                if key in ftype:
                    record_type = rtype
                    event_date = fact.get("date", {}).get("original", "")
                    break

        return {
            "full_name": full_name,
            "record_type": record_type,
            "event_date": event_date,
            "source_id": entry.get("id", ""),
        }
