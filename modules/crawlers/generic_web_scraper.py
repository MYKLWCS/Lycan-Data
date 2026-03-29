"""Generic web scraper — extracts emails, phones, social links from any URL."""
import re
import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.registry import register
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(r'[\+]?[(]?[0-9]{1,4}[)]?[-\s./0-9]{7,15}')
_SOCIAL_RE = re.compile(
    r'https?://(?:www\.)?(twitter|x|instagram|facebook|linkedin|github|tiktok|youtube)'
    r'\.com/([a-zA-Z0-9_.]+)', re.IGNORECASE,
)


@register("generic_web_scraper")
class GenericWebScraper(HttpxCrawler):
    """Scrapes any URL for contact info and social links."""
    platform = "generic_web_scraper"
    category = CrawlerCategory.OTHER
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.4
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        url = identifier
        try:
            resp = await self.get(url)
            if not resp or resp.status_code != 200:
                return self._result(identifier, found=False)
            text = resp.text
            emails = list(set(_EMAIL_RE.findall(text)))[:20]
            phones = list(set(_PHONE_RE.findall(text)))[:10]
            social_links = [
                {"platform": m.group(1).lower(), "handle": m.group(2), "url": m.group(0)}
                for m in _SOCIAL_RE.finditer(text)
            ]
            return CrawlerResult(
                platform="generic_web_scraper",
                identifier=url,
                found=bool(emails or phones or social_links),
                data={"url": url, "emails": emails, "phones": phones, "social_links": social_links},
                profile_url=url,
                source_reliability=0.4,
            )
        except Exception as exc:
            logger.warning("Generic scraper failed for %s: %s", url, exc)
            return CrawlerResult(platform="generic_web_scraper", identifier=url, found=False, data={})
