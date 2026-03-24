"""
crypto_blockchair.py — Multi-chain crypto lookup via Blockchair free API.

Supports BTC, ETH, LTC, DOGE, BCH, XRP, SOL, BNB, MATIC and more.
Identifier format: "{chain}:{address}" e.g. "btc:1A1z..." or "eth:0x..."
Registered as "crypto_blockchair".
"""
from __future__ import annotations
import logging

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

_BLOCKCHAIR_URL = "https://api.blockchair.com/{chain}/dashboards/address/{address}"

# Mapping from short chain identifiers to Blockchair path segments
BLOCKCHAIR_CHAINS: dict[str, str] = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "ltc": "litecoin",
    "doge": "dogecoin",
    "bch": "bitcoin-cash",
    "xrp": "ripple",
    "sol": "solana",
    "bnb": "bnb",
    "matic": "polygon",
}


def _parse_blockchair_response(json_data: dict, address: str) -> dict | None:
    """
    Extract address stats from Blockchair dashboard response.
    Returns None if the expected structure is absent.
    """
    data_block = json_data.get("data", {})
    if not data_block:
        return None

    # The address key may differ in case; try exact then case-insensitive
    addr_data = data_block.get(address) or data_block.get(address.lower())
    if addr_data is None:
        # Last resort: take the first value
        values = list(data_block.values())
        addr_data = values[0] if values else None

    if addr_data is None:
        return None

    addr_stats = addr_data.get("address", {})
    context = json_data.get("context", {})

    return {
        "balance": addr_stats.get("balance", 0),
        "balance_usd": addr_stats.get("balance_usd"),
        "transaction_count": addr_stats.get("transaction_count", 0),
        "received": addr_stats.get("received", 0),
        "spent": addr_stats.get("spent", 0),
        "output_count": addr_stats.get("output_count"),
        "unspent_output_count": addr_stats.get("unspent_output_count"),
    }


@register("crypto_blockchair")
class CryptoBlockchairCrawler(HttpxCrawler):
    """
    Queries Blockchair for multi-chain crypto address statistics.

    Identifier must be "{chain_code}:{address}", e.g. "btc:1A1z..." or
    "eth:0x1234...".  Supported chain codes: btc, eth, ltc, doge, bch,
    xrp, sol, bnb, matic.

    Routes through TOR3 — crypto wallet lookups are high-sensitivity.
    """

    platform = "crypto_blockchair"
    source_reliability = 0.80
    requires_tor = True
    tor_instance = TorInstance.TOR3

    async def scrape(self, identifier: str) -> CrawlerResult:
        identifier = identifier.strip()

        if ":" not in identifier:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_identifier_format",
                source_reliability=self.source_reliability,
            )

        chain_code, address = identifier.split(":", 1)
        chain_code = chain_code.lower().strip()
        address = address.strip()

        bc_chain = BLOCKCHAIR_CHAINS.get(chain_code)
        if bc_chain is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"unsupported_chain:{chain_code}",
                source_reliability=self.source_reliability,
            )

        url = _BLOCKCHAIR_URL.format(chain=bc_chain, address=address)
        response = await self.get(url)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
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

        if response.status_code == 404:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="address_not_found",
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
            json_data = response.json()
        except Exception:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="invalid_json",
                source_reliability=self.source_reliability,
            )

        stats = _parse_blockchair_response(json_data, address)
        if stats is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="unexpected_response_structure",
                source_reliability=self.source_reliability,
            )

        return self._result(
            identifier,
            found=True,
            chain=chain_code,
            address=address,
            balance=stats["balance"],
            balance_usd=stats.get("balance_usd"),
            transaction_count=stats["transaction_count"],
            received=stats["received"],
            spent=stats["spent"],
        )
