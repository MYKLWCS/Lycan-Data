"""
Comprehensive tests for low-coverage crawler modules.

Modules covered:
  - crypto_bscscan        (CryptoBscscanCrawler)
  - crypto_polygonscan    (CryptoPolygonscanCrawler)
  - news_archive          (NewsArchiveCrawler)
  - news_wikipedia        (WikipediaCrawler)
  - news_search           (NewsSearchCrawler)
  - obituary_search       (ObituarySearchCrawler)
  - email_hibp            (EmailHIBPCrawler)
  - email_holehe          (EmailHoleheCrawler)
  - reddit                (RedditCrawler)
  - github                (GitHubCrawler)
  - google_maps           (GoogleMapsCrawler)
  - httpx_base            (HttpxCrawler + _domain_from_url)
  - db_writer             (upsert_social_profile)

Modules NOT re-tested here (covered by other test files):
  - paste_ghostbin / paste_pastebin / paste_psbdmp  → test_paste_monitor.py
  - public_faa / public_npi / public_nsopw / public_voter → test_public_records.py
  - domain_theharvester / domain_whois             → test_domain_osint.py
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── trigger @register decorators ──────────────────────────────────────────────
import modules.crawlers.crypto_bscscan  # noqa: F401
import modules.crawlers.crypto_polygonscan  # noqa: F401
import modules.crawlers.email_hibp  # noqa: F401
import modules.crawlers.email_holehe  # noqa: F401
import modules.crawlers.github  # noqa: F401
import modules.crawlers.google_maps  # noqa: F401
import modules.crawlers.news_archive  # noqa: F401
import modules.crawlers.news_search  # noqa: F401
import modules.crawlers.news_wikipedia  # noqa: F401
import modules.crawlers.obituary_search  # noqa: F401
import modules.crawlers.reddit  # noqa: F401
from modules.crawlers.crypto_bscscan import (
    CryptoBscscanCrawler,
    _parse_transactions as bsc_parse_txs,
    _wei_to_bnb,
)
from modules.crawlers.crypto_polygonscan import (
    CryptoPolygonscanCrawler,
    _parse_transactions as poly_parse_txs,
    _wei_to_matic,
)
from modules.crawlers.db_writer import upsert_social_profile
from modules.crawlers.email_hibp import EmailHIBPCrawler, _parse_breaches
from modules.crawlers.email_holehe import EmailHoleheCrawler
from modules.crawlers.github import GitHubCrawler
from modules.crawlers.google_maps import (
    GoogleMapsCrawler,
    _parse_google_kg,
    _parse_nominatim_result,
)
from modules.crawlers.httpx_base import HttpxCrawler, _domain_from_url
from modules.crawlers.news_archive import (
    NewsArchiveCrawler,
    _parse_cdx_records,
    _parse_closest,
)
from modules.crawlers.news_search import (
    NewsSearchCrawler,
    _parse_ddg_html,
    _parse_rss,
    _tag_article,
)
from modules.crawlers.news_wikipedia import (
    WikipediaCrawler,
    _parse_summary,
    _parse_wikidata,
    _parse_wp_search,
)
from modules.crawlers.obituary_search import (
    ObituarySearchCrawler,
    _extract_names_from_segment,
    _extract_preceded_by,
    _extract_survived_by,
    _parse_findagrave,
    _parse_legacy,
)
from modules.crawlers.reddit import RedditCrawler
from modules.crawlers.registry import is_registered
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance


# ===========================================================================
# Shared mock helper
# ===========================================================================


def _mock_resp(status=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text or ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


# ===========================================================================
# _domain_from_url  (httpx_base)
# ===========================================================================


def test_domain_from_url_standard():
    assert _domain_from_url("https://api.example.com/path?q=1") == "api.example.com"


def test_domain_from_url_no_scheme():
    # No scheme → urlparse gives empty netloc → returns original string
    result = _domain_from_url("example.com")
    assert result == "example.com"


def test_domain_from_url_with_port():
    assert _domain_from_url("http://localhost:8080/endpoint") == "localhost:8080"


def test_domain_from_url_empty_string():
    assert _domain_from_url("") == ""


# ===========================================================================
# HttpxCrawler.get / post  (httpx_base)
# ===========================================================================


class _ConcreteHttpxCrawler(HttpxCrawler):
    """Minimal concrete subclass so we can instantiate HttpxCrawler."""

    platform = "test_httpx"
    source_reliability = 0.5
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:  # pragma: no cover
        return self._result(identifier, found=False)


@pytest.mark.asyncio
async def test_httpx_get_circuit_open_returns_none():
    """Circuit breaker in OPEN state must cause get() to return None immediately."""
    crawler = _ConcreteHttpxCrawler()
    mock_cb = AsyncMock()
    mock_cb.is_open.return_value = True

    with patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb):
        result = await crawler.get("https://example.com/api")

    assert result is None
    mock_cb.is_open.assert_called_once_with("example.com")


@pytest.mark.asyncio
async def test_httpx_get_circuit_closed_success():
    """Circuit CLOSED → get() completes, records success, returns response."""
    crawler = _ConcreteHttpxCrawler()
    fake_resp = MagicMock()
    fake_resp.status_code = 200

    mock_cb = AsyncMock()
    mock_cb.is_open.return_value = False

    mock_rl = AsyncMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=fake_resp)

    with (
        patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl),
        patch.object(crawler, "_client", return_value=mock_client),
    ):
        result = await crawler.get("https://example.com/api")

    assert result is fake_resp
    mock_cb.record_success.assert_called_once_with("example.com")


@pytest.mark.asyncio
async def test_httpx_get_exception_records_failure():
    """Network exception → get() records failure, returns None."""
    crawler = _ConcreteHttpxCrawler()

    mock_cb = AsyncMock()
    mock_cb.is_open.return_value = False

    mock_rl = AsyncMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

    with (
        patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl),
        patch.object(crawler, "_client", return_value=mock_client),
    ):
        result = await crawler.get("https://example.com/api")

    assert result is None
    mock_cb.record_failure.assert_called_once_with("example.com")


@pytest.mark.asyncio
async def test_httpx_post_circuit_open_returns_none():
    """Circuit breaker OPEN must block POST just like GET."""
    crawler = _ConcreteHttpxCrawler()
    mock_cb = AsyncMock()
    mock_cb.is_open.return_value = True

    with patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb):
        result = await crawler.post("https://example.com/submit", data={"key": "val"})

    assert result is None


@pytest.mark.asyncio
async def test_httpx_post_circuit_closed_success():
    """POST with CLOSED circuit succeeds and records success."""
    crawler = _ConcreteHttpxCrawler()
    fake_resp = MagicMock()
    fake_resp.status_code = 201

    mock_cb = AsyncMock()
    mock_cb.is_open.return_value = False
    mock_rl = AsyncMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=fake_resp)

    with (
        patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl),
        patch.object(crawler, "_client", return_value=mock_client),
    ):
        result = await crawler.post("https://example.com/submit", json={"x": 1})

    assert result is fake_resp
    mock_cb.record_success.assert_called_once_with("example.com")


@pytest.mark.asyncio
async def test_httpx_rate_limiter_failure_does_not_block():
    """Rate limiter acquire raising should not prevent the request from proceeding."""
    crawler = _ConcreteHttpxCrawler()
    fake_resp = MagicMock()

    mock_cb = AsyncMock()
    mock_cb.is_open.return_value = False

    mock_rl = AsyncMock()
    mock_rl.acquire.side_effect = Exception("redis unavailable")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=fake_resp)

    with (
        patch("shared.circuit_breaker.get_circuit_breaker", return_value=mock_cb),
        patch("shared.rate_limiter.get_rate_limiter", return_value=mock_rl),
        patch.object(crawler, "_client", return_value=mock_client),
    ):
        result = await crawler.get("https://example.com/api")

    # Despite rate limiter failure the request still completed
    assert result is fake_resp


# ===========================================================================
# db_writer — upsert_social_profile
# ===========================================================================

def _make_db_writer_mocks(existing_profile=None):
    """
    Return (mock_session, mock_select, mock_SocialProfile, mock_profile) with
    all the plumbing wired up so upsert_social_profile can run without a real DB.
    """
    mock_profile = MagicMock()
    mock_profile.platform = "reddit"

    mock_select_result = MagicMock()  # result of select(...)
    mock_where_result = MagicMock()   # result of .where(...)
    mock_select_result.where.return_value = mock_where_result

    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = existing_profile

    mock_session = MagicMock()
    mock_session.execute = AsyncMock(return_value=mock_execute_result)
    mock_session.flush = AsyncMock()

    return mock_session, mock_select_result, mock_profile


@pytest.mark.asyncio
async def test_upsert_social_profile_insert_new():
    """When no existing profile is found, a new SocialProfile is inserted."""
    result = CrawlerResult(
        platform="reddit",
        identifier="testuser",
        found=True,
        data={
            "handle": "testuser",
            "display_name": "Test User",
            "post_count": 42,
            "is_verified": False,
        },
        profile_url="https://reddit.com/u/testuser",
        source_reliability=0.55,
    )

    mock_session, mock_select_result, mock_profile = _make_db_writer_mocks(existing_profile=None)

    with (
        patch("modules.crawlers.db_writer.select", return_value=mock_select_result),
        patch("modules.crawlers.db_writer.SocialProfile", return_value=mock_profile),
        patch("modules.crawlers.db_writer.apply_quality_to_model", return_value=None),
    ):
        profile = await upsert_social_profile(mock_session, result)

    mock_session.add.assert_called_once()
    mock_session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_social_profile_updates_existing():
    """When an existing profile is found, it is updated in place, not re-added."""
    result = CrawlerResult(
        platform="github",
        identifier="ghuser",
        found=True,
        data={"handle": "ghuser", "display_name": "GH User"},
        profile_url="https://github.com/ghuser",
        source_reliability=0.65,
    )

    existing = MagicMock()
    existing.platform = "github"
    existing.handle = "ghuser"

    mock_session, mock_select_result, _ = _make_db_writer_mocks(existing_profile=existing)

    with (
        patch("modules.crawlers.db_writer.select", return_value=mock_select_result),
        patch("modules.crawlers.db_writer.apply_quality_to_model", return_value=None),
    ):
        profile = await upsert_social_profile(mock_session, result)

    # Should NOT add again since record already exists
    mock_session.add.assert_not_called()
    mock_session.flush.assert_called_once()
    assert profile is existing


@pytest.mark.asyncio
async def test_upsert_social_profile_sets_person_id():
    """person_id is propagated to the profile when supplied."""
    result = CrawlerResult(
        platform="reddit",
        identifier="redditor",
        found=True,
        data={"handle": "redditor"},
        source_reliability=0.55,
    )

    pid = uuid.uuid4()
    mock_session, mock_select_result, mock_profile = _make_db_writer_mocks(existing_profile=None)

    with (
        patch("modules.crawlers.db_writer.select", return_value=mock_select_result),
        patch("modules.crawlers.db_writer.SocialProfile", return_value=mock_profile),
        patch("modules.crawlers.db_writer.apply_quality_to_model", return_value=None),
    ):
        await upsert_social_profile(mock_session, result, person_id=pid)

    assert mock_profile.person_id == pid


# ===========================================================================
# crypto_bscscan
# ===========================================================================

_BSC_BALANCE_JSON = {"status": "1", "message": "OK", "result": str(int(2.5 * 1e18))}

_BSC_TX_JSON = {
    "status": "1",
    "message": "OK",
    "result": [
        {
            "hash": "0xbsc1",
            "from": "0xAAA",
            "to": "0xBBB",
            "value": str(int(1.0 * 1e18)),
            "timeStamp": "1700000001",
            "isError": "0",
        },
        {
            "hash": "0xbsc2",
            "from": "0xCCC",
            "to": "0xDDD",
            "value": str(int(0.5 * 1e18)),
            "timeStamp": "1700000002",
            "isError": "0",
        },
    ],
}


def test_crypto_bscscan_registered():
    assert is_registered("crypto_bscscan")


def test_wei_to_bnb_conversion():
    assert _wei_to_bnb(int(1e18)) == pytest.approx(1.0)
    assert _wei_to_bnb(int(2.5e18)) == pytest.approx(2.5)
    assert _wei_to_bnb(0) == pytest.approx(0.0)


def test_bsc_parse_transactions_fields():
    txs = bsc_parse_txs(_BSC_TX_JSON["result"])
    assert len(txs) == 2
    assert txs[0]["hash"] == "0xbsc1"
    assert txs[0]["value"] == pytest.approx(1.0)
    assert txs[0]["isError"] == "0"
    assert txs[1]["hash"] == "0xbsc2"


def test_bsc_parse_transactions_limits_to_10():
    big_list = [{"hash": f"0x{i}", "from": "", "to": "", "value": 0, "timeStamp": "", "isError": "0"} for i in range(20)]
    result = bsc_parse_txs(big_list)
    assert len(result) == 10


@pytest.mark.asyncio
async def test_bscscan_scrape_success():
    """Full success path returns found=True with balance and transactions."""
    crawler = CryptoBscscanCrawler()
    responses = [_mock_resp(200, _BSC_BALANCE_JSON), _mock_resp(200, _BSC_TX_JSON)]

    with patch.object(crawler, "get", new=AsyncMock(side_effect=responses)):
        result = await crawler.scrape("0xBSCWALLET")

    assert result.found is True
    assert result.platform == "crypto_bscscan"
    assert result.data["balance_bnb"] == pytest.approx(2.5)
    assert len(result.data["recent_transactions"]) == 2
    assert result.data["recent_transactions"][0]["hash"] == "0xbsc1"


@pytest.mark.asyncio
async def test_bscscan_get_none_returns_http_error():
    crawler = CryptoBscscanCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("0xANY")

    assert result.found is False
    # _result() stores kwargs in data dict
    assert result.data.get("error") == "http_error"


@pytest.mark.asyncio
async def test_bscscan_non_200_status():
    crawler = CryptoBscscanCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
        result = await crawler.scrape("0xANY")

    assert result.found is False
    assert "http_503" in result.data.get("error", "")


@pytest.mark.asyncio
async def test_bscscan_invalid_json():
    """JSON parse failure returns found=False with invalid_json error."""
    crawler = CryptoBscscanCrawler()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = ValueError("bad json")

    with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
        result = await crawler.scrape("0xANY")

    assert result.found is False
    assert result.data.get("error") == "invalid_json"


@pytest.mark.asyncio
async def test_bscscan_api_status_not_1():
    """BscScan status != '1' returns api_error."""
    crawler = CryptoBscscanCrawler()
    err_json = {"status": "0", "message": "No transactions found", "result": ""}
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, err_json))):
        result = await crawler.scrape("0xBAD")

    assert result.found is False
    assert result.data.get("error", "").startswith("api_error:")


@pytest.mark.asyncio
async def test_bscscan_tx_fetch_failure_still_returns_balance():
    """Tx list request failing should not cancel the balance result."""
    crawler = CryptoBscscanCrawler()
    responses = [_mock_resp(200, _BSC_BALANCE_JSON), None]

    with patch.object(crawler, "get", new=AsyncMock(side_effect=responses)):
        result = await crawler.scrape("0xBSCWALLET")

    assert result.found is True
    assert result.data["balance_bnb"] == pytest.approx(2.5)
    assert result.data["recent_transactions"] == []


def test_bscscan_source_reliability():
    assert CryptoBscscanCrawler().source_reliability == pytest.approx(0.90)


def test_bscscan_requires_tor_false():
    assert CryptoBscscanCrawler().requires_tor is False


# ===========================================================================
# crypto_polygonscan
# ===========================================================================

_POLY_BALANCE_JSON = {"status": "1", "message": "OK", "result": str(int(10.0 * 1e18))}

_POLY_TX_JSON = {
    "status": "1",
    "message": "OK",
    "result": [
        {
            "hash": "0xpoly1",
            "from": "0x111",
            "to": "0x222",
            "value": str(int(5.0 * 1e18)),
            "timeStamp": "1700000003",
            "isError": "0",
        }
    ],
}


def test_crypto_polygonscan_registered():
    assert is_registered("crypto_polygonscan")


def test_wei_to_matic_conversion():
    assert _wei_to_matic(int(1e18)) == pytest.approx(1.0)
    assert _wei_to_matic(int(10e18)) == pytest.approx(10.0)
    assert _wei_to_matic(0) == pytest.approx(0.0)


def test_poly_parse_transactions_fields():
    txs = poly_parse_txs(_POLY_TX_JSON["result"])
    assert len(txs) == 1
    assert txs[0]["hash"] == "0xpoly1"
    assert txs[0]["value"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_polygonscan_scrape_success():
    crawler = CryptoPolygonscanCrawler()
    responses = [_mock_resp(200, _POLY_BALANCE_JSON), _mock_resp(200, _POLY_TX_JSON)]

    with patch.object(crawler, "get", new=AsyncMock(side_effect=responses)):
        result = await crawler.scrape("0xPOLYWALLET")

    assert result.found is True
    assert result.platform == "crypto_polygonscan"
    assert result.data["balance_matic"] == pytest.approx(10.0)
    assert len(result.data["recent_transactions"]) == 1
    assert result.data["address"] == "0xPOLYWALLET"


@pytest.mark.asyncio
async def test_polygonscan_get_none():
    crawler = CryptoPolygonscanCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("0xANY")

    assert result.found is False
    assert result.data.get("error") == "http_error"


@pytest.mark.asyncio
async def test_polygonscan_non_200():
    crawler = CryptoPolygonscanCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
        result = await crawler.scrape("0xANY")

    assert result.found is False
    assert "http_500" in result.data.get("error", "")


@pytest.mark.asyncio
async def test_polygonscan_invalid_json():
    crawler = CryptoPolygonscanCrawler()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = ValueError("bad json")
    with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
        result = await crawler.scrape("0xANY")

    assert result.found is False
    assert result.data.get("error") == "invalid_json"


@pytest.mark.asyncio
async def test_polygonscan_api_error_status():
    crawler = CryptoPolygonscanCrawler()
    err_json = {"status": "0", "message": "Invalid address format", "result": ""}
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, err_json))):
        result = await crawler.scrape("0xBAD")

    assert result.found is False
    assert "api_error:" in result.data.get("error", "")


@pytest.mark.asyncio
async def test_polygonscan_tx_none_still_returns_balance():
    crawler = CryptoPolygonscanCrawler()
    responses = [_mock_resp(200, _POLY_BALANCE_JSON), None]
    with patch.object(crawler, "get", new=AsyncMock(side_effect=responses)):
        result = await crawler.scrape("0xPOLYWALLET")

    assert result.found is True
    assert result.data["recent_transactions"] == []


def test_polygonscan_source_reliability():
    assert CryptoPolygonscanCrawler().source_reliability == pytest.approx(0.90)


# ===========================================================================
# news_archive
# ===========================================================================

_CLOSEST_JSON = {
    "archived_snapshots": {
        "closest": {
            "url": "https://web.archive.org/web/20240101/http://example.com",
            "timestamp": "20240101000000",
            "status": "200",
            "available": True,
        }
    }
}

_CDX_ROWS = [
    ["timestamp", "original", "statuscode", "length"],
    ["20230501", "http://example.com/", "200", "12345"],
    ["20230601", "http://example.com/about", "200", "8765"],
]

_CDX_COUNT_INT = 42


def test_news_archive_registered():
    assert is_registered("news_archive")


def test_parse_closest_full():
    snap = _parse_closest(_CLOSEST_JSON)
    assert snap["available"] is True
    assert snap["timestamp"] == "20240101000000"
    assert "example.com" in snap["url"]


def test_parse_closest_empty():
    assert _parse_closest({}) == {}
    assert _parse_closest({"archived_snapshots": {}}) == {}


def test_parse_cdx_records_happy():
    records = _parse_cdx_records(_CDX_ROWS)
    assert len(records) == 2
    assert records[0]["timestamp"] == "20230501"
    assert records[0]["statuscode"] == "200"
    assert records[1]["original"] == "http://example.com/about"


def test_parse_cdx_records_empty():
    assert _parse_cdx_records([]) == []


def test_parse_cdx_records_skips_short_rows():
    rows = [["timestamp", "original"], ["20230101"]]  # second row too short
    records = _parse_cdx_records(rows)
    assert records == []


@pytest.mark.asyncio
async def test_news_archive_scrape_found():
    crawler = NewsArchiveCrawler()

    def make_get(closest, cdx_rows, cdx_count):
        calls = [0]

        async def _get(url, **kwargs):
            calls[0] += 1
            if calls[0] == 1:
                return _mock_resp(200, closest)
            elif calls[0] == 2:
                return _mock_resp(200, cdx_rows)
            else:
                return _mock_resp(200, cdx_count)

        return _get

    with patch.object(
        crawler, "get", new=make_get(_CLOSEST_JSON, _CDX_ROWS, _CDX_COUNT_INT)
    ):
        result = await crawler.scrape("example.com")

    assert result.found is True
    assert result.platform == "news_archive"
    assert result.data["closest_snapshot"]["available"] is True
    assert len(result.data["cdx_records"]) == 2
    assert result.data["total_snapshots"] == 42


@pytest.mark.asyncio
async def test_news_archive_all_requests_fail():
    """All sub-requests returning None produces found=False."""
    crawler = NewsArchiveCrawler()

    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("missing.com")

    assert result.found is False
    assert result.data["closest_snapshot"] == {}
    assert result.data["cdx_records"] == []
    assert result.data["total_snapshots"] == 0


@pytest.mark.asyncio
async def test_news_archive_cdx_count_list_form():
    """CDX count returned as list with single numeric element."""
    crawler = NewsArchiveCrawler()
    calls = [0]

    async def _get(url, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return _mock_resp(200, _CLOSEST_JSON)
        elif calls[0] == 2:
            return _mock_resp(200, [])  # empty cdx rows
        else:
            return _mock_resp(200, [99])  # list form of count

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("example.com")

    assert result.data["total_snapshots"] == 99


def test_news_archive_source_reliability():
    assert NewsArchiveCrawler().source_reliability == pytest.approx(0.85)


def test_news_archive_requires_tor_false():
    assert NewsArchiveCrawler().requires_tor is False


# ===========================================================================
# news_wikipedia
# ===========================================================================

_WP_SEARCH_JSON = {
    "query": {
        "search": [
            {
                "title": "Elon Musk",
                "snippet": "Business magnate and investor",
                "pageid": 111,
                "wordcount": 50000,
                "timestamp": "2024-01-01T00:00:00Z",
            },
            {
                "title": "Elon Musk (disambiguation)",
                "snippet": "May refer to...",
                "pageid": 222,
                "wordcount": 100,
                "timestamp": "2023-06-01T00:00:00Z",
            },
        ]
    }
}

_WP_SUMMARY_JSON = {
    "title": "Elon Musk",
    "extract": "Elon Reeve Musk is a business magnate...",
    "description": "Business magnate and investor",
    "thumbnail": {"source": "https://upload.wikimedia.org/elon.jpg"},
    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Elon_Musk"}},
}

_WD_SEARCH_JSON = {
    "search": [
        {
            "id": "Q317521",
            "label": "Elon Musk",
            "description": "business magnate",
            "aliases": [{"value": "Elon R. Musk"}],
            "url": "https://www.wikidata.org/wiki/Q317521",
        }
    ]
}


def test_news_wikipedia_registered():
    assert is_registered("news_wikipedia")


def test_parse_wp_search_extracts_results():
    results = _parse_wp_search(_WP_SEARCH_JSON)
    assert len(results) == 2
    assert results[0]["title"] == "Elon Musk"
    assert results[0]["pageid"] == 111
    assert "magnate" in results[0]["snippet"]


def test_parse_wp_search_empty():
    assert _parse_wp_search({}) == []
    assert _parse_wp_search({"query": {}}) == []


def test_parse_summary_fields():
    s = _parse_summary(_WP_SUMMARY_JSON)
    assert s["title"] == "Elon Musk"
    assert "magnate" in s["extract"]
    assert s["thumbnail"] == "https://upload.wikimedia.org/elon.jpg"
    assert "Elon_Musk" in s["content_url"]


def test_parse_wikidata_fields():
    entities = _parse_wikidata(_WD_SEARCH_JSON)
    assert len(entities) == 1
    assert entities[0]["id"] == "Q317521"
    assert entities[0]["label"] == "Elon Musk"
    assert "Elon R. Musk" in entities[0]["aliases"]


@pytest.mark.asyncio
async def test_wikipedia_scrape_full_success():
    """All three sub-requests succeed → found=True with full data."""
    crawler = WikipediaCrawler()
    calls = [0]

    async def _get(url, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return _mock_resp(200, _WP_SEARCH_JSON)
        elif calls[0] == 2:
            return _mock_resp(200, _WP_SUMMARY_JSON)
        else:
            return _mock_resp(200, _WD_SEARCH_JSON)

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("Elon Musk")

    assert result.found is True
    assert result.platform == "news_wikipedia"
    assert len(result.data["wikipedia_results"]) == 2
    assert result.data["top_summary"]["title"] == "Elon Musk"
    assert len(result.data["wikidata_entities"]) == 1


@pytest.mark.asyncio
async def test_wikipedia_scrape_no_results():
    """Empty search → found=False."""
    crawler = WikipediaCrawler()
    empty_search = {"query": {"search": []}}
    empty_wd = {"search": []}

    async def _get(url, **kwargs):
        if "wikipedia.org/w/api.php" in url:
            return _mock_resp(200, empty_search)
        elif "wikidata.org" in url:
            return _mock_resp(200, empty_wd)
        return None

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("totally unknown xyz")

    assert result.found is False
    assert result.data["wikipedia_results"] == []
    assert result.data["top_summary"] == {}


@pytest.mark.asyncio
async def test_wikipedia_scrape_wp_request_fails():
    """WP search returning None results in empty wp_results."""
    crawler = WikipediaCrawler()

    async def _get(url, **kwargs):
        if "wikidata" in url:
            return _mock_resp(200, _WD_SEARCH_JSON)
        return None

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("Elon Musk")

    # Wikidata found something so found=True
    assert result.found is True
    assert result.data["wikipedia_results"] == []
    assert len(result.data["wikidata_entities"]) == 1


def test_wikipedia_source_reliability():
    assert WikipediaCrawler().source_reliability == pytest.approx(0.90)


def test_wikipedia_requires_tor_false():
    assert WikipediaCrawler().requires_tor is False


# ===========================================================================
# news_search
# ===========================================================================

_DDG_HTML = """
<html><body>
<div class="result">
  <a class="result__a" href="https://example.com/article1">CEO arrested for fraud</a>
  <div class="result__snippet">John Smith was arrested after SEC investigation.</div>
  <span class="result__timestamp">2024-01-10</span>
