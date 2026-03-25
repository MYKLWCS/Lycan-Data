"""
Tests for Public Records scrapers — Task 26.
  - PublicNPICrawler   (public_npi)
  - PublicFAACrawler   (public_faa)
  - PublicNSOPWCrawler (public_nsopw)
  - PublicVoterCrawler (public_voter)

16 tests total — all HTTP calls are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.public_faa  # noqa: F401

# Trigger @register decorators
import modules.crawlers.public_npi  # noqa: F401
import modules.crawlers.public_nsopw  # noqa: F401
import modules.crawlers.public_voter  # noqa: F401
from modules.crawlers.public_faa import (
    PublicFAACrawler,
    _extract_viewstate,
    _parse_airmen_html,
)
from modules.crawlers.public_faa import (
    _split_name as faa_split_name,
)
from modules.crawlers.public_npi import (
    PublicNPICrawler,
    _parse_providers,
)
from modules.crawlers.public_npi import (
    _split_name as npi_split_name,
)
from modules.crawlers.public_nsopw import (
    PublicNSOPWCrawler,
    _parse_offenders,
)
from modules.crawlers.public_nsopw import (
    _split_name as nsopw_split_name,
)
from modules.crawlers.public_voter import (
    PublicVoterCrawler,
    _parse_voter_response,
)
from modules.crawlers.public_voter import (
    _parse_identifier as voter_parse_identifier,
)
from modules.crawlers.registry import is_registered

# ===========================================================================
# Helper factories
# ===========================================================================


def _mock_resp(status: int = 200, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("no json"))
    return resp


# ===========================================================================
# Sample data
# ===========================================================================

SAMPLE_NPI_JSON = {
    "result_count": 2,
    "results": [
        {
            "number": "1234567890",
            "basic": {
                "first_name": "John",
                "last_name": "Smith",
                "credential": "MD",
                "gender": "M",
                "enumeration_date": "2005-03-15",
                "status": "A",
            },
            "addresses": [
                {
                    "address_1": "100 Hospital Dr",
                    "city": "Austin",
                    "state": "TX",
                    "postal_code": "78701",
                    "address_purpose": "LOCATION",
                }
            ],
            "taxonomies": [{"desc": "Internal Medicine", "primary": True}],
        },
        {
            "number": "0987654321",
            "basic": {
                "first_name": "John",
                "last_name": "Smith",
                "credential": "DO",
                "gender": "M",
                "enumeration_date": "2010-07-20",
                "status": "A",
            },
            "addresses": [
                {
                    "address_1": "200 Clinic Blvd",
                    "city": "Dallas",
                    "state": "TX",
                    "postal_code": "75201",
                    "address_purpose": "LOCATION",
                }
            ],
            "taxonomies": [{"desc": "Family Medicine", "primary": True}],
        },
    ],
}

SAMPLE_FAA_GET_HTML = """
<html><body>
<form method="post">
<input type="hidden" name="__VIEWSTATE" value="abc123" />
<input type="hidden" name="__VIEWSTATEGENERATOR" value="def456" />
<input type="hidden" name="__EVENTVALIDATION" value="ghi789" />
</form>
</body></html>
"""

SAMPLE_FAA_POST_HTML = """
<html><body>
<table>
  <tr>
    <th>Certificate Number</th>
    <th>First Name</th>
    <th>Last Name</th>
    <th>City</th>
    <th>State</th>
    <th>Certificates</th>
  </tr>
  <tr>
    <td>123456789</td>
    <td>John</td>
    <td>Smith</td>
    <td>Dallas</td>
    <td>TX</td>
    <td>Private Pilot, Instrument Rating</td>
  </tr>
