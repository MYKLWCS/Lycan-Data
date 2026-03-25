"""
test_crawlers_wave6b.py — Coverage gap tests for phase5 crawlers (batch B).

Targets specific uncovered lines across:
  radaris, redfin_property, sec_insider, spokeo, spotify_public,
  stackoverflow_profile, threads_profile, txcourts, vin_decode_enhanced,
  interests_extractor
"""

from __future__ import annotations

import asyncio
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
# 1. radaris.py
#    line 48: name_tag found but name_text is falsy or "not found" -> found=False
#    line 52: name_text contains "not found" -> found=False
# ---------------------------------------------------------------------------


class TestRadarisCrawler:
    @pytest.mark.asyncio
    async def test_name_tag_empty_text_returns_not_found(self):
        """Line 48: profile-name tag exists but get_text returns empty string."""
        from modules.crawlers.radaris import RadarisCrawler

        html = "<html><body><div class='profile-name'></div></body></html>"
        resp = _mock_resp(status=200, text=html)
        crawler = RadarisCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_name_text_contains_not_found_returns_not_found(self):
        """Line 52: name_text contains 'not found' phrase."""
        from modules.crawlers.radaris import RadarisCrawler

        html = "<html><body><div class='profile-name'>Profile Not Found</div></body></html>"
        resp = _mock_resp(status=200, text=html)
        crawler = RadarisCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_no_name_tag_returns_not_found(self):
        """Line 48: neither .profile-name nor h1 found in page."""
        from modules.crawlers.radaris import RadarisCrawler

        html = "<html><body><p>some content</p></body></html>"
        resp = _mock_resp(status=200, text=html)
        crawler = RadarisCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Smith")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """HTTP non-200 -> found=False early return."""
        from modules.crawlers.radaris import RadarisCrawler

        resp = _mock_resp(status=403)
        crawler = RadarisCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False


# ---------------------------------------------------------------------------
# 2. redfin_property.py
#    line 50: HTTP failure -> found=False
#    lines 63-64: both json.loads and resp.json() fail -> found=False error=parse_error
# ---------------------------------------------------------------------------


class TestRedfinPropertyCrawler:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 50: resp.status_code != 200 -> found=False."""
        from modules.crawlers.redfin_property import RedfinPropertyCrawler

        resp = _mock_resp(status=503)
        crawler = RedfinPropertyCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123 Main St Dallas TX")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_none_response_returns_not_found(self):
        """Line 50: resp is None -> found=False."""
        from modules.crawlers.redfin_property import RedfinPropertyCrawler

        crawler = RedfinPropertyCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("123 Main St")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_both_json_parse_paths_fail_returns_parse_error(self):
        """Lines 63-64: raw_text json.loads fails AND resp.json() also raises -> parse_error."""
        from modules.crawlers.redfin_property import RedfinPropertyCrawler

        # text is not valid JSON and doesn't start with '{}&&'
        resp = _mock_resp(status=200, text="<html>not json at all</html>")
        # resp.json() is already set to raise ValueError by _mock_resp(json_data=None)
        crawler = RedfinPropertyCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123 Main St")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_redfin_prefix_stripped_and_parsed(self):
        """Covers the '{}&&' prefix-strip path (line 55-56) and happy path."""
        import json

        from modules.crawlers.redfin_property import RedfinPropertyCrawler

        payload = {
            "payload": {
                "homes": [
                    {
                        "address": {
                            "streetAddress": "123 Main",
                            "city": "Dallas",
                            "state": "TX",
                            "zip": "75001",
                        },
                        "price": 250000,
                        "beds": 3,
                        "baths": 2,
                        "sqFt": 1800,
                        "yearBuilt": 1995,
                        "listingType": "FOR_SALE",
                    }
                ]
            }
        }
        resp = _mock_resp(status=200, text="{}&&" + json.dumps(payload))
        # resp.json() should not be called in this path, but set it anyway
        resp.json.side_effect = ValueError("should not be called")
        crawler = RedfinPropertyCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("123 Main St Dallas TX")
        assert result.found is True
        assert result.data["count"] == 1


# ---------------------------------------------------------------------------
# 3. sec_insider.py
#    line 48: HTTP failure -> found=False
#    lines 52-54: JSON parse fails -> found=False error=parse_error
# ---------------------------------------------------------------------------


