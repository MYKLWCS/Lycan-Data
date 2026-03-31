"""
icij_offshoreleaks.py — ICIJ Offshore Leaks Database search.

Searches the ICIJ Offshore Leaks database at:
  https://offshoreleaks.icij.org/search?q=NAME

Returns matches from the Panama Papers, Pandora Papers, FinCEN Files,
Luanda Leaks, and other ICIJ investigation datasets.

Registered as "icij_offshoreleaks".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://offshoreleaks.icij.org/search?q={query}&e=&c=&j=&page=1"
# ICIJ also exposes a JSON API used by their React frontend
_JSON_API = "https://offshoreleaks.icij.org/api/search?q={query}&e=&c=&j=&page=1"

_KNOWN_DATASETS = {
    "panama_papers",
    "pandora_papers",
    "fincen_files",
    "luanda_leaks",
    "bahamas_leaks",
    "paradise_papers",
    "offshore_leaks",
}


def _normalise_dataset(raw: str) -> str:
    """Normalise a dataset label to a canonical slug."""
    slug = raw.lower().replace(" ", "_").replace("-", "_")
    for known in _KNOWN_DATASETS:
        if known in slug:
            return known
    return slug


def _parse_json_results(data: Any) -> list[dict[str, Any]]:
    """
    Parse the ICIJ JSON API response.

    The frontend API returns something like:
    {
      "data": {
        "entities": [...],
        "officers": [...],
        "addresses": [...],
        "intermediaries": [...]
      }
    }
    Each item has: name, entity_type, jurisdiction, datasets, node_id, etc.
    """
    matches: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return matches

    payload = data.get("data") or data
    if isinstance(payload, list):
        sections: dict[str, list] = {"results": payload}
    else:
        sections = {k: v for k, v in payload.items() if isinstance(v, list)}

    for section_name, items in sections.items():
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("node_name", "")
            entity_type = item.get("type") or item.get("node_type") or section_name.rstrip("s")
            jurisdiction = (
                item.get("jurisdiction")
                or item.get("country_codes", "")
                or item.get("jurisdiction_description", "")
            )
            datasets_raw: list[str] = item.get("datasets") or item.get("sourceIDs") or []
            if isinstance(datasets_raw, str):
                datasets_raw = [datasets_raw]
            datasets = [_normalise_dataset(d) for d in datasets_raw]

            linked_to = item.get("linked_to") or item.get("connected_to", "")
            registered_address = item.get("registered_address") or item.get("address", "")
            incorporation_date = (
                item.get("incorporation_date") or item.get("inactivation_date", "") or ""
            )
            if isinstance(incorporation_date, dict):
                incorporation_date = incorporation_date.get("value", "")

            if not name:
                continue

            matches.append(
                {
                    "name": name,
                    "entity_name": item.get("entity_name") or name,
                    "entity_type": entity_type,
                    "jurisdiction": jurisdiction,
                    "linked_to": linked_to,
                    "source_dataset": datasets[0] if datasets else "",
                    "source_datasets": datasets,
                    "registered_address": registered_address,
                    "incorporation_date": str(incorporation_date),
                }
            )

    return matches


def _parse_html_results(html: str) -> list[dict[str, Any]]:
    """
    Fallback: scrape the ICIJ search results HTML page.
    Parses the result cards rendered by the server-side template.
    """
    matches: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        # ICIJ result cards sit inside .search-result or article tags
        cards = soup.select(".search-result, article.result, li.result-item, .result")
        if not cards:
            # Try table rows
            for table in soup.find_all("table"):
                rows = table.find_all("tr")
                headers = [
                    th.get_text(strip=True).lower()
                    for th in (rows[0].find_all(["th", "td"]) if rows else [])
                ]
                for row in rows[1:]:
                    cells = row.find_all("td")
                    record = {
                        headers[i] if i < len(headers) else f"col_{i}": c.get_text(strip=True)
                        for i, c in enumerate(cells)
                    }
                    name = record.get("name", "")
                    if name:
                        matches.append(
                            {
                                "name": name,
                                "entity_name": name,
                                "entity_type": record.get("type", ""),
                                "jurisdiction": record.get("jurisdiction", ""),
                                "linked_to": "",
                                "source_dataset": record.get("source", ""),
                                "source_datasets": [],
                                "registered_address": record.get("address", ""),
                                "incorporation_date": "",
                            }
                        )
        for card in cards:
            name_el = card.select_one("h3, h4, .name, .entity-name, strong")
            name = name_el.get_text(strip=True) if name_el else ""
            dataset_el = card.select_one(".dataset, .source, .tag, .badge")
            dataset = dataset_el.get_text(strip=True) if dataset_el else ""
            jurisdiction_el = card.select_one(".jurisdiction, .country")
            jurisdiction = jurisdiction_el.get_text(strip=True) if jurisdiction_el else ""
            type_el = card.select_one(".type, .entity-type")
            entity_type = type_el.get_text(strip=True) if type_el else ""

            if not name:
                continue
            matches.append(
                {
                    "name": name,
                    "entity_name": name,
                    "entity_type": entity_type,
                    "jurisdiction": jurisdiction,
                    "linked_to": "",
                    "source_dataset": _normalise_dataset(dataset) if dataset else "",
                    "source_datasets": [_normalise_dataset(dataset)] if dataset else [],
                    "registered_address": "",
                    "incorporation_date": "",
                }
            )
    except Exception as exc:
        logger.debug("ICIJ HTML parse error: %s", exc)
    return matches


@register("icij_offshoreleaks")
class IcijOffshoreLeaksCrawler(HttpxCrawler):
    """
    Searches the ICIJ Offshore Leaks database for matches across all
    available datasets (Panama Papers, Pandora Papers, FinCEN Files, etc.).

    Tries the JSON API first; falls back to HTML scraping.

    identifier: person or company name

    Data keys returned:
        icij_matches  — list of {name, entity_name, entity_type, jurisdiction,
                        linked_to, source_dataset, registered_address,
                        incorporation_date}
        is_in_leak    — bool
        leak_names    — list of dataset slugs found
        match_count   — integer
        query         — original identifier
    """

    platform = "icij_offshoreleaks"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.90
    requires_tor = False
    proxy_tier = "datacenter"

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        encoded = quote_plus(query)

        matches = await self._try_json_api(encoded)
        if not matches:
            matches = await self._try_html(encoded)

        leak_names = sorted(
            {
                ds
                for m in matches
                for ds in (m.get("source_datasets") or [m.get("source_dataset", "")])
                if ds
            }
        )

        return self._result(
            identifier,
            found=len(matches) > 0,
            icij_matches=matches,
            is_in_leak=len(matches) > 0,
            leak_names=leak_names,
            match_count=len(matches),
            query=query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _try_json_api(self, encoded: str) -> list[dict[str, Any]]:
        url = _JSON_API.format(query=encoded)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is None or resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception as exc:
            logger.debug("ICIJ JSON decode error: %s", exc)
            return []
        return _parse_json_results(data)

    async def _try_html(self, encoded: str) -> list[dict[str, Any]]:
        url = _SEARCH_URL.format(query=encoded)
        resp = await self.get(url)
        if resp is None or resp.status_code != 200:
            logger.debug("ICIJ HTML search returned %s", resp.status_code if resp else "None")
            return []
        return _parse_html_results(resp.text)
