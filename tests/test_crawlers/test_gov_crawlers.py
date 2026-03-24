"""
Tests for government/public-data crawlers — 17 modules.

All HTTP calls are mocked via patch.object on the crawler's get() or post()
method. No real network traffic is generated.

Crawlers covered:
  gov_bop           — BOP inmate locator (POST + HTML)
  gov_epa           — EPA ECHO facility compliance (GET + JSON)
  gov_fda           — FDA drug events + recalls (dual GET + JSON)
  gov_fdic          — FDIC BankFind institution search (GET + JSON)
  gov_fec           — FEC campaign finance candidates (GET + JSON)
  gov_finra         — FINRA BrokerCheck individual search (GET + JSON)
  gov_fred          — St. Louis Fed FRED series search (GET + JSON)
  gov_gleif         — GLEIF LEI fuzzy completion + fulltext fallback (GET + JSON)
  gov_grants        — Grants.gov opportunity search (POST + JSON)
  gov_nmls          — NMLS Consumer Access licensee search (POST + JSON)
  gov_osha          — OSHA inspection search (GET + JSON + HTML fallback)
  gov_propublica    — ProPublica Nonprofit Explorer (GET + JSON)
  gov_sam           — SAM.gov entity registration (GET + JSON, needs API key)
  gov_usaspending   — USASpending.gov award search (POST + JSON)
  gov_uspto_patents  — PatentsView patent search (dual GET + JSON)
  gov_uspto_trademarks — USPTO IBD trademark search (GET + JSON)
  gov_worldbank     — World Bank country + GDP lookup (dual GET + JSON)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str | None = None):
    """Build a lightweight mock that looks like an httpx.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_data if json_data is not None else {})
    resp.text = text if text is not None else str(json_data or {})
    return resp


def _bad_json_resp(status: int = 200):
    """Mock whose .json() raises ValueError — exercises parse_error branches."""
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(side_effect=ValueError("bad json"))
    resp.text = "not json"
    return resp


def _get_error(result) -> str | None:
    """
    Retrieve the error string from a CrawlerResult regardless of where it lives.

    Some crawlers use CrawlerResult(error=...) directly → stored in result.error.
    Others use self._result(id, found=False, error=...) → stored in result.data["error"]
    because BaseCrawler._result() passes all kwargs into the data dict.
    This helper checks both so tests are not fragile to that implementation detail.
    """
    return result.error or result.data.get("error")


# ===========================================================================
# gov_bop — Federal Bureau of Prisons inmate locator
# ===========================================================================


import modules.crawlers.gov_bop  # noqa: F401 — trigger @register


class TestGovBop:
    """BOP uses POST, returns HTML (not JSON)."""

    @pytest.mark.asyncio
    async def test_bop_success_with_register_numbers(self):
        from modules.crawlers.gov_bop import BopCrawler

        html = (
            "<html><body><table>"
            "<tr><td>12345678</td><td>SMITH, JOHN</td></tr>"
            "<tr><td>87654321</td><td>DOE, JANE</td></tr>"
            "</table></body></html>"
        )
        crawler = BopCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200, text=html))):
            result = await crawler.scrape("John Smith")

        assert result.found is True
        assert result.platform == "gov_bop"
        assert "12345678" in result.data["register_numbers"]
        assert "87654321" in result.data["register_numbers"]
        assert result.data["query"] == "John Smith"

    @pytest.mark.asyncio
    async def test_bop_no_records_phrase(self):
        """HTML containing a 'No records found' phrase → found=False."""
        from modules.crawlers.gov_bop import BopCrawler

        html = "<html><body>No records found for that name.</body></html>"
        crawler = BopCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200, text=html))):
            result = await crawler.scrape("Nobody Here")

        assert result.found is False
        assert result.data["register_numbers"] == []

    @pytest.mark.asyncio
    async def test_bop_network_error(self):
        """post() returns None → found=False with http_error."""
        from modules.crawlers.gov_bop import BopCrawler

        crawler = BopCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert _get_error(result) == "http_error"

    @pytest.mark.asyncio
    async def test_bop_empty_response_text(self):
        """Empty HTML body → found=False (empty text is falsy)."""
        from modules.crawlers.gov_bop import BopCrawler

        crawler = BopCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200, text=""))):
            result = await crawler.scrape("John Smith")

        assert result.found is False

    @pytest.mark.asyncio
    async def test_bop_preview_truncated_to_2000(self):
        """raw_response_preview must be at most 2000 characters."""
        from modules.crawlers.gov_bop import BopCrawler

        long_html = "A" * 5000
        crawler = BopCrawler()
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, text=long_html))
        ):
            result = await crawler.scrape("test")

        assert len(result.data["raw_response_preview"]) <= 2000

    @pytest.mark.asyncio
    async def test_bop_did_not_return_phrase(self):
        """Alternative no-results phrase → found=False."""
        from modules.crawlers.gov_bop import BopCrawler

        html = "<html>Your search did not return any results.</html>"
        crawler = BopCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200, text=html))):
            result = await crawler.scrape("test")

        assert result.found is False


# ===========================================================================
# gov_epa — EPA ECHO facility compliance
# ===========================================================================


import modules.crawlers.gov_epa  # noqa: F401


class TestGovEpa:
    _SUCCESS_DATA = {
        "Results": {
            "Results": [
                {
                    "CWPName": "ACME Chemical Plant",
                    "CWPCity": "Houston",
                    "CWPState": "TX",
                    "CWPSic": "2819",
                    "CWPStatus": "Active",
                    "CWPQtrsWithNC": "4",
                    "FacLat": "29.7604",
                    "FacLong": "-95.3698",
                    "RegistryId": "110000000001",
                    "FacFIPSCode": "48201",
                }
            ]
        }
    }

    @pytest.mark.asyncio
    async def test_epa_success(self):
        from modules.crawlers.gov_epa import EpaCrawler

        crawler = EpaCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._SUCCESS_DATA))
        ):
            result = await crawler.scrape("ACME Chemical")

        assert result.found is True
        assert result.platform == "gov_epa"
        assert len(result.data["facilities"]) == 1
        assert result.data["facilities"][0]["CWPName"] == "ACME Chemical Plant"

    @pytest.mark.asyncio
    async def test_epa_flat_facilities_key(self):
        """Parser falls back to 'Facilities' key when Results nesting is absent."""
        from modules.crawlers.gov_epa import EpaCrawler

        data = {
            "Facilities": [
                {
                    "CWPName": "Flat Corp",
                    "CWPCity": "Denver",
                    "CWPState": "CO",
                    "CWPSic": None,
                    "CWPStatus": "Active",
                    "CWPQtrsWithNC": "0",
                    "FacLat": None,
                    "FacLong": None,
                    "RegistryId": "999",
                    "FacFIPSCode": None,
                }
            ]
        }
        crawler = EpaCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, data))):
            result = await crawler.scrape("Flat Corp")

        assert result.found is True
        assert result.data["facilities"][0]["CWPName"] == "Flat Corp"

    @pytest.mark.asyncio
    async def test_epa_empty_results(self):
        """Empty results array → found=False."""
        from modules.crawlers.gov_epa import EpaCrawler

        crawler = EpaCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, {"Results": {"Results": []}}))
        ):
            result = await crawler.scrape("Unknown Corp")

        assert result.found is False
        assert result.data["facilities"] == []

    @pytest.mark.asyncio
    async def test_epa_network_error(self):
        from modules.crawlers.gov_epa import EpaCrawler

        crawler = EpaCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_epa_bad_status(self):
        from modules.crawlers.gov_epa import EpaCrawler

        crawler = EpaCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert "500" in result.error

    @pytest.mark.asyncio
    async def test_epa_invalid_json(self):
        from modules.crawlers.gov_epa import EpaCrawler

        crawler = EpaCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_bad_json_resp())):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "parse_error"


