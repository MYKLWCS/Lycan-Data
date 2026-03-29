"""
sanctions_australia.py — Australia DFAT consolidated sanctions list crawler.

Downloads the DFAT regulation 8 consolidated CSV, caches it for 6 hours,
and searches across all string columns using fuzzy word-overlap matching
(same algorithm as sanctions_ofac.py).

CSV URL: https://www.dfat.gov.au/sites/default/files/regulation8_consolidated.csv

Registered as "sanctions_australia".
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

_CSV_URL = "https://www.dfat.gov.au/sites/default/files/regulation8_consolidated.csv"
_CACHE_PATH = "/tmp/lycan_australia_sanctions.csv"
_CACHE_MAX_AGE_HOURS = 6.0
_MATCH_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Cache helpers (mirrored from sanctions_ofac.py)
# ---------------------------------------------------------------------------


@register("sanctions_australia")
class SanctionsAustraliaCrawler(HttpxCrawler):
    """
    Downloads the DFAT Australia consolidated sanctions CSV, caches it for 6 hours,
    and searches across all string columns using fuzzy word-overlap matching.

    source_reliability is 0.99 — official government data.
    """

    platform = "sanctions_australia"
    category = CrawlerCategory.SANCTIONS_AML
    rate_limit = RateLimit(requests_per_second=2.0, burst_size=10, cooldown_seconds=0.0)
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        csv_text = await self._get_csv()
        if csv_text is None:
            return self._result(
                identifier,
                found=False,
                error="Failed to download Australia DFAT sanctions list",
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
        if cache_valid(_CACHE_PATH):
            logger.debug("AUS sanctions: using cached list at %s", _CACHE_PATH)
            try:
                with open(_CACHE_PATH, encoding="utf-8-sig", errors="replace") as fh:
                    return fh.read()
            except OSError as exc:
                logger.warning("AUS sanctions: cache read failed: %s", exc)

        logger.info("AUS sanctions: downloading list from %s", _CSV_URL)
        response = await self.get(_CSV_URL)
        if response is None or response.status_code != 200:
            logger.error("AUS sanctions: HTTP request failed")
            return None

        text = response.text
        try:
            with open(_CACHE_PATH, "w", encoding="utf-8-sig", errors="replace") as fh:
                fh.write(text)
            logger.debug("AUS sanctions: cached list to %s", _CACHE_PATH)
        except OSError as exc:
            logger.warning("AUS sanctions: could not write cache: %s", exc)

        return text

    def _search_csv(self, csv_text: str, query: str) -> list[dict[str, Any]]:
        """
        Parse all rows and search every string column for word-overlap matches.
        Returns rows that match at or above the threshold in any column.
        """
        matches: list[dict[str, Any]] = []
        reader = csv.DictReader(io.StringIO(csv_text))

        for row in reader:
            best_score = 0.0
            best_field = ""
            best_value = ""

            for field, value in row.items():
                if not isinstance(value, str) or not value.strip():
                    continue
                score = word_overlap(query, value.strip())
                if score > best_score:
                    best_score = score
                    best_field = field
                    best_value = value.strip()

            if best_score >= _MATCH_THRESHOLD:
                match_record: dict[str, Any] = {
                    "match_score": round(best_score, 3),
                    "matched_field": best_field,
                    "matched_value": best_value,
                }
                # Include all non-empty fields from the row
                for field, value in row.items():
                    if value and value.strip():
                        match_record[field] = value.strip()
                matches.append(match_record)

        return matches
