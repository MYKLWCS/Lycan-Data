"""
test_sanctions_wave4.py — Targeted coverage for uncovered lines in sanctions crawlers.

Targets:
  sanctions_canada          lines 45-48, 114-115, 128-129
  sanctions_ofac            lines 43, 114-115, 128-129, 151, 154
  sanctions_australia       lines 109-110, 143
  sanctions_eu              lines 97, 127-129
  sanctions_fatf            lines 207-209
  sanctions_uk              lines 128-130
  sanctions_fbi             line 34
  sanctions_un              line 41
  sanctions_worldbank_debarment  lines 31, 58
"""
from __future__ import annotations

import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared mock helper
# ---------------------------------------------------------------------------


def _mock_resp(status=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ===========================================================================
# sanctions_canada
# ===========================================================================

import modules.crawlers.sanctions_canada  # noqa: F401 — trigger @register
from modules.crawlers.sanctions_canada import (
    SanctionsCanadaCrawler,
    _cache_valid as canada_cache_valid,
)


class TestCanadaCacheValid:
    """Lines 45-48: _cache_valid returns False when file absent, True when fresh."""

    def test_returns_false_when_file_missing(self, tmp_path):
        assert canada_cache_valid(str(tmp_path / "nonexistent.csv")) is False

    def test_returns_true_for_fresh_file(self, tmp_path):
        f = tmp_path / "fresh.csv"
        f.write_text("data")
        assert canada_cache_valid(str(f), max_age_hours=1.0) is True

    def test_returns_false_for_stale_file(self, tmp_path):
        f = tmp_path / "stale.csv"
        f.write_text("data")
        # Back-date mtime by 10 hours
        old = time.time() - 36000
        os.utime(str(f), (old, old))
        assert canada_cache_valid(str(f), max_age_hours=1.0) is False


class TestCanadaGetCsvOsError:
    """Line 114-115: OSError on cache read falls through to download."""

    @pytest.mark.asyncio
    async def test_cache_read_oserror_falls_through_to_download(self):
        crawler = SanctionsCanadaCrawler()
        csv_text = "LastName,FirstName\nSmith,John\n"
        with patch(
            "modules.crawlers.sanctions_canada._cache_valid", return_value=True
        ), patch("builtins.open", side_effect=OSError("disk error")), patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(text=csv_text))
        ):
            result = await crawler._get_csv()
        assert result == csv_text


class TestCanadaCacheWriteOsError:
    """Lines 128-129: OSError on cache write is swallowed, text still returned."""

    @pytest.mark.asyncio
    async def test_cache_write_oserror_returns_text(self):
        crawler = SanctionsCanadaCrawler()
        csv_text = "LastName,FirstName\nDoe,Jane\n"

        real_open_calls: list = []

        def selective_open(path, mode="r", **kwargs):
            real_open_calls.append((path, mode))
            if "w" in mode:
                raise OSError("read-only filesystem")
            raise FileNotFoundError("not cached")

        with patch(
            "modules.crawlers.sanctions_canada._cache_valid", return_value=False
        ), patch("builtins.open", side_effect=selective_open), patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(text=csv_text))
        ):
            result = await crawler._get_csv()
        assert result == csv_text


# ===========================================================================
# sanctions_ofac
# ===========================================================================

import modules.crawlers.sanctions_ofac  # noqa: F401
from modules.crawlers.sanctions_ofac import (
    SanctionsOFACCrawler,
    _cache_path as ofac_cache_path,
)


class TestOfacCachePath:
    """Line 43: _cache_path returns expected /tmp path."""

    def test_cache_path_format(self):
        assert ofac_cache_path("sdn", "csv") == "/tmp/lycan_sdn.csv"


class TestOfacGetCsvOsError:
    """Lines 114-115: OSError on cache read falls through to download."""

    @pytest.mark.asyncio
    async def test_cache_read_oserror_falls_through(self):
        crawler = SanctionsOFACCrawler()
        csv_text = "Ent_num,SDN_Name\n1,TEST PERSON\n"
        with patch(
            "modules.crawlers.sanctions_ofac._cache_valid", return_value=True
        ), patch("builtins.open", side_effect=OSError("io error")), patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(text=csv_text))
        ):
            result = await crawler._get_csv()
        assert result == csv_text