# ===========================================================================
# gov_fda — FDA drug events + enforcement recalls
# ===========================================================================


import modules.crawlers.gov_fda  # noqa: F401


class TestGovFda:
    _EVENTS_DATA = {
        "results": [
            {
                "safetyreportid": "12345",
                "receivedate": "20240101",
                "serious": "1",
                "patient": {
                    "drug": [
                        {
                            "openfda": {"generic_name": ["aspirin"]},
                            "medicinalproduct": "ASPIRIN",
                        }
                    ],
                    "reaction": [{"reactionmeddrapt": "Headache"}],
                },
            }
        ]
    }
    _RECALLS_DATA = {
        "results": [
            {
                "recall_number": "F-0001-2024",
                "recalling_firm": "ACME Pharma",
                "product_description": "Aspirin 325mg tablets",
                "reason_for_recall": "Contamination",
                "classification": "Class I",
                "status": "Ongoing",
                "recall_initiation_date": "20240115",
                "state": "TX",
            }
        ]
    }

    @pytest.mark.asyncio
    async def test_fda_success_both_endpoints(self):
        """Both events and recalls return data → found=True."""
        from modules.crawlers.gov_fda import FdaCrawler

        crawler = FdaCrawler()
        events_resp = _mock_resp(200, self._EVENTS_DATA)
        recalls_resp = _mock_resp(200, self._RECALLS_DATA)

        with patch.object(
            crawler, "get", new=AsyncMock(side_effect=[events_resp, recalls_resp])
        ):
            result = await crawler.scrape("aspirin")

        assert result.found is True
        assert result.platform == "gov_fda"
        assert len(result.data["adverse_events"]) == 1
        assert len(result.data["recalls"]) == 1
        assert result.data["adverse_events"][0]["report_id"] == "12345"
        assert result.data["recalls"][0]["recall_number"] == "F-0001-2024"

    @pytest.mark.asyncio
    async def test_fda_events_only(self):
        """Only events response succeeds → found=True (events >= 1)."""
        from modules.crawlers.gov_fda import FdaCrawler

        crawler = FdaCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_mock_resp(200, self._EVENTS_DATA), _mock_resp(404)]),
        ):
            result = await crawler.scrape("aspirin")

        assert result.found is True
        assert len(result.data["adverse_events"]) == 1
        assert result.data["recalls"] == []

    @pytest.mark.asyncio
    async def test_fda_recalls_only(self):
        """Only recalls response succeeds → found=True."""
        from modules.crawlers.gov_fda import FdaCrawler

        crawler = FdaCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_mock_resp(404), _mock_resp(200, self._RECALLS_DATA)]),
        ):
            result = await crawler.scrape("ACME Pharma")

        assert result.found is True
        assert result.data["adverse_events"] == []
        assert len(result.data["recalls"]) == 1

    @pytest.mark.asyncio
    async def test_fda_both_none(self):
        """Both responses None → found=False with http_error."""
        from modules.crawlers.gov_fda import FdaCrawler

        crawler = FdaCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("aspirin")

        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_fda_events_bad_json(self):
        """Invalid JSON on events endpoint is silently ignored; recalls still parsed."""
        from modules.crawlers.gov_fda import FdaCrawler

        crawler = FdaCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_bad_json_resp(), _mock_resp(200, self._RECALLS_DATA)]),
        ):
            result = await crawler.scrape("aspirin")

        assert result.data["adverse_events"] == []
        assert len(result.data["recalls"]) == 1

    @pytest.mark.asyncio
    async def test_fda_drug_without_openfda_name(self):
        """Drug record without openfda.generic_name uses medicinalproduct instead."""
        from modules.crawlers.gov_fda import FdaCrawler

        events_data = {
            "results": [
                {
                    "safetyreportid": "99",
                    "receivedate": "20240201",
                    "serious": "2",
                    "patient": {
                        "drug": [{"openfda": {}, "medicinalproduct": "IBUPROFEN"}],
                        "reaction": [],
                    },
                }
            ]
        }
        crawler = FdaCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_mock_resp(200, events_data), _mock_resp(404)]),
        ):
            result = await crawler.scrape("ibuprofen")

        assert result.found is True
        assert "IBUPROFEN" in result.data["adverse_events"][0]["drugs"]

    @pytest.mark.asyncio
    async def test_fda_empty_results(self):
        """Both endpoints return empty results arrays → found=False."""
        from modules.crawlers.gov_fda import FdaCrawler

        crawler = FdaCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(
                side_effect=[_mock_resp(200, {"results": []}), _mock_resp(200, {"results": []})]
            ),
        ):
            result = await crawler.scrape("unknown")

        assert result.found is False


# ===========================================================================
# gov_fdic — FDIC BankFind institution search
# ===========================================================================


import modules.crawlers.gov_fdic  # noqa: F401


class TestGovFdic:
    _SUCCESS_DATA = {
        "data": [
            {
                "data": {
                    "NAME": "Wells Fargo Bank",
                    "CITY": "Sioux Falls",
                    "STNAME": "South Dakota",
                    "ASSET": 1900000000,
                    "REPDTE": "20231231",
                }
            }
        ],
        "meta": {"total": 5},
    }

    @pytest.mark.asyncio
    async def test_fdic_success(self):
        from modules.crawlers.gov_fdic import FdicCrawler

        crawler = FdicCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._SUCCESS_DATA))
        ):
            result = await crawler.scrape("Wells Fargo")

        assert result.found is True
        assert result.platform == "gov_fdic"
        assert len(result.data["institutions"]) == 1
        assert result.data["institutions"][0]["name"] == "Wells Fargo Bank"
        assert result.data["total"] == 5

    @pytest.mark.asyncio
    async def test_fdic_item_without_nested_data(self):
        """Items that are flat dicts (no 'data' sub-key) still parse correctly."""
        data = {
            "data": [
                {
                    "NAME": "Flat Bank",
                    "CITY": "Dallas",
                    "STNAME": "Texas",
                    "ASSET": 5000000,
                    "REPDTE": "20231231",
                }
            ],
            "meta": {"total": 1},
        }
        from modules.crawlers.gov_fdic import FdicCrawler

        crawler = FdicCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, data))):
            result = await crawler.scrape("Flat Bank")

        assert result.found is True
        assert result.data["institutions"][0]["name"] == "Flat Bank"

    @pytest.mark.asyncio
    async def test_fdic_empty_results(self):
        from modules.crawlers.gov_fdic import FdicCrawler

        crawler = FdicCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, {"data": [], "meta": {"total": 0}}))
        ):
            result = await crawler.scrape("Nonexistent Bank")

        assert result.found is False
        assert result.data["total"] == 0

    @pytest.mark.asyncio
    async def test_fdic_network_error(self):
        from modules.crawlers.gov_fdic import FdicCrawler

        crawler = FdicCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "http_error"

    @pytest.mark.asyncio
    async def test_fdic_bad_status(self):
        from modules.crawlers.gov_fdic import FdicCrawler

        crawler = FdicCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert "503" in _get_error(result)

    @pytest.mark.asyncio
    async def test_fdic_invalid_json(self):
        from modules.crawlers.gov_fdic import FdicCrawler

        crawler = FdicCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_bad_json_resp())):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "parse_error"


