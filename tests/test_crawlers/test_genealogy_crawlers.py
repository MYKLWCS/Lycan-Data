"""
Tests for all 5 genealogy crawlers — found and not-found cases using mock HTTP.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.genealogy.ancestry_hints  # noqa: F401 — trigger @register
import modules.crawlers.genealogy.census_records  # noqa: F401
import modules.crawlers.genealogy.geni_public  # noqa: F401
import modules.crawlers.genealogy.newspapers_archive  # noqa: F401
import modules.crawlers.genealogy.vitals_records  # noqa: F401
from modules.crawlers.genealogy.ancestry_hints import AncestryHintsCrawler
from modules.crawlers.genealogy.census_records import CensusRecordsCrawler
from modules.crawlers.genealogy.geni_public import GeniPublicCrawler
from modules.crawlers.genealogy.newspapers_archive import NewspapersArchiveCrawler
from modules.crawlers.genealogy.vitals_records import VitalsRecordsCrawler
from modules.crawlers.registry import is_registered

# ── Shared helpers ─────────────────────────────────────────────────────────────


def _mock_response(status_code: int, json_data: dict):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data)
    return resp


def _mock_http_error():
    return None  # HttpxCrawler.get() returns None on error


# ── Registry checks ────────────────────────────────────────────────────────────


def test_all_crawlers_registered():
    assert is_registered("ancestry_hints")
    assert is_registered("census_records")
    assert is_registered("vitals_records")
    assert is_registered("newspapers_archive")
    assert is_registered("geni_public")


# ── AncestryHintsCrawler ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ancestry_hints_found():
    crawler = AncestryHintsCrawler()
    mock_resp = _mock_response(
        200,
        {
            "results": [
                {
                    "name": "John Doe",
                    "facts": {"birth_date": "1850", "birth_place": "Ohio"},
                    "parents": [{"name": "James Doe"}],
                    "children": [],
                    "spouses": [{"name": "Mary Doe", "marriage_date": "1875"}],
                    "siblings": [],
                    "url": "https://ancestry.com/test",
                }
            ]
        },
    )
    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("John Doe")

    assert result.found is True
    assert result.platform == "ancestry_hints"
    assert result.data.get("person_name") == "John Doe"


@pytest.mark.asyncio
async def test_ancestry_hints_not_found_http_error():
    crawler = AncestryHintsCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_http_error())):
        result = await crawler.scrape("Unknown Person")

    assert result.found is False
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_ancestry_hints_not_found_empty_results():
    crawler = AncestryHintsCrawler()
    mock_resp = _mock_response(200, {"results": []})
    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("Nobody Here")

    assert result.found is False


# ── CensusRecordsCrawler ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_census_records_found():
    crawler = CensusRecordsCrawler()
    entry = {
        "content": {
            "gedcomx": {
                "persons": [
                    {
                        "id": "P1",
                        "names": [{"nameForms": [{"fullText": "John Doe"}]}],
                        "facts": [
                            {
                                "type": "http://gedcomx.org/Birth",
                                "date": {"original": "1850"},
                                "place": {"original": "Ohio"},
                            }
                        ],
                    }
                ],
                "relationships": [],
            }
        },
        "id": "https://familysearch.org/records/test",
    }
    mock_resp = _mock_response(200, {"entries": [entry], "results": 1})
    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("John Doe")

    assert result.found is True
    assert result.platform == "census_records"


@pytest.mark.asyncio
async def test_census_records_not_found():
    crawler = CensusRecordsCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_http_error())):
        result = await crawler.scrape("Unknown Person")

    assert result.found is False
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_census_records_auth_required():
    crawler = CensusRecordsCrawler()
    mock_resp = _mock_response(401, {})
    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    assert result.error == "auth_required"


# ── VitalsRecordsCrawler ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vitals_records_found():
    crawler = VitalsRecordsCrawler()
    entry = {
        "content": {
            "gedcomx": {
                "persons": [
                    {
                        "names": [{"nameForms": [{"fullText": "Jane Smith"}]}],
                        "facts": [
                            {
                                "type": "http://gedcomx.org/Birth",
                                "date": {"original": "1920"},
                                "place": {"original": "New York"},
                            },
                            {
                                "type": "http://gedcomx.org/Death",
                                "date": {"original": "1995"},
                                "place": {"original": "Florida"},
                            },
                        ],
                    }
                ]
            }
        },
        "id": "record-id",
    }
    mock_resp = _mock_response(200, {"entries": [entry], "results": 1})
    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("Jane Smith")

    assert result.found is True
    assert result.platform == "vitals_records"


@pytest.mark.asyncio
async def test_vitals_records_not_found():
    crawler = VitalsRecordsCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_http_error())):
        result = await crawler.scrape("Nobody Here")

    assert result.found is False
    assert result.error == "http_error"


# ── NewspapersArchiveCrawler ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_newspapers_archive_found():
    crawler = NewspapersArchiveCrawler()
    mock_resp = _mock_response(
        200,
        {
            "items": [
                {
                    "title": "The Daily Gazette",
                    "place_of_publication": "Springfield, IL",
                    "url": "https://chroniclingamerica.loc.gov/lccn/test/",
                }
            ],
            "totalItems": 5,
        },
    )
    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("John Doe")

    assert result.found is True
    assert result.platform == "newspapers_archive"
    assert result.data.get("record_type") == "obituary"


@pytest.mark.asyncio
async def test_newspapers_archive_not_found():
    crawler = NewspapersArchiveCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_http_error())):
        result = await crawler.scrape("Nobody Here")

    assert result.found is False
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_newspapers_archive_empty():
    crawler = NewspapersArchiveCrawler()
    mock_resp = _mock_response(200, {"items": [], "totalItems": 0})
    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("Nobody Here")

    assert result.found is False


# ── GeniPublicCrawler ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_geni_public_found():
    crawler = GeniPublicCrawler()
    mock_resp = _mock_response(
        200,
        {
            "results": [
                {
                    "name": "Robert Johnson",
                    "birth": {"date": {"year": 1890}, "location": {"city": "Memphis"}},
                    "death": {},
                    "spouses": [],
                    "parents": [{"name": "William Johnson"}],
                    "children": [],
                    "siblings": [],
                    "url": "https://www.geni.com/people/Robert-Johnson/12345",
                }
            ],
            "total_count": 1,
        },
    )
    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("Robert Johnson")

    assert result.found is True
    assert result.platform == "geni_public"
    assert result.data.get("person_name") == "Robert Johnson"


@pytest.mark.asyncio
async def test_geni_public_not_found():
    crawler = GeniPublicCrawler()
    with patch.object(crawler, "get", AsyncMock(return_value=_mock_http_error())):
        result = await crawler.scrape("Nobody Here")

    assert result.found is False
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_geni_public_empty_results():
    crawler = GeniPublicCrawler()
    mock_resp = _mock_response(200, {"results": [], "total_count": 0})
    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("Nobody Here")

    assert result.found is False


@pytest.mark.asyncio
async def test_geni_public_rate_limited():
    crawler = GeniPublicCrawler()
    mock_resp = _mock_response(429, {})
    with patch.object(crawler, "get", AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("John Doe")

    assert result.found is False
    assert result.error == "rate_limited"
