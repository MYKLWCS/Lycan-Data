"""
social_snscrape.py — snscrape subprocess wrapper for Twitter/X.

Fetches a Twitter/X user profile and recent tweets using the snscrape CLI.
snscrape uses Twitter's undocumented API — no API key required.

All subprocess calls use asyncio.create_subprocess_exec (arg-list form).
Username is validated to [A-Za-z0-9_] before use — no shell injection risk.

Registered as "snscrape".
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from typing import Any

from modules.crawlers.base import BaseCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

SNSCRAPE_TIMEOUT = 60
SNSCRAPE_MAX_TWEETS = 20

# Twitter usernames: 1-50 chars, alphanumeric + underscore only
_VALID_USERNAME = re.compile(r"^[A-Za-z0-9_]{1,50}$")


def _validate_username(raw: str) -> str:
    """Strip @ prefix and enforce allowed character set."""
    cleaned = raw.lstrip("@").strip()
    if not _VALID_USERNAME.match(cleaned):
        raise ValueError(f"Invalid Twitter username: {raw!r}")
    return cleaned


def _snscrape_available() -> bool:
    return shutil.which("snscrape") is not None


async def _run_snscrape(*args: str) -> bytes:
    """
    Run snscrape with the given arguments (arg-list, no shell).
    Returns raw stdout bytes.
    """
    proc = await asyncio.create_subprocess_exec(
        "snscrape",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(
            proc.communicate(), timeout=SNSCRAPE_TIMEOUT
        )
        return stdout
    except TimeoutError:
        proc.kill()
        raise


def _parse_jsonl(data: bytes) -> list[dict[str, Any]]:
    """Parse newline-delimited JSON output from snscrape."""
    results = []
    for line in data.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return results


def _normalise_profile(raw: dict[str, Any]) -> dict[str, Any]:
    user = raw.get("user") or raw
    return {
        "username": user.get("username"),
        "display_name": user.get("displayname"),
        "bio": user.get("description") or user.get("rawDescription"),
        "follower_count": user.get("followersCount"),
        "following_count": user.get("friendsCount"),
        "tweet_count": user.get("statusesCount"),
        "like_count": user.get("favouritesCount"),
        "is_verified": user.get("verified", False),
        "is_protected": user.get("protected", False),
        "location": user.get("location"),
        "url": user.get("url"),
        "created_at": str(user.get("created")) if user.get("created") else None,
        "profile_image_url": user.get("profileImageUrl"),
    }


@register("snscrape")
class SnscrapeCrawler(BaseCrawler):
    """
    Fetches Twitter/X profile and recent tweets via the snscrape CLI.

    identifier: Twitter username (with or without @)
    Returns: profile metadata and up to 20 recent tweets.
    """

    platform = "snscrape"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=2.0)
    source_reliability = 0.70
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        try:
            username = _validate_username(identifier)
        except ValueError as exc:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
                source_reliability=self.source_reliability,
            )

        if not _snscrape_available():
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="snscrape_not_installed",
                source_reliability=self.source_reliability,
            )

        # Fetch profile — max 1 result from twitter-user scraper
        try:
            raw = await _run_snscrape(
                "--jsonl", "--max-results", "1", "twitter-user", username
            )
        except TimeoutError:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="snscrape_timeout",
                source_reliability=self.source_reliability,
            )
        except Exception as exc:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=str(exc),
                source_reliability=self.source_reliability,
            )

        records = _parse_jsonl(raw)
        if not records:
            return self._result(identifier, found=False, username=username)

        profile = _normalise_profile(records[0])

        # Fetch recent tweets — search query "from:username" is passed as a
        # single validated string argument; no shell expansion occurs.
        from_query = "from:" + username   # username validated to [A-Za-z0-9_]
        try:
            tweet_raw = await _run_snscrape(
                "--jsonl",
                "--max-results", str(SNSCRAPE_MAX_TWEETS),
                "twitter-search",
                from_query,
            )
            raw_tweets = _parse_jsonl(tweet_raw)
        except Exception:
            raw_tweets = []

        tweets = [
            {
                "id": t.get("id"),
                "text": t.get("rawContent") or t.get("content"),
                "created_at": str(t.get("date")) if t.get("date") else None,
                "like_count": t.get("likeCount"),
                "retweet_count": t.get("retweetCount"),
                "reply_count": t.get("replyCount"),
                "url": t.get("url"),
            }
            for t in raw_tweets[:SNSCRAPE_MAX_TWEETS]
        ]

        return self._result(
            identifier,
            found=True,
            **profile,
            recent_tweets=tweets,
            tweet_sample_count=len(tweets),
            profile_url="https://twitter.com/" + username,
        )
