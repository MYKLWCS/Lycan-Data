"""
vk_profile.py — VK.com public profile scraper.

Scrapes publicly visible VK profile pages (vk.com/username or vk.com/id123456).
No API key required — scrapes the public web interface.

Uses Tor/residential proxy for Russian-IP-sensitive content and to avoid
rate limiting on the VK public API edge.

Registered as "vk_profile".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_VK_PROFILE_URL = "https://vk.com/{username}"
_VK_SEARCH_URL = "https://vk.com/search?c[section]=people&c[q]={query}"
# VK also exposes a mobile-friendly endpoint that's less JS-heavy
_VK_MOBILE_URL = "https://m.vk.com/{username}"
# Public VK API endpoint for basic user info (no auth for public profiles)
_VK_API_SEARCH = (
    "https://api.vk.com/method/users.search"
    "?q={query}&fields=city,country,photo_max,status,bdate,education,career"
    "&count=10&v=5.131"
)
_VK_API_USER = (
    "https://api.vk.com/method/users.get"
    "?user_ids={user_id}"
    "&fields=city,country,photo_max_orig,status,bdate,education,career,"
    "contacts,followers_count,counters,relation"
    "&v=5.131"
)


def _is_username(identifier: str) -> bool:
    """Return True if identifier looks like a VK username (no spaces, no |)."""
    return "|" not in identifier and " " not in identifier.strip()


def _extract_username(identifier: str) -> str:
    """Extract clean username, stripping vk.com/ prefix if present."""
    uid = identifier.strip()
    for prefix in ("https://vk.com/", "http://vk.com/", "vk.com/"):
        if uid.lower().startswith(prefix):
            uid = uid[len(prefix) :]
    return uid


def _parse_name_country(identifier: str) -> tuple[str, str]:
    """Parse "John Smith | Russia" into (name, country)."""
    parts = identifier.split("|", 1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def _parse_vk_api_user(data: Any) -> dict[str, Any] | None:
    """Parse VK API users.get or users.search response."""
    try:
        if isinstance(data, dict):
            response = data.get("response", [])
            if isinstance(response, list) and response:
                user = response[0]
            elif isinstance(response, dict):
                items = response.get("items", [])
                user = items[0] if items else {}
            else:
                return None
        elif isinstance(data, list) and data:
            user = data[0]
        else:
            return None

        first_name = user.get("first_name", "")
        last_name = user.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip()
        user_id = user.get("id", "")
        deactivated = user.get("deactivated", "")

        city = user.get("city", {})
        city_name = city.get("title", "") if isinstance(city, dict) else str(city)
        country = user.get("country", {})
        country_name = country.get("title", "") if isinstance(country, dict) else str(country)

        counters = user.get("counters", {}) or {}

        career_list = user.get("career", []) or []
        career_items: list[dict[str, Any]] = []
        for job in career_list:
            if isinstance(job, dict):
                career_items.append(
                    {
                        "company": job.get("company", ""),
                        "position": job.get("position", ""),
                        "from": job.get("from"),
                        "until": job.get("until"),
                    }
                )

        education = user.get("education", {}) or {}
        university = education.get("university_name", "") if isinstance(education, dict) else ""

        return {
            "vk_id": str(user_id),
            "display_name": full_name,
            "first_name": first_name,
            "last_name": last_name,
            "is_active": not bool(deactivated),
            "deactivated": deactivated,
            "status": user.get("status", ""),
            "birth_date": user.get("bdate", ""),
            "city": city_name,
            "country": country_name,
            "follower_count": counters.get("followers", 0),
            "friends_count": counters.get("friends", 0),
            "photos_count": counters.get("photos", 0),
            "posts_count": counters.get("wall", 0),
            "groups_count": counters.get("groups", 0),
            "profile_image_url": user.get("photo_max_orig") or user.get("photo_max", ""),
            "education_university": university,
            "career": career_items,
            "profile_url": f"https://vk.com/id{user_id}",
        }
    except Exception as exc:
        logger.debug("VK API parse error: %s", exc)
        return None


def _parse_vk_html(html: str) -> dict[str, Any]:
    """
    Fallback: parse the VK mobile profile HTML page.
    Extracts display name, city, workplace, followers from the rendered page.
    """
    result: dict[str, Any] = {}
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Name: usually in <h1> or .profile_name
        name_el = (
            soup.select_one("h1.profile_name") or soup.select_one("h1") or soup.select_one(".name")
        )
        if name_el:
            result["display_name"] = name_el.get_text(strip=True)

        # Status / bio
        status_el = soup.select_one(".status, .profile_status, .page_block_status")
        if status_el:
            result["status"] = status_el.get_text(strip=True)

        # City
        city_el = soup.select_one(".pp_city, .city, [data-field='city']")
        if city_el:
            result["city"] = city_el.get_text(strip=True)

        # Followers — look for a counter near a "followers" label
        for el in soup.find_all(string=re.compile(r"\bfollower", re.I)):
            parent = el.parent
            if parent:
                count_text = parent.get_text(strip=True)
                m = re.search(r"([\d\s,]+)", count_text)
                if m:
                    try:
                        result["follower_count"] = int(m.group(1).replace(",", "").replace(" ", ""))
                    except ValueError:
                        pass
                    break

        # Profile image
        img_el = (
            soup.select_one(".profile_avatar img")
            or soup.select_one(".userpic img")
            or soup.select_one(".photo img")
        )
        if img_el:
            result["profile_image_url"] = img_el.get("src", "")

        # Posts — look for wall entries
        posts: list[dict[str, Any]] = []
        for post_el in soup.select(".wall_item, .post, ._post")[:10]:
            text_el = post_el.select_one(".pi_text, .wall_post_text, .post_text")
            date_el = post_el.select_one(".pi_date, time, .rel_date")
            posts.append(
                {
                    "text": text_el.get_text(strip=True)[:280] if text_el else "",
                    "date": date_el.get_text(strip=True) if date_el else "",
                }
            )
        if posts:
            result["recent_posts"] = posts

    except Exception as exc:
        logger.debug("VK HTML parse error: %s", exc)

    return result


@register("vk_profile")
class VkProfileCrawler(HttpxCrawler):
    """
    Scrapes public VK.com profile pages.

    When given a username, fetches the profile directly.
    When given "Name | Country", searches VK people search and returns
    the top matching profile.

    identifier: VK username (e.g. "durov") or "John Smith | Russia"

    Data keys returned:
        vk_id             — VK numeric user ID
        display_name      — full display name
        first_name        — first name
        last_name         — last name
        status            — profile status/bio text
        birth_date        — birthdate if public
        city              — current city
        country           — country
        follower_count    — number of followers
        friends_count     — number of friends
        photos_count      — photo count
        posts_count       — wall post count
        profile_image_url — avatar URL
        education_university — university name if listed
        career            — list of {company, position, from, until}
        recent_posts      — list of recent public posts (HTML fallback)
        profile_url       — canonical VK profile URL
        is_active         — bool (False if account deleted/banned)
    """

    platform = "vk_profile"
    source_reliability = 0.72
    requires_tor = True
    proxy_tier = "residential"

    async def scrape(self, identifier: str) -> CrawlerResult:
        if _is_username(identifier):
            username = _extract_username(identifier)
            profile = await self._fetch_by_username(username)
        else:
            name, country = _parse_name_country(identifier)
            profile = await self._search_by_name(name, country)

        if not profile:
            return self._result(
                identifier,
                found=False,
                error="not_found",
                query=identifier,
            )

        profile_url = profile.get("profile_url", "")
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data=profile,
            profile_url=profile_url or None,
            source_reliability=self.source_reliability,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_by_username(self, username: str) -> dict[str, Any] | None:
        """Fetch VK profile by known username, trying API then HTML fallback."""
        api_url = _VK_API_USER.format(user_id=username)
        resp = await self.get(api_url, headers={"Accept": "application/json"})
        if resp is not None and resp.status_code == 200:
            try:
                parsed = _parse_vk_api_user(resp.json())
                if parsed:
                    return parsed
            except Exception as exc:
                logger.debug("VK API user parse error: %s", exc)

        # HTML fallback — mobile version is lighter
        mobile_url = _VK_MOBILE_URL.format(username=username)
        resp = await self.get(mobile_url)
        if resp is None or resp.status_code not in (200, 206):
            return None
        parsed = _parse_vk_html(resp.text)
        if not parsed.get("display_name"):
            return None
        parsed["profile_url"] = f"https://vk.com/{username}"
        return parsed

    async def _search_by_name(self, name: str, country: str) -> dict[str, Any] | None:
        """Search VK for a person by name using the users.search API."""
        encoded = quote_plus(name)
        url = _VK_API_SEARCH.format(query=encoded)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is not None and resp.status_code == 200:
            try:
                parsed = _parse_vk_api_user(resp.json())
                if parsed:
                    return parsed
            except Exception as exc:
                logger.debug("VK search API error: %s", exc)

        # HTML people search fallback
        search_url = _VK_SEARCH_URL.format(query=encoded)
        resp = await self.get(search_url)
        if resp is None or resp.status_code not in (200, 206):
            return None
        parsed = _parse_vk_html(resp.text)
        return parsed if parsed.get("display_name") else None
