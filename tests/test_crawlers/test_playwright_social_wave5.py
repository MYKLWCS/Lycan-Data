"""
test_playwright_social_wave5.py — Coverage gap tests for Playwright/HTTP social crawlers.

Crawlers covered:
  - LinkedInCrawler     (modules/crawlers/linkedin.py)
  - FindAGraveCrawler   (modules/crawlers/people_findagrave.py)
  - PeopleThatsThemCrawler (modules/crawlers/people_thatsthem.py)

All network I/O is mocked. No real HTTP or Playwright calls are made.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, text: str = "", json_data=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


def _make_page_cm(
    content: str = "",
    url: str = "https://www.linkedin.com/in/johndoe/",
    title: str = "John Doe | LinkedIn",
    query_selector_return=None,
    query_selector_all_return=None,
):
    """Build an async context manager that yields a mock Playwright page."""
    inner_page = AsyncMock()
    inner_page.content = AsyncMock(return_value=content)
    inner_page.url = url
    inner_page.title = AsyncMock(return_value=title)
    inner_page.query_selector = AsyncMock(return_value=query_selector_return)
    inner_page.query_selector_all = AsyncMock(return_value=query_selector_all_return or [])

    @asynccontextmanager
    async def _cm(*args, **kwargs):
        yield inner_page

    return _cm, inner_page


# ===========================================================================
# LinkedIn (modules/crawlers/linkedin.py)
# ===========================================================================


class TestLinkedInCrawlerScrape:
    """Tests for LinkedInCrawler.scrape() — lines 29-57."""

    def _make_crawler(self):
        from modules.crawlers.linkedin import LinkedInCrawler

        return LinkedInCrawler()

    # --- test 1: normal username handle → success path (lines 29-57) ---

    @pytest.mark.asyncio
    async def test_scrape_username_success(self):
        """scrape() with a plain username builds URL, extracts data, returns found=True."""
        crawler = self._make_crawler()

        content = "<html><body>John Doe profile</body></html>"
        page_cm, inner_page = _make_page_cm(
            content=content,
            url="https://www.linkedin.com/in/johndoe/",
            title="John Doe | LinkedIn",
        )

        with patch.object(crawler, "_extract", new=AsyncMock(return_value={"display_name": "John Doe", "handle": "johndoe"})):
            with patch.object(crawler, "page", page_cm):
                result = await crawler.scrape("johndoe")

        assert result.found is True
        assert result.platform == "linkedin"
        assert result.data.get("display_name") == "John Doe"
        assert result.profile_url == "https://www.linkedin.com/in/johndoe/"

    # --- test 2: URL identifier starting with http, /in/ path extraction (lines 29-33) ---

    @pytest.mark.asyncio
    async def test_scrape_url_with_in_path_extracts_handle(self):
        """scrape() with a full URL extracts handle from /in/ segment."""
        crawler = self._make_crawler()

        content = "<html><body>Jane profile</body></html>"
        page_cm, inner_page = _make_page_cm(
            content=content,
            url="https://www.linkedin.com/in/jane-smith/",
            title="Jane Smith | LinkedIn",
        )

        with patch.object(crawler, "_extract", new=AsyncMock(return_value={"display_name": "Jane Smith", "handle": "jane-smith"})):
            with patch.object(crawler, "page", page_cm):
                result = await crawler.scrape("https://www.linkedin.com/in/jane-smith/")

        assert result.found is True
        assert result.profile_url == "https://www.linkedin.com/in/jane-smith/"
        # handle extracted from /in/ segment
        assert result.identifier == "jane-smith"

    # --- test 3: URL without /in/ — falls back to full URL as handle (line 32 else branch) ---

    @pytest.mark.asyncio
    async def test_scrape_url_without_in_uses_full_url_as_handle(self):
        """scrape() with an http URL that has no /in/ uses the URL itself as handle."""
        crawler = self._make_crawler()

        content = "<html><body>Company page</body></html>"
        page_cm, inner_page = _make_page_cm(
            content=content,
            url="https://www.linkedin.com/company/acme/",
            title="Acme Corp | LinkedIn",
        )

        with patch.object(crawler, "_extract", new=AsyncMock(return_value={"display_name": "Acme Corp", "handle": "https://www.linkedin.com/company/acme/"})):
            with patch.object(crawler, "page", page_cm):
                result = await crawler.scrape("https://www.linkedin.com/company/acme/")

        assert result.platform == "linkedin"

    # --- test 4: auth wall → _try_public_view is called (lines 41-43 / 65-66) ---

    @pytest.mark.asyncio
    async def test_scrape_authwall_calls_try_public_view(self):
        """When page.url contains 'authwall', scrape() delegates to _try_public_view."""
        crawler = self._make_crawler()

        page_cm, inner_page = _make_page_cm(
            content="<html>login required</html>",
            url="https://www.linkedin.com/authwall?session_redirect=...",
            title="LinkedIn Login",
        )

        public_result = MagicMock()
        public_result.found = False

        with patch.object(crawler, "_try_public_view", new=AsyncMock(return_value=public_result)) as mock_tpv:
            with patch.object(crawler, "page", page_cm):
                result = await crawler.scrape("johndoe")

        mock_tpv.assert_called_once_with("johndoe")
        assert result is public_result

    # --- test 5: login in URL → _try_public_view called (covers "login" branch of line 41) ---

    @pytest.mark.asyncio
    async def test_scrape_login_url_calls_try_public_view(self):
        """When page.url contains 'login', scrape() delegates to _try_public_view."""
        crawler = self._make_crawler()

        page_cm, inner_page = _make_page_cm(
            content="<html>Sign in to LinkedIn</html>",
            url="https://www.linkedin.com/login?fromSignIn=true",
            title="LinkedIn: Log In or Sign Up",
        )

        public_result = MagicMock()
        public_result.found = False

        with patch.object(crawler, "_try_public_view", new=AsyncMock(return_value=public_result)) as mock_tpv:
            with patch.object(crawler, "page", page_cm):
                result = await crawler.scrape("johndoe")

        mock_tpv.assert_called_once_with("johndoe")

    # --- test 6: Page not found in content → found=False (line 45-46 / 71) ---

    @pytest.mark.asyncio
    async def test_scrape_page_not_found_content(self):
        """When content contains 'Page not found', scrape() returns found=False."""
        crawler = self._make_crawler()

        page_cm, _ = _make_page_cm(
            content="<html><body>Page not found</body></html>",
            url="https://www.linkedin.com/in/doesnotexist/",
            title="Page not found | LinkedIn",
        )

        with patch.object(crawler, "page", page_cm):
            result = await crawler.scrape("doesnotexist")

        assert result.found is False
        assert result.platform == "linkedin"

    # --- test 7: "profile does not exist" in content (lowercase check, line 45) ---

    @pytest.mark.asyncio
    async def test_scrape_profile_does_not_exist_content(self):
        """When content contains 'profile does not exist', scrape() returns found=False."""
        crawler = self._make_crawler()

        page_cm, _ = _make_page_cm(
            content="<html><body>This profile does not exist on LinkedIn.</body></html>",
            url="https://www.linkedin.com/in/ghost/",
            title="Profile not found | LinkedIn",
        )

        with patch.object(crawler, "page", page_cm):
            result = await crawler.scrape("ghost")

        assert result.found is False

    # --- test 8: _extract returns empty dict → found=False (line 50-57 / 76) ---

    @pytest.mark.asyncio
    async def test_scrape_extract_returns_empty_dict(self):
        """When _extract returns no display_name, found is False."""
        crawler = self._make_crawler()

        page_cm, _ = _make_page_cm(
            content="<html><body>profile page</body></html>",
            url="https://www.linkedin.com/in/sparse/",
            title="LinkedIn",
        )

        with patch.object(crawler, "_extract", new=AsyncMock(return_value={"handle": "sparse"})):
            with patch.object(crawler, "page", page_cm):
                result = await crawler.scrape("sparse")

        assert result.found is False
        assert result.platform == "linkedin"


# ===========================================================================
# LinkedIn _extract — post_count lines 120-126
# ===========================================================================


class TestLinkedInExtract:
    """Tests for LinkedInCrawler._extract() focusing on post_count branch."""

    def _make_crawler(self):
        from modules.crawlers.linkedin import LinkedInCrawler

        return LinkedInCrawler()

    @pytest.mark.asyncio
    async def test_extract_post_count_from_primary_selector(self):
        """Lines 120-124: post_count parsed from .pv-recent-activity-section__headline-text."""
        crawler = self._make_crawler()

        # Build mock page
        page = AsyncMock()
        page.title = AsyncMock(return_value="John Doe | LinkedIn")

        # headline, loc, conn selectors → None
        post_count_el = AsyncMock()
        post_count_el.inner_text = AsyncMock(return_value="42 posts")

        async def _qs(selector):
            if "pv-recent-activity-section__headline-text" in selector:
                return post_count_el
            return None

        page.query_selector = AsyncMock(side_effect=_qs)
        page.query_selector_all = AsyncMock(return_value=[])

        data = await crawler._extract(page, "johndoe")

        assert data.get("post_count") == 42

    @pytest.mark.asyncio
    async def test_extract_post_count_fallback_to_data_test_id(self):
        """Lines 118-124: when primary selector returns None, fallback to [data-test-id='post-count']."""
        crawler = self._make_crawler()

        page = AsyncMock()
        page.title = AsyncMock(return_value="John Doe | LinkedIn")

        post_count_el = AsyncMock()
        post_count_el.inner_text = AsyncMock(return_value="5 posts in the last 30 days")

        call_count = {"n": 0}

        async def _qs(selector):
            call_count["n"] += 1
            if "pv-recent-activity-section__headline-text" in selector:
                return None  # primary misses
            if "data-test-id" in selector and "post-count" in selector:
                return post_count_el  # fallback hits
            return None

        page.query_selector = AsyncMock(side_effect=_qs)
        page.query_selector_all = AsyncMock(return_value=[])

        data = await crawler._extract(page, "johndoe")

        assert data.get("post_count") == 5

    @pytest.mark.asyncio
    async def test_extract_post_count_invalid_text_skipped(self):
        """Lines 120-126: ValueError when int() conversion fails — key absent, no exception raised."""
        crawler = self._make_crawler()

        page = AsyncMock()
        page.title = AsyncMock(return_value="John Doe | LinkedIn")

        post_count_el = AsyncMock()
        post_count_el.inner_text = AsyncMock(return_value="Many posts")

        async def _qs(selector):
            if "pv-recent-activity-section__headline-text" in selector:
                return post_count_el
            return None

        page.query_selector = AsyncMock(side_effect=_qs)
        page.query_selector_all = AsyncMock(return_value=[])

        data = await crawler._extract(page, "johndoe")

        # Key should be absent (ValueError caught on line 125)
        assert "post_count" not in data

    @pytest.mark.asyncio
    async def test_extract_post_count_with_comma(self):
        """post_count strips commas before int conversion — '1,234 posts' → 1234."""
        crawler = self._make_crawler()

        page = AsyncMock()
        page.title = AsyncMock(return_value="John Doe | LinkedIn")

        post_count_el = AsyncMock()
        post_count_el.inner_text = AsyncMock(return_value="1,234 posts")

        async def _qs(selector):
            if "pv-recent-activity-section__headline-text" in selector:
                return post_count_el
            return None

        page.query_selector = AsyncMock(side_effect=_qs)
        page.query_selector_all = AsyncMock(return_value=[])

        data = await crawler._extract(page, "johndoe")

        assert data.get("post_count") == 1234

    @pytest.mark.asyncio
    async def test_extract_title_with_dash_separator(self):
        """_extract uses '-' separator when '|' is absent in title (line 65-66)."""
        crawler = self._make_crawler()

        page = AsyncMock()
        page.title = AsyncMock(return_value="Jane Smith - Software Engineer - LinkedIn")
        page.query_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[])

        data = await crawler._extract(page, "jane-smith")

        assert data.get("display_name") == "Jane Smith"

    @pytest.mark.asyncio
    async def test_extract_no_title_separator(self):
        """When title has neither | nor -, display_name is not set."""
        crawler = self._make_crawler()

        page = AsyncMock()
        page.title = AsyncMock(return_value="LinkedIn")
        page.query_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[])

        data = await crawler._extract(page, "somebody")

        assert "display_name" not in data


# ===========================================================================
# LinkedIn _try_public_view — lines 160-191
# ===========================================================================


class TestLinkedInTryPublicView:
    """Tests for LinkedInCrawler._try_public_view() — lines 162-191."""

    def _make_crawler(self):
        from modules.crawlers.linkedin import LinkedInCrawler

        return LinkedInCrawler()

    def _patch_httpx(self, mock_resp):
        """
        Helper: return a context manager that patches httpx.AsyncClient at the
        module level where it is imported inside _try_public_view (local import).
        Because httpx is imported inside the function body, we must patch the
        httpx module's AsyncClient directly.
        """
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        return patch("httpx.AsyncClient", return_value=mock_client)

    @pytest.mark.asyncio
    async def test_try_public_view_200_with_h1_returns_found_true(self):
        """Lines 175-188: status 200, no authwall in URL, h1 present → found=True."""
        crawler = self._make_crawler()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://www.linkedin.com/in/johndoe/"  # no authwall
        mock_resp.text = "<html><h1>John Doe</h1><p>Software Engineer</p></html>"

        with self._patch_httpx(mock_resp):
            result = await crawler._try_public_view("johndoe")

        assert result.found is True
        assert result.platform == "linkedin"
        assert result.data.get("display_name") == "John Doe"
        assert "johndoe" in result.profile_url

    @pytest.mark.asyncio
    async def test_try_public_view_200_no_h1_returns_found_false(self):
        """Lines 175-188: status 200, no authwall, but no h1 tag → found=False."""
        crawler = self._make_crawler()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://www.linkedin.com/in/johndoe/"
        mock_resp.text = "<html><p>No heading here.</p></html>"

        with self._patch_httpx(mock_resp):
            result = await crawler._try_public_view("johndoe")

        assert result.found is False
        assert result.platform == "linkedin"

    @pytest.mark.asyncio
    async def test_try_public_view_authwall_in_redirect_url(self):
        """When response URL contains 'authwall', the 200 branch is skipped → returns auth_wall error."""
        crawler = self._make_crawler()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://www.linkedin.com/authwall?trk=..."
        mock_resp.text = "<html>Login required</html>"

        with self._patch_httpx(mock_resp):
            result = await crawler._try_public_view("johndoe")

        # Falls through to line 191: found=False, error="auth_wall"
        assert result.found is False
        assert result.data.get("error") == "auth_wall"

    @pytest.mark.asyncio
    async def test_try_public_view_non_200_status(self):
        """Non-200 status code skips the branch → falls to auth_wall fallback (line 191)."""
        crawler = self._make_crawler()

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.url = "https://www.linkedin.com/in/johndoe/"
        mock_resp.text = "<html>Forbidden</html>"

        with self._patch_httpx(mock_resp):
            result = await crawler._try_public_view("johndoe")

        assert result.found is False
        assert result.data.get("error") == "auth_wall"

    @pytest.mark.asyncio
    async def test_try_public_view_exception_returns_auth_wall(self):
        """Lines 189-191: exception during httpx call → found=False, error='auth_wall'."""
        crawler = self._make_crawler()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await crawler._try_public_view("johndoe")

        assert result.found is False
        assert result.data.get("error") == "auth_wall"
        assert result.platform == "linkedin"

    @pytest.mark.asyncio
    async def test_try_public_view_source_reliability_discounted(self):
        """Lines 185-188: public view result has source_reliability *= 0.7."""
        crawler = self._make_crawler()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://www.linkedin.com/in/johndoe/"
        mock_resp.text = "<html><h1>John Doe</h1></html>"

        with self._patch_httpx(mock_resp):
            result = await crawler._try_public_view("johndoe")

        expected_reliability = crawler.source_reliability * 0.7
        assert abs(result.source_reliability - expected_reliability) < 0.001


# ===========================================================================
# FindAGrave _parse_memorial_html — jsonld branch (lines 72-83 / 92-118)
# ===========================================================================


class TestFindAGraveParseMemorialHtml:
    """Tests for _parse_memorial_html() JSON-LD fallback branch."""

    def test_jsonld_single_person_object(self):
        """Lines 93-116: single JSON-LD Person object is parsed into result."""
        from modules.crawlers.people_findagrave import _parse_memorial_html

        html = (
            '<html><body>'
            '<script type="application/ld+json">'
            '{"@type": "Person", "name": "John Doe", "birthDate": "1900", "deathDate": "1985", '
            '"url": "https://www.findagrave.com/memorial/12345"}'
            '</script>'
            '</body></html>'
        )

        results = _parse_memorial_html(html)

        assert len(results) == 1
        assert results[0]["name"] == "John Doe"
        assert results[0]["birth_date"] == "1900"
        assert results[0]["death_date"] == "1985"
        assert results[0]["memorial_url"] == "https://www.findagrave.com/memorial/12345"
        assert results[0]["memorial_id"] == ""

    def test_jsonld_list_with_multiple_persons(self):
        """JSON-LD array containing multiple Person objects — all parsed (lines 103-113)."""
        from modules.crawlers.people_findagrave import _parse_memorial_html

        data = [
            {"@type": "Person", "name": "Alice Smith", "birthDate": "1920"},
            {"@type": "Person", "name": "Bob Smith", "birthDate": "1922"},
        ]
        html = (
            '<html><body>'
            f'<script type="application/ld+json">{json.dumps(data)}</script>'
            '</body></html>'
        )

        results = _parse_memorial_html(html)

        assert len(results) == 2
        names = [r["name"] for r in results]
        assert "Alice Smith" in names
        assert "Bob Smith" in names

    def test_jsonld_non_person_type_ignored(self):
        """JSON-LD entries with @type != 'Person' are skipped (line 105 condition)."""
        from modules.crawlers.people_findagrave import _parse_memorial_html

        html = (
            '<html><body>'
            '<script type="application/ld+json">'
            '{"@type": "WebPage", "name": "Search Results"}'
            '</script>'
            '</body></html>'
        )

        results = _parse_memorial_html(html)

        assert results == []

    def test_jsonld_invalid_json_is_skipped(self):
        """Malformed JSON in ld+json block is caught and skipped (line 115 except)."""
        from modules.crawlers.people_findagrave import _parse_memorial_html

        html = (
            '<html><body>'
            '<script type="application/ld+json">NOT VALID JSON {{{</script>'
            '</body></html>'
        )

        results = _parse_memorial_html(html)

        assert results == []

    def test_jsonld_mixed_valid_and_invalid_blocks(self):
        """One invalid ld+json block, one valid — only valid is returned."""
        from modules.crawlers.people_findagrave import _parse_memorial_html

        html = (
            '<html><body>'
            '<script type="application/ld+json">GARBAGE</script>'
            '<script type="application/ld+json">'
            '{"@type": "Person", "name": "Mary Jones"}'
            '</script>'
            '</body></html>'
        )

        results = _parse_memorial_html(html)

        assert len(results) == 1
        assert results[0]["name"] == "Mary Jones"

    def test_jsonld_person_with_missing_optional_fields(self):
        """JSON-LD Person with only name — birth/death/url default to empty string."""
        from modules.crawlers.people_findagrave import _parse_memorial_html

        html = (
            '<html><body>'
            '<script type="application/ld+json">'
            '{"@type": "Person", "name": "Unnamed Person"}'
            '</script>'
            '</body></html>'
        )

        results = _parse_memorial_html(html)

        assert len(results) == 1
        assert results[0]["name"] == "Unnamed Person"
        assert results[0]["birth_date"] == ""
        assert results[0]["death_date"] == ""
        assert results[0]["memorial_url"] == ""

    def test_regular_html_memorial_blocks_take_priority_over_jsonld(self):
        """When memorial-item divs are found, JSON-LD fallback is not used."""
        from modules.crawlers.people_findagrave import _parse_memorial_html

        html = (
            '<html><body>'
            '<div class="memorial-item">'
            '<a href="/memorial/99999/john-doe">John Doe</a>'
            '</div>'
            '<script type="application/ld+json">'
            '{"@type": "Person", "name": "Should Not Appear"}'
            '</script>'
            '</body></html>'
        )

        results = _parse_memorial_html(html)

        names = [r.get("name", "") for r in results]
        assert "Should Not Appear" not in names


# ===========================================================================
# FindAGrave scrape() — lines 141-202
# ===========================================================================


class TestFindAGraveScrape:
    """Tests for FindAGraveCrawler.scrape() covering all branches (lines 141-202)."""

    def _make_crawler(self):
        from modules.crawlers.people_findagrave import FindAGraveCrawler

        return FindAGraveCrawler()

    @pytest.mark.asyncio
    async def test_scrape_empty_identifier_returns_error(self):
        """Lines 143-151: empty string → error='empty_identifier', found=False."""
        crawler = self._make_crawler()

        result = await crawler.scrape("   ")

        assert result.found is False
        assert result.data.get("error") == "empty_identifier"
        assert result.platform == "people_findagrave"

    @pytest.mark.asyncio
    async def test_scrape_none_response_returns_http_error(self):
        """Lines 165-173: resp is None → error='http_error'."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_scrape_403_returns_blocked_error(self):
        """Lines 175-183: status 403 → error='blocked_403'."""
        crawler = self._make_crawler()

        resp = _mock_resp(status=403, text="Forbidden")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.data.get("error") == "blocked_403"

    @pytest.mark.asyncio
    async def test_scrape_non_200_returns_http_status_error(self):
        """Lines 185-193: status != 200 (e.g. 503) → error='http_503'."""
        crawler = self._make_crawler()

        resp = _mock_resp(status=503, text="Service Unavailable")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.data.get("error") == "http_503"

    @pytest.mark.asyncio
    async def test_scrape_200_with_no_results_found_false(self):
        """Lines 195-202: 200 response but no memorial HTML → found=False, empty memorials."""
        crawler = self._make_crawler()

        resp = _mock_resp(status=200, text="<html><body>No results found</body></html>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.data.get("memorials") == []
        assert result.data.get("total") == 0

    @pytest.mark.asyncio
    async def test_scrape_200_with_jsonld_person_found_true(self):
        """Lines 195-202: 200 response with JSON-LD Person → found=True, memorials populated."""
        crawler = self._make_crawler()

        html = (
            '<html><body>'
            '<script type="application/ld+json">'
            '{"@type": "Person", "name": "Jane Doe", "birthDate": "1945", "deathDate": "2010"}'
            '</script>'
            '</body></html>'
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Doe")

        assert result.found is True
        assert result.data.get("total") == 1
        assert result.data["memorials"][0]["name"] == "Jane Doe"
        assert result.data.get("query") == "Jane Doe"

    @pytest.mark.asyncio
    async def test_scrape_single_word_name_uses_as_last_name(self):
        """Lines 153-155: single word name — first='', last=word."""
        crawler = self._make_crawler()

        html = (
            '<html><body>'
            '<script type="application/ld+json">'
            '{"@type": "Person", "name": "Elvis"}'
            '</script>'
            '</body></html>'
        )
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Elvis")

        # Should not raise; single-word name handled gracefully
        assert result.platform == "people_findagrave"

    @pytest.mark.asyncio
    async def test_scrape_url_contains_first_and_last_name(self):
        """Verify URL is built with correctly split first/last name via quote_plus."""
        crawler = self._make_crawler()

        resp = _mock_resp(status=200, text="<html><body>empty</body></html>")
        get_mock = AsyncMock(return_value=resp)
        with patch.object(crawler, "get", new=get_mock):
            await crawler.scrape("John Smith")

        called_url = get_mock.call_args[0][0]
        assert "John" in called_url
        assert "Smith" in called_url


# ===========================================================================
# ThatsThem _build_url — lines 40-52
# ===========================================================================


class TestThatsThemBuildUrl:
    """Unit tests for the pure _build_url() function (lines 40-52)."""

    def test_phone_with_plus_prefix(self):
        """Line 43: identifier starting with '+' → mode='phone'."""
        from modules.crawlers.people_thatsthem import _build_url

        url, mode = _build_url("+13055551234")

        assert mode == "phone"
        assert "/phone/" in url
        assert "13055551234" in url

    def test_phone_starting_with_digit(self):
        """Line 43: identifier starting with digit → mode='phone'."""
        from modules.crawlers.people_thatsthem import _build_url

        url, mode = _build_url("3055551234")

        assert mode == "phone"
        assert "/phone/" in url

    def test_phone_strips_non_digits(self):
        """_build_url strips dashes/spaces/parens from phone numbers."""
        from modules.crawlers.people_thatsthem import _build_url

        url, mode = _build_url("+1 (305) 555-1234")

        assert mode == "phone"
        assert "(305)" not in url
        assert "-" not in url.split("/phone/")[1]

    def test_email_mode(self):
        """Line 46-47 / 62: identifier containing '@' → mode='email'."""
        from modules.crawlers.people_thatsthem import _build_url

        url, mode = _build_url("test@example.com")

        assert mode == "email"
        assert "/email/" in url

    def test_email_with_plus_sign_in_local_part(self):
        """Email with + in local part — still routed as email (@ takes priority)."""
        from modules.crawlers.people_thatsthem import _build_url

        url, mode = _build_url("user+tag@example.com")

        assert mode == "email"

    def test_name_two_words(self):
        """Lines 48-52: two-word name → mode='name', slug='First-Last'."""
        from modules.crawlers.people_thatsthem import _build_url

        url, mode = _build_url("John Doe")

        assert mode == "name"
        assert "/name/" in url
        assert "John-Doe" in url

    def test_name_single_word_slug_has_no_trailing_dash(self):
        """Single word name: slug = 'John-' then strip('-') → 'John'."""
        from modules.crawlers.people_thatsthem import _build_url

        url, mode = _build_url("John")

        assert mode == "name"
        assert "/name/" in url
        assert "John-" not in url  # trailing dash stripped
        assert "John" in url


# ===========================================================================
# ThatsThem _parse_persons — lines 82-123
# ===========================================================================


class TestThatsThemParsePersons:
    """Tests for _parse_persons() HTML parsing (lines 65-127)."""

    def test_parse_record_with_name_address_phones_emails_age(self):
        """Full card with all fields populated."""
        from modules.crawlers.people_thatsthem import _parse_persons

        html = """
        <html><body>
          <div class="record">
            <h2 class="name">John Doe</h2>
            <div class="address">123 Main St, Miami, FL 33101</div>
            <a href="tel:+13055551234" class="phone">+1 (305) 555-1234</a>
            <a href="mailto:john@example.com">john@example.com</a>
            <div class="age">Age 45</div>
          </div>
        </body></html>
        """

        persons = _parse_persons(html)

        assert len(persons) == 1
        p = persons[0]
        assert p["name"] == "John Doe"
        assert "123 Main St" in p["address"]
        assert any("305" in ph for ph in p.get("phones", []))
        assert p.get("age") == 45

    def test_parse_multiple_records(self):
        """Multiple record divs → multiple person entries."""
        from modules.crawlers.people_thatsthem import _parse_persons

        html = """
        <html><body>
          <div class="record"><h2 class="name">Alice</h2><div class="address">Addr 1</div></div>
          <div class="record"><h2 class="name">Bob</h2><div class="address">Addr 2</div></div>
        </body></html>
        """

        persons = _parse_persons(html)

        assert len(persons) == 2
        names = [p["name"] for p in persons]
        assert "Alice" in names
        assert "Bob" in names

    def test_parse_fallback_article_selector(self):
        """Fallback selector 'article' used when no .record divs found."""
        from modules.crawlers.people_thatsthem import _parse_persons

        html = """
        <html><body>
          <article>
            <h2>Carol</h2>
            <div class="address">789 Oak Ave</div>
          </article>
        </body></html>
        """

        persons = _parse_persons(html)

        assert len(persons) >= 1
        assert persons[0]["name"] == "Carol"

    def test_parse_empty_html_returns_empty_list(self):
        """No cards at all → empty list."""
        from modules.crawlers.people_thatsthem import _parse_persons

        persons = _parse_persons("<html><body></body></html>")

        assert persons == []

    def test_parse_card_without_name_or_address_excluded(self):
        """Cards without name or address are not appended (line 122 condition)."""
        from modules.crawlers.people_thatsthem import _parse_persons

        html = """
        <html><body>
          <div class="record">
            <a href="tel:+13055551234">+1 (305) 555-1234</a>
          </div>
        </body></html>
        """

        persons = _parse_persons(html)

        assert persons == []

    def test_parse_email_from_href(self):
        """Email extracted from mailto: href when link text is empty."""
        from modules.crawlers.people_thatsthem import _parse_persons

        html = """
        <html><body>
          <div class="record">
            <h2>Dave</h2>
            <a href="mailto:dave@test.com"></a>
          </div>
        </body></html>
        """

        persons = _parse_persons(html)

        assert len(persons) == 1
        assert "dave@test.com" in persons[0].get("emails", [])

    def test_parse_deduplicates_phone_numbers(self):
        """Duplicate phone numbers are deduplicated (dict.fromkeys on line 101)."""
        from modules.crawlers.people_thatsthem import _parse_persons

        html = """
        <html><body>
          <div class="record">
            <h2>Eve</h2>
            <a href="tel:+13055551234" class="phone">305-555-1234</a>
            <a href="tel:+13055551234" class="phone">305-555-1234</a>
          </div>
        </body></html>
        """

        persons = _parse_persons(html)

        assert len(persons) == 1
        assert len(persons[0].get("phones", [])) == 1


# ===========================================================================
# ThatsThem scrape() — lines 151-196
# ===========================================================================


class TestThatsThemScrape:
    """Tests for PeopleThatsThemCrawler.scrape() covering all branches (lines 151-196)."""

    def _make_crawler(self):
        from modules.crawlers.people_thatsthem import PeopleThatsThemCrawler

        return PeopleThatsThemCrawler()

    @pytest.mark.asyncio
    async def test_scrape_none_response_returns_http_error(self):
        """Lines 156-163: resp is None → CrawlerResult(error='http_error', found=False)."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Doe")

        assert result.found is False
        assert result.error == "http_error"
        assert result.platform == "people_thatsthem"

    @pytest.mark.asyncio
    async def test_scrape_429_returns_rate_limited(self):
        """Lines 165-172: status 429 → CrawlerResult(error='rate_limited')."""
        crawler = self._make_crawler()

        resp = _mock_resp(status=429, text="Too Many Requests")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")

        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_scrape_404_returns_not_found_result(self):
        """Lines 174-175: status 404 → _result() with found=False, persons=[], mode set."""
        crawler = self._make_crawler()

        resp = _mock_resp(status=404, text="Not Found")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")

        assert result.found is False
        assert result.platform == "people_thatsthem"
        assert result.data.get("persons") == []
        assert result.data.get("mode") == "name"

    @pytest.mark.asyncio
    async def test_scrape_non_200_non_404_non_429_returns_http_status(self):
        """Lines 177-183: status 500 → CrawlerResult(error='http_500')."""
        crawler = self._make_crawler()

        resp = _mock_resp(status=500, text="Internal Server Error")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")

        assert result.found is False
        assert result.error == "http_500"

    @pytest.mark.asyncio
    async def test_scrape_200_no_persons_found_false(self):
        """Lines 186-196: 200 response with no parseable cards → found=False."""
        crawler = self._make_crawler()

        resp = _mock_resp(status=200, text="<html><body>No results.</body></html>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")

        assert result.found is False
        assert result.data.get("persons") == []

    @pytest.mark.asyncio
    async def test_scrape_200_with_person_found_true(self):
        """Lines 186-196: 200 response with person cards → found=True, persons populated."""
        crawler = self._make_crawler()

        html = """
        <html><body>
          <div class="record">
            <h2 class="name">John Doe</h2>
            <div class="address">Miami, FL 33101</div>
          </div>
        </body></html>
        """
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")

        assert result.found is True
        assert len(result.data.get("persons", [])) >= 1
        assert result.data.get("mode") == "name"
        assert result.data.get("query") == "John Doe"

    @pytest.mark.asyncio
    async def test_scrape_phone_mode_sets_correct_mode(self):
        """Lines 152 + 194: phone identifier sets mode='phone' in result data."""
        crawler = self._make_crawler()

        html = """
        <html><body>
          <div class="record">
            <h2 class="name">John Doe</h2>
            <div class="address">123 Main St</div>
          </div>
        </body></html>
        """
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+13055551234")

        assert result.data.get("mode") == "phone"

    @pytest.mark.asyncio
    async def test_scrape_email_mode_sets_correct_mode(self):
        """Line 62 / email routing: email identifier sets mode='email' in result data."""
        crawler = self._make_crawler()

        html = """
        <html><body>
          <div class="record">
            <h2 class="name">John Doe</h2>
            <div class="address">456 Elm St</div>
          </div>
        </body></html>
        """
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("john@example.com")

        assert result.data.get("mode") == "email"

    @pytest.mark.asyncio
    async def test_scrape_200_sets_profile_url(self):
        """Lines 189-196: profile_url is set to the built URL on success."""
        crawler = self._make_crawler()

        html = """
        <html><body>
          <div class="record">
            <h2 class="name">Jane Smith</h2>
            <div class="address">789 Oak Ave</div>
          </div>
        </body></html>
        """
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Smith")

        assert result.data.get("profile_url") is not None
        assert "thatsthem.com" in result.data.get("profile_url", "")

    @pytest.mark.asyncio
    async def test_scrape_404_phone_sets_phone_mode(self):
        """404 for phone identifier still correctly sets mode='phone' in result data."""
        crawler = self._make_crawler()

        resp = _mock_resp(status=404, text="Not Found")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+15551234567")

        assert result.found is False
        assert result.data.get("mode") == "phone"