class TestSecInsiderCrawler:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 48: status != 200 -> found=False."""
        from modules.crawlers.sec_insider import SecInsiderCrawler

        resp = _mock_resp(status=404)
        crawler = SecInsiderCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Elon Musk")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_none_response_returns_not_found(self):
        """Line 48: resp is None -> found=False."""
        from modules.crawlers.sec_insider import SecInsiderCrawler

        crawler = SecInsiderCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("Jane Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_parse_error(self):
        """Lines 52-54: resp.json() raises -> found=False, error=parse_error."""
        from modules.crawlers.sec_insider import SecInsiderCrawler

        resp = _mock_resp(status=200, text="not-json")
        # json_data=None means resp.json() raises ValueError
        crawler = SecInsiderCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_happy_path_with_filings(self):
        """Covers hit parsing and found=True path."""
        from modules.crawlers.sec_insider import SecInsiderCrawler

        payload = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "entity_name": "Tesla Inc",
                            "form_type": "4",
                            "file_date": "2023-01-15",
                            "period_of_report": "2023-01-14",
                            "file_num": "000-56789",
                        }
                    }
                ],
                "total": {"value": 1},
            }
        }
        resp = _mock_resp(status=200, json_data=payload)
        crawler = SecInsiderCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Elon Musk")
        assert result.found is True
        assert result.data["total"] == 1
        assert len(result.data["filings"]) == 1


# ---------------------------------------------------------------------------
# 4. spokeo.py
#    lines 49-51: resp.json() raises -> found=False error=parse_error
#    line 56: html is empty string -> found=False
#    line 61: first card selector found nothing, second selector (select) also empty
#    line 63: cards is still empty after both selectors -> found=False
# ---------------------------------------------------------------------------


class TestSpokeoCrawler:
    @pytest.mark.asyncio
    async def test_json_parse_error_returns_parse_error(self):
        """Lines 49-51: resp.json() raises -> parse_error."""
        from modules.crawlers.spokeo import SpokeoCrawler

        resp = _mock_resp(status=200, text="bad json")
        # json_data=None already makes resp.json() raise
        crawler = SpokeoCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_empty_html_in_solution_returns_not_found(self):
        """Line 56: solution.response is empty string -> found=False."""
        from modules.crawlers.spokeo import SpokeoCrawler

        payload = {"solution": {"response": ""}}
        resp = _mock_resp(status=200, json_data=payload)
        crawler = SpokeoCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_no_solution_key_returns_not_found(self):
        """Line 56: solution dict has no response key -> html is '' -> found=False."""
        from modules.crawlers.spokeo import SpokeoCrawler

        payload = {"solution": {}}
        resp = _mock_resp(status=200, json_data=payload)
        crawler = SpokeoCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_no_cards_in_html_returns_not_found(self):
        """Lines 61-63: HTML has no matching card classes -> found=False."""
        from modules.crawlers.spokeo import SpokeoCrawler

        html = "<html><body><div class='unrelated'>stuff</div></body></html>"
        payload = {"solution": {"response": html}}
        resp = _mock_resp(status=200, json_data=payload)
        crawler = SpokeoCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """HTTP non-200 -> found=False."""
        from modules.crawlers.spokeo import SpokeoCrawler

        resp = _mock_resp(status=500)
        crawler = SpokeoCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_cards_found_via_person_card_selector(self):
        """Lines 61-63 branch: card-block empty but [class*='person-card'] matches."""
        from modules.crawlers.spokeo import SpokeoCrawler

        html = (
            "<html><body>"
            "<div class='person-card'>"
            "<h3 class='name'>John Doe</h3>"
            "<div class='address'>Dallas, TX</div>"
            "</div>"
            "</body></html>"
        )
        payload = {"solution": {"response": html}}
        resp = _mock_resp(status=200, json_data=payload)
        crawler = SpokeoCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is True
        assert result.data["count"] >= 1


# ---------------------------------------------------------------------------
# 5. spotify_public.py
#    line 40: HTTP failure -> found=False
#    lines 44-46: resp.json() raises -> found=False error=parse_error
# ---------------------------------------------------------------------------


class TestSpotifyPublicCrawler:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 40: status != 200 -> found=False."""
        from modules.crawlers.spotify_public import SpotifyPublicCrawler

        resp = _mock_resp(status=401)
        crawler = SpotifyPublicCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("someuser")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_none_response_returns_not_found(self):
        """Line 40: resp is None -> found=False."""
        from modules.crawlers.spotify_public import SpotifyPublicCrawler

        crawler = SpotifyPublicCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("someuser")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_parse_error(self):
        """Lines 44-46: resp.json() raises -> found=False, error=parse_error."""
        from modules.crawlers.spotify_public import SpotifyPublicCrawler

        resp = _mock_resp(status=200, text="not-json")
        crawler = SpotifyPublicCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("someuser")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_happy_path_returns_users(self):
        """Covers the found=True path."""
        from modules.crawlers.spotify_public import SpotifyPublicCrawler

        payload = {
            "users": {
                "items": [
                    {
                        "display_name": "Some User",
                        "id": "someuser123",
                        "uri": "spotify:user:someuser123",
                    }
                ]
            }
        }
        resp = _mock_resp(status=200, json_data=payload)
        crawler = SpotifyPublicCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("someuser")
        assert result.found is True
        assert result.data["count"] == 1