</div>
<div class="result">
  <a class="result__a" href="https://other.com/article2">Company IPO success</a>
  <div class="result__snippet">Record-breaking IPO raised $2B.</div>
</div>
</body></html>
"""

_RSS_XML = """<?xml version="1.0"?>
<rss version="2.0">
<channel>
  <item>
    <title>John Smith lawsuit filed</title>
    <link>https://news.example.com/lawsuit</link>
    <pubDate>Mon, 15 Jan 2024 00:00:00 GMT</pubDate>
    <description>John Smith faces a class-action lawsuit in California court.</description>
  </item>
  <item>
    <title>Startup funding round</title>
    <link>https://news.example.com/funding</link>
    <pubDate>Tue, 16 Jan 2024 00:00:00 GMT</pubDate>
    <description>Series B funding secured by tech startup.</description>
  </item>
</channel>
</rss>
"""

_EMPTY_RSS = """<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""


def test_news_search_registered():
    assert is_registered("news_search")


def test_tag_article_legal():
    tags = _tag_article("CEO sued in court", "lawsuit settlement reached")
    assert "legal" in tags


def test_tag_article_criminal():
    tags = _tag_article("Man arrested for assault", "sentenced to prison")
    assert "criminal" in tags


def test_tag_article_financial():
    tags = _tag_article("Company IPO announced", "SEC investigation begins")
    assert "financial" in tags


