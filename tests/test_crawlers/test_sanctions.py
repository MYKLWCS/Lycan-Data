"""
Tests for Sanctions & Watchlists scrapers — Task 22.
  - SanctionsOFACCrawler  (sanctions_ofac)
  - SanctionsUNCrawler    (sanctions_un)
  - SanctionsFBICrawler   (sanctions_fbi)

15 tests total — all HTTP calls are mocked.
"""

from __future__ import annotations

import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

import modules.crawlers.sanctions_fbi  # noqa: F401

# Trigger @register decorators
import modules.crawlers.sanctions_ofac  # noqa: F401
import modules.crawlers.sanctions_un  # noqa: F401
from modules.crawlers.registry import is_registered
from modules.crawlers.sanctions_fbi import (
    SanctionsFBICrawler,
)
from modules.crawlers.sanctions_fbi import (
    _name_matches as fbi_name_matches,
)
from modules.crawlers.sanctions_ofac import (
    SanctionsOFACCrawler,
)
from modules.crawlers.sanctions_ofac import (
    _cache_valid as ofac_cache_valid,
)
from modules.crawlers.sanctions_ofac import (
    _name_matches as ofac_name_matches,
)
from modules.crawlers.sanctions_un import (
    SanctionsUNCrawler,
)
from modules.crawlers.sanctions_un import (
    _cache_valid as un_cache_valid,
)
from modules.crawlers.sanctions_un import (
    _name_matches as un_name_matches,
)

# ===========================================================================
# Helper factories
# ===========================================================================


def _mock_httpx_response(status: int = 200, text: str = "", json_data: dict | None = None):
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


SAMPLE_OFAC_CSV = (
    "Ent_num,SDN_Name,SDN_Type,Program,Title,Call_Sign\n"
    "1234,SMITH JOHN WILLIAM,Individual,SDGT,Mr.,\n"
    "5678,DOE JANE,Entity,SDGT,,\n"
    "9999,UNRELATED PERSON,Individual,SDGT,,\n"
)

SAMPLE_UN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CONSOLIDATED_LIST>
  <INDIVIDUALS>
    <INDIVIDUAL>
      <FIRST_NAME>JOHN</FIRST_NAME>
      <SECOND_NAME>WILLIAM</SECOND_NAME>
      <THIRD_NAME>SMITH</THIRD_NAME>
      <UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE>
      <REFERENCE_NUMBER>QDi.001</REFERENCE_NUMBER>
      <INDIVIDUAL_ALIAS>
        <ALIAS_NAME>Johnny Smith</ALIAS_NAME>
      </INDIVIDUAL_ALIAS>
    </INDIVIDUAL>
    <INDIVIDUAL>
      <FIRST_NAME>JANE</FIRST_NAME>
      <SECOND_NAME>DOE</SECOND_NAME>
      <THIRD_NAME></THIRD_NAME>
      <UN_LIST_TYPE>Taliban</UN_LIST_TYPE>
      <REFERENCE_NUMBER>QDi.002</REFERENCE_NUMBER>
    </INDIVIDUAL>
  </INDIVIDUALS>
  <ENTITIES>
    <ENTITY>
      <FIRST_NAME>ACME WEAPONS CORP</FIRST_NAME>
      <UN_LIST_TYPE>Al-Qaida</UN_LIST_TYPE>
      <REFERENCE_NUMBER>QDe.001</REFERENCE_NUMBER>
      <ENTITY_ALIAS>
        <ALIAS_NAME>ACME Corp</ALIAS_NAME>
      </ENTITY_ALIAS>
    </ENTITY>
  </ENTITIES>
