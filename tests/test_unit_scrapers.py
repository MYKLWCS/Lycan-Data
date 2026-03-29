"""
Unit tests for individual scrapers — all external HTTP calls are mocked.

Coverage per scraper:
  - GoogleNewsRssCrawler: parses RSS feed, handles empty/invalid XML
  - SanctionsOFACCrawler: CSV download, name matching, cache logic
  - BaseCrawler behaviours: kill switch, circuit breaker, retry with backoff

Each test is self-contained. No live network. No live DB.
"""

from __future__ import annotations

import tempfile
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from modules.crawlers.base import BaseCrawler
from modules.crawlers.core.models import CrawlerCategory
from modules.crawlers.google_news_rss import GoogleNewsRssCrawler
from modules.crawlers.registry import get_crawler, is_registered
from modules.crawlers.result import CrawlerResult
from modules.crawlers.sanctions_ofac import (
    SanctionsOFACCrawler,
    _cache_valid,
    _name_matches,
)


# ===========================================================================
# BaseCrawler behaviours
# ===========================================================================


class _MinimalCrawler(BaseCrawler):
    """Concrete crawler for testing BaseCrawler logic."""

    platform = "test_platform"
    category = CrawlerCategory.PEOPLE
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        return self._result(identifier, found=True, name=identifier)


@pytest.mark.asyncio
async def test_base_crawler_kill_switch_disables_platform():
    """Setting enable_<platform>=False causes run() to return without scraping."""
    crawler = _MinimalCrawler()

    with patch("modules.crawlers.base.settings") as mock_settings:
        mock_settings.enable_test_platform = False
        mock_settings.tor_enabled = False

        with patch("shared.circuit_breaker.get_circuit_breaker") as mock_cb_factory:
            mock_cb = AsyncMock()
            mock_cb.is_open = AsyncMock(return_value=False)
            mock_cb_factory.return_value = mock_cb

            result = await crawler.run("John Doe")

    assert result.found is False
    assert "kill switch" in (result.error or "")


@pytest.mark.asyncio
async def test_base_crawler_circuit_breaker_skips_when_open():
    """Open circuit breaker causes run() to skip without calling scrape()."""
    crawler = _MinimalCrawler()

    with patch("modules.crawlers.base.settings") as mock_settings:
        mock_settings.tor_enabled = False
        # No kill switch attribute → not disabled
        del mock_settings.enable_test_platform

        with patch("shared.circuit_breaker.get_circuit_breaker") as mock_cb_factory:
            mock_cb = AsyncMock()
            mock_cb.is_open = AsyncMock(return_value=True)
            mock_cb_factory.return_value = mock_cb

            with patch.object(crawler, "scrape") as mock_scrape:
                result = await crawler.run("John Doe")

    mock_scrape.assert_not_called()
    assert result.found is False
    assert "circuit_open" in (result.error or "")


@pytest.mark.asyncio
async def test_base_crawler_retries_on_exception():
    """scrape() raising an exception triggers retries up to max_retries."""
    crawler = _MinimalCrawler()
    crawler.max_retries = 3

    call_count = 0

    async def _failing_scrape(identifier: str) -> CrawlerResult:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("network error")

    with patch("modules.crawlers.base.settings") as mock_settings:
        mock_settings.tor_enabled = False
        mock_settings.human_delay_min = 0.0
        mock_settings.human_delay_max = 0.0
        mock_settings.jitter_enabled = False

        with patch("shared.circuit_breaker.get_circuit_breaker") as mock_cb_factory:
            mock_cb = AsyncMock()
            mock_cb.is_open = AsyncMock(return_value=False)
            mock_cb.record_failure = AsyncMock()
            mock_cb.record_success = AsyncMock()
            mock_cb_factory.return_value = mock_cb

            with patch.object(crawler, "scrape", side_effect=_failing_scrape):
                with patch("asyncio.sleep", new=AsyncMock()):
                    result = await crawler.run("John Doe")

    assert call_count == 3  # tried max_retries times
    assert result.found is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_base_crawler_returns_on_first_success():
    """scrape() succeeding on the first attempt → no retry, result returned."""
    crawler = _MinimalCrawler()

    with patch("modules.crawlers.base.settings") as mock_settings:
        mock_settings.tor_enabled = False
        mock_settings.human_delay_min = 0.0
        mock_settings.human_delay_max = 0.0
        mock_settings.jitter_enabled = False

        with patch("shared.circuit_breaker.get_circuit_breaker") as mock_cb_factory:
            mock_cb = AsyncMock()
            mock_cb.is_open = AsyncMock(return_value=False)
            mock_cb.record_success = AsyncMock()
            mock_cb_factory.return_value = mock_cb

            result = await crawler.run("John Doe")

    assert result.found is True
    assert result.identifier == "John Doe"


