"""
telegram_dark.py — Telegram public channel scanner for dark web intel.

Scans a curated list of public Telegram channels known to carry cybersecurity,
breach, and dark web intelligence. Uses t.me/s/{channel} (no auth required)
to fetch message previews and searches for query mentions.

Registered as "telegram_dark".
"""

from __future__ import annotations

import asyncio
import logging
import re

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_TG_CHANNEL_URL = "https://t.me/s/{channel}"

# Public Telegram channels carrying dark web / threat intel content.
DARK_CHANNELS = [
    "cybernewsrus",
    "darkwebinformer",
    "breachdetector",
    "leakbase_official",
    "databreaches",
    "cyberscoop",
]


def _parse_channel_messages(html: str) -> list[dict]:
    """
    Extract messages from a t.me/s/{channel} page.

    Telegram renders public channel previews with each message in:
    <div class="tgme_widget_message_wrap"> containing:
    - <div class="tgme_widget_message_text"> — message body
    - <a class="tgme_widget_message_date">   — permalink + datetime
    """
    soup = BeautifulSoup(html, "html.parser")
    messages: list[dict] = []

    for wrap in soup.find_all("div", class_=re.compile(r"tgme_widget_message\b")):
        text_div = wrap.find("div", class_=re.compile(r"tgme_widget_message_text"))
        if not text_div:
            continue

        text = text_div.get_text(strip=True)

        # Permalink is in the <a class="tgme_widget_message_date"> tag
        date_a = wrap.find("a", class_=re.compile(r"tgme_widget_message_date"))
        message_url = date_a.get("href", "") if date_a else ""
        date_tag = date_a.find("time") if date_a else None
        date = date_tag.get("datetime", "") if date_tag else ""

        messages.append(
            {
                "message_text": text,
                "message_url": message_url,
                "date": date,
            }
        )

    return messages


def _filter_mentions(messages: list[dict], query: str, channel: str) -> list[dict]:
    """Return messages that contain the query string (case-insensitive)."""
    q_lower = query.lower()
    hits: list[dict] = []
    for msg in messages:
        if q_lower in msg["message_text"].lower():
            hits.append(
                {
                    "channel": channel,
                    "message_text": msg["message_text"],
                    "message_url": msg["message_url"],
                    "date": msg["date"],
                }
            )
    return hits


@register("telegram_dark")
class TelegramDarkCrawler(HttpxCrawler):
    """
    Scans known dark-web Telegram channels for mentions of an identifier.

    Uses t.me/s/{channel} (public web preview, no credentials needed).
    Routes through TOR2 to mask the enumeration pattern.

    identifier: freeform keyword, email, username, or domain
    """

    platform = "telegram_dark"
    category = CrawlerCategory.DARK_WEB
    rate_limit = RateLimit(requests_per_second=0.3, burst_size=2, cooldown_seconds=5.0)
    source_reliability = 0.45
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        all_mentions: list[dict] = []

        for channel in DARK_CHANNELS:
            url = _TG_CHANNEL_URL.format(channel=channel)
            response = await self.get(url)

            if response is None:
                logger.warning("telegram_dark: could not reach channel %s", channel)
                continue

            if response.status_code not in (200, 301, 302):
                logger.warning(
                    "telegram_dark: channel %s returned HTTP %d",
                    channel,
                    response.status_code,
                )
                continue

            messages = _parse_channel_messages(response.text)
            hits = _filter_mentions(messages, query, channel)
            all_mentions.extend(hits)

            # Polite gap between channel requests
            await asyncio.sleep(0.5)

        return self._result(
            identifier,
            found=len(all_mentions) > 0,
            mentions=all_mentions,
            query=query,
            mention_count=len(all_mentions),
        )
