"""
test_open_pep_search.py — Full branch coverage for open_pep_search.py.

Covers:
- _classify_tier(): tier1, tier2, tier3, default
- _classify_categories(): each category bucket, empty → default "government"
- _highest_tier(): tier1 wins, tier2 wins, tier3, empty list
- _parse_opensanctions(): full result, empty results, missing keys
- _parse_interpol(): _embedded path, flat notices path, empty, missing fields
- OpenPepSearchCrawler.scrape(): combined results, no matches, country hint parsed
- _search_opensanctions(): 200 success, None resp, non-200, JSON parse error
- _search_interpol(): 200 success, None resp, non-200, JSON parse error
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.pep.open_pep_search import (
    OpenPepSearchCrawler,
    _classify_categories,
    _classify_tier,
    _highest_tier,
    _parse_interpol,
    _parse_opensanctions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int, json_data: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("no json"))
    return resp


def _crawler() -> OpenPepSearchCrawler:
    return OpenPepSearchCrawler()


# ---------------------------------------------------------------------------
# _classify_tier
# ---------------------------------------------------------------------------


def test_classify_tier_tier1_president():
    assert _classify_tier("President of France") == "tier1"


def test_classify_tier_tier1_minister():
    assert _classify_tier("Minister of Finance") == "tier1"


def test_classify_tier_tier1_central_bank():
    assert _classify_tier("Governor Central Bank") == "tier1"


def test_classify_tier_tier2_deputy():
    assert _classify_tier("Deputy Minister") == "tier2"


def test_classify_tier_tier2_director():
    assert _classify_tier("Director of Operations") == "tier2"


def test_classify_tier_tier2_mayor():
    assert _classify_tier("Mayor of City") == "tier2"


def test_classify_tier_tier3_spouse():
    assert _classify_tier("Spouse of official") == "tier3"


def test_classify_tier_tier3_relative():
    assert _classify_tier("close associate") == "tier3"


def test_classify_tier_default_unknown():
    # No matching keyword — defaults to tier2
    assert _classify_tier("Businessman") == "tier2"


def test_classify_tier_case_insensitive():
    assert _classify_tier("PRIME MINISTER") == "tier1"


# ---------------------------------------------------------------------------
# _classify_categories
# ---------------------------------------------------------------------------


def test_classify_categories_government():
    cats = _classify_categories("Minister of Parliament")
    assert "government" in cats


def test_classify_categories_military():
    cats = _classify_categories("General in armed forces")
    assert "military" in cats


def test_classify_categories_judiciary():
    cats = _classify_categories("Chief Justice Supreme Court")
    assert "judiciary" in cats


def test_classify_categories_soe():
    cats = _classify_categories("Chairman of state-owned enterprise")
    assert "soe" in cats


def test_classify_categories_international():
    cats = _classify_categories("Ambassador to the UN")
    assert "international" in cats


def test_classify_categories_empty_falls_back_to_government():
    cats = _classify_categories("Random citizen")
    assert cats == ["government"]


def test_classify_categories_multiple():
    cats = _classify_categories("General and ambassador")
    assert "military" in cats
    assert "international" in cats


# ---------------------------------------------------------------------------
# _highest_tier
# ---------------------------------------------------------------------------


def test_highest_tier_tier1_wins():
    assert _highest_tier(["tier2", "tier1", "tier3"]) == "tier1"


def test_highest_tier_tier2_when_no_tier1():
    assert _highest_tier(["tier3", "tier2"]) == "tier2"


def test_highest_tier_tier3_only():
    assert _highest_tier(["tier3"]) == "tier3"


def test_highest_tier_empty_list():
    assert _highest_tier([]) == ""


def test_highest_tier_no_known_tier():
    assert _highest_tier(["", ""]) == ""


# ---------------------------------------------------------------------------
# _parse_opensanctions
# ---------------------------------------------------------------------------


def test_parse_opensanctions_full_record():
    data = {
        "results": [
            {
                "id": "abc",
                "caption": "John Smith",
                "schema": "Person",
                "properties": {
                    "name": ["John Smith"],
                    "position": ["Minister of Finance"],
                    "country": ["GB"],
                    "organization": ["HM Treasury"],
                    "employer": [],
                    "startDate": ["2020-01-01"],
                    "incorporationDate": [],
                    "endDate": [],
                    "dissolutionDate": [],
                    "associate": ["Jane Doe"],
                    "familyMember": ["Bob Smith"],
                },
            }
        ]
    }
    results = _parse_opensanctions(data)
    assert len(results) == 1
    r = results[0]
    assert r["source"] == "opensanctions"
    assert r["name"] == "John Smith"
    assert r["position"] == "Minister of Finance"
    assert r["country"] == "GB"
    assert r["pep_level"] == "tier1"
    assert r["organization"] == "HM Treasury"
    assert r["start_date"] == "2020-01-01"
    assert r["end_date"] == ""
    assert r["is_current"] is True
    assert "Jane Doe" in r["related_entities"]
    assert "Bob Smith" in r["related_entities"]
    assert "government" in r["categories"]


def test_parse_opensanctions_empty_results():
    assert _parse_opensanctions({"results": []}) == []


def test_parse_opensanctions_missing_results_key():
    assert _parse_opensanctions({}) == []


def test_parse_opensanctions_uses_caption_over_name_prop():
    data = {
        "results": [
            {
                "caption": "Caption Name",
                "properties": {
                    "name": ["Prop Name"],
                    "position": [],
                    "country": [],
                    "organization": [],
                    "employer": [],
                    "startDate": [],
                    "incorporationDate": [],
                    "endDate": [],
                    "dissolutionDate": [],
                    "associate": [],
                    "familyMember": [],
                },
            }
        ]
    }
    results = _parse_opensanctions(data)
    assert results[0]["name"] == "Caption Name"


def test_parse_opensanctions_falls_back_to_name_when_no_caption():
    data = {
        "results": [
            {
                "properties": {
                    "name": ["Prop Only"],
                    "position": [],
                    "country": [],
                    "organization": [],
                    "employer": [],
                    "startDate": [],
                    "incorporationDate": [],
                    "endDate": [],
                    "dissolutionDate": [],
                    "associate": [],
                    "familyMember": [],
                },
            }
        ]
    }
    results = _parse_opensanctions(data)
    assert results[0]["name"] == "Prop Only"


def test_parse_opensanctions_end_date_marks_not_current():
    data = {
        "results": [
            {
                "caption": "Someone",
                "properties": {
                    "name": [],
                    "position": [],
                    "country": [],
                    "organization": [],
                    "employer": [],
                    "startDate": [],
                    "incorporationDate": [],
                    "endDate": ["2019-12-31"],
                    "dissolutionDate": [],
                    "associate": [],
                    "familyMember": [],
                },
            }
        ]
    }
    results = _parse_opensanctions(data)
    assert results[0]["is_current"] is False
    assert results[0]["end_date"] == "2019-12-31"


def test_parse_opensanctions_employer_fallback():
    data = {
        "results": [
            {
                "caption": "Worker",
                "properties": {
                    "name": [],
                    "position": [],
                    "country": [],
                    "organization": [],
                    "employer": ["Acme Corp"],
                    "startDate": [],
                    "incorporationDate": [],
                    "endDate": [],
                    "dissolutionDate": [],
                    "associate": [],
                    "familyMember": [],
                },
            }
        ]
    }
    results = _parse_opensanctions(data)
    assert results[0]["organization"] == "Acme Corp"


# ---------------------------------------------------------------------------
# _parse_interpol
# ---------------------------------------------------------------------------


def test_parse_interpol_embedded_path():
    data = {
        "_embedded": {
            "notices": [
                {
                    "forename": "Ivan",
                    "name": "Petrov",
                    "nationalities": ["RU"],
                    "entity_id": "2020/12345",
                    "date_of_birth": "1975-06-15",
                }
            ]
        }
    }
    results = _parse_interpol(data)
    assert len(results) == 1
    r = results[0]
    assert r["source"] == "interpol_red_notice"
    assert r["name"] == "Ivan Petrov"
    assert r["country"] == "RU"
    assert r["pep_level"] == "tier1"
    assert r["entity_id"] == "2020/12345"
    assert r["start_date"] == "1975-06-15"
    assert r["is_current"] is True
    assert r["categories"] == ["law_enforcement"]


def test_parse_interpol_flat_notices_path():
    data = {
        "notices": [
            {
                "forename": "Ana",
                "name": "Lopez",
                "nationalities": ["MX"],
                "entity_id": "2021/999",
            }
        ]
    }
    results = _parse_interpol(data)
    assert len(results) == 1
    assert results[0]["name"] == "Ana Lopez"


def test_parse_interpol_empty_data():
    assert _parse_interpol({}) == []


def test_parse_interpol_no_nationality():
    data = {
        "_embedded": {
            "notices": [{"forename": "X", "name": "Y", "nationalities": [], "entity_id": "1"}]
        }
    }
    results = _parse_interpol(data)
    assert results[0]["country"] == ""


def test_parse_interpol_missing_forename():
    data = {"_embedded": {"notices": [{"name": "Surname", "nationalities": [], "entity_id": "2"}]}}
    results = _parse_interpol(data)
    assert results[0]["name"] == "Surname"


# ---------------------------------------------------------------------------
# OpenPepSearchCrawler.scrape() — integration-style
# ---------------------------------------------------------------------------


async def test_scrape_returns_pep_match_from_opensanctions():
    crawler = _crawler()
    os_match = {
        "source": "opensanctions",
        "name": "John Smith",
        "position": "Minister",
        "country": "ZA",
        "pep_level": "tier1",
        "organization": "",
        "start_date": "",
        "end_date": "",
        "is_current": True,
        "related_entities": [],
        "categories": ["government"],
    }

    with (
        patch.object(crawler, "_search_opensanctions", new=AsyncMock(return_value=[os_match])),
        patch.object(crawler, "_search_interpol", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("John Smith")

    assert isinstance(result, CrawlerResult)
    assert result.found is True
    assert result.data["is_pep"] is True
    assert result.data["pep_level"] == "tier1"
    assert result.data["match_count"] == 1
    assert result.data["query"] == "John Smith"


async def test_scrape_no_matches():
    crawler = _crawler()
    with (
        patch.object(crawler, "_search_opensanctions", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_interpol", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("Nobody Known")

    assert result.found is False
    assert result.data["is_pep"] is False
    assert result.data["pep_level"] == ""
    assert result.data["match_count"] == 0


async def test_scrape_country_hint_stripped_from_query():
    crawler = _crawler()
    with (
        patch.object(crawler, "_search_opensanctions", new=AsyncMock(return_value=[])) as mock_os,
        patch.object(crawler, "_search_interpol", new=AsyncMock(return_value=[])),
    ):
        await crawler.scrape("John Smith | South Africa")

    # The encoded query should NOT contain "South Africa"
    call_args = mock_os.call_args[0][0]
    assert "South+Africa" not in call_args
    assert "John" in call_args


async def test_scrape_merges_opensanctions_and_interpol():
    crawler = _crawler()
    os_match = {
        "source": "opensanctions",
        "name": "X",
        "position": "Director",
        "country": "US",
        "pep_level": "tier2",
        "organization": "",
        "start_date": "",
        "end_date": "",
        "is_current": True,
        "related_entities": [],
        "categories": ["government"],
    }
    ip_match = {
        "source": "interpol_red_notice",
        "name": "X",
        "position": "Interpol Red Notice subject",
        "country": "US",
        "pep_level": "tier1",
        "organization": "Interpol",
        "start_date": "",
        "end_date": "",
        "is_current": True,
        "related_entities": [],
        "categories": ["law_enforcement"],
        "entity_id": "2023/1",
    }
    with (
        patch.object(crawler, "_search_opensanctions", new=AsyncMock(return_value=[os_match])),
        patch.object(crawler, "_search_interpol", new=AsyncMock(return_value=[ip_match])),
    ):
        result = await crawler.scrape("X Y")

    assert result.data["match_count"] == 2
    assert result.data["pep_level"] == "tier1"
    assert "law_enforcement" in result.data["pep_categories"]


async def test_scrape_single_word_name_interpol_handling():
    """When name has only one word, firstname is empty, lastname = encoded query."""
    crawler = _crawler()
    with (
        patch.object(crawler, "_search_opensanctions", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_interpol", new=AsyncMock(return_value=[])) as mock_ip,
    ):
        await crawler.scrape("Mononym")

    # Called with (firstname, lastname) — single word → firstname="" (empty), lastname=encoded query
    args = mock_ip.call_args[0]
    assert args[0] == ""  # single word → firstname empty
    assert args[1] == "Mononym"  # encoded query becomes lastname


# ---------------------------------------------------------------------------
# _search_opensanctions — branch coverage
# ---------------------------------------------------------------------------


async def test_search_opensanctions_success():
    crawler = _crawler()
    data = {
        "results": [
            {
                "caption": "Alice",
                "properties": {
                    "name": ["Alice"],
                    "position": ["Senator"],
                    "country": ["US"],
                    "organization": [],
                    "employer": [],
                    "startDate": [],
                    "incorporationDate": [],
                    "endDate": [],
                    "dissolutionDate": [],
                    "associate": [],
                    "familyMember": [],
                },
            }
        ]
    }
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, data))):
        results = await crawler._search_opensanctions("Alice")
    assert len(results) == 1
    assert results[0]["name"] == "Alice"


async def test_search_opensanctions_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_opensanctions("Alice")
    assert results == []


async def test_search_opensanctions_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(403))):
        results = await crawler._search_opensanctions("Alice")
    assert results == []


async def test_search_opensanctions_json_parse_error():
    crawler = _crawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json = MagicMock(side_effect=ValueError("bad json"))
    with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
        results = await crawler._search_opensanctions("Alice")
    assert results == []


# ---------------------------------------------------------------------------
# _search_interpol — branch coverage
# ---------------------------------------------------------------------------


async def test_search_interpol_success():
    crawler = _crawler()
    data = {
        "_embedded": {
            "notices": [
                {
                    "forename": "Bob",
                    "name": "Jones",
                    "nationalities": ["AU"],
                    "entity_id": "X1",
                }
            ]
        }
    }
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, data))):
        results = await crawler._search_interpol("Bob", "Jones")
    assert len(results) == 1
    assert results[0]["source"] == "interpol_red_notice"


async def test_search_interpol_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_interpol("Bob", "Jones")
    assert results == []


async def test_search_interpol_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
        results = await crawler._search_interpol("Bob", "Jones")
    assert results == []


async def test_search_interpol_json_parse_error():
    crawler = _crawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json = MagicMock(side_effect=ValueError("bad json"))
    with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
        results = await crawler._search_interpol("Bob", "Jones")
    assert results == []
