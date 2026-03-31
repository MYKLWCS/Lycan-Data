"""
idcrawl.py — IDCrawl people-search crawler.

Searches https://www.idcrawl.com/{name} for social profiles, phone numbers,
and email addresses. Light or no Cloudflare protection.

Registered as "idcrawl".
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


@register("idcrawl")
class IDCrawlCrawler(CurlCrawler):
    """Scrapes IDCrawl for social profiles, phone numbers, and emails by name."""

    platform = "idcrawl"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.3, burst_size=2, cooldown_seconds=3.0)
    source_reliability = 0.55
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        # Parse "First Last|City,State" format — use name only for URL
        name = identifier.split("|")[0].strip()
        if not name:
            return self._result(identifier, found=False)

        slug = name.lower().replace(" ", "-")
        url = f"https://www.idcrawl.com/{slug}"

        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        persons = _parse_idcrawl(resp.text)
        phones = _extract_phones(resp.text)
        emails = _extract_emails(resp.text)
        social_links = _extract_social_links(resp.text)

        has_data = bool(persons or phones or emails or social_links)

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=has_data,
            data={
                "persons": persons[:10],
                "phones": phones[:10],
                "emails": emails[:10],
                "social_links": social_links[:20],
                "profile_url": url,
            },
            source_reliability=self.source_reliability,
        )


def _parse_idcrawl(html: str) -> list[dict]:
    """Parse person result cards from IDCrawl HTML."""
    persons = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(
            "div.result, div.person, div[class*='result'], div[class*='person'], article.result"
        )
        for card in cards[:10]:
            person = {}
            name_el = card.find(["h2", "h3", "h4"])
            if name_el:
                person["name"] = name_el.get_text(strip=True)

            # Address
            addr_el = card.find(class_=lambda c: c and "address" in c.lower() if c else False)
            if addr_el:
                person["address"] = addr_el.get_text(strip=True)

            # Age
            card_text = card.get_text(" ", strip=True)
            age_match = re.search(r"[Aa]ge\s+(\d{1,3})", card_text)
            if age_match:
                person["age"] = int(age_match.group(1))

            if person.get("name"):
                persons.append(person)
    except Exception as exc:
        logger.debug("IDCrawl parse error: %s", exc)
    return persons


def _extract_phones(html: str) -> list[str]:
    """Extract phone numbers from page text."""
    phones = []
    for match in _PHONE_RE.findall(html):
        digits = re.sub(r"[^\d]", "", match)
        if 7 <= len(digits) <= 11:
            phones.append(match.strip())
    return list(dict.fromkeys(phones))


def _extract_emails(html: str) -> list[str]:
    """Extract email addresses from page text."""
    emails = []
    for match in _EMAIL_RE.findall(html):
        lower = match.lower()
        if not any(s in lower for s in ["example.", "test.", "email.", "idcrawl"]):
            emails.append(lower)
    return list(dict.fromkeys(emails))


def _extract_social_links(html: str) -> list[dict]:
    """Extract social media profile links from page."""
    social_re = re.compile(
        r"https?://(?:www\.)?(twitter|x|instagram|facebook|linkedin|github|"
        r"youtube|tiktok|pinterest|reddit)\.com/([a-zA-Z0-9_.]+)",
        re.IGNORECASE,
    )
    links = []
    seen = set()
    for m in social_re.finditer(html):
        key = (m.group(1).lower(), m.group(2).lower())
        if key not in seen:
            seen.add(key)
            links.append(
                {
                    "platform": m.group(1).lower(),
                    "handle": m.group(2),
                    "url": m.group(0),
                }
            )
    return links
