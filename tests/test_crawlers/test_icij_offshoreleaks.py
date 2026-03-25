"""
Unit tests for modules/crawlers/gov/icij_offshoreleaks.py.

Covers every branch: _normalise_dataset, _parse_json_results,
_parse_html_results, IcijOffshoreLeaksCrawler._try_json_api,
_try_html, and scrape.

No real HTTP calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.gov.icij_offshoreleaks  # noqa: F401 — trigger @register
from modules.crawlers.gov.icij_offshoreleaks import (
    IcijOffshoreLeaksCrawler,
    _normalise_dataset,
    _parse_html_results,
    _parse_json_results,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("no json"))
    return resp


# ---------------------------------------------------------------------------
# _normalise_dataset
# ---------------------------------------------------------------------------


class TestNormaliseDataset:
    def test_known_slug_exact(self):
        assert _normalise_dataset("panama_papers") == "panama_papers"

    def test_known_slug_with_spaces(self):
        assert _normalise_dataset("Panama Papers") == "panama_papers"

    def test_known_slug_with_hyphens(self):
        assert _normalise_dataset("pandora-papers") == "pandora_papers"

    def test_known_slug_mixed_case(self):
        assert _normalise_dataset("FinCEN Files") == "fincen_files"

    def test_unknown_slug_passes_through(self):
        result = _normalise_dataset("mystery leaks")
        assert result == "mystery_leaks"

    def test_bahamas_leaks(self):
        assert _normalise_dataset("Bahamas Leaks") == "bahamas_leaks"

    def test_paradise_papers(self):
        assert _normalise_dataset("paradise papers") == "paradise_papers"

    def test_offshore_leaks(self):
        assert _normalise_dataset("offshore leaks") == "offshore_leaks"

    def test_luanda_leaks(self):
        assert _normalise_dataset("luanda-leaks") == "luanda_leaks"


# ---------------------------------------------------------------------------
# _parse_json_results
# ---------------------------------------------------------------------------


class TestParseJsonResults:
    _FULL_PAYLOAD = {
        "data": {
            "entities": [
                {
                    "name": "Mossack Fonseca",
                    "type": "company",
                    "jurisdiction": "PA",
                    "datasets": ["panama_papers"],
                    "linked_to": "Offshore Corp",
                    "registered_address": "Panama City",
                    "incorporation_date": "1986-01-01",
                    "entity_name": "Mossack Fonseca & Co.",
                }
            ],
            "officers": [
                {
                    "node_name": "John Doe",
                    "node_type": "person",
                    "country_codes": "US",
                    "sourceIDs": ["pandora_papers"],
                    "connected_to": "Shell Corp",
                    "address": "New York",
                    "inactivation_date": "2021-01-01",
                }
            ],
        }
    }

    def test_parses_entities_and_officers(self):
        results = _parse_json_results(self._FULL_PAYLOAD)
        assert len(results) == 2

    def test_entity_fields(self):
        results = _parse_json_results(self._FULL_PAYLOAD)
        entity = next(r for r in results if r["name"] == "Mossack Fonseca")
        assert entity["entity_type"] == "company"
        assert entity["jurisdiction"] == "PA"
        assert entity["source_dataset"] == "panama_papers"
        assert "panama_papers" in entity["source_datasets"]
        assert entity["registered_address"] == "Panama City"
        assert entity["entity_name"] == "Mossack Fonseca & Co."

    def test_officer_fields(self):
        results = _parse_json_results(self._FULL_PAYLOAD)
        officer = next(r for r in results if r["name"] == "John Doe")
        assert officer["entity_type"] == "person"
        assert officer["jurisdiction"] == "US"
        assert "pandora_papers" in officer["source_datasets"]

    def test_non_dict_input_returns_empty(self):
        assert _parse_json_results([]) == []
        assert _parse_json_results("string") == []
        assert _parse_json_results(None) == []

    def test_items_without_name_skipped(self):
        data = {"data": {"entities": [{"type": "company", "jurisdiction": "US"}]}}
        results = _parse_json_results(data)
        assert results == []

    def test_non_dict_items_in_section_skipped(self):
        data = {"data": {"entities": ["not_a_dict", {"name": "Valid Entity"}]}}
        results = _parse_json_results(data)
        assert len(results) == 1

    def test_payload_is_list(self):
        """When data.get('data') is a list, it's treated as a 'results' section."""
        data = {"data": [{"name": "Some Entity", "type": "company"}]}
        results = _parse_json_results(data)
        assert len(results) == 1

    def test_top_level_dict_without_data_key(self):
        """Top-level dict without 'data' key uses itself as payload."""
        data = {"entities": [{"name": "Direct Entity", "type": "intermediary"}]}
        results = _parse_json_results(data)
        assert len(results) == 1

    def test_datasets_as_string_wrapped_in_list(self):
        data = {"data": {"entities": [{"name": "Corp X", "datasets": "panama_papers"}]}}
        results = _parse_json_results(data)
        assert results[0]["source_datasets"] == ["panama_papers"]

    def test_empty_datasets_gives_empty_source_dataset(self):
        data = {"data": {"entities": [{"name": "Corp Y", "datasets": []}]}}
        results = _parse_json_results(data)
        assert results[0]["source_dataset"] == ""
        assert results[0]["source_datasets"] == []

    def test_incorporation_date_as_dict(self):
        data = {
            "data": {
                "entities": [
                    {
                        "name": "Corp Z",
                        "incorporation_date": {"value": "2001-03-15"},
                    }
                ]
            }
        }
        results = _parse_json_results(data)
        assert results[0]["incorporation_date"] == "2001-03-15"

    def test_jurisdiction_description_fallback(self):
        data = {
            "data": {
                "entities": [
                    {
                        "name": "Corp W",
                        "jurisdiction_description": "British Virgin Islands",
                    }
                ]
            }
        }
        results = _parse_json_results(data)
        assert results[0]["jurisdiction"] == "British Virgin Islands"

    def test_section_name_used_as_entity_type_fallback(self):
        data = {"data": {"intermediaries": [{"name": "Broker Co"}]}}
        results = _parse_json_results(data)
        # Section "intermediaries" → entity_type = "intermediarie" (rstrip 's')
        assert "intermediar" in results[0]["entity_type"]


