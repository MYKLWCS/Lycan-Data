"""
crypto_ethereum.py — Ethereum wallet lookup via Etherscan free API.

Fetches ETH balance and recent transactions for a 0x... wallet address.
Uses the public demo API key which permits up to 5 req/s without registration.
Registered as "crypto_ethereum".
"""

from __future__ import annotations

import logging

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_ETHERSCAN_BASE = "https://api.etherscan.io/api"
_DEMO_KEY = "YourApiKeyToken"
_WEI = 1e18


def _wei_to_eth(wei: int | str) -> float:
    """Convert wei integer (or string) to ETH float."""
    return int(wei) / _WEI


def _parse_recent_txs(txlist: list[dict], limit: int = 5) -> list[dict]:
    """Extract minimal tx fields from the first `limit` entries."""
    out = []
    for tx in txlist[:limit]:
        out.append(
            {
                "hash": tx.get("hash", ""),
                "from": tx.get("from", ""),
                "to": tx.get("to", ""),
                "amount_eth": _wei_to_eth(tx.get("value", 0)),
                "time": int(tx.get("timeStamp", 0)),
            }
        )
    return out


@register("crypto_ethereum")
class CryptoEthereumCrawler(CurlCrawler):
    """
    Queries Etherscan for ETH wallet balance and recent transaction history.

    Routes through TOR3 — crypto wallet lookups are a high-sensitivity
    operation that must not be attributed to the investigator's IP.
    """

    platform = "crypto_ethereum"
    source_reliability = 0.85
    requires_tor = True
    tor_instance = TorInstance.TOR3

    async def scrape(self, identifier: str) -> CrawlerResult:
        address = identifier.strip()

        # --- Fetch balance ---
        balance_url = (
            f"{_ETHERSCAN_BASE}?module=account&action=balance"
            f"&address={address}&tag=latest&apikey={_DEMO_KEY}"
        )
        bal_resp = await self.get(balance_url)

        if bal_resp is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if bal_resp.status_code == 429:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="rate_limited",
                source_reliability=self.source_reliability,
            )

        if bal_resp.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{bal_resp.status_code}",
                source_reliability=self.source_reliability,
            )

        try:
            bal_data = bal_resp.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        if bal_data.get("status") != "1":
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=bal_data.get("message", "api_error"),
                source_reliability=self.source_reliability,
            )

        balance_eth = _wei_to_eth(bal_data.get("result", 0))

        # --- Fetch recent transactions ---
        tx_url = (
            f"{_ETHERSCAN_BASE}?module=account&action=txlist"
            f"&address={address}&startblock=0&endblock=99999999"
            f"&sort=desc&page=1&offset=10&apikey={_DEMO_KEY}"
        )
        tx_resp = await self.get(tx_url)

        txlist: list[dict] = []
        if tx_resp is not None and tx_resp.status_code == 200:
            try:
                tx_data = tx_resp.json()
                if tx_data.get("status") == "1":
                    txlist = tx_data.get("result", [])
            except Exception:
                pass

        recent_txs = _parse_recent_txs(txlist)

        return self._result(
            identifier,
            found=True,
            address=address,
            balance_eth=balance_eth,
            tx_count=len(txlist),
            recent_txs=recent_txs,
        )
