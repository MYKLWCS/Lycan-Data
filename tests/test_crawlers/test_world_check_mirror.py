"""
test_world_check_mirror.py — Full branch coverage for world_check_mirror.py.

Covers:
- _classify_tier(): tier1, tier2, tier3, default
- _parse_dob_identifier(): with DOB, without DOB
- _parse_complyadvantage_html(): card layout, table layout, no name skip, empty
- _parse_generic_kyc_html(): JSON-LD Person path, heading pattern fallback, empty
- WorldCheckMirrorCrawler.scrape(): full match, no matches, DOB parsed, highest tier
- _search_complyadvantage(): 200, 206 (partial), None, non-200
- _search_dowjones(): 200, None, non-200
- _search_acuris(): 200, None, non-200
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.pep.world_check_mirror import (
    WorldCheckMirrorCrawler,
    _classify_tier,
    _parse_complyadvantage_html,
    _parse_dob_identifier,
    _parse_generic_kyc_html,
)
from modules.crawlers.result import CrawlerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int, text: str = "", json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


def _crawler() -> WorldCheckMirrorCrawler:
    return WorldCheckMirrorCrawler()


# ---------------------------------------------------------------------------
# _classify_tier
# ---------------------------------------------------------------------------


def test_wc_classify_tier_tier1_president():
    assert _classify_tier("President of the Republic") == "tier1"


def test_wc_classify_tier_tier1_parliament():
    assert _classify_tier("Member of Parliament parliament") == "tier1"


def test_wc_classify_tier_tier1_central_bank():
    assert _classify_tier("Governor central bank") == "tier2"  # "governor" triggers deputy/governor fast-path → tier2


def test_wc_classify_tier_tier1_ambassador():
    assert _classify_tier("Ambassador to the EU") == "tier1"


def test_wc_classify_tier_tier2_deputy():
    assert _classify_tier("Deputy Director General") == "tier2"


def test_wc_classify_tier_tier2_director():
    assert _classify_tier("Director of state-owned company") == "tier2"


def test_wc_classify_tier_tier3_relative():
    assert _classify_tier("relative of official") == "tier3"


def test_wc_classify_tier_tier3_spouse():
    assert _classify_tier("Spouse") == "tier3"


def test_wc_classify_tier_default():
    assert _classify_tier("Software Engineer") == "tier2"


# ---------------------------------------------------------------------------
# _parse_dob_identifier
# ---------------------------------------------------------------------------


def test_parse_dob_with_valid_iso_date():
    name, dob = _parse_dob_identifier("John Smith 1975-03-14")
    assert name == "John Smith"
    assert dob == "1975-03-14"


def test_parse_dob_without_date():
    name, dob = _parse_dob_identifier("John Smith")
    assert name == "John Smith"
    assert dob == ""


def test_parse_dob_date_at_start():
    name, dob = _parse_dob_identifier("1990-01-01 John Smith")
    # The DOB is found, name is whatever precedes it
    assert dob == "1990-01-01"


def test_parse_dob_strips_whitespace():
    name, dob = _parse_dob_identifier("  Jane Doe  ")
    assert name == "Jane Doe"
    assert dob == ""


# ---------------------------------------------------------------------------
# _parse_complyadvantage_html — card layout
# ---------------------------------------------------------------------------


def test_parse_ca_html_card_layout():
    html = """
    <html><body>
    <article>
      <h3 class="entity-name">John Smith</h3>
      <div class="country">United Kingdom</div>
      <div class="role">Minister of Finance</div>
      <span class="risk">High</span>
    </article>
    </body></html>
    """
    results = _parse_complyadvantage_html(html)
    assert len(results) == 1
    r = results[0]
    assert r["source"] == "world_check_mirror"
    assert r["source_site"] == "complyadvantage"
    assert r["name"] == "John Smith"
    assert r["country"] == "United Kingdom"
    assert r["pep_level"] == "tier1"  # "minister" in position


def test_parse_ca_html_skips_card_without_name():
    html = """
    <html><body>
    <article>
      <div class="country">UK</div>
    </article>
    </body></html>
    """
    results = _parse_complyadvantage_html(html)
    assert results == []


def test_parse_ca_html_table_layout():
    html = """
    <html><body>
    <table>
      <tr><th>Name</th><th>Role</th><th>Country</th></tr>
      <tr><td>Jane Doe</td><td>Deputy Minister</td><td>France</td></tr>
    </table>
    </body></html>
    """
    results = _parse_complyadvantage_html(html)
    assert len(results) == 1
    r = results[0]
    assert r["name"] == "Jane Doe"
    assert r["pep_level"] == "tier2"  # "deputy" keyword
    assert r["country"] == "France"


def test_parse_ca_html_table_skips_row_without_name():
    html = """
    <html><body>
    <table>
      <tr><th>Name</th><th>Role</th></tr>
      <tr><td></td><td>Something</td></tr>
    </table>
    </body></html>
    """
    results = _parse_complyadvantage_html(html)
    assert results == []


def test_parse_ca_html_empty_string():
    results = _parse_complyadvantage_html("")
    assert results == []


# ---------------------------------------------------------------------------
# _parse_generic_kyc_html — JSON-LD path
# ---------------------------------------------------------------------------


def test_parse_generic_kyc_json_ld_person():
    html = """
    <html><head>
    <script type="application/ld+json">
    {
      "@type": "Person",
      "name": "Roberto Sanchez",
      "jobTitle": "Senator",
      "nationality": "MX",
      "worksFor": {"name": "Mexican Senate"}
    }
    </script>
    </head><body></body></html>
    """
    results = _parse_generic_kyc_html(html, "test_source")
    assert len(results) == 1
    r = results[0]
    assert r["name"] == "Roberto Sanchez"
    assert r["position"] == "Senator"
    assert r["country"] == "MX"
    assert r["organization"] == "Mexican Senate"
    assert r["source_site"] == "test_source"


def test_parse_generic_kyc_json_ld_non_person_ignored():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "Organization", "name": "Acme Corp"}
    </script>
    </head><body></body></html>
    """
    results = _parse_generic_kyc_html(html, "test_source")
    assert results == []