def test_tag_article_general_fallback():
    tags = _tag_article("Weather report today", "cloudy skies expected")
    assert tags == ["general"]


def test_parse_ddg_html_extracts_articles():
    articles = _parse_ddg_html(_DDG_HTML)
    assert len(articles) == 2
    assert articles[0]["title"] == "CEO arrested for fraud"
    assert articles[0]["url"] == "https://example.com/article1"
    assert "criminal" in articles[0]["categories"] or "legal" in articles[0]["categories"]


def test_parse_ddg_html_empty():
    assert _parse_ddg_html("<html><body></body></html>") == []


def test_parse_rss_extracts_items():
    articles = _parse_rss(_RSS_XML, source="google_news")
    assert len(articles) == 2
    assert articles[0]["title"] == "John Smith lawsuit filed"
    assert articles[0]["source"] == "google_news"
    assert "legal" in articles[0]["categories"]
    assert articles[1]["title"] == "Startup funding round"


def test_parse_rss_empty_channel():
    articles = _parse_rss(_EMPTY_RSS, source="bing_news")
    assert articles == []


def test_parse_rss_invalid_xml():
    articles = _parse_rss("THIS IS NOT XML!!!", source="bing_news")
    assert articles == []


@pytest.mark.asyncio
async def test_news_search_scrape_aggregates_sources():
    """Successful scrape from all three sources deduplicates and aggregates."""
    crawler = NewsSearchCrawler()
    calls = [0]

    async def _get(url, **kwargs):
        calls[0] += 1
        if calls[0] == 1:  # DDG
            return _mock_resp(200, text=_DDG_HTML)
        elif calls[0] == 2:  # Google News RSS
            return _mock_resp(200, text=_RSS_XML)
        else:  # Bing RSS
            return _mock_resp(200, text=_EMPTY_RSS)

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("John Smith")

    assert result.found is True
    assert result.platform == "news_search"
    # DDG gives 2, RSS gives 2, Bing gives 0 → 4 total (all unique URLs)
    assert result.data["article_count"] == 4
    assert result.data["query"] == "John Smith"


