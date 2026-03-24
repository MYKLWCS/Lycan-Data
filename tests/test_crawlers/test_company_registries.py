"""
Tests for Company Registry scrapers — Task 24.
  - OpenCorporatesCrawler    (company_opencorporates)
  - SECEdgarCrawler          (company_sec)
  - CompaniesHouseCrawler    (company_companies_house)

15 tests total — all HTTP calls are mocked.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Trigger @register decorators
import modules.crawlers.company_opencorporates   # noqa: F401
import modules.crawlers.company_sec              # noqa: F401
import modules.crawlers.company_companies_house  # noqa: F401

from modules.crawlers.company_opencorporates import (
    OpenCorporatesCrawler,
    _parse_companies as oc_parse_companies,
    _parse_officers  as oc_parse_officers,
)
from modules.crawlers.company_sec import (
    SECEdgarCrawler,
    _parse_atom_feed,
)
from modules.crawlers.company_companies_house import (
    CompaniesHouseCrawler,
    _parse_companies as ch_parse_companies,
    _parse_officers  as ch_parse_officers,
)
from modules.crawlers.registry import is_registered


# ===========================================================================
# Helpers
# ===========================================================================

def _mock_resp(status: int = 200, json_data: dict | None = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


# ---- Sample payloads ----

OC_COMPANY_JSON = {
    "results": {
        "companies": [
            {
                "company": {
                    "name": "Acme Corp",
                    "company_number": "GB12345",
                    "jurisdiction_code": "gb",
                    "registered_address": {"in_full": "1 High St, London"},
                    "current_status": "Active",
                    "incorporation_date": "2005-06-01",
                    "company_type": "Private Limited Company",
                    "opencorporates_url": "https://opencorporates.com/companies/gb/12345",
                }
            }
        ]
    }
}

OC_OFFICER_JSON = {
    "results": {
        "officers": [
            {
                "officer": {
                    "name": "John Smith",
                    "position": "Director",
                    "company": {
                        "name": "Acme Corp",
                        "jurisdiction_code": "gb",
                        "opencorporates_url": "https://opencorporates.com/companies/gb/12345",
                    },
                    "start_date": "2010-01-01",
                    "end_date": None,
                }
            }
        ]
    }
}

SAMPLE_ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>EDGAR Company Search</title>
  <entry>
    <title>10-K for ACME CORP (CIK: 0001234567)</title>
    <updated>2024-03-15T00:00:00-04:00</updated>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001234567"/>
    <category label="10-K" term="form-type"/>
    <content>CIK: 0001234567 ACME CORP annual report</content>
  </entry>
  <entry>
    <title>8-K for ACME CORP</title>
    <updated>2023-11-01T00:00:00-04:00</updated>
    <link href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001234567&amp;type=8-K"/>
    <category label="8-K" term="form-type"/>
    <content>CIK: 0001234567 current report</content>
  </entry>
</feed>"""

