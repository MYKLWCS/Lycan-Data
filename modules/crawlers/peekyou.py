"""
peekyou.py — PeekYou people-search scraper.

PeekYou aggregates social profiles and web presence for a given name.
URL: https://www.peekyou.com/{first}.{last}/

Registered as "peekyou".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup

from modules.crawlers.playwright_base import PlaywrightCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_BASE = "https://www.peekyou.com"


def _build_url(identifier: str) -> str:
    """Build PeekYou URL from a name or username identifier."""
    parts = identifier.strip().split()
    if len(parts) >= 2:
        first = quote(parts[0].lower(), safe="")
        last = quote(parts[-1].lower(), safe="")
        return f"{_BASE}/{first}.{last}/"
    # Single token — try direct path
    slug = quote(parts[0].lower(), safe="")
    return f"{_BASE}/{slug}/"


def _parse_profiles(html: str) -> list[dict[str, Any]]:
    """Extract social profile links and web presence from PeekYou HTML."""
    profiles: list[dict[str, Any]] = []
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Each person result is in a .person_cell or article block
        cards = soup.select(
            "li.person_cell, div.person_cell, article.person, div[class*='person']"
        )
        if not cards:
            # Fallback: look for any structured name + link block
            cards = soup.select("div.result, li.result")

        for card in cards:
            person: dict[str, Any] = {}

            # Name
            name_tag = card.select_one(
                "h2, h3, .name, [class*='name'], [itemprop='name']"
            )
            if name_tag:
                person["name"] = name_tag.get_text(strip=True)

            # Location
            loc_tag = card.select_one(
                ".location, [class*='location'], [itemprop='addressLocality']"
            )
            if loc_tag:
                person["location"] = loc_tag.get_text(strip=True)

            # Age
            card_text = card.get_text(" ", strip=True)
            age_m = re.search(r"[Aa]ge\s+(\d{1,3})", card_text)
            if age_m:
                person["age"] = int(age_m.group(1))

            # Social links — PeekYou often renders as icon links
            social_links: list[dict[str, str]] = []
            for a in card.select("a[href]"):
                href = a.get("href", "")
                if not href or href.startswith("#"):
                    continue
                label = a.get_text(strip=True) or a.get("aria-label", "")
                # Detect social platforms by domain
                for platform in (
                    "twitter", "facebook", "instagram", "linkedin",
                    "youtube", "pinterest", "tiktok", "reddit",
                ):
                    if platform in href.lower():
                        social_links.append({"platform": platform, "url": href, "label": label})
                        break
                else:
                    if href.startswith("http") and "peekyou" not in href:
                        social_links.append({"platform": "web", "url": href, "label": label})

            if social_links:
                person["social_links"] = social_links

            # Profile URL on PeekYou
            detail_a = card.select_one("a[href*='/p/'], a[href*='/person/']")
            if detail_a:
                person["profile_url"] = detail_a.get("href", "")

            if person.get("name") or person.get("social_links"):
                profiles.append(person)

    except Exception as exc:
        logger.warning("PeekYou HTML parse error: %s", exc)

    return profiles


@register("peekyou")
class PeekYouCrawler(PlaywrightCrawler):
    """
    Scrapes PeekYou for social profiles and web presence.

    identifier: full name (e.g. "John Smith")
    Returns social profile links, location, and age estimates.

    source_reliability: 0.60 — aggregated but often outdated links.
    """

    platform = "peekyou"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.3, burst_size=2, cooldown_seconds=3.0)
    source_reliability = 0.60
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        url = _build_url(identifier)

        async with self.page(url) as page:
            if await self.is_blocked(page):
                await self.rotate_circuit()
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="bot_block",
                    source_reliability=self.source_reliability,
                )

            content = await page.content()

        profiles = _parse_profiles(content)
        found = bool(profiles)

        return self._result(
            identifier,
            found=found,
            profiles=profiles,
            profile_count=len(profiles),
            query_url=url,
        )
