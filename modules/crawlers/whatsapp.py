from __future__ import annotations

import logging
import re

from modules.crawlers.core.models import CrawlerCategory, RateLimit
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register

logger = logging.getLogger(__name__)


@register("whatsapp")
class WhatsAppCrawler(HttpxCrawler):
    """
    Checks if a phone number is registered on WhatsApp.
    Method: scrape wa.me/{number} — if registered, page redirects to WhatsApp.
    """

    platform = "whatsapp"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.65  # phone confirmation via wa.me heuristic
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        # Only accept phone numbers — reject usernames/handles
        digits_only = re.sub(r"\D", "", identifier)
        if len(digits_only) < 7:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                data={},
                error="invalid_phone",
            )

        # Normalize: remove + and spaces for wa.me URL
        phone = identifier.strip().replace(" ", "").replace("-", "")
        phone_clean = phone.lstrip("+")

        url = f"https://wa.me/{phone_clean}"
        response = await self.get(url)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                data={"phone": identifier, "whatsapp_registered": None},
                error="timeout",
            )

        registered = self._detect_registered(response.text, str(response.url))
        data = {
            "phone": identifier,
            "whatsapp_registered": registered,
            "handle": identifier,
        }

        return CrawlerResult(
            platform=self.platform,
            identifier=identifier,
            found=registered is True,
            data=data,
            profile_url=url,
            source_reliability=self.source_reliability if registered is not None else 0.0,
        )

    def _detect_registered(self, html: str, final_url: str) -> bool | None:
        """
        Heuristic detection:
        - Registered: page contains "Send message" or "Open WhatsApp" call-to-action
        - Not registered: page contains "phone number shared via link may not be on WhatsApp"
        - Unknown: anything else
        """
        html_lower = html.lower()
        if "send message" in html_lower or "open whatsapp" in html_lower:
            return True
        if "may not be on whatsapp" in html_lower or "not available" in html_lower:
            return False
        # wa.me sometimes just redirects to the app — treat as registered
        if "api.whatsapp.com" in final_url or "open.whatsapp.com" in final_url:
            return True
        return None  # unknown