EMPTY_ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>EDGAR Company Search</title>
</feed>"""

CH_COMPANY_JSON = {
    "items": [
        {
            "title": "Acme UK Ltd",
            "company_number": "12345678",
            "company_status": "active",
            "date_of_creation": "2010-03-15",
            "address_snippet": "1 High Street, London, EC1A 1BB",
            "company_type": "ltd",
        }
    ]
}

CH_OFFICER_JSON = {
    "items": [
        {
            "title": "John Smith",
            "date_of_birth": {"month": 6, "year": 1975},
            "appointment_count": 3,
            "links": {"self": "/officers/abc123/appointments"},
        }
    ]
}


# ===========================================================================
# 1. Registry tests
# ===========================================================================

def test_opencorporates_registered():
    assert is_registered("company_opencorporates")


def test_sec_registered():
    assert is_registered("company_sec")


def test_companies_house_registered():
    assert is_registered("company_companies_house")


# ===========================================================================
# 2. _parse_companies / _parse_officers — OpenCorporates
# ===========================================================================

def test_oc_parse_companies():
    companies = oc_parse_companies(OC_COMPANY_JSON)
    assert len(companies) == 1
    co = companies[0]
    assert co["name"] == "Acme Corp"
    assert co["jurisdiction"] == "gb"
    assert co["status"] == "Active"
    assert "opencorporates.com" in co["url"]


def test_oc_parse_officers():
    officers = oc_parse_officers(OC_OFFICER_JSON)
    assert len(officers) == 1
    off = officers[0]
    assert off["name"] == "John Smith"
    assert off["position"] == "Director"
    assert off["company_name"] == "Acme Corp"


# ===========================================================================
# 3. OpenCorporatesCrawler — scrape()
# ===========================================================================

@pytest.mark.asyncio
async def test_oc_company_found():
    crawler = OpenCorporatesCrawler()
    mock_co = _mock_resp(200, json_data=OC_COMPANY_JSON)
    mock_off = _mock_resp(200, json_data=OC_OFFICER_JSON)
    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
        result = await crawler.scrape("Acme Corp")
    assert result.found is True
    assert len(result.data["companies"]) == 1
    assert result.data["companies"][0]["name"] == "Acme Corp"


@pytest.mark.asyncio
async def test_oc_officer_found():
    crawler = OpenCorporatesCrawler()
    mock_co = _mock_resp(200, json_data={"results": {"companies": []}})
    mock_off = _mock_resp(200, json_data=OC_OFFICER_JSON)
    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
        result = await crawler.scrape("John Smith")
    assert result.found is True
    assert len(result.data["officers"]) == 1


@pytest.mark.asyncio
async def test_oc_not_found():
    crawler = OpenCorporatesCrawler()
    empty = {"results": {"companies": []}}
    empty_off = {"results": {"officers": []}}
    mock_co = _mock_resp(200, json_data=empty)
    mock_off = _mock_resp(200, json_data=empty_off)
    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
        result = await crawler.scrape("Nobody Zzzxxx")
    assert result.found is False
    assert result.data["result_count"] == 0


@pytest.mark.asyncio
async def test_oc_http_error():
    crawler = OpenCorporatesCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("Acme Corp")
    assert result.found is False
    assert result.data.get("error") == "http_error" or result.error is not None


# ===========================================================================
# 4. _parse_atom_feed — SEC
# ===========================================================================

def test_sec_parse_atom_feed():
    filings = _parse_atom_feed(SAMPLE_ATOM_XML)
    assert len(filings) == 2
    assert filings[0]["form_type"] == "10-K"
    assert "sec.gov" in filings[0]["url"]
    assert filings[0]["date"] == "2024-03-15"


def test_sec_parse_atom_feed_empty():
    filings = _parse_atom_feed(EMPTY_ATOM_XML)
    assert filings == []


def test_sec_parse_atom_feed_invalid_xml():
    filings = _parse_atom_feed("<<< not xml >>>")
    assert filings == []


# ===========================================================================
# 5. SECEdgarCrawler — scrape()
# ===========================================================================

@pytest.mark.asyncio
async def test_sec_filings_found():
    crawler = SECEdgarCrawler()
    mock_atom = _mock_resp(200, text=SAMPLE_ATOM_XML)
    # FTS call returns empty
    mock_fts = _mock_resp(200, json_data={"hits": {"hits": []}})
    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_atom, mock_fts])):
        result = await crawler.scrape("Acme Corp")
    assert result.found is True
    assert result.data["result_count"] >= 2
    assert result.data["filings"][0]["form_type"] == "10-K"


@pytest.mark.asyncio
async def test_sec_not_found():
    crawler = SECEdgarCrawler()
    mock_atom = _mock_resp(200, text=EMPTY_ATOM_XML)
    mock_fts = _mock_resp(200, json_data={"hits": {"hits": []}})
    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_atom, mock_fts])):
        result = await crawler.scrape("Nobody Zzzxxx")
    assert result.found is False
    assert result.data["result_count"] == 0


@pytest.mark.asyncio
async def test_sec_http_error():
    crawler = SECEdgarCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("Acme Corp")
    assert result.found is False
    assert result.data.get("error") == "http_error" or result.error is not None


# ===========================================================================
# 6. _parse_companies / _parse_officers — Companies House
# ===========================================================================

def test_ch_parse_companies():
    companies = ch_parse_companies(CH_COMPANY_JSON)
    assert len(companies) == 1
    co = companies[0]
    assert co["name"] == "Acme UK Ltd"
    assert co["company_number"] == "12345678"
    assert co["status"] == "active"
    assert "find-and-update" in co["url"]


def test_ch_parse_officers():
    officers = ch_parse_officers(CH_OFFICER_JSON)
    assert len(officers) == 1
    off = officers[0]
    assert off["name"] == "John Smith"
    assert off["dob_year"] == 1975
    assert off["appointment_count"] == 3


# ===========================================================================
# 7. CompaniesHouseCrawler — scrape()
# ===========================================================================

@pytest.mark.asyncio
async def test_ch_company_found():
    crawler = CompaniesHouseCrawler()
    mock_co = _mock_resp(200, json_data=CH_COMPANY_JSON)
    mock_off = _mock_resp(200, json_data={"items": []})
    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
        result = await crawler.scrape("Acme UK Ltd")
    assert result.found is True
    assert result.data["companies"][0]["name"] == "Acme UK Ltd"


@pytest.mark.asyncio
async def test_ch_officer_found():
    crawler = CompaniesHouseCrawler()
    mock_co = _mock_resp(200, json_data={"items": []})
    mock_off = _mock_resp(200, json_data=CH_OFFICER_JSON)
    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
        result = await crawler.scrape("John Smith")
    assert result.found is True
    assert len(result.data["officers"]) == 1


@pytest.mark.asyncio
async def test_ch_not_found():
    crawler = CompaniesHouseCrawler()
    mock_co = _mock_resp(200, json_data={"items": []})
    mock_off = _mock_resp(200, json_data={"items": []})
    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
        result = await crawler.scrape("Nobody Zzzxxx")
    assert result.found is False
    assert result.data["result_count"] == 0


@pytest.mark.asyncio
async def test_ch_http_error():
    crawler = CompaniesHouseCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("Acme Corp")
    assert result.found is False
    assert result.data.get("error") == "http_error" or result.error is not None