</table>
</body></html>
"""

SAMPLE_NSOPW_JSON = {
    "TotalRecordCount": 1,
    "Records": [
        {
            "FullName": "JOHN SMITH",
            "Address": "500 Oak St",
            "City": "Houston",
            "State": "TX",
            "DOB": "1980-04-12",
            "Conviction": "Indecent Exposure",
        }
    ],
}

SAMPLE_VOTER_JSON = {
    "Registered": True,
    "CountyName": "Wayne",
    "JurisdictionName": "Detroit",
    "VoterStatus": "Active",
}


# ===========================================================================
# 1. Registry tests
# ===========================================================================


def test_npi_registered():
    assert is_registered("public_npi")


def test_faa_registered():
    assert is_registered("public_faa")


def test_nsopw_registered():
    assert is_registered("public_nsopw")


def test_voter_registered():
    assert is_registered("public_voter")


# ===========================================================================
# 2. Utility function tests
# ===========================================================================


def test_npi_split_name():
    first, last = npi_split_name("Jane Doe")
    assert first == "Jane"
    assert last == "Doe"


def test_voter_parse_identifier_full():
    parsed = voter_parse_identifier("John Smith|03|1985|Detroit")
    assert parsed["first"] == "John"
    assert parsed["last"] == "Smith"
    assert parsed["month"] == "03"
    assert parsed["year"] == "1985"
    assert parsed["city"] == "Detroit"


def test_voter_parse_identifier_name_only():
    parsed = voter_parse_identifier("Alice Brown")
    assert parsed["first"] == "Alice"
    assert parsed["last"] == "Brown"
    assert parsed["month"] == ""
    assert parsed["year"] == ""


def test_faa_extract_viewstate():
    fields = _extract_viewstate(SAMPLE_FAA_GET_HTML)
    assert fields["__VIEWSTATE"] == "abc123"
    assert fields["__VIEWSTATEGENERATOR"] == "def456"
    assert fields["__EVENTVALIDATION"] == "ghi789"


# ===========================================================================
# 3. Parse helpers
# ===========================================================================


def test_parse_providers():
    providers = _parse_providers(SAMPLE_NPI_JSON)
    assert len(providers) == 2
    assert providers[0]["npi"] == "1234567890"
    assert providers[0]["credential"] == "MD"
    assert providers[0]["specialty"] == "Internal Medicine"
    assert providers[0]["state"] == "TX"


def test_parse_airmen_html():
    pilots = _parse_airmen_html(SAMPLE_FAA_POST_HTML)
    assert len(pilots) == 1
    assert pilots[0]["certificate_number"] == "123456789"
    assert pilots[0]["name"] == "John Smith"
    assert "Private Pilot" in pilots[0]["certificates"]


def test_parse_offenders():
    offenders = _parse_offenders(SAMPLE_NSOPW_JSON)
    assert len(offenders) == 1
    assert offenders[0]["name"] == "JOHN SMITH"
    assert offenders[0]["state"] == "TX"
    assert offenders[0]["conviction"] == "Indecent Exposure"


def test_parse_voter_response():
    info = _parse_voter_response(SAMPLE_VOTER_JSON)
    assert info["registered"] is True
    assert info["county"] == "Wayne"
    assert info["jurisdiction"] == "Detroit"


# ===========================================================================
# 4. PublicNPICrawler.scrape() — mocked
# ===========================================================================


@pytest.mark.asyncio
async def test_npi_found():
    crawler = PublicNPICrawler()
    mock_resp = _mock_resp(200, json_data=SAMPLE_NPI_JSON)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("John Smith")

    assert result.found is True
    assert result.data["result_count"] == 2
    assert len(result.data["providers"]) == 2
    assert result.data["providers"][0]["npi"] == "1234567890"


@pytest.mark.asyncio
async def test_npi_not_found():
    crawler = PublicNPICrawler()
    mock_resp = _mock_resp(200, json_data={"result_count": 0, "results": []})

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("Nobody Zzzxxx")

    assert result.found is False
    assert result.data["result_count"] == 0


@pytest.mark.asyncio
async def test_npi_http_error():
    crawler = PublicNPICrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("John Smith")
    assert result.found is False
    assert result.data.get("error") == "http_error" or result.error is not None


# ===========================================================================
# 5. PublicFAACrawler.scrape() — mocked
# ===========================================================================


@pytest.mark.asyncio
async def test_faa_found():
    crawler = PublicFAACrawler()
    get_resp = _mock_resp(200, text=SAMPLE_FAA_GET_HTML)
    post_resp = _mock_resp(200, text=SAMPLE_FAA_POST_HTML)
    # get returns GET response, post returns POST response
    with (
        patch.object(crawler, "get", new=AsyncMock(return_value=get_resp)),
        patch.object(crawler, "post", new=AsyncMock(return_value=post_resp)),
    ):
        result = await crawler.scrape("John Smith")

    assert result.found is True
    assert result.data["result_count"] == 1
    assert result.data["pilots"][0]["certificate_number"] == "123456789"


@pytest.mark.asyncio
async def test_faa_http_error_on_get():
    crawler = PublicFAACrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("John Smith")
    assert result.found is False
    assert "error" in result.data or result.error is not None


# ===========================================================================
# 6. PublicNSOPWCrawler.scrape() — mocked
# ===========================================================================


@pytest.mark.asyncio
async def test_nsopw_found():
    crawler = PublicNSOPWCrawler()
    mock_resp = _mock_resp(200, json_data=SAMPLE_NSOPW_JSON)

    with patch.object(crawler, "post", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("John Smith")

    assert result.found is True
    assert result.data["result_count"] == 1
    assert result.data["offenders"][0]["name"] == "JOHN SMITH"


@pytest.mark.asyncio
async def test_nsopw_not_found():
    crawler = PublicNSOPWCrawler()
    mock_resp = _mock_resp(200, json_data={"TotalRecordCount": 0, "Records": []})

    with patch.object(crawler, "post", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("Nobody Zzzxxx")

    assert result.found is False
    assert result.data["result_count"] == 0


@pytest.mark.asyncio
async def test_nsopw_http_error():
    crawler = PublicNSOPWCrawler()
    with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("John Smith")
    assert result.found is False


# ===========================================================================
# 7. PublicVoterCrawler.scrape() — mocked
# ===========================================================================


@pytest.mark.asyncio
async def test_voter_registered():
    crawler = PublicVoterCrawler()
    mock_resp = _mock_resp(200, json_data=SAMPLE_VOTER_JSON)

    with patch.object(crawler, "post", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("John Smith|03|1985")

    assert result.found is True
    assert result.data["registered"] is True
    assert result.data["state"] == "MI"
    assert result.data["county"] == "Wayne"


@pytest.mark.asyncio
async def test_voter_not_registered():
    crawler = PublicVoterCrawler()
    mock_resp = _mock_resp(
        200,
        json_data={
            "Registered": False,
            "CountyName": None,
            "JurisdictionName": None,
            "VoterStatus": "Inactive",
        },
    )

    with patch.object(crawler, "post", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("Alice Brown")

    assert result.found is False
    assert result.data["registered"] is False


@pytest.mark.asyncio
async def test_voter_http_error():
    crawler = PublicVoterCrawler()
    with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("John Smith")
    assert result.found is False
    assert result.data.get("error") == "http_error" or result.error is not None
