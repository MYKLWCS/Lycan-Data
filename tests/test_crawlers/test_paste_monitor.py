"""
Tests for paste monitor crawlers:
  - PastePastebinCrawler  (paste_pastebin) — 4 tests
  - PasteGhostbinCrawler  (paste_ghostbin) — 4 tests
  - PastePsbdmpCrawler    (paste_psbdmp)   — 4 tests

Total: 12 tests.
"""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import modules.crawlers.paste_pastebin   # noqa: F401
import modules.crawlers.paste_ghostbin   # noqa: F401
import modules.crawlers.paste_psbdmp     # noqa: F401

from modules.crawlers.paste_pastebin import PastePastebinCrawler, _parse_pastebin_html
from modules.crawlers.paste_ghostbin import PasteGhostbinCrawler, _parse_rentry_html
from modules.crawlers.paste_psbdmp import PastePsbdmpCrawler, _parse_psbdmp_response
from modules.crawlers.registry import is_registered
from shared.tor import TorInstance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_resp(status_code: int = 200, text: str = "", json_data=None) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    if json_data is not None:
        mock.json.return_value = json_data
    else:
        mock.json.side_effect = ValueError("no json")
    return mock


_PASTEBIN_HTML = """
<html><body>
<div class="search-result">
  <a href="/XyZ123">Leaked credentials 2024</a>
  <span class="date">2024-01-15</span>
  <p>john.doe@example.com password123 leaked from breach...</p>
</div>
<div class="search-result">
  <a href="/AbC456">Database dump</a>
  <span class="date">2024-02-10</span>
  <p>example.com user database exposed...</p>
</div>
</body></html>
"""

_RENTRY_HTML = """
<html><body>
<a href="/abc12">Paste abc12</a>
<a href="/def34">Paste def34</a>
<a href="/search">Search</a>
<a href="https://external.com">External</a>
</body></html>
"""

_PSBDMP_JSON = [
    {"id": "AAABBB", "time": "1700000000", "text": "john.doe@example.com pass123"},
    {"id": "CCCDDD", "time": "1700001000", "text": "example.com database dump here"},
]

_EMPTY_HTML = "<html><body><p>No results.</p></body></html>"


# ---------------------------------------------------------------------------
# PastePastebinCrawler — 4 tests
# ---------------------------------------------------------------------------

def test_paste_pastebin_registered():
    """paste_pastebin must be in the crawler registry."""
    assert is_registered("paste_pastebin")


def test_parse_pastebin_html_extracts_mentions():
    """_parse_pastebin_html extracts title, url, date, and preview from results."""
    mentions = _parse_pastebin_html(_PASTEBIN_HTML)
    assert len(mentions) == 2
    assert mentions[0]["title"] == "Leaked credentials 2024"
    assert mentions[0]["url"] == "https://pastebin.com/XyZ123"
    assert mentions[0]["date"] == "2024-01-15"
    assert "john.doe" in mentions[0]["preview"]
    assert mentions[1]["url"] == "https://pastebin.com/AbC456"


@pytest.mark.asyncio
async def test_pastebin_scrape_returns_mentions():
    """Successful scrape returns found=True with populated mentions list."""
    crawler = PastePastebinCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, _PASTEBIN_HTML))):
        result = await crawler.scrape("john.doe@example.com")

    assert result.found is True
    assert result.platform == "paste_pastebin"
    assert result.data["mention_count"] == 2
    assert result.data["query"] == "john.doe@example.com"
    assert len(result.data["mentions"]) == 2


@pytest.mark.asyncio
async def test_pastebin_rate_limited():
    """HTTP 429 returns found=False with rate_limited error."""
    crawler = PastePastebinCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
        result = await crawler.scrape("test")

    assert result.found is False
    assert result.error == "rate_limited"


