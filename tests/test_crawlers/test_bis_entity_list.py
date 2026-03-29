"""
Unit tests for modules/crawlers/gov/bis_entity_list.py.

Covers every branch: _cache_valid, _word_overlap, _search_csv,
BisEntityListCrawler._get_csv (cache hit, cache read error, download success,
download fallback, all-fail) and BisEntityListCrawler.scrape.

No real HTTP or filesystem calls are made.
"""

from __future__ import annotations

import builtins
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

import modules.crawlers.gov.bis_entity_list  # noqa: F401 — trigger @register
from modules.crawlers.gov.bis_entity_list import (
    _CACHE_PATH,
    BisEntityListCrawler,
    _search_csv,
)
from modules.crawlers.utils import cache_valid as _cache_valid, word_overlap as _word_overlap

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


_SAMPLE_CSV = (
    "Country,Entity Name,Federal Register Citation,License Requirement,License Policy,Related Persons\n"
    "China,Huawei Technologies Co.,83 FR 54505,For all items subject to the EAR,Presumption of denial,Huawei Device Co.\n"
    "Russia,Rostec Corporation,85 FR 12345,All items,Policy of denial,\n"
    "Germany,SAP SE,,,, \n"
)


# ---------------------------------------------------------------------------
# _cache_valid
# ---------------------------------------------------------------------------


class TestCacheValid:
    def test_returns_false_when_path_missing(self):
        with patch("modules.crawlers.gov.bis_entity_list.os.path.exists", return_value=False):
            assert _cache_valid("/nonexistent/file.csv") is False

    def test_returns_true_when_file_fresh(self):
        import time

        with (
            patch("modules.crawlers.gov.bis_entity_list.os.path.exists", return_value=True),
            patch(
                "modules.crawlers.gov.bis_entity_list.os.path.getmtime",
                return_value=time.time() - 3600,  # 1 hour old
            ),
        ):
            assert _cache_valid("/some/file.csv", max_age_hours=24.0) is True

    def test_returns_false_when_file_stale(self):
        import time

        with (
            patch("modules.crawlers.gov.bis_entity_list.os.path.exists", return_value=True),
            patch(
                "modules.crawlers.gov.bis_entity_list.os.path.getmtime",
                return_value=time.time() - 90000,  # 25 hours old
            ),
        ):
            assert _cache_valid("/some/file.csv", max_age_hours=24.0) is False

    def test_uses_default_max_age(self):
        """Calling without max_age_hours uses module-level default (24 h)."""
        import time

        with (
            patch("modules.crawlers.gov.bis_entity_list.os.path.exists", return_value=True),
            patch(
                "modules.crawlers.gov.bis_entity_list.os.path.getmtime",
                return_value=time.time() - 3600,
            ),
        ):
            assert _cache_valid("/some/file.csv") is True


# ---------------------------------------------------------------------------
# _word_overlap
# ---------------------------------------------------------------------------


class TestWordOverlap:
    def test_empty_query_returns_zero(self):
        assert _word_overlap("", "Huawei Technologies") == 0.0

    def test_full_match_returns_one(self):
        assert _word_overlap("huawei technologies", "huawei technologies") == 1.0

    def test_partial_match(self):
        score = _word_overlap("huawei technologies co", "huawei technologies")
        # 2 words overlap out of 3 query words → 2/3
        assert abs(score - 2 / 3) < 1e-9

    def test_no_overlap_returns_zero(self):
        assert _word_overlap("apple inc", "huawei technologies") == 0.0

    def test_case_insensitive(self):
        assert _word_overlap("HUAWEI", "huawei technologies co") == 1.0

    def test_single_word_full_match(self):
        assert _word_overlap("huawei", "Huawei") == 1.0


# ---------------------------------------------------------------------------
# _search_csv
# ---------------------------------------------------------------------------