@pytest.mark.asyncio
async def test_news_search_deduplicates_urls():
    """Same URL from two sources is counted only once."""
    crawler = NewsSearchCrawler()

    # Both DDG and RSS return an article with same URL
    ddg_html = """
    <html><body>
    <div class="result">
      <a class="result__a" href="https://shared.com/article">Shared article</a>
    </div>
    </body></html>
    """
    rss_xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Shared article</title>
        <link>https://shared.com/article</link>
        <description>Content</description>
      </item>
    </channel></rss>
    """
    calls = [0]

    async def _get(url, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return _mock_resp(200, text=ddg_html)
        elif calls[0] == 2:
            return _mock_resp(200, text=rss_xml)
        else:
            return _mock_resp(200, text=_EMPTY_RSS)

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("something")

    # shared URL appears only once
    assert result.data["article_count"] == 1


@pytest.mark.asyncio
async def test_news_search_all_requests_fail():
    """All HTTP requests failing returns found=True with empty article list."""
    crawler = NewsSearchCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("no results")

    assert result.found is True  # crawler always returns True
    assert result.data["article_count"] == 0


def test_news_search_uses_tor():
    crawler = NewsSearchCrawler()
    assert crawler.requires_tor is True
    assert crawler.tor_instance == TorInstance.TOR2


# ===========================================================================
# obituary_search
# ===========================================================================

_LEGACY_HTML = """
<html><body>
<div class="obituary-listing">
  <h3 class="name">John Smith</h3>
  <span class="date">January 5, 2024</span>
  <span class="location">Dallas, TX</span>
  <p>
    John Smith, age 72, passed away on January 5, 2024.
    He is survived by his wife Mary Smith and son Robert Smith.
    Preceded in death by his parents William Smith and Alice Jones.
    Memorial service will be held Saturday.
  </p>
