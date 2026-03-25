from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from modules.crawlers.playwright_base import PlaywrightCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.constants import SOURCE_RELIABILITY
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


@register("linkedin")
class LinkedInCrawler(PlaywrightCrawler):
    """
    Scrapes LinkedIn profiles.
    Strategy: direct profile page scrape. On auth-wall, falls back to
    scraping Google cache or LinkedIn's public-facing data.
    """

    platform = "linkedin"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = SOURCE_RELIABILITY.get("linkedin", 0.75)
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        # identifier can be a LinkedIn URL or a username
        if identifier.startswith("http"):
            url = identifier
            handle = (
                identifier.split("/in/")[-1].rstrip("/") if "/in/" in identifier else identifier
            )
        else:
            handle = identifier.lower().replace(" ", "-")
            url = f"https://www.linkedin.com/in/{handle}/"

        async with self.page(url) as page:
            content = await page.content()

            if "authwall" in page.url or "login" in page.url:
                # Hit auth wall — try public guest view
                return await self._try_public_view(handle)

            if "Page not found" in content or "profile does not exist" in content.lower():
                return self._result(handle, found=False, handle=handle)

            data = await self._extract(page, handle)

        return CrawlerResult(
            platform=self.platform,
            identifier=handle,
            found=bool(data.get("display_name")),
            data=data,
            profile_url=url,
            source_reliability=self.source_reliability,
        )

    async def _extract(self, page, handle: str) -> dict:
        data: dict = {"handle": handle}
        try:
            title = await page.title() or ""
            if "|" in title:
                data["display_name"] = title.split("|")[0].strip()
            elif "-" in title:
                data["display_name"] = title.split("-")[0].strip()

            # Headline
            headline = await page.query_selector(".top-card-layout__headline")
            if headline:
                data["headline"] = await headline.inner_text()

            # Location
            loc = await page.query_selector(".top-card__subline-item")
            if loc:
                data["location"] = await loc.inner_text()

            # Connection count
            conn = await page.query_selector(".top-card__connections-count")
            if conn:
                data["connections"] = await conn.inner_text()

            # Skills list
            skill_els = await page.query_selector_all(
                ".skill-categories-section .skill-name, .pv-skill-category-entity__name span"
            )
            if skill_els:
                skills = []
                for el in skill_els[:30]:
                    text = (await el.inner_text()).strip()
                    if text:
                        skills.append(text)
                if skills:
                    data["skills"] = skills

            # Endorsement count (sum across all skills)
            endorsement_els = await page.query_selector_all(
                ".pv-skill-category-entity__endorsement-count"
            )
            if endorsement_els:
                total_endorsements = 0
                for el in endorsement_els:
                    try:
                        count_text = (
                            (await el.inner_text()).strip().replace(",", "").replace("+", "")
                        )
                        total_endorsements += int(count_text)
                    except (ValueError, AttributeError):
                        pass
                data["endorsement_count"] = total_endorsements

            # Post count
            post_count_el = await page.query_selector(".pv-recent-activity-section__headline-text")
            if not post_count_el:
                post_count_el = await page.query_selector("[data-test-id='post-count']")
            if post_count_el:
                try:
                    pc_text = (await post_count_el.inner_text()).strip().split()[0].replace(",", "")
                    data["post_count"] = int(pc_text)
                except (ValueError, AttributeError):
                    pass

            # Education — degree, field, school
            education_items = []
            edu_els = await page.query_selector_all(
                ".education-section .pv-education-entity, "
                ".pv-profile-section__list-item.education-item"
            )
            for edu_el in edu_els[:5]:
                school_el = await edu_el.query_selector(
                    ".pv-entity__school-name, h3.pv-entity__school-name"
                )
                degree_el = await edu_el.query_selector(".pv-entity__degree-name span:nth-child(2)")
                field_el = await edu_el.query_selector(".pv-entity__fos span:nth-child(2)")
                dates_el = await edu_el.query_selector(".pv-entity__dates span:nth-child(2)")
                education_items.append(
                    {
                        "school": (await school_el.inner_text()).strip() if school_el else "",
                        "degree": (await degree_el.inner_text()).strip() if degree_el else "",
                        "field": (await field_el.inner_text()).strip() if field_el else "",
                        "dates": (await dates_el.inner_text()).strip() if dates_el else "",
                    }
                )
            if education_items:
                data["education"] = education_items

        except Exception as exc:
            logger.debug("LinkedIn extract error: %s", exc)
        return data

    async def _try_public_view(self, handle: str) -> CrawlerResult:
        """Try the Bing/Google cached version of the profile."""
        import httpx

        # LinkedIn exposes structured data on some profiles via their embed API
        url = f"https://www.linkedin.com/in/{handle}/"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    url,
                    headers={
                        "User-Agent": "LinkedInBot/1.0 (compatible; Mozilla/5.0)",
                        "Accept": "text/html",
                    },
                )
                if r.status_code == 200 and "authwall" not in str(r.url):
                    soup = BeautifulSoup(r.text, "html.parser")
                    name_tag = soup.find("h1")
                    data: dict = {"handle": handle}
                    if name_tag:
                        data["display_name"] = name_tag.get_text(strip=True)
                    return CrawlerResult(
                        platform=self.platform,
                        identifier=handle,
                        found=bool(data.get("display_name")),
                        data=data,
                        profile_url=url,
                        source_reliability=self.source_reliability * 0.7,  # lower confidence
                    )
        except Exception as exc:
            logger.debug("LinkedIn public view failed: %s", exc)
        return self._result(handle, found=False, error="auth_wall", handle=handle)
