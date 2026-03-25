from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

SNOWFLAKE_RE = re.compile(r"^\d{17,19}$")
DISCORD_EPOCH = datetime(2015, 1, 1)
LOOKUP_URL = "https://discordlookup.mesalytic.moe/v1/user/{snowflake}"

AVATAR_BASE = "https://cdn.discordapp.com/avatars/{id}/{hash}.png"


def snowflake_to_datetime(snowflake: int) -> str:
    """Convert a Discord snowflake ID to an ISO timestamp string."""
    ms = snowflake >> 22
    return (DISCORD_EPOCH + timedelta(milliseconds=ms)).isoformat()


@register("discord")
class DiscordCrawler(CurlCrawler):
    """
    Looks up Discord users by numeric snowflake ID via discordlookup.mesalytic.moe.
    Non-numeric identifiers are rejected immediately — Discord has no public profile
    URL resolvable from a username alone.
    """

    platform = "discord"
    source_reliability = 0.50
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        identifier = identifier.strip()

        if not SNOWFLAKE_RE.match(identifier):
            return self._result(
                identifier,
                found=False,
                error="Discord requires numeric user ID (snowflake)",
            )

        url = LOOKUP_URL.format(snowflake=identifier)
        response = await self.get(url)

        if response is None:
            return self._result(identifier, found=False, error="http_error")

        if response.status_code == 404:
            return self._result(identifier, found=False)

        if response.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"unexpected_status_{response.status_code}",
            )

        try:
            payload = response.json()
        except Exception as exc:
            logger.debug("Discord JSON parse error: %s", exc)
            return self._result(identifier, found=False, error="json_parse_error")

        data = self._build_data(identifier, payload)

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=True,
            data=data,
            source_reliability=self.source_reliability,
        )

    def _build_data(self, snowflake: str, payload: dict) -> dict:
        data: dict = {}
        data["username"] = payload.get("username")
        data["discriminator"] = payload.get("discriminator") or payload.get("tag")
        data["bot"] = payload.get("bot", False)

        avatar_hash = payload.get("avatar")
        user_id = payload.get("id", snowflake)
        if avatar_hash:
            data["avatar_url"] = AVATAR_BASE.format(id=user_id, hash=avatar_hash)

        try:
            data["created_at"] = snowflake_to_datetime(int(snowflake))
        except Exception:
            pass

        return data
