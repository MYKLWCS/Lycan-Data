"""
social_mastodon.py — Mastodon/Fediverse account search crawler.

Searches the Mastodon public search API (mastodon.social) for accounts
matching a username or display name. No authentication required.

Source: https://mastodon.social/api/v2/search
Registered as "social_mastodon".
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

# Primary and secondary Mastodon instances to search
_INSTANCES = [
    "mastodon.social",
    "infosec.exchange",
    "fosstodon.org",
]
_SEARCH_PATH = "/api/v2/search?q={query}&resolve=false&limit=10&type=accounts"
_HEADERS = {"Accept": "application/json"}


def _parse_account(account: dict) -> dict[str, Any]:
    """Extract relevant fields from a Mastodon account record."""
    return {
        "id": account.get("id"),
        "username": account.get("username", ""),
        "acct": account.get("acct", ""),
        "display_name": account.get("display_name", ""),
        "url": account.get("url", ""),
        "followers_count": account.get("followers_count", 0),
        "following_count": account.get("following_count", 0),
        "statuses_count": account.get("statuses_count", 0),
        "created_at": account.get("created_at", ""),
        "note": _strip_html(account.get("note", "")),
        "bot": account.get("bot", False),
        "locked": account.get("locked", False),
        "fields": [
            {"name": f.get("name", ""), "value": _strip_html(f.get("value", ""))}
            for f in account.get("fields", [])
        ],
        "instance": "",  # filled by caller
    }


def _strip_html(html: str) -> str:
    """Remove HTML tags from Mastodon bio/note text."""
    import re

    return re.sub(r"<[^>]+>", "", html).strip()


@register("social_mastodon")
class MastodonCrawler(HttpxCrawler):
    """
    Searches Mastodon/Fediverse for accounts matching a username or display name.

    Queries mastodon.social first, then infosec.exchange and fosstodon.org
    as secondary instances. Deduplicates by acct field.

    identifier: username or display name (e.g. "johndoe" or "@johndoe@mastodon.social")

    Data keys returned:
        accounts    — list of matching Mastodon accounts (up to 10, deduplicated)
        total       — count of accounts found
        instances_checked — list of instances queried
    """

    platform = "social_mastodon"
    category = CrawlerCategory.SOCIAL_MEDIA
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip().lstrip("@")
        if not query:
            return self._result(
                identifier,
                found=False,
                error="empty_identifier",
                accounts=[],
                total=0,
                instances_checked=[],
            )

        all_accounts: list[dict[str, Any]] = []
        seen_accts: set[str] = set()
        instances_checked: list[str] = []

        for instance in _INSTANCES:
            url = f"https://{instance}{_SEARCH_PATH.format(query=quote_plus(query))}"
            resp = await self.get(url, headers=_HEADERS)

            if resp is None or resp.status_code != 200:
                continue

            instances_checked.append(instance)

            try:
                data = resp.json()
            except Exception as exc:
                logger.debug("Mastodon JSON parse error on %s: %s", instance, exc)
                continue

            accounts = data.get("accounts", [])
            for acc in accounts:
                parsed = _parse_account(acc)
                parsed["instance"] = instance
                acct = parsed.get("acct", "")
                # Normalize acct to include instance if missing
                if "@" not in acct:
                    acct = f"{acct}@{instance}"
                if acct in seen_accts:
                    continue
                seen_accts.add(acct)
                parsed["acct"] = acct
                all_accounts.append(parsed)

            # Stop after finding results on the first successful instance
            if all_accounts:
                break

        # Sort by follower count descending
        all_accounts.sort(key=lambda a: a.get("followers_count", 0), reverse=True)

        return self._result(
            identifier,
            found=len(all_accounts) > 0,
            accounts=all_accounts[:10],
            total=len(all_accounts),
            instances_checked=instances_checked,
        )