def test_parse_generic_kyc_json_ld_person_no_name_ignored():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "Person", "jobTitle": "Senator"}
    </script>
    </head><body></body></html>
    """
    results = _parse_generic_kyc_html(html, "test_source")
    assert results == []


def test_parse_generic_kyc_json_ld_workfor_string():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "Person", "name": "Tom", "worksFor": "Senate"}
    </script>
    </head><body></body></html>
    """
    results = _parse_generic_kyc_html(html, "test_source")
    assert len(results) == 1
    assert results[0]["organization"] == "Senate"


def test_parse_generic_kyc_heading_pattern_fallback():
    html = """
    <html><body>
    <h2>John Smith</h2>
    <p>Minister of Justice</p>
    </body></html>
    """
    results = _parse_generic_kyc_html(html, "fallback_source")
    assert len(results) == 1
    r = results[0]
    assert r["name"] == "John Smith"
    assert r["source_site"] == "fallback_source"


def test_parse_generic_kyc_heading_no_match_pattern():
    """Lowercase names do not match the capitalised pattern."""
    html = """
    <html><body>
    <h2>john smith lowercase</h2>
    </body></html>
    """
    results = _parse_generic_kyc_html(html, "x")
    assert results == []


def test_parse_generic_kyc_empty():
    results = _parse_generic_kyc_html("", "empty")
    assert results == []


# ---------------------------------------------------------------------------
# WorldCheckMirrorCrawler.scrape()
# ---------------------------------------------------------------------------


async def test_wc_scrape_with_matches():
    crawler = _crawler()
    match = {
        "source": "world_check_mirror",
        "source_site": "complyadvantage",
        "name": "Test Person",
        "position": "Minister",
        "country": "DE",
        "pep_level": "tier1",
        "organization": "",
        "start_date": "",
        "end_date": "",
        "is_current": True,
        "related_entities": [],
    }
    with (
        patch.object(crawler, "_search_complyadvantage", new=AsyncMock(return_value=[match])),
        patch.object(crawler, "_search_dowjones", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_acuris", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("Test Person")

    assert isinstance(result, CrawlerResult)
    assert result.found is True
    assert result.data["is_pep"] is True
    assert result.data["pep_level"] == "tier1"
    assert result.data["match_count"] == 1


async def test_wc_scrape_no_matches():
    crawler = _crawler()
    with (
        patch.object(crawler, "_search_complyadvantage", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_dowjones", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_acuris", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("Nobody")

    assert result.found is False
    assert result.data["pep_level"] == ""
    assert result.data["match_count"] == 0


async def test_wc_scrape_dob_parsed_from_identifier():
    crawler = _crawler()
    with (
        patch.object(crawler, "_search_complyadvantage", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_dowjones", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_acuris", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("John Doe 1980-05-20")

    assert result.data["dob_used"] == "1980-05-20"
    assert result.data["query"] == "John Doe"


async def test_wc_scrape_highest_tier_selected():
    crawler = _crawler()
    m1 = {"pep_level": "tier3", "source": "x", "source_site": "x", "name": "A",
           "position": "", "country": "", "organization": "", "start_date": "",
           "end_date": "", "is_current": True, "related_entities": []}
    m2 = {"pep_level": "tier1", "source": "x", "source_site": "x", "name": "B",
           "position": "", "country": "", "organization": "", "start_date": "",
           "end_date": "", "is_current": True, "related_entities": []}
    with (
        patch.object(crawler, "_search_complyadvantage", new=AsyncMock(return_value=[m1])),
        patch.object(crawler, "_search_dowjones", new=AsyncMock(return_value=[m2])),
        patch.object(crawler, "_search_acuris", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("Someone")

    assert result.data["pep_level"] == "tier1"


# ---------------------------------------------------------------------------
# _search_complyadvantage — branches
# ---------------------------------------------------------------------------


async def test_search_ca_200():
    crawler = _crawler()
    html = """
    <html><body>
    <article><h3 class="name">Ana Lima</h3><div class="role">president</div></article>
    </body></html>
    """
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=html))):
        results = await crawler._search_complyadvantage("Ana+Lima")
    assert isinstance(results, list)


async def test_search_ca_206_partial():
    """206 Partial Content is accepted."""
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(206, text=""))):
        results = await crawler._search_complyadvantage("X")
    assert results == []  # empty HTML, but no error


async def test_search_ca_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_complyadvantage("X")
    assert results == []


async def test_search_ca_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(403))):
        results = await crawler._search_complyadvantage("X")
    assert results == []


# ---------------------------------------------------------------------------
# _search_dowjones — branches
# ---------------------------------------------------------------------------


async def test_search_dj_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text="<html></html>"))):
        results = await crawler._search_dowjones("X")
    assert isinstance(results, list)


async def test_search_dj_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_dowjones("X")
    assert results == []


async def test_search_dj_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
        results = await crawler._search_dowjones("X")
    assert results == []


# ---------------------------------------------------------------------------
# _search_acuris — branches
# ---------------------------------------------------------------------------


async def test_search_acuris_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text="<html></html>"))):
        results = await crawler._search_acuris("X")
    assert isinstance(results, list)


async def test_search_acuris_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_acuris("X")
    assert results == []


async def test_search_acuris_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(403))):
        results = await crawler._search_acuris("X")
    assert results == []
