"""
Tests for crypto tracer crawlers:
  - CryptoBitcoinCrawler    (crypto_bitcoin)    — 4 tests
  - CryptoEthereumCrawler   (crypto_ethereum)   — 4 tests
  - CryptoBlockchairCrawler (crypto_blockchair) — 4 tests

Total: 12 tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.crypto_bitcoin  # noqa: F401 — trigger @register
import modules.crawlers.crypto_blockchair  # noqa: F401
import modules.crawlers.crypto_ethereum  # noqa: F401
from modules.crawlers.crypto_bitcoin import CryptoBitcoinCrawler, _satoshi_to_btc
from modules.crawlers.crypto_blockchair import BLOCKCHAIR_CHAINS, CryptoBlockchairCrawler
from modules.crawlers.crypto_ethereum import CryptoEthereumCrawler, _wei_to_eth
from modules.crawlers.registry import is_registered
from shared.tor import TorInstance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int = 200, json_data=None):
    mock = MagicMock()
    mock.status_code = status_code
    if json_data is not None:
        mock.json.return_value = json_data
    else:
        mock.json.side_effect = ValueError("no json")
    return mock


# ---------------------------------------------------------------------------
# CryptoBitcoinCrawler — 4 tests
# ---------------------------------------------------------------------------

_BTC_JSON = {
    "final_balance": 100_000_000,  # 1.0 BTC
    "total_received": 200_000_000,  # 2.0 BTC
    "total_sent": 100_000_000,  # 1.0 BTC
    "n_tx": 5,
    "txs": [
        {"hash": "abc123", "time": 1700000000, "out": [{"value": 50_000_000}]},
        {"hash": "def456", "time": 1700000100, "out": [{"value": 25_000_000}]},
    ],
}


def test_crypto_bitcoin_registered():
    assert is_registered("crypto_bitcoin")


@pytest.mark.asyncio
async def test_bitcoin_balance_parsed():
    """blockchain.info response is converted from satoshis to BTC correctly."""
    crawler = CryptoBitcoinCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, _BTC_JSON))):
        result = await crawler.scrape("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")

    assert result.found is True
    assert result.platform == "crypto_bitcoin"
    assert result.data["balance_btc"] == pytest.approx(1.0)
    assert result.data["total_received_btc"] == pytest.approx(2.0)
    assert result.data["total_sent_btc"] == pytest.approx(1.0)
    assert result.data["tx_count"] == 5
    assert len(result.data["recent_txs"]) == 2
    assert result.data["recent_txs"][0]["hash"] == "abc123"
    assert result.data["recent_txs"][0]["amount_btc"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_bitcoin_http_error_none():
    """Network failure returns found=False with http_error."""
    crawler = CryptoBitcoinCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")

    assert result.found is False
    assert result.error == "http_error"


def test_satoshi_to_btc_conversion():
    """Satoshi-to-BTC conversion: 1 BTC = 100_000_000 satoshis."""
    assert _satoshi_to_btc(100_000_000) == pytest.approx(1.0)
    assert _satoshi_to_btc(50_000_000) == pytest.approx(0.5)
    assert _satoshi_to_btc(0) == pytest.approx(0.0)


def test_bitcoin_requires_tor3():
    """Bitcoin crawler must use TOR3 for dark-web routing."""
    crawler = CryptoBitcoinCrawler()
    assert crawler.requires_tor is True
    assert crawler.tor_instance == TorInstance.TOR3


# ---------------------------------------------------------------------------
# CryptoEthereumCrawler — 4 tests
# ---------------------------------------------------------------------------

_ETH_BALANCE_JSON = {
    "status": "1",
    "message": "OK",
    "result": str(int(1.5 * 1e18)),  # 1.5 ETH in wei
}

_ETH_TX_JSON = {
    "status": "1",
    "message": "OK",
    "result": [
        {
            "hash": "0xabc",
            "from": "0x111",
            "to": "0x222",
            "value": str(int(0.5 * 1e18)),
            "timeStamp": "1700000000",
        },
        {
            "hash": "0xdef",
            "from": "0x333",
            "to": "0x444",
            "value": str(int(0.25 * 1e18)),
            "timeStamp": "1700000100",
        },
    ],
}


def test_crypto_ethereum_registered():
    assert is_registered("crypto_ethereum")


@pytest.mark.asyncio
async def test_ethereum_balance_parsed():
    """Etherscan response converts wei to ETH and returns tx list."""
    crawler = CryptoEthereumCrawler()

    responses = [
        _mock_response(200, _ETH_BALANCE_JSON),
        _mock_response(200, _ETH_TX_JSON),
    ]

    with patch.object(crawler, "get", new=AsyncMock(side_effect=responses)):
        result = await crawler.scrape("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")

    assert result.found is True
    assert result.platform == "crypto_ethereum"
    assert result.data["balance_eth"] == pytest.approx(1.5)
    assert result.data["tx_count"] == 2
    assert result.data["recent_txs"][0]["hash"] == "0xabc"
    assert result.data["recent_txs"][0]["amount_eth"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_ethereum_api_error_status():
    """Etherscan status != '1' returns found=False with error."""
    crawler = CryptoEthereumCrawler()
    err_json = {"status": "0", "message": "NOTOK", "result": "Invalid address"}

    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, err_json))):
        result = await crawler.scrape("0xinvalid")

    assert result.found is False
    assert result.error == "NOTOK"


def test_wei_to_eth_conversion():
    """Wei-to-ETH conversion: 1 ETH = 10^18 wei."""
    assert _wei_to_eth(int(1e18)) == pytest.approx(1.0)
    assert _wei_to_eth(int(0.5e18)) == pytest.approx(0.5)
    assert _wei_to_eth(0) == pytest.approx(0.0)


def test_ethereum_source_reliability():
    """Ethereum crawler source_reliability should be 0.85."""
    crawler = CryptoEthereumCrawler()
    assert crawler.source_reliability == 0.85


# ---------------------------------------------------------------------------
# CryptoBlockchairCrawler — 4 tests
# ---------------------------------------------------------------------------

_BLOCKCHAIR_JSON = {
    "data": {
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf": {
            "address": {
                "balance": 6_854_000_000,
                "balance_usd": 285_000.0,
                "transaction_count": 3408,
                "received": 6_854_000_000,
                "spent": 0,
                "output_count": 3408,
                "unspent_output_count": 3408,
            }
        }
    },
    "context": {"code": 200},
}


def test_crypto_blockchair_registered():
    assert is_registered("crypto_blockchair")


@pytest.mark.asyncio
async def test_blockchair_btc_parsed():
    """Blockchair BTC response is parsed into balance and tx_count."""
    crawler = CryptoBlockchairCrawler()
    address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf"

    with patch.object(
        crawler, "get", new=AsyncMock(return_value=_mock_response(200, _BLOCKCHAIR_JSON))
    ):
        result = await crawler.scrape(f"btc:{address}")

    assert result.found is True
    assert result.platform == "crypto_blockchair"
    assert result.data["chain"] == "btc"
    assert result.data["address"] == address
    assert result.data["balance"] == 6_854_000_000
    assert result.data["balance_usd"] == pytest.approx(285_000.0)
    assert result.data["transaction_count"] == 3408
    assert result.data["received"] == 6_854_000_000
    assert result.data["spent"] == 0


@pytest.mark.asyncio
async def test_blockchair_invalid_format():
    """Missing colon separator returns error without an HTTP call."""
    crawler = CryptoBlockchairCrawler()
    result = await crawler.scrape("btc1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf")

    assert result.found is False
    assert result.error == "invalid_identifier_format"


@pytest.mark.asyncio
async def test_blockchair_unsupported_chain():
    """Unknown chain code returns error without an HTTP call."""
    crawler = CryptoBlockchairCrawler()
    result = await crawler.scrape("xyz:someaddress")

    assert result.found is False
    assert "unsupported_chain" in result.error


def test_blockchair_chain_mapping():
    """BLOCKCHAIR_CHAINS maps all expected short codes."""
    for code in ("btc", "eth", "ltc", "doge", "bch", "xrp", "sol", "bnb", "matic"):
        assert code in BLOCKCHAIR_CHAINS
    assert BLOCKCHAIR_CHAINS["btc"] == "bitcoin"
    assert BLOCKCHAIR_CHAINS["eth"] == "ethereum"
    assert BLOCKCHAIR_CHAINS["doge"] == "dogecoin"
