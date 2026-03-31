"""
social_instaloader.py — Instaloader subprocess wrapper.

Fetches Instagram profile metadata (followers, following, posts, bio, etc.)
using the instaloader CLI. No login required for public profiles.

Uses asyncio.create_subprocess_exec (arg-list form) — no shell injection risk.
Pattern identical to username_sherlock.py, email_holehe.py, username_maigret.py.

Registered as "instaloader".
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path

from modules.crawlers.base import BaseCrawler
from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

INSTALOADER_TIMEOUT = 120  # seconds


def _instaloader_available() -> bool:
    """Return True if instaloader is on PATH."""
    return shutil.which("instaloader") is not None


def _parse_profile_json(profile_path: Path) -> dict:
    """
    Parse instaloader's JSON profile file.
    instaloader writes profile metadata into {username}/*.json files.
    """
    json_files = list(profile_path.glob("*.json"))
    if not json_files:
        json_files = list(profile_path.glob("**/*.json"))
    for f in json_files:
        try:
            raw = json.loads(f.read_text())
            node = raw.get("node") or raw
            return {
                "username": node.get("username"),
                "full_name": node.get("full_name"),
                "biography": node.get("biography"),
                "follower_count": (node.get("edge_followed_by") or {}).get("count"),
                "following_count": (node.get("edge_follow") or {}).get("count"),
                "post_count": (node.get("edge_owner_to_timeline_media") or {}).get("count"),
                "is_private": node.get("is_private", False),
                "is_verified": node.get("is_verified", False),
                "profile_pic_url": node.get("profile_pic_url_hd") or node.get("profile_pic_url"),
                "external_url": node.get("external_url"),
                "business_category": node.get("business_category_name"),
            }
        except Exception as exc:  # pragma: no cover
            logger.debug("Instaloader JSON parse error %s: %s", f, exc)
    return {}


async def _fetch_instaloader(username: str, output_dir: str) -> None:
    """
    Run instaloader in output_dir for the given username.
    Uses exec (arg list) — username is passed as a discrete argument,
    never interpolated into a shell string.
    """
    proc = await asyncio.create_subprocess_exec(
        "instaloader",
        "--no-pictures",
        "--no-videos",
        "--no-video-thumbnails",
        "--no-geotags",
        "--fast-update",
        "--dirname-pattern={profile}",
        "--",  # end of options — username follows as positional
        username,  # passed as separate arg, not shell-interpolated
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=output_dir,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=INSTALOADER_TIMEOUT)
    except TimeoutError:
        proc.kill()
        raise


@register("instaloader")
class InstaloaderCrawler(BaseCrawler):
    """
    Fetches Instagram profile data via the instaloader CLI.

    identifier: Instagram username (without @)
    Returns: followers, following, post count, bio, verified status.

    No login required for public profiles.
    """

    platform = "instaloader"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.2, burst_size=2, cooldown_seconds=5.0)
    source_reliability = 0.80
    requires_tor = False  # Instagram aggressively blocks Tor exit nodes

    async def scrape(self, identifier: str) -> CrawlerResult:
        username = identifier.lstrip("@").strip()

        if not _instaloader_available():
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="instaloader_not_installed",
                source_reliability=self.source_reliability,
            )

        with tempfile.TemporaryDirectory(prefix="lycan_ig_") as tmpdir:
            try:
                await _fetch_instaloader(username, tmpdir)
            except TimeoutError:
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="instaloader_timeout",
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

            profile_dir = Path(tmpdir) / username
            if not profile_dir.exists():
                subdirs = [d for d in Path(tmpdir).iterdir() if d.is_dir()]
                profile_dir = subdirs[0] if subdirs else Path(tmpdir)

            profile_data = _parse_profile_json(profile_dir)

        if not profile_data:
            return self._result(identifier, found=False, username=username)

        return self._result(
            identifier,
            found=True,
            **profile_data,
            profile_url=f"https://www.instagram.com/{username}/",
        )
