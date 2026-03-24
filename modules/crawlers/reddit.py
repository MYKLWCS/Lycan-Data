from __future__ import annotations
import logging
from datetime import datetime, timezone

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.constants import SOURCE_RELIABILITY

logger = logging.getLogger(__name__)

REDDIT_API_BASE = "https://www.reddit.com"


@register("reddit")
class RedditCrawler(HttpxCrawler):
    """
    Scrapes Reddit profiles via the public JSON API (no auth needed).
    GET /user/{username}/about.json and /user/{username}/submitted.json
    """

    platform = "reddit"
    source_reliability = SOURCE_RELIABILITY.get("twitter", 0.55)  # similar reliability
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        handle = identifier.lstrip("u/").lstrip("/")
        url = f"{REDDIT_API_BASE}/user/{handle}/about.json"

        response = await self.get(url, headers={"Accept": "application/json"})
        if response is None:
            return self._result(handle, found=False, error="timeout")
        if response.status_code == 404:
            return self._result(handle, found=False, handle=handle)
        if response.status_code != 200:
            return self._result(handle, found=False, error=f"http_{response.status_code}")

        try:
            j = response.json()
        except Exception:
            return self._result(handle, found=False, error="parse_error")

        data_raw = j.get("data", {})
        if not data_raw:
            return self._result(handle, found=False, handle=handle)

        data = self._parse(data_raw, handle)

        # Fetch recent posts
        posts_url = f"{REDDIT_API_BASE}/user/{handle}/submitted.json?limit=25"
        posts_resp = await self.get(posts_url, headers={"Accept": "application/json"})
        if posts_resp and posts_resp.status_code == 200:
            try:
                posts_j = posts_resp.json()
                data["recent_posts"] = self._parse_posts(posts_j)
            except Exception:
                pass

        return CrawlerResult(
            platform=self.platform,
            identifier=handle,
            found=True,
            data=data,
            profile_url=f"https://reddit.com/u/{handle}",
            source_reliability=self.source_reliability,
        )

    def _parse(self, raw: dict, handle: str) -> dict:
        created_utc = raw.get("created_utc")
        created_at = None
        if created_utc:
            created_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)

        return {
            "handle": handle,
            "display_name": raw.get("name"),
            "platform_user_id": str(raw.get("id", "")),
            "post_count": raw.get("link_karma", 0) + raw.get("comment_karma", 0),
            "is_verified": raw.get("verified", False),
            "profile_created_at": created_at,
            "link_karma": raw.get("link_karma"),
            "comment_karma": raw.get("comment_karma"),
            "is_gold": raw.get("is_gold", False),
            "has_verified_email": raw.get("has_verified_email", False),
        }

    def _parse_posts(self, j: dict) -> list[dict]:
        posts = []
        for child in j.get("data", {}).get("children", [])[:25]:
            p = child.get("data", {})
            posts.append({
                "subreddit": p.get("subreddit"),
                "title": p.get("title", "")[:200],
                "score": p.get("score", 0),
                "created_utc": p.get("created_utc"),
            })
        return posts
