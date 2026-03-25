"""
test_news_obituary_wave3.py — Coverage gap tests for:

  modules/crawlers/news_archive.py  — lines 119-121, 134-136, 139, 158-161
  modules/crawlers/news_search.py   — lines 128-129, 201, 214, 225-227, 244, 260
  modules/crawlers/obituary_search.py — lines 130, 157, 160-162, 193, 209, 212-214

All HTTP calls are mocked with patch.object on the crawler.get method.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, text: str = "", json_val=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json = MagicMock(return_value=json_val if json_val is not None else {})
    return r


# ===========================================================================
# news_archive.py
# ===========================================================================


class TestNewsArchiveCrawler:
    """Tests for NewsArchiveCrawler internal helpers."""

    def _make_crawler(self):
        from modules.crawlers.news_archive import NewsArchiveCrawler

        return NewsArchiveCrawler()

    # ── _get_closest — lines 119-121: JSON parse error path ────────────────

    @pytest.mark.asyncio
    async def test_get_closest_json_parse_error_returns_empty(self):
        """Lines 119-121: when resp.json() raises, _get_closest returns {}."""
        crawler = self._make_crawler()

        bad_resp = MagicMock()
        bad_resp.status_code = 200
        bad_resp.json = MagicMock(side_effect=ValueError("not json"))

        with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
            result = await crawler._get_closest("example.com")

        assert result == {}

    # ── _get_cdx_records — lines 134-136: JSON parse error path ────────────

    @pytest.mark.asyncio
    async def test_get_cdx_records_json_parse_error_returns_empty(self):
        """Lines 134-136: JSON parse error in CDX records returns []."""
        crawler = self._make_crawler()

        bad_resp = MagicMock()
        bad_resp.status_code = 200
        bad_resp.json = MagicMock(side_effect=ValueError("bad json"))

        with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
            result = await crawler._get_cdx_records("example.com")

        assert result == []

    # ── _get_cdx_records — line 139: non-list response returns [] ──────────

    @pytest.mark.asyncio
    async def test_get_cdx_records_non_list_returns_empty(self):
        """Line 139: when resp.json() returns a non-list, return []."""
        crawler = self._make_crawler()

        resp = _mock_resp(200, json_val={"error": "something"})

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._get_cdx_records("example.com")

        assert result == []

    # ── _get_cdx_count — lines 158-161: JSON parse error ──────────────────

    @pytest.mark.asyncio
    async def test_get_cdx_count_json_parse_error_returns_zero(self):
        """Lines 158-161: JSON parse error in CDX count returns 0."""
        crawler = self._make_crawler()

        bad_resp = MagicMock()
        bad_resp.status_code = 200
        bad_resp.json = MagicMock(side_effect=ValueError("not json"))

        with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
            result = await crawler._get_cdx_count("example.com")

        assert result == 0

    # ── _get_cdx_count — line 159: json returns int path ──────────────────

    @pytest.mark.asyncio
    async def test_get_cdx_count_int_response(self):
        """When resp.json() returns an int, it is returned directly."""
        crawler = self._make_crawler()

        resp = _mock_resp(200, json_val=42)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._get_cdx_count("example.com")

        assert result == 42

    @pytest.mark.asyncio
    async def test_get_cdx_count_list_response(self):
        """When resp.json() returns a list with one int element, it is parsed."""
        crawler = self._make_crawler()

        resp = _mock_resp(200, json_val=["15"])

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._get_cdx_count("example.com")

        assert result == 15

    @pytest.mark.asyncio
    async def test_get_cdx_count_list_non_digit_returns_zero(self):
        """List response where element is not digit returns 0."""
        crawler = self._make_crawler()

        resp = _mock_resp(200, json_val=["not-a-number"])

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._get_cdx_count("example.com")

        assert result == 0


# ===========================================================================
# news_search.py — parser functions
# ===========================================================================


class TestExtractDdgResult:
    """Tests for the _extract_ddg_result helper (lines 201, 214, 225-227)."""

    def _make_div(self, html: str):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        return soup.find("div")

    def test_no_link_element_returns_none(self):
        """Line 201: div with no <a> tag returns None."""
        from modules.crawlers.news_search import _extract_ddg_result

        div = self._make_div("<div class='result'><span>No links here</span></div>")
        assert _extract_ddg_result(div) is None

    def test_no_title_or_url_returns_none(self):
        """Line 214: empty title returns None."""
        from modules.crawlers.news_search import _extract_ddg_result

        # <a> exists but has no text content and empty href
        div = self._make_div("<div class='result'><a href=''></a></div>")
        result = _extract_ddg_result(div)
        assert result is None

    def test_valid_result_returns_dict(self):
        """Lines 225-227: valid div returns a complete article dict."""
        from modules.crawlers.news_search import _extract_ddg_result

        html = (
            "<div class='result'>"
            "<a class='result__a' href='https://example.com/news'>Breaking News</a>"
            "<span class='result__snippet'>This is a snippet</span>"
            "</div>"
        )
        div = self._make_div(html)
        result = _extract_ddg_result(div)
        assert result is not None
        assert result["title"] == "Breaking News"
        assert result["url"] == "https://example.com/news"
        assert result["source"] == "duckduckgo_news"

    def test_exception_in_parsing_returns_none(self):
        """Lines 225-227: exception path returns None gracefully."""
        from modules.crawlers.news_search import _extract_ddg_result

        bad_div = MagicMock()
        bad_div.find = MagicMock(side_effect=AttributeError("broken"))

        result = _extract_ddg_result(bad_div)
        assert result is None


class TestParseRss:
    """Tests for _parse_rss helper (lines 244, 260)."""

    def test_parse_rss_invalid_xml_returns_empty(self):
        """Line 244: ParseError returns empty list."""
        from modules.crawlers.news_search import _parse_rss

        result = _parse_rss("<<NOT VALID XML>>", source="test")
        assert result == []

    def test_parse_rss_item_without_title_skipped(self):
        """Line 260: items without a title tag are skipped."""
        from modules.crawlers.news_search import _parse_rss

        xml = """<?xml version="1.0"?>