# ---------------------------------------------------------------------------
# 6. stackoverflow_profile.py
#    line 42: HTTP failure -> found=False
#    lines 46-48: resp.json() raises -> found=False error=parse_error
# ---------------------------------------------------------------------------


class TestStackOverflowProfileCrawler:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 42: status != 200 -> found=False."""
        from modules.crawlers.stackoverflow_profile import StackOverflowProfileCrawler

        resp = _mock_resp(status=429)
        crawler = StackOverflowProfileCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_none_response_returns_not_found(self):
        """Line 42: resp is None -> found=False."""
        from modules.crawlers.stackoverflow_profile import StackOverflowProfileCrawler

        crawler = StackOverflowProfileCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_parse_error(self):
        """Lines 46-48: resp.json() raises -> found=False, error=parse_error."""
        from modules.crawlers.stackoverflow_profile import StackOverflowProfileCrawler

        resp = _mock_resp(status=200, text="not-json")
        crawler = StackOverflowProfileCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_happy_path_returns_profiles(self):
        """Covers the found=True path with items."""
        from modules.crawlers.stackoverflow_profile import StackOverflowProfileCrawler

        payload = {
            "items": [
                {
                    "user_id": 12345,
                    "display_name": "John Doe",
                    "reputation": 9999,
                    "badge_counts": {"gold": 5, "silver": 20},
                    "link": "https://stackoverflow.com/users/12345",
                    "location": "Dallas, TX",
                    "website_url": "https://johndoe.dev",
                }
            ]
        }
        resp = _mock_resp(status=200, json_data=payload)
        crawler = StackOverflowProfileCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is True
        assert result.data["count"] == 1
        assert result.data["profiles"][0]["user_id"] == 12345


# ---------------------------------------------------------------------------
# 7. threads_profile.py
#    lines 40-42: resp.json() raises -> found=False error=parse_error
#    line 46: user dict is empty -> found=False
# ---------------------------------------------------------------------------


class TestThreadsProfileCrawler:
    @pytest.mark.asyncio
    async def test_json_parse_error_returns_parse_error(self):
        """Lines 40-42: resp.json() raises -> found=False, error=parse_error."""
        from modules.crawlers.threads_profile import ThreadsProfileCrawler

        resp = _mock_resp(status=200, text="not-json")
        crawler = ThreadsProfileCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("somehandle")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_empty_user_dict_returns_not_found(self):
        """Line 46: data.user is empty dict / falsy -> found=False."""
        from modules.crawlers.threads_profile import ThreadsProfileCrawler

        payload = {"data": {"user": {}}}
        resp = _mock_resp(status=200, json_data=payload)
        crawler = ThreadsProfileCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("somehandle")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_no_data_key_returns_not_found(self):
        """Line 46: payload has no 'data' key -> user is empty -> found=False."""
        from modules.crawlers.threads_profile import ThreadsProfileCrawler

        payload = {}
        resp = _mock_resp(status=200, json_data=payload)
        crawler = ThreadsProfileCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("somehandle")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """HTTP non-200 -> found=False."""
        from modules.crawlers.threads_profile import ThreadsProfileCrawler

        resp = _mock_resp(status=404)
        crawler = ThreadsProfileCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("somehandle")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_happy_path_returns_profile(self):
        """Covers the found=True path with a valid user."""
        from modules.crawlers.threads_profile import ThreadsProfileCrawler

        payload = {
            "data": {
                "user": {
                    "username": "testhandle",
                    "biography": "fitness crypto travel",
                    "edge_followed_by": {"count": 1234},
                }
            }
        }
        resp = _mock_resp(status=200, json_data=payload)
        crawler = ThreadsProfileCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("testhandle")
        assert result.found is True
        assert result.data["follower_count"] == 1234


# ---------------------------------------------------------------------------
# 8. txcourts.py
#    line 39: HTTP failure -> found=False
#    lines 61-63: fallback path — no table rows, but elements with class 'case-number' found
# ---------------------------------------------------------------------------


class TestTxCourtsCrawler:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 39: status != 200 -> found=False."""
        from modules.crawlers.txcourts import TxCourtsCrawler

        resp = _mock_resp(status=503)
        crawler = TxCourtsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_none_response_returns_not_found(self):
        """Line 39: resp is None -> found=False."""
        from modules.crawlers.txcourts import TxCourtsCrawler

        crawler = TxCourtsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_fallback_case_number_class_returns_found(self):
        """Lines 61-63: primary table empty, fallback finds .case-number elements."""
        from modules.crawlers.txcourts import TxCourtsCrawler

        html = (
            "<html><body>"
            "<span class='case-number'>2023-CR-00123</span>"
            "<span class='case-number'>2023-CR-00456</span>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        crawler = TxCourtsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is True
        assert result.data["count"] == 2
        assert result.data["cases"][0]["case_number"] == "2023-CR-00123"

    @pytest.mark.asyncio
    async def test_no_cases_returns_not_found(self):
        """Line 66: no table rows and no fallback matches -> found=False."""
        from modules.crawlers.txcourts import TxCourtsCrawler

        html = "<html><body><p>No records found.</p></body></html>"
        resp = _mock_resp(status=200, text=html)
        crawler = TxCourtsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Jane Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_table_rows_returns_found(self):
        """Primary table path: rows with >=2 cells parsed correctly."""
        from modules.crawlers.txcourts import TxCourtsCrawler

        html = (
            "<html><body>"
            "<table class='results'>"
            "<tr><td>Case Number</td><td>Party</td><td>Type</td></tr>"
            "<tr><td>2023-CR-00789</td><td>John Doe vs State</td><td>Criminal</td></tr>"
            "</table>"
            "</body></html>"
        )
        resp = _mock_resp(status=200, text=html)
        crawler = TxCourtsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Doe")
        assert result.found is True
        assert result.data["cases"][0]["case_number"] == "2023-CR-00789"


# ---------------------------------------------------------------------------
# 9. vin_decode_enhanced.py
#    line 41: HTTP failure -> found=False
#    lines 45-47: resp.json() raises -> found=False error=parse_error
#    line 51: results list is empty -> found=False
# ---------------------------------------------------------------------------


class TestVinDecodeEnhancedCrawler:
    @pytest.mark.asyncio
    async def test_http_failure_returns_not_found(self):
        """Line 41: status != 200 -> found=False."""
        from modules.crawlers.vin_decode_enhanced import VinDecodeEnhancedCrawler

        resp = _mock_resp(status=400)
        crawler = VinDecodeEnhancedCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1HGCM82633A004352")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_none_response_returns_not_found(self):
        """Line 41: resp is None -> found=False."""
        from modules.crawlers.vin_decode_enhanced import VinDecodeEnhancedCrawler

        crawler = VinDecodeEnhancedCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("1HGCM82633A004352")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_parse_error(self):
        """Lines 45-47: resp.json() raises -> found=False, error=parse_error."""
        from modules.crawlers.vin_decode_enhanced import VinDecodeEnhancedCrawler

        resp = _mock_resp(status=200, text="not-json-at-all")
        crawler = VinDecodeEnhancedCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1HGCM82633A004352")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_empty_results_returns_not_found(self):
        """Line 51: Results list is empty -> found=False."""
        from modules.crawlers.vin_decode_enhanced import VinDecodeEnhancedCrawler

        payload = {"Results": []}
        resp = _mock_resp(status=200, json_data=payload)
        crawler = VinDecodeEnhancedCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1HGCM82633A004352")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_fatal_error_code_with_no_make_returns_not_found(self):
        """Line 57: error_code in FATAL set and Make is empty -> found=False."""
        from modules.crawlers.vin_decode_enhanced import VinDecodeEnhancedCrawler

        payload = {"Results": [{"ErrorCode": "6", "Make": ""}]}
        resp = _mock_resp(status=200, json_data=payload)
        crawler = VinDecodeEnhancedCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("00000000000000000")
        assert result.found is False
        assert "vin_error_6" in result.data.get("error", "")

    @pytest.mark.asyncio
    async def test_happy_path_returns_vehicle_data(self):
        """Covers the full success path with a valid VIN decode result."""
        from modules.crawlers.vin_decode_enhanced import VinDecodeEnhancedCrawler

        payload = {
            "Results": [
                {
                    "ErrorCode": "0",
                    "Make": "HONDA",
                    "Model": "Accord",
                    "ModelYear": "2003",
                    "BodyClass": "Sedan",
                    "DriveType": "FWD",
                    "EngineCylinders": "4",
                    "FuelTypePrimary": "Gasoline",
                    "GVWR": "",
                    "PlantCountry": "USA",
                    "Series": "EX",
                    "Trim": "",
                    "VehicleType": "PASSENGER CAR",
                }
            ]
        }
        resp = _mock_resp(status=200, json_data=payload)
        crawler = VinDecodeEnhancedCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("1HGCM82633A004352")
        assert result.found is True
        assert result.data["make"] == "HONDA"
        assert result.data["model"] == "Accord"


# ---------------------------------------------------------------------------
# 10. interests_extractor.py
#    lines 55-56: no 'session' kwarg -> warning + found=False error=no_session
#    lines 102-104: followed_topics loop adds lowercase stripped topics
#    lines 108-110: liked_pages loop adds non-empty string pages
#    line 113: interests list is empty after all loops -> found=False
#    lines 139-140: profile is None -> creates new BehaviouralProfile and adds it
#    line 149: flush+commit success path
# ---------------------------------------------------------------------------


class TestInterestsExtractorCrawler:
    @pytest.mark.asyncio
    async def test_no_session_returns_no_session_error(self):
        """Lines 55-56: missing session kwarg -> found=False error=no_session."""
        from modules.crawlers.interests_extractor import InterestsExtractorCrawler

        crawler = InterestsExtractorCrawler()
        result = await crawler.scrape("some-person-id")
        assert result.found is False
        assert result.data.get("error") == "no_session"

    @pytest.mark.asyncio
    async def test_no_jobs_returns_not_found(self):
        """Line 76: no completed jobs for person -> found=False."""
        from modules.crawlers.interests_extractor import InterestsExtractorCrawler

        session = MagicMock()
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=execute_result)

        crawler = InterestsExtractorCrawler()

        # Patch sqlalchemy imports inside scrape
        with patch.dict(
            "sys.modules",
            {
                "sqlalchemy": MagicMock(),
                "shared.models.crawl": MagicMock(),
            },
        ):
            import sqlalchemy as sa_mock

            sa_mock.select = MagicMock(return_value=MagicMock())
            with patch(
                "modules.crawlers.interests_extractor.InterestsExtractorCrawler.scrape",
                wraps=crawler.scrape,
            ):
                # Use a simpler approach: mock the session.execute path
                pass

        # Direct approach: patch sqlalchemy.select and CrawlJob at module level
        mock_select = MagicMock()
        mock_crawljob = MagicMock()
        mock_crawljob.person_id = MagicMock()
        mock_crawljob.status = "done"

        with (
            patch("sqlalchemy.select", mock_select),
            patch("shared.models.crawl.CrawlJob", mock_crawljob),
        ):
            result = await crawler.scrape("550e8400-e29b-41d4-a716-446655440000", session=session)
        assert result.found is False

    @pytest.mark.asyncio
    async def test_followed_topics_extracted(self):
        """Lines 102-104: followed_topics are lowercased and appended to interests."""
        from modules.crawlers.interests_extractor import InterestsExtractorCrawler

        job = MagicMock()
        job.meta = {
            "platform": "threads",
            "result": {
                "followed_topics": ["Fitness", "CRYPTO", "Travel"],
            },
        }

        session = MagicMock()
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = [job]
        session.execute = AsyncMock(return_value=execute_result)
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        # Mock _persist_interests to avoid DB operations
        crawler = InterestsExtractorCrawler()
        with (
            patch.object(crawler, "_persist_interests", new=AsyncMock()),
            patch("sqlalchemy.select", MagicMock()),
            patch("shared.models.crawl.CrawlJob", MagicMock()),
        ):
            result = await crawler.scrape("550e8400-e29b-41d4-a716-446655440000", session=session)

        assert result.found is True
        assert "fitness" in result.data["interests"]
        assert "crypto" in result.data["interests"]
        assert "travel" in result.data["interests"]

    @pytest.mark.asyncio
    async def test_liked_pages_extracted(self):
        """Lines 108-110: liked_pages strings are lowercased and appended."""
        from modules.crawlers.interests_extractor import InterestsExtractorCrawler

        job = MagicMock()
        job.meta = {
            "platform": "facebook",
            "result": {
                "liked_pages": ["Tesla Motors", "SpaceX", ""],  # empty string ignored
            },
        }

        session = MagicMock()
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = [job]
        session.execute = AsyncMock(return_value=execute_result)

        crawler = InterestsExtractorCrawler()
        with (
            patch.object(crawler, "_persist_interests", new=AsyncMock()),
            patch("sqlalchemy.select", MagicMock()),
            patch("shared.models.crawl.CrawlJob", MagicMock()),
        ):
            result = await crawler.scrape("550e8400-e29b-41d4-a716-446655440000", session=session)

        assert result.found is True
        assert "tesla motors" in result.data["interests"]
        assert "spacex" in result.data["interests"]
        # Empty string should not be included
        assert "" not in result.data["interests"]

    @pytest.mark.asyncio
    async def test_empty_interests_returns_not_found(self):
        """Line 113: all jobs produce no extractable interests -> found=False."""
        from modules.crawlers.interests_extractor import InterestsExtractorCrawler

        job = MagicMock()
        # Job has a platform but empty result with no usable signals
        job.meta = {
            "platform": "unknown_platform",
            "result": {},
        }

        session = MagicMock()
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = [job]
        session.execute = AsyncMock(return_value=execute_result)

        crawler = InterestsExtractorCrawler()
        with (
            patch("sqlalchemy.select", MagicMock()),
            patch("shared.models.crawl.CrawlJob", MagicMock()),
        ):
            result = await crawler.scrape("550e8400-e29b-41d4-a716-446655440000", session=session)
        assert result.found is False

    @pytest.mark.asyncio
    async def test_persist_creates_new_profile_when_none(self):
        """Lines 139-140: profile is None -> new BehaviouralProfile created and added."""
        import uuid

        from modules.crawlers.interests_extractor import InterestsExtractorCrawler

        person_id = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        interests = ["crypto", "fitness"]

        session = MagicMock()
        # First execute: returns no existing profile
        no_profile_result = MagicMock()
        no_profile_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=no_profile_result)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        mock_profile_cls = MagicMock()
        mock_profile_instance = MagicMock()
        mock_profile_cls.return_value = mock_profile_instance

        crawler = InterestsExtractorCrawler()
        with (
            patch("sqlalchemy.select", MagicMock()),
            patch("shared.models.behavioural.BehaviouralProfile", mock_profile_cls),
        ):
            await crawler._persist_interests(person_id, interests, session)

        # Verify a new profile was instantiated and added to session
        mock_profile_cls.assert_called_once_with(person_id=person_id, interests=interests)
        session.add.assert_called_once_with(mock_profile_instance)

    @pytest.mark.asyncio
    async def test_persist_merges_existing_profile(self):
        """Line 143-145: existing profile -> interests are merged and deduplicated."""
        import uuid

        from modules.crawlers.interests_extractor import InterestsExtractorCrawler

        person_id = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        new_interests = ["crypto", "fitness", "travel"]

        existing_profile = MagicMock()
        existing_profile.interests = ["crypto", "gaming"]  # crypto duplicated

        session = MagicMock()
        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = existing_profile
        session.execute = AsyncMock(return_value=profile_result)
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        crawler = InterestsExtractorCrawler()
        with (
            patch("sqlalchemy.select", MagicMock()),
            patch("shared.models.behavioural.BehaviouralProfile", MagicMock()),
        ):
            await crawler._persist_interests(person_id, new_interests, session)

        merged = existing_profile.interests
        # crypto was already there, should not be duplicated
        assert merged.count("crypto") == 1
        assert "gaming" in merged
        assert "fitness" in merged
        assert "travel" in merged

    @pytest.mark.asyncio
    async def test_persist_flush_commit_called(self):
        """Line 149: flush and commit are called on success."""
        import uuid

        from modules.crawlers.interests_extractor import InterestsExtractorCrawler

        person_id = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        interests = ["gaming"]

        session = MagicMock()
        no_profile_result = MagicMock()
        no_profile_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=no_profile_result)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        crawler = InterestsExtractorCrawler()
        with (
            patch("sqlalchemy.select", MagicMock()),
            patch("shared.models.behavioural.BehaviouralProfile", MagicMock()),
        ):
            await crawler._persist_interests(person_id, interests, session)

        session.flush.assert_awaited_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_rollback_on_flush_exception(self):
        """Lines 150-155: flush raises -> rollback is called."""
        import uuid

        from modules.crawlers.interests_extractor import InterestsExtractorCrawler

        person_id = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        interests = ["stocks"]

        session = MagicMock()
        no_profile_result = MagicMock()
        no_profile_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=no_profile_result)
        session.add = MagicMock()
        session.flush = AsyncMock(side_effect=Exception("DB error"))
        session.rollback = AsyncMock()
        session.commit = AsyncMock()

        crawler = InterestsExtractorCrawler()
        with (
            patch("sqlalchemy.select", MagicMock()),
            patch("shared.models.behavioural.BehaviouralProfile", MagicMock()),
        ):
            # Should not raise
            await crawler._persist_interests(person_id, interests, session)

        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reddit_subreddit_extraction(self):
        """Lines 87-90: Reddit platform extracts subreddit names from recent_posts."""
        from modules.crawlers.interests_extractor import InterestsExtractorCrawler

        job = MagicMock()
        job.meta = {
            "platform": "reddit",
            "result": {
                "recent_posts": [
                    {"subreddit": "personalfinance"},
                    {"subreddit": "investing"},
                    {"subreddit": "personalfinance"},  # duplicate — should not re-add
                ],
            },
        }

        session = MagicMock()
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = [job]
        session.execute = AsyncMock(return_value=execute_result)

        crawler = InterestsExtractorCrawler()
        with (
            patch.object(crawler, "_persist_interests", new=AsyncMock()),
            patch("sqlalchemy.select", MagicMock()),
            patch("shared.models.crawl.CrawlJob", MagicMock()),
        ):
            result = await crawler.scrape("550e8400-e29b-41d4-a716-446655440000", session=session)

        assert result.found is True
        interests = result.data["interests"]
        assert interests.count("personalfinance") == 1
        assert "investing" in interests

    @pytest.mark.asyncio
    async def test_bio_keyword_extraction(self):
        """Lines 93-98: bio text matched against _BIO_INTEREST_KEYWORDS."""
        from modules.crawlers.interests_extractor import InterestsExtractorCrawler

        job = MagicMock()
        job.meta = {
            "platform": "twitter",
            "result": {
                "bio": "I love crypto, gaming, and real estate investing. Entrepreneur at heart.",
            },
        }

        session = MagicMock()
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = [job]
        session.execute = AsyncMock(return_value=execute_result)

        crawler = InterestsExtractorCrawler()
        with (
            patch.object(crawler, "_persist_interests", new=AsyncMock()),
            patch("sqlalchemy.select", MagicMock()),
            patch("shared.models.crawl.CrawlJob", MagicMock()),
        ):
            result = await crawler.scrape("550e8400-e29b-41d4-a716-446655440000", session=session)

        assert result.found is True
        interests = result.data["interests"]
        assert "crypto" in interests
        assert "gaming" in interests
        assert "real estate" in interests
        assert "entrepreneur" in interests
