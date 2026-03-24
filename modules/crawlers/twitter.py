from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.constants import SOURCE_RELIABILITY

logger = logging.getLogger(__name__)

# Known working nitter instances (fallback list)
NITTER_INSTANCES: list[str] = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.net",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]


@register("twitter")
class TwitterCrawler(HttpxCrawler):
    """Scrapes Twitter profiles via nitter mirrors (no auth required)."""

    platform = "twitter"
    source_reliability = SOURCE_RELIABILITY.get("twitter", 0.55)
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        handle = identifier.lstrip("@").lower()

        for instance in NITTER_INSTANCES:
            result = await self._try_instance(instance, handle)
            if result.found or result.error != "not_found":
                return result

        return self._result(handle, found=False, handle=handle, error="all_instances_failed")

    async def _try_instance(self, instance: str, handle: str) -> CrawlerResult:
        url = f"{instance}/{handle}"
        response = await self.get(url)
        if response is None or response.status_code != 200:
            return self._result(handle, found=False, error="http_error")

        soup = BeautifulSoup(response.text, "html.parser")

        if soup.find(class_="error-panel") or "User not found" in response.text:
            return self._result(handle, found=False, error="not_found")

        data = self._parse_profile(soup, handle)
        tweets = self._parse_tweets(soup)
        data["recent_tweets"] = tweets

        return CrawlerResult(
            platform=self.platform,
            identifier=handle,
            found=True,
            data=data,
            profile_url=f"https://twitter.com/{handle}",
            source_reliability=self.source_reliability,
        )

    def _parse_profile(self, soup: BeautifulSoup, handle: str) -> dict:
        data: dict = {"handle": handle}
        try:
            name_tag = soup.find(class_="profile-card-fullname")
            if name_tag:
                data["display_name"] = name_tag.get_text(strip=True)

            bio_tag = soup.find(class_="profile-bio")
            if bio_tag:
                data["bio"] = bio_tag.get_text(strip=True)[:500]

            stats = soup.find_all(class_="profile-stat-num")
            labels = soup.find_all(class_="profile-stat-header")
            for stat, label in zip(stats, labels, strict=False):
                label_text = label.get_text(strip=True).lower()
                val = _parse_stat(stat.get_text(strip=True))
                if "tweet" in label_text:
                    data["post_count"] = val
                elif "following" in label_text:
                    data["following_count"] = val
                elif "follower" in label_text:
                    data["follower_count"] = val

            data["is_verified"] = bool(soup.find(class_="verified-icon"))

            loc = soup.find(class_="profile-location")
            if loc:
                data["location"] = loc.get_text(strip=True)

            joined = soup.find(class_="profile-joindate")
            if joined:
                data["profile_created_at_str"] = joined.get_text(strip=True)

        except Exception as exc:
            logger.debug("Twitter parse error: %s", exc)
        return data

    def _parse_tweets(self, soup: BeautifulSoup) -> list[dict]:
        tweets = []
        for item in soup.find_all(class_="timeline-item")[:20]:
            tweet: dict = {}
            content = item.find(class_="tweet-content")
            if content:
                tweet["text"] = content.get_text(strip=True)[:280]
            date_tag = item.find(class_="tweet-date")
            if date_tag and date_tag.find("a"):
                tweet["date"] = date_tag.find("a").get("title", "")
            stats = item.find(class_="tweet-stats")
            if stats:
                for s in stats.find_all(class_="tweet-stat"):
                    icon = s.find(class_="icon-comment")
                    if icon:
                        tweet["replies"] = _parse_stat(s.get_text(strip=True))
            if tweet:
                tweets.append(tweet)
        return tweets


def _parse_stat(s: str) -> int:
    s = re.sub(r"[^\d.,KMB]", "", s).strip()
    if not s:
        return 0
    return _safe_parse(s)


def _safe_parse(s: str) -> int:
    s = s.replace(",", "")
    for suffix, mult in [("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)]:
        if s.upper().endswith(suffix):
            try:
                return int(float(s[:-1]) * mult)
            except ValueError:
                return 0
    try:
        return int(float(s))
    except ValueError:
        return 0