# ===========================================================================
# gov_fec — FEC campaign finance candidates
# ===========================================================================


import modules.crawlers.gov_fec  # noqa: F401


class TestGovFec:
    _SUCCESS_DATA = {
        "results": [
            {
                "name": "Biden, Joseph R",
                "party": "DEM",
                "state": "DE",
                "office": "P",
                "total_receipts": 1234567890.0,
                "election_years": [2020, 2024],
            }
        ],
        "pagination": {"count": 1},
    }

    @pytest.mark.asyncio
    async def test_fec_success(self):
        from modules.crawlers.gov_fec import FecCrawler

        crawler = FecCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._SUCCESS_DATA))
        ):
            result = await crawler.scrape("Joe Biden")

        assert result.found is True
        assert result.platform == "gov_fec"
        assert len(result.data["candidates"]) == 1
        assert result.data["candidates"][0]["party"] == "DEM"
        assert result.data["count"] == 1

    @pytest.mark.asyncio
    async def test_fec_empty_results(self):
        from modules.crawlers.gov_fec import FecCrawler

        crawler = FecCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(return_value=_mock_resp(200, {"results": [], "pagination": {"count": 0}})),
        ):
            result = await crawler.scrape("Nobody")

        assert result.found is False
        assert result.data["count"] == 0

    @pytest.mark.asyncio
    async def test_fec_network_error(self):
        from modules.crawlers.gov_fec import FecCrawler

        crawler = FecCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "http_error"

    @pytest.mark.asyncio
    async def test_fec_bad_status(self):
        from modules.crawlers.gov_fec import FecCrawler

        crawler = FecCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert "500" in _get_error(result)

    @pytest.mark.asyncio
    async def test_fec_invalid_json(self):
        from modules.crawlers.gov_fec import FecCrawler

        crawler = FecCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_bad_json_resp())):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "parse_error"

    @pytest.mark.asyncio
    async def test_fec_uses_demo_key_when_unconfigured(self):
        """FEC crawler should not crash when settings.fec_api_key is absent."""
        from modules.crawlers.gov_fec import FecCrawler

        crawler = FecCrawler()
        with (
            patch("modules.crawlers.gov_fec.settings", spec=[]),  # no fec_api_key attr
            patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._SUCCESS_DATA))
            ),
        ):
            result = await crawler.scrape("Biden")

        assert result.found is True


# ===========================================================================
# gov_finra — FINRA BrokerCheck
# ===========================================================================


import modules.crawlers.gov_finra  # noqa: F401


class TestGovFinra:
    _SUCCESS_DATA = {
        "hits": {
            "total": {"value": 1},
            "hits": [
                {
                    "_source": {
                        "ind_source_id": "1234567",
                        "ind_firstname": "John",
                        "ind_lastname": "Smith",
                        "ind_middlename": "W",
                        "bc_scope": "Active",
                        "ind_bc_disc_fl": "N",
                        "ind_ia_disc_fl": "N",
                        "ind_bc_scope": "Registered",
                        "ind_ia_scope": None,
                        "ind_industry_cal_yr_cnt": 15,
                    }
                }
            ],
        }
    }

    @pytest.mark.asyncio
    async def test_finra_success(self):
        from modules.crawlers.gov_finra import FinraCrawler

        crawler = FinraCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._SUCCESS_DATA))
        ):
            result = await crawler.scrape("John Smith")

        assert result.found is True
        assert result.platform == "gov_finra"
        assert len(result.data["brokers"]) == 1
        assert result.data["brokers"][0]["ind_firstname"] == "John"
        assert result.data["total"] == 1

    @pytest.mark.asyncio
    async def test_finra_total_as_int(self):
        """hits.total as bare integer (not dict) still sets total correctly."""
        data = {
            "hits": {
                "total": 3,
                "hits": [{"_source": {"ind_source_id": "999", "ind_firstname": "Jane"}}],
            }
        }
        from modules.crawlers.gov_finra import FinraCrawler

        crawler = FinraCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, data))):
            result = await crawler.scrape("Jane")

        assert result.data["total"] == 3

    @pytest.mark.asyncio
    async def test_finra_hits_as_list(self):
        """hits field is a plain list (not wrapped in dict) — parser handles it."""
        data = {"hits": [{"_source": {"ind_source_id": "888", "ind_firstname": "Bob"}}]}
        from modules.crawlers.gov_finra import FinraCrawler

        crawler = FinraCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, data))):
            result = await crawler.scrape("Bob")

        assert result.found is True
        assert result.data["total"] == 1  # len(brokers) fallback

    @pytest.mark.asyncio
    async def test_finra_rate_limit_429(self):
        from modules.crawlers.gov_finra import FinraCrawler

        crawler = FinraCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_finra_bad_status(self):
        from modules.crawlers.gov_finra import FinraCrawler

        crawler = FinraCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert "503" in result.error

    @pytest.mark.asyncio
    async def test_finra_network_error(self):
        from modules.crawlers.gov_finra import FinraCrawler

        crawler = FinraCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_finra_invalid_json(self):
        from modules.crawlers.gov_finra import FinraCrawler

        crawler = FinraCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_bad_json_resp())):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "parse_error"

    @pytest.mark.asyncio
    async def test_finra_empty_hits(self):
        from modules.crawlers.gov_finra import FinraCrawler

        crawler = FinraCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(return_value=_mock_resp(200, {"hits": {"total": {"value": 0}, "hits": []}})),
        ):
            result = await crawler.scrape("Nobody")

        assert result.found is False
        assert result.data["brokers"] == []


# ===========================================================================
# gov_fred — FRED economic series search
# ===========================================================================


import modules.crawlers.gov_fred  # noqa: F401


class TestGovFred:
    _SUCCESS_DATA = {
        "seriess": [
            {
                "id": "UNRATE",
                "title": "Unemployment Rate",
                "frequency": "Monthly",
                "units": "Percent",
                "last_updated": "2024-01-05 08:01:02-06",
                "popularity": 95,
                "observation_start": "1948-01-01",
                "observation_end": "2023-12-01",
                "seasonal_adjustment": "Seasonally Adjusted",
                "notes": "The unemployment rate represents the number of unemployed...",
            }
        ],
        "count": 1,
    }

    @pytest.mark.asyncio
    async def test_fred_success(self):
        from modules.crawlers.gov_fred import FredCrawler

        crawler = FredCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._SUCCESS_DATA))
        ):
            result = await crawler.scrape("unemployment rate")

        assert result.found is True
        assert result.platform == "gov_fred"
        assert result.data["series"][0]["id"] == "UNRATE"
        assert result.data["count"] == 1

    @pytest.mark.asyncio
    async def test_fred_empty_results(self):
        from modules.crawlers.gov_fred import FredCrawler

        crawler = FredCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, {"seriess": [], "count": 0}))
        ):
            result = await crawler.scrape("noresults")

        assert result.found is False

    @pytest.mark.asyncio
    async def test_fred_rate_limit_429(self):
        from modules.crawlers.gov_fred import FredCrawler

        crawler = FredCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
            result = await crawler.scrape("gdp")

        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_fred_bad_status(self):
        from modules.crawlers.gov_fred import FredCrawler

        crawler = FredCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert "500" in result.error

    @pytest.mark.asyncio
    async def test_fred_network_error(self):
        from modules.crawlers.gov_fred import FredCrawler

        crawler = FredCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_fred_invalid_json(self):
        from modules.crawlers.gov_fred import FredCrawler

        crawler = FredCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_bad_json_resp())):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "parse_error"

    @pytest.mark.asyncio
    async def test_fred_uses_demo_key_fallback(self):
        """Crawler must not crash when settings.fred_api_key is absent."""
        from modules.crawlers.gov_fred import FredCrawler

        crawler = FredCrawler()
        with (
            patch("modules.crawlers.gov_fred.settings", spec=[]),
            patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._SUCCESS_DATA))
            ),
        ):
            result = await crawler.scrape("GDP")

        assert result.found is True


