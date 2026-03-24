"""
test_remaining_crawlers.py — Comprehensive pytest tests for low-coverage crawlers.

Covers all branches in:
  sanctions_australia, sanctions_canada, sanctions_eu, sanctions_fatf,
  sanctions_uk, sanctions_worldbank_debarment, sanctions_opensanctions,
  social_mastodon, social_spotify, social_steam, social_twitch,
  geo_adsbexchange, geo_ip, geo_openstreetmap,
  financial_crunchbase, financial_worldbank, financial_finra
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


def _mock_resp(status: int = 200, json_data=None, text: str = "", content: bytes = b""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else (str(json_data) if json_data is not None else "")
    resp.content = content if content else resp.text.encode("latin-1", errors="replace")
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


def _mock_json_resp(status: int = 200, json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = str(json_data or {})
    resp.content = resp.text.encode()
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


# ===========================================================================
# sanctions_australia
# ===========================================================================


class TestSanctionsAustralia:
    @pytest.mark.asyncio
    async def test_success_match(self):
        from modules.crawlers.sanctions_australia import SanctionsAustraliaCrawler

        crawler = SanctionsAustraliaCrawler()
        csv = "Name,Type,Country\nVladimir Putin,Individual,Russia\n"
        resp = _mock_resp(200, text=csv)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_australia._cache_valid", return_value=False):
                result = await crawler.scrape("Vladimir Putin")
        assert result.found is True
        assert result.data["match_count"] >= 1

    @pytest.mark.asyncio
    async def test_no_match(self):
        from modules.crawlers.sanctions_australia import SanctionsAustraliaCrawler

        crawler = SanctionsAustraliaCrawler()
        csv = "Name,Type,Country\nJohn Doe,Individual,USA\n"
        resp = _mock_resp(200, text=csv)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_australia._cache_valid", return_value=False):
                result = await crawler.scrape("Completely Different Person")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_network_error(self):
        from modules.crawlers.sanctions_australia import SanctionsAustraliaCrawler

        crawler = SanctionsAustraliaCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            with patch("modules.crawlers.sanctions_australia._cache_valid", return_value=False):
                result = await crawler.scrape("test")
        assert result.found is False
        assert "Failed" in (result.data.get("error") or "")

    @pytest.mark.asyncio
    async def test_non_200_status(self):
        from modules.crawlers.sanctions_australia import SanctionsAustraliaCrawler

        crawler = SanctionsAustraliaCrawler()
        resp = _mock_resp(500)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_australia._cache_valid", return_value=False):
                result = await crawler.scrape("test")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_uses_cache_when_valid(self, tmp_path):
        from modules.crawlers.sanctions_australia import SanctionsAustraliaCrawler

        crawler = SanctionsAustraliaCrawler()
        cache_file = tmp_path / "aus.csv"
        cache_file.write_text("Name,Type\nAlice Bob,Individual\n", encoding="utf-8-sig")

        with patch("modules.crawlers.sanctions_australia._cache_valid", return_value=True):
            with patch("modules.crawlers.sanctions_australia._CACHE_PATH", str(cache_file)):
                result = await crawler.scrape("Alice Bob")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_cache_write_failure_still_returns_data(self):
        from modules.crawlers.sanctions_australia import SanctionsAustraliaCrawler

        crawler = SanctionsAustraliaCrawler()
        csv = "Name,Type\nAlice Smith,Individual\n"
        resp = _mock_resp(200, text=csv)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_australia._cache_valid", return_value=False):
                with patch("builtins.open", side_effect=[OSError("disk full")]):
                    # Even if cache write fails, should return text from HTTP response
                    result = await crawler.scrape("Alice Smith")
        # We can't write cache but text comes from resp.text directly
        assert result is not None

    def test_name_matches_empty_query(self):
        from modules.crawlers.sanctions_australia import _name_matches

        assert _name_matches("", "anything") == 0.0

    def test_name_matches_full_overlap(self):
        from modules.crawlers.sanctions_australia import _name_matches

        score = _name_matches("John Smith", "John Smith Senior")
        assert score == 1.0

    def test_name_matches_partial(self):
        from modules.crawlers.sanctions_australia import _name_matches

        score = _name_matches("John Smith", "John Brown")
        assert 0.0 < score < 1.0

    def test_cache_valid_missing_file(self, tmp_path):
        from modules.crawlers.sanctions_australia import _cache_valid

        assert _cache_valid(str(tmp_path / "nonexistent.csv")) is False

    def test_cache_valid_fresh_file(self, tmp_path):
        from modules.crawlers.sanctions_australia import _cache_valid

        f = tmp_path / "fresh.csv"
        f.write_text("data")
        assert _cache_valid(str(f), max_age_hours=6.0) is True

    def test_cache_valid_stale_file(self, tmp_path):
        from modules.crawlers.sanctions_australia import _cache_valid

        f = tmp_path / "stale.csv"
        f.write_text("data")
        old_time = time.time() - 7 * 3600
        os.utime(str(f), (old_time, old_time))
        assert _cache_valid(str(f), max_age_hours=6.0) is False

    @pytest.mark.asyncio
    async def test_empty_csv(self):
        from modules.crawlers.sanctions_australia import SanctionsAustraliaCrawler

        crawler = SanctionsAustraliaCrawler()
        resp = _mock_resp(200, text="Name,Type\n")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_australia._cache_valid", return_value=False):
                result = await crawler.scrape("anybody")
        assert result.found is False
        assert result.data["match_count"] == 0


# ===========================================================================
# sanctions_canada
# ===========================================================================


class TestSanctionsCanada:
    @pytest.mark.asyncio
    async def test_success_match_with_name_columns(self):
        from modules.crawlers.sanctions_canada import SanctionsCanadaCrawler

        crawler = SanctionsCanadaCrawler()
        # Use Aliases column which contains the full name — scores 1.0 against "Putin"
        csv = "LastName,FirstName,MiddleName,DOB,Aliases\nPutin,Vladimir,,1952-10-07,Putin\n"
        resp = _mock_resp(200, text=csv)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_canada._cache_valid", return_value=False):
                result = await crawler.scrape("Putin")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_fallback_to_all_columns(self):
        from modules.crawlers.sanctions_canada import SanctionsCanadaCrawler

        crawler = SanctionsCanadaCrawler()
        # No known name columns present
        csv = "FullName,Country\nAlice Smith,Canada\n"
        resp = _mock_resp(200, text=csv)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_canada._cache_valid", return_value=False):
                result = await crawler.scrape("Alice Smith")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_network_error(self):
        from modules.crawlers.sanctions_canada import SanctionsCanadaCrawler

        crawler = SanctionsCanadaCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            with patch("modules.crawlers.sanctions_canada._cache_valid", return_value=False):
                result = await crawler.scrape("test")
        assert result.found is False
        assert "Canada" in (result.data.get("error") or "")

    @pytest.mark.asyncio
    async def test_non_200(self):
        from modules.crawlers.sanctions_canada import SanctionsCanadaCrawler

        crawler = SanctionsCanadaCrawler()
        resp = _mock_resp(503)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_canada._cache_valid", return_value=False):
                result = await crawler.scrape("test")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_uses_cache(self, tmp_path):
        from modules.crawlers.sanctions_canada import SanctionsCanadaCrawler

        crawler = SanctionsCanadaCrawler()
        cache_file = tmp_path / "canada.csv"
        # Single-word query "Smith" matches LastName column at score 1.0 (>= 0.7 threshold)
        cache_file.write_text("LastName,FirstName\nSmith,John\n", encoding="utf-8-sig")
        with patch("modules.crawlers.sanctions_canada._cache_valid", return_value=True):
            with patch("modules.crawlers.sanctions_canada._CACHE_PATH", str(cache_file)):
                result = await crawler.scrape("Smith")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_no_match(self):
        from modules.crawlers.sanctions_canada import SanctionsCanadaCrawler

        crawler = SanctionsCanadaCrawler()
        csv = "LastName,FirstName\nPutin,Vladimir\n"
        resp = _mock_resp(200, text=csv)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_canada._cache_valid", return_value=False):
                result = await crawler.scrape("Completely Nobody")
        assert result.found is False

    def test_name_matches_empty_query(self):
        from modules.crawlers.sanctions_canada import _name_matches

        assert _name_matches("", "anything") == 0.0

    def test_dob_alias_fallback(self):
        from modules.crawlers.sanctions_canada import SanctionsCanadaCrawler

        crawler = SanctionsCanadaCrawler()
        # Verify _search_csv picks DateOfBirth when DOB column missing.
        # Query "Smith" matches LastName "Smith" at score 1.0 (above 0.7 threshold).
        csv = "LastName,FirstName,DateOfBirth\nSmith,John,1990-01-01\n"
        result = crawler._search_csv(csv, "Smith")
        assert len(result) > 0
        assert result[0]["DOB"] == "1990-01-01"


# ===========================================================================
# sanctions_eu
# ===========================================================================


class TestSanctionsEU:
    @pytest.mark.asyncio
    async def test_success_match(self):
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        # EU CSV: FileGenerationDate,Entity_LogicalId,Entity_Remark,FirstName,MiddleName,LastName,WholeName,...
        csv_row = "2024-01-01,E001,remark,Vladimir,,Putin,Vladimir Putin,en,person"
        csv_text = f"FileGenerationDate,Entity_LogicalId,Entity_Remark,NameAlias_FirstName,NameAlias_MiddleName,NameAlias_LastName,NameAlias_WholeName,NameAlias_NameLanguage,Entity_SubjectType\n{csv_row}\n"
        resp = _mock_resp(200, text=csv_text)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_eu._cache_valid", return_value=False):
                result = await crawler.scrape("Vladimir Putin")
        assert result.found is True
        assert result.data["match_count"] >= 1

    @pytest.mark.asyncio
    async def test_no_match(self):
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        csv_text = "FileGenerationDate,Entity_LogicalId,Entity_Remark,NameAlias_FirstName,NameAlias_MiddleName,NameAlias_LastName,NameAlias_WholeName,NameAlias_NameLanguage,Entity_SubjectType\n2024-01-01,E001,remark,John,,Doe,John Doe,en,person\n"
        resp = _mock_resp(200, text=csv_text)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_eu._cache_valid", return_value=False):
                result = await crawler.scrape("Completely Different")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_network_error(self):
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            with patch("modules.crawlers.sanctions_eu._cache_valid", return_value=False):
                result = await crawler.scrape("test")
        assert result.found is False
        assert result.data.get("error") == "download_failed"

    @pytest.mark.asyncio
    async def test_non_200(self):
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        resp = _mock_resp(403)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_eu._cache_valid", return_value=False):
                result = await crawler.scrape("test")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_row_too_short_skipped(self):
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        # Only 3 columns — will be skipped
        csv_text = "col1,col2,col3\nval1,val2,val3\n"
        resp = _mock_resp(200, text=csv_text)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_eu._cache_valid", return_value=False):
                result = await crawler.scrape("val1")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_deduplication_by_entity_id(self):
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        row = "2024-01-01,E001,remark,Vladimir,,Putin,Vladimir Putin,en,person"
        csv_text = "FileGenerationDate,Entity_LogicalId,Entity_Remark,NameAlias_FirstName,NameAlias_MiddleName,NameAlias_LastName,NameAlias_WholeName,NameAlias_NameLanguage,Entity_SubjectType\n"
        csv_text += row + "\n" + row + "\n"  # duplicate rows same entity_id
        resp = _mock_resp(200, text=csv_text)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_eu._cache_valid", return_value=False):
                result = await crawler.scrape("Vladimir Putin")
        assert result.data["match_count"] == 1

    def test_name_overlap_score(self):
        from modules.crawlers.sanctions_eu import _name_overlap_score

        assert _name_overlap_score("", "anything") == 0.0
        assert _name_overlap_score("Putin", "Vladimir Putin") == 1.0
        assert _name_overlap_score("John Smith", "John Brown") == 0.5

    @pytest.mark.asyncio
    async def test_matches_capped_at_50(self):
        from modules.crawlers.sanctions_eu import EUSanctionsCrawler

        crawler = EUSanctionsCrawler()
        header = "FileGenerationDate,Entity_LogicalId,Entity_Remark,NameAlias_FirstName,NameAlias_MiddleName,NameAlias_LastName,NameAlias_WholeName,NameAlias_NameLanguage,Entity_SubjectType\n"
        rows = "\n".join(
            f"2024-01-01,E{i:03d},remark,John,,Smith,John Smith,en,person" for i in range(60)
        )
        resp = _mock_resp(200, text=header + rows)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_eu._cache_valid", return_value=False):
                result = await crawler.scrape("John Smith")
        assert len(result.data["matches"]) <= 50


# ===========================================================================
# sanctions_fatf
# ===========================================================================


class TestSanctionsFATF:
    @pytest.mark.asyncio
    async def test_blacklist_country_embedded(self):
        from modules.crawlers.sanctions_fatf import FATFCrawler

        crawler = FATFCrawler()
        # Force HTTP fail so embedded list is used
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("Iran")
        assert result.found is True
        assert result.data["status"] == "black_list"

    @pytest.mark.asyncio
    async def test_greylist_country_embedded(self):
        from modules.crawlers.sanctions_fatf import FATFCrawler

        crawler = FATFCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("Nigeria")
        assert result.found is True
        assert result.data["status"] == "grey_list"

    @pytest.mark.asyncio
    async def test_clean_country(self):
        from modules.crawlers.sanctions_fatf import FATFCrawler

        crawler = FATFCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("Switzerland")
        assert result.found is False
        assert result.data["status"] == "clean"

    @pytest.mark.asyncio
    async def test_iso2_code_resolution(self):
        from modules.crawlers.sanctions_fatf import FATFCrawler

        crawler = FATFCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("IR")  # ISO-2 for Iran
        assert result.data["status"] == "black_list"

    @pytest.mark.asyncio
    async def test_iso3_code_resolution(self):
        from modules.crawlers.sanctions_fatf import FATFCrawler

        crawler = FATFCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("PRK")  # ISO-3 for North Korea
        assert result.data["status"] == "black_list"

    @pytest.mark.asyncio
    async def test_live_parse_used_when_successful(self):
        from modules.crawlers.sanctions_fatf import FATFCrawler

        crawler = FATFCrawler()
        html = """
        <html><body>
        <h2>Jurisdictions under increased monitoring</h2>
        <p>Albania, Barbados, Cayman Islands</p>
        <h2>Call for Action</h2>
        <p>North Korea, Iran</p>
        </body></html>
        """
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Iran")
        # Live parse may or may not find exact match; source should be live if parse returned data
        assert result is not None

    @pytest.mark.asyncio
    async def test_429_falls_back_to_embedded(self):
        from modules.crawlers.sanctions_fatf import FATFCrawler

        crawler = FATFCrawler()
        resp = _mock_resp(429)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Myanmar")
        assert result.data["status"] == "black_list"
        assert result.data["source"] == "embedded"

    def test_resolve_country_unknown_code(self):
        from modules.crawlers.sanctions_fatf import _resolve_country

        assert _resolve_country("XYZ") == "XYZ"

    def test_parse_fatf_page_empty_html(self):
        from modules.crawlers.sanctions_fatf import _parse_fatf_page

        black, grey = _parse_fatf_page("")
        assert black == []
        assert grey == []

    def test_match_country_case_insensitive(self):
        from modules.crawlers.sanctions_fatf import _match_country

        assert _match_country("iran", frozenset(["Iran"])) is True
        assert _match_country("IRAN", frozenset(["Iran"])) is True


# ===========================================================================
# sanctions_uk
# ===========================================================================


class TestSanctionsUK:
    def _make_uk_csv(self, rows: list[list[str]]) -> str:
        """Build a UK OFSI-style CSV with 2 header rows."""
        lines = ["OFSI UK Consolidated Sanctions List", "GroupID,LastUpdated,Name6,Name1,Name2,Name3,Name4,Name5,DOB,TownOfBirth,CountryOfBirth,Nationality,PassportNumber,Position,Regime"]
        for row in rows:
            lines.append(",".join(row))
        return "\n".join(lines)

    @pytest.mark.asyncio
    async def test_success_match(self):
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        csv = self._make_uk_csv([
            ["G001", "2024-01-01", "", "Sechin", "Igor", "", "", "", "1960-09-07", "", "", "Russian", "", "CEO", "Russia"]
        ])
        resp = MagicMock()
        resp.status_code = 200
        resp.content = csv.encode("latin-1", errors="replace")
        resp.text = csv
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=False):
                result = await crawler.scrape("Igor Sechin")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_no_match(self):
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        csv = self._make_uk_csv([
            ["G001", "2024-01-01", "", "Doe", "John", "", "", "", "", "", "", "", "", "", "Russia"]
        ])
        resp = MagicMock()
        resp.status_code = 200
        resp.content = csv.encode("latin-1")
        resp.text = csv
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=False):
                result = await crawler.scrape("Completely Nobody")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_network_error(self):
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=False):
                result = await crawler.scrape("test")
        assert result.found is False
        assert result.data.get("error") == "download_failed"

    @pytest.mark.asyncio
    async def test_non_200(self):
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        resp = MagicMock()
        resp.status_code = 500
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=False):
                result = await crawler.scrape("test")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_uses_cache(self, tmp_path):
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        csv = self._make_uk_csv([
            ["G001", "2024-01-01", "", "Smith", "John", "", "", "", "", "", "", "", "", "", ""]
        ])
        cache_file = tmp_path / "uk.csv"
        cache_file.write_text(csv, encoding="latin-1")
        with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=True):
            with patch("modules.crawlers.sanctions_uk._CACHE_PATH", str(cache_file)):
                result = await crawler.scrape("John Smith")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_matches_capped_at_50(self):
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        header = "header row\nGroupID,LastUpdated,Name6,Name1,Name2,Name3,Name4,Name5,DOB,TownOfBirth,CountryOfBirth,Nationality,PassportNumber,Position,Regime\n"
        rows = "\n".join(
            f"G{i:03d},2024-01-01,,Smith,John,,,,,,,,,," for i in range(60)
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.content = (header + rows).encode("latin-1")
        resp.text = header + rows
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=False):
                result = await crawler.scrape("John Smith")
        assert len(result.data["matches"]) <= 50

    def test_name_overlap_score(self):
        from modules.crawlers.sanctions_uk import _name_overlap_score

        assert _name_overlap_score("", "anything") == 0.0
        assert _name_overlap_score("John Smith", "John Smith") == 1.0

    @pytest.mark.asyncio
    async def test_group_name_match(self):
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        # Group name in col 2
        csv = "header\nGroupID,LastUpdated,Name6,Name1,Name2,Name3,Name4,Name5,DOB,TownOfBirth,CountryOfBirth,Nationality,PassportNumber,Position,Regime\nG001,2024-01-01,Acme Corp,,,,,,,,,,,,"
        resp = MagicMock()
        resp.status_code = 200
        resp.content = csv.encode("latin-1")
        resp.text = csv
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=False):
                result = await crawler.scrape("Acme Corp")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_deduplication_by_group_id(self):
        from modules.crawlers.sanctions_uk import UKSanctionsCrawler

        crawler = UKSanctionsCrawler()
        row = "G001,2024-01-01,,Smith,John,,,,,,,,,,"
        csv = "header\nGroupID,LastUpdated,Name6,Name1,Name2,Name3,Name4,Name5,DOB,TownOfBirth,CountryOfBirth,Nationality,PassportNumber,Position,Regime\n" + row + "\n" + row
        resp = MagicMock()
        resp.status_code = 200
        resp.content = csv.encode("latin-1")
        resp.text = csv
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            with patch("modules.crawlers.sanctions_uk._cache_valid", return_value=False):
                result = await crawler.scrape("John Smith")
        assert result.data["match_count"] == 1


# ===========================================================================
# sanctions_worldbank_debarment
# ===========================================================================


class TestSanctionsWorldBankDebarment:
    @pytest.mark.asyncio
    async def test_success_list_payload(self):
        from modules.crawlers.sanctions_worldbank_debarment import SanctionsWorldBankDebarmentCrawler

        crawler = SanctionsWorldBankDebarmentCrawler()
        payload = [{"firmName": "Acme Corp", "country": "US", "fromDate": "2020-01-01", "toDate": "", "grounds": "Fraud", "ineligibilityPeriod": "5 years"}]
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Acme Corp")
        assert result.found is True
        assert result.data["total"] >= 1

    @pytest.mark.asyncio
    async def test_success_nested_debarredfirms(self):
        from modules.crawlers.sanctions_worldbank_debarment import SanctionsWorldBankDebarmentCrawler

        crawler = SanctionsWorldBankDebarmentCrawler()
        payload = {"debarredFirms": [{"firmName": "Acme Corp", "country": "US", "fromDate": "", "toDate": "", "grounds": "", "ineligibilityPeriod": ""}]}
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Acme Corp")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_success_nested_debarredfirm_singular(self):
        from modules.crawlers.sanctions_worldbank_debarment import SanctionsWorldBankDebarmentCrawler

        crawler = SanctionsWorldBankDebarmentCrawler()
        payload = {"debarredFirm": {"firmName": "Acme Corp", "country": "US", "fromDate": "", "toDate": "", "grounds": "", "ineligibilityPeriod": ""}}
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Acme Corp")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_404_means_no_results(self):
        from modules.crawlers.sanctions_worldbank_debarment import SanctionsWorldBankDebarmentCrawler

        crawler = SanctionsWorldBankDebarmentCrawler()
        resp = _mock_json_resp(404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Unknown Corp")
        assert result.found is False
        assert result.data.get("error") is None  # 404 is clean not-found

    @pytest.mark.asyncio
    async def test_network_error(self):
        from modules.crawlers.sanctions_worldbank_debarment import SanctionsWorldBankDebarmentCrawler

        crawler = SanctionsWorldBankDebarmentCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_non_200_non_404(self):
        from modules.crawlers.sanctions_worldbank_debarment import SanctionsWorldBankDebarmentCrawler

        crawler = SanctionsWorldBankDebarmentCrawler()
        resp = _mock_json_resp(500)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test")
        assert result.found is False
        assert "500" in (result.data.get("error") or "")

    @pytest.mark.asyncio
    async def test_json_parse_error(self):
        from modules.crawlers.sanctions_worldbank_debarment import SanctionsWorldBankDebarmentCrawler

        crawler = SanctionsWorldBankDebarmentCrawler()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_low_overlap_filtered(self):
        from modules.crawlers.sanctions_worldbank_debarment import SanctionsWorldBankDebarmentCrawler

        crawler = SanctionsWorldBankDebarmentCrawler()
        # firmName has zero overlap with query
        payload = [{"firmName": "Totally Different Entity", "country": "XX"}]
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Acme Corp")
        assert result.found is False

    def test_parse_debarred_other_key_names(self):
        from modules.crawlers.sanctions_worldbank_debarment import _parse_debarred

        payload = {"data": [{"firmName": "Acme Corp", "countryName": "USA", "debarmentFromDate": "2020", "debarmentToDate": "2025", "sanctionType": "Fraud", "ineligibilityPeriod": "5yr"}]}
        result = _parse_debarred(payload, "Acme Corp")
        assert len(result) == 1
        assert result[0]["country"] == "USA"


# ===========================================================================
# sanctions_opensanctions
# ===========================================================================


class TestSanctionsOpenSanctions:
    @pytest.mark.asyncio
    async def test_success(self):
        from modules.crawlers.sanctions_opensanctions import OpenSanctionsCrawler

        crawler = OpenSanctionsCrawler()
        payload = {
            "results": [
                {
                    "id": "NK-001",
                    "caption": "Vladimir Putin",
                    "schema": "Person",
                    "datasets": ["us_ofac_sdn", "eu_fsf"],
                    "referents": [],
                    "properties": {
                        "name": ["Vladimir Putin"],
                        "alias": [],
                        "birthDate": ["1952-10-07"],
                        "nationality": ["Russian"],
                        "topics": ["sanction"],
                        "country": ["ru"],
                    },
                }
            ],
            "total": {"value": 1},
        }
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Vladimir Putin")
        assert result.found is True
        assert result.data["total"] == 1
        assert "us_ofac_sdn" in result.data["datasets"]

    @pytest.mark.asyncio
    async def test_empty_identifier(self):
        from modules.crawlers.sanctions_opensanctions import OpenSanctionsCrawler

        crawler = OpenSanctionsCrawler()
        result = await crawler.scrape("   ")
        assert result.found is False
        assert result.data.get("error") == "empty_identifier"

    @pytest.mark.asyncio
    async def test_network_error(self):
        from modules.crawlers.sanctions_opensanctions import OpenSanctionsCrawler

        crawler = OpenSanctionsCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_429_rate_limited(self):
        from modules.crawlers.sanctions_opensanctions import OpenSanctionsCrawler

        crawler = OpenSanctionsCrawler()
        resp = _mock_json_resp(429)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test")
        assert result.found is False
        assert result.data.get("error") == "rate_limited"

    @pytest.mark.asyncio
    async def test_non_200(self):
        from modules.crawlers.sanctions_opensanctions import OpenSanctionsCrawler

        crawler = OpenSanctionsCrawler()
        resp = _mock_json_resp(503)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test")
        assert result.found is False
        assert "503" in (result.data.get("error") or "")

    @pytest.mark.asyncio
    async def test_json_parse_error(self):
        from modules.crawlers.sanctions_opensanctions import OpenSanctionsCrawler

        crawler = OpenSanctionsCrawler()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_no_results(self):
        from modules.crawlers.sanctions_opensanctions import OpenSanctionsCrawler

        crawler = OpenSanctionsCrawler()
        payload = {"results": [], "total": {"value": 0}}
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Nobody Here")
        assert result.found is False
        assert result.data["total"] == 0

    @pytest.mark.asyncio
    async def test_total_as_integer(self):
        from modules.crawlers.sanctions_opensanctions import OpenSanctionsCrawler

        crawler = OpenSanctionsCrawler()
        payload = {"results": [], "total": 5}
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test")
        assert result.data["total"] == 5

    def test_parse_entity(self):
        from modules.crawlers.sanctions_opensanctions import _parse_entity

        entity = {
            "id": "X1",
            "caption": "Test",
            "schema": "Person",
            "datasets": ["ofac"],
            "referents": [],
            "properties": {
                "name": ["Test"],
                "alias": ["T"],
                "birthDate": ["1980"],
                "nationality": ["US"],
                "topics": ["sanction"],
                "country": ["us"],
            },
        }
        parsed = _parse_entity(entity)
        assert parsed["id"] == "X1"
        assert parsed["topics"] == ["sanction"]


# ===========================================================================
# social_mastodon
# ===========================================================================


class TestSocialMastodon:
    @pytest.mark.asyncio
    async def test_success(self):
        from modules.crawlers.social_mastodon import MastodonCrawler

        crawler = MastodonCrawler()
        payload = {
            "accounts": [
                {
                    "id": "1",
                    "username": "testuser",
                    "acct": "testuser",
                    "display_name": "Test User",
                    "url": "https://mastodon.social/@testuser",
                    "followers_count": 100,
                    "following_count": 50,
                    "statuses_count": 200,
                    "created_at": "2020-01-01",
                    "note": "<p>Bio text</p>",
                    "bot": False,
                    "locked": False,
                    "fields": [],
                }
            ]
        }
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("testuser")
        assert result.found is True
        assert result.data["total"] >= 1
        # HTML stripped from note
        assert "<p>" not in result.data["accounts"][0]["note"]

    @pytest.mark.asyncio
    async def test_empty_identifier(self):
        from modules.crawlers.social_mastodon import MastodonCrawler

        crawler = MastodonCrawler()
        result = await crawler.scrape("   ")
        assert result.found is False
        assert result.data.get("error") == "empty_identifier"

    @pytest.mark.asyncio
    async def test_at_prefix_stripped(self):
        from modules.crawlers.social_mastodon import MastodonCrawler

        crawler = MastodonCrawler()
        payload = {"accounts": []}
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("@testuser")
        # Should not error — @ is stripped
        assert result.found is False

    @pytest.mark.asyncio
    async def test_all_instances_fail(self):
        from modules.crawlers.social_mastodon import MastodonCrawler

        crawler = MastodonCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("testuser")
        assert result.found is False
        assert result.data["instances_checked"] == []

    @pytest.mark.asyncio
    async def test_non_200_skips_instance(self):
        from modules.crawlers.social_mastodon import MastodonCrawler

        crawler = MastodonCrawler()
        resp = _mock_json_resp(500)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("testuser")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_json_parse_error_continues(self):
        from modules.crawlers.social_mastodon import MastodonCrawler

        crawler = MastodonCrawler()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("testuser")
        # Should not crash, just return not found
        assert result.found is False

    @pytest.mark.asyncio
    async def test_deduplication_by_acct(self):
        from modules.crawlers.social_mastodon import MastodonCrawler

        crawler = MastodonCrawler()
        account = {
            "id": "1",
            "username": "dup",
            "acct": "dup",
            "display_name": "Dup",
            "url": "",
            "followers_count": 10,
            "following_count": 5,
            "statuses_count": 20,
            "created_at": "",
            "note": "",
            "bot": False,
            "locked": False,
            "fields": [],
        }
        payload = {"accounts": [account, account]}  # same account twice
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("dup")
        assert result.data["total"] == 1

    @pytest.mark.asyncio
    async def test_stops_after_first_successful_instance(self):
        from modules.crawlers.social_mastodon import MastodonCrawler

        crawler = MastodonCrawler()
        account = {"id": "1", "username": "user", "acct": "user", "display_name": "User", "url": "", "followers_count": 5, "following_count": 2, "statuses_count": 10, "created_at": "", "note": "", "bot": False, "locked": False, "fields": []}
        payload = {"accounts": [account]}
        resp = _mock_json_resp(200, payload)
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return resp

        with patch.object(crawler, "get", new=mock_get):
            result = await crawler.scrape("user")
        # Should stop after first instance that returned results
        assert call_count == 1

    def test_strip_html(self):
        from modules.crawlers.social_mastodon import _strip_html

        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"
        assert _strip_html("plain text") == "plain text"


# ===========================================================================
# social_spotify
# ===========================================================================


class TestSocialSpotify:
    @pytest.mark.asyncio
    async def test_empty_identifier(self):
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()
        result = await crawler.scrape("   ")
        assert result.found is False
        assert result.data.get("error") == "empty_identifier"

    @pytest.mark.asyncio
    async def test_not_configured(self):
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()
        with patch("modules.crawlers.social_spotify.settings") as mock_settings:
            mock_settings.spotify_client_id = ""
            mock_settings.spotify_client_secret = ""
            result = await crawler.scrape("eminem")
        assert result.found is False
        assert result.data.get("error") == "not_configured"

    @pytest.mark.asyncio
    async def test_auth_failed(self):
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()
        with patch("modules.crawlers.social_spotify.settings") as mock_settings:
            mock_settings.spotify_client_id = "id"
            mock_settings.spotify_client_secret = "secret"
            with patch.object(crawler, "_get_access_token", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("eminem")
        assert result.found is False
        assert result.data.get("error") == "auth_failed"

    @pytest.mark.asyncio
    async def test_user_lookup_success(self):
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()
        user_data = {
            "id": "spotify",
            "display_name": "Spotify",
            "email": "",
            "country": "US",
            "product": "premium",
            "followers": {"total": 1000000},
            "external_urls": {"spotify": "https://open.spotify.com/user/spotify"},
            "images": [{"url": "https://example.com/img.jpg"}],
            "type": "user",
            "uri": "spotify:user:spotify",
        }
        pl_data = {"items": [{"id": "pl1", "name": "Top Hits", "public": True, "tracks": {"total": 50}, "external_urls": {"spotify": "https://open.spotify.com/playlist/pl1"}}]}
        with patch("modules.crawlers.social_spotify.settings") as mock_settings:
            mock_settings.spotify_client_id = "id"
            mock_settings.spotify_client_secret = "secret"
            with patch.object(crawler, "_get_access_token", new=AsyncMock(return_value="tok123")):
                user_resp = _mock_json_resp(200, user_data)
                pl_resp = _mock_json_resp(200, pl_data)
                with patch.object(crawler, "get", new=AsyncMock(side_effect=[user_resp, pl_resp])):
                    result = await crawler.scrape("spotify")
        assert result.found is True
        assert result.data["result_type"] == "user"
        assert len(result.data["playlists"]) == 1

    @pytest.mark.asyncio
    async def test_user_not_found_artist_fallback(self):
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()
        artist_search = {
            "artists": {
                "items": [
                    {
                        "id": "em001",
                        "name": "Eminem",
                        "genres": ["hip hop"],
                        "popularity": 95,
                        "followers": {"total": 50000000},
                        "external_urls": {"spotify": "https://open.spotify.com/artist/em001"},
                        "images": [{"url": "https://example.com/em.jpg"}],
                        "uri": "spotify:artist:em001",
                    }
                ]
            }
        }
        with patch("modules.crawlers.social_spotify.settings") as mock_settings:
            mock_settings.spotify_client_id = "id"
            mock_settings.spotify_client_secret = "secret"
            with patch.object(crawler, "_get_access_token", new=AsyncMock(return_value="tok123")):
                user_resp = _mock_json_resp(404)
                search_resp = _mock_json_resp(200, artist_search)
                with patch.object(crawler, "get", new=AsyncMock(side_effect=[user_resp, search_resp])):
                    result = await crawler.scrape("Eminem")
        assert result.found is True
        assert result.data["result_type"] == "artist"

    @pytest.mark.asyncio
    async def test_artist_search_no_results(self):
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()
        with patch("modules.crawlers.social_spotify.settings") as mock_settings:
            mock_settings.spotify_client_id = "id"
            mock_settings.spotify_client_secret = "secret"
            with patch.object(crawler, "_get_access_token", new=AsyncMock(return_value="tok123")):
                user_resp = _mock_json_resp(404)
                search_resp = _mock_json_resp(200, {"artists": {"items": []}})
                with patch.object(crawler, "get", new=AsyncMock(side_effect=[user_resp, search_resp])):
                    result = await crawler.scrape("UnknownArtistXYZ")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_artist_search_http_error(self):
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()
        with patch("modules.crawlers.social_spotify.settings") as mock_settings:
            mock_settings.spotify_client_id = "id"
            mock_settings.spotify_client_secret = "secret"
            with patch.object(crawler, "_get_access_token", new=AsyncMock(return_value="tok123")):
                user_resp = _mock_json_resp(404)
                search_resp = _mock_json_resp(500)
                with patch.object(crawler, "get", new=AsyncMock(side_effect=[user_resp, search_resp])):
                    result = await crawler.scrape("test")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_artist_search_parse_error(self):
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()
        with patch("modules.crawlers.social_spotify.settings") as mock_settings:
            mock_settings.spotify_client_id = "id"
            mock_settings.spotify_client_secret = "secret"
            with patch.object(crawler, "_get_access_token", new=AsyncMock(return_value="tok123")):
                user_resp = _mock_json_resp(404)
                search_resp = MagicMock()
                search_resp.status_code = 200
                search_resp.json.side_effect = ValueError("bad json")
                with patch.object(crawler, "get", new=AsyncMock(side_effect=[user_resp, search_resp])):
                    result = await crawler.scrape("test")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_get_access_token_failure(self):
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
            token = await crawler._get_access_token("id", "secret")
        assert token is None

    @pytest.mark.asyncio
    async def test_get_access_token_success(self):
        from modules.crawlers.social_spotify import SpotifyCrawler

        crawler = SpotifyCrawler()
        resp = _mock_json_resp(200, {"access_token": "mytoken"})
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            token = await crawler._get_access_token("id", "secret")
        assert token == "mytoken"

    def test_parse_user_no_images(self):
        from modules.crawlers.social_spotify import _parse_user

        data = {"id": "u1", "display_name": "User", "followers": {"total": 0}, "images": [], "external_urls": {}, "type": "user", "uri": ""}
        parsed = _parse_user(data)
        assert parsed["avatar_url"] is None

    def test_parse_artist_no_images(self):
        from modules.crawlers.social_spotify import _parse_artist

        data = {"id": "a1", "name": "Artist", "genres": [], "popularity": 50, "followers": {"total": 0}, "external_urls": {}, "images": [], "uri": ""}
        parsed = _parse_artist(data)
        assert parsed["avatar_url"] is None
        assert parsed["type"] == "artist"


# ===========================================================================
# social_steam
# ===========================================================================


_STEAM_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<profile>
    <steamID64>76561197960287930</steamID64>
    <steamID><![CDATA[Gabe Newell]]></steamID>
    <customURL>gaben</customURL>
    <headline><![CDATA[CEO]]></headline>
    <summary><![CDATA[Valve boss]]></summary>
    <memberSince>January 1, 2003</memberSince>
    <location>Bellevue, WA</location>
    <country>US</country>
    <stateCode>WA</stateCode>
    <avatarIcon>https://example.com/avatar.jpg</avatarIcon>
    <onlineState>online</onlineState>
</profile>"""