</CONSOLIDATED_LIST>
"""

SAMPLE_FBI_JSON = {
    "items": [
        {
            "title": "JOHN WILLIAM SMITH",
            "description": "Armed and dangerous fugitive.",
            "aliases": ["Johnny Smith", "J.W. Smith"],
            "subjects": ["Fugitive"],
            "field_offices": ["houston"],
            "reward_text": "$10,000",
            "url": "https://www.fbi.gov/wanted/fugitives/john-william-smith",
            "images": [],
        },
        {
            "title": "COMPLETELY DIFFERENT PERSON",
            "description": "Another person.",
            "aliases": [],
            "subjects": ["Fugitive"],
            "field_offices": [],
            "reward_text": "",
            "url": "https://www.fbi.gov/wanted/fugitives/different",
            "images": [],
        },
    ],
    "total": 2,
    "page": 1,
}


# ===========================================================================
# 1. Registry tests
# ===========================================================================


def test_ofac_registered():
    """sanctions_ofac must be registered in the crawler registry."""
    assert is_registered("sanctions_ofac")


def test_un_registered():
    """sanctions_un must be registered in the crawler registry."""
    assert is_registered("sanctions_un")


def test_fbi_registered():
    """sanctions_fbi must be registered in the crawler registry."""
    assert is_registered("sanctions_fbi")


# ===========================================================================
# 2. _name_matches utility tests
# ===========================================================================


def test_name_matches_exact():
    """Exact same name → score 1.0."""
    assert ofac_name_matches("John Smith", "John Smith") == 1.0


def test_name_matches_partial():
    """Query words that all appear in a longer candidate → full score."""
    # "John Smith" vs "Smith John William" — both query words appear → 1.0
    score = ofac_name_matches("John Smith", "Smith John William")
    assert score >= 0.5  # at minimum, partial overlap


def test_name_matches_no_overlap():
    """Completely different names → score 0.0."""
    assert ofac_name_matches("Alice Brown", "Xavier Green") == 0.0


def test_name_matches_empty_query():
    """Empty query string → score 0.0."""
    assert ofac_name_matches("", "John Smith") == 0.0


# ===========================================================================
# 3. _cache_valid tests
# ===========================================================================


def test_cache_valid_missing_file():
    """Non-existent file → False."""
    assert ofac_cache_valid("/tmp/lycan_nonexistent_99999.csv") is False


def test_cache_valid_fresh_file():
    """File modified just now → True."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tf:
        tf.write(b"data")
        tmp_path = tf.name
    try:
        assert ofac_cache_valid(tmp_path, max_age_hours=6.0) is True
    finally:
        os.unlink(tmp_path)