class TestSearchCsv:
    def test_returns_matches_above_threshold(self):
        matches = _search_csv(_SAMPLE_CSV, "Huawei Technologies Co")
        assert len(matches) == 1
        assert matches[0]["name"] == "Huawei Technologies Co."
        assert matches[0]["country"] == "China"
        assert "Presumption" in matches[0]["license_policy"]

    def test_returns_empty_when_no_match(self):
        matches = _search_csv(_SAMPLE_CSV, "completely unrelated entity xyz")
        assert matches == []

    def test_match_score_in_result(self):
        matches = _search_csv(_SAMPLE_CSV, "Rostec Corporation")
        assert len(matches) == 1
        assert 0.0 < matches[0]["match_score"] <= 1.0

    def test_related_persons_extracted(self):
        matches = _search_csv(_SAMPLE_CSV, "Huawei Technologies Co")
        assert matches[0]["related_persons"] == "Huawei Device Co."

    def test_skips_rows_with_no_name(self):
        csv_no_name = "Country,Entity Name,Federal Register Citation\nChina,,80 FR 1234\n"
        matches = _search_csv(csv_no_name, "China")
        assert matches == []

    def test_handles_alternative_column_names(self):
        alt_csv = (
            "country,entity_name,federal_register_citation,license_requirement,license_policy,related_persons\n"
            "US,Widget Corp LLC,,,, \n"
        )
        matches = _search_csv(alt_csv, "Widget Corp LLC")
        assert len(matches) == 1
        assert matches[0]["name"] == "Widget Corp LLC"

    def test_handles_name_column_fallback(self):
        """Tests the 'Name' / 'name' column fallback."""
        csv_name_col = "Country,Name\nUS,Global Exports Inc\n"
        matches = _search_csv(csv_name_col, "Global Exports Inc")
        assert len(matches) == 1

    def test_malformed_csv_returns_empty(self):
        """Exception inside csv.DictReader iteration logs a warning and returns []."""
        import csv as csv_mod

        with patch.object(csv_mod, "DictReader", side_effect=RuntimeError("parse boom")):
            matches = _search_csv("bad content", "anything")
        assert matches == []

    def test_fr_citation_alternative_key(self):
        """Tests 'FR Citation' column key fallback."""
        csv_fr = (
            "Country,Entity Name,FR Citation,License Requirement,License Policy,Related Persons\n"
            "US,Acme Corp,88 FR 99999,All items,Denial,\n"
        )
        matches = _search_csv(csv_fr, "Acme Corp")
        assert matches[0]["federal_register_citation"] == "88 FR 99999"

    def test_multiple_matches_returned(self):
        csv_multi = (
            "Country,Entity Name,Federal Register Citation,License Requirement,License Policy,Related Persons\n"
            "CN,Huawei Technologies,80 FR 1,req1,pol1,\n"
            "CN,Huawei Device Co,80 FR 2,req2,pol2,\n"
        )
        matches = _search_csv(csv_multi, "Huawei Technologies")
        # Both share "Huawei" — exact match should definitely be included
        assert any(m["name"] == "Huawei Technologies" for m in matches)


# ---------------------------------------------------------------------------
# BisEntityListCrawler._get_csv
# ---------------------------------------------------------------------------


