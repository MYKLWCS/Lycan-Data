"""
sanctions_uk.py — UK HMT / OFSI Financial Sanctions crawler.

Downloads the UK OFSI (Office of Financial Sanctions Implementation) consolidated
sanctions list CSV, caches it for 6 hours, and searches by name.

Source: https://ofsistorage.blob.core.windows.net/publishlive/ConsolidatedList.csv
Registered as "sanctions_uk".
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

_UK_CSV_URL = (
    "https://ofsistorage.blob.core.windows.net/publishlive/ConsolidatedList.csv"
)
_CACHE_PATH = "/tmp/lycan_uk_sanctions.csv"
_CACHE_MAX_AGE_HOURS = 6.0
_MATCH_THRESHOLD = 0.6

# UK OFSI CSV columns (0-indexed):
# 0: GroupID, 1: LastUpdated, 2: Name6 (Group Name), 3: Name1 (Last name),
# 4: Name2 (First name), 5: Name3 (Middle name), 6: Name4, 7: Name5,
# 8: DOB, 9: Town of Birth, 10: Country of Birth, 11: Nationality,
# 12: Passport Number, 13: Position, 14: Regime


def _cache_valid(path: str, max_age_hours: float = _CACHE_MAX_AGE_HOURS) -> bool:
    if not os.path.exists(path):
        return False
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    return age_hours < max_age_hours


def _name_overlap_score(query: str, candidate: str) -> float:
    """Word-overlap match score 0.0–1.0."""
    q_words = set(query.lower().split())
    c_words = set(candidate.lower().split())
    if not q_words:
        return 0.0
    return len(q_words & c_words) / len(q_words)


@register("sanctions_uk")
class UKSanctionsCrawler(HttpxCrawler):
    """
    Downloads the UK OFSI consolidated sanctions CSV, caches for 6 hours,
    and searches by name.

    identifier: person or entity name (e.g. "Igor Sechin")

    Data keys returned:
        matches     — list of matching sanction records (up to 50)
        match_count — number of matches found
    """

    platform = "sanctions_uk"
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        csv_text = await self._get_csv()
        if csv_text is None:
            return self._result(
                identifier,
                found=False,
                error="download_failed",
                matches=[],
                match_count=0,
            )

        matches = self._search(csv_text, identifier.strip())
        return self._result(
            identifier,
            found=len(matches) > 0,
            matches=matches[:50],
            match_count=len(matches),
        )

    async def _get_csv(self) -> str | None:
        """Return CSV from cache (if fresh) or download from OFSI."""
        if _cache_valid(_CACHE_PATH):
            logger.debug("UK sanctions: using cached list at %s", _CACHE_PATH)
            try:
                with open(_CACHE_PATH, "r", encoding="latin-1", errors="replace") as fh:
                    return fh.read()
            except OSError as exc:
                logger.warning("UK sanctions: cache read failed: %s", exc)

        logger.info("UK sanctions: downloading OFSI consolidated list")
        response = await self.get(_UK_CSV_URL)
        if response is None or response.status_code != 200:
            logger.error("UK sanctions: HTTP request failed")
            return None

        # OFSI CSV is latin-1 encoded
        try:
            text = response.content.decode("latin-1", errors="replace")
        except Exception:
            text = response.text

        try:
            with open(_CACHE_PATH, "w", encoding="latin-1", errors="replace") as fh:
                fh.write(text)
            logger.debug("UK sanctions: cached list to %s", _CACHE_PATH)
        except OSError as exc:
            logger.warning("UK sanctions: could not write cache: %s", exc)

        return text

    def _search(self, csv_text: str, query: str) -> list[dict[str, Any]]:
        """Search the OFSI CSV for matching names."""
        matches: list[dict[str, Any]] = []
        seen_groups: set[str] = set()

        try:
            reader = csv.reader(io.StringIO(csv_text))
        except Exception as exc:
            logger.warning("UK sanctions: CSV parse error: %s", exc)
            return []

        for i, row in enumerate(reader):
            # Skip header rows
            if i < 2:
                continue
            if len(row) < 3:
                continue

            group_id = row[0].strip() if row[0] else ""
            group_name = row[2].strip() if len(row) > 2 else ""  # Entity/Group name
            last = row[3].strip() if len(row) > 3 else ""
            first = row[4].strip() if len(row) > 4 else ""
            middle = row[5].strip() if len(row) > 5 else ""
            dob = row[8].strip() if len(row) > 8 else ""
            nationality = row[11].strip() if len(row) > 11 else ""
            regime = row[14].strip() if len(row) > 14 else ""

            candidates = []
            if group_name:
                candidates.append(group_name)
            name_parts = " ".join(p for p in [first, middle, last] if p)
            if name_parts:
                candidates.append(name_parts)

            best_score = 0.0
            for cand in candidates:
                score = _name_overlap_score(query, cand)
                if score > best_score:
                    best_score = score

            if best_score < _MATCH_THRESHOLD:
                continue

            if group_id and group_id in seen_groups:
                continue
            if group_id:
                seen_groups.add(group_id)

            matches.append(
                {
                    "group_id": group_id,
                    "group_name": group_name,
                    "first_name": first,
                    "last_name": last,
                    "date_of_birth": dob,
                    "nationality": nationality,
                    "regime": regime,
                    "match_score": round(best_score, 3),
                }
            )

        matches.sort(key=lambda m: m["match_score"], reverse=True)
        return matches
