"""
sanctions_eu.py — EU Financial Sanctions Database (FSDB) crawler.

Downloads the EU consolidated sanctions CSV list, caches it for 6 hours,
and searches it by name using fuzzy word-overlap matching.

Source: https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList/content
Registered as "sanctions_eu".
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

logger = logging.getLogger(__name__)

_EU_CSV_URL = (
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList/content?token=n/a"
)
_CACHE_PATH = "/tmp/lycan_eu_sanctions.csv"
_CACHE_MAX_AGE_HOURS = 6.0
_MATCH_THRESHOLD = 0.6

# EU CSV columns (0-indexed):
# 0: FileGenerationDate, 1: Entity_LogicalId, 2: Entity_Remark,
# 3: NameAlias_FirstName, 4: NameAlias_MiddleName, 5: NameAlias_LastName,
# 6: NameAlias_WholeName, 7: NameAlias_NameLanguage, 8: Entity_SubjectType


def _cache_valid(path: str, max_age_hours: float = _CACHE_MAX_AGE_HOURS) -> bool:
    if not os.path.exists(path):
        return False
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    return age_hours < max_age_hours


def _name_overlap_score(query: str, candidate: str) -> float:
    """Word-overlap score 0.0–1.0. All query words found in candidate."""
    q_words = set(query.lower().split())
    c_words = set(candidate.lower().split())
    if not q_words:
        return 0.0
    return len(q_words & c_words) / len(q_words)


@register("sanctions_eu")
class EUSanctionsCrawler(HttpxCrawler):
    """
    Downloads the EU Financial Sanctions consolidated CSV list, caches for 6 hours,
    and searches for matching persons/entities by name.

    identifier: person or entity name (e.g. "Bashar al-Assad")

    Data keys returned:
        matches     — list of matching sanction records (up to 50)
        match_count — number of matches found
    """

    platform = "sanctions_eu"
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
        """Return CSV text from cache (if fresh) or download from EU FSDB."""
        if _cache_valid(_CACHE_PATH):
            logger.debug("EU sanctions: using cached list at %s", _CACHE_PATH)
            try:
                with open(_CACHE_PATH, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            except OSError as exc:
                logger.warning("EU sanctions: cache read failed: %s", exc)

        logger.info("EU sanctions: downloading consolidated list from EU FSDB")
        response = await self.get(
            _EU_CSV_URL,
            headers={"Accept": "text/csv, text/plain, */*"},
        )
        if response is None or response.status_code != 200:
            logger.error("EU sanctions: HTTP request failed")
            return None

        text = response.text
        try:
            with open(_CACHE_PATH, "w", encoding="utf-8", errors="replace") as fh:
                fh.write(text)
            logger.debug("EU sanctions: cached list to %s", _CACHE_PATH)
        except OSError as exc:
            logger.warning("EU sanctions: could not write cache: %s", exc)

        return text

    def _search(self, csv_text: str, query: str) -> list[dict[str, Any]]:
        """Search the EU sanctions CSV for matching names."""
        matches: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        try:
            reader = csv.reader(io.StringIO(csv_text))
        except Exception as exc:
            logger.warning("EU sanctions: CSV parse error: %s", exc)
            return []

        for row in reader:
            if len(row) < 6:
                continue

            # Extract candidate name fields
            first = row[3].strip() if len(row) > 3 else ""
            middle = row[4].strip() if len(row) > 4 else ""
            last = row[5].strip() if len(row) > 5 else ""
            whole = row[6].strip() if len(row) > 6 else ""
            entity_id = row[1].strip() if len(row) > 1 else ""
            subject_type = row[8].strip() if len(row) > 8 else ""

            # Build candidate string for matching
            candidates = []
            if whole:
                candidates.append(whole)
            if first or last:
                candidates.append(f"{first} {middle} {last}".strip())

            best_score = 0.0
            for cand in candidates:
                score = _name_overlap_score(query, cand)
                if score > best_score:
                    best_score = score

            if best_score < _MATCH_THRESHOLD:
                continue

            # Deduplicate by entity_id
            if entity_id and entity_id in seen_ids:
                continue
            if entity_id:  # pragma: no branch
                seen_ids.add(entity_id)

            matches.append(
                {
                    "entity_id": entity_id,
                    "whole_name": whole,
                    "first_name": first,
                    "last_name": last,
                    "subject_type": subject_type,
                    "match_score": round(best_score, 3),
                }
            )

        matches.sort(key=lambda m: m["match_score"], reverse=True)
        return matches
