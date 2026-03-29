"""
bis_entity_list.py — Bureau of Industry and Security (BIS) Entity List search.

Downloads and caches the BIS Entity List CSV from:
  https://www.bis.doc.gov/index.php/policy-guidance/lists-of-parties-of-concern/entity-list

Searches for name matches and returns license requirement, policy, and
related persons for any hits.

Registered as "bis_entity_list".
"""

from __future__ import annotations

import csv
import io
import logging
import os
import time
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.utils import word_overlap, cache_valid

logger = logging.getLogger(__name__)

# BIS publishes the Entity List as a consolidated CSV via the EAR supplement
_BIS_CSV_URL = (
    "https://www.bis.doc.gov/index.php/component/docman/doc_download/"
    "1005-supplement-no-4-to-part-744-entity-list"
)
# Fallback: direct XLSX/CSV mirror often hosted by BIS
_BIS_CSV_FALLBACK = (
    "https://www.bis.doc.gov/index.php/documents/regulations-docs/"
    "1005-supplement-no-4-to-part-744/file"
)

_CACHE_PATH = "/tmp/lycan_cache/bis_entity_list.csv"
_CACHE_MAX_AGE_HOURS = 24.0
_MATCH_THRESHOLD = 0.55


def _search_csv(csv_text: str, query: str) -> list[dict[str, Any]]:
    """
    Parse the BIS Entity List CSV and return matching rows.

    The BIS consolidated CSV layout (approximate):
      Country | Entity Name | Address | Federal Register Citation |
      License Requirement | License Policy | Related Persons
    """
    matches: list[dict[str, Any]] = []
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            # Normalise keys — BIS CSV headers vary between releases
            name = (
                row.get("Entity Name")
                or row.get("entity_name")
                or row.get("Name")
                or row.get("name", "")
            ).strip()
            if not name:
                continue
            score = word_overlap(query, name)
            if score < _MATCH_THRESHOLD:
                continue
            country = (row.get("Country") or row.get("country", "")).strip()
            fr_citation = (
                row.get("Federal Register Citation")
                or row.get("FR Citation")
                or row.get("federal_register_citation", "")
            ).strip()
            license_req = (
                row.get("License Requirement") or row.get("license_requirement", "")
            ).strip()
            license_policy = (row.get("License Policy") or row.get("license_policy", "")).strip()
            related = (row.get("Related Persons") or row.get("related_persons", "")).strip()
            matches.append(
                {
                    "name": name,
                    "country": country,
                    "federal_register_citation": fr_citation,
                    "license_requirement": license_req,
                    "license_policy": license_policy,
                    "related_persons": related,
                    "match_score": round(score, 3),
                }
            )
    except Exception as exc:
        logger.warning("BIS Entity List CSV parse error: %s", exc)
    return matches


@register("bis_entity_list")
class BisEntityListCrawler(HttpxCrawler):
    """
    Downloads the BIS Entity List CSV (cached 24 h) and fuzzy-searches
    it for the given person or company name.

    identifier: person or company name

    Data keys returned:
        bis_matches   — list of {name, country, federal_register_citation,
                        license_requirement, license_policy, related_persons,
                        match_score}
        is_on_bis_list — bool
        match_count    — integer
        query          — original identifier
    """

    platform = "bis_entity_list"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.98
    requires_tor = False
    proxy_tier = "direct"

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        csv_text = await self._get_csv()
        if csv_text is None:
            return self._result(
                identifier,
                found=False,
                error="download_failed",
                bis_matches=[],
                is_on_bis_list=False,
                match_count=0,
                query=query,
            )

        matches = _search_csv(csv_text, query)
        return self._result(
            identifier,
            found=len(matches) > 0,
            bis_matches=matches,
            is_on_bis_list=len(matches) > 0,
            match_count=len(matches),
            query=query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_csv(self) -> str | None:
        """Return CSV text from cache or download fresh from BIS."""
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)

        if cache_valid(_CACHE_PATH):
            logger.debug("BIS Entity List: using cached file at %s", _CACHE_PATH)
            try:
                with open(_CACHE_PATH, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError as exc:
                logger.warning("BIS Entity List: cache read failed: %s", exc)

        for url in (_BIS_CSV_URL, _BIS_CSV_FALLBACK):
            logger.info("BIS Entity List: downloading from %s", url)
            resp = await self.get(url)
            if resp is not None and resp.status_code == 200 and len(resp.text) > 1000:
                text = resp.text
                try:
                    with open(_CACHE_PATH, "w", encoding="utf-8", errors="replace") as fh:
                        fh.write(text)
                    logger.debug("BIS Entity List: cached to %s", _CACHE_PATH)
                except OSError as exc:
                    logger.warning("BIS Entity List: cache write failed: %s", exc)
                return text
            logger.debug(
                "BIS Entity List: %s returned %s",
                url,
                resp.status_code if resp else "None",
            )

        logger.error("BIS Entity List: all download attempts failed")
        return None
