"""
test_company_wave4.py — Coverage wave 4 for company and financial crawlers.

Targets:
  company_companies_house.py  : 104-105 (company JSON parse error)
                                113-114 (officer JSON parse error)
  company_opencorporates.py   : 112-113 (company JSON parse error)
                                121-122 (officer JSON parse error)
  company_sec.py              : 134     (non-200 HTTP response early return)
                                151-162 (FTS hits appended + JSON exception)
  financial_worldbank.py      : 112-113 (ISO2 path metadata parse error)
                                168-170 (indicator fetch parse error)

All HTTP calls are mocked — no real infrastructure required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = "", json_raises=False):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_raises:
        resp.json = MagicMock(side_effect=ValueError("bad json"))
    elif json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(return_value={})
    return resp


# ===========================================================================
# company_companies_house.py
# ===========================================================================


import modules.crawlers.company_companies_house  # noqa: F401 — trigger @register

from modules.crawlers.company_companies_house import CompaniesHouseCrawler


class TestCompaniesHouseJsonErrors:
    """Lines 104-105 and 113-114: JSON parse exceptions are logged, not raised."""

    @pytest.mark.asyncio
    async def test_company_json_parse_error_continues(self):
        """Lines 104-105: company endpoint returns 200 but json() raises."""
        crawler = CompaniesHouseCrawler()
        mock_co = _mock_resp(200, json_raises=True)
        # Officer endpoint returns empty list
        mock_off = _mock_resp(200, json_data={"items": []})

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
            result = await crawler.scrape("Acme Corp")

        # Exception is swallowed — companies list stays empty, no crash
        assert result.data["companies"] == []
        assert result.found is False

    @pytest.mark.asyncio
    async def test_officer_json_parse_error_continues(self):
        """Lines 113-114: officer endpoint returns 200 but json() raises."""
        crawler = CompaniesHouseCrawler()
        mock_co = _mock_resp(200, json_data={"items": []})
        mock_off = _mock_resp(200, json_raises=True)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
            result = await crawler.scrape("John Smith")

        # Exception is swallowed — officers list stays empty, no crash
        assert result.data["officers"] == []
        assert result.found is False

    @pytest.mark.asyncio
    async def test_both_json_parse_errors_gives_not_found(self):
        """Both endpoints parse-fail — result_count=0, found=False."""
        crawler = CompaniesHouseCrawler()
        mock_co = _mock_resp(200, json_raises=True)
        mock_off = _mock_resp(200, json_raises=True)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
            result = await crawler.scrape("Error Corp")

        assert result.data["result_count"] == 0
        assert result.found is False


# ===========================================================================
# company_opencorporates.py
# ===========================================================================


import modules.crawlers.company_opencorporates  # noqa: F401 — trigger @register

from modules.crawlers.company_opencorporates import OpenCorporatesCrawler


class TestOpenCorporatesJsonErrors:
    """Lines 112-113 and 121-122: JSON parse exceptions are logged, not raised."""

    @pytest.mark.asyncio
    async def test_company_json_parse_error_continues(self):
        """Lines 112-113: company endpoint returns 200 but json() raises."""
        crawler = OpenCorporatesCrawler()
        mock_co = _mock_resp(200, json_raises=True)
        mock_off = _mock_resp(200, json_data={"results": {"officers": []}})

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
            result = await crawler.scrape("Acme Corp")

        assert result.data["companies"] == []
        assert result.found is False

    @pytest.mark.asyncio
    async def test_officer_json_parse_error_continues(self):
        """Lines 121-122: officer endpoint returns 200 but json() raises."""
        crawler = OpenCorporatesCrawler()
        mock_co = _mock_resp(200, json_data={"results": {"companies": []}})
        mock_off = _mock_resp(200, json_raises=True)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
            result = await crawler.scrape("John Smith")

        assert result.data["officers"] == []
        assert result.found is False

    @pytest.mark.asyncio
    async def test_both_json_errors_gives_not_found(self):
        """Both endpoints parse-fail — result_count=0, found=False."""
        crawler = OpenCorporatesCrawler()
        mock_co = _mock_resp(200, json_raises=True)
        mock_off = _mock_resp(200, json_raises=True)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
            result = await crawler.scrape("Error Corp")

        assert result.data["result_count"] == 0
        assert result.found is False


# ===========================================================================
# company_sec.py
# ===========================================================================


import modules.crawlers.company_sec  # noqa: F401 — trigger @register

from modules.crawlers.company_sec import SECEdgarCrawler

_VALID_ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>EDGAR Company Search</title>
  <entry>
    <title>10-K for TEST CORP</title>
    <updated>2024-01-01T00:00:00-04:00</updated>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"/>
    <category label="10-K" term="form-type"/>
    <content>CIK: 0001234567 TEST CORP annual report</content>
  </entry>
</feed>"""

_FTS_RESPONSE = {
    "hits": {
        "hits": [
            {
                "_source": {
                    "entity_name": "Test Corp",
                    "file_num": "001-12345",
                    "form_type": "8-K",
                    "file_date": "2024-02-01",
                    "file_path": "edgar/data/1234567/0001234567-24-000001.txt",
                }
            }
        ]
    }
}