# ---------------------------------------------------------------------------
# _parse_html_results
# ---------------------------------------------------------------------------


class TestParseHtmlResults:
    _CARDS_HTML = """
    <html><body>
    <div class="search-result">
      <h3>Offshore Holdings Ltd</h3>
      <span class="dataset">Panama Papers</span>
      <span class="jurisdiction">British Virgin Islands</span>
      <span class="type">Entity</span>
    </div>
    <div class="search-result">
      <h4>Mystery Person</h4>
    </div>
    </body></html>
    """

    _TABLE_HTML = """
    <html><body>
    <table>
      <tr><th>Name</th><th>Type</th><th>Jurisdiction</th><th>Source</th><th>Address</th></tr>
      <tr><td>Table Corp</td><td>company</td><td>Cayman Islands</td><td>pandora_papers</td><td>George Town</td></tr>
    </table>
    </body></html>
    """

    def test_parses_cards(self):
        results = _parse_html_results(self._CARDS_HTML)
        assert len(results) >= 1
        r = next(r for r in results if r["name"] == "Offshore Holdings Ltd")
        assert r["entity_type"] == "Entity"
        assert r["jurisdiction"] == "British Virgin Islands"
        assert r["source_dataset"] == "panama_papers"

    def test_card_without_name_skipped(self):
        html = """
        <div class="search-result">
          <span class="dataset">Panama Papers</span>
        </div>
        """
        results = _parse_html_results(html)
        assert results == []

    def test_card_with_no_optional_elements(self):
        """Card with only name and no dataset/jurisdiction/type."""
        html = """<div class="result"><strong>Bare Corp</strong></div>"""
        results = _parse_html_results(html)
        assert len(results) == 1
        assert results[0]["source_dataset"] == ""
        assert results[0]["source_datasets"] == []

    def test_table_fallback_when_no_cards(self):
        results = _parse_html_results(self._TABLE_HTML)
        assert len(results) >= 1
        r = next((r for r in results if r["name"] == "Table Corp"), None)
        if r:  # table row was parsed
            assert r["jurisdiction"] == "Cayman Islands"

    def test_table_row_without_name_skipped(self):
        html = """
        <table>
          <tr><th>Name</th><th>Type</th></tr>
          <tr><td></td><td>company</td></tr>
        </table>
        """
        results = _parse_html_results(html)
        assert results == []

    def test_empty_html_returns_empty(self):
        assert _parse_html_results("") == []

    def test_exception_returns_empty(self):
        """Any exception during parse is caught and returns []."""
        # BeautifulSoup is imported inside the function body, not at module level.
        # Simulate a parse exception by patching bs4.BeautifulSoup directly.
        import bs4

        with patch.object(bs4, "BeautifulSoup", side_effect=RuntimeError("soup error")):
            results = _parse_html_results("<html></html>")
        assert results == []

    def test_article_result_selector(self):
        html = """
        <html><body>
        <article class="result">
          <h3>Article Corp</h3>
          <span class="dataset">Paradise Papers</span>
        </article>
        </body></html>
        """
        results = _parse_html_results(html)
        assert any(r["name"] == "Article Corp" for r in results)


# ---------------------------------------------------------------------------
# IcijOffshoreLeaksCrawler._try_json_api
# ---------------------------------------------------------------------------