class TestBisEntityListCrawlerGetCsv:
    def _crawler(self) -> BisEntityListCrawler:
        return BisEntityListCrawler()

    async def test_returns_cache_when_valid(self):
        crawler = self._crawler()
        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=True),
            patch("builtins.open", mock_open(read_data=_SAMPLE_CSV)),
        ):
            result = await crawler._get_csv()
        assert result == _SAMPLE_CSV

    async def test_cache_read_error_falls_through_to_download(self):
        """If reading the cache file raises OSError, we fall through to download."""
        crawler = self._crawler()
        big_text = "a" * 1100  # >1000 bytes

        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=True),
            patch("builtins.open", side_effect=OSError("disk error")),
            patch.object(
                crawler,
                "get",
                new=AsyncMock(return_value=_mock_resp(200, text=big_text)),
            ),
        ):
            result = await crawler._get_csv()
        # download succeeded even though cache read failed
        assert result == big_text

    async def test_downloads_primary_url_and_caches(self):
        """Cache invalid → downloads from primary URL → writes cache."""
        crawler = self._crawler()
        big_text = "x" * 1500

        m = mock_open()
        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=False),
            patch.object(
                crawler,
                "get",
                new=AsyncMock(return_value=_mock_resp(200, text=big_text)),
            ),
            patch("builtins.open", m),
        ):
            result = await crawler._get_csv()

        assert result == big_text
        m.assert_called()  # cache write attempted

    async def test_fallback_to_secondary_url_when_primary_fails(self):
        """Primary URL returns non-200 → fallback URL returns 200 with big text."""
        crawler = self._crawler()
        big_text = "y" * 1500
        call_count = [0]

        async def fake_get(url, **kwargs):
            c = call_count[0]
            call_count[0] += 1
            if c == 0:
                return _mock_resp(404, text="")
            return _mock_resp(200, text=big_text)

        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=False),
            patch.object(crawler, "get", side_effect=fake_get),
            patch("builtins.open", mock_open()),
        ):
            result = await crawler._get_csv()

        assert result == big_text

    async def test_primary_returns_none_fallback_succeeds(self):
        """Primary returns None (network error) → fallback URL succeeds."""
        crawler = self._crawler()
        big_text = "z" * 1500
        call_count = [0]

        async def fake_get(url, **kwargs):
            c = call_count[0]
            call_count[0] += 1
            if c == 0:
                return None
            return _mock_resp(200, text=big_text)

        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=False),
            patch.object(crawler, "get", side_effect=fake_get),
            patch("builtins.open", mock_open()),
        ):
            result = await crawler._get_csv()

        assert result == big_text

    async def test_primary_returns_short_text_fallback_succeeds(self):
        """Primary returns 200 but text < 1000 bytes → try fallback."""
        crawler = self._crawler()
        big_text = "b" * 1500
        call_count = [0]

        async def fake_get(url, **kwargs):
            c = call_count[0]
            call_count[0] += 1
            if c == 0:
                return _mock_resp(200, text="short")
            return _mock_resp(200, text=big_text)

        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=False),
            patch.object(crawler, "get", side_effect=fake_get),
            patch("builtins.open", mock_open()),
        ):
            result = await crawler._get_csv()

        assert result == big_text

    async def test_all_downloads_fail_returns_none(self):
        """Both URLs fail → returns None."""
        crawler = self._crawler()

        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=False),
            patch.object(crawler, "get", new=AsyncMock(return_value=None)),
        ):
            result = await crawler._get_csv()

        assert result is None

    async def test_cache_write_error_still_returns_text(self):
        """Cache write OSError is swallowed; CSV text still returned."""
        crawler = self._crawler()
        big_text = "w" * 1500

        def open_raises_on_write(path, mode="r", **kwargs):
            if "w" in mode:
                raise OSError("disk full")
            # Should not be called for read in this path
            raise OSError("unexpected read")

        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=False),
            patch.object(
                crawler,
                "get",
                new=AsyncMock(return_value=_mock_resp(200, text=big_text)),
            ),
            patch("builtins.open", side_effect=open_raises_on_write),
        ):
            result = await crawler._get_csv()

        assert result == big_text


# ---------------------------------------------------------------------------
# BisEntityListCrawler.scrape
# ---------------------------------------------------------------------------


class TestBisEntityListCrawlerScrape:
    def _crawler(self) -> BisEntityListCrawler:
        return BisEntityListCrawler()

    async def test_scrape_returns_matches_on_hit(self):
        crawler = self._crawler()
        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=True),
            patch("builtins.open", mock_open(read_data=_SAMPLE_CSV)),
        ):
            result = await crawler.scrape("Huawei Technologies Co")

        assert result.found is True
        assert result.data["is_on_bis_list"] is True
        assert result.data["match_count"] >= 1
        assert len(result.data["bis_matches"]) >= 1
        assert result.data["query"] == "Huawei Technologies Co"
        assert result.error is None

    async def test_scrape_returns_not_found_when_no_match(self):
        crawler = self._crawler()
        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=True),
            patch("builtins.open", mock_open(read_data=_SAMPLE_CSV)),
        ):
            result = await crawler.scrape("completely unknown xyz entity")

        assert result.found is False
        assert result.data["is_on_bis_list"] is False
        assert result.data["match_count"] == 0
        assert result.data["bis_matches"] == []

    async def test_scrape_returns_error_when_download_fails(self):
        crawler = self._crawler()
        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=False),
            patch.object(crawler, "get", new=AsyncMock(return_value=None)),
        ):
            result = await crawler.scrape("Huawei")

        assert result.found is False
        # error is stored in data dict (via _result(**data)), not on result.error
        assert result.data.get("error") == "download_failed"
        assert result.data["bis_matches"] == []
        assert result.data["is_on_bis_list"] is False

    async def test_scrape_strips_whitespace_from_identifier(self):
        """Leading/trailing spaces in identifier are stripped before use."""
        crawler = self._crawler()
        with (
            patch("modules.crawlers.gov.bis_entity_list.os.makedirs"),
            patch("modules.crawlers.gov.bis_entity_list.cache_valid", return_value=True),
            patch("builtins.open", mock_open(read_data=_SAMPLE_CSV)),
        ):
            result = await crawler.scrape("  Huawei Technologies Co  ")

        assert result.data["query"] == "Huawei Technologies Co"

    async def test_platform_and_reliability(self):
        crawler = self._crawler()
        assert crawler.platform == "bis_entity_list"
        assert crawler.source_reliability == 0.98
        assert crawler.requires_tor is False
        assert crawler.proxy_tier == "direct"
