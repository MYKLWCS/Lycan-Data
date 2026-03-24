"""
crypto_polygonscan.py — Polygon (MATIC) wallet lookup via PolygonScan API.

Fetches MATIC balance and recent transactions for a Polygon wallet address.
Registered as "crypto_polygonscan".
"""
from __future__ import annotations

import logging
from urllib.parse import quote_plus

from shared.config import settings
from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_BASE = "https://api.polygonscan.com/api"
_WEI = 1e18

_BALANCE_URL = (
    _BASE
    + "?module=account&action=balance"
    + "&address={address}&tag=latest&apikey={key}"
)
_TXLIST_URL = (
    _BASE
    + "?module=account&action=txlist"
    + "&address={address}&sort=desc&page=1&offset=10&apikey={key}"
)


def _wei_to_matic(wei: int | float) -> float:
    """Convert wei integer to MATIC float."""
    return int(wei) / _WEI


def _parse_transactions(txs: list[dict]) -> list[dict]:
    """Extract relevant fields from the transaction list."""
    out = []
    for tx in txs[:10]:
        out.append(
            {
                "hash": tx.get("hash", ""),
                "from": tx.get("from", ""),
                "to": tx.get("to", ""),
                "value": _wei_to_matic(tx.get("value", 0)),
                "timeStamp": tx.get("timeStamp", ""),
                "isError": tx.get("isError", "0"),
            }
        )
    return out


@register("crypto_polygonscan")
class CryptoPolygonscanCrawler(HttpxCrawler):
    """
    Queries PolygonScan for MATIC wallet balance and recent transactions.

    identifier: Polygon wallet address (0x...)
    """

    platform = "crypto_polygonscan"
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        address = identifier.strip()
        api_key: str = getattr(settings, "polygonscan_api_key", "") or "YourApiKeyToken"

        # Fetch balance
        balance_url = _BALANCE_URL.format(address=address, key=api_key)
        balance_resp = await self.get(balance_url)

        if balance_resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                balance_matic=None,
                recent_transactions=[],
            )

        if balance_resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{balance_resp.status_code}",
                balance_matic=None,
                recent_transactions=[],
            )

        try:
            balance_data = balance_resp.json()
        except Exception:
            return self._result(
                identifier,
                found=False,
                error="invalid_json",
                balance_matic=None,
                recent_transactions=[],
            )

        if balance_data.get("status") != "1":
            message = balance_data.get("message", "unknown_error")
            return self._result(
                identifier,
                found=False,
                error=f"api_error:{message}",
                balance_matic=None,
                recent_transactions=[],
            )

        balance_matic = _wei_to_matic(balance_data.get("result", 0))

        # Fetch recent transactions
        txlist_url = _TXLIST_URL.format(address=address, key=api_key)
        tx_resp = await self.get(txlist_url)

        recent_transactions: list[dict] = []
        if tx_resp is not None and tx_resp.status_code == 200:
            try:
                tx_data = tx_resp.json()
                if tx_data.get("status") == "1":
                    recent_transactions = _parse_transactions(
                        tx_data.get("result", [])
                    )
            except Exception as exc:
                logger.warning("PolygonScan txlist parse error: %s", exc)

        return self._result(
            identifier,
            found=True,
            address=address,
            balance_matic=balance_matic,
            recent_transactions=recent_transactions,
        )
