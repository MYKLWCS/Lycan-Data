"""
test_crawlers_wave6a.py — Coverage gap tests for phase5 crawlers (batch A).

Targets specific uncovered lines in 11 crawlers:
  bing_news        lines 44-46, 64
  bluesky_profile  lines 43-45, 49
  ca_courts        lines 42, 64-66
  clustrmaps       lines 47, 56-59
  county_assessor_fl lines 42, 62-66
  county_assessor_tx lines 64-67, 70
  familytreenow    lines 42, 49
  fl_courts        lines 58-63, 70
  gdelt_mentions   lines 42, 46-48
  github_profile   lines 45, 49-51
  google_news_rss  lines 40, 44-46
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_resp(status=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ---------------------------------------------------------------------------
# 1. bing_news.py
#    line 44-46: ET.ParseError branch → found=False, error="parse_error"
#    line 64:    articles list is empty → found=False
# ---------------------------------------------------------------------------


class TestBingNews:
    @pytest.mark.asyncio
    async def test_parse_error_returns_not_found(self):
        """Lines 44-46: malformed XML triggers ET.ParseError → parse_error result."""
        from modules.crawlers.bing_news import BingNewsCrawler

        crawler = BingNewsCrawler()
        resp = _mock_resp(status=200, text="<<not xml>>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_empty_articles_returns_not_found(self):
        """Line 64: valid XML but no <item> elements → found=False."""
        from modules.crawlers.bing_news import BingNewsCrawler

        crawler = BingNewsCrawler()
        # Valid RSS shell with no items
        xml = "<rss><channel><title>Bing News</title></channel></rss>"
        resp = _mock_resp(status=200, text=xml)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 39-40 (already covered by wave5): extra guard — None response."""
        from modules.crawlers.bing_news import BingNewsCrawler

        crawler = BingNewsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Doe")
        assert result.found is False


# ---------------------------------------------------------------------------
# 2. bluesky_profile.py
#    lines 43-45: JSON decode failure → found=False, error="parse_error"
#    line 49:     payload has neither displayName nor handle → found=False
# ---------------------------------------------------------------------------


class TestBlueskyProfile:
    @pytest.mark.asyncio
    async def test_json_parse_error_returns_not_found(self):
        """Lines 43-45: resp.json() raises → parse_error result."""
        from modules.crawlers.bluesky_profile import BlueskyProfileCrawler

        crawler = BlueskyProfileCrawler()
        resp = _mock_resp(status=200)  # json.side_effect=ValueError already set
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("user.bsky.social")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_empty_payload_returns_not_found(self):
        """Line 49: payload with no displayName and no handle → found=False."""
        from modules.crawlers.bluesky_profile import BlueskyProfileCrawler

        crawler = BlueskyProfileCrawler()
        resp = _mock_resp(status=200, json_data={})
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("ghost.bsky.social")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_found_with_handle_only(self):
        """Confirm line 49 is skipped when handle is present (found=True path)."""
        from modules.crawlers.bluesky_profile import BlueskyProfileCrawler

        crawler = BlueskyProfileCrawler()
        resp = _mock_resp(
            status=200, json_data={"handle": "user.bsky.social", "followersCount": 100}
        )
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("user.bsky.social")
        assert result.found is True


# ---------------------------------------------------------------------------
# 3. ca_courts.py
#    line 42:    HTTP non-200 → found=False
#    lines 64-66: generic fallback "case-row" elements picked up
# ---------------------------------------------------------------------------


