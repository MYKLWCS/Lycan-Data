"""
OFAC SDN (Specially Designated Nationals) sanctions list scraper.
Source: https://www.treasury.gov/ofac/downloads/sdn.csv

Registered as: sanctions_ofac
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
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.utils import cache_valid, word_overlap

logger = logging.getLogger(__name__)

OFAC_CSV_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
CACHE_PATH = "/tmp/lycan_ofac.csv"
CACHE_MAX_AGE_HOURS = 6.0
MATCH_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_path(name: str, ext: str) -> str:
    return f"/tmp/lycan_{name}.{ext}"


# ---------------------------------------------------------------------------
# Name-matching helper
# ---------------------------------------------------------------------------


@register("sanctions_ofac")
class SanctionsOFACCrawler(HttpxCrawler):
    """
    Downloads the OFAC SDN CSV list, caches it for 6 hours, and searches
    it by name using fuzzy word-overlap matching.
    """

    platform = "sanctions_ofac"
    category = CrawlerCategory.SANCTIONS_AML
    rate_limit = RateLimit(requests_per_second=2.0, burst_size=10, cooldown_seconds=0.0)
    source_reliability = 0.95
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        """Search the OFAC SDN list for the given name/identifier."""
        csv_text = await self._get_csv()
        if csv_text is None:
            return self._result(
                identifier,
                found=False,
                error="Failed to download OFAC SDN list",
                matches=[],
                match_count=0,
                query=identifier,
            )

        matches = self._search_csv(csv_text, identifier)
        return self._result(
            identifier,
            found=len(matches) > 0,
            matches=matches,
            match_count=len(matches),
            query=identifier,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_csv(self) -> str | None:
        """Return CSV text from cache (if fresh) or download from OFAC."""
        if cache_valid(CACHE_PATH):
            logger.debug("OFAC: using cached list at %s", CACHE_PATH)
            try:
                with open(CACHE_PATH, encoding="latin-1") as fh:
                    return fh.read()
            except OSError as exc:
                logger.warning("OFAC: cache read failed: %s", exc)

        logger.info("OFAC: downloading SDN list from %s", OFAC_CSV_URL)
        response = await self.get(OFAC_CSV_URL)
        if response is None or response.status_code != 200:
            logger.error("OFAC: HTTP request failed")
            return None

        text = response.text
        try:
            with open(CACHE_PATH, "w", encoding="latin-1", errors="replace") as fh:
                fh.write(text)
            logger.debug("OFAC: cached list to %s", CACHE_PATH)
        except OSError as exc:
            logger.warning("OFAC: could not write cache: %s", exc)

        return text

    def _search_csv(self, csv_text: str, query: str) -> list[dict[str, Any]]:
        """
        Parse the OFAC SDN CSV and return all rows where the SDN_Name
        fuzzy-matches the query with score >= MATCH_THRESHOLD.

        CSV column layout (1-indexed, 0-indexed in Python):
          0: Ent_num
          1: SDN_Name
          2: SDN_Type
          3: Program
          4: Title
          5: Call_Sign
          ...
        """
        matches: list[dict[str, Any]] = []
        reader = csv.reader(io.StringIO(csv_text))
        for row in reader:
            if len(row) < 2:
                continue
            sdn_name = row[1].strip()
            if not sdn_name or sdn_name.lower() in ("-0-", "name"):
                continue  # skip header / empty sentinel rows

            score = word_overlap(query, sdn_name)
            if score >= MATCH_THRESHOLD:
                matches.append(
                    {
                        "name": sdn_name,
                        "type": row[2].strip() if len(row) > 2 else "",
                        "program": row[3].strip() if len(row) > 3 else "",
                        "aliases": [],  # aliases are in separate rows in SDN CSV
                        "match_score": round(score, 3),
                    }
                )
        return matches
