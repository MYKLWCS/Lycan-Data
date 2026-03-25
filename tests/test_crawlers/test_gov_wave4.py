"""
Gov crawler wave-4 coverage tests.

Targets lines not yet exercised in gov_epa, gov_fda, gov_finra, gov_fred,
gov_grants, gov_nmls, gov_osha, gov_sam, gov_uspto_patents, gov_worldbank,
gov_gleif.

All HTTP calls are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("no json"))
    return resp


def _get_error(result) -> str | None:
    return result.error or (result.data.get("error") if result.data else None)


# ===========================================================================
# gov_epa — line 44: `if not isinstance(item, dict): continue`
# ===========================================================================

import modules.crawlers.gov_epa  # noqa: F401 — trigger @register
from modules.crawlers.gov_epa import EpaCrawler, _parse_facilities


class TestGovEpaLine44:
    """Test _parse_facilities when items list contains non-dict entries."""

    def test_parse_facilities_skips_non_dict_items(self):
        data = {
            "Results": {
                "Results": [
                    "not_a_dict",
                    42,
                    {"CWPName": "Test Facility", "CWPCity": "Austin"},
                ]
            }
        }
        results = _parse_facilities(data)
        assert len(results) == 1
        assert results[0]["CWPName"] == "Test Facility"

    def test_parse_facilities_flat_list_key(self):
        """Exercises the fallback flat-list branch in _parse_facilities."""
        data = {
            "Facilities": [
                {"CWPName": "Facility A", "CWPState": "TX"},
            ]
        }
        results = _parse_facilities(data)
        assert len(results) == 1
        assert results[0]["CWPName"] == "Facility A"

    @pytest.mark.asyncio
    async def test_epa_scrape_json_parse_error(self):
        crawler = EpaCrawler()
        bad = MagicMock()
        bad.status_code = 200
        bad.json = MagicMock(side_effect=ValueError("bad json"))
        with patch.object(crawler, "get", new=AsyncMock(return_value=bad)):
            result = await crawler.scrape("Test Corp")
        assert _get_error(result) is not None


# ===========================================================================
# gov_fda — lines 121-122: recalls JSON parse error
# ===========================================================================

import modules.crawlers.gov_fda  # noqa: F401
from modules.crawlers.gov_fda import FdaCrawler


class TestGovFdaLines121_122:
    @pytest.mark.asyncio
    async def test_fda_recalls_json_error_logs_warning(self):
        """Recalls response has invalid JSON — exercises line 121-122."""
        crawler = FdaCrawler()
        events_resp = _mock_resp(200, json_data={"results": []})
        recalls_resp = MagicMock()
        recalls_resp.status_code = 200
        recalls_resp.json = MagicMock(side_effect=ValueError("bad"))

        async def fake_get(url, **kwargs):
            if "event" in url:
                return events_resp
            return recalls_resp

        with patch.object(crawler, "get", side_effect=fake_get):
            result = await crawler.scrape("aspirin")
        # Should return normally (events were fine, recalls failed silently)
        assert result is not None

    @pytest.mark.asyncio
    async def test_fda_events_json_error_logs_warning(self):
        """Events response has invalid JSON — exercises line 115-116."""
        crawler = FdaCrawler()
        events_resp = MagicMock()
        events_resp.status_code = 200
        events_resp.json = MagicMock(side_effect=ValueError("bad"))
        recalls_resp = _mock_resp(200, json_data={"results": []})

        async def fake_get(url, **kwargs):
            if "event" in url:
                return events_resp
            return recalls_resp

        with patch.object(crawler, "get", side_effect=fake_get):
            result = await crawler.scrape("aspirin")
        assert result is not None


# ===========================================================================
# gov_finra — line 43: `hit_list = hits or []`
# ===========================================================================

import modules.crawlers.gov_finra  # noqa: F401
from modules.crawlers.gov_finra import FinraCrawler, _parse_brokers


class TestGovFinraLine43:
    def test_parse_brokers_hits_is_list(self):
        """When 'hits' is already a list (not dict), uses `hits or []`."""
        data = {"hits": [{"_source": {"ind_firstname": "John", "ind_lastname": "Doe"}}]}
        result = _parse_brokers(data)
        assert len(result) == 1
        assert result[0]["ind_firstname"] == "John"

    def test_parse_brokers_hits_is_none(self):
        """hits is None → hit_list = [] → empty result."""
        data = {"hits": None}
        result = _parse_brokers(data)
        assert result == []

    def test_parse_brokers_non_dict_item_skipped(self):
        """Non-dict items in hit_list are skipped."""
        data = {"hits": {"hits": ["not_a_dict", {"_source": {"ind_source_id": "x"}}]}}
        result = _parse_brokers(data)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_finra_rate_limited(self):
        crawler = FinraCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
            result = await crawler.scrape("John Smith")
        assert _get_error(result) == "rate_limited"


# ===========================================================================
# gov_fred — line 35: `if not isinstance(item, dict): continue`
# ===========================================================================

import modules.crawlers.gov_fred  # noqa: F401
from modules.crawlers.gov_fred import FredCrawler, _parse_series


class TestGovFredLine35:
    def test_parse_series_skips_non_dict(self):
        data = {"seriess": ["not_dict", {"id": "GDP", "title": "Gross Domestic Product"}]}
        result = _parse_series(data)
        assert len(result) == 1
        assert result[0]["id"] == "GDP"

    @pytest.mark.asyncio
    async def test_fred_rate_limited(self):
        crawler = FredCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
            result = await crawler.scrape("unemployment")
        assert _get_error(result) == "rate_limited"


# ===========================================================================
# gov_grants — line 36: `if not isinstance(item, dict): continue`
# ===========================================================================

import modules.crawlers.gov_grants  # noqa: F401
from modules.crawlers.gov_grants import GrantsCrawler, _parse_opportunities


class TestGovGrantsLine36:
    def test_parse_opportunities_skips_non_dict(self):
        data = {
            "oppHits": [
                "not_a_dict",
                {"opportunityTitle": "Research Grant", "agencyName": "NIH"},
            ]
        }
        result = _parse_opportunities(data)
        assert len(result) == 1
        assert result[0]["opportunityTitle"] == "Research Grant"

    @pytest.mark.asyncio
    async def test_grants_http_none(self):
        crawler = GrantsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("research")
        assert _get_error(result) is not None


# ===========================================================================
# gov_nmls — line 46: `if not isinstance(item, dict): continue`
# ===========================================================================

import modules.crawlers.gov_nmls  # noqa: F401
from modules.crawlers.gov_nmls import NmlsCrawler, _parse_licensees


class TestGovNmlsLine46:
    def test_parse_licensees_skips_non_dict(self):
        data = ["not_dict", {"EntityName": "ABC Mortgage", "NmlsId": "123"}]
        result = _parse_licensees(data)
        assert len(result) == 1
        assert result[0]["EntityName"] == "ABC Mortgage"

    def test_parse_licensees_dict_wrapper_fallback(self):
        data = {"Results": [{"EntityName": "XYZ Lender", "PrimaryState": "TX"}]}
        result = _parse_licensees(data)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_nmls_non_200_non_429(self):
        crawler = NmlsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("broker name")
        assert _get_error(result) is not None


# ===========================================================================
# gov_osha — lines 41, 46
# ===========================================================================

import modules.crawlers.gov_osha  # noqa: F401
from modules.crawlers.gov_osha import OshaCrawler, _parse_dol_inspections


class TestGovOshaLines41_46:
    def test_parse_dol_dict_with_no_known_key_wraps_as_list(self):
        """Dict with no recognized key → wrapped as single-item list (line 41)."""
        data = {"activity_nr": "123", "estab_name": "Test Corp"}
        result = _parse_dol_inspections(data)
        assert len(result) == 1
        assert result[0]["activity_nr"] == "123"

    def test_parse_dol_inspections_skips_non_dict(self):
        """Non-dict items in list are skipped (line 46)."""
        data = ["not_dict", {"activity_nr": "456", "estab_name": "Safe Corp"}]
        result = _parse_dol_inspections(data)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_osha_fallback_non_200_or_302(self):
        """Fallback returns 500 → http_error path."""
        crawler = OshaCrawler()
        primary_resp = _mock_resp(200, json_data=[])  # empty list → no inspections
        fallback_resp = _mock_resp(500)

        call_count = [0]

        async def fake_get(url, **kwargs):
            c = call_count[0]
            call_count[0] += 1
            return primary_resp if c == 0 else fallback_resp

        with patch.object(crawler, "get", side_effect=fake_get):
            result = await crawler.scrape("Test Corp")
        assert _get_error(result) is not None

    @pytest.mark.asyncio
    async def test_osha_fallback_none(self):
        """Fallback returns None → http_error path."""
        crawler = OshaCrawler()
        primary_resp = _mock_resp(200, json_data=[])
        call_count = [0]

        async def fake_get(url, **kwargs):
            c = call_count[0]
            call_count[0] += 1
            return primary_resp if c == 0 else None

        with patch.object(crawler, "get", side_effect=fake_get):
            result = await crawler.scrape("Test Corp")
        assert _get_error(result) is not None


# ===========================================================================
# gov_sam — line 37: `api_key` not configured returns not_configured
# ===========================================================================

import modules.crawlers.gov_sam  # noqa: F401
from modules.crawlers.gov_sam import SamCrawler


class TestGovSamLine37:
    @pytest.mark.asyncio
    async def test_sam_no_api_key_returns_not_configured(self):
        """No SAM API key → not_configured error (line 37 branch)."""
        crawler = SamCrawler()
        with patch("modules.crawlers.gov_sam.settings") as mock_settings:
            mock_settings.sam_api_key = ""
            result = await crawler.scrape("Acme Corp")
        assert _get_error(result) == "not_configured"


# ===========================================================================
# gov_uspto_patents — lines 118-119: assignee parse error
# ===========================================================================

import modules.crawlers.gov_uspto_patents  # noqa: F401
from modules.crawlers.gov_uspto_patents import GovUsptoPatentsCrawler


class TestGovUsptoPatentsLines118_119:
    @pytest.mark.asyncio
    async def test_uspto_assignee_json_error(self):
        """Second request (assignee) has invalid JSON — exercises lines 118-119."""
        crawler = GovUsptoPatentsCrawler()
        # First call: inventor search → empty patents
        inventor_resp = _mock_resp(200, json_data={"patents": [], "total_patent_count": 0})
        # Second call: assignee search → bad JSON
        bad_resp = MagicMock()
        bad_resp.status_code = 200
        bad_resp.json = MagicMock(side_effect=ValueError("bad json"))

        call_count = [0]

        async def fake_get(url, **kwargs):
            c = call_count[0]
            call_count[0] += 1
            return inventor_resp if c == 0 else bad_resp

        with patch.object(crawler, "get", side_effect=fake_get):
            result = await crawler.scrape("Acme Corp")
        # Should complete without raising
        assert result is not None


# ===========================================================================
# gov_worldbank — lines 57, 61
# ===========================================================================

import modules.crawlers.gov_worldbank  # noqa: F401
from modules.crawlers.gov_worldbank import WorldBankCrawler, _parse_gdp


class TestGovWorldbankLines57_61:
    def test_parse_gdp_returns_empty_for_short_list(self):
        """line 57: empty data → []"""
        assert _parse_gdp([]) == []
        assert _parse_gdp([None]) == []

    def test_parse_gdp_skips_non_dict_items(self):
        """line 61: non-dict items are skipped."""
        data = [None, ["not_a_dict", {"date": "2020", "value": 1000.0}]]
        result = _parse_gdp(data)
        assert len(result) == 1
        assert result[0]["year"] == "2020"

    @pytest.mark.asyncio
    async def test_worldbank_iso2_path(self):
        """Using a 2-letter ISO code bypasses the country search."""
        crawler = WorldBankCrawler()
        gdp_resp = _mock_resp(200, json_data=[None, [{"date": "2020", "value": 1e12, "indicator": {"value": "GDP"}}]])

        with patch.object(crawler, "get", new=AsyncMock(return_value=gdp_resp)):
            result = await crawler.scrape("US")
        assert result is not None


# ===========================================================================
# gov_gleif — lines 124-126: fulltext fallback parse error
# ===========================================================================

import modules.crawlers.gov_gleif  # noqa: F401
from modules.crawlers.gov_gleif import GleifCrawler


class TestGovGleifLines124_126:
    @pytest.mark.asyncio
    async def test_gleif_fulltext_fallback_parse_error(self):
        """Fulltext fallback response has invalid JSON — exercises lines 124-126."""
        crawler = GleifCrawler()
        # First request (fuzzy): non-200 → triggers fallback
        fuzzy_resp = _mock_resp(503)
        # Fallback request: bad JSON
        bad_resp = MagicMock()
        bad_resp.status_code = 200
        bad_resp.json = MagicMock(side_effect=ValueError("bad json"))

        call_count = [0]

        async def fake_get(url, **kwargs):
            c = call_count[0]
            call_count[0] += 1
            return fuzzy_resp if c == 0 else bad_resp

        with patch.object(crawler, "get", side_effect=fake_get):
            result = await crawler.scrape("Goldman Sachs")
        # Should return gracefully with empty completions
        assert result is not None
        assert result.data.get("completions") == []

    @pytest.mark.asyncio
    async def test_gleif_fuzzy_json_error_triggers_fulltext(self):
        """Fuzzy JSON parse error → falls back to fulltext (lines 90-92)."""
        crawler = GleifCrawler()
        bad_fuzzy = MagicMock()
        bad_fuzzy.status_code = 200
        bad_fuzzy.json = MagicMock(side_effect=ValueError("bad"))
        fulltext_resp = _mock_resp(200, json_data={"data": [
            {
                "id": "LEI123",
                "attributes": {
                    "lei": "LEI123",
                    "entity": {"legalName": {"name": "Goldman Sachs"}},
                },
            }
        ]})

        call_count = [0]

        async def fake_get(url, **kwargs):
            c = call_count[0]
            call_count[0] += 1
            return bad_fuzzy if c == 0 else fulltext_resp

        with patch.object(crawler, "get", side_effect=fake_get):
            result = await crawler.scrape("Goldman Sachs")
        assert result is not None