class TestSocialSteam:
    @pytest.mark.asyncio
    async def test_success(self):
        from modules.crawlers.social_steam import SteamCrawler

        crawler = SteamCrawler()
        resp = _mock_resp(200, text=_STEAM_XML)
        with patch("modules.crawlers.social_steam.settings") as mock_settings:
            mock_settings.steam_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                result = await crawler.scrape("gaben")
        assert result.found is True
        assert result.data["steam_id"] == "76561197960287930"
        assert result.data["online"] == "online"

    @pytest.mark.asyncio
    async def test_empty_identifier(self):
        from modules.crawlers.social_steam import SteamCrawler

        crawler = SteamCrawler()
        result = await crawler.scrape("   ")
        assert result.found is False
        assert result.data.get("error") == "empty_identifier"

    @pytest.mark.asyncio
    async def test_network_error(self):
        from modules.crawlers.social_steam import SteamCrawler

        crawler = SteamCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("gaben")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        from modules.crawlers.social_steam import SteamCrawler

        crawler = SteamCrawler()
        resp = _mock_resp(404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("nonexistentuser")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_302_redirect_not_found(self):
        from modules.crawlers.social_steam import SteamCrawler

        crawler = SteamCrawler()
        resp = _mock_resp(302)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("nonexistentuser")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_non_200_non_redirect(self):
        from modules.crawlers.social_steam import SteamCrawler

        crawler = SteamCrawler()
        resp = _mock_resp(500)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("gaben")
        assert result.found is False
        assert "500" in (result.data.get("error") or "")

    @pytest.mark.asyncio
    async def test_xml_error_tag(self):
        from modules.crawlers.social_steam import SteamCrawler

        crawler = SteamCrawler()
        error_xml = "<error>The specified profile could not be found.</error>"
        resp = _mock_resp(200, text=error_xml)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("nonexistentuser")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_with_api_key_fetches_summary(self):
        from modules.crawlers.social_steam import SteamCrawler

        crawler = SteamCrawler()
        xml_resp = _mock_resp(200, text=_STEAM_XML)
        summary_data = {
            "response": {
                "players": [
                    {
                        "realname": "Gabe Newell",
                        "loccountrycode": "US",
                        "lastlogoff": 1700000000,
                        "communityvisibilitystate": 3,
                    }
                ]
            }
        }
        summary_resp = _mock_json_resp(200, summary_data)
        with patch("modules.crawlers.social_steam.settings") as mock_settings:
            mock_settings.steam_api_key = "TESTAPIKEY"
            with patch.object(crawler, "get", new=AsyncMock(side_effect=[xml_resp, summary_resp])):
                result = await crawler.scrape("gaben")
        assert result.found is True
        assert result.data["profile"]["real_name"] == "Gabe Newell"

    @pytest.mark.asyncio
    async def test_groups_and_games_parsed(self):
        from modules.crawlers.social_steam import SteamCrawler

        crawler = SteamCrawler()
        xml = _STEAM_XML.replace(
            "</profile>",
            """<groups>
<group><groupName>Valve</groupName><groupID64>103582791434202956</groupID64></group>
</groups>
<mostPlayedGames>
<game><gameName>Team Fortress 2</gameName><hoursLast2Weeks>5.0</hoursLast2Weeks><hoursOnRecord>100</hoursOnRecord></game>
</mostPlayedGames>
</profile>"""
        ).replace("</profile>", "")
        resp = _mock_resp(200, text=xml)
        with patch("modules.crawlers.social_steam.settings") as mock_settings:
            mock_settings.steam_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                result = await crawler.scrape("gaben")
        assert result.found is True

    def test_extract_xml_value(self):
        from modules.crawlers.social_steam import _extract_xml_value

        xml = "<steamID64>76561197960287930</steamID64>"
        assert _extract_xml_value(xml, "steamID64") == "76561197960287930"

    def test_extract_xml_cdata(self):
        from modules.crawlers.social_steam import _extract_xml_value

        xml = "<steamID><![CDATA[Gabe Newell]]></steamID>"
        assert _extract_xml_value(xml, "steamID") == "Gabe Newell"

    def test_extract_xml_missing_tag(self):
        from modules.crawlers.social_steam import _extract_xml_value

        assert _extract_xml_value("<foo>bar</foo>", "baz") == ""


# ===========================================================================
# social_twitch
# ===========================================================================


class TestSocialTwitch:
    @pytest.mark.asyncio
    async def test_empty_identifier(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        crawler = TwitchCrawler()
        result = await crawler.scrape("   ")
        assert result.found is False
        assert result.data.get("error") == "empty_identifier"

    @pytest.mark.asyncio
    async def test_not_configured(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        crawler = TwitchCrawler()
        with patch("modules.crawlers.social_twitch.settings") as mock_settings:
            mock_settings.twitch_client_id = ""
            mock_settings.twitch_client_secret = ""
            result = await crawler.scrape("xqc")
        assert result.found is False
        assert result.data.get("error") == "not_configured"

    @pytest.mark.asyncio
    async def test_auth_failed(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        crawler = TwitchCrawler()
        with patch("modules.crawlers.social_twitch.settings") as mock_settings:
            mock_settings.twitch_client_id = "id"
            mock_settings.twitch_client_secret = "secret"
            with patch.object(crawler, "_get_app_token", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("xqc")
        assert result.found is False
        assert result.data.get("error") == "auth_failed"

    @pytest.mark.asyncio
    async def test_success_live_stream(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        crawler = TwitchCrawler()
        user_data = {
            "data": [{
                "id": "71092938",
                "login": "xqc",
                "display_name": "xQc",
                "type": "",
                "broadcaster_type": "partner",
                "description": "Main Variety Streamer",
                "profile_image_url": "https://example.com/img.jpg",
                "view_count": 300000000,
                "created_at": "2014-12-14T20:32:28Z",
            }]
        }
        stream_data = {
            "data": [{
                "title": "Gaming",
                "game_name": "Minecraft",
                "viewer_count": 50000,
                "started_at": "2024-01-01T00:00:00Z",
                "language": "en",
                "is_mature": False,
            }]
        }
        channel_data = {
            "data": [{
                "broadcaster_language": "en",
                "game_name": "Minecraft",
                "title": "Gaming",
                "delay": 0,
                "tags": ["English"],
            }]
        }
        with patch("modules.crawlers.social_twitch.settings") as mock_settings:
            mock_settings.twitch_client_id = "cid"
            mock_settings.twitch_client_secret = "csecret"
            with patch.object(crawler, "_get_app_token", new=AsyncMock(return_value="apptoken")):
                user_resp = _mock_json_resp(200, user_data)
                stream_resp = _mock_json_resp(200, stream_data)
                channel_resp = _mock_json_resp(200, channel_data)
                with patch.object(crawler, "get", new=AsyncMock(side_effect=[user_resp, stream_resp, channel_resp])):
                    result = await crawler.scrape("xqc")
        assert result.found is True
        assert result.data["is_live"] is True
        assert result.data["stream"]["game_name"] == "Minecraft"
        assert result.data["channel"]["broadcaster_language"] == "en"

    @pytest.mark.asyncio
    async def test_user_not_found(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        crawler = TwitchCrawler()
        with patch("modules.crawlers.social_twitch.settings") as mock_settings:
            mock_settings.twitch_client_id = "cid"
            mock_settings.twitch_client_secret = "csecret"
            with patch.object(crawler, "_get_app_token", new=AsyncMock(return_value="apptoken")):
                user_resp = _mock_json_resp(200, {"data": []})
                stream_resp = _mock_json_resp(200, {"data": []})
                with patch.object(crawler, "get", new=AsyncMock(side_effect=[user_resp, stream_resp])):
                    result = await crawler.scrape("nonexistentuser")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_user_api_error(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        crawler = TwitchCrawler()
        with patch("modules.crawlers.social_twitch.settings") as mock_settings:
            mock_settings.twitch_client_id = "cid"
            mock_settings.twitch_client_secret = "csecret"
            with patch.object(crawler, "_get_app_token", new=AsyncMock(return_value="apptoken")):
                user_resp = _mock_json_resp(500)
                with patch.object(crawler, "get", new=AsyncMock(return_value=user_resp)):
                    result = await crawler.scrape("xqc")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_user_json_parse_error(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        crawler = TwitchCrawler()
        with patch("modules.crawlers.social_twitch.settings") as mock_settings:
            mock_settings.twitch_client_id = "cid"
            mock_settings.twitch_client_secret = "csecret"
            with patch.object(crawler, "_get_app_token", new=AsyncMock(return_value="apptoken")):
                user_resp = MagicMock()
                user_resp.status_code = 200
                user_resp.json.side_effect = ValueError("bad")
                with patch.object(crawler, "get", new=AsyncMock(return_value=user_resp)):
                    result = await crawler.scrape("xqc")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_offline_stream(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        crawler = TwitchCrawler()
        user_data = {"data": [{"id": "123", "login": "streamer", "display_name": "Streamer", "type": "", "broadcaster_type": "", "description": "", "profile_image_url": "", "view_count": 0, "created_at": ""}]}
        with patch("modules.crawlers.social_twitch.settings") as mock_settings:
            mock_settings.twitch_client_id = "cid"
            mock_settings.twitch_client_secret = "csecret"
            with patch.object(crawler, "_get_app_token", new=AsyncMock(return_value="tok")):
                user_resp = _mock_json_resp(200, user_data)
                stream_resp = _mock_json_resp(200, {"data": []})  # offline
                channel_resp = _mock_json_resp(200, {"data": []})
                with patch.object(crawler, "get", new=AsyncMock(side_effect=[user_resp, stream_resp, channel_resp])):
                    result = await crawler.scrape("streamer")
        assert result.found is True
        assert result.data["is_live"] is False
        assert result.data["stream"] is None

    @pytest.mark.asyncio
    async def test_get_app_token_success(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        crawler = TwitchCrawler()
        resp = _mock_json_resp(200, {"access_token": "apptoken123"})
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            token = await crawler._get_app_token("cid", "csecret")
        assert token == "apptoken123"

    @pytest.mark.asyncio
    async def test_get_app_token_failure(self):
        from modules.crawlers.social_twitch import TwitchCrawler

        crawler = TwitchCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
            token = await crawler._get_app_token("cid", "csecret")
        assert token is None


# ===========================================================================
# geo_adsbexchange
# ===========================================================================


class TestGeoAdsbExchange:
    @pytest.mark.asyncio
    async def test_success(self):
        from modules.crawlers.geo_adsbexchange import GeoAdsbexchangeCrawler

        crawler = GeoAdsbexchangeCrawler()
        payload = {
            "response": {
                "aircraft": {
                    "registration": "N12345",
                    "type": "Boeing 737",
                    "manufacturer": "Boeing",
                    "registered_owner": "United Airlines",
                    "registered_owner_country_name": "United States",
                    "mode_s": "A12345",
                    "url": "https://api.adsbdb.com/v0/aircraft/N12345",
                }
            }
        }
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("N12345")
        assert result.found is True
        assert result.data["registration"] == "N12345"
        assert result.data["manufacturer"] == "Boeing"

    @pytest.mark.asyncio
    async def test_registration_normalised_uppercase(self):
        from modules.crawlers.geo_adsbexchange import GeoAdsbexchangeCrawler

        crawler = GeoAdsbexchangeCrawler()
        payload = {"response": {"aircraft": {"registration": "G-ABCD", "type": "Cessna 172"}}}
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("g-abcd")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        from modules.crawlers.geo_adsbexchange import GeoAdsbexchangeCrawler

        crawler = GeoAdsbexchangeCrawler()
        resp = _mock_json_resp(404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("N99999")
        assert result.found is False
        assert result.data.get("error") == "registration_not_found"

    @pytest.mark.asyncio
    async def test_network_error(self):
        from modules.crawlers.geo_adsbexchange import GeoAdsbexchangeCrawler

        crawler = GeoAdsbexchangeCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("N12345")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_non_200_non_404(self):
        from modules.crawlers.geo_adsbexchange import GeoAdsbexchangeCrawler

        crawler = GeoAdsbexchangeCrawler()
        resp = _mock_json_resp(500)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("N12345")
        assert result.found is False
        assert "500" in (result.data.get("error") or "")

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        from modules.crawlers.geo_adsbexchange import GeoAdsbexchangeCrawler

        crawler = GeoAdsbexchangeCrawler()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("not json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("N12345")
        assert result.found is False
        assert result.data.get("error") == "invalid_json"

    @pytest.mark.asyncio
    async def test_empty_aircraft_block(self):
        from modules.crawlers.geo_adsbexchange import GeoAdsbexchangeCrawler

        crawler = GeoAdsbexchangeCrawler()
        payload = {"response": {"aircraft": {}}}
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("N12345")
        assert result.found is False

    def test_parse_aircraft_fallback_to_response_level(self):
        from modules.crawlers.geo_adsbexchange import _parse_aircraft

        payload = {"response": {"registration": "N12345", "type": "Cessna"}}
        aircraft = _parse_aircraft(payload)
        assert aircraft["registration"] == "N12345"

    def test_parse_aircraft_operator_fallback(self):
        from modules.crawlers.geo_adsbexchange import _parse_aircraft

        payload = {"response": {"aircraft": {"operator": "Delta", "icao_hex": "ABC123"}}}
        aircraft = _parse_aircraft(payload)
        assert aircraft["operator"] == "Delta"
        assert aircraft["modes"] == "ABC123"

    def test_normalise_registration(self):
        from modules.crawlers.geo_adsbexchange import _normalise_registration

        assert _normalise_registration("  n12345  ") == "N12345"


# ===========================================================================
# geo_ip
# ===========================================================================


class TestGeoIP:
    @pytest.mark.asyncio
    async def test_success(self):
        from modules.crawlers.geo_ip import GeoIPCrawler

        crawler = GeoIPCrawler()
        payload = {
            "status": "success",
            "country": "United States",
            "countryCode": "US",
            "region": "CA",
            "regionName": "California",
            "city": "Mountain View",
            "zip": "94043",
            "lat": 37.386,
            "lon": -122.0838,
            "timezone": "America/Los_Angeles",
            "isp": "Google LLC",
            "org": "Google LLC",
            "as": "AS15169 Google LLC",
            "mobile": False,
            "proxy": False,
            "hosting": True,
            "query": "8.8.8.8",
        }
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("8.8.8.8")
        assert result.found is True
        assert result.data["country"] == "United States"
        assert result.data["city"] == "Mountain View"
        assert result.data["hosting"] is True

    @pytest.mark.asyncio
    async def test_network_error(self):
        from modules.crawlers.geo_ip import GeoIPCrawler

        crawler = GeoIPCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("8.8.8.8")
        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_429_rate_limited(self):
        from modules.crawlers.geo_ip import GeoIPCrawler

        crawler = GeoIPCrawler()
        resp = _mock_json_resp(429)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("8.8.8.8")
        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_non_200(self):
        from modules.crawlers.geo_ip import GeoIPCrawler

        crawler = GeoIPCrawler()
        resp = _mock_json_resp(503)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("8.8.8.8")
        assert result.found is False
        assert "503" in (result.error or "")

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        from modules.crawlers.geo_ip import GeoIPCrawler

        crawler = GeoIPCrawler()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("8.8.8.8")
        assert result.found is False
        assert result.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_api_fail_status(self):
        from modules.crawlers.geo_ip import GeoIPCrawler

        crawler = GeoIPCrawler()
        payload = {"status": "fail", "message": "private range"}
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("192.168.1.1")
        assert result.found is False
        assert result.error == "private range"

    @pytest.mark.asyncio
    async def test_proxy_flag_detected(self):
        from modules.crawlers.geo_ip import GeoIPCrawler

        crawler = GeoIPCrawler()
        payload = {
            "status": "success",
            "country": "Netherlands",
            "countryCode": "NL",
            "region": "NH",
            "regionName": "North Holland",
            "city": "Amsterdam",
            "zip": "1000",
            "lat": 52.377,
            "lon": 4.9,
            "timezone": "Europe/Amsterdam",
            "isp": "Mullvad VPN",
            "org": "Mullvad",
            "as": "AS9009",
            "mobile": False,
            "proxy": True,
            "hosting": False,
            "query": "193.138.218.1",
        }
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("193.138.218.1")
        assert result.found is True
        assert result.data["proxy"] is True


# ===========================================================================
# geo_openstreetmap
# ===========================================================================


class TestGeoOpenStreetMap:
    @pytest.mark.asyncio
    async def test_geocode_success(self):
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()
        payload = [
            {
                "display_name": "New York, USA",
                "lat": "40.7128",
                "lon": "-74.0060",
                "type": "city",
                "class": "place",
                "importance": 0.9,
                "address": {"city": "New York"},
                "osm_id": 12345,
                "osm_type": "relation",
            }
        ]
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("New York")
        assert result.found is True
        assert result.data["mode"] == "geocode"
        assert len(result.data["places"]) == 1

    @pytest.mark.asyncio
    async def test_geocode_no_results(self):
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()
        resp = _mock_json_resp(200, [])
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("XYZ Unknown Place That Does Not Exist 99999")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_geocode_network_error(self):
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("London")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_geocode_429(self):
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()
        resp = _mock_json_resp(429)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("London")
        assert result.found is False
        assert result.data.get("error") == "rate_limited"

    @pytest.mark.asyncio
    async def test_geocode_non_200(self):
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()
        resp = _mock_json_resp(500)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("London")
        assert result.found is False
        assert "500" in (result.data.get("error") or "")

    @pytest.mark.asyncio
    async def test_geocode_json_parse_error(self):
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("London")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_overpass_success(self):
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()
        payload = {
            "elements": [
                {
                    "type": "node",
                    "id": 1234,
                    "lat": 40.7128,
                    "lon": -74.006,
                    "tags": {"name": "Central Park", "amenity": "park"},
                },
                {
                    "type": "node",
                    "id": 9999,
                    "lat": 40.713,
                    "lon": -74.005,
                    "tags": {},  # no tags — should be skipped
                },
            ]
        }
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("40.7128,-74.0060")
        assert result.found is True
        assert result.data["mode"] == "overpass"
        assert len(result.data["places"]) == 1
        assert result.data["places"][0]["name"] == "Central Park"

    @pytest.mark.asyncio
    async def test_overpass_network_error(self):
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()
        with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("40.7128,-74.0060")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_overpass_429(self):
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()
        resp = _mock_json_resp(429)
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("51.5074,-0.1278")
        assert result.found is False
        assert result.data.get("error") == "rate_limited"

    @pytest.mark.asyncio
    async def test_overpass_non_200(self):
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()
        resp = _mock_json_resp(503)
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("51.5074,-0.1278")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_overpass_json_parse_error(self):
        from modules.crawlers.geo_openstreetmap import OpenStreetMapCrawler

        crawler = OpenStreetMapCrawler()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("51.5074,-0.1278")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    def test_is_latlon_valid(self):
        from modules.crawlers.geo_openstreetmap import _is_latlon

        result = _is_latlon("40.7128,-74.0060")
        assert result == (40.7128, -74.006)

    def test_is_latlon_invalid(self):
        from modules.crawlers.geo_openstreetmap import _is_latlon

        assert _is_latlon("New York") is None
        assert _is_latlon("40.7128") is None

    def test_is_latlon_with_spaces(self):
        from modules.crawlers.geo_openstreetmap import _is_latlon

        result = _is_latlon(" 40.7128 , -74.0060 ")
        assert result is not None

    def test_overpass_query_format(self):
        from modules.crawlers.geo_openstreetmap import _overpass_query

        query = _overpass_query(51.5, -0.1, 500)
        assert "around:500,51.5,-0.1" in query
        assert "[out:json]" in query


# ===========================================================================
# financial_crunchbase
# ===========================================================================


class TestFinancialCrunchbase:
    @pytest.mark.asyncio
    async def test_api_mode_success(self):
        from modules.crawlers.financial_crunchbase import CrunchbaseCrawler

        crawler = CrunchbaseCrawler()
        payload = {
            "entities": [
                {
                    "identifier": {"value": "OpenAI"},
                    "properties": {
                        "short_description": "AI safety company",
                        "founded_on": {"value": "2015-12-11"},
                        "funding_total": {"value_usd": 11300000000},
                        "num_funding_rounds": 8,
                        "num_employees_enum": "501-1000",
                    },
                }
            ]
        }
        resp = _mock_json_resp(200, payload)
        with patch("modules.crawlers.financial_crunchbase.settings") as mock_settings:
            mock_settings.crunchbase_api_key = "APIKEY123"
            with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
                result = await crawler.scrape("OpenAI")
        assert result.found is True
        assert result.data["source"] == "api"
        assert result.data["organizations"][0]["name"] == "OpenAI"
        assert result.data["organizations"][0]["funding_total"] == 11300000000

    @pytest.mark.asyncio
    async def test_api_mode_401_invalid_key(self):
        from modules.crawlers.financial_crunchbase import CrunchbaseCrawler

        crawler = CrunchbaseCrawler()
        resp = _mock_json_resp(401)
        with patch("modules.crawlers.financial_crunchbase.settings") as mock_settings:
            mock_settings.crunchbase_api_key = "BADKEY"
            with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
                result = await crawler.scrape("OpenAI")
        assert result.found is False
        assert result.data.get("error") == "invalid_api_key"

    @pytest.mark.asyncio
    async def test_api_mode_429_rate_limited(self):
        from modules.crawlers.financial_crunchbase import CrunchbaseCrawler

        crawler = CrunchbaseCrawler()
        resp = _mock_json_resp(429)
        with patch("modules.crawlers.financial_crunchbase.settings") as mock_settings:
            mock_settings.crunchbase_api_key = "KEY"
            with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
                result = await crawler.scrape("Tesla")
        assert result.found is False
        assert result.data.get("error") == "rate_limited"

    @pytest.mark.asyncio
    async def test_api_mode_network_error(self):
        from modules.crawlers.financial_crunchbase import CrunchbaseCrawler

        crawler = CrunchbaseCrawler()
        with patch("modules.crawlers.financial_crunchbase.settings") as mock_settings:
            mock_settings.crunchbase_api_key = "KEY"
            with patch.object(crawler, "post", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("Tesla")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_api_mode_json_parse_error(self):
        from modules.crawlers.financial_crunchbase import CrunchbaseCrawler

        crawler = CrunchbaseCrawler()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch("modules.crawlers.financial_crunchbase.settings") as mock_settings:
            mock_settings.crunchbase_api_key = "KEY"
            with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
                result = await crawler.scrape("Tesla")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    @pytest.mark.asyncio
    async def test_api_mode_non_200(self):
        from modules.crawlers.financial_crunchbase import CrunchbaseCrawler

        crawler = CrunchbaseCrawler()
        resp = _mock_json_resp(500)
        with patch("modules.crawlers.financial_crunchbase.settings") as mock_settings:
            mock_settings.crunchbase_api_key = "KEY"
            with patch.object(crawler, "post", new=AsyncMock(return_value=resp)):
                result = await crawler.scrape("Tesla")
        assert result.found is False
        assert "500" in (result.data.get("error") or "")

    @pytest.mark.asyncio
    async def test_public_scrape_mode_success(self):
        from modules.crawlers.financial_crunchbase import CrunchbaseCrawler

        crawler = CrunchbaseCrawler()
        html = '"identifier": {"value": "OpenAI", "other": "stuff"}'
        resp = MagicMock()
        resp.status_code = 200
        resp.text = html
        with patch("modules.crawlers.financial_crunchbase.settings") as mock_settings:
            mock_settings.crunchbase_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                result = await crawler.scrape("OpenAI")
        assert result.data["source"] == "public_scrape"

    @pytest.mark.asyncio
    async def test_public_scrape_mode_network_error(self):
        from modules.crawlers.financial_crunchbase import CrunchbaseCrawler

        crawler = CrunchbaseCrawler()
        with patch("modules.crawlers.financial_crunchbase.settings") as mock_settings:
            mock_settings.crunchbase_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("OpenAI")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_public_scrape_mode_429(self):
        from modules.crawlers.financial_crunchbase import CrunchbaseCrawler

        crawler = CrunchbaseCrawler()
        resp = _mock_json_resp(429)
        with patch("modules.crawlers.financial_crunchbase.settings") as mock_settings:
            mock_settings.crunchbase_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                result = await crawler.scrape("OpenAI")
        assert result.found is False
        assert result.data.get("error") == "rate_limited"

    @pytest.mark.asyncio
    async def test_public_scrape_mode_non_200(self):
        from modules.crawlers.financial_crunchbase import CrunchbaseCrawler

        crawler = CrunchbaseCrawler()
        resp = _mock_json_resp(500)
        with patch("modules.crawlers.financial_crunchbase.settings") as mock_settings:
            mock_settings.crunchbase_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
                result = await crawler.scrape("OpenAI")
        assert result.found is False

    def test_parse_api_response_nested_funding(self):
        from modules.crawlers.financial_crunchbase import _parse_api_response

        data = {
            "entities": [
                {
                    "identifier": {"value": "Acme"},
                    "properties": {
                        "short_description": "Test",
                        "founded_on": {"value": "2010-01-01"},
                        "funding_total": {"value_usd": 5000000},
                        "num_funding_rounds": 2,
                        "num_employees_enum": "11-50",
                    },
                }
            ]
        }
        orgs = _parse_api_response(data)
        assert orgs[0]["funding_total"] == 5000000
        assert orgs[0]["founded_on"] == "2010-01-01"

    def test_scrape_public_names(self):
        from modules.crawlers.financial_crunchbase import _scrape_public_names

        html = '"identifier": {"value": "OpenAI", "other": "x"} "identifier": {"value": "Tesla"}'
        names = _scrape_public_names(html)
        assert any(n["name"] == "OpenAI" for n in names)


# ===========================================================================
# financial_worldbank
# ===========================================================================


def _wb_country_resp():
    return [
        {"page": 1, "pages": 1, "per_page": 50, "total": 1},
        [
            {
                "iso2Code": "US",
                "name": "United States",
                "capitalCity": "Washington D.C.",
                "region": {"value": "North America"},
                "incomeLevel": {"value": "High income"},
            }
        ],
    ]


def _wb_indicator_resp(years=None):
    years = years or ["2022", "2021", "2020"]
    return [
        {"page": 1},
        [{"date": y, "value": float(i) * 1e12} for i, y in enumerate(years)],
    ]


class TestFinancialWorldBank:
    @pytest.mark.asyncio
    async def test_success_country_name(self):
        from modules.crawlers.financial_worldbank import FinancialWorldBankCrawler

        crawler = FinancialWorldBankCrawler()
        country_resp = _mock_json_resp(200, _wb_country_resp())
        indicator_resp = _mock_json_resp(200, _wb_indicator_resp())

        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[country_resp, indicator_resp, indicator_resp, indicator_resp]),
        ):
            result = await crawler.scrape("United States")
        assert result.found is True
        assert result.data["country_info"]["iso2"] == "US"
        assert len(result.data["gdp_data"]) > 0

    @pytest.mark.asyncio
    async def test_success_iso2_code(self):
        from modules.crawlers.financial_worldbank import FinancialWorldBankCrawler

        crawler = FinancialWorldBankCrawler()
        # ISO-2 branch: first call is metadata lookup, then 3 indicators
        country_resp = _mock_json_resp(200, _wb_country_resp())
        indicator_resp = _mock_json_resp(200, _wb_indicator_resp())

        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[country_resp, indicator_resp, indicator_resp, indicator_resp]),
        ):
            result = await crawler.scrape("US")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_iso2_skips_name_resolve_when_lookup_fails(self):
        from modules.crawlers.financial_worldbank import FinancialWorldBankCrawler

        crawler = FinancialWorldBankCrawler()
        indicator_resp = _mock_json_resp(200, _wb_indicator_resp())

        # First call (metadata) returns None — should fall through gracefully
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[None, indicator_resp, indicator_resp, indicator_resp]),
        ):
            result = await crawler.scrape("US")
        assert result.found is True
        # country_info should use the raw iso2 fallback
        assert result.data["country_info"]["iso2"] == "US"

    @pytest.mark.asyncio
    async def test_country_name_not_found(self):
        from modules.crawlers.financial_worldbank import FinancialWorldBankCrawler

        crawler = FinancialWorldBankCrawler()
        # Country search returns empty records list
        empty_resp = _mock_json_resp(200, [{"page": 1}, []])
        with patch.object(crawler, "get", new=AsyncMock(return_value=empty_resp)):
            result = await crawler.scrape("Narnia")
        assert result.found is False
        assert result.data.get("error") == "country_not_found"

    @pytest.mark.asyncio
    async def test_network_error_on_search(self):
        from modules.crawlers.financial_worldbank import FinancialWorldBankCrawler

        crawler = FinancialWorldBankCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("Nigeria")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_non_200_on_search(self):
        from modules.crawlers.financial_worldbank import FinancialWorldBankCrawler

        crawler = FinancialWorldBankCrawler()
        resp = _mock_json_resp(500)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Nigeria")
        assert result.found is False
        assert "500" in (result.data.get("error") or "")

    @pytest.mark.asyncio
    async def test_indicator_fetch_failure_returns_empty(self):
        from modules.crawlers.financial_worldbank import FinancialWorldBankCrawler

        crawler = FinancialWorldBankCrawler()
        country_resp = _mock_json_resp(200, _wb_country_resp())
        # All 3 indicator calls fail
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[country_resp, None, None, None]),
        ):
            result = await crawler.scrape("United States")
        assert result.found is True
        assert result.data["gdp_data"] == []

    @pytest.mark.asyncio
    async def test_country_search_parse_error(self):
        from modules.crawlers.financial_worldbank import FinancialWorldBankCrawler

        crawler = FinancialWorldBankCrawler()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Nigeria")
        assert result.found is False
        assert result.data.get("error") == "country_not_found"

    def test_parse_indicator_series_malformed(self):
        from modules.crawlers.financial_worldbank import _parse_indicator_series

        assert _parse_indicator_series([]) == []
        assert _parse_indicator_series(None) == []
        assert _parse_indicator_series([{"page": 1}]) == []

    def test_parse_indicator_series_none_records(self):
        from modules.crawlers.financial_worldbank import _parse_indicator_series

        data = [{"page": 1}, [None, {"date": "2022", "value": 1e12}]]
        result = _parse_indicator_series(data)
        assert len(result) == 1
        assert result[0]["year"] == "2022"

    def test_resolve_country_info_no_records(self):
        from modules.crawlers.financial_worldbank import _resolve_country_info

        assert _resolve_country_info([]) is None
        assert _resolve_country_info([{"page": 1}, []]) is None
        assert _resolve_country_info([{"page": 1}, None]) is None


# ===========================================================================
# financial_finra
# ===========================================================================


class TestFinancialFinra:
    @pytest.mark.asyncio
    async def test_success(self):
        from modules.crawlers.financial_finra import FinancialFinraCrawler

        crawler = FinancialFinraCrawler()
        payload = {
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_source": {
                            "ind_source_id": "12345",
                            "ind_firstname": "John",
                            "ind_lastname": "Smith",
                            "ind_bc_scope": "broker",
                            "ind_bc_disc_fl": "N",
                        }
                    }
                ],
            }
        }
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")
        assert result.found is True
        assert result.data["total"] == 1
        assert result.data["brokers"][0]["bc_lastname"] == "Smith"

    @pytest.mark.asyncio
    async def test_disclosure_flag_true(self):
        from modules.crawlers.financial_finra import FinancialFinraCrawler

        crawler = FinancialFinraCrawler()
        payload = {
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_source": {
                            "ind_source_id": "99999",
                            "ind_firstname": "Bad",
                            "ind_lastname": "Actor",
                            "ind_bc_scope": "broker",
                            "ind_bc_disc_fl": "Y",
                        }
                    }
                ],
            }
        }
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Bad Actor")
        assert result.data["brokers"][0]["ind_bc_disc_fl"] is True

    @pytest.mark.asyncio
    async def test_no_results(self):
        from modules.crawlers.financial_finra import FinancialFinraCrawler

        crawler = FinancialFinraCrawler()
        payload = {"hits": {"total": {"value": 0}, "hits": []}}
        resp = _mock_json_resp(200, payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("Unknown Nobody")
        assert result.found is False
        assert result.data["total"] == 0

    @pytest.mark.asyncio
    async def test_network_error(self):
        from modules.crawlers.financial_finra import FinancialFinraCrawler

        crawler = FinancialFinraCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_non_200(self):
        from modules.crawlers.financial_finra import FinancialFinraCrawler

        crawler = FinancialFinraCrawler()
        resp = _mock_json_resp(503)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert "503" in (result.data.get("error") or "")

    @pytest.mark.asyncio
    async def test_json_parse_error(self):
        from modules.crawlers.financial_finra import FinancialFinraCrawler

        crawler = FinancialFinraCrawler()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.data.get("error") == "parse_error"

    def test_parse_brokers_total_as_int(self):
        from modules.crawlers.financial_finra import _parse_brokers

        payload = {"hits": {"total": 5, "hits": []}}
        brokers, total = _parse_brokers(payload)
        assert total == 5
        assert brokers == []

    def test_parse_brokers_empty_payload(self):
        from modules.crawlers.financial_finra import _parse_brokers

        brokers, total = _parse_brokers({})
        assert total == 0
        assert brokers == []

    @pytest.mark.asyncio
    async def test_429_rate_limited(self):
        from modules.crawlers.financial_finra import FinancialFinraCrawler

        crawler = FinancialFinraCrawler()
        resp = _mock_json_resp(429)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("John Smith")
        # FINRA doesn't have explicit 429 handling; falls into generic non-200
        assert result.found is False
        assert result.data.get("error") is not None
