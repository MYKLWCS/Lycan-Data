"""
UN Consolidated Sanctions List scraper.
Source: https://scsanctions.un.org/resources/xml/en/consolidated.xml

Registered as: sanctions_un
"""

from __future__ import annotations

import logging
from typing import Any
from xml.etree import ElementTree as ET

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.utils import cache_valid, word_overlap

logger = logging.getLogger(__name__)

UN_XML_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
CACHE_PATH = "/tmp/lycan_un.xml"
CACHE_MAX_AGE_HOURS = 6.0
MATCH_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Cache helpers (shared pattern across sanction scrapers)
# ---------------------------------------------------------------------------


def _cache_path(name: str, ext: str) -> str:
    return f"/tmp/lycan_{name}.{ext}"


# ---------------------------------------------------------------------------
# Name-matching helper
# ---------------------------------------------------------------------------


def _text(element: ET.Element | None) -> str:
    """Safely extract stripped text from an XML element."""
    if element is None:
        return ""
    return (element.text or "").strip()


def _build_full_name(*parts: str) -> str:
    """Join non-empty name parts into a full name string."""
    return " ".join(p for p in parts if p).strip()


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("sanctions_un")
class SanctionsUNCrawler(HttpxCrawler):
    """
    Downloads the UN Consolidated Sanctions XML list, caches it for 6 hours,
    and searches both INDIVIDUAL and ENTITY records by name.
    """

    platform = "sanctions_un"
    category = CrawlerCategory.SANCTIONS_AML
    rate_limit = RateLimit(requests_per_second=2.0, burst_size=10, cooldown_seconds=0.0)
    source_reliability = 0.95
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        """Search the UN consolidated sanctions list for the given name."""
        xml_text = await self._get_xml()
        if xml_text is None:
            return self._result(
                identifier,
                found=False,
                error="Failed to download UN Consolidated Sanctions list",
                matches=[],
                match_count=0,
                query=identifier,
            )

        matches = self._search_xml(xml_text, identifier)
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

    async def _get_xml(self) -> str | None:
        """Return XML text from cache (if fresh) or download from UN."""
        if cache_valid(CACHE_PATH):
            logger.debug("UN: using cached list at %s", CACHE_PATH)
            try:
                with open(CACHE_PATH, encoding="utf-8") as fh:
                    return fh.read()
            except OSError as exc:
                logger.warning("UN: cache read failed: %s", exc)

        logger.info("UN: downloading consolidated list from %s", UN_XML_URL)
        response = await self.get(UN_XML_URL)
        if response is None or response.status_code != 200:
            logger.error("UN: HTTP request failed")
            return None

        text = response.text
        try:
            with open(CACHE_PATH, "w", encoding="utf-8") as fh:
                fh.write(text)
            logger.debug("UN: cached list to %s", CACHE_PATH)
        except OSError as exc:
            logger.warning("UN: could not write cache: %s", exc)

        return text

    def _search_xml(self, xml_text: str, query: str) -> list[dict[str, Any]]:
        """
        Parse the UN sanctions XML and return matching INDIVIDUAL and ENTITY records.

        XML structure (simplified):
          <CONSOLIDATED_LIST>
            <INDIVIDUALS>
              <INDIVIDUAL>
                <FIRST_NAME>...</FIRST_NAME>
                <SECOND_NAME>...</SECOND_NAME>
                <THIRD_NAME>...</THIRD_NAME>
                <UN_LIST_TYPE>...</UN_LIST_TYPE>
                <REFERENCE_NUMBER>...</REFERENCE_NUMBER>
                <INDIVIDUAL_ALIAS>
                  <ALIAS_NAME>...</ALIAS_NAME>
                </INDIVIDUAL_ALIAS>
              </INDIVIDUAL>
            </INDIVIDUALS>
            <ENTITIES>
              <ENTITY>
                <FIRST_NAME>...</FIRST_NAME>
                <UN_LIST_TYPE>...</UN_LIST_TYPE>
                <REFERENCE_NUMBER>...</REFERENCE_NUMBER>
                <ENTITY_ALIAS>
                  <ALIAS_NAME>...</ALIAS_NAME>
                </ENTITY_ALIAS>
              </ENTITY>
            </ENTITIES>
          </CONSOLIDATED_LIST>
        """
        matches: list[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.error("UN: XML parse error: %s", exc)
            return matches

        # Search individuals
        for individual in root.iter("INDIVIDUAL"):
            first = _text(individual.find("FIRST_NAME"))
            second = _text(individual.find("SECOND_NAME"))
            third = _text(individual.find("THIRD_NAME"))
            full_name = _build_full_name(first, second, third)
            reference = _text(individual.find("REFERENCE_NUMBER"))
            list_type = _text(individual.find("UN_LIST_TYPE"))

            aliases = [
                _text(alias.find("ALIAS_NAME"))
                for alias in individual.iter("INDIVIDUAL_ALIAS")
                if _text(alias.find("ALIAS_NAME"))
            ]

            # Check full name and all aliases
            candidates = [full_name] + aliases
            best_score = max((word_overlap(query, c) for c in candidates if c), default=0.0)

            if best_score >= MATCH_THRESHOLD:
                matches.append(
                    {
                        "name": full_name,
                        "reference": reference,
                        "list_type": list_type,
                        "aliases": aliases,
                        "match_score": round(best_score, 3),
                        "record_type": "individual",
                    }
                )

        # Search entities
        for entity in root.iter("ENTITY"):
            # Entities may use FIRST_NAME for the entity name in the UN XML schema
            first = _text(entity.find("FIRST_NAME"))
            second = _text(entity.find("SECOND_NAME"))
            third = _text(entity.find("THIRD_NAME"))
            full_name = _build_full_name(first, second, third)
            reference = _text(entity.find("REFERENCE_NUMBER"))
            list_type = _text(entity.find("UN_LIST_TYPE"))

            aliases = [
                _text(alias.find("ALIAS_NAME"))
                for alias in entity.iter("ENTITY_ALIAS")
                if _text(alias.find("ALIAS_NAME"))
            ]

            candidates = [full_name] + aliases
            best_score = max((word_overlap(query, c) for c in candidates if c), default=0.0)

            if best_score >= MATCH_THRESHOLD:
                matches.append(
                    {
                        "name": full_name,
                        "reference": reference,
                        "list_type": list_type,
                        "aliases": aliases,
                        "match_score": round(best_score, 3),
                        "record_type": "entity",
                    }
                )

        return matches