class TestOfacCacheWriteOsError:
    """Lines 128-129: OSError on cache write is swallowed, text still returned."""

    @pytest.mark.asyncio
    async def test_cache_write_oserror_returns_text(self):
        crawler = SanctionsOFACCrawler()
        csv_text = "Ent_num,SDN_Name\n2,ANOTHER NAME\n"

        def selective_open(path, mode="r", **kwargs):
            if "w" in mode:
                raise OSError("no space left")
            raise FileNotFoundError("miss")

        with patch(
            "modules.crawlers.sanctions_ofac._cache_valid", return_value=False
        ), patch("builtins.open", side_effect=selective_open), patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(text=csv_text))
        ):
            result = await crawler._get_csv()
        assert result == csv_text


class TestOfacSearchCsvShortRow:
    """Line 151: rows with fewer than 2 columns are skipped."""

    def test_short_row_skipped(self):
        crawler = SanctionsOFACCrawler()
        csv_text = "only_one_column\n1234,SMITH JOHN,Individual,SDGT\n"
        results = crawler._search_csv(csv_text, "smith john")
        # Short first row is skipped; second row matches
        names = [r["name"] for r in results]
        assert "SMITH JOHN" in names

    def test_completely_short_csv_returns_empty(self):
        crawler = SanctionsOFACCrawler()
        csv_text = "one\ntwo\nthree\n"
        results = crawler._search_csv(csv_text, "smith")
        assert results == []


class TestOfacSearchCsvSentinelRow:
    """Line 153-154: rows with '-0-' or 'name' as SDN_Name are skipped."""

    def test_zero_sentinel_skipped(self):
        crawler = SanctionsOFACCrawler()
        csv_text = "1,-0-,Individual,SDGT\n2,REAL PERSON,Individual,SDGT\n"
        results = crawler._search_csv(csv_text, "real person")
        names = [r["name"] for r in results]
        assert "-0-" not in names
        assert "REAL PERSON" in names

    def test_name_header_sentinel_skipped(self):
        crawler = SanctionsOFACCrawler()
        csv_text = "Ent_num,name,SDN_Type,Program\n1,ACTUAL NAME,Individual,SDGT\n"
        results = crawler._search_csv(csv_text, "actual name")
        names = [r["name"] for r in results]
        # 'name' sentinel is skipped
        assert "name" not in [n.lower() for n in names]


# ===========================================================================
# sanctions_australia
# ===========================================================================

import modules.crawlers.sanctions_australia  # noqa: F401
from modules.crawlers.sanctions_australia import SanctionsAustraliaCrawler


class TestAustraliaGetCsvOsError:
    """Lines 109-110: OSError on cache read falls through to download."""

    @pytest.mark.asyncio
    async def test_cache_read_oserror_falls_through(self):
        crawler = SanctionsAustraliaCrawler()
        csv_text = "Name,DOB\nSmith John,1970-01-01\n"
        with patch(
            "modules.crawlers.sanctions_australia._cache_valid", return_value=True
        ), patch("builtins.open", side_effect=OSError("permission denied")), patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(text=csv_text))
        ):
            result = await crawler._get_csv()
        assert result == csv_text


class TestAustraliaSearchCsvSkipEmptyField:
    """Line 143: non-string or empty field values are skipped."""

    def test_empty_value_skipped(self):
        crawler = SanctionsAustraliaCrawler()
        # A row where most fields are empty; only Name has a value
        csv_text = "Name,DOB,Citizenship\nSmith John,,\n"
        results = crawler._search_csv(csv_text, "smith john")
        assert len(results) >= 1
        # Australia returns the matched field value, not a "name" key
        assert results[0]["matched_value"] == "Smith John"

    def test_all_empty_row_no_match(self):
        crawler = SanctionsAustraliaCrawler()
        csv_text = "Name,DOB\n,,\n"
        results = crawler._search_csv(csv_text, "smith")
        assert results == []


# ===========================================================================
# sanctions_eu
# ===========================================================================

import modules.crawlers.sanctions_eu  # noqa: F401
from modules.crawlers.sanctions_eu import EUSanctionsCrawler


class TestEuGetCsvOsError:
    """Line 97: OSError on cache read falls through to download."""

    @pytest.mark.asyncio
    async def test_cache_read_oserror_falls_through(self):
        crawler = EUSanctionsCrawler()
        csv_text = "Id;Entity_logical_id;Name_alias_wholename\n1;42;Smith John\n"
        with patch(
            "modules.crawlers.sanctions_eu._cache_valid", return_value=True
        ), patch("builtins.open", side_effect=OSError("stale fd")), patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(text=csv_text))
        ):
            result = await crawler._get_csv()
        assert result == csv_text