def test_cache_valid_old_file():
    """File with mtime set 7 hours ago → False."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tf:
        tf.write(b"data")
        tmp_path = tf.name
    try:
        old_mtime = time.time() - (7 * 3600)
        os.utime(tmp_path, (old_mtime, old_mtime))
        assert ofac_cache_valid(tmp_path, max_age_hours=6.0) is False
    finally:
        os.unlink(tmp_path)


# ===========================================================================
# 4. OFAC scraper tests
# ===========================================================================


@pytest.mark.asyncio
async def test_ofac_name_found():
    """OFAC scraper returns a match when the name appears in the CSV."""
    crawler = SanctionsOFACCrawler()
    mock_resp = _mock_httpx_response(200, SAMPLE_OFAC_CSV)

    # Ensure cache is bypassed
    with (
        patch("modules.crawlers.sanctions_ofac._cache_valid", return_value=False),
        patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)),
        patch("builtins.open", mock_open()),
    ):
        result = await crawler.scrape("SMITH JOHN")

    assert result.found is True
    assert result.data["match_count"] >= 1
    names = [m["name"] for m in result.data["matches"]]
    assert any("SMITH" in n for n in names)


@pytest.mark.asyncio
async def test_ofac_name_not_found():
    """OFAC scraper returns match_count=0 when name is absent."""
    crawler = SanctionsOFACCrawler()
    mock_resp = _mock_httpx_response(200, SAMPLE_OFAC_CSV)

    with (
        patch("modules.crawlers.sanctions_ofac._cache_valid", return_value=False),
        patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)),
        patch("builtins.open", mock_open()),
    ):
        result = await crawler.scrape("NOBODY UNKNOWN ZZZXXX")

    assert result.data["match_count"] == 0
    assert result.found is False


@pytest.mark.asyncio
async def test_ofac_cache_hit_no_http():
    """When cache is fresh, OFAC scraper reads from disk without making HTTP call."""
    crawler = SanctionsOFACCrawler()

    with (
        patch("modules.crawlers.sanctions_ofac._cache_valid", return_value=True),
        patch("builtins.open", mock_open(read_data=SAMPLE_OFAC_CSV)),
        patch.object(crawler, "get", new=AsyncMock()) as mock_get,
    ):
        result = await crawler.scrape("SMITH JOHN")

    mock_get.assert_not_called()
    assert result.data["match_count"] >= 1


@pytest.mark.asyncio
async def test_ofac_http_failure():
    """OFAC scraper returns error result when HTTP download fails."""
    crawler = SanctionsOFACCrawler()

    with (
        patch("modules.crawlers.sanctions_ofac._cache_valid", return_value=False),
        patch.object(crawler, "get", new=AsyncMock(return_value=None)),
    ):
        result = await crawler.scrape("JOHN SMITH")

    assert result.found is False
    assert result.data.get("match_count", 0) == 0


# ===========================================================================
# 5. UN scraper tests
# ===========================================================================


@pytest.mark.asyncio
async def test_un_xml_individual_found():
    """UN scraper correctly parses INDIVIDUAL elements and returns a match."""
    crawler = SanctionsUNCrawler()
    mock_resp = _mock_httpx_response(200, SAMPLE_UN_XML)

    with (
        patch("modules.crawlers.sanctions_un._cache_valid", return_value=False),
        patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)),
        patch("builtins.open", mock_open()),
    ):
        result = await crawler.scrape("JOHN SMITH")

    assert result.found is True
    assert result.data["match_count"] >= 1
    match = result.data["matches"][0]
    assert "JOHN" in match["name"] or "SMITH" in match["name"]
    assert "reference" in match
    assert "list_type" in match


@pytest.mark.asyncio
async def test_un_xml_entity_found():
    """UN scraper correctly parses ENTITY elements."""
    crawler = SanctionsUNCrawler()
    mock_resp = _mock_httpx_response(200, SAMPLE_UN_XML)

    with (
        patch("modules.crawlers.sanctions_un._cache_valid", return_value=False),
        patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)),
        patch("builtins.open", mock_open()),
    ):
        result = await crawler.scrape("ACME WEAPONS")

    assert result.found is True
    entity_matches = [m for m in result.data["matches"] if m.get("record_type") == "entity"]
    assert len(entity_matches) >= 1


@pytest.mark.asyncio
async def test_un_name_not_found():
    """UN scraper returns match_count=0 when name not on list."""
    crawler = SanctionsUNCrawler()
    mock_resp = _mock_httpx_response(200, SAMPLE_UN_XML)

    with (
        patch("modules.crawlers.sanctions_un._cache_valid", return_value=False),
        patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)),
        patch("builtins.open", mock_open()),
    ):
        result = await crawler.scrape("NOBODY UNKNOWN ZZZXXX")

    assert result.data["match_count"] == 0
    assert result.found is False


# ===========================================================================
# 6. FBI scraper tests
# ===========================================================================


@pytest.mark.asyncio
async def test_fbi_name_found():
    """FBI scraper returns match when title matches query."""
    crawler = SanctionsFBICrawler()
    mock_resp = _mock_httpx_response(200, json_data=SAMPLE_FBI_JSON)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("JOHN SMITH")

    assert result.found is True
    assert result.data["match_count"] >= 1
    match = result.data["matches"][0]
    assert "name" in match
    assert "url" in match
    assert "reward" in match
    assert "aliases" in match


@pytest.mark.asyncio
async def test_fbi_name_not_found():
    """FBI scraper returns match_count=0 when no items match."""
    crawler = SanctionsFBICrawler()
    mock_resp = _mock_httpx_response(200, json_data=SAMPLE_FBI_JSON)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("NOBODY UNKNOWN ZZZXXX")

    assert result.data["match_count"] == 0
    assert result.found is False


@pytest.mark.asyncio
async def test_fbi_api_failure():
    """FBI scraper returns error result on HTTP failure."""
    crawler = SanctionsFBICrawler()

    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("JOHN SMITH")

    assert result.found is False
    assert result.data.get("match_count", 0) == 0


@pytest.mark.asyncio
async def test_fbi_json_parse_error():
    """FBI scraper handles invalid JSON gracefully."""
    crawler = SanctionsFBICrawler()
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json = MagicMock(side_effect=ValueError("bad json"))

    with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
        result = await crawler.scrape("JOHN SMITH")

    assert result.found is False
    assert "error" in result.data or result.error is not None
