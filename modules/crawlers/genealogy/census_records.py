"""FamilySearch census records crawler via GedcomX API."""
from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_API_BASE = "https://api.familysearch.org/platform/records/search"


@register("census_records")
class CensusRecordsCrawler(HttpxCrawler):
    platform = "census_records"
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        """identifier: "First Last:YYYY" """
        parts = identifier.split(":")
        name_part = parts[0].strip()
        year_part = parts[1].strip() if len(parts) > 1 else ""

        url = f"{_API_BASE}?q.givenName={name_part}&q.birthLikeDate.years={year_part}&collection_id=1803959"
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

        person_map = self._build_person_map(gedcomx)
        records = []
        for entry in gedcomx.get("entries", []):
            parsed = self._parse_census_entry(entry, person_map)
            if parsed:
                records.append(parsed)

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=bool(records),
            data={"records": records},
            source_reliability=self.source_reliability,
        )

    def _build_person_map(self, gedcomx: dict) -> dict[str, str]:
        """Map GedcomX person resource IDs to display names."""
        person_map: dict[str, str] = {}
        for person in gedcomx.get("persons", []):
            pid = person.get("id", "")
            names = person.get("names", [])
            if names:
                parts_list = names[0].get("nameForms", [{}])[0].get("parts", [])
                full = " ".join(p.get("value", "") for p in parts_list).strip()
                person_map[pid] = full or pid
        return person_map

    def _parse_census_entry(self, entry: dict, person_map: dict[str, str] | None = None) -> dict | None:
        if person_map is None:
            person_map = {}
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

        birth_date = ""
        death_date = ""
        for fact in person.get("facts", []):
            ftype = fact.get("type", "")
            if "Birth" in ftype:
                birth_date = fact.get("date", {}).get("original", "")
            elif "Death" in ftype:
                death_date = fact.get("date", {}).get("original", "")

        relationships = []
        for rel in gedcomx.get("relationships", []):
            rtype = rel.get("type", "")
            p1_id = rel.get("person1", {}).get("resourceId", "")
            p2_id = rel.get("person2", {}).get("resourceId", "")
            relationships.append({
                "type": "spouse" if "Couple" in rtype else "parent_child",
                "person1": person_map.get(p1_id, p1_id),
                "person2": person_map.get(p2_id, p2_id),
            })

        return {
            "full_name": full_name,
            "birth_date": birth_date,
            "death_date": death_date,
            "record_type": "census",
            "relationships": relationships,
            "source_id": entry.get("id", ""),
        }