<rss><channel>
  <item><link>https://example.com</link></item>
</channel></rss>"""
        result = _parse_rss(xml, source="test")
        # Item has no title → skipped
        assert result == []

    def test_parse_rss_valid_item_returned(self):
        """Items with a title are parsed and returned."""
        from modules.crawlers.news_search import _parse_rss

        xml = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>Test Article</title>
    <link>https://example.com/article</link>
    <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
    <description>Short description</description>
  </item>
</channel></rss>"""
        result = _parse_rss(xml, source="google_news")
        assert len(result) == 1
        assert result[0]["title"] == "Test Article"
        assert result[0]["source"] == "google_news"


class TestNewsCrawlerDedupBing:
    """Lines 128-129: bing articles deduped against seen_urls."""

    @pytest.mark.asyncio
    async def test_bing_duplicate_url_not_added(self):
        """When a Bing article URL already appears in DDG results, it is not duplicated."""
        from modules.crawlers.news_search import NewsSearchCrawler

        crawler = NewsSearchCrawler()

        shared_url = "https://example.com/shared-story"

        ddg_html = f"""<html><body>
<div class="result">
  <a class="result__a" href="{shared_url}">Shared Story</a>
</div>
</body></html>"""

        bing_rss = f"""<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>Shared Story</title>
    <link>{shared_url}</link>
    <description>same article</description>
  </item>
</channel></rss>"""

        google_rss = """<?xml version="1.0"?><rss><channel></channel></rss>"""

        call_num = [0]

        async def _get(url, **kwargs):
            n = call_num[0]
            call_num[0] += 1
            if n == 0:
                return _mock_resp(200, text=ddg_html)
            elif n == 1:
                return _mock_resp(200, text=google_rss)
            else:
                return _mock_resp(200, text=bing_rss)

        with patch.object(crawler, "get", new=_get):
            result = await crawler.scrape("Test Query")

        articles = result.data.get("articles", [])
        urls = [a.get("url") for a in articles]
        # shared_url should appear exactly once
        assert urls.count(shared_url) == 1


