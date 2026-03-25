"""
test_people_intel_wave4.py — Branch-coverage gap tests (wave 4).

Crawlers covered:
  people_intelx    — lines 38, 41-152
  people_phonebook — lines 42-98

Each test targets specific uncovered lines identified in the coverage report.
All external I/O is mocked; no real network calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ===========================================================================
# people_intelx.py
# Lines: 38 (_api_key), 41-152 (scrape — all branches)
# ===========================================================================


class TestIntelXApiKey:
    """Line 38: _api_key() reads INTELX_API_KEY from environment."""

    def _make(self):
        from modules.crawlers.people_intelx import IntelXCrawler

        return IntelXCrawler()

    def test_api_key_present(self):
        crawler = self._make()
        with patch.dict("os.environ", {"INTELX_API_KEY": "testkey123"}):
            assert crawler._api_key() == "testkey123"

    def test_api_key_absent(self):
        crawler = self._make()
        with patch.dict("os.environ", {}, clear=True):
            assert crawler._api_key() is None


class TestIntelXScrape:
    """Lines 41-152: scrape() — all branches."""

    def _make(self):
        from modules.crawlers.people_intelx import IntelXCrawler

        return IntelXCrawler()

    # Lines 41-49: no API key → found=False
    @pytest.mark.asyncio
    async def test_scrape_no_api_key(self):
        crawler = self._make()
        with patch.dict("os.environ", {}, clear=True):
            result = await crawler.scrape("john.doe@example.com")
        assert result.found is False
        assert result.error == "INTELX_API_KEY not set"

    # Lines 57-71: self.post() raises an exception (step 1)
    @pytest.mark.asyncio
    async def test_scrape_post_raises(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(crawler, "post", new=AsyncMock(side_effect=ConnectionError("refused"))),
        ):
            result = await crawler.scrape("target@example.com")
        assert result.found is False
        assert result.error == "refused"

    # Lines 73-81: search_resp is None
    @pytest.mark.asyncio
    async def test_scrape_search_resp_none(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(crawler, "post", new=AsyncMock(return_value=None)),
        ):
            result = await crawler.scrape("target@example.com")
        assert result.found is False
        assert result.error == "search_http_none"

    # Lines 73-81: search_resp non-200/201 status (e.g. 403)
    @pytest.mark.asyncio
    async def test_scrape_search_resp_403(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(403))),
        ):
            result = await crawler.scrape("target@example.com")
        assert result.found is False
        assert result.error == "search_http_403"

    # Lines 73-81: search_resp status 429
    @pytest.mark.asyncio
    async def test_scrape_search_resp_429(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(429))),
        ):
            result = await crawler.scrape("target@example.com")
        assert result.found is False
        assert result.error == "search_http_429"

    # Lines 83-92: search_resp.json() raises → invalid_search_json
    @pytest.mark.asyncio
    async def test_scrape_search_invalid_json(self):
        crawler = self._make()
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200))),
        ):
            result = await crawler.scrape("target@example.com")
        assert result.found is False
        assert result.error == "invalid_search_json"

    # Lines 94-102: search_data has no 'id' → no_search_id
    @pytest.mark.asyncio
    async def test_scrape_no_search_id(self):
        crawler = self._make()
        search_data = {"status": "ok"}  # no 'id' key
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(
                crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=search_data))
            ),
        ):
            result = await crawler.scrape("target@example.com")
        assert result.found is False
        assert result.error == "no_search_id"

    # Lines 94-102: id is empty string → no_search_id
    @pytest.mark.asyncio
    async def test_scrape_empty_search_id(self):
        crawler = self._make()
        search_data = {"id": ""}
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(
                crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=search_data))
            ),
        ):
            result = await crawler.scrape("target@example.com")
        assert result.found is False
        assert result.error == "no_search_id"

    # Lines 105-117: self.get() raises (step 2 fetch)
    @pytest.mark.asyncio
    async def test_scrape_results_get_raises(self):
        crawler = self._make()
        search_data = {"id": "abc-search-id-123"}
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(
                crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=search_data))
            ),
            patch.object(crawler, "get", new=AsyncMock(side_effect=TimeoutError("timeout"))),
        ):
            result = await crawler.scrape("target@example.com")
        assert result.found is False
        assert result.error == "timeout"

    # Lines 119-127: results_resp is None
    @pytest.mark.asyncio
    async def test_scrape_results_resp_none(self):
        crawler = self._make()
        search_data = {"id": "abc-search-id-123"}
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(
                crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=search_data))
            ),
            patch.object(crawler, "get", new=AsyncMock(return_value=None)),
        ):
            result = await crawler.scrape("target@example.com")
        assert result.found is False
        assert result.error == "results_http_none"

    # Lines 119-127: results_resp non-200
    @pytest.mark.asyncio
    async def test_scrape_results_resp_non200(self):
        crawler = self._make()
        search_data = {"id": "abc-search-id-123"}
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(
                crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=search_data))
            ),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))),
        ):
            result = await crawler.scrape("target@example.com")
        assert result.found is False
        assert result.error == "results_http_503"

    # Lines 129-138: results_resp.json() raises → invalid_results_json
    @pytest.mark.asyncio
    async def test_scrape_results_invalid_json(self):
        crawler = self._make()
        search_data = {"id": "abc-search-id-123"}
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(
                crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=search_data))
            ),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200))),
        ):
            result = await crawler.scrape("target@example.com")
        assert result.found is False
        assert result.error == "invalid_results_json"

    # Lines 140-158: 200 with empty records → found=False
    @pytest.mark.asyncio
    async def test_scrape_empty_records(self):
        crawler = self._make()
        search_data = {"id": "abc-search-id-123"}
        results_data = {"records": [], "total": 0}
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(
                crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=search_data))
            ),
            patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=results_data))
            ),
        ):
            result = await crawler.scrape("nobody@example.com")
        assert result.found is False
        assert result.data["hits"] == []
        assert result.data["total"] == 0

    # Lines 140-158: 200 with populated records → found=True
    @pytest.mark.asyncio
    async def test_scrape_success_with_records(self):
        crawler = self._make()
        search_data = {"id": "xyz-search-999"}
        results_data = {
            "records": [
                {
                    "name": "leaked-doc.txt",
                    "type": "leaks",
                    "date": "2022-05-01T00:00:00Z",
                    "bucket": "darkweb",
                },
                {
                    "name": "telegram-dump.csv",
                    "type": "telegram",
                    "date": "2023-01-15T00:00:00Z",
                    "bucket": "telegram",
                },
            ],
            "total": 2,
        }
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(
                crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=search_data))
            ),
            patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=results_data))
            ),
        ):
            result = await crawler.scrape("john.doe@example.com")
        assert result.found is True
        assert len(result.data["hits"]) == 2
        assert result.data["hits"][0]["name"] == "leaked-doc.txt"
        assert result.data["hits"][0]["bucket"] == "darkweb"
        assert result.data["hits"][1]["type"] == "telegram"
        assert result.data["total"] == 2

    # Lines 140-158: records key absent → treated as empty
    @pytest.mark.asyncio
    async def test_scrape_no_records_key(self):
        crawler = self._make()
        search_data = {"id": "abc-search-id-123"}
        results_data = {"total": 0}  # no 'records' key
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(
                crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=search_data))
            ),
            patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=results_data))
            ),
        ):
            result = await crawler.scrape("nobody@example.com")
        assert result.found is False
        assert result.data["hits"] == []

    # search_resp 201 is also accepted
    @pytest.mark.asyncio
    async def test_scrape_search_resp_201_accepted(self):
        crawler = self._make()
        search_data = {"id": "created-id-201"}
        results_data = {"records": [], "total": 0}
        with (
            patch.dict("os.environ", {"INTELX_API_KEY": "k"}),
            patch.object(
                crawler, "post", new=AsyncMock(return_value=_mock_resp(201, json_data=search_data))
            ),
            patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=results_data))
            ),
        ):
            result = await crawler.scrape("target@example.com")
        # 201 is valid — should proceed past the status check
        assert result.error is None or result.error not in ("search_http_201",)
        assert result.found is False  # no records


# ===========================================================================
# people_phonebook.py
# Lines: 42-98 (entire scrape method)
# ===========================================================================


class TestPhonebookScrape:
    def _make(self):
        from modules.crawlers.people_phonebook import PhonebookCrawler

        return PhonebookCrawler()

    # Lines 50-59: self.post() raises an exception
    @pytest.mark.asyncio
    async def test_scrape_post_raises(self):
        crawler = self._make()
        with patch.object(
            crawler, "post", new=AsyncMock(side_effect=RuntimeError("connection refused"))
        ):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error == "connection refused"

    # Lines 61-69: response is None
    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make()
        with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error == "http_none"

    # Lines 61-69: non-200 status (e.g. 503)
    @pytest.mark.asyncio
    async def test_scrape_non200(self):
        crawler = self._make()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error == "http_503"

    # Lines 61-69: 403 forbidden
    @pytest.mark.asyncio
    async def test_scrape_403(self):
        crawler = self._make()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(403))):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "http_403"

    # Lines 71-80: response.json() raises → invalid_json
    @pytest.mark.asyncio
    async def test_scrape_invalid_json(self):
        crawler = self._make()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200))):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error == "invalid_json"

    # Lines 82-106: 200 with empty hits → found=False
    @pytest.mark.asyncio
    async def test_scrape_empty_hits(self):
        crawler = self._make()
        json_data = {"hits": []}
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))
        ):
            result = await crawler.scrape("nobody@example.com")
        assert result.found is False
        assert result.data["emails"] == []
        assert result.data["urls"] == []
        assert result.data["subdomains"] == []
        assert result.data["total_hits"] == 0

    # Lines 82-106: hits with email values
    @pytest.mark.asyncio
    async def test_scrape_email_hits(self):
        crawler = self._make()
        json_data = {
            "hits": [
                {"value": "john.smith@example.com"},
                {"value": "jsmith@corp.org"},
                {"value": "UPPER@Example.COM"},  # should be lowercased
            ]
        }
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))
        ):
            result = await crawler.scrape("john smith")
        assert result.found is True
        assert "john.smith@example.com" in result.data["emails"]
        assert "jsmith@corp.org" in result.data["emails"]
        assert "upper@example.com" in result.data["emails"]
        assert result.data["urls"] == []
        assert result.data["subdomains"] == []

    # Lines 82-106: hits with URL values
    @pytest.mark.asyncio
    async def test_scrape_url_hits(self):
        crawler = self._make()
        json_data = {
            "hits": [
                {"value": "https://example.com/page"},
                {"value": "http://sub.example.com"},
            ]
        }
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is True
        assert "https://example.com/page" in result.data["urls"]
        assert "http://sub.example.com" in result.data["urls"]
        assert result.data["emails"] == []
        assert result.data["subdomains"] == []

    # Lines 82-106: hits with subdomain values (no @ and no http prefix)
    @pytest.mark.asyncio
    async def test_scrape_subdomain_hits(self):
        crawler = self._make()
        json_data = {
            "hits": [
                {"value": "mail.example.com"},
                {"value": "vpn.example.com"},
            ]
        }
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is True
        assert "mail.example.com" in result.data["subdomains"]
        assert "vpn.example.com" in result.data["subdomains"]
        assert result.data["emails"] == []
        assert result.data["urls"] == []

    # Lines 82-106: mixed hits (email + url + subdomain)
    @pytest.mark.asyncio
    async def test_scrape_mixed_hits(self):
        crawler = self._make()
        json_data = {
            "hits": [
                {"value": "admin@example.com"},
                {"value": "https://example.com"},
                {"value": "api.example.com"},
            ]
        }
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is True
        assert len(result.data["emails"]) == 1
        assert len(result.data["urls"]) == 1
        assert len(result.data["subdomains"]) == 1
        assert result.data["total_hits"] == 3

    # Lines 82-106: hit is a string (not dict) → str(item) path
    @pytest.mark.asyncio
    async def test_scrape_hits_as_strings(self):
        crawler = self._make()
        json_data = {
            "hits": [
                "mail.example.com",
                "https://example.com",
            ]
        }
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is True
        # string items without "@" and "https" → subdomains or urls
        assert result.data["total_hits"] == 2

    # Lines 82: data is a list (not dict) → hits defaults to []
    @pytest.mark.asyncio
    async def test_scrape_response_is_list_not_dict(self):
        crawler = self._make()
        json_data = ["item1", "item2"]  # a list, not a dict
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.data["emails"] == []

    # verify query uses stripped identifier
    @pytest.mark.asyncio
    async def test_scrape_identifier_is_stripped(self):
        crawler = self._make()
        json_data = {"hits": []}
        captured_payloads = []

        async def capturing_post(url, **kwargs):
            captured_payloads.append(kwargs.get("json", {}))
            return _mock_resp(200, json_data=json_data)

        with patch.object(crawler, "post", new=capturing_post):
            await crawler.scrape("  John Smith  ")

        assert len(captured_payloads) == 1
        assert captured_payloads[0]["term"] == "John Smith"

    # email with invalid format (has @ but fails regex) → goes to subdomains
    @pytest.mark.asyncio
    async def test_scrape_at_sign_invalid_email_to_subdomains(self):
        crawler = self._make()
        # Has @ but doesn't match the email regex (no TLD)
        json_data = {
            "hits": [
                {"value": "notavalidemail@"},
            ]
        }
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, json_data=json_data))
        ):
            result = await crawler.scrape("example.com")
        # "notavalidemail@" has @ but fails email_re.match → goes to subdomains
        assert result.found is True
        assert "notavalidemail@" in result.data["subdomains"]
        assert result.data["emails"] == []
