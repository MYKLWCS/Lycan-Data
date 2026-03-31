"""
social_spotify.py — Spotify public user/artist profile crawler.

Queries the Spotify Web API for a user or artist profile.
Uses client credentials flow (no user login required, free registration at
https://developer.spotify.com/dashboard).

Falls back to checking the Spotify embed URL if credentials are not configured.

Requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET environment variables.
Returns error "not_configured" if absent.

Source: https://api.spotify.com/v1/users/{user_id}
Registered as "social_spotify".
"""

from __future__ import annotations

import logging
from typing import Any

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from shared.config import settings

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://accounts.spotify.com/api/token"
_USER_URL = "https://api.spotify.com/v1/users/{user_id}"
_ARTIST_SEARCH_URL = "https://api.spotify.com/v1/search?q={query}&type=artist&limit=5"
_USER_PLAYLISTS_URL = "https://api.spotify.com/v1/users/{user_id}/playlists?limit=10"


def _parse_user(data: dict) -> dict[str, Any]:
    """Extract fields from a Spotify user profile."""
    followers = data.get("followers", {})
    images = data.get("images", [])
    return {
        "id": data.get("id", ""),
        "display_name": data.get("display_name", ""),
        "email": data.get("email", ""),  # only available with user-read-email scope
        "country": data.get("country", ""),
        "product": data.get("product", ""),  # free/premium
        "followers": followers.get("total", 0) if isinstance(followers, dict) else 0,
        "profile_url": data.get("external_urls", {}).get("spotify", ""),
        "avatar_url": images[0].get("url") if images else None,
        "type": data.get("type", "user"),
        "uri": data.get("uri", ""),
    }


def _parse_artist(data: dict) -> dict[str, Any]:
    """Extract fields from a Spotify artist profile."""
    followers = data.get("followers", {})
    images = data.get("images", [])
    return {
        "id": data.get("id", ""),
        "name": data.get("name", ""),
        "genres": data.get("genres", []),
        "popularity": data.get("popularity", 0),
        "followers": followers.get("total", 0) if isinstance(followers, dict) else 0,
        "profile_url": data.get("external_urls", {}).get("spotify", ""),
        "avatar_url": images[0].get("url") if images else None,
        "type": "artist",
        "uri": data.get("uri", ""),
    }


@register("social_spotify")
class SpotifyCrawler(HttpxCrawler):
    """
    Fetches a Spotify user profile or searches for an artist by name.

    Attempts user lookup first (by Spotify user ID), then falls back to
    artist search by name. Uses Spotify client credentials OAuth flow.

    Requires settings.spotify_client_id and settings.spotify_client_secret.

    identifier: Spotify user ID (e.g. "spotify") or artist name (e.g. "Eminem")

    Data keys returned:
        profile     — user or artist profile data
        playlists   — public playlists (user profiles only, up to 10)
        result_type — "user" | "artist"
    """

    platform = "social_spotify"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.70
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        if not query:
            return self._result(
                identifier,
                found=False,
                error="empty_identifier",
                profile=None,
                playlists=[],
                result_type=None,
            )

        client_id: str = getattr(settings, "spotify_client_id", "")
        client_secret: str = getattr(settings, "spotify_client_secret", "")

        if not client_id or not client_secret:
            return self._result(
                identifier,
                found=False,
                error="not_configured",
                profile=None,
                playlists=[],
                result_type=None,
            )

        token = await self._get_access_token(client_id, client_secret)
        if not token:
            return self._result(
                identifier,
                found=False,
                error="auth_failed",
                profile=None,
                playlists=[],
                result_type=None,
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        # Try direct user ID lookup first
        user_resp = await self.get(
            _USER_URL.format(user_id=query),
            headers=headers,
        )
        if user_resp is not None and user_resp.status_code == 200:
            try:
                user_data = user_resp.json()
                profile = _parse_user(user_data)

                # Fetch public playlists
                playlists: list[dict[str, Any]] = []
                pl_resp = await self.get(
                    _USER_PLAYLISTS_URL.format(user_id=query),
                    headers=headers,
                )
                if pl_resp and pl_resp.status_code == 200:
                    try:
                        pl_items = pl_resp.json().get("items", [])
                        playlists = [
                            {
                                "id": pl.get("id"),
                                "name": pl.get("name", ""),
                                "public": pl.get("public", False),
                                "tracks_total": pl.get("tracks", {}).get("total", 0),
                                "url": pl.get("external_urls", {}).get("spotify", ""),
                            }
                            for pl in pl_items[:10]
                            if pl
                        ]
                    except Exception:
                        logger.debug(
                            "Failed to fetch Spotify playlists for profile %s",
                            profile.get("profile_url") or identifier,
                            exc_info=True,
                        )

                return self._result(
                    identifier,
                    found=True,
                    profile=profile,
                    playlists=playlists,
                    result_type="user",
                )
            except Exception as exc:
                logger.debug("Spotify user parse failed for %r: %s", identifier, exc)

        # Fallback: search for artist by name
        from urllib.parse import quote_plus

        search_resp = await self.get(
            _ARTIST_SEARCH_URL.format(query=quote_plus(query)),
            headers=headers,
        )
        if search_resp is None or search_resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{search_resp.status_code if search_resp else 'none'}",
                profile=None,
                playlists=[],
                result_type=None,
            )

        try:
            artists = search_resp.json().get("artists", {}).get("items", [])
        except Exception as exc:
            logger.warning("Spotify artist search parse error for %r: %s", identifier, exc)
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                profile=None,
                playlists=[],
                result_type=None,
            )

        if not artists:
            return self._result(
                identifier,
                found=False,
                profile=None,
                playlists=[],
                result_type=None,
            )

        # Return the best match (highest popularity)
        best = max(artists, key=lambda a: a.get("popularity", 0))
        return self._result(
            identifier,
            found=True,
            profile=_parse_artist(best),
            playlists=[],
            result_type="artist",
        )

    async def _get_access_token(self, client_id: str, client_secret: str) -> str | None:
        """Obtain Spotify access token via client credentials flow."""
        import base64

        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        resp = await self.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if resp is None or resp.status_code != 200:
            logger.warning("Spotify token request failed")
            return None
        try:
            return resp.json().get("access_token")
        except Exception:
            return None
