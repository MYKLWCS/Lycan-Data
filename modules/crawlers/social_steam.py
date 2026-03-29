"""
social_steam.py — Steam community profile OSINT crawler.

Fetches a Steam user profile using the Steam XML community API (no auth required)
or the Steam Web API (requires STEAM_API_KEY env var for enhanced data).

The XML endpoint is always attempted first as it requires no credentials.

Source: https://steamcommunity.com/id/{username}?xml=1
API:    https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/
Registered as "social_steam".
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from shared.config import settings
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_XML_URL = "https://steamcommunity.com/id/{username}?xml=1"
_RESOLVE_URL = (
    "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
    "?key={api_key}&vanityurl={username}"
)
_SUMMARY_URL = (
    "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
    "?key={api_key}&steamids={steam_id}"
)
_HEADERS = {
    "Accept": "text/xml, application/xml, */*",
    "User-Agent": "Mozilla/5.0 (compatible; LycanBot/1.0)",
}


def _extract_xml_value(xml: str, tag: str) -> str:
    """Extract a tag value from XML string using regex."""
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", xml, re.IGNORECASE | re.DOTALL)
    if match:
        # Strip CDATA wrappers
        val = match.group(1)
        val = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", val, flags=re.DOTALL)
        return val.strip()
    return ""


def _parse_xml_profile(xml: str, username: str) -> dict[str, Any]:
    """Parse Steam XML profile into a structured dict."""
    return {
        "steam_id": _extract_xml_value(xml, "steamID64"),
        "username": _extract_xml_value(xml, "steamID") or username,
        "custom_url": _extract_xml_value(xml, "customURL"),
        "headline": _extract_xml_value(xml, "headline"),
        "summary": _extract_xml_value(xml, "summary"),
        "member_since": _extract_xml_value(xml, "memberSince"),
        "location": _extract_xml_value(xml, "location"),
        "country": _extract_xml_value(xml, "country"),
        "state_code": _extract_xml_value(xml, "stateCode"),
        "avatar_url": _extract_xml_value(xml, "avatarIcon"),
        "online_state": _extract_xml_value(xml, "onlineState"),
        "in_game_name": _extract_xml_value(xml, "inGameInfo") or None,
        "profile_url": f"https://steamcommunity.com/id/{username}",
        "groups": [
            {
                "name": _extract_xml_value(grp, "groupName"),
                "group_id": _extract_xml_value(grp, "groupID64"),
            }
            for grp in re.findall(r"<group>(.*?)</group>", xml, re.DOTALL)
        ][:10],
        "recently_played": [
            {
                "name": _extract_xml_value(game, "gameName"),
                "playtime_2weeks": _extract_xml_value(game, "hoursLast2Weeks"),
                "playtime_total": _extract_xml_value(game, "hoursOnRecord"),
            }
            for game in re.findall(r"<game>(.*?)</game>", xml, re.DOTALL)
        ][:10],
    }


@register("social_steam")
class SteamCrawler(HttpxCrawler):
    """
    Fetches Steam community profile data for a username or vanity URL.

    Uses the public XML API as primary (no auth required).
    If STEAM_API_KEY is configured, also resolves vanity URL → SteamID64
    and fetches enhanced player summary.

    identifier: Steam vanity URL username (e.g. "gaben")

    Data keys returned:
        profile     — Steam profile fields (username, summary, location, groups)
        steam_id    — SteamID64 if available
        online      — current online state
        in_game     — current game if playing
    """

    platform = "social_steam"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.80
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        username = identifier.strip().lower()
        if not username:
            return self._result(
                identifier,
                found=False,
                error="empty_identifier",
                profile=None,
                steam_id=None,
                online=None,
                in_game=None,
            )

        # Primary: XML community profile (no auth)
        xml_url = _XML_URL.format(username=quote_plus(username))
        resp = await self.get(xml_url, headers=_HEADERS)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                profile=None,
                steam_id=None,
                online=None,
                in_game=None,
            )

        if resp.status_code == 302 or resp.status_code == 404:
            return self._result(
                identifier,
                found=False,
                profile=None,
                steam_id=None,
                online=None,
                in_game=None,
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                profile=None,
                steam_id=None,
                online=None,
                in_game=None,
            )

        xml_text = resp.text
        # Steam returns an error page when profile not found
        if (
            "<error>" in xml_text.lower()
            or "the specified profile could not be found" in xml_text.lower()
        ):
            return self._result(
                identifier,
                found=False,
                profile=None,
                steam_id=None,
                online=None,
                in_game=None,
            )

        profile = _parse_xml_profile(xml_text, username)
        steam_id = profile.get("steam_id")
        online_state = profile.get("online_state", "")
        in_game = profile.get("in_game_name")

        # Secondary: Steam Web API enhanced data (optional, requires API key)
        api_key: str = getattr(settings, "steam_api_key", "")
        if api_key and steam_id:
            summary = await self._fetch_player_summary(api_key, steam_id)
            if summary:
                profile.update(
                    {
                        "real_name": summary.get("realname", ""),
                        "country_code": summary.get("loccountrycode", ""),
                        "last_online": summary.get("lastlogoff"),
                        "community_visibility": summary.get("communityvisibilitystate"),
                    }
                )

        return self._result(
            identifier,
            found=bool(steam_id or profile.get("username")),
            profile=profile,
            steam_id=steam_id,
            online=online_state,
            in_game=in_game,
        )

    async def _fetch_player_summary(self, api_key: str, steam_id: str) -> dict[str, Any] | None:
        """Fetch enhanced player data from Steam Web API."""
        url = _SUMMARY_URL.format(api_key=api_key, steam_id=steam_id)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is None or resp.status_code != 200:
            return None
        try:
            players = resp.json().get("response", {}).get("players", [])
            return players[0] if players else None
        except Exception:
            return None
