"""
census_records.py — FamilySearch census/records API crawler.

Queries the FamilySearch Platform records search endpoint for historical
census and vital records tied to a given name.

Registered as "census_records".
"""

import logging
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

SOURCE_RELIABILITY = 0.90
_RECORDS_URL = (
    "https://api.familysearch.org/platform/records/search"
    "?q.givenName={first}&q.surname={last}&count=5"
)
_FS_ACCEPT = "application/x-fs-v1+json"


def _parse_record(entry: dict) -> dict:
    """Normalise a single FamilySearch records entry."""
    content = entry.get("content", {}).get("gedcomx", {})
    persons_list = content.get("persons", [])
    p = persons_list[0] if persons_list else {}

    full_name = ""
    for name in p.get("names", []):
        for form in name.get("nameForms", []):
            if form.get("fullText"):
                full_name = form["fullText"]
                break
        if full_name:
            break

    birth_date = birth_place = death_date = death_place = None
    for fact in p.get("facts", []):
        ftype = fact.get("type", "")
        if "Birth" in ftype:
            birth_date = fact.get("date", {}).get("original")
            birth_place = fact.get("place", {}).get("original")
        elif "Death" in ftype:
            death_date = fact.get("date", {}).get("original")
            death_place = fact.get("place", {}).get("original")

    relationships = content.get("relationships", [])
    parents: list[dict] = []
    children: list[dict] = []
    spouses: list[dict] = []

    persons_by_id = {pp.get("id"): pp for pp in persons_list}

    for rel in relationships:
        rtype = rel.get("type", "")
        p1_id = (rel.get("person1") or {}).get("resourceId")
        p2_id = (rel.get("person2") or {}).get("resourceId")

        def _name_for(pid: str) -> str:
            pp = persons_by_id.get(pid, {})
            for nm in pp.get("names", []):
                for form in nm.get("nameForms", []):
                    if form.get("fullText"):
                        return form["fullText"]
            return ""

        if "ParentChild" in rtype:
            parent_name = _name_for(p1_id or "")
            child_name = _name_for(p2_id or "")
            if parent_name:
                parents.append({"name": parent_name, "birth_year": None})
            if child_name:
                children.append({"name": child_name, "birth_year": None})
        elif "Couple" in rtype:
            other_id = p2_id if p1_id == p.get("id") else p1_id
            spouse_name = _name_for(other_id or "")
            if spouse_name:
                spouses.append({"name": spouse_name, "marriage_date": None})

    return {
        "person_name": full_name,
        "birth_date": birth_date,
        "birth_place": birth_place,
        "death_date": death_date,
        "death_place": death_place,
        "parents": parents,
        "children": children,
        "spouses": spouses,
        "siblings": [],
        "source_url": entry.get("id", ""),
        "record_type": "census",
    }


@register("census_records")
class CensusRecordsCrawler(HttpxCrawler):
    """
    Queries FamilySearch Platform records/search for census records.

    identifier: "First Last"

    source_reliability: 0.90 — government-sourced records, high quality.
    """

    platform = "census_records"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = SOURCE_RELIABILITY
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        parts = identifier.strip().split(" ", 1)
        first = quote_plus(parts[0])
        last = quote_plus(parts[1]) if len(parts) > 1 else ""
        url = _RECORDS_URL.format(first=first, last=last)

        response = await self.get(url, headers={"Accept": _FS_ACCEPT})
        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 401:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="auth_required",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if response.status_code not in (200, 206):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{response.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            json_data = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        entries = json_data.get("entries", [])
        records = [_parse_record(e) for e in entries]
        found = len(records) > 0

        primary = records[0] if records else {}
        return self._result(
            identifier,
            found=found,
            records=records,
            total=json_data.get("results", len(records)),
            query=identifier,
            **{k: v for k, v in primary.items() if k != "person_name"},
            person_name=primary.get("person_name", ""),
        )
