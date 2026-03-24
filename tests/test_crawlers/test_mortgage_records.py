"""
Tests for Mortgage & Loan Records scrapers — Tasks 36.
  - MortgageHmdaCrawler    (mortgage_hmda)
  - MortgageDeedCrawler    (mortgage_deed)
  - BankruptcyPacerCrawler (bankruptcy_pacer)

15 tests total — HTTP calls are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.bankruptcy_pacer  # noqa: F401
import modules.crawlers.mortgage_deed  # noqa: F401

# Trigger @register decorators
import modules.crawlers.mortgage_hmda  # noqa: F401
from modules.crawlers.bankruptcy_pacer import (
    BankruptcyPacerCrawler,
    _parse_cfpb_complaints,
    _parse_recap_results,
)
from modules.crawlers.mortgage_deed import (
    MortgageDeedCrawler,
    _parse_publicrecordsnow_html,
)
from modules.crawlers.mortgage_hmda import (
    MortgageHmdaCrawler,
    _parse_hmda_aggregations,
)
from modules.crawlers.mortgage_hmda import (
    _parse_identifier as _hmda_parse_id,
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


# Sample HMDA aggregations response
SAMPLE_HMDA_JSON = {
    "aggregations": [
        {
            "count": 120,
            "loan_amount": 285000,
            "income": 85000,
            "lei": "BANK_OF_AMERICA",
            "action_taken": "1",  # originated
        },
        {
            "count": 30,
            "loan_amount": 195000,
            "income": 65000,
            "lei": "WELLS_FARGO",
            "action_taken": "denied",
        },
    ]
}

# Sample deed/mortgage HTML
SAMPLE_DEED_HTML = """
<html><body>
  <div class="result-item">
    Owner: John Smith
    123 Oak Street, Austin TX 78701
    Deed Date: 03/15/2022
    Mortgage: $325,000
    Lender: First National Bank
    Type: Deed of Trust
  </div>
  <div class="result-item">
    Owner: John Smith
    456 Elm Ave, Austin TX 78702
    Deed Date: 07/20/2019
    Mortgage: $210,000
    Lender: Wells Fargo
    Type: Warranty Deed
  </div>
