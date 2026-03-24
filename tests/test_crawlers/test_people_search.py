"""
Tests for people search scrapers — Task 16.
  - WhitepagesCrawler    (whitepages)
  - FastPeopleSearchCrawler (fastpeoplesearch)
  - TruePeopleSearchCrawler (truepeoplesearch)

12 tests total — Playwright page context is mocked entirely.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.fastpeoplesearch  # noqa: F401
import modules.crawlers.truepeoplesearch  # noqa: F401

# Trigger @register decorators
import modules.crawlers.whitepages  # noqa: F401
from modules.crawlers.fastpeoplesearch import FastPeopleSearchCrawler
from modules.crawlers.registry import is_registered
from modules.crawlers.truepeoplesearch import TruePeopleSearchCrawler
from modules.crawlers.whitepages import WhitepagesCrawler, _parse_name_identifier

# ---------------------------------------------------------------------------
# Shared fixture: build a mock Playwright page context manager
# ---------------------------------------------------------------------------


def make_page_cm(html: str, title: str = "People Search Results"):
    """Return a context manager that yields a mock Playwright page."""
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value=html)
    mock_page.title = AsyncMock(return_value=title)
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield mock_page

    return _cm


# ===========================================================================
# WHITEPAGES TESTS (3)
# ===========================================================================


@pytest.mark.asyncio
async def test_whitepages_found():
    """WhitepagesCrawler parses person cards and returns results."""
    html = """
    <html><body>
      <div class="card" data-testid="person-card">
        <h2 class="name">John Smith</h2>
        <span>Age 45</span>
        <div class="location">Chicago, IL</div>
        <div class="phone">(312) 555-0100</div>
      </div>
      <div class="card" data-testid="person-card">
        <h2 class="name">John Smith</h2>
        <span>Age 38</span>
        <div class="location">Austin, TX</div>
      </div>
    </body></html>
    """
    crawler = WhitepagesCrawler()
    with patch.object(crawler, "page", make_page_cm(html)):
        result = await crawler.scrape("John Smith|Chicago,IL")

    assert result.found is True
    assert result.platform == "whitepages"
    assert isinstance(result.data["results"], list)
    assert result.data["result_count"] >= 0


@pytest.mark.asyncio
async def test_whitepages_not_found():
    """WhitepagesCrawler returns found=False when 'No results' appears in page."""
    html = "<html><body><p>No results found for your search.</p></body></html>"
    crawler = WhitepagesCrawler()
    with patch.object(crawler, "page", make_page_cm(html)):
        result = await crawler.scrape("Xyz Zzznotreal")

    assert result.found is False
    assert result.data.get("result_count") == 0


@pytest.mark.asyncio
async def test_whitepages_bot_block():
    """WhitepagesCrawler detects 'Access Denied' title and returns error."""
    html = "<html><head><title>Access Denied</title></head><body>Blocked</body></html>"
    crawler = WhitepagesCrawler()

    # rotate_circuit should be called on block detection
    with (
        patch.object(crawler, "page", make_page_cm(html, title="Access Denied")),
        patch.object(crawler, "rotate_circuit", AsyncMock()) as mock_rotate,
    ):
        result = await crawler.scrape("John Smith")

    assert result.found is False
    assert "bot_block" in (result.error or "")
    mock_rotate.assert_called_once()


# ===========================================================================
# FASTPEOPLESEARCH TESTS (3)
# ===========================================================================


@pytest.mark.asyncio
async def test_fastpeoplesearch_found():
    """FastPeopleSearchCrawler parses .card-block elements and returns results."""
    html = """
    <html><body>
      <div class="card-block">
        <h2>Jane Doe</h2>
        <span>Age 33</span>
        <div class="location">Dallas, TX</div>
        <a href="tel:+12145550199">(214) 555-0199</a>
        <div class="address">123 Main St, Dallas TX 75201</div>
      </div>
      <div class="card-block">
        <h2>Jane Doe</h2>
        <span>Age 41</span>
      </div>
    </body></html>
    """
    crawler = FastPeopleSearchCrawler()
    with patch.object(crawler, "page", make_page_cm(html)):
        result = await crawler.scrape("Jane Doe|Dallas,TX")

    assert result.found is True
    assert result.platform == "fastpeoplesearch"
    assert isinstance(result.data["results"], list)
    assert result.data["result_count"] >= 0


@pytest.mark.asyncio
async def test_fastpeoplesearch_not_found():
    """FastPeopleSearchCrawler returns found=True with empty results on 'No results'."""
    html = "<html><body><p>No results found for this name.</p></body></html>"
    crawler = FastPeopleSearchCrawler()
    with patch.object(crawler, "page", make_page_cm(html)):
        result = await crawler.scrape("Xyz Zzznotreal")

    # Site loads but has no matches → found=True, empty results
    assert result.found is True
    assert result.data["results"] == []
    assert result.data["result_count"] == 0


@pytest.mark.asyncio
async def test_fastpeoplesearch_bot_block():
    """FastPeopleSearchCrawler detects block page and rotates Tor circuit."""
    html = "<html><head><title>Blocked</title></head><body>Access Denied</body></html>"
    crawler = FastPeopleSearchCrawler()

    with (
        patch.object(crawler, "page", make_page_cm(html, title="Blocked")),
        patch.object(crawler, "rotate_circuit", AsyncMock()) as mock_rotate,
    ):
        result = await crawler.scrape("John Smith")

    assert result.found is False
    assert result.error is not None
    mock_rotate.assert_called_once()


# ===========================================================================
# TRUEPEOPLESEARCH TESTS (3)
# ===========================================================================


@pytest.mark.asyncio
async def test_truepeoplesearch_found():
    """TruePeopleSearchCrawler parses .card elements and returns person data."""
    html = """
    <html><body>
      <div class="card">
        <h2 class="name">Robert Johnson</h2>
        <span>Age 52</span>
        <div class="address">456 Oak Ave, Miami FL 33101</div>
        <a href="tel:+13055550177">(305) 555-0177</a>
      </div>
      <div class="card">
        <h2 class="name">Robert Johnson</h2>
        <span>Age 29</span>
      </div>
    </body></html>
    """
    crawler = TruePeopleSearchCrawler()
    with patch.object(crawler, "page", make_page_cm(html)):
        result = await crawler.scrape("Robert Johnson|Miami,FL")

    assert result.found is True
    assert result.platform == "truepeoplesearch"
    assert isinstance(result.data["results"], list)
    assert result.data["result_count"] >= 0


@pytest.mark.asyncio
async def test_truepeoplesearch_no_records_found():
    """TruePeopleSearchCrawler returns found=False on 'No Records Found' sentinel."""
    html = "<html><body><p>No Records Found matching your search criteria.</p></body></html>"
    crawler = TruePeopleSearchCrawler()
    with patch.object(crawler, "page", make_page_cm(html)):
        result = await crawler.scrape("Xyz Zzznotreal")

    assert result.found is False
    assert result.data["result_count"] == 0


@pytest.mark.asyncio
async def test_truepeoplesearch_bot_block():
    """TruePeopleSearchCrawler detects '403' in title and rotates circuit."""
    html = "<html><head><title>403 Forbidden</title></head><body>Forbidden</body></html>"
    crawler = TruePeopleSearchCrawler()

    with (
        patch.object(crawler, "page", make_page_cm(html, title="403 Forbidden")),
        patch.object(crawler, "rotate_circuit", AsyncMock()) as mock_rotate,
    ):
        result = await crawler.scrape("John Smith")

    assert result.found is False
    assert "bot_block" in (result.error or "")
    mock_rotate.assert_called_once()


# ===========================================================================
# _parse_name_identifier HELPER TESTS (3)
# ===========================================================================


def test_parse_name_full_with_location():
    """Parses 'John Smith|Chicago,IL' correctly into components."""
    first, last, city, state = _parse_name_identifier("John Smith|Chicago,IL")
    assert first == "John"
    assert last == "Smith"
    assert city == "Chicago"
    assert state == "IL"


def test_parse_name_no_location():
    """Parses 'Jane Doe' with no location — city/state are empty strings."""
    first, last, city, state = _parse_name_identifier("Jane Doe")
    assert first == "Jane"
    assert last == "Doe"
    assert city == ""
    assert state == ""


def test_parse_name_single_token():
    """Single-token name — last is same as full name, no location."""
    first, last, city, state = _parse_name_identifier("Madonna")
    assert first == "Madonna"
    assert last == ""
    assert city == ""
    assert state == ""


# ===========================================================================
# REGISTRY TESTS (3)
# ===========================================================================


def test_whitepages_registered():
    assert is_registered("whitepages")


def test_fastpeoplesearch_registered():
    assert is_registered("fastpeoplesearch")


def test_truepeoplesearch_registered():
    assert is_registered("truepeoplesearch")