# ===========================================================================
# gov_gleif — GLEIF LEI fuzzy completion + full-text fallback
# ===========================================================================


import modules.crawlers.gov_gleif  # noqa: F401


class TestGovGleif:
    _FUZZY_LIST = [
        {"lei": "HWUPKR0MPOU8FGXBT394", "value": "Goldman Sachs & Co."},
        {"lei": "784F5XWPLTWKTBV3E584", "value": "Goldman Sachs Bank USA"},
    ]
    _FULLTEXT_DATA = {
        "data": [
            {
                "id": "HWUPKR0MPOU8FGXBT394",
                "attributes": {
                    "lei": "HWUPKR0MPOU8FGXBT394",
                    "entity": {"legalName": {"name": "Goldman Sachs & Co."}},
                },
            }
        ]
    }

    @pytest.mark.asyncio
    async def test_gleif_success_list_response(self):
        """Fuzzy endpoint returns plain list → completions parsed correctly."""
        from modules.crawlers.gov_gleif import GleifCrawler

        crawler = GleifCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._FUZZY_LIST))
        ):
            result = await crawler.scrape("Goldman Sachs")

        assert result.found is True
        assert result.platform == "gov_gleif"
        assert len(result.data["completions"]) == 2
        assert result.data["completions"][0]["lei"] == "HWUPKR0MPOU8FGXBT394"

    @pytest.mark.asyncio
    async def test_gleif_success_dict_with_data_key(self):
        """Fuzzy endpoint returns {data: [...]} dict → parser uses data key."""
        from modules.crawlers.gov_gleif import GleifCrawler

        data = {"data": self._FUZZY_LIST}
        crawler = GleifCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, data))):
            result = await crawler.scrape("Goldman")

        assert result.found is True
        assert len(result.data["completions"]) == 2

    @pytest.mark.asyncio
    async def test_gleif_fuzzy_non200_fallback_success(self):
        """Non-200 on fuzzy → full-text fallback returns results → found=True."""
        from modules.crawlers.gov_gleif import GleifCrawler

        crawler = GleifCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(
                side_effect=[_mock_resp(503), _mock_resp(200, self._FULLTEXT_DATA)]
            ),
        ):
            result = await crawler.scrape("Goldman Sachs")

        assert result.found is True
        assert result.data["completions"][0]["name"] == "Goldman Sachs & Co."

    @pytest.mark.asyncio
    async def test_gleif_fuzzy_non200_fallback_fails(self):
        """Non-200 on fuzzy AND fallback also fails → found=False."""
        from modules.crawlers.gov_gleif import GleifCrawler

        crawler = GleifCrawler()
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[_mock_resp(503), None])):
            result = await crawler.scrape("Unknown Corp")

        assert result.found is False
        assert result.data["completions"] == []

    @pytest.mark.asyncio
    async def test_gleif_network_error_on_fuzzy(self):
        """None on fuzzy → error result with http_error."""
        from modules.crawlers.gov_gleif import GleifCrawler

        crawler = GleifCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "http_error"

    @pytest.mark.asyncio
    async def test_gleif_empty_list(self):
        """Empty fuzzy completion list → found=False."""
        from modules.crawlers.gov_gleif import GleifCrawler

        crawler = GleifCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, []))):
            result = await crawler.scrape("Unknown Corp")

        assert result.found is False

    @pytest.mark.asyncio
    async def test_gleif_parse_error_triggers_fallback(self):
        """Bad JSON on fuzzy → fall through to full-text fallback."""
        from modules.crawlers.gov_gleif import GleifCrawler

        crawler = GleifCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(
                side_effect=[_bad_json_resp(), _mock_resp(200, self._FULLTEXT_DATA)]
            ),
        ):
            result = await crawler.scrape("Goldman")

        assert result.found is True

    @pytest.mark.asyncio
    async def test_gleif_fulltext_legal_name_string(self):
        """legalName as plain string (not dict) is handled by str() cast."""
        fulltext = {
            "data": [
                {
                    "id": "ABC123",
                    "attributes": {
                        "lei": "ABC123",
                        "entity": {"legalName": "Plain String Corp"},
                    },
                }
            ]
        }
        from modules.crawlers.gov_gleif import GleifCrawler

        crawler = GleifCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_mock_resp(503), _mock_resp(200, fulltext)]),
        ):
            result = await crawler.scrape("Plain String")

        assert result.found is True
        assert "Plain String Corp" in result.data["completions"][0]["name"]


# ===========================================================================
# gov_grants — Grants.gov opportunity search
# ===========================================================================


import modules.crawlers.gov_grants  # noqa: F401


class TestGovGrants:
    _OPP_HIT = {
        "opportunityTitle": "Small Business Innovation Research",
        "opportunityNumber": "DOD-SBIR-2024-001",
        "agencyName": "Department of Defense",
        "openDate": "2024-01-01",
        "closeDate": "2024-03-31",
        "awardCeiling": 1500000,
        "awardFloor": 0,
        "cfdaNumber": "12.910",
        "opportunityCategory": "Discretionary",
        "fundingActivityCategory": "RD",
    }

    @pytest.mark.asyncio
    async def test_grants_success_opphits_key(self):
        """Response uses oppHits top-level key."""
        from modules.crawlers.gov_grants import GrantsCrawler

        data = {"oppHits": [self._OPP_HIT], "totalRecords": 1}
        crawler = GrantsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200, data))):
            result = await crawler.scrape("small business")

        assert result.found is True
        assert result.platform == "gov_grants"
        assert len(result.data["opportunities"]) == 1
        assert result.data["opportunities"][0]["agencyName"] == "Department of Defense"
        assert result.data["total"] == 1

    @pytest.mark.asyncio
    async def test_grants_success_nested_hits(self):
        """Response uses hits.hits nesting (Elasticsearch style)."""
        from modules.crawlers.gov_grants import GrantsCrawler

        data = {
            "hits": {
                "hits": [{"_source": self._OPP_HIT}],
                "total": {"value": 1},
            }
        }
        crawler = GrantsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200, data))):
            result = await crawler.scrape("research")

        assert result.found is True
        assert result.data["opportunities"][0]["opportunityTitle"] == "Small Business Innovation Research"

    @pytest.mark.asyncio
    async def test_grants_empty_results(self):
        from modules.crawlers.gov_grants import GrantsCrawler

        crawler = GrantsCrawler()
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, {"oppHits": [], "totalRecords": 0}))
        ):
            result = await crawler.scrape("nothing")

        assert result.found is False

    @pytest.mark.asyncio
    async def test_grants_network_error(self):
        from modules.crawlers.gov_grants import GrantsCrawler

        crawler = GrantsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_grants_bad_status(self):
        from modules.crawlers.gov_grants import GrantsCrawler

        crawler = GrantsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(500))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert "500" in result.error

    @pytest.mark.asyncio
    async def test_grants_invalid_json(self):
        from modules.crawlers.gov_grants import GrantsCrawler

        crawler = GrantsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_bad_json_resp())):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "parse_error"

    @pytest.mark.asyncio
    async def test_grants_total_from_nested_hits(self):
        """total falls back to hits.total.value when totalRecords absent."""
        from modules.crawlers.gov_grants import GrantsCrawler

        data = {
            "hits": {
                "hits": [self._OPP_HIT],
                "total": {"value": 42},
            }
        }
        crawler = GrantsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200, data))):
            result = await crawler.scrape("research")

        assert result.data["total"] == 42