</body></html>
"""

# Sample CourtListener RECAP response
SAMPLE_RECAP_JSON = {
    "count": 2,
    "results": [
        {
            "caseName": "In re: John Smith",
            "court": "txnb",
            "dateFiled": "2021-05-10",
            "status": "Closed",
            "nature_of_suit": "Chapter 7",
            "absolute_url": "/docket/11111/",
            "assets": "50000",
            "liabilities": "120000",
        },
        {
            "caseName": "Smith v. Creditor LLC",
            "court": "txnb",
            "dateFiled": "2020-03-01",
            "status": "Active",
            "nature_of_suit": "",
            "absolute_url": "/docket/22222/",
            "assets": None,
            "liabilities": None,
        },
    ],
}

# Sample CFPB complaints response
SAMPLE_CFPB_JSON = {
    "hits": {
        "hits": [
            {
                "_source": {
                    "product": "Mortgage",
                    "sub_product": "Conventional home mortgage",
                    "issue": "Struggling to pay mortgage",
                    "company": "First National Bank",
                    "date_received": "2023-09-15",
                    "company_response": "Closed with explanation",
                    "complaint_id": "6543210",
                }
            },
            {
                "_source": {
                    "product": "Debt collection",
                    "sub_product": "Mortgage debt",
                    "issue": "Attempts to collect debt not owed",
                    "company": "Wells Fargo",
                    "date_received": "2023-11-01",
                    "company_response": "In progress",
                    "complaint_id": "7654321",
                }
            },
        ]
    }
}


# ===========================================================================
# 1. Registry tests
# ===========================================================================


def test_mortgage_hmda_registered():
    assert is_registered("mortgage_hmda")


def test_mortgage_deed_registered():
    assert is_registered("mortgage_deed")


def test_bankruptcy_pacer_registered():
    assert is_registered("bankruptcy_pacer")


# ===========================================================================
# 2. _parse_identifier (HMDA)
# ===========================================================================


def test_hmda_parse_identifier_city_state():
    city, state, zip_code = _hmda_parse_id("Austin,TX")
    assert city == "Austin"
    assert state == "TX"
    assert zip_code == ""


def test_hmda_parse_identifier_zip():
    city, state, zip_code = _hmda_parse_id("78701")
    assert zip_code == "78701"
    assert city == ""
    assert state == ""


# ===========================================================================
# 3. _parse_hmda_aggregations
# ===========================================================================


def test_parse_hmda_aggregations_totals():
    summary = _parse_hmda_aggregations(SAMPLE_HMDA_JSON)
    assert summary["total_loans"] == 150  # 120 + 30
    assert summary["denial_rate"] is not None
    assert 0 < summary["denial_rate"] < 1


def test_parse_hmda_aggregations_top_lenders():
    summary = _parse_hmda_aggregations(SAMPLE_HMDA_JSON)
    assert len(summary["top_lenders"]) >= 1
    # Top lender should be bank of america (120 loans vs 30)
    assert summary["top_lenders"][0]["lender"] == "BANK_OF_AMERICA"


def test_parse_hmda_aggregations_empty():
    summary = _parse_hmda_aggregations({})
    assert summary["total_loans"] == 0
    assert summary["top_lenders"] == []


# ===========================================================================
# 4. MortgageHmdaCrawler — scrape()
# ===========================================================================


@pytest.mark.asyncio
async def test_hmda_found():
    """Valid city/state returns aggregate data."""
    crawler = MortgageHmdaCrawler()
    mock_resp = _mock_resp(200, json_data=SAMPLE_HMDA_JSON)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("Austin,TX")

    assert result.found is True
    assert result.data["total_loans"] == 150
    assert result.data["city"] == "Austin"
    assert result.data["state"] == "TX"


@pytest.mark.asyncio
async def test_hmda_http_error():
    """Network failure returns error result."""
    crawler = MortgageHmdaCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("Austin,TX")
    assert result.found is False
    assert result.data.get("error") == "http_error"


@pytest.mark.asyncio
async def test_hmda_not_found_empty_response():
    """Empty aggregations → found=False."""
    crawler = MortgageHmdaCrawler()
    mock_resp = _mock_resp(200, json_data={"aggregations": []})
    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("Nowhere,ZZ")
    assert result.found is False
    assert result.data["total_loans"] == 0


# ===========================================================================
# 5. _parse_publicrecordsnow_html
# ===========================================================================


def test_parse_deed_html_finds_records():
    records = _parse_publicrecordsnow_html(SAMPLE_DEED_HTML)
    assert len(records) >= 1


def test_parse_deed_html_empty():
    records = _parse_publicrecordsnow_html("<html><body></body></html>")
    assert records == []


# ===========================================================================
# 6. MortgageDeedCrawler — scrape()
# ===========================================================================


@pytest.mark.asyncio
async def test_deed_found():
    """HTML with deed records → found result."""
    crawler = MortgageDeedCrawler()
    mock_resp_obj = _mock_resp(200, text=SAMPLE_DEED_HTML)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp_obj)):
        result = await crawler.scrape("John Smith")

    assert result.found is True
    assert result.data["result_count"] >= 1


@pytest.mark.asyncio
async def test_deed_http_error():
    crawler = MortgageDeedCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("John Smith")
    assert result.found is False
    assert result.data.get("error") == "http_error"


@pytest.mark.asyncio
async def test_deed_bad_status():
    crawler = MortgageDeedCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(403))):
        result = await crawler.scrape("John Smith")
    assert result.found is False


# ===========================================================================
# 7. _parse_recap_results
# ===========================================================================


def test_parse_recap_results_extracts_fields():
    cases = _parse_recap_results(SAMPLE_RECAP_JSON)
    assert len(cases) == 2
    assert cases[0]["case_name"] == "In re: John Smith"
    assert cases[0]["court"] == "txnb"
    assert "courtlistener.com" in cases[0]["docket_url"]


def test_parse_recap_chapter_detection():
    cases = _parse_recap_results(SAMPLE_RECAP_JSON)
    # "Chapter 7" in nature_of_suit → chapter == "7"
    assert cases[0]["chapter"] == "7"


def test_parse_recap_results_empty():
    cases = _parse_recap_results({"count": 0, "results": []})
    assert cases == []


# ===========================================================================
# 8. _parse_cfpb_complaints
# ===========================================================================


def test_parse_cfpb_complaints_extracts_fields():
    complaints = _parse_cfpb_complaints(SAMPLE_CFPB_JSON)
    assert len(complaints) == 2
    assert complaints[0]["product"] == "Mortgage"
    assert complaints[0]["company"] == "First National Bank"
    assert complaints[0]["complaint_id"] == "6543210"


# ===========================================================================
# 9. BankruptcyPacerCrawler — scrape()
# ===========================================================================


@pytest.mark.asyncio
async def test_bankruptcy_found():
    """RECAP + CFPB both return data → cases + complaints populated."""
    crawler = BankruptcyPacerCrawler()
    mock_recap = _mock_resp(200, json_data=SAMPLE_RECAP_JSON)
    mock_cfpb = _mock_resp(200, json_data=SAMPLE_CFPB_JSON)

    with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_recap, mock_cfpb])):
        result = await crawler.scrape("John Smith")

    assert result.found is True
    assert result.data["case_count"] == 2
    assert len(result.data["cases"]) == 2
    assert len(result.data["complaints"]) == 2


@pytest.mark.asyncio
async def test_bankruptcy_http_error():
    crawler = BankruptcyPacerCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("John Smith")
    assert result.found is False
    assert result.data.get("error") == "http_error"


@pytest.mark.asyncio
async def test_bankruptcy_not_found():
    """Empty results from both sources → found=False."""
    crawler = BankruptcyPacerCrawler()
    empty_recap = _mock_resp(200, json_data={"count": 0, "results": []})
    empty_cfpb = _mock_resp(200, json_data={"hits": {"hits": []}})

    with patch.object(crawler, "get", new=AsyncMock(side_effect=[empty_recap, empty_cfpb])):
        result = await crawler.scrape("Nobody Xyzzy")

    assert result.found is False
    assert result.data["case_count"] == 0
    assert result.data["complaints"] == []


@pytest.mark.asyncio
async def test_bankruptcy_json_parse_error():
    """Invalid JSON from RECAP → error result."""
    crawler = BankruptcyPacerCrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json = MagicMock(side_effect=ValueError("bad json"))
    with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("John Smith")
    assert result.found is False
    assert "error" in result.data or result.error is not None