class TestSECEdgarNon200AndFTS:
    """Lines 134 and 151-162."""

    @pytest.mark.asyncio
    async def test_non_200_primary_response_returns_error(self):
        """Line 134: primary Atom feed returns non-200 — early return with error key."""
        crawler = SECEdgarCrawler()
        mock_atom = _mock_resp(status=503)

        with patch.object(crawler, "get", new=AsyncMock(return_value=mock_atom)):
            result = await crawler.scrape("Test Corp")

        assert result.found is False
        assert "503" in (result.data.get("error", "") or result.error or "")

    @pytest.mark.asyncio
    async def test_fts_hits_are_appended_to_filings(self):
        """Lines 151-160: FTS returns hits → appended to filings list."""
        crawler = SECEdgarCrawler()
        mock_atom = _mock_resp(200, text=_VALID_ATOM_XML)
        mock_fts = _mock_resp(200, json_data=_FTS_RESPONSE)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_atom, mock_fts])):
            result = await crawler.scrape("Test Corp")

        assert result.found is True
        # Atom feed had 1 filing; FTS added 1 more
        assert result.data["result_count"] == 2
        form_types = [f["form_type"] for f in result.data["filings"]]
        assert "8-K" in form_types

    @pytest.mark.asyncio
    async def test_fts_json_parse_error_is_swallowed(self):
        """Lines 161-162: FTS returns 200 but json() raises — exception is caught."""
        crawler = SECEdgarCrawler()
        mock_atom = _mock_resp(200, text=_VALID_ATOM_XML)
        mock_fts = _mock_resp(200, json_raises=True)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_atom, mock_fts])):
            result = await crawler.scrape("Test Corp")

        # Atom feed result still returned, FTS failure doesn't crash
        assert result.found is True
        assert result.data["result_count"] == 1

    @pytest.mark.asyncio
    async def test_fts_none_response_skips_append(self):
        """FTS returns None — no secondary hits, primary filings returned intact."""
        crawler = SECEdgarCrawler()
        mock_atom = _mock_resp(200, text=_VALID_ATOM_XML)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_atom, None])):
            result = await crawler.scrape("Test Corp")

        assert result.found is True
        assert result.data["result_count"] == 1


# ===========================================================================
# financial_worldbank.py
# ===========================================================================


import modules.crawlers.financial_worldbank  # noqa: F401 — trigger @register

from modules.crawlers.financial_worldbank import FinancialWorldBankCrawler

_COUNTRY_META_RESPONSE = [
    {"page": 1},
    [
        {
            "iso2Code": "US",
            "name": "United States",
            "capitalCity": "Washington D.C.",
            "region": {"value": "North America"},
            "incomeLevel": {"value": "High income"},
        }
    ],
]

_INDICATOR_RESPONSE = [
    {"page": 1},
    [
        {"date": "2023", "value": 25_000_000_000_000},
        {"date": "2022", "value": 23_000_000_000_000},
    ],
]


class TestWorldBankISO2PathMetadataError:
    """Lines 112-113: ISO-2 code path + metadata lookup raises exception."""

    @pytest.mark.asyncio
    async def test_iso2_metadata_parse_error_uses_fallback(self):
        """Lines 112-113: metadata json() raises, crawler falls back to bare iso2 dict."""
        crawler = FinancialWorldBankCrawler()

        # First call: metadata search → 200 but json raises
        mock_meta = _mock_resp(200, json_raises=True)
        # Subsequent 3 indicator calls: all return None (skipped)
        mock_indicator = _mock_resp(200, json_data=_INDICATOR_RESPONSE)

        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[mock_meta, mock_indicator, mock_indicator, mock_indicator]),
        ):
            result = await crawler.scrape("US")

        # Should still succeed with fallback country_info
        assert result.found is True
        assert result.data["country_info"]["iso2"] == "US"


class TestWorldBankIndicatorParseError:
    """Lines 168-170: indicator json() raises — empty list used, no crash."""

    @pytest.mark.asyncio
    async def test_indicator_parse_error_produces_empty_list(self):
        """Lines 168-170: indicator fetch returns 200 but json() raises."""
        crawler = FinancialWorldBankCrawler()

        # First call: metadata search (name-based path)
        mock_meta = _mock_resp(200, json_data=_COUNTRY_META_RESPONSE)
        # All 3 indicator calls raise on json()
        mock_bad_indicator = _mock_resp(200, json_raises=True)

        with patch.object(
            crawler,
            "get",
            new=AsyncMock(
                side_effect=[mock_meta, mock_bad_indicator, mock_bad_indicator, mock_bad_indicator]
            ),
        ):
            result = await crawler.scrape("United States")

        assert result.found is True
        # All indicator lists should be empty due to parse errors
        assert result.data["gdp_data"] == []
        assert result.data["cpi_data"] == []
        assert result.data["unemployment_data"] == []

    @pytest.mark.asyncio
    async def test_indicator_parse_error_on_iso2_path(self):
        """Lines 168-170 via ISO2 path: indicator raises → empty lists."""
        crawler = FinancialWorldBankCrawler()

        # ISO2 path: metadata search returns valid data
        mock_meta = _mock_resp(200, json_data=_COUNTRY_META_RESPONSE)
        mock_bad = _mock_resp(200, json_raises=True)

        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[mock_meta, mock_bad, mock_bad, mock_bad]),
        ):
            result = await crawler.scrape("US")

        assert result.found is True
        assert result.data["gdp_data"] == []