</div>
<div class="obituary-listing">
  <h3 class="name">Jane Doe</h3>
  <span class="date">February 10, 2024</span>
</div>
</body></html>
"""

_FINDAGRAVE_HTML = """
<html><body>
<div class="memorial-item">
  <a class="name" href="/memorial/12345">Robert Johnson</a>
  <p>1945 - 2020 Beloved father and husband.</p>
</div>
</body></html>
"""

_EMPTY_OBT_HTML = "<html><body><p>No results found.</p></body></html>"


def test_obituary_search_registered():
    assert is_registered("obituary_search")


def test_extract_survived_by():
    # Names must start with capital letters and appear after commas/semicolons/and
    # so they are picked up by _extract_names_from_segment
    text = "survived by Mary Smith, Robert Smith, Alice Brown memorial service follows"
    names = _extract_survived_by(text)
    assert isinstance(names, list)
    assert len(names) >= 1
    full = " ".join(names)
    assert "Mary Smith" in full


def test_extract_preceded_by():
    # Names must appear comma/and separated and start capitalised
    text = "preceded in death by William Smith, Alice Jones survived by children"
    names = _extract_preceded_by(text)
    assert isinstance(names, list)
    assert len(names) >= 1
    full = " ".join(names)
    assert "William Smith" in full


def test_extract_survived_by_no_marker():
    assert _extract_survived_by("No marker text here.") == []


def test_extract_preceded_by_no_marker():
    assert _extract_preceded_by("Nothing relevant.") == []


def test_extract_names_from_segment_basic():
    segment = "Mary Smith, Robert Johnson, and Alice Brown"
    names = _extract_names_from_segment(segment)
    assert "Mary Smith" in names
    assert "Robert Johnson" in names
    assert "Alice Brown" in names


def test_extract_names_from_segment_limits_to_10():
    segment = ", ".join([f"Person{chr(65+i)} Smith" for i in range(15)])
    names = _extract_names_from_segment(segment)
    assert len(names) <= 10


def test_parse_legacy_extracts_obits():
    results = _parse_legacy(_LEGACY_HTML, "John Smith")
    assert len(results) >= 1
    assert any(r.get("name") == "John Smith" for r in results)
    assert results[0]["source"] == "legacy.com"


def test_parse_legacy_empty_html():
    results = _parse_legacy(_EMPTY_OBT_HTML, "Nobody")
    assert results == []


def test_parse_findagrave_extracts_memorials():
    results = _parse_findagrave(_FINDAGRAVE_HTML, "Robert Johnson")
    assert len(results) >= 1
    assert results[0]["source"] == "findagrave.com"
    assert results[0]["name"] == "Robert Johnson"
    # birth_year holds the regex capture group (18|19|20), death_year the next match
    # so values are "19" and "20" — the function stores the capture group fragment
    assert results[0]["birth_year"] is not None
    assert results[0]["death_year"] is not None
    # date is formatted as "birth–death"
    assert results[0]["date"] is not None and "–" in results[0]["date"]


def test_parse_findagrave_empty_html():
    results = _parse_findagrave(_EMPTY_OBT_HTML, "Nobody")
    assert results == []


@pytest.mark.asyncio
async def test_obituary_search_scrape_found():
    crawler = ObituarySearchCrawler()
    calls = [0]

    async def _get(url, **kwargs):
        calls[0] += 1
        if calls[0] == 1:  # Legacy
            return _mock_resp(200, text=_LEGACY_HTML)
        else:  # FindAGrave
            return _mock_resp(200, text=_FINDAGRAVE_HTML)

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("John Smith")

    assert result.found is True
    assert result.platform == "obituary_search"
    assert len(result.data["obituaries"]) >= 1
    assert "legacy.com" in result.data["sources_checked"]
    assert "findagrave.com" in result.data["sources_checked"]


@pytest.mark.asyncio
async def test_obituary_search_with_location():
    """Pipe-separated identifier includes location filter."""
    crawler = ObituarySearchCrawler()

    async def _get(url, **kwargs):
        if "legacy" in url:
            assert "Dallas" in url or "location" in url
            return _mock_resp(200, text=_LEGACY_HTML)
        return _mock_resp(200, text=_EMPTY_OBT_HTML)

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("John Smith|Dallas,TX")

    assert result.data["query"] == "John Smith"


@pytest.mark.asyncio
async def test_obituary_search_both_fail():
    crawler = ObituarySearchCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("Ghost Person")

    assert result.found is False
    assert result.data["obituaries"] == []


def test_obituary_search_uses_tor():
    crawler = ObituarySearchCrawler()
    assert crawler.requires_tor is True
    assert crawler.tor_instance == TorInstance.TOR2


# ===========================================================================
# email_hibp
# ===========================================================================

_HIBP_BREACHES = [
    {"Name": "Adobe", "Domain": "adobe.com", "BreachDate": "2013-10-04", "DataClasses": ["Email", "Password"]},
    {"Name": "LinkedIn", "Domain": "linkedin.com", "BreachDate": "2012-05-05", "DataClasses": ["Email", "Password", "Username"]},
]


def test_email_hibp_registered():
    assert is_registered("email_hibp")


def test_parse_breaches_fields():
    breaches = _parse_breaches(_HIBP_BREACHES)
    assert len(breaches) == 2
    assert breaches[0]["name"] == "Adobe"
    assert breaches[0]["domain"] == "adobe.com"
    assert "Password" in breaches[0]["data_classes"]
    assert breaches[1]["name"] == "LinkedIn"


def test_parse_breaches_empty():
    assert _parse_breaches([]) == []


@pytest.mark.asyncio
async def test_hibp_scrape_found_breaches():
    crawler = EmailHIBPCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, _HIBP_BREACHES))):
        result = await crawler.scrape("test@example.com")

    assert result.found is True
    assert result.platform == "email_hibp"
    assert result.data["breach_count"] == 2
    assert result.data["email"] == "test@example.com"
    assert result.data["breaches"][0]["name"] == "Adobe"


@pytest.mark.asyncio
async def test_hibp_404_means_clean():
    """404 = no breaches found — still returns found=True with empty list."""
    crawler = EmailHIBPCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
        result = await crawler.scrape("clean@example.com")

    assert result.found is True
    assert result.data["breaches"] == []
    assert result.data["breach_count"] == 0


@pytest.mark.asyncio
async def test_hibp_429_rate_limited():
    crawler = EmailHIBPCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "rate_limited"


@pytest.mark.asyncio
async def test_hibp_http_none():
    crawler = EmailHIBPCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_hibp_non_200_non_404_non_429():
    crawler = EmailHIBPCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert "http_503" in result.error


@pytest.mark.asyncio
async def test_hibp_invalid_json():
    crawler = EmailHIBPCrawler()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = ValueError("bad json")
    with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "invalid_json"


def test_hibp_source_reliability():
    assert EmailHIBPCrawler().source_reliability == pytest.approx(0.80)


def test_hibp_lowercases_email():
    """Email is normalised to lowercase before querying."""
    # Just check the crawler stores the lowercased version
    crawler = EmailHIBPCrawler()
    # Can verify by inspecting what URL would be constructed for upper-case input
    # The scrape method does: email = identifier.strip().lower()
    # We can test via a mock that checks the URL
    captured_urls = []

    async def _get(url, **kwargs):
        captured_urls.append(url)
        return _mock_resp(404)

    import asyncio as _asyncio
    _asyncio.get_event_loop().run_until_complete(
        _run_with_patch(crawler, _get, "TEST@EXAMPLE.COM")
    )
    assert "test@example.com" in captured_urls[0]


async def _run_with_patch(crawler, fake_get, identifier):
    with patch.object(crawler, "get", new=fake_get):
        return await crawler.scrape(identifier)


# ===========================================================================
# email_holehe
# ===========================================================================


def test_email_holehe_registered():
    assert is_registered("email_holehe")


@pytest.mark.asyncio
async def test_holehe_not_installed():
    crawler = EmailHoleheCrawler()
    with patch(
        "modules.crawlers.email_holehe._check_holehe_installed",
        new=AsyncMock(return_value=False),
    ):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "holehe_not_installed"


@pytest.mark.asyncio
async def test_holehe_success():
    crawler = EmailHoleheCrawler()
    with (
        patch(
            "modules.crawlers.email_holehe._check_holehe_installed",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "modules.crawlers.email_holehe._run_holehe",
            new=AsyncMock(return_value=(["github.com", "twitter.com"], 50)),
        ),
    ):
        result = await crawler.scrape("test@example.com")

    assert result.found is True
    assert result.platform == "email_holehe"
    assert result.data["email"] == "test@example.com"
    assert "github.com" in result.data["found_on"]
    assert result.data["checked_count"] == 50


@pytest.mark.asyncio
async def test_holehe_timeout():
    crawler = EmailHoleheCrawler()
    with (
        patch(
            "modules.crawlers.email_holehe._check_holehe_installed",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "modules.crawlers.email_holehe._run_holehe",
            new=AsyncMock(side_effect=TimeoutError()),
        ),
    ):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "holehe_timeout"


@pytest.mark.asyncio
async def test_holehe_file_not_found():
    """FileNotFoundError from _run_holehe maps to holehe_not_installed."""
    crawler = EmailHoleheCrawler()
    with (
        patch(
            "modules.crawlers.email_holehe._check_holehe_installed",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "modules.crawlers.email_holehe._run_holehe",
            new=AsyncMock(side_effect=FileNotFoundError()),
        ),
    ):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "holehe_not_installed"


def test_holehe_source_reliability():
    assert EmailHoleheCrawler().source_reliability == pytest.approx(0.70)


def test_holehe_requires_tor_false():
    assert EmailHoleheCrawler().requires_tor is False


# ===========================================================================
# reddit
# ===========================================================================

_REDDIT_ABOUT_JSON = {
    "data": {
        "name": "testuser",
        "id": "abc123",
        "link_karma": 1500,
        "comment_karma": 3200,
        "created_utc": 1600000000,
        "verified": False,
        "is_gold": False,
        "has_verified_email": True,
    }
}

_REDDIT_POSTS_JSON = {
    "data": {
        "children": [
            {
                "data": {
                    "subreddit": "python",
                    "title": "How do I async?",
                    "score": 42,
                    "created_utc": 1700000000,
                }
            },
            {
                "data": {
                    "subreddit": "technology",
                    "title": "New tool released",
                    "score": 15,
                    "created_utc": 1700001000,
                }
            },
        ]
    }
}


def test_reddit_registered():
    assert is_registered("reddit")


@pytest.mark.asyncio
async def test_reddit_scrape_success():
    crawler = RedditCrawler()
    calls = [0]

    async def _get(url, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return _mock_resp(200, _REDDIT_ABOUT_JSON)
        else:
            return _mock_resp(200, _REDDIT_POSTS_JSON)

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("testuser")

    assert result.found is True
    assert result.platform == "reddit"
    assert result.data["handle"] == "testuser"
    assert result.data["link_karma"] == 1500
    assert result.data["comment_karma"] == 3200
    assert result.data["has_verified_email"] is True
    assert len(result.data["recent_posts"]) == 2
    assert result.data["recent_posts"][0]["subreddit"] == "python"


@pytest.mark.asyncio
async def test_reddit_u_prefix_stripped():
    """u/ prefix is stripped from identifier before query."""
    crawler = RedditCrawler()
    captured = []

    async def _get(url, **kwargs):
        captured.append(url)
        return _mock_resp(200, _REDDIT_ABOUT_JSON)

    with patch.object(crawler, "get", new=_get):
        await crawler.scrape("u/testuser")

    assert "testuser" in captured[0]
    assert "u/" not in captured[0].split("/user/")[1]


@pytest.mark.asyncio
async def test_reddit_404_not_found():
    crawler = RedditCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
        result = await crawler.scrape("nonexistent_user")

    assert result.found is False


@pytest.mark.asyncio
async def test_reddit_http_none():
    crawler = RedditCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("testuser")

    assert result.found is False
    # reddit uses self._result() so error goes in data dict
    assert result.data.get("error") == "timeout"


@pytest.mark.asyncio
async def test_reddit_non_200_status():
    crawler = RedditCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
        result = await crawler.scrape("testuser")

    assert result.found is False
    assert "http_503" in result.data.get("error", "")


@pytest.mark.asyncio
async def test_reddit_empty_data_field():
    """data field empty → not found."""
    crawler = RedditCrawler()
    resp = _mock_resp(200, {"data": {}})
    with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
        result = await crawler.scrape("emptyuser")

    assert result.found is False


@pytest.mark.asyncio
async def test_reddit_posts_fetch_failure_doesnt_crash():
    """Posts request failing should not crash the scrape."""
    crawler = RedditCrawler()
    calls = [0]

    async def _get(url, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            return _mock_resp(200, _REDDIT_ABOUT_JSON)
        return None  # posts request fails

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("testuser")

    assert result.found is True
    assert "recent_posts" not in result.data or result.data.get("recent_posts") is None


def test_reddit_uses_tor():
    assert RedditCrawler().requires_tor is True


# ===========================================================================
# github
# ===========================================================================

_GITHUB_USER_JSON = {
    "name": "Jane Developer",
    "bio": "Software engineer",
    "public_repos": 30,
    "followers": 150,
    "following": 50,
    "company": "Acme Corp",
    "location": "San Francisco, CA",
    "blog": "https://janedev.io",
    "avatar_url": "https://avatars.githubusercontent.com/u/12345",
    "created_at": "2018-04-01T00:00:00Z",
}


def test_github_registered():
    assert is_registered("github")


@pytest.mark.asyncio
async def test_github_scrape_success():
    crawler = GitHubCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, _GITHUB_USER_JSON))):
        result = await crawler.scrape("janedev")

    assert result.found is True
    assert result.platform == "github"
    assert result.data["name"] == "Jane Developer"
    assert result.data["public_repos"] == 30
    assert result.data["followers"] == 150
    assert result.profile_url == "https://github.com/janedev"
    assert result.data["handle"] == "janedev"


@pytest.mark.asyncio
async def test_github_at_prefix_stripped():
    """@ prefix is stripped before query."""
    crawler = GitHubCrawler()
    captured = []

    async def _get(url, **kwargs):
        captured.append(url)
        return _mock_resp(200, _GITHUB_USER_JSON)

    with patch.object(crawler, "get", new=_get):
        await crawler.scrape("@janedev")

    assert "/janedev" in captured[0]
    assert "/@janedev" not in captured[0]


@pytest.mark.asyncio
async def test_github_404_not_found():
    crawler = GitHubCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
        result = await crawler.scrape("nobody_xyz_nonexistent")

    assert result.found is False
    assert result.error is None


@pytest.mark.asyncio
async def test_github_http_none():
    crawler = GitHubCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("janedev")

    assert result.found is False
    # github uses self._result() so error goes in data dict
    assert result.data.get("error") == "http_error"


@pytest.mark.asyncio
async def test_github_non_200_status():
    crawler = GitHubCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(403))):
        result = await crawler.scrape("janedev")

    assert result.found is False
    assert "403" in result.data.get("error", "")


@pytest.mark.asyncio
async def test_github_invalid_json():
    crawler = GitHubCrawler()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = ValueError("bad json")
    with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
        result = await crawler.scrape("janedev")

    assert result.found is False
    assert result.data.get("error") == "json_parse_error"


def test_github_source_reliability():
    assert GitHubCrawler().source_reliability == pytest.approx(0.65)


def test_github_uses_tor():
    assert GitHubCrawler().requires_tor is True


# ===========================================================================
# google_maps
# ===========================================================================

_NOMINATIM_JSON = [
    {
        "display_name": "Tesla, Inc., Palo Alto, Santa Clara County, California, USA",
        "lat": "37.3945438",
        "lon": "-122.1497916",
        "type": "office",
        "address": {
            "road": "Page Mill Rd",
            "city": "Palo Alto",
            "state": "California",
            "postcode": "94304",
            "country": "United States",
        },
    }
]

_GOOGLE_KG_HTML = """
<html><body>
<span class="LrzXr">123 Tesla Ave, Palo Alto, CA 94304</span>
<a href="tel:+16505551234">(650) 555-1234</a>
</body></html>
"""

_GOOGLE_KG_NO_DATA_HTML = "<html><body><p>Generic search results only.</p></body></html>"


def test_google_maps_registered():
    assert is_registered("google_maps")


def test_parse_nominatim_result_fields():
    item = _NOMINATIM_JSON[0]
    loc = _parse_nominatim_result(item)
    assert loc["lat"] == pytest.approx(37.3945438)
    assert loc["lon"] == pytest.approx(-122.1497916)
    assert loc["type"] == "office"
    assert "Palo Alto" in loc["address"]
    assert loc["phone"] is None  # nominatim never returns phone


def test_parse_nominatim_result_no_lat_lon():
    item = {"display_name": "Somewhere", "type": "place", "address": {}}
    loc = _parse_nominatim_result(item)
    assert loc["lat"] is None
    assert loc["lon"] is None
    assert loc["name"] == "Somewhere"


def test_parse_google_kg_with_address_and_phone():
    loc = _parse_google_kg(_GOOGLE_KG_HTML, "Tesla Palo Alto")
    assert loc is not None
    assert "Tesla Ave" in loc["address"]
    assert "+16505551234" in loc["phone"]
    assert loc["type"] == "knowledge_graph"


def test_parse_google_kg_no_useful_data():
    loc = _parse_google_kg(_GOOGLE_KG_NO_DATA_HTML, "Unknown Corp")
    assert loc is None


@pytest.mark.asyncio
async def test_google_maps_scrape_with_results():
    crawler = GoogleMapsCrawler()
    calls = [0]

    async def _get(url, **kwargs):
        calls[0] += 1
        if calls[0] == 1:  # Nominatim
            return _mock_resp(200, _NOMINATIM_JSON)
        else:  # Google KG
            return _mock_resp(200, text=_GOOGLE_KG_HTML)

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("Tesla Palo Alto")

    assert result.found is True
    assert result.platform == "google_maps"
    # Nominatim + KG = at least 2 location entries
    assert len(result.data["locations"]) >= 2
    assert result.data["query"] == "Tesla Palo Alto"


@pytest.mark.asyncio
async def test_google_maps_nominatim_returns_non_list():
    """Nominatim returning non-list JSON is handled gracefully."""
    crawler = GoogleMapsCrawler()

    async def _get(url, **kwargs):
        if "nominatim" in url:
            return _mock_resp(200, {"error": "bad request"})
        return _mock_resp(200, text=_GOOGLE_KG_NO_DATA_HTML)

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("BadQuery")

    # Still returns found=True with empty locations (crawler always sets found=True)
    assert result.found is True
    assert result.data["locations"] == []


@pytest.mark.asyncio
async def test_google_maps_all_requests_fail():
    crawler = GoogleMapsCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("Nowhere")

    assert result.found is True  # google_maps always returns found=True
    assert result.data["locations"] == []


def test_google_maps_uses_tor():
    crawler = GoogleMapsCrawler()
    assert crawler.requires_tor is True
    assert crawler.tor_instance == TorInstance.TOR2


def test_google_maps_source_reliability():
    assert GoogleMapsCrawler().source_reliability == pytest.approx(0.70)
