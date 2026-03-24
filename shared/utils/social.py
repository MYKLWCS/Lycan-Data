"""Social media handle normalisation."""

from __future__ import annotations

import re


def normalize_handle(handle: str, platform: str = "unknown") -> str:
    """
    Normalize a social media handle.
    Strips @, whitespace, and lowercases.
    """
    cleaned = handle.strip().lstrip("@").lower()
    # Remove URL prefix if someone passed a full URL
    patterns = [
        r"https?://(?:www\.)?(?:instagram|twitter|x|tiktok|linkedin|facebook|reddit|github)\.com/",
        r"https?://t\.me/",
    ]
    for pat in patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.rstrip("/").strip()
    return cleaned


def extract_handle_from_url(url: str) -> str | None:
    """
    Extract a username/handle from a social media URL.
    Returns None if unable to extract.
    """
    patterns = [
        r"(?:instagram\.com|twitter\.com|x\.com|tiktok\.com|github\.com|reddit\.com/u)/([a-zA-Z0-9._\-]+)",
        r"linkedin\.com/in/([a-zA-Z0-9\-]+)",
        r"facebook\.com/([a-zA-Z0-9.]+)",
        r"t\.me/([a-zA-Z0-9_]+)",
        r"youtube\.com/@([a-zA-Z0-9_\-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return normalize_handle(match.group(1))
    return None


def build_profile_url(platform: str, handle: str) -> str | None:
    """Build a canonical profile URL for a platform + handle."""
    handle = normalize_handle(handle)
    urls = {
        "instagram": f"https://www.instagram.com/{handle}/",
        "twitter": f"https://twitter.com/{handle}",
        "tiktok": f"https://www.tiktok.com/@{handle}",
        "linkedin": f"https://www.linkedin.com/in/{handle}/",
        "facebook": f"https://www.facebook.com/{handle}",
        "github": f"https://github.com/{handle}",
        "reddit": f"https://www.reddit.com/u/{handle}/",
        "telegram": f"https://t.me/{handle}",
        "youtube": f"https://www.youtube.com/@{handle}",
    }
    return urls.get(platform.lower())
