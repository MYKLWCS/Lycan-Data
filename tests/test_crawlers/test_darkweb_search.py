"""
Tests for dark web search crawlers:
  - DarkwebAhmiaCrawler  (darkweb_ahmia) — 5 tests
  - DarkwebTorchCrawler  (darkweb_torch) — 5 tests

Total: 10 tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.darkweb_ahmia  # noqa: F401 — trigger @register
import modules.crawlers.darkweb_torch  # noqa: F401
from modules.crawlers.darkweb_ahmia import DarkwebAhmiaCrawler, _parse_ahmia_html
from modules.crawlers.darkweb_torch import DarkwebTorchCrawler, _parse_torch_html
from modules.crawlers.registry import is_registered
from shared.tor import TorInstance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(status_code: int = 200, text: str = "") -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    return mock


_AHMIA_HTML = """
<html><body>
<ul>
  <li class="result">
    <h4>Hidden Market Alpha</h4>
    <cite>http://alphamarket3axyz.onion/</cite>
    <p>The leading darknet marketplace for digital goods.</p>
  </li>
  <li class="result">
    <h4>Forum Beta</h4>
    <cite>http://forumbeta4def.onion/</cite>
    <p>Community discussions on underground topics.</p>
  </li>
</ul>
</body></html>
"""

_TORCH_HTML = """
<html><body>
<dl>
  <dt><a href="http://torchresult1abc.onion/">Torch Result One</a></dt>
  <dd>Description of the first result from Torch.</dd>
  <dt><a href="http://torchresult2def.onion/">Torch Result Two</a></dt>
  <dd>Description of the second result.</dd>
</dl>
</body></html>
"""

_EMPTY_HTML = "<html><body><p>No results found.</p></body></html>"


# ---------------------------------------------------------------------------
# DarkwebAhmiaCrawler — 5 tests
# ---------------------------------------------------------------------------


def test_darkweb_ahmia_registered():
    """Ahmia crawler must be in the registry."""
    assert is_registered("darkweb_ahmia")


def test_parse_ahmia_html_extracts_results():
    """_parse_ahmia_html pulls title, onion_url, and description from <li.result>."""
    results = _parse_ahmia_html(_AHMIA_HTML)
    assert len(results) == 2
    assert results[0]["title"] == "Hidden Market Alpha"
    assert results[0]["onion_url"] == "http://alphamarket3axyz.onion/"
    assert "digital goods" in results[0]["description"]
    assert results[1]["title"] == "Forum Beta"


def test_parse_ahmia_html_empty():
    """Empty HTML returns an empty list without raising."""
    results = _parse_ahmia_html(_EMPTY_HTML)
    assert results == []


@pytest.mark.asyncio
async def test_ahmia_scrape_returns_results():
    """Successful Ahmia scrape returns found=True with populated results list."""
    crawler = DarkwebAhmiaCrawler()
    # Two pages: first returns results, second returns empty (stops pagination)
    responses = [_mock_resp(200, _AHMIA_HTML), _mock_resp(200, _EMPTY_HTML)]

    with patch.object(crawler, "get", new=AsyncMock(side_effect=responses)):
        result = await crawler.scrape("dark marketplace")

    assert result.found is True
    assert result.platform == "darkweb_ahmia"
    assert result.data["result_count"] == 2
    assert result.data["query"] == "dark marketplace"
    assert len(result.data["results"]) == 2
    assert result.data["results"][0]["onion_url"] == "http://alphamarket3axyz.onion/"


@pytest.mark.asyncio
async def test_ahmia_http_none_returns_error():
    """Network failure on first page returns found=False with http_error."""
    crawler = DarkwebAhmiaCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("test query")

    assert result.found is False
    assert result.error == "http_error"


def test_ahmia_uses_tor2():
    """Ahmia crawler routes through TOR2 (clearnet search, enrichment tier)."""
    crawler = DarkwebAhmiaCrawler()
    assert crawler.requires_tor is True
    assert crawler.tor_instance == TorInstance.TOR2
    assert crawler.source_reliability == pytest.approx(0.40)


# ---------------------------------------------------------------------------
# DarkwebTorchCrawler — 5 tests
# ---------------------------------------------------------------------------


def test_darkweb_torch_registered():
    """Torch crawler must be in the registry."""
    assert is_registered("darkweb_torch")


def test_parse_torch_html_extracts_results():
    """_parse_torch_html extracts title, onion_url, and description from <dt>/<dd>."""
    results = _parse_torch_html(_TORCH_HTML)
    assert len(results) == 2
    assert results[0]["title"] == "Torch Result One"
    assert results[0]["onion_url"] == "http://torchresult1abc.onion/"
    assert "first result" in results[0]["description"]
    assert results[1]["title"] == "Torch Result Two"


def test_parse_torch_html_empty():
    """Empty HTML returns an empty list."""
    results = _parse_torch_html(_EMPTY_HTML)
    assert results == []


@pytest.mark.asyncio
async def test_torch_scrape_returns_results():
    """Successful Torch scrape returns found=True with populated results list."""
    crawler = DarkwebTorchCrawler()
    responses = [_mock_resp(200, _TORCH_HTML), _mock_resp(200, _EMPTY_HTML)]

    with patch.object(crawler, "get", new=AsyncMock(side_effect=responses)):
        result = await crawler.scrape("exploit")

    assert result.found is True
    assert result.platform == "darkweb_torch"
    assert result.data["result_count"] == 2
    assert result.data["query"] == "exploit"
    assert len(result.data["results"]) == 2


@pytest.mark.asyncio
async def test_torch_http_none_returns_error():
    """Network failure on first page returns found=False with http_error."""
    crawler = DarkwebTorchCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("test")

    assert result.found is False
    assert result.error == "http_error"


def test_torch_uses_tor3():
    """Torch is a .onion site — must use TOR3 and report low source_reliability."""
    crawler = DarkwebTorchCrawler()
    assert crawler.requires_tor is True
    assert crawler.tor_instance == TorInstance.TOR3
    assert crawler.source_reliability == pytest.approx(0.35)