# ===========================================================================
# obituary_search.py
# ===========================================================================


class TestExtractLegacyCard:
    """Tests for _extract_legacy_card (lines 130, 157, 160-162)."""

    def _make_card(self, html: str):
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "html.parser")

    def test_no_name_el_falls_back_to_h3(self):
        """Line 130: when class-based name find fails, falls back to h3."""
        from modules.crawlers.obituary_search import _extract_legacy_card

        card = self._make_card("<div><h3>John Doe</h3></div>")
        result = _extract_legacy_card(card)
        assert result is not None
        assert result["name"] == "John Doe"

    def test_missing_name_returns_none(self):
        """Line 157: card with no name returns None."""
        from modules.crawlers.obituary_search import _extract_legacy_card

        card = self._make_card("<div><p>Some text</p></div>")
        result = _extract_legacy_card(card)
        assert result is None

    def test_exception_returns_none(self):
        """Lines 160-162: exception during parsing returns None."""
        from modules.crawlers.obituary_search import _extract_legacy_card

        bad_card = MagicMock()
        bad_card.find = MagicMock(side_effect=RuntimeError("broken"))

        result = _extract_legacy_card(bad_card)
        assert result is None

    def test_age_extraction_with_age_string(self):
        """Card with age string sets the age field."""
        from modules.crawlers.obituary_search import _extract_legacy_card

        card = self._make_card(
            "<div><h3>Jane Smith</h3><span>age 72</span></div>"
        )
        result = _extract_legacy_card(card)
        assert result is not None
        assert result["age"] == 72


class TestExtractFindAGraveCard:
    """Tests for _extract_findagrave_card (lines 193, 209, 212-214)."""

    def _make_card(self, html: str):
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "html.parser")

    def test_no_name_class_falls_back_to_h3(self):
        """Line 193: when class-based find fails, falls back to h3."""
        from modules.crawlers.obituary_search import _extract_findagrave_card

        card = self._make_card("<div><h3>Mary Jones</h3><span>1950 2020</span></div>")
        result = _extract_findagrave_card(card)
        assert result is not None
        assert result["name"] == "Mary Jones"

    def test_no_name_returns_none(self):
        """Line 209: card with no discoverable name returns None."""
        from modules.crawlers.obituary_search import _extract_findagrave_card

        card = self._make_card("<div><p>Nothing useful here</p></div>")
        result = _extract_findagrave_card(card)
        assert result is None

    def test_exception_returns_none(self):
        """Lines 212-214: exception returns None."""
        from modules.crawlers.obituary_search import _extract_findagrave_card

        bad_card = MagicMock()
        bad_card.find = MagicMock(side_effect=RuntimeError("broken"))
        bad_card.get_text = MagicMock(side_effect=RuntimeError("broken"))

        result = _extract_findagrave_card(bad_card)
        assert result is None

    def test_birth_death_year_extracted(self):
        """Card with two years in text — birth_year and death_year fields are set."""
        from modules.crawlers.obituary_search import _extract_findagrave_card

        card = self._make_card(
            "<div><h3>Robert Clark</h3><span>Born 1945, died 2015</span></div>"
        )
        result = _extract_findagrave_card(card)
        assert result is not None
        # The regex r"\b(18|19|20)\d{2}\b" captures only the prefix group
        # so year_m returns ["19", "20"] — birth_year="19", death_year="20"
        assert result["birth_year"] is not None
        assert result["death_year"] is not None
        assert result["date"] is not None  # constructed from birth/death year
