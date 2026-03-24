"""
crypto_bitcoin.py — Bitcoin wallet lookup via blockchain.info free API.

Fetches balance, transaction counts, and recent transactions for a
Bitcoin address. No API key required.
Registered as "crypto_bitcoin".
"""
from __future__ import annotations
import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_BTC_URL = "https://blockchain.info/rawaddr/{address}?limit=10"
_SATOSHI = 1e8


def _satoshi_to_btc(satoshis: int | float) -> float:
    """Convert satoshi integer to BTC float."""
    return int(satoshis) / _SATOSHI


def _parse_recent_txs(txs: list[dict], limit: int = 5) -> list[dict]:
    """Extract minimal fields from the first `limit` transactions."""
    out = []
    for tx in txs[:limit]:
        # Net value from output perspective; best effort
        amount_sat = sum(o.get("value", 0) for o in tx.get("out", []))
        out.append({
            "hash": tx.get("hash", ""),
            "time": tx.get("time", 0),
            "amount_btc": _satoshi_to_btc(amount_sat),
        })
    return out


@register("crypto_bitcoin")
class CryptoBitcoinCrawler(HttpxCrawler):
    """
    Queries blockchain.info for Bitcoin wallet balance and recent transactions.

    Routes through TOR3 — crypto wallet lookups are a high-sensitivity
    operation that must not be attributed to the investigator's IP.
    """

    platform = "crypto_bitcoin"
    source_reliability = 0.85
    requires_tor = True
    tor_instance = TorInstance.TOR3

    async def scrape(self, identifier: str) -> CrawlerResult:
        address = identifier.strip()
        url = _BTC_URL.format(address=address)

        response = await self.get(url)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 404:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="address_not_found",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if response.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{response.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            data = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        balance_btc = _satoshi_to_btc(data.get("final_balance", 0))
        total_received_btc = _satoshi_to_btc(data.get("total_received", 0))
        total_sent_btc = _satoshi_to_btc(data.get("total_sent", 0))
        tx_count = data.get("n_tx", 0)
        recent_txs = _parse_recent_txs(data.get("txs", []))

        return self._result(
            identifier,
            found=True,
            address=address,
            balance_btc=balance_btc,
            total_received_btc=total_received_btc,
            total_sent_btc=total_sent_btc,
            tx_count=tx_count,
            recent_txs=recent_txs,
        )