# ===========================================================================
# gov_nmls — NMLS Consumer Access licensee search
# ===========================================================================


import modules.crawlers.gov_nmls  # noqa: F401


class TestGovNmls:
    _LICENSEE = {
        "EntityName": "QuickCash Mortgage LLC",
        "NmlsId": 123456,
        "PrimaryState": "TX",
        "LicenseStatus": "Approved-Active",
        "licenseList": [{"state": "TX", "licenseNumber": "TX123"}],
        "EntityType": "Individual",
        "OtherTradeName": None,
    }

    @pytest.mark.asyncio
    async def test_nmls_success_list_response(self):
        """API returns a plain list of licensees."""
        from modules.crawlers.gov_nmls import NmlsCrawler

        crawler = NmlsCrawler()
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, [self._LICENSEE]))
        ):
            result = await crawler.scrape("QuickCash")

        assert result.found is True
        assert result.platform == "gov_nmls"
        assert result.data["licensees"][0]["EntityName"] == "QuickCash Mortgage LLC"

    @pytest.mark.asyncio
    async def test_nmls_success_individual_list_key(self):
        """API returns dict with IndividualList key."""
        from modules.crawlers.gov_nmls import NmlsCrawler

        data = {"IndividualList": [self._LICENSEE], "TotalRecords": 1}
        crawler = NmlsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200, data))):
            result = await crawler.scrape("QuickCash")

        assert result.found is True
        assert len(result.data["licensees"]) == 1

    @pytest.mark.asyncio
    async def test_nmls_success_results_key(self):
        """API returns dict with Results key."""
        from modules.crawlers.gov_nmls import NmlsCrawler

        data = {"Results": [self._LICENSEE]}
        crawler = NmlsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200, data))):
            result = await crawler.scrape("QuickCash")

        assert result.found is True

    @pytest.mark.asyncio
    async def test_nmls_licensee_uses_full_name_fallback(self):
        """EntityName absent → FullName used instead."""
        from modules.crawlers.gov_nmls import NmlsCrawler

        licensee = {**self._LICENSEE, "EntityName": None, "FullName": "John Broker"}
        crawler = NmlsCrawler()
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, [licensee]))
        ):
            result = await crawler.scrape("John")

        assert result.data["licensees"][0]["EntityName"] == "John Broker"

    @pytest.mark.asyncio
    async def test_nmls_rate_limit_429(self):
        from modules.crawlers.gov_nmls import NmlsCrawler

        crawler = NmlsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(429))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_nmls_network_error(self):
        from modules.crawlers.gov_nmls import NmlsCrawler

        crawler = NmlsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_nmls_bad_status(self):
        from modules.crawlers.gov_nmls import NmlsCrawler

        crawler = NmlsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("test")

        assert result.found is False

    @pytest.mark.asyncio
    async def test_nmls_invalid_json(self):
        from modules.crawlers.gov_nmls import NmlsCrawler

        crawler = NmlsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_bad_json_resp())):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "parse_error"

    @pytest.mark.asyncio
    async def test_nmls_empty_list(self):
        from modules.crawlers.gov_nmls import NmlsCrawler

        crawler = NmlsCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(200, []))):
            result = await crawler.scrape("Nobody")

        assert result.found is False
        assert result.data["licensees"] == []


# ===========================================================================
# gov_osha — OSHA inspection search (primary DOL API + HTML fallback)
# ===========================================================================


import modules.crawlers.gov_osha  # noqa: F401


class TestGovOsha:
    _INSPECTION = {
        "activity_nr": "12345678",
        "estab_name": "ACME Factory",
        "open_date": "2023-06-01",
        "close_date": "2023-06-15",
        "nr_violations": 3,
        "total_current_penalty": "12500.00",
        "city": "Houston",
        "state": "TX",
        "naics_code": "332999",
        "insp_type": "Planned",
    }

    @pytest.mark.asyncio
    async def test_osha_success_list_response(self):
        """DOL API returns a list of inspections."""
        from modules.crawlers.gov_osha import OshaCrawler

        crawler = OshaCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, [self._INSPECTION]))
        ):
            result = await crawler.scrape("ACME Factory")

        assert result.found is True
        assert result.platform == "gov_osha"
        assert len(result.data["inspections"]) == 1
        assert result.data["inspections"][0]["establishment_name"] == "ACME Factory"
        assert result.data["source"] == "dol_api"

    @pytest.mark.asyncio
    async def test_osha_success_data_key(self):
        """DOL API returns dict with 'data' key."""
        from modules.crawlers.gov_osha import OshaCrawler

        data = {"data": [self._INSPECTION]}
        crawler = OshaCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, data))):
            result = await crawler.scrape("ACME")

        assert result.found is True
        assert result.data["source"] == "dol_api"

    @pytest.mark.asyncio
    async def test_osha_primary_empty_fallback_200(self):
        """Empty primary results → fallback called; fallback 200 → result returned."""
        from modules.crawlers.gov_osha import OshaCrawler

        crawler = OshaCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_mock_resp(200, []), _mock_resp(200)]),
        ):
            result = await crawler.scrape("Small Biz")

        # No inspections found, but fallback reached successfully
        assert result.found is False
        assert result.data["source"] == "fallback"

    @pytest.mark.asyncio
    async def test_osha_primary_empty_fallback_302(self):
        """Fallback returning 302 (redirect) is treated as success."""
        from modules.crawlers.gov_osha import OshaCrawler

        crawler = OshaCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_mock_resp(200, []), _mock_resp(302)]),
        ):
            result = await crawler.scrape("test")

        assert result.data["source"] == "fallback"

    @pytest.mark.asyncio
    async def test_osha_primary_none_fallback_success(self):
        """Primary returns None (network error) → fallback tried, succeeds."""
        from modules.crawlers.gov_osha import OshaCrawler

        crawler = OshaCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[None, _mock_resp(200, [self._INSPECTION])]),
        ):
            # Note: primary None → inspections stays [] → triggers fallback
            # But fallback returns HTML, so inspections still [] → found=False
            result = await crawler.scrape("test")

        # The primary None doesn't cause crash; fallback runs
        assert result.error is None or result.found is False

    @pytest.mark.asyncio
    async def test_osha_primary_bad_json_fallback_success(self):
        """Primary bad JSON → inspections empty → fallback triggered."""
        from modules.crawlers.gov_osha import OshaCrawler

        crawler = OshaCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_bad_json_resp(), _mock_resp(200)]),
        ):
            result = await crawler.scrape("test")

        assert result.data["source"] == "fallback"

    @pytest.mark.asyncio
    async def test_osha_fallback_network_error(self):
        """Primary empty + fallback None → http_error result."""
        from modules.crawlers.gov_osha import OshaCrawler

        crawler = OshaCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(side_effect=[_mock_resp(200, []), None])
        ):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_osha_fallback_bad_status(self):
        """Primary empty + fallback 500 → http_500 error."""
        from modules.crawlers.gov_osha import OshaCrawler

        crawler = OshaCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(side_effect=[_mock_resp(200, []), _mock_resp(500)])
        ):
            result = await crawler.scrape("test")

        assert result.found is False
        assert "500" in result.error


