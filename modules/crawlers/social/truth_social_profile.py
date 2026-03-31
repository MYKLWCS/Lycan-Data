"""
truth_social_profile.py — Truth Social public profile scraper.

Scrapes publicly visible Truth Social profiles at:
  https://truthsocial.com/@USERNAME

Also supports name-based search using Truth Social's public Mastodon-compatible
API endpoint.

No API key required for public profiles.

Registered as "truth_social_profile".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_PROFILE_URL = "https://truthsocial.com/@{username}"
# Truth Social runs on a Mastodon fork — use the Mastodon-compatible API
_API_ACCOUNT_LOOKUP = "https://truthsocial.com/api/v1/accounts/lookup?acct={username}"
_API_ACCOUNT_STATUSES = "https://truthsocial.com/api/v1/accounts/{account_id}/statuses?limit=20"
_API_SEARCH = "https://truthsocial.com/api/v2/search?q={query}&type=accounts&limit=10"

_MAX_POSTS = 20


def _is_name_search(identifier: str) -> bool:
    """Return True when identifier starts with 'name:' prefix."""
    return identifier.lower().startswith("name:")


def _extract_name_query(identifier: str) -> str:
    return identifier[5:].strip()


def _clean_html(text: str) -> str:
    """Strip HTML tags from Truth Social post content."""
    return re.sub(r"<[^>]+>", " ", text).strip()


def _parse_account(data: dict) -> dict[str, Any]:
    """Normalise a Mastodon-format account object."""
    display_name = data.get("display_name") or data.get("username", "")
    username = data.get("username", "")
    account_id = str(data.get("id", ""))
    note = _clean_html(data.get("note") or "")
    avatar = data.get("avatar") or data.get("avatar_static", "")
    created_at = data.get("created_at", "")
    fields: list[dict[str, Any]] = data.get("fields") or []

    counters = {
        "follower_count": data.get("followers_count", 0),
        "following_count": data.get("following_count", 0),
        "post_count": data.get("statuses_count", 0),
    }

    return {
        "account_id": account_id,
        "username": username,
        "display_name": display_name,
        "bio": note,
        "follower_count": counters["follower_count"],
        "following_count": counters["following_count"],
        "post_count": counters["post_count"],
        "joined_date": created_at,
        "profile_image_url": avatar,
        "profile_url": f"https://truthsocial.com/@{username}",
        "is_verified": data.get("verified", False),
        "is_bot": data.get("bot", False),
        "custom_fields": [
            {"label": f.get("name", ""), "value": _clean_html(f.get("value", ""))} for f in fields
        ],
    }


def _parse_statuses(data: list) -> list[dict[str, Any]]:
    """
    Parse a list of Mastodon-format status objects into simplified post records.
    """
    posts: list[dict[str, Any]] = []
    for status in data[:_MAX_POSTS]:
        if not isinstance(status, dict):
            continue
        # Handle retruth (reblog) vs original
        is_retruth = bool(status.get("reblog"))
        content_raw = (
            status.get("reblog", {}).get("content", "") if is_retruth else status.get("content", "")
        )
        content = _clean_html(content_raw)[:500]
        url = status.get("reblog", {}).get("url", "") if is_retruth else status.get("url", "")
        posts.append(
            {
                "post_id": str(status.get("id", "")),
                "content": content,
                "created_at": status.get("created_at", ""),
                "url": url,
                "reply_count": status.get("replies_count", 0),
                "retruth_count": status.get("reblogs_count", 0),
                "favourite_count": status.get("favourites_count", 0),
                "is_retruth": is_retruth,
                "language": status.get("language", ""),
            }
        )
    return posts


def _parse_profile_html(html: str) -> dict[str, Any]:
    """
    Fallback HTML scraper for Truth Social profile pages.
    Used when the API endpoints return 401/403 or unexpected responses.
    """
    result: dict[str, Any] = {}
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Display name
        name_el = (
            soup.select_one(".account__header__tabs__name h1")
            or soup.select_one("h1.display-name")
            or soup.select_one("h1")
        )
        if name_el:
            result["display_name"] = name_el.get_text(strip=True)

        # Bio
        bio_el = soup.select_one(".account__header__content, .bio, .note")
        if bio_el:
            result["bio"] = _clean_html(str(bio_el))[:500]

        # Follower/following/post counts — look for stat blocks
        for stat_el in soup.select(".account__header__bar .counter, .counter-number, .stat"):
            label_el = stat_el.select_one(".counter-label, .label, small")
            value_el = stat_el.select_one(".counter-number, strong, span")
            if label_el and value_el:
                label = label_el.get_text(strip=True).lower()
                value_text = value_el.get_text(strip=True).replace(",", "")
                try:
                    value = int(value_text)
                except ValueError:
                    continue
                if "follower" in label:
                    result["follower_count"] = value
                elif "following" in label:
                    result["following_count"] = value
                elif "post" in label or "trut" in label or "status" in label:
                    result["post_count"] = value

        # Profile image
        img_el = (
            soup.select_one(".account__header__tabs__name img")
            or soup.select_one(".account__avatar img")
            or soup.select_one("img.avatar")
        )
        if img_el:
            result["profile_image_url"] = img_el.get("src", "")

        # Joined date — look for a "Joined" label
        for el in soup.find_all(string=re.compile(r"Joined", re.I)):
            parent = el.parent
            if parent:
                result["joined_date"] = parent.get_text(strip=True).replace("Joined", "").strip()
                break

        # Recent posts
        posts: list[dict[str, Any]] = []
        for post_el in soup.select(".status, .entry, .post")[:_MAX_POSTS]:
            text_el = post_el.select_one(".status__content, .content, p")
            time_el = post_el.select_one("time, .timestamp")
            if text_el:
                posts.append(
                    {
                        "content": _clean_html(str(text_el))[:500],
                        "created_at": time_el.get("datetime", "") if time_el else "",
                        "url": "",
                        "is_retruth": False,
                    }
                )
        if posts:
            result["recent_posts"] = posts

    except Exception as exc:
        logger.debug("Truth Social HTML parse error: %s", exc)

    return result


@register("truth_social_profile")
class TruthSocialProfileCrawler(HttpxCrawler):
    """
    Scrapes Truth Social public profiles.

    Uses the Mastodon-compatible API (no key required for public data),
    with HTML scraping as a fallback.

    identifier: Truth Social username (e.g. "realDonaldTrump")
                or "name:John Smith" for name-based search

    Data keys returned:
        username          — Truth Social handle
        display_name      — displayed full name
        bio               — profile bio text
        follower_count    — number of followers
        following_count   — number following
        post_count        — number of posts
        joined_date       — account creation date (ISO 8601)
        recent_posts      — list of up to 20 recent posts
        profile_image_url — avatar URL
        profile_url       — canonical profile URL
        is_verified       — bool
        is_bot            — bool
    """

    platform = "truth_social_profile"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.70
    requires_tor = False
    proxy_tier = "datacenter"

    async def scrape(self, identifier: str) -> CrawlerResult:
        if _is_name_search(identifier):
            name_query = _extract_name_query(identifier)
            profile_data = await self._search_by_name(name_query)
            query = name_query
        else:
            username = identifier.strip().lstrip("@")
            profile_data = await self._fetch_by_username(username)
            query = username

        if not profile_data:
            return self._result(
                identifier,
                found=False,
                error="not_found",
                query=query,
            )

        profile_url = profile_data.get("profile_url", "")
        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data=profile_data,
            profile_url=profile_url or None,
            source_reliability=self.source_reliability,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_by_username(self, username: str) -> dict[str, Any] | None:
        """Fetch a specific profile by username using the API, then HTML fallback."""
        # Step 1: Account lookup API
        lookup_url = _API_ACCOUNT_LOOKUP.format(username=username)
        resp = await self.get(lookup_url, headers={"Accept": "application/json"})
        account_data: dict[str, Any] = {}

        if resp is not None and resp.status_code == 200:
            try:
                account_data = _parse_account(resp.json())
            except Exception as exc:
                logger.debug("Truth Social account lookup parse error: %s", exc)

        # Step 2: Fetch recent posts using account ID
        if account_data.get("account_id"):
            posts = await self._fetch_statuses(account_data["account_id"])
            account_data["recent_posts"] = posts
            return account_data

        # Step 3: HTML fallback
        profile_url = _PROFILE_URL.format(username=username)
        resp = await self.get(profile_url)
        if resp is None or resp.status_code not in (200, 206):
            return None
        html_data = _parse_profile_html(resp.text)
        if not html_data.get("display_name"):
            return None
        html_data["username"] = username
        html_data["profile_url"] = profile_url
        return html_data

    async def _fetch_statuses(self, account_id: str) -> list[dict[str, Any]]:
        """Fetch recent public statuses for a given account ID."""
        url = _API_ACCOUNT_STATUSES.format(account_id=account_id)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is None or resp.status_code != 200:
            return []
        try:
            data = resp.json()
            if isinstance(data, list):
                return _parse_statuses(data)
        except Exception as exc:
            logger.debug("Truth Social statuses parse error: %s", exc)
        return []

    async def _search_by_name(self, name: str) -> dict[str, Any] | None:
        """Search Truth Social accounts by display name."""
        encoded = quote_plus(name)
        url = _API_SEARCH.format(query=encoded)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is None or resp.status_code != 200:
            logger.debug("Truth Social search returned %s", resp.status_code if resp else "None")
            return None
        try:
            data = resp.json()
            accounts = data.get("accounts", [])
            if not accounts:
                return None
            # Return the first result
            account_data = _parse_account(accounts[0])
            if account_data.get("account_id"):
                posts = await self._fetch_statuses(account_data["account_id"])
                account_data["recent_posts"] = posts
            return account_data
        except Exception as exc:
            logger.debug("Truth Social search parse error: %s", exc)
            return None
