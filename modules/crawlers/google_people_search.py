"""
google_people_search.py — Extract people data from multiple free search APIs.

Uses DuckDuckGo Instant Answer API + Bing search to find phone numbers,
emails, addresses, social links from search results. No API key needed.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_PHONE_RE = re.compile(r'[\+]?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
_SOCIAL_RE = re.compile(
    r'https?://(?:www\.)?(twitter|x|instagram|facebook|linkedin|github)\.com/([a-zA-Z0-9_.]+)',
    re.IGNORECASE,
)


@register("google_people_search")
class GooglePeopleSearchCrawler(HttpxCrawler):
    """Extract people data from free search APIs."""

    platform = "google_people_search"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.5
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        name = identifier.strip()
        if not name:
            return self._result(identifier, found=False)

        phones = set()
        emails = set()
        social_links = []
        abstract = ""
        image = ""

        # Source 1: DuckDuckGo Instant Answer API (always works, no CAPTCHA)
        try:
            ddg_url = f"https://api.duckduckgo.com/?q={quote_plus(name)}&format=json&no_redirect=1"
            resp = await self.get(ddg_url)
            if resp and resp.status_code == 200:
                data = resp.json()
                abstract = data.get("Abstract", "") or data.get("AbstractText", "")
                image = data.get("Image", "")
                # Extract from related topics
                for topic in data.get("RelatedTopics", []):
                    if isinstance(topic, dict):
                        text = topic.get("Text", "")
                        for ph in _PHONE_RE.findall(text):
                            phones.add(ph.strip())
                        for em in _EMAIL_RE.findall(text):
                            emails.add(em.lower())
                        first_url = topic.get("FirstURL", "")
                        for m in _SOCIAL_RE.finditer(first_url):
                            social_links.append({"platform": m.group(1), "handle": m.group(2), "url": m.group(0)})
        except Exception:
            pass

        # Source 2: Bing search (often not blocked)
        try:
            bing_url = f"https://www.bing.com/search?q={quote_plus(name + ' phone email')}"
            resp2 = await self.get(bing_url)
            if resp2 and resp2.status_code == 200:
                soup = BeautifulSoup(resp2.text, "html.parser")
                for elem in soup.select("li.b_algo, .b_caption"):
                    text = elem.get_text(" ", strip=True)
                    for ph in _PHONE_RE.findall(text):
                        digits = re.sub(r'[^\d]', '', ph)
                        if 7 <= len(digits) <= 11:
                            phones.add(ph.strip())
                    for em in _EMAIL_RE.findall(text):
                        if not any(s in em for s in ['example.', 'test.', 'email.']):
                            emails.add(em.lower())
                # Extract social links from Bing results
                for a in soup.select("a[href]"):
                    href = a.get("href", "")
                    for m in _SOCIAL_RE.finditer(href):
                        social_links.append({"platform": m.group(1), "handle": m.group(2), "url": m.group(0)})
        except Exception:
            pass

        has_data = bool(phones or emails or social_links or abstract)

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=has_data,
            data={
                "phones": list(phones)[:10],
                "emails": list(emails)[:10],
                "social_links": social_links[:10],
                "abstract": abstract[:500] if abstract else "",
                "profile_image_url": image if image else None,
            },
            source_reliability=self.source_reliability,
        )