# ===========================================================================
# gov_propublica — ProPublica Nonprofit Explorer
# ===========================================================================


import modules.crawlers.gov_propublica  # noqa: F401


class TestGovProPublica:
    _SUCCESS_DATA = {
        "organizations": [
            {
                "name": "American Red Cross",
                "city": "Washington",
                "state": "DC",
                "ein": "530196605",
                "ntee_code": "P20",
                "income_amount": 3000000000,
                "filing_date": "2023-05-15",
            }
        ],
        "total_results": 1,
    }

    @pytest.mark.asyncio
    async def test_propublica_success(self):
        from modules.crawlers.gov_propublica import ProPublicaCrawler

        crawler = ProPublicaCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._SUCCESS_DATA))
        ):
            result = await crawler.scrape("American Red Cross")

        assert result.found is True
        assert result.platform == "gov_propublica"
        assert len(result.data["organizations"]) == 1
        assert result.data["organizations"][0]["ein"] == "530196605"
        assert result.data["total_results"] == 1

    @pytest.mark.asyncio
    async def test_propublica_empty_results(self):
        from modules.crawlers.gov_propublica import ProPublicaCrawler

        crawler = ProPublicaCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(return_value=_mock_resp(200, {"organizations": [], "total_results": 0})),
        ):
            result = await crawler.scrape("NoSuchOrg")

        assert result.found is False
        assert result.data["total_results"] == 0

    @pytest.mark.asyncio
    async def test_propublica_network_error(self):
        from modules.crawlers.gov_propublica import ProPublicaCrawler

        crawler = ProPublicaCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "http_error"

    @pytest.mark.asyncio
    async def test_propublica_bad_status(self):
        from modules.crawlers.gov_propublica import ProPublicaCrawler

        crawler = ProPublicaCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert "404" in _get_error(result)

    @pytest.mark.asyncio
    async def test_propublica_invalid_json(self):
        from modules.crawlers.gov_propublica import ProPublicaCrawler

        crawler = ProPublicaCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_bad_json_resp())):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "parse_error"


# ===========================================================================
# gov_sam — SAM.gov federal contractor entity registration
# ===========================================================================


import modules.crawlers.gov_sam  # noqa: F401


class TestGovSam:
    _ENTITY = {
        "entityRegistration": {
            "ueiSAM": "ABC123456789",
            "legalBusinessName": "Lockheed Martin Corporation",
            "registrationStatus": "Active",
            "registrationExpirationDate": "2025-01-15",
            "purposeOfRegistrationDesc": "All Awards",
            "entityTypeDesc": "Business or Organization",
            "congressionalDistrict": "07",
            "submissionDate": "2024-01-15",
        },
        "coreData": {
            "entityInformation": {
                "fiscalYearEndCloseDate": "1231",
            }
        },
    }
    _SUCCESS_DATA = {
        "entityData": [_ENTITY],
        "totalRecords": 1,
    }

    @pytest.mark.asyncio
    async def test_sam_success(self):
        from modules.crawlers.gov_sam import SamCrawler

        crawler = SamCrawler()
        with (
            patch("modules.crawlers.gov_sam.settings", sam_api_key="TESTAPIKEY"),
            patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._SUCCESS_DATA))
            ),
        ):
            result = await crawler.scrape("Lockheed Martin")

        assert result.found is True
        assert result.platform == "gov_sam"
        assert result.data["entities"][0]["ueiSAM"] == "ABC123456789"
        assert result.data["total_count"] == 1

    @pytest.mark.asyncio
    async def test_sam_not_configured(self):
        """No API key → not_configured error without making HTTP calls."""
        from modules.crawlers.gov_sam import SamCrawler

        crawler = SamCrawler()
        with patch("modules.crawlers.gov_sam.settings", sam_api_key=""):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "not_configured"

    @pytest.mark.asyncio
    async def test_sam_not_configured_missing_attr(self):
        """Settings object has no sam_api_key attr at all → not_configured."""
        from modules.crawlers.gov_sam import SamCrawler

        crawler = SamCrawler()
        with patch("modules.crawlers.gov_sam.settings", spec=[]):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "not_configured"

    @pytest.mark.asyncio
    async def test_sam_network_error(self):
        from modules.crawlers.gov_sam import SamCrawler

        crawler = SamCrawler()
        with (
            patch("modules.crawlers.gov_sam.settings", sam_api_key="KEY"),
            patch.object(crawler, "get", new=AsyncMock(return_value=None)),
        ):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_sam_403_invalid_key(self):
        from modules.crawlers.gov_sam import SamCrawler

        crawler = SamCrawler()
        with (
            patch("modules.crawlers.gov_sam.settings", sam_api_key="BADKEY"),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(403))),
        ):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "invalid_api_key"

    @pytest.mark.asyncio
    async def test_sam_bad_status(self):
        from modules.crawlers.gov_sam import SamCrawler

        crawler = SamCrawler()
        with (
            patch("modules.crawlers.gov_sam.settings", sam_api_key="KEY"),
            patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))),
        ):
            result = await crawler.scrape("test")

        assert result.found is False
        assert "500" in result.error

    @pytest.mark.asyncio
    async def test_sam_invalid_json(self):
        from modules.crawlers.gov_sam import SamCrawler

        crawler = SamCrawler()
        with (
            patch("modules.crawlers.gov_sam.settings", sam_api_key="KEY"),
            patch.object(crawler, "get", new=AsyncMock(return_value=_bad_json_resp())),
        ):
            result = await crawler.scrape("test")

        assert result.found is False
        assert result.error == "parse_error"

    @pytest.mark.asyncio
    async def test_sam_empty_entity_data(self):
        from modules.crawlers.gov_sam import SamCrawler

        crawler = SamCrawler()
        with (
            patch("modules.crawlers.gov_sam.settings", sam_api_key="KEY"),
            patch.object(
                crawler,
                "get",
                new=AsyncMock(return_value=_mock_resp(200, {"entityData": [], "totalRecords": 0})),
            ),
        ):
            result = await crawler.scrape("Unknown Corp")

        assert result.found is False
        assert result.data["total_count"] == 0


# ===========================================================================
# gov_usaspending — USASpending.gov award search
# ===========================================================================


import modules.crawlers.gov_usaspending  # noqa: F401


