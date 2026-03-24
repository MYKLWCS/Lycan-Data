"""
FBI Most Wanted list scraper.
Source: https://api.fbi.gov/wanted/v1/list

Registered as: sanctions_fbi
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

FBI_API_BASE = "https://api.fbi.gov/wanted/v1/list"
MATCH_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Name-matching helper
# ---------------------------------------------------------------------------

def _name_matches(query: str, candidate: str, threshold: float = MATCH_THRESHOLD) -> float:
    """Returns a match score 0.0–1.0 based on word overlap."""
    q_words = set(query.lower().split())
    c_words = set(candidate.lower().split())
    if not q_words:
        return 0.0
    overlap = len(q_words & c_words)
    score = overlap / len(q_words)
    return score


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

@register("sanctions_fbi")
class SanctionsFBICrawler(HttpxCrawler):
    """
    Queries the FBI Most Wanted public API by name and returns matching
    fugitive records. No caching — live API call per search.
    """

    platform = "sanctions_fbi"
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        """Search the FBI Most Wanted API for the given name."""
        url = f"{FBI_API_BASE}?pageSize=20&title={quote(identifier)}"
        response = await self.get(url)

        if response is None or response.status_code != 200:
            logger.error("FBI: API request failed (status=%s)", getattr(response, "status_code", "N/A"))
            return self._result(
                identifier,
                found=False,
                error="Failed to reach FBI Most Wanted API",
                matches=[],
                match_count=0,
                query=identifier,
            )

        try:
            payload = response.json()
        except Exception as exc:
            logger.error("FBI: JSON decode error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="FBI API returned invalid JSON",
                matches=[],
                match_count=0,
                query=identifier,
            )

        items = payload.get("items", [])
        matches = self._filter_items(items, identifier)

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

    def _filter_items(self, items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        """
        Filter API result items to those that match the query by name or alias.

        Each item JSON structure (relevant fields):
          {
            "title": "JOHN WILLIAM SMITH",
            "description": "...",
            "aliases": ["Johnny Smith", ...],
            "subjects": ["Fugitive"],
            "field_offices": ["houston"],
            "reward_text": "$10,000",
            "url": "https://www.fbi.gov/wanted/...",
            "images": [{"large": "...", "thumb": "..."}]
          }
        """
        matches: list[dict[str, Any]] = []
        for item in items:
            title = item.get("title", "")
            aliases: list[str] = item.get("aliases") or []

            # Score against title and all aliases
            candidates = [title] + [a for a in aliases if a]
            best_score = max((_name_matches(query, c) for c in candidates if c), default=0.0)

            if best_score >= MATCH_THRESHOLD:
                matches.append(
                    {
                        "name": title,
                        "url": item.get("url", ""),
                        "reward": item.get("reward_text", ""),
                        "description": (item.get("description") or "")[:500],
                        "aliases": aliases,
                        "subjects": item.get("subjects") or [],
                        "field_offices": item.get("field_offices") or [],
                        "match_score": round(best_score, 3),
                    }
                )
        return matches