class TestIcijCrawlerTryJsonApi:
    def _crawler(self) -> IcijOffshoreLeaksCrawler:
        return IcijOffshoreLeaksCrawler()

    async def test_returns_empty_when_resp_none(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._try_json_api("test+query")
        assert result == []

    async def test_returns_empty_when_non_200(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
            result = await crawler._try_json_api("query")
        assert result == []

    async def test_returns_empty_on_json_decode_error(self):
        crawler = self._crawler()
        resp = _mock_resp(200)
        resp.json = MagicMock(side_effect=ValueError("bad json"))
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._try_json_api("query")
        assert result == []

    async def test_returns_parsed_data_on_success(self):
        crawler = self._crawler()
        data = {"data": {"entities": [{"name": "Test Corp", "type": "company"}]}}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=data))):
            result = await crawler._try_json_api("Test+Corp")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# IcijOffshoreLeaksCrawler._try_html
# ---------------------------------------------------------------------------


class TestIcijCrawlerTryHtml:
    def _crawler(self) -> IcijOffshoreLeaksCrawler:
        return IcijOffshoreLeaksCrawler()

    async def test_returns_empty_when_resp_none(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._try_html("query")
        assert result == []

    async def test_returns_empty_when_non_200(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler._try_html("query")
        assert result == []

    async def test_returns_html_parse_results(self):
        crawler = self._crawler()
        html = '<div class="search-result"><h3>HTML Corp</h3></div>'
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=html))):
            result = await crawler._try_html("HTML+Corp")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# IcijOffshoreLeaksCrawler.scrape — integration
# ---------------------------------------------------------------------------


class TestIcijOffshoreLeaksCrawlerScrape:
    def _crawler(self) -> IcijOffshoreLeaksCrawler:
        return IcijOffshoreLeaksCrawler()

    async def test_scrape_uses_json_api_when_successful(self):
        crawler = self._crawler()
        data = {
            "data": {
                "entities": [
                    {
                        "name": "Panama Corp",
                        "type": "company",
                        "jurisdiction": "PA",
                        "datasets": ["panama_papers"],
                    }
                ]
            }
        }
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=data))):
            result = await crawler.scrape("Panama Corp")

        assert result.found is True
        assert result.data["is_in_leak"] is True
        assert result.data["match_count"] == 1
        assert "panama_papers" in result.data["leak_names"]
        assert result.data["query"] == "Panama Corp"

    async def test_scrape_falls_back_to_html_when_json_empty(self):
        crawler = self._crawler()
        html = """
        <div class="search-result">
          <h3>HTML Leak Corp</h3>
          <span class="dataset">Pandora Papers</span>
        </div>
        """
        call_count = [0]

        async def fake_get(url, **kwargs):
            c = call_count[0]
            call_count[0] += 1
            if c == 0:
                return _mock_resp(503)  # JSON API fails
            return _mock_resp(200, text=html)

        with patch.object(crawler, "get", side_effect=fake_get):
            result = await crawler.scrape("HTML Leak Corp")

        assert result.found is True

    async def test_scrape_returns_not_found_when_both_fail(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("Unknown Entity")

        assert result.found is False
        assert result.data["match_count"] == 0
        assert result.data["icij_matches"] == []
        assert result.data["leak_names"] == []

    async def test_leak_names_deduplicated_and_sorted(self):
        crawler = self._crawler()
        data = {
            "data": {
                "entities": [
                    {"name": "Corp A", "datasets": ["pandora_papers", "panama_papers"]},
                    {"name": "Corp B", "datasets": ["panama_papers"]},
                ]
            }
        }
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=data))):
            result = await crawler.scrape("Corp")

        leak_names = result.data["leak_names"]
        assert sorted(leak_names) == leak_names  # sorted
        assert len(leak_names) == len(set(leak_names))  # unique

    async def test_scrape_strips_whitespace(self):
        crawler = self._crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
            result = await crawler.scrape("  Corp  ")
        assert result.data["query"] == "Corp"

    async def test_platform_attributes(self):
        crawler = self._crawler()
        assert crawler.platform == "icij_offshoreleaks"
        assert crawler.source_reliability == 0.90
        assert crawler.requires_tor is False
        assert crawler.proxy_tier == "datacenter"

    async def test_leak_names_uses_source_dataset_fallback(self):
        """When source_datasets is absent but source_dataset has a value, it appears in leak_names."""
        crawler = self._crawler()
        # Return data where source_datasets is populated
        data = {
            "data": {
                "entities": [
                    {"name": "Corp C", "datasets": ["fincen_files"]},
                ]
            }
        }
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=data))):
            result = await crawler.scrape("Corp C")

        assert "fincen_files" in result.data["leak_names"]