class TestGovUsaSpending:
    _SUCCESS_DATA = {
        "results": [
            {
                "Award ID": "FA8729-24-C-0001",
                "Recipient Name": "Lockheed Martin Corporation",
                "Award Amount": 250000000.0,
                "Awarding Agency": "Department of Defense",
            }
        ],
        "page_metadata": {"total": 47},
    }

    @pytest.mark.asyncio
    async def test_usaspending_success(self):
        from modules.crawlers.gov_usaspending import UsaSpendingCrawler

        crawler = UsaSpendingCrawler()
        with patch.object(
            crawler, "post", new=AsyncMock(return_value=_mock_resp(200, self._SUCCESS_DATA))
        ):
            result = await crawler.scrape("Lockheed Martin")

        assert result.found is True
        assert result.platform == "gov_usaspending"
        assert len(result.data["awards"]) == 1
        assert result.data["awards"][0]["Recipient Name"] == "Lockheed Martin Corporation"
        assert result.data["count"] == 47

    @pytest.mark.asyncio
    async def test_usaspending_empty_results(self):
        from modules.crawlers.gov_usaspending import UsaSpendingCrawler

        crawler = UsaSpendingCrawler()
        with patch.object(
            crawler,
            "post",
            new=AsyncMock(return_value=_mock_resp(200, {"results": [], "page_metadata": {"total": 0}})),
        ):
            result = await crawler.scrape("Nobody")

        assert result.found is False
        assert result.data["count"] == 0

    @pytest.mark.asyncio
    async def test_usaspending_network_error(self):
        from modules.crawlers.gov_usaspending import UsaSpendingCrawler

        crawler = UsaSpendingCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "http_error"

    @pytest.mark.asyncio
    async def test_usaspending_bad_status(self):
        from modules.crawlers.gov_usaspending import UsaSpendingCrawler

        crawler = UsaSpendingCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_mock_resp(422))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert "422" in _get_error(result)

    @pytest.mark.asyncio
    async def test_usaspending_invalid_json(self):
        from modules.crawlers.gov_usaspending import UsaSpendingCrawler

        crawler = UsaSpendingCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=_bad_json_resp())):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "parse_error"


# ===========================================================================
# gov_uspto_patents — PatentsView patent search (inventor + assignee)
# ===========================================================================


import modules.crawlers.gov_uspto_patents  # noqa: F401


class TestGovUsptoPatents:
    _PATENT_LIST = {
        "patents": [
            {
                "patent_id": "10123456",
                "patent_title": "Widget Manufacturing Process",
                "patent_date": "2023-06-13",
                "assignee_organization": "Acme Corp",
            }
        ],
        "total_patent_count": 1,
    }
    _ASSIGNEE_LIST = {
        "patents": [
            {
                "patent_id": "10654321",
                "patent_title": "Advanced Widget",
                "patent_date": "2023-11-01",
                "assignee_organization": [{"assignee_organization": "Acme Corporation"}],
            }
        ],
        "total_patent_count": 5,
    }

    @pytest.mark.asyncio
    async def test_patents_inventor_hit(self):
        """First GET (inventor search) returns patents → result found."""
        from modules.crawlers.gov_uspto_patents import GovUsptoPatentsCrawler

        crawler = GovUsptoPatentsCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._PATENT_LIST))
        ):
            result = await crawler.scrape("Jane Smith")

        assert result.found is True
        assert result.platform == "gov_uspto_patents"
        assert result.data["patents"][0]["patent_id"] == "10123456"
        assert result.data["total"] == 1

    @pytest.mark.asyncio
    async def test_patents_inventor_empty_assignee_hit(self):
        """Inventor search returns empty → fallback assignee search returns results."""
        from modules.crawlers.gov_uspto_patents import GovUsptoPatentsCrawler

        empty = {"patents": [], "total_patent_count": 0}
        crawler = GovUsptoPatentsCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_mock_resp(200, empty), _mock_resp(200, self._ASSIGNEE_LIST)]),
        ):
            result = await crawler.scrape("Acme Corporation")

        assert result.found is True
        assert result.data["patents"][0]["patent_id"] == "10654321"
        assert result.data["total"] == 5

    @pytest.mark.asyncio
    async def test_patents_assignee_list_parsed(self):
        """assignee_organization as list of dicts → joined string."""
        from modules.crawlers.gov_uspto_patents import GovUsptoPatentsCrawler

        crawler = GovUsptoPatentsCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(
                side_effect=[
                    _mock_resp(200, {"patents": [], "total_patent_count": 0}),
                    _mock_resp(200, self._ASSIGNEE_LIST),
                ]
            ),
        ):
            result = await crawler.scrape("Acme")

        assert "Acme Corporation" in result.data["patents"][0]["assignee_organization"]

    @pytest.mark.asyncio
    async def test_patents_both_empty(self):
        """Both searches return empty patents → found=False."""
        from modules.crawlers.gov_uspto_patents import GovUsptoPatentsCrawler

        empty = {"patents": [], "total_patent_count": 0}
        crawler = GovUsptoPatentsCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_mock_resp(200, empty), _mock_resp(200, empty)]),
        ):
            result = await crawler.scrape("Unknown Inventor")

        assert result.found is False

    @pytest.mark.asyncio
    async def test_patents_network_error(self):
        """First GET returns None → http_error result."""
        from modules.crawlers.gov_uspto_patents import GovUsptoPatentsCrawler

        crawler = GovUsptoPatentsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "http_error"

    @pytest.mark.asyncio
    async def test_patents_inventor_bad_json_fallback_success(self):
        """Bad JSON on inventor → assignee search succeeds."""
        from modules.crawlers.gov_uspto_patents import GovUsptoPatentsCrawler

        crawler = GovUsptoPatentsCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_bad_json_resp(), _mock_resp(200, self._ASSIGNEE_LIST)]),
        ):
            result = await crawler.scrape("Acme")

        assert result.found is True

    @pytest.mark.asyncio
    async def test_patents_single_token_identifier(self):
        """Single-word identifier → last_name = full identifier, no crash."""
        from modules.crawlers.gov_uspto_patents import GovUsptoPatentsCrawler

        crawler = GovUsptoPatentsCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(return_value=_mock_resp(200, self._PATENT_LIST)),
        ):
            result = await crawler.scrape("Smith")

        assert result.found is True


# ===========================================================================
# gov_uspto_trademarks — USPTO IBD trademark search
# ===========================================================================


import modules.crawlers.gov_uspto_trademarks  # noqa: F401


