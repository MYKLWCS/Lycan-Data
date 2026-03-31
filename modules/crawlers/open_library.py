"""
open_library.py — Open Library author search.

Free API, no key needed. Finds published books by a person.
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://openlibrary.org/search/authors.json?q={query}&limit=3"
_WORKS_URL = "https://openlibrary.org/authors/{key}/works.json?limit=10"


@register("open_library")
class OpenLibraryCrawler(HttpxCrawler):
    """Search Open Library for books authored by a person."""

    platform = "open_library"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=1.0)
    source_reliability = 0.7
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        if not query or len(query) < 3:
            return self._result(identifier, found=False)

        search_url = _SEARCH_URL.format(query=quote_plus(query))
        resp = await self.get(search_url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)

        try:
            data = resp.json()
            authors = data.get("docs", [])
        except Exception:
            return self._result(identifier, found=False, error="parse_error")

        if not authors:
            return self._result(identifier, found=False)

        author = authors[0]
        author_key = author.get("key", "")
        author_name = author.get("name", "")
        birth_date = author.get("birth_date", "")
        death_date = author.get("death_date", "")
        work_count = author.get("work_count", 0)
        top_subjects = author.get("top_subjects", [])[:10]
        top_work = author.get("top_work", "")

        # Get works list
        works = []
        if author_key:
            works_url = _WORKS_URL.format(key=author_key)
            resp2 = await self.get(works_url)
            if resp2 and resp2.status_code == 200:
                try:
                    entries = resp2.json().get("entries", [])
                    for w in entries[:10]:
                        works.append(
                            {
                                "title": w.get("title", ""),
                                "first_publish_year": w.get("first_publish_date", ""),
                                "subjects": [
                                    s for s in w.get("subjects", [])[:5] if isinstance(s, str)
                                ],
                            }
                        )
                except Exception:
                    logger.debug(
                        "Open Library works lookup failed for %s", identifier, exc_info=True
                    )

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=bool(author_name),
            data={
                "author_name": author_name,
                "birth_date": birth_date,
                "death_date": death_date,
                "work_count": work_count,
                "top_work": top_work,
                "top_subjects": top_subjects,
                "works": works,
                "author_key": author_key,
            },
            profile_url=f"https://openlibrary.org/authors/{author_key}" if author_key else None,
            source_reliability=self.source_reliability,
        )