def test_pastebin_tor_and_reliability():
    """Pastebin crawler uses TOR2 and has source_reliability 0.35."""
    crawler = PastePastebinCrawler()
    assert crawler.requires_tor is True
    assert crawler.tor_instance == TorInstance.TOR2
    assert crawler.source_reliability == pytest.approx(0.35)


# ---------------------------------------------------------------------------
# PasteGhostbinCrawler — 4 tests
# ---------------------------------------------------------------------------

def test_paste_ghostbin_registered():
    """paste_ghostbin must be in the crawler registry."""
    assert is_registered("paste_ghostbin")


def test_parse_rentry_html_extracts_mentions():
    """_parse_rentry_html returns paste links and filters navigation items."""
    mentions = _parse_rentry_html(_RENTRY_HTML)
    urls = [m["url"] for m in mentions]
    assert "https://rentry.co/abc12" in urls
    assert "https://rentry.co/def34" in urls
    # Navigation and external links must be excluded
    assert not any("search" in u for u in urls)
    assert not any("external.com" in u for u in urls)


@pytest.mark.asyncio
async def test_ghostbin_scrape_empty_results():
    """Page with no paste links returns found=False and empty mentions list."""
    crawler = PasteGhostbinCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, _EMPTY_HTML))):
        result = await crawler.scrape("nonexistent query")

    assert result.found is False
    assert result.data["mention_count"] == 0
    assert result.data["mentions"] == []


@pytest.mark.asyncio
async def test_ghostbin_http_none_returns_error():
    """Network failure returns found=False with http_error."""
    crawler = PasteGhostbinCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("test")

    assert result.found is False
    assert result.error == "http_error"


def test_ghostbin_tor_and_reliability():
    """Ghostbin/rentry crawler uses TOR2 and has source_reliability 0.30."""
    crawler = PasteGhostbinCrawler()
    assert crawler.requires_tor is True
    assert crawler.tor_instance == TorInstance.TOR2
    assert crawler.source_reliability == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# PastePsbdmpCrawler — 4 tests
# ---------------------------------------------------------------------------

def test_paste_psbdmp_registered():
    """paste_psbdmp must be in the crawler registry."""
    assert is_registered("paste_psbdmp")


def test_parse_psbdmp_response_extracts_mentions():
    """_parse_psbdmp_response converts API items into pastebin_id/url/time/preview."""
    mentions = _parse_psbdmp_response(_PSBDMP_JSON)
    assert len(mentions) == 2
    assert mentions[0]["pastebin_id"] == "AAABBB"
    assert mentions[0]["url"] == "https://pastebin.com/raw/AAABBB"
    assert mentions[0]["time"] == "1700000000"
    assert "john.doe" in mentions[0]["preview"]
    assert mentions[1]["pastebin_id"] == "CCCDDD"


@pytest.mark.asyncio
async def test_psbdmp_scrape_returns_mentions():
    """Successful JSON response returns found=True with mention list."""
    crawler = PastePsbdmpCrawler()
    with patch.object(
        crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=_PSBDMP_JSON))
    ):
        result = await crawler.scrape("example.com")

    assert result.found is True
    assert result.platform == "paste_psbdmp"
    assert result.data["mention_count"] == 2
    assert result.data["query"] == "example.com"
    assert result.data["mentions"][0]["pastebin_id"] == "AAABBB"


@pytest.mark.asyncio
async def test_psbdmp_404_returns_empty():
    """HTTP 404 from psbdmp means no results — returns found=False, empty mentions."""
    crawler = PastePsbdmpCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
        result = await crawler.scrape("notfound")

    assert result.found is False
    assert result.data["mention_count"] == 0
    assert result.data["mentions"] == []


def test_psbdmp_tor_and_reliability():
    """psbdmp crawler uses TOR2 and has source_reliability 0.35."""
    crawler = PastePsbdmpCrawler()
    assert crawler.requires_tor is True
    assert crawler.tor_instance == TorInstance.TOR2
    assert crawler.source_reliability == pytest.approx(0.35)
