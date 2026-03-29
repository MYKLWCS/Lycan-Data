"""
Social Graph crawler — maps cross-platform social connections.

Analyses a blob of already-scraped social data to identify:
- @mention networks
- Consistent usernames across platforms (Twitter, Instagram, GitHub, etc.)
- Co-follow relationships
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from modules.crawlers.base import BaseCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

# Platforms we look for in the text blob
KNOWN_PLATFORMS = [
    "twitter",
    "instagram",
    "github",
    "linkedin",
    "facebook",
    "tiktok",
    "reddit",
    "youtube",
    "telegram",
]

# Regex to extract @mentions
MENTION_RE = re.compile(r"@(\w+)")

# Regex to detect platform-prefixed mentions like "twitter:username" or "github/username"
PLATFORM_MENTION_RE = re.compile(
    r"(?P<platform>" + "|".join(KNOWN_PLATFORMS) + r")"
    r"[:/](?P<username>\w+)",
    re.IGNORECASE,
)


@register("social_graph")
class SocialGraphCrawler(BaseCrawler):
    """
    Analyses a text blob of scraped social data to surface cross-platform
    connection graphs.

    identifier format: a raw text blob containing scraped social content,
    bios, follower lists, etc.

    This crawler performs local analysis — no HTTP calls required.
    """

    platform = "social_graph"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.55
    requires_tor = False  # analysis of already-scraped data

    async def scrape(self, identifier: str) -> CrawlerResult:
        text = identifier.strip()

        # ── Extract @mentions ──────────────────────────────────────────────────
        mentions = _extract_mentions(text)

        # ── Extract platform-specific usernames ────────────────────────────────
        platform_mentions = _extract_platform_mentions(text)

        # ── Build connection map ───────────────────────────────────────────────
        connections = _build_connections(mentions, platform_mentions)

        return self._result(
            identifier=identifier,
            found=True,
            connections=connections,
            connection_count=len(connections),
        )


# ── Analysis functions ─────────────────────────────────────────────────────────


def _extract_mentions(text: str) -> dict[str, int]:
    """
    Extract all @mentions from text and return {username: count}.
    Case-normalised (lowercased) to deduplicate variations.
    """
    raw = MENTION_RE.findall(text)
    counts: dict[str, int] = defaultdict(int)
    for username in raw:
        counts[username.lower()] += 1
    return dict(counts)


def _extract_platform_mentions(text: str) -> dict[str, list[str]]:
    """
    Extract platform-specific username patterns like "github/johndoe" or
    "twitter:johndoe".

    Returns {username_lower: [platform1, platform2, ...]}
    """
    platform_map: dict[str, list[str]] = defaultdict(list)
    for match in PLATFORM_MENTION_RE.finditer(text):
        platform = match.group("platform").lower()
        username = match.group("username").lower()
        if platform not in platform_map[username]:
            platform_map[username].append(platform)
    return dict(platform_map)


def _build_connections(
    mentions: dict[str, int],
    platform_mentions: dict[str, list[str]],
) -> list[dict]:
    """
    Combine @mention counts and platform-specific mentions into a unified
    connection list.

    A connection is flagged as cross-platform if the same username appears on
    2+ platforms.
    """
    all_usernames: set[str] = set(mentions.keys()) | set(platform_mentions.keys())

    connections: list[dict] = []
    for username in sorted(all_usernames):
        platforms = platform_mentions.get(username, [])
        mention_count = mentions.get(username, 0)

        connections.append(
            {
                "username": username,
                "platforms": platforms,
                "mention_count": mention_count,
                "co_follows": len(platforms) >= 2,  # True if cross-platform match
            }
        )

    return connections