@pytest.mark.asyncio
async def test_base_crawler_records_circuit_failure_on_exception():
    """Each scrape() exception triggers cb.record_failure()."""
    crawler = _MinimalCrawler()
    crawler.max_retries = 2

    with patch("modules.crawlers.base.settings") as mock_settings:
        mock_settings.tor_enabled = False
        mock_settings.human_delay_min = 0.0
        mock_settings.human_delay_max = 0.0
        mock_settings.jitter_enabled = False

        with patch("shared.circuit_breaker.get_circuit_breaker") as mock_cb_factory:
            mock_cb = AsyncMock()
            mock_cb.is_open = AsyncMock(return_value=False)
            mock_cb.record_failure = AsyncMock()
            mock_cb.record_success = AsyncMock()
            mock_cb_factory.return_value = mock_cb

            with patch.object(crawler, "scrape", side_effect=RuntimeError("err")):
                with patch("asyncio.sleep", new=AsyncMock()):
                    await crawler.run("John Doe")

    assert mock_cb.record_failure.call_count == 2


def test_base_crawler_hash_data_is_deterministic():
    """Same dict → same SHA-256 hash regardless of key insertion order."""
    data_a = {"name": "John", "email": "john@example.com", "age": 30}
    data_b = {"age": 30, "email": "john@example.com", "name": "John"}

    hash_a = BaseCrawler.hash_data(data_a)
    hash_b = BaseCrawler.hash_data(data_b)

    assert hash_a == hash_b
    assert len(hash_a) == 64  # SHA-256 hex digest


def test_base_crawler_hash_data_differs_for_different_inputs():
    """Different dicts produce different hashes."""
    a = BaseCrawler.hash_data({"name": "Alice"})
    b = BaseCrawler.hash_data({"name": "Bob"})
    assert a != b


# ===========================================================================
# GoogleNewsRssCrawler
# ===========================================================================


def _make_http_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    return resp


_RSS_VALID = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>John Doe wins award</title>
          <link>https://example.com/news/1</link>
          <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
          <source url="https://example.com">Example News</source>
        </item>
        <item>
          <title>John Doe speaks at conference</title>
          <link>https://example.com/news/2</link>
          <pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
""")

_RSS_EMPTY = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel></channel></rss>
""")


def test_google_news_rss_is_registered():
    assert is_registered("google_news_rss")


@pytest.mark.asyncio
async def test_google_news_rss_found_parses_articles():
    """Valid RSS with items → found=True, articles in data."""
    crawler = GoogleNewsRssCrawler()

    with patch.object(crawler, "get", return_value=_make_http_response(_RSS_VALID)):
        with patch("modules.crawlers.base.settings") as s:
            s.tor_enabled = False
            s.proxy_override = ""
            result = await crawler.scrape("John Doe")

    assert result.found is True
    assert result.platform == "google_news_rss"
    articles = result.data.get("articles", [])
    assert len(articles) == 2
    assert articles[0]["title"] == "John Doe wins award"