class TestEuSearchCsvParseError:
    """Lines 127-129: exception during csv.reader construction returns []."""

    def test_csv_reader_exception_returns_empty(self):
        crawler = EUSanctionsCrawler()
        with patch("modules.crawlers.sanctions_eu.csv") as mock_csv:
            mock_csv.reader.side_effect = Exception("bad csv")
            results = crawler._search("some csv text", "smith")
        assert results == []


# ===========================================================================
# sanctions_fatf
# ===========================================================================

import modules.crawlers.sanctions_fatf  # noqa: F401
from modules.crawlers.sanctions_fatf import _parse_fatf_page


class TestFatfParseHtmlException:
    """Lines 207-209: exception during HTML parse returns ([], [])."""

    def test_parse_exception_returns_empty_lists(self):
        with patch("modules.crawlers.sanctions_fatf.re") as mock_re:
            mock_re.sub.side_effect = RuntimeError("regex engine crash")
            black, grey = _parse_fatf_page("<html>anything</html>")
        assert black == []
        assert grey == []

    def test_parse_none_html_returns_empty_lists(self):
        # Passing None triggers AttributeError inside the try block
        black, grey = _parse_fatf_page(None)  # type: ignore[arg-type]
        assert black == []
        assert grey == []


# ===========================================================================
# sanctions_uk
# ===========================================================================

import modules.crawlers.sanctions_uk  # noqa: F401
from modules.crawlers.sanctions_uk import UKSanctionsCrawler


class TestUkSearchCsvParseError:
    """Lines 128-130: exception during csv.reader construction returns []."""

    def test_csv_reader_exception_returns_empty(self):
        crawler = UKSanctionsCrawler()
        with patch("modules.crawlers.sanctions_uk.csv") as mock_csv:
            mock_csv.reader.side_effect = Exception("encoding failure")
            results = crawler._search("some text", "smith")
        assert results == []


# ===========================================================================
# sanctions_fbi
# ===========================================================================

import modules.crawlers.sanctions_fbi  # noqa: F401
from modules.crawlers.sanctions_fbi import _name_matches as fbi_name_matches


class TestFbiNameMatchesEmptyQuery:
    """Line 34: empty query string returns 0.0."""

    def test_empty_query_returns_zero(self):
        assert fbi_name_matches("", "John Smith") == 0.0

    def test_whitespace_only_query_returns_zero(self):
        # split() on whitespace-only gives [], so q_words is empty
        assert fbi_name_matches("   ", "John Smith") == 0.0


# ===========================================================================
# sanctions_un
# ===========================================================================

import modules.crawlers.sanctions_un  # noqa: F401
from modules.crawlers.sanctions_un import _cache_path as un_cache_path


class TestUnCachePath:
    """Line 41: _cache_path returns expected /tmp path."""

    def test_cache_path_xml(self):
        assert un_cache_path("un", "xml") == "/tmp/lycan_un.xml"

    def test_cache_path_arbitrary(self):
        assert un_cache_path("test", "json") == "/tmp/lycan_test.json"


# ===========================================================================
# sanctions_worldbank_debarment
# ===========================================================================

import modules.crawlers.sanctions_worldbank_debarment  # noqa: F401
from modules.crawlers.sanctions_worldbank_debarment import (
    _parse_debarred,
    _word_overlap,
)


class TestWordOverlapEmptyQuery:
    """Line 31: empty query returns 0.0."""

    def test_empty_query_returns_zero(self):
        assert _word_overlap("", "Acme Corporation") == 0.0

    def test_whitespace_query_returns_zero(self):
        assert _word_overlap("  ", "Acme Corporation") == 0.0


class TestParseDebarredNonDictRecord:
    """Line 58: non-dict records in list are skipped (continue)."""

    def test_non_dict_items_skipped(self):
        payload = ["not a dict", 42, None, {"firmName": "Acme Corp", "ineligibilityType": "DEBARMENT"}]
        results = _parse_debarred(payload, "acme corp")
        # Non-dict entries skipped, matching dict entry returned
        assert len(results) == 1
        assert results[0]["firm_name"] == "Acme Corp"

    def test_all_non_dict_items_returns_empty(self):
        payload = ["string", 123, None, True]
        results = _parse_debarred(payload, "acme")
        assert results == []
