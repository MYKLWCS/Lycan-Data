from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CrawlerResult:
    """Unified result returned by every scraper."""
    platform: str
    identifier: str              # what was searched (handle, phone, email, etc.)
    found: bool                  # did we find a profile?
    data: dict[str, Any] = field(default_factory=dict)
    profile_url: str | None = None
    error: str | None = None
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_reliability: float = 0.5
    tor_used: bool = False
    circuit_id: str | None = None

    def to_db_dict(self) -> dict[str, Any]:
        """Fields that map directly to SocialProfile columns."""
        return {
            "platform": self.platform,
            "handle": self.data.get("handle"),
            "display_name": self.data.get("display_name"),
            "bio": self.data.get("bio"),
            "url": self.profile_url,
            "follower_count": self.data.get("follower_count"),
            "following_count": self.data.get("following_count"),
            "post_count": self.data.get("post_count"),
            "is_verified": self.data.get("is_verified", False),
            "is_private": self.data.get("is_private", False),
            "is_active": self.found,
            "profile_created_at": self.data.get("profile_created_at"),
            "profile_data": self.data,
            "scraped_from": self.profile_url or self.platform,
            "last_scraped_at": self.scraped_at,
            "source_reliability": self.source_reliability,
            "freshness_score": 1.0,
        }