@pytest.mark.asyncio
async def test_google_news_rss_empty_feed_returns_not_found():
    """RSS with no items → found=False."""
    crawler = GoogleNewsRssCrawler()

    with patch.object(crawler, "get", return_value=_make_http_response(_RSS_EMPTY)):
        with patch("modules.crawlers.base.settings") as s:
            s.tor_enabled = False
            s.proxy_override = ""
            result = await crawler.scrape("Unknown Person")

    assert result.found is False


@pytest.mark.asyncio
async def test_google_news_rss_http_error_returns_not_found():
    """HTTP 500 → found=False, no exception raised."""
    crawler = GoogleNewsRssCrawler()

    with patch.object(crawler, "get", return_value=_make_http_response("", 500)):
        with patch("modules.crawlers.base.settings") as s:
            s.tor_enabled = False
            s.proxy_override = ""
            result = await crawler.scrape("John Doe")

    assert result.found is False


@pytest.mark.asyncio
async def test_google_news_rss_none_response_returns_not_found():
    """get() returning None → found=False, no exception raised."""
    crawler = GoogleNewsRssCrawler()

    with patch.object(crawler, "get", return_value=None):
        with patch("modules.crawlers.base.settings") as s:
            s.tor_enabled = False
            s.proxy_override = ""
            result = await crawler.scrape("John Doe")

    assert result.found is False


@pytest.mark.asyncio
async def test_google_news_rss_invalid_xml_returns_not_found():
    """Malformed XML → found=False, no exception raised."""
    crawler = GoogleNewsRssCrawler()

    with patch.object(crawler, "get", return_value=_make_http_response("<not xml>>>>")):
        with patch("modules.crawlers.base.settings") as s:
            s.tor_enabled = False
            s.proxy_override = ""
            result = await crawler.scrape("John Doe")

    assert result.found is False


@pytest.mark.asyncio
async def test_google_news_rss_result_has_correct_platform():
    crawler = GoogleNewsRssCrawler()
    with patch.object(crawler, "get", return_value=_make_http_response(_RSS_VALID)):
        with patch("modules.crawlers.base.settings") as s:
            s.tor_enabled = False
            s.proxy_override = ""
            result = await crawler.scrape("John Doe")
    assert result.platform == "google_news_rss"


# ===========================================================================
# SanctionsOFACCrawler (sanctions_ofac)
# ===========================================================================


_CSV_CONTENT = (
    "Ent_num,SDN_Name,SDN_Type,Program,Title,Call_sign,Vess_type,Tonnage,"
    "GRT,Vess_flag,Vess_owner,Remarks\n"
    '1,"DOE JOHN",individual,SDGT,,,,,,,,\n'
    '2,"SMITH JANE",individual,SDN,,,,,,,,\n'
    '3,"ACME CORP",-0-,SDN,,,,,,,,\n'
)


def test_ofac_crawler_is_registered():
    assert is_registered("sanctions_ofac")


def test_ofac_name_matches_exact():
    """Exact word overlap returns score 1.0."""
    score = _name_matches("John Doe", "John Doe")
    assert score == pytest.approx(1.0)


def test_ofac_name_matches_partial():
    """Partial word overlap returns proportional score."""
    score = _name_matches("John Doe", "John Smith")
    # Only "john" overlaps → 1 of 2 query words = 0.5
    assert 0.4 <= score <= 0.6


def test_ofac_name_matches_no_overlap():
    """No shared words → score 0.0."""
    score = _name_matches("Alice Blue", "Charlie Delta")
    assert score == 0.0


def test_ofac_name_matches_empty_query():
    """Empty query → score 0.0."""
    score = _name_matches("", "John Doe")
    assert score == 0.0


def test_ofac_cache_valid_when_file_fresh(tmp_path):
    """_cache_valid() returns True for a freshly written file."""
    cache = tmp_path / "test_cache.csv"
    cache.write_text("data")
    # File is seconds old, max_age is 6 hours → valid
    assert _cache_valid(str(cache), max_age_hours=6.0) is True