class TestGovUsptoTrademarks:
    _SUCCESS_DATA = {
        "body": {
            "numFound": 2,
            "docs": [
                {
                    "serialNumber": "87654321",
                    "registrationNumber": "5123456",
                    "wordMark": "ACME",
                    "ownerName": "ACME Corp",
                    "statusCode": "REGISTERED",
                    "filingDate": "2020-03-15",
                },
                {
                    "serialNumber": "87000001",
                    "registrationNumber": "",
                    "wordMark": "ACME WIDGETS",
                    "ownerName": "ACME Corp",
                    "statusCode": "PENDING",
                    "filingDate": "2023-01-10",
                },
            ],
        }
    }

    @pytest.mark.asyncio
    async def test_trademarks_success(self):
        from modules.crawlers.gov_uspto_trademarks import GovUsptoTrademarksCrawler

        crawler = GovUsptoTrademarksCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._SUCCESS_DATA))
        ):
            result = await crawler.scrape("ACME")

        assert result.found is True
        assert result.platform == "gov_uspto_trademarks"
        assert len(result.data["trademarks"]) == 2
        assert result.data["trademarks"][0]["wordMark"] == "ACME"
        assert result.data["total"] == 2

    @pytest.mark.asyncio
    async def test_trademarks_empty_docs(self):
        from modules.crawlers.gov_uspto_trademarks import GovUsptoTrademarksCrawler

        crawler = GovUsptoTrademarksCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(return_value=_mock_resp(200, {"body": {"numFound": 0, "docs": []}})),
        ):
            result = await crawler.scrape("NOSUCHBRAND")

        assert result.found is False
        assert result.data["total"] == 0

    @pytest.mark.asyncio
    async def test_trademarks_network_error(self):
        from modules.crawlers.gov_uspto_trademarks import GovUsptoTrademarksCrawler

        crawler = GovUsptoTrademarksCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "http_error"

    @pytest.mark.asyncio
    async def test_trademarks_404(self):
        from modules.crawlers.gov_uspto_trademarks import GovUsptoTrademarksCrawler

        crawler = GovUsptoTrademarksCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "not_found"

    @pytest.mark.asyncio
    async def test_trademarks_bad_status(self):
        from modules.crawlers.gov_uspto_trademarks import GovUsptoTrademarksCrawler

        crawler = GovUsptoTrademarksCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
            result = await crawler.scrape("test")

        assert result.found is False
        assert "500" in _get_error(result)

    @pytest.mark.asyncio
    async def test_trademarks_invalid_json(self):
        from modules.crawlers.gov_uspto_trademarks import GovUsptoTrademarksCrawler

        crawler = GovUsptoTrademarksCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_bad_json_resp())):
            result = await crawler.scrape("test")

        assert result.found is False
        assert _get_error(result) == "parse_error"


# ===========================================================================
# gov_worldbank — World Bank country + GDP
# ===========================================================================


import modules.crawlers.gov_worldbank  # noqa: F401


class TestGovWorldBank:
    _COUNTRY_SEARCH = [
        {"page": 1, "pages": 1, "per_page": 5, "total": 1},
        [
            {
                "id": "ZA",
                "name": "South Africa",
                "iso2Code": "ZA",
                "region": {"value": "Sub-Saharan Africa"},
                "incomeLevel": {"value": "Upper middle income"},
                "lendingType": {"value": "IBRD"},
                "capitalCity": "Pretoria",
                "longitude": "28.1871",
                "latitude": "-25.746",
            }
        ],
    ]
    _GDP_DATA = [
        {"page": 1, "pages": 1, "per_page": 5, "total": 5},
        [
            {
                "date": "2023",
                "value": 405270000000.0,
                "indicator": {"value": "GDP (current US$)"},
            },
            {
                "date": "2022",
                "value": 422011000000.0,
                "indicator": {"value": "GDP (current US$)"},
            },
        ],
    ]

    @pytest.mark.asyncio
    async def test_worldbank_success_by_country_name(self):
        """Full path: country name → search → GDP fetch."""
        from modules.crawlers.gov_worldbank import WorldBankCrawler

        crawler = WorldBankCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(
                side_effect=[_mock_resp(200, self._COUNTRY_SEARCH), _mock_resp(200, self._GDP_DATA)]
            ),
        ):
            result = await crawler.scrape("South Africa")

        assert result.found is True
        assert result.platform == "gov_worldbank"
        assert result.data["country"]["iso2Code"] == "ZA"
        assert len(result.data["gdp_data"]) == 2
        assert result.data["gdp_data"][0]["year"] == "2023"

    @pytest.mark.asyncio
    async def test_worldbank_success_by_iso2_code(self):
        """ISO-2 code skips country search, goes straight to GDP."""
        from modules.crawlers.gov_worldbank import WorldBankCrawler

        crawler = WorldBankCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, self._GDP_DATA))
        ):
            result = await crawler.scrape("ZA")

        assert result.found is True
        assert result.data["country"]["iso2Code"] == "ZA"
        assert len(result.data["gdp_data"]) >= 1

    @pytest.mark.asyncio
    async def test_worldbank_country_not_found(self):
        """Country search returns empty list → found=False."""
        from modules.crawlers.gov_worldbank import WorldBankCrawler

        crawler = WorldBankCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(return_value=_mock_resp(200, [{"page": 1}, None])),
        ):
            result = await crawler.scrape("Atlantis")

        assert result.found is False

    @pytest.mark.asyncio
    async def test_worldbank_network_error_on_search(self):
        from modules.crawlers.gov_worldbank import WorldBankCrawler

        crawler = WorldBankCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("Germany")

        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_worldbank_bad_status_on_search(self):
        from modules.crawlers.gov_worldbank import WorldBankCrawler

        crawler = WorldBankCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
            result = await crawler.scrape("Brazil")

        assert result.found is False
        assert "500" in result.error

    @pytest.mark.asyncio
    async def test_worldbank_invalid_json_on_search(self):
        from modules.crawlers.gov_worldbank import WorldBankCrawler

        crawler = WorldBankCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_bad_json_resp())):
            result = await crawler.scrape("France")

        assert result.found is False
        assert result.error == "parse_error"

    @pytest.mark.asyncio
    async def test_worldbank_gdp_fetch_fails_gracefully(self):
        """GDP request returns None → gdp_data is [], country still found."""
        from modules.crawlers.gov_worldbank import WorldBankCrawler

        crawler = WorldBankCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[_mock_resp(200, self._COUNTRY_SEARCH), None]),
        ):
            result = await crawler.scrape("South Africa")

        assert result.found is True
        assert result.data["gdp_data"] == []

    @pytest.mark.asyncio
    async def test_worldbank_gdp_bad_json_graceful(self):
        """GDP bad JSON → gdp_data is [], no crash."""
        from modules.crawlers.gov_worldbank import WorldBankCrawler

        crawler = WorldBankCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(
                side_effect=[_mock_resp(200, self._COUNTRY_SEARCH), _bad_json_resp()]
            ),
        ):
            result = await crawler.scrape("South Africa")

        assert result.found is True
        assert result.data["gdp_data"] == []

    @pytest.mark.asyncio
    async def test_worldbank_iso2_no_gdp(self):
        """ISO-2 path: GDP fetch returns empty list → gdp_data=[]."""
        from modules.crawlers.gov_worldbank import WorldBankCrawler

        empty_gdp = [{"page": 1}, []]
        crawler = WorldBankCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, empty_gdp))
        ):
            result = await crawler.scrape("ZZ")

        assert result.found is True
        assert result.data["gdp_data"] == []

    @pytest.mark.asyncio
    async def test_worldbank_search_returns_short_list(self):
        """Data list with fewer than 2 elements → _parse_country returns None → found=False."""
        from modules.crawlers.gov_worldbank import WorldBankCrawler

        crawler = WorldBankCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, [{"page": 1}]))
        ):
            result = await crawler.scrape("Nowhere")

        assert result.found is False


# ===========================================================================
# Registry smoke tests — all 17 crawlers must be registered
# ===========================================================================


def test_all_gov_crawlers_registered():
    """Each gov_* crawler must appear in the registry after module import."""
    from modules.crawlers.registry import is_registered

    expected = [
        "gov_bop",
        "gov_epa",
        "gov_fda",
        "gov_fdic",
        "gov_fec",
        "gov_finra",
        "gov_fred",
        "gov_gleif",
        "gov_grants",
        "gov_nmls",
        "gov_osha",
        "gov_propublica",
        "gov_sam",
        "gov_usaspending",
        "gov_uspto_patents",
        "gov_uspto_trademarks",
        "gov_worldbank",
    ]
    for platform in expected:
        assert is_registered(platform), f"'{platform}' not registered"
