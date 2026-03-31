"""
social_ghunt.py — GHunt Google account OSINT crawler.

Wraps the GHunt CLI (https://github.com/mxrch/GHunt) as an isolated subprocess.
GHunt is AGPL-licensed — we invoke it as a black-box process to keep the AGPL
boundary clean and avoid re-licensing contamination.

identifier: Google account email address (e.g. "john.doe@gmail.com")
Registered as "social_ghunt".

Requires:
  - ghunt CLI on PATH (pip install ghunt)
  - GHUNT session authenticated (ghunt login)
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess

from modules.crawlers.base import BaseCrawler
from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)

_GHUNT_TIMEOUT = 120  # seconds — GHunt can be slow on first run


def _run_ghunt_sync(email: str) -> tuple[int, bytes, bytes]:
    """Run GHunt synchronously; called via asyncio.to_thread."""
    proc = subprocess.run(
        ["ghunt", "email", email, "--json"],
        capture_output=True,
        timeout=_GHUNT_TIMEOUT,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _parse_output(stdout: bytes) -> dict:
    """
    Extract the JSON object GHunt writes to stdout.

    GHunt may emit log lines before the JSON; we scan for the first '{'.
    """
    text = stdout.decode("utf-8", errors="replace").strip()

    # Find the first JSON object boundary
    brace_idx = text.find("{")
    if brace_idx == -1:
        return {}

    try:
        return json.loads(text[brace_idx:])
    except json.JSONDecodeError:
        # Try to extract the first complete JSON object naively
        try:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(text, brace_idx)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}


def _normalise(raw: dict) -> dict:
    """Flatten GHunt's nested output into a flat data dict."""
    data: dict = {}

    # GHunt v2 top-level keys
    data["ghunt_version"] = raw.get("version", "")

    profile = raw.get("profile", raw.get("google_account", {})) or {}
    if isinstance(profile, dict):
        data["name"] = profile.get("name", "")
        data["profile_photo"] = profile.get("profile_photo_url", "")
        data["cover_photo"] = profile.get("cover_photo_url", "")
        data["gaia_id"] = profile.get("gaia_id", profile.get("personId", ""))
        data["last_updated"] = profile.get("last_updated", "")

    services = raw.get("services", raw.get("activated_services", [])) or []
    if isinstance(services, list):
        data["activated_services"] = services
    elif isinstance(services, dict):
        data["activated_services"] = list(services.keys())

    reviews = raw.get("reviews", {}) or {}
    if isinstance(reviews, dict):
        data["review_count"] = reviews.get("total_reviews", 0)

    maps_data = raw.get("maps", {}) or {}
    if isinstance(maps_data, dict):
        data["maps_stats"] = {
            "reviews": maps_data.get("review_count", 0),
            "photos": maps_data.get("photo_count", 0),
        }

    youtube = raw.get("youtube", {}) or {}
    if isinstance(youtube, dict):
        data["youtube_channel"] = youtube.get("channel_url", "")

    calendar = raw.get("calendar", {}) or {}
    if isinstance(calendar, dict):
        data["calendar_public"] = bool(calendar.get("calendars"))

    # Preserve full raw for downstream enrichers
    data["raw"] = raw
    return data


@register("social_ghunt")
class GHuntCrawler(BaseCrawler):
    """
    Runs GHunt as an isolated subprocess to gather OSINT on a Google account.

    GHunt is AGPL-licensed; invoked as a separate process to maintain
    clean licensing boundaries.

    identifier: Google account email address
    requires_tor: False (GHunt manages its own session/auth)
    source_reliability: 0.75 — direct Google data but session-dependent
    """

    platform = "social_ghunt"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.25, burst_size=2, cooldown_seconds=5.0)
    source_reliability = 0.75
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        email = identifier.strip().lower()

        if not shutil.which("ghunt"):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="ghunt_not_installed",
                source_reliability=self.source_reliability,
            )

        try:
            returncode, stdout, stderr = await asyncio.to_thread(_run_ghunt_sync, email)
        except subprocess.TimeoutExpired:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="ghunt_timeout",
                source_reliability=self.source_reliability,
            )
        except FileNotFoundError:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="ghunt_not_installed",
                source_reliability=self.source_reliability,
            )

        # GHunt exits non-zero when account not found or not authenticated
        if returncode != 0 and not stdout:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            if "not authenticated" in stderr_text.lower() or "login" in stderr_text.lower():
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=False,
                    error="ghunt_not_authenticated",
                    source_reliability=self.source_reliability,
                )
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"ghunt_exit_{returncode}",
                source_reliability=self.source_reliability,
            )

        raw = _parse_output(stdout)
        if not raw:
            # stdout wasn't valid JSON — account likely not found
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="no_json_output",
                source_reliability=self.source_reliability,
            )

        data = _normalise(raw)
        found = bool(data.get("gaia_id") or data.get("name") or data.get("activated_services"))

        return self._result(
            identifier,
            found=found,
            email=email,
            **{k: v for k, v in data.items() if k != "raw"},
            raw=raw,
        )