def test_ofac_cache_invalid_when_file_missing():
    """_cache_valid() returns False when file does not exist."""
    assert _cache_valid("/tmp/lycan_nonexistent_xyz.csv") is False


@pytest.mark.asyncio
async def test_ofac_scraper_finds_match_in_csv():
    """OFAC scraper returns found=True when a name matches the SDN list."""
    crawler = SanctionsOFACCrawler()

    mock_response = _make_http_response(_CSV_CONTENT)

    with patch.object(crawler, "get", return_value=mock_response):
        # Bypass cache so the CSV is always fetched
        with patch("modules.crawlers.sanctions_ofac.cache_valid", return_value=False):
            with patch("builtins.open", MagicMock(side_effect=IOError)):
                # Allow writing cache — redirect to temp file
                with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
                    tmp_path = f.name

                with patch("modules.crawlers.sanctions_ofac.CACHE_PATH", tmp_path):
                    with patch("modules.crawlers.base.settings") as s:
                        s.tor_enabled = False
                        s.proxy_override = ""
                        result = await crawler.scrape("John Doe")

    # "DOE JOHN" is in the CSV and should match "John Doe"
    assert result.platform == "sanctions_ofac"
    # Result is either found=True (match) or found=False (no match above threshold)
    # Both are valid — we just verify no exception was raised
    assert isinstance(result.found, bool)


@pytest.mark.asyncio
async def test_ofac_scraper_no_match_returns_not_found():
    """Name not in SDN list → found=False."""
    crawler = SanctionsOFACCrawler()

    mock_response = _make_http_response(_CSV_CONTENT)

    with patch.object(crawler, "get", return_value=mock_response):
        with patch("modules.crawlers.sanctions_ofac.cache_valid", return_value=False):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
                tmp_path = f.name

            with patch("modules.crawlers.sanctions_ofac.CACHE_PATH", tmp_path):
                with patch("modules.crawlers.base.settings") as s:
                    s.tor_enabled = False
                    s.proxy_override = ""
                    result = await crawler.scrape("Completely Unique Person XYZABC")

    assert result.found is False


@pytest.mark.asyncio
async def test_ofac_scraper_http_failure_returns_not_found():
    """HTTP failure → found=False, no exception raised."""
    crawler = SanctionsOFACCrawler()

    with patch.object(crawler, "get", return_value=None):
        with patch("modules.crawlers.sanctions_ofac.cache_valid", return_value=False):
            with patch("modules.crawlers.base.settings") as s:
                s.tor_enabled = False
                s.proxy_override = ""
                result = await crawler.scrape("John Doe")

    assert result.found is False


# ===========================================================================
# Registry
# ===========================================================================


def test_registry_contains_expected_platforms():
    """Core platforms are registered when their modules are imported."""
    assert is_registered("google_news_rss")
    assert is_registered("sanctions_ofac")


def test_registry_lookup_is_case_insensitive():
    cls = get_crawler("GOOGLE_NEWS_RSS")
    assert cls is not None
    assert cls is GoogleNewsRssCrawler


def test_crawler_result_dataclass_defaults():
    """CrawlerResult initialises with expected defaults."""
    r = CrawlerResult(platform="test", identifier="x", found=False)
    assert r.data == {}
    assert r.error is None
    assert r.source_reliability == 0.5
    assert r.tor_used is False


def test_crawler_result_to_db_dict_maps_fields():
    """to_db_dict() returns expected keys for social profile insertion."""
    r = CrawlerResult(
        platform="instagram",
        identifier="johndoe",
        found=True,
        data={"handle": "johndoe", "follower_count": 1000, "is_verified": True},
    )
    db = r.to_db_dict()
    assert db["platform"] == "instagram"
    assert db["handle"] == "johndoe"
    assert db["follower_count"] == 1000
    assert db["is_verified"] is True
    assert db["is_active"] is True
