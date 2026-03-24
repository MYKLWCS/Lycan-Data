"""
sanctions_canada.py — Canada OSFI consolidated sanctions list crawler.

Downloads the OSFI individuals CSV, caches it for 6 hours, and searches
using the same fuzzy word-overlap algorithm as the other sanctions crawlers.

CSV URL: https://www.osfi-bsif.gc.ca/Eng/fi-if/amlc-clrpc/atf-fat/Documents/Consolidatedlistindividuals.csv

Registered as "sanctions_canada".
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

logger = logging.getLogger(__name__)

_CSV_URL = (
    "https://www.osfi-bsif.gc.ca/Eng/fi-if/amlc-clrpc/atf-fat/Documents/"
    "Consolidatedlistindividuals.csv"
)
_CACHE_PATH = "/tmp/lycan_canada_sanctions.csv"
_CACHE_MAX_AGE_HOURS = 6.0
_MATCH_THRESHOLD = 0.7

# Known column names in the OSFI CSV (present when available)
_NAME_COLUMNS = ["LastName", "FirstName", "MiddleName", "Aliases", "AliasType"]


# ---------------------------------------------------------------------------
# Cache helpers (mirrored from sanctions_ofac.py)
# ---------------------------------------------------------------------------

def _cache_valid(path: str, max_age_hours: float = _CACHE_MAX_AGE_HOURS) -> bool:
    if not os.path.exists(path):
        return False
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    return age_hours < max_age_hours


# ---------------------------------------------------------------------------
# Name-matching helper (same algorithm as sanctions_ofac.py)
# ---------------------------------------------------------------------------

def _name_matches(query: str, candidate: str, threshold: float = _MATCH_THRESHOLD) -> float:
    q_words = set(query.lower().split())
    c_words = set(candidate.lower().split())
    if not q_words:
        return 0.0
    overlap = len(q_words & c_words)
    return overlap / len(q_words)


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

@register("sanctions_canada")
class SanctionsCanadaCrawler(HttpxCrawler):
    """
    Downloads the OSFI Canada consolidated individuals sanctions CSV, caches it
    for 6 hours, and searches name columns using fuzzy word-overlap matching.

    source_reliability is 0.99 — official government data.
    """

    platform = "sanctions_canada"
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        csv_text = await self._get_csv()
        if csv_text is None:
            return self._result(
                identifier,
                found=False,
                error="Failed to download Canada OSFI sanctions list",
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
        if _cache_valid(_CACHE_PATH):
            logger.debug("CAN sanctions: using cached list at %s", _CACHE_PATH)
            try:
                with open(_CACHE_PATH, "r", encoding="utf-8-sig", errors="replace") as fh:
                    return fh.read()
            except OSError as exc:
                logger.warning("CAN sanctions: cache read failed: %s", exc)

        logger.info("CAN sanctions: downloading list from %s", _CSV_URL)
        response = await self.get(_CSV_URL)
        if response is None or response.status_code != 200:
            logger.error("CAN sanctions: HTTP request failed")
            return None

        text = response.text
        try:
            with open(_CACHE_PATH, "w", encoding="utf-8-sig", errors="replace") as fh:
                fh.write(text)
            logger.debug("CAN sanctions: cached list to %s", _CACHE_PATH)
        except OSError as exc:
            logger.warning("CAN sanctions: could not write cache: %s", exc)

        return text

    def _search_csv(self, csv_text: str, query: str) -> list[dict[str, Any]]:
        """
        Search the OSFI CSV for name matches.

        Prioritises known name columns (LastName, FirstName, Aliases) but
        falls back to scanning all string columns if those are not present,
        matching the same resilient pattern as sanctions_australia.py.
        """
        matches: list[dict[str, Any]] = []
        reader = csv.DictReader(io.StringIO(csv_text))

        for row in reader:
            fieldnames = list(row.keys())

            # Determine which columns to search
            search_cols = [c for c in _NAME_COLUMNS if c in fieldnames]
            if not search_cols:
                search_cols = fieldnames  # fall back to all columns

            best_score = 0.0
            best_field = ""

            for col in search_cols:
                value = row.get(col, "")
                if not isinstance(value, str) or not value.strip():
                    continue
                score = _name_matches(query, value.strip())
                if score > best_score:
                    best_score = score
                    best_field = col

            if best_score >= _MATCH_THRESHOLD:
                match_record: dict[str, Any] = {
                    "match_score": round(best_score, 3),
                    "matched_field": best_field,
                    # Surface the key identifying fields when available
                    "LastName": row.get("LastName", "").strip(),
                    "FirstName": row.get("FirstName", "").strip(),
                    "DOB": row.get("DOB", row.get("DateOfBirth", "")).strip(),
                    "Aliases": row.get("Aliases", row.get("AliasType", "")).strip(),
                }
                # Include all remaining non-empty row data
                for field, value in row.items():
                    if field not in match_record and value and value.strip():
                        match_record[field] = value.strip()
                matches.append(match_record)

        return matches
