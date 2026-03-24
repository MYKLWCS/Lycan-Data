"""
social_twitch.py — Twitch channel/user OSINT crawler.

Queries the Twitch Helix API for a channel by username, returning subscriber
count, view count, stream history, and profile metadata.

Requires TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET environment variables
(free at https://dev.twitch.tv/console/apps). Returns not_configured if absent.

Source: https://api.twitch.tv/helix/users
Registered as "social_twitch".
"""

from __future__ import annotations

import logging
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.config import settings

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_USERS_URL = "https://api.twitch.tv/helix/users?login={login}"
_STREAMS_URL = "https://api.twitch.tv/helix/streams?user_login={login}"
_CHANNEL_URL = "https://api.twitch.tv/helix/channels?broadcaster_id={user_id}"


@register("social_twitch")
class TwitchCrawler(HttpxCrawler):
    """
    Fetches Twitch profile, stream status, and channel metadata for a username.

    Requires settings.twitch_client_id and settings.twitch_client_secret.
    Returns error "not_configured" if credentials are missing.

    identifier: Twitch username/login (e.g. "xqc")

    Data keys returned:
        profile         — user profile (display_name, description, view_count, etc.)
        stream          — current stream info (null if offline)
        channel         — channel metadata (game, title, language)
        is_live         — True if currently streaming
    """

    platform = "social_twitch"
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        login = identifier.strip().lower()
        if not login:
            return self._result(
                identifier,
                found=False,
                error="empty_identifier",
                profile=None,
                stream=None,
                channel=None,
                is_live=False,
            )

        client_id: str = getattr(settings, "twitch_client_id", "")
        client_secret: str = getattr(settings, "twitch_client_secret", "")

        if not client_id or not client_secret:
            return self._result(
                identifier,
                found=False,
                error="not_configured",
                profile=None,
                stream=None,
                channel=None,
                is_live=False,
            )

        # Obtain app access token via client credentials flow
        token = await self._get_app_token(client_id, client_secret)
        if not token:
            return self._result(
                identifier,
                found=False,
                error="auth_failed",
                profile=None,
                stream=None,
                channel=None,
                is_live=False,
            )

        headers = {
            "Client-ID": client_id,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        # Fetch user profile
        user_resp = await self.get(_USERS_URL.format(login=login), headers=headers)
        if user_resp is None or user_resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{user_resp.status_code if user_resp else 'none'}",
                profile=None,
                stream=None,
                channel=None,
                is_live=False,
            )

        try:
            user_data = user_resp.json()
        except Exception:
            return self._result(
                identifier,
                found=False,
                error="parse_error",
                profile=None,
                stream=None,
                channel=None,
                is_live=False,
            )

        users = user_data.get("data", [])
        if not users:
            return self._result(
                identifier,
                found=False,
                profile=None,
                stream=None,
                channel=None,
                is_live=False,
            )

        user = users[0]
        user_id = user.get("id", "")
        profile = {
            "id": user_id,
            "login": user.get("login", ""),
            "display_name": user.get("display_name", ""),
            "type": user.get("type", ""),
            "broadcaster_type": user.get("broadcaster_type", ""),
            "description": user.get("description", ""),
            "profile_image_url": user.get("profile_image_url", ""),
            "view_count": user.get("view_count", 0),
            "created_at": user.get("created_at", ""),
            "profile_url": f"https://www.twitch.tv/{login}",
        }

        # Fetch stream status
        stream_resp = await self.get(_STREAMS_URL.format(login=login), headers=headers)
        stream: dict[str, Any] | None = None
        is_live = False
        if stream_resp and stream_resp.status_code == 200:
            try:
                stream_data = stream_resp.json().get("data", [])
                if stream_data:
                    s = stream_data[0]
                    stream = {
                        "title": s.get("title", ""),
                        "game_name": s.get("game_name", ""),
                        "viewer_count": s.get("viewer_count", 0),
                        "started_at": s.get("started_at", ""),
                        "language": s.get("language", ""),
                        "is_mature": s.get("is_mature", False),
                    }
                    is_live = True
            except Exception:
                pass

        # Fetch channel metadata
        channel: dict[str, Any] | None = None
        if user_id:
            ch_resp = await self.get(_CHANNEL_URL.format(user_id=user_id), headers=headers)
            if ch_resp and ch_resp.status_code == 200:
                try:
                    ch_data = ch_resp.json().get("data", [])
                    if ch_data:
                        c = ch_data[0]
                        channel = {
                            "broadcaster_language": c.get("broadcaster_language", ""),
                            "game_name": c.get("game_name", ""),
                            "title": c.get("title", ""),
                            "delay": c.get("delay", 0),
                            "tags": c.get("tags", []),
                        }
                except Exception:
                    pass

        return self._result(
            identifier,
            found=True,
            profile=profile,
            stream=stream,
            channel=channel,
            is_live=is_live,
        )

    async def _get_app_token(self, client_id: str, client_secret: str) -> str | None:
        """Obtain Twitch app access token via client credentials flow."""
        resp = await self.post(
            _TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Accept": "application/json"},
        )
        if resp is None or resp.status_code != 200:
            logger.warning("Twitch token request failed")
            return None
        try:
            return resp.json().get("access_token")
        except Exception:
            return None
