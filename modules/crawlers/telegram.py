from __future__ import annotations

import logging
import os
import re

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.constants import SOURCE_RELIABILITY
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


@register("telegram")
class TelegramCrawler(HttpxCrawler):
    """
    Probes Telegram for a username or phone number.
    - Username: scrape t.me/{username} public page
    - Phone: requires Telethon (optional, configured via TELEGRAM_API_ID env var)
    """

    platform = "telegram"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = SOURCE_RELIABILITY.get("telegram", 0.50)
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        # Detect if it's a phone number or username
        cleaned = identifier.strip().replace(" ", "")
        if cleaned.startswith("+") or cleaned.lstrip("+").isdigit():
            return await self._probe_phone(cleaned)
        else:
            return await self._probe_username(cleaned.lstrip("@"))

    async def _probe_username(self, handle: str) -> CrawlerResult:
        """Scrape public t.me page for username."""
        url = f"https://t.me/{handle}"
        response = await self.get(url)
        if response is None or response.status_code != 200:
            return self._result(handle, found=False, error="http_error")

        soup = BeautifulSoup(response.text, "html.parser")

        # Not found page
        if "tgme_page_additional" not in response.text and "tgme_page_title" not in response.text:
            return self._result(handle, found=False, handle=handle)

        data: dict = {"handle": handle}
        name_tag = soup.find(class_="tgme_page_title")
        if name_tag:
            data["display_name"] = name_tag.get_text(strip=True)

        bio_tag = soup.find(class_="tgme_page_description")
        if bio_tag:
            data["bio"] = bio_tag.get_text(strip=True)[:500]

        extra_tag = soup.find(class_="tgme_page_extra")
        if extra_tag:
            data["extra"] = extra_tag.get_text(strip=True)

        # Subscriber count for channels
        subscribers_match = re.search(
            r"([\d\s,]+)\s*(?:subscribers|members)", response.text, re.IGNORECASE
        )
        if subscribers_match:
            count_str = subscribers_match.group(1).replace(",", "").replace(" ", "")
            try:
                data["follower_count"] = int(count_str)
            except ValueError:
                pass

        return CrawlerResult(
            platform=self.platform,
            identifier=handle,
            found=bool(data.get("display_name")),
            data=data,
            profile_url=url,
            source_reliability=self.source_reliability,
        )

    async def _probe_phone(self, phone: str) -> CrawlerResult:
        """
        Check if a phone number is registered on Telegram.
        Uses Telethon if configured, otherwise returns unknown.
        """
        api_id = os.environ.get("TELEGRAM_API_ID")
        api_hash = os.environ.get("TELEGRAM_API_HASH")
        session_string = os.environ.get("TELEGRAM_SESSION")

        if not (api_id and api_hash and session_string):
            # Telethon not configured — return partial result
            return CrawlerResult(
                platform=self.platform,
                identifier=phone,
                found=False,
                data={"phone": phone, "telegram_registered": None},
                error="telethon_not_configured",
                source_reliability=0.0,
            )

        try:
            from telethon import TelegramClient
            from telethon.errors import PhoneNumberInvalidError
            from telethon.sessions import StringSession
            from telethon.tl.functions.contacts import ResolvePhoneRequest

            client = TelegramClient(StringSession(session_string), int(api_id), api_hash)
            await client.connect()
            try:
                result = await client(ResolvePhoneRequest(phone=phone))
                user = result.users[0] if result.users else None
                if user:
                    return CrawlerResult(
                        platform=self.platform,
                        identifier=phone,
                        found=True,
                        data={
                            "phone": phone,
                            "telegram_registered": True,
                            "display_name": f"{user.first_name or ''} {user.last_name or ''}".strip(),
                            "handle": user.username,
                            "platform_user_id": str(user.id),
                        },
                        source_reliability=self.source_reliability,
                    )
            except (PhoneNumberInvalidError, Exception) as exc:
                logger.debug("Telethon probe failed: %s", exc)
            finally:
                await client.disconnect()
        except ImportError:
            pass

        return CrawlerResult(
            platform=self.platform,
            identifier=phone,
            found=False,
            data={"phone": phone, "telegram_registered": False},
            source_reliability=self.source_reliability * 0.5,
        )