class TestCaCourts:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 42: resp.status_code != 200 → found=False."""
        from modules.crawlers.ca_courts import CaCourtsCrawler

        crawler = CaCourtsCrawler()
        resp = _mock_resp(status=503)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Smith")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_case_row_fallback_found(self):
        """Lines 64-66: no caselist table but elements with 'case-row' class exist."""
        from modules.crawlers.ca_courts import CaCourtsCrawler

        crawler = CaCourtsCrawler()
        # Real HTML: no #caselist table → primary select returns nothing.
        # A <div class="case-row"> triggers the fallback find_all branch.
        html = '<html><body><div class="case-row">21STCV12345 - Smith v State</div></body></html>'
        resp = _mock_resp(status=200, text=html)

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Smith")

        assert result.found is True
        assert result.data["count"] >= 1

    @pytest.mark.asyncio
    async def test_no_cases_returns_not_found(self):
        """Line 69: no table rows and no case-row divs → found=False."""
        from modules.crawlers.ca_courts import CaCourtsCrawler

        crawler = CaCourtsCrawler()
        resp = _mock_resp(status=200, text="<html><body><p>No results</p></body></html>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Nobody Here")
        assert result.found is False


# ---------------------------------------------------------------------------
# 4. clustrmaps.py
#    line 47:    soup has no h1 → found=False
#    lines 56-59: no address-item class elements but "address" divs exist
# ---------------------------------------------------------------------------


class TestClustrMaps:
    @pytest.mark.asyncio
    async def test_no_h1_returns_not_found(self):
        """Line 47: page loads but no <h1> tag → found=False."""
        from modules.crawlers.clustrmaps import ClustrMapsCrawler

        crawler = ClustrMapsCrawler()
        resp = _mock_resp(status=200, text="<html><body><p>Not a person page</p></body></html>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_address_div_fallback(self):
        """Lines 56-59: no .address-item elements but divs with 'address' in class → found=True."""
        from modules.crawlers.clustrmaps import ClustrMapsCrawler

        crawler = ClustrMapsCrawler()
        html = """<html><body>
            <h1>John Doe</h1>
            <div class="address-history">123 Main St, Austin TX</div>
        </body></html>"""
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is True
        assert len(result.data["addresses"]) >= 1

    @pytest.mark.asyncio
    async def test_h1_present_no_addresses(self):
        """Confirm found=False when h1 exists but no addresses of any kind."""
        from modules.crawlers.clustrmaps import ClustrMapsCrawler

        crawler = ClustrMapsCrawler()
        html = "<html><body><h1>John Doe</h1></body></html>"
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False


# ---------------------------------------------------------------------------
# 5. county_assessor_fl.py
#    line 42:    HTTP non-200 → found=False
#    lines 62-66: no parcel-result elements, falls back to generic table rows
# ---------------------------------------------------------------------------


class TestCountyAssessorFl:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 42: HTTP error → found=False."""
        from modules.crawlers.county_assessor_fl import CountyAssessorFlCrawler

        crawler = CountyAssessorFlCrawler()
        resp = _mock_resp(status=404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123 Main St Orlando FL")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_table_fallback_returns_parcels(self):
        """Lines 62-66: no .parcel-result divs, but a data table with rows → found=True."""
        from modules.crawlers.county_assessor_fl import CountyAssessorFlCrawler

        crawler = CountyAssessorFlCrawler()
        html = """<html><body>
            <table>
              <tbody>
                <tr><td>34-22-28-0000-00-001</td><td>John Doe</td><td>$250,000</td></tr>
              </tbody>
            </table>
        </body></html>"""
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123 Main St Orlando FL")
        assert result.found is True
        assert result.data["count"] >= 1

    @pytest.mark.asyncio
    async def test_table_row_with_header_id_skipped(self):
        """Lines 64-65: table row whose first cell is 'Parcel ID' header is skipped."""
        from modules.crawlers.county_assessor_fl import CountyAssessorFlCrawler

        crawler = CountyAssessorFlCrawler()
        html = """<html><body>
            <table>
              <tbody>
                <tr><td>Parcel ID</td><td>Owner</td><td>Value</td></tr>
                <tr><td>34-22-28-0000-00-002</td><td>Jane Doe</td><td>$300,000</td></tr>
              </tbody>
            </table>
        </body></html>"""
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("456 Oak Ave Orlando FL")
        assert result.found is True
        # Only the data row should be captured, not the header
        assert result.data["count"] == 1


# ---------------------------------------------------------------------------
# 6. county_assessor_tx.py
#    lines 64-67: no results table, fallback to elements with "account" in class
#    line 70:    fallback also empty → found=False
# ---------------------------------------------------------------------------


class TestCountyAssessorTx:
    @pytest.mark.asyncio
    async def test_account_class_fallback_found(self):
        """Lines 64-67: no results table but element with 'account' class → found=True."""
        from modules.crawlers.county_assessor_tx import CountyAssessorTxCrawler

        crawler = CountyAssessorTxCrawler()
        html = """<html><body>
            <div class="account-number">R1234567</div>
        </body></html>"""
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123 Elm St Dallas TX")
        assert result.found is True
        assert result.data["count"] >= 1

    @pytest.mark.asyncio
    async def test_no_data_at_all_returns_not_found(self):
        """Line 70: no table rows, no account-class elements → found=False."""
        from modules.crawlers.county_assessor_tx import CountyAssessorTxCrawler

        crawler = CountyAssessorTxCrawler()
        resp = _mock_resp(status=200, text="<html><body><p>Nothing here</p></body></html>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("999 Nowhere Ln")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_table_results_found(self):
        """Cover the primary table path (verify baseline) and skip header row."""
        from modules.crawlers.county_assessor_tx import CountyAssessorTxCrawler

        crawler = CountyAssessorTxCrawler()
        html = """<html><body>
            <table class="results">
              <tr><td>account</td><td>Owner</td><td>Value</td></tr>
              <tr><td>R9876543</td><td>Bob Smith</td><td>$500,000</td></tr>
            </table>
        </body></html>"""
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("456 Main St Dallas TX")
        assert result.found is True
        assert result.data["count"] == 1


# ---------------------------------------------------------------------------
# 7. familytreenow.py
#    line 42:   HTTP non-200 → found=False
#    line 49:   cards is empty and "no results" text absent → found=False (second branch)
# ---------------------------------------------------------------------------


class TestFamilyTreeNow:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 42: HTTP error → found=False."""
        from modules.crawlers.familytreenow import FamilyTreeNowCrawler

        crawler = FamilyTreeNowCrawler()
        resp = _mock_resp(status=403)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_no_cards_no_text_returns_not_found(self):
        """Line 49: no card-block elements and no 'no results' text → second not-found branch."""
        from modules.crawlers.familytreenow import FamilyTreeNowCrawler

        crawler = FamilyTreeNowCrawler()
        # No card-block, no "no results" string — hits the final else on line 49
        html = "<html><body><p>Some unrelated content</p></body></html>"
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_no_cards_with_no_results_text_returns_not_found(self):
        """Line 48: no cards, page says 'no results' → first branch of the if."""
        from modules.crawlers.familytreenow import FamilyTreeNowCrawler

        crawler = FamilyTreeNowCrawler()
        html = "<html><body><p>Sorry, no results found.</p></body></html>"
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Nobody Known")
        assert result.found is False


# ---------------------------------------------------------------------------
# 8. fl_courts.py
#    lines 58-63: no .case-result divs, generic table-row fallback executes
#    line 70:    fallback also empty → found=False
# ---------------------------------------------------------------------------


class TestFlCourts:
    @pytest.mark.asyncio
    async def test_table_row_fallback_found(self):
        """Lines 58-63: no .case-result divs but tbody rows with data → found=True."""
        from modules.crawlers.fl_courts import FlCourtsCrawler

        crawler = FlCourtsCrawler()
        html = """<html><body>
            <table>
              <tbody>
                <tr><td>2023-CC-001234</td><td>Doe, John</td><td>Open</td></tr>
              </tbody>
            </table>
        </body></html>"""
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is True
        assert result.data["count"] >= 1

    @pytest.mark.asyncio
    async def test_table_row_starting_with_case_skipped(self):
        """Line 62: table row where first cell starts with 'case' is skipped as header."""
        from modules.crawlers.fl_courts import FlCourtsCrawler

        crawler = FlCourtsCrawler()
        html = """<html><body>
            <table>
              <tbody>
                <tr><td>Case Number</td><td>Party</td><td>Status</td></tr>
                <tr><td>2024-DR-005678</td><td>Smith, Jane</td><td>Closed</td></tr>
              </tbody>
            </table>
        </body></html>"""
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Smith")
        assert result.found is True
        # Header row skipped, only data row remains
        assert result.data["count"] == 1

    @pytest.mark.asyncio
    async def test_no_cases_returns_not_found(self):
        """Line 70: no case-result divs, no table rows → found=False."""
        from modules.crawlers.fl_courts import FlCourtsCrawler

        crawler = FlCourtsCrawler()
        resp = _mock_resp(status=200, text="<html><body><p>No records</p></body></html>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Ghost Person")
        assert result.found is False


# ---------------------------------------------------------------------------
# 9. gdelt_mentions.py
#    line 42:   HTTP non-200 → found=False
#    lines 46-48: JSON decode failure → parse_error
# ---------------------------------------------------------------------------


class TestGdeltMentions:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 42: non-200 response → found=False."""
        from modules.crawlers.gdelt_mentions import GdeltMentionsCrawler

        crawler = GdeltMentionsCrawler()
        resp = _mock_resp(status=429)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_not_found(self):
        """Lines 46-48: resp.json() raises → parse_error result."""
        from modules.crawlers.gdelt_mentions import GdeltMentionsCrawler

        crawler = GdeltMentionsCrawler()
        resp = _mock_resp(status=200)  # json.side_effect=ValueError already set
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_empty_articles_list_returns_not_found(self):
        """Line 52: articles key present but empty list → found=False."""
        from modules.crawlers.gdelt_mentions import GdeltMentionsCrawler

        crawler = GdeltMentionsCrawler()
        resp = _mock_resp(status=200, json_data={"articles": []})
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False


# ---------------------------------------------------------------------------
# 10. github_profile.py
#     line 45:   HTTP non-200 → found=False
#     lines 49-51: JSON decode failure → parse_error
# ---------------------------------------------------------------------------


class TestGitHubProfile:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 45: resp.status_code != 200 → found=False."""
        from modules.crawlers.github_profile import GitHubProfileCrawler

        crawler = GitHubProfileCrawler()
        resp = _mock_resp(status=403)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("johndoe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_not_found(self):
        """Lines 49-51: resp.json() raises → parse_error result."""
        from modules.crawlers.github_profile import GitHubProfileCrawler

        crawler = GitHubProfileCrawler()
        resp = _mock_resp(status=200)  # json.side_effect=ValueError already set
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("johndoe")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_empty_items_returns_not_found(self):
        """Line 55: items list empty → found=False."""
        from modules.crawlers.github_profile import GitHubProfileCrawler

        crawler = GitHubProfileCrawler()
        resp = _mock_resp(status=200, json_data={"total_count": 0, "items": []})
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("unknownxyz123")
        assert result.found is False


# ---------------------------------------------------------------------------
# 11. google_news_rss.py
#     line 40:   HTTP non-200 → found=False
#     lines 44-46: ET.ParseError → parse_error
# ---------------------------------------------------------------------------


class TestGoogleNewsRss:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 40: non-200 response → found=False."""
        from modules.crawlers.google_news_rss import GoogleNewsRssCrawler

        crawler = GoogleNewsRssCrawler()
        resp = _mock_resp(status=503)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_parse_error_returns_not_found(self):
        """Lines 44-46: malformed XML triggers ET.ParseError → parse_error result."""
        from modules.crawlers.google_news_rss import GoogleNewsRssCrawler

        crawler = GoogleNewsRssCrawler()
        resp = _mock_resp(status=200, text="<broken><<xml>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_empty_rss_returns_not_found(self):
        """Line 64: valid XML but no <item> elements → found=False."""
        from modules.crawlers.google_news_rss import GoogleNewsRssCrawler

        crawler = GoogleNewsRssCrawler()
        xml = "<rss><channel><title>Google News</title></channel></rss>"
        resp = _mock_resp(status=200, text=xml)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_rss_with_items_returns_found(self):
        """Baseline: valid RSS with items → found=True, articles populated."""
        from modules.crawlers.google_news_rss import GoogleNewsRssCrawler

        crawler = GoogleNewsRssCrawler()
        xml = """<rss><channel>
            <item>
                <title>John Doe wins award</title>
                <link>https://news.example.com/1</link>
                <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
                <source>Example News</source>
            </item>
        </channel></rss>"""
        resp = _mock_resp(status=200, text=xml)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is True
        assert result.data["count"] == 1
