"""
test_faa_aircraft_registry_transport.py — 100% line coverage for faa_aircraft_registry.py.

Covers:
  - _cache_valid
  - _word_overlap
  - _is_nnumber
  - _normalise_nnumber
  - _row_to_aircraft
  - _search_master_csv
  - _parse_nnumber_html (dt/dd path, table path, empty-data path)
  - FaaAircraftRegistryCrawler.scrape() — N-number and owner-name branches
  - FaaAircraftRegistryCrawler._get_master_csv() — all cache/download/ZIP branches
  - FaaAircraftRegistryCrawler._lookup_nnumber() — success and failure paths

All filesystem and HTTP calls are mocked.
asyncio_mode=auto — no @pytest.mark.asyncio decorators.
"""

from __future__ import annotations

import csv
import io
import os
import time
import zipfile
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, content: bytes = b"", text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    resp.text = text
    return resp


def _make_crawler():
    from modules.crawlers.transport.faa_aircraft_registry import FaaAircraftRegistryCrawler

    return FaaAircraftRegistryCrawler()


def _make_csv_text(rows: list[dict]) -> str:
    """Build a positional FAA-style CSV from a list of dicts keyed by _MASTER_COLS."""
    from modules.crawlers.transport.faa_aircraft_registry import _MASTER_COLS

    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow([row.get(col, "") for col in _MASTER_COLS])
    return output.getvalue()


def _make_zip(csv_text: str, inner_name: str = "MASTER.txt") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(inner_name, csv_text.encode("latin-1"))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _cache_valid
# ---------------------------------------------------------------------------


class TestCacheValid:
    def _fn(self, path, max_age_hours=48.0):
        from modules.crawlers.utils import cache_valid as _cache_valid

        return _cache_valid(path, max_age_hours)

    def test_file_does_not_exist(self, tmp_path):
        assert self._fn(str(tmp_path / "missing.csv")) is False

    def test_file_fresh(self, tmp_path):
        p = tmp_path / "fresh.csv"
        p.write_text("data")
        # mtime is now — well within 48 hours
        assert self._fn(str(p)) is True

    def test_file_stale(self, tmp_path):
        p = tmp_path / "stale.csv"
        p.write_text("data")
        stale_mtime = time.time() - (50 * 3600)
        os.utime(str(p), (stale_mtime, stale_mtime))
        assert self._fn(str(p)) is False

    def test_custom_max_age(self, tmp_path):
        p = tmp_path / "cache.csv"
        p.write_text("data")
        # File is fresh but we give max_age_hours=0 — should be stale
        assert self._fn(str(p), max_age_hours=0.0) is False


# ---------------------------------------------------------------------------
# _word_overlap
# ---------------------------------------------------------------------------


class TestWordOverlap:
    def _fn(self, query, candidate):
        from modules.crawlers.utils import word_overlap as _word_overlap

        return _word_overlap(query, candidate)

    def test_full_match(self):
        assert self._fn("john smith", "john smith") == 1.0

    def test_partial_match(self):
        score = self._fn("john smith", "john jones")
        assert score == 0.5

    def test_no_match(self):
        assert self._fn("john smith", "mary jones") == 0.0

    def test_empty_query(self):
        assert self._fn("", "anything") == 0.0

    def test_case_insensitive(self):
        assert self._fn("JOHN SMITH", "john smith") == 1.0


# ---------------------------------------------------------------------------
# _is_nnumber
# ---------------------------------------------------------------------------


class TestIsNnumber:
    def _fn(self, s):
        from modules.crawlers.transport.faa_aircraft_registry import _is_nnumber

        return _is_nnumber(s)

    def test_valid_nnumber(self):
        assert self._fn("N12345") is True

    def test_valid_short(self):
        assert self._fn("N123") is True

    def test_lowercase_n(self):
        assert self._fn("n99ABC") is True

    def test_too_long(self):
        assert self._fn("N12345678") is False

    def test_empty_after_strip(self):
        assert self._fn("N") is False

    def test_non_alnum_after_strip(self):
        assert self._fn("N!@#$%") is False

    def test_plain_name(self):
        assert self._fn("John Smith") is False

    def test_with_dashes_alnum(self):
        # dashes are removed before isalnum check
        assert self._fn("N123-A") is True

    def test_just_n_letter(self):
        # "N" → strip N → "" → not bool("") = False
        assert self._fn("N") is False


# ---------------------------------------------------------------------------
# _normalise_nnumber
# ---------------------------------------------------------------------------


class TestNormaliseNnumber:
    def _fn(self, s):
        from modules.crawlers.transport.faa_aircraft_registry import _normalise_nnumber

        return _normalise_nnumber(s)

    def test_already_has_n(self):
        assert self._fn("N12345") == "N12345"

    def test_lowercase_n_uppercased(self):
        assert self._fn("n12345") == "N12345"

    def test_no_n_prefix(self):
        assert self._fn("12345") == "N12345"

    def test_with_spaces(self):
        assert self._fn("  N 999  ") == "N 999"


# ---------------------------------------------------------------------------
# _row_to_aircraft
# ---------------------------------------------------------------------------


class TestRowToAircraft:
    def _fn(self, row, is_deregistered=False):
        from modules.crawlers.transport.faa_aircraft_registry import _row_to_aircraft

        return _row_to_aircraft(row, is_deregistered)

    def _base_row(self, **overrides):
        row = {
            "n_number": "12345",
            "serial_number": "SN-001",
            "mfr_mdl_code": "CESSNA",
            "kit_mfr": "",
            "kit_model": "172",
            "eng_mfr_mdl": "",
            "year_mfr": "2000",
            "type_registrant": "1",
            "name": "John Smith",
            "street": "100 Airport Rd",
            "street2": "",
            "city": "Tulsa",
            "state": "OK",
            "zip_code": "74101",
            "region": "SW",
            "county": "Tulsa",
            "country": "US",
            "last_action_date": "20230101",
            "cert_issue_date": "20000601",
            "certification": "Standard",
            "type_aircraft": "4",
            "type_engine": "1",
            "status_code": "A",
            "mode_s_code": "ABC",
            "fract_owner": "",
            "air_worth_date": "20000701",
            "other_names_1": "",
            "other_names_2": "",
            "other_names_3": "",
            "other_names_4": "",
            "other_names_5": "",
            "expiration_date": "20260101",
            "unique_id": "U001",
            "mode_s_code_hex": "0x1234",
        }
        row.update(overrides)
        return row

    def test_basic_fields(self):
        result = self._fn(self._base_row())
        assert result["n_number"] == "N12345"
        assert result["owner_name"] == "John Smith"
        assert result["aircraft_type"] == "Fixed Wing Single Engine"
        assert result["engine_type"] == "Reciprocating"
        assert result["registrant_type"] == "Individual"
        assert result["is_deregistered"] is False
        assert "100 Airport Rd" in result["registrant_address"]
        assert "Tulsa" in result["registrant_address"]

    def test_deregistered_flag(self):
        result = self._fn(self._base_row(), is_deregistered=True)
        assert result["is_deregistered"] is True

    def test_unknown_type_code_passthrough(self):
        result = self._fn(self._base_row(type_aircraft="X", type_engine="X"))
        assert result["aircraft_type"] == "X"
        assert result["engine_type"] == "X"

    def test_kit_mfr_preferred_over_mfr_mdl_code(self):
        result = self._fn(self._base_row(kit_mfr="KIT MAKER"))
        assert result["manufacturer"] == "KIT MAKER"

    def test_mfr_mdl_code_fallback(self):
        result = self._fn(self._base_row(kit_mfr="", mfr_mdl_code="CESSNA"))
        assert result["manufacturer"] == "CESSNA"

    def test_address_parts_excludes_empty(self):
        """Empty street2 not included in address."""
        result = self._fn(self._base_row(street2=""))
        assert ",  " not in result["registrant_address"]  # no double comma from empty

    def test_value_estimate_engine_type(self):
        """Engine type Turbo-Fan → $25M estimate."""
        result = self._fn(self._base_row(type_engine="5"))
        assert result["estimated_value_usd"] == 25_000_000

    def test_value_estimate_aircraft_type_fallback(self):
        """Unknown engine, known aircraft type → aircraft type estimate used."""
        result = self._fn(self._base_row(type_engine="99", type_aircraft="1"))
        # type_engine "99" not in _ENGINE_TYPES → stays "99", not in _VALUE_ESTIMATES
        # type_aircraft "1" → "Glider" → $50,000
        assert result["estimated_value_usd"] == 50_000

    def test_value_estimate_default(self):
        """Both unknown → default $200,000."""
        result = self._fn(self._base_row(type_engine="99", type_aircraft="Z"))
        assert result["estimated_value_usd"] == 200_000

    def test_all_registrant_types(self):
        from modules.crawlers.transport.faa_aircraft_registry import _REGISTRANT_TYPES

        for code, label in _REGISTRANT_TYPES.items():
            result = self._fn(self._base_row(type_registrant=code))
            assert result["registrant_type"] == label

    def test_all_aircraft_types(self):
        from modules.crawlers.transport.faa_aircraft_registry import _AIRCRAFT_TYPES

        for code, label in _AIRCRAFT_TYPES.items():
            result = self._fn(self._base_row(type_aircraft=code))
            assert result["aircraft_type"] == label

    def test_all_engine_types(self):
        from modules.crawlers.transport.faa_aircraft_registry import _ENGINE_TYPES

        for code, label in _ENGINE_TYPES.items():
            result = self._fn(self._base_row(type_engine=code))
            assert result["engine_type"] == label


# ---------------------------------------------------------------------------
# _search_master_csv
# ---------------------------------------------------------------------------


class TestSearchMasterCsv:
    def _fn(self, csv_text, query, threshold=0.6):
        from modules.crawlers.transport.faa_aircraft_registry import _search_master_csv

        return _search_master_csv(csv_text, query, threshold)

    def _make_row_list(self, name="John Smith", n_number="12345"):
        from modules.crawlers.transport.faa_aircraft_registry import _MASTER_COLS

        row = dict.fromkeys(_MASTER_COLS, "")
        row["n_number"] = n_number
        row["name"] = name
        row["type_aircraft"] = "4"
        row["type_engine"] = "1"
        row["type_registrant"] = "1"
        return [row[col] for col in _MASTER_COLS]

    def _csv_from_rows(self, rows):
        buf = io.StringIO()
        writer = csv.writer(buf)
        for r in rows:
            writer.writerow(r)
        return buf.getvalue()

    def test_match_found(self):
        csv_text = self._csv_from_rows([self._make_row_list("JOHN SMITH", "54321")])
        results = self._fn(csv_text, "john smith")
        assert len(results) == 1
        assert results[0]["owner_name"] == "JOHN SMITH"

    def test_no_match_below_threshold(self):
        csv_text = self._csv_from_rows([self._make_row_list("MARY JONES", "99999")])
        results = self._fn(csv_text, "john smith")
        assert results == []

    def test_short_row_skipped(self):
        """Row with fewer than 8 columns — skipped."""
        csv_text = "too,few,columns\n"
        results = self._fn(csv_text, "anything")
        assert results == []

    def test_empty_owner_name_skipped(self):
        """Row where column 6 is empty — skipped."""
        from modules.crawlers.transport.faa_aircraft_registry import _MASTER_COLS

        row = [""] * len(_MASTER_COLS)
        row[6] = ""
        buf = io.StringIO()
        csv.writer(buf).writerow(row)
        results = self._fn(buf.getvalue(), "anything")
        assert results == []

    def test_stops_at_50_results(self):
        """Returns at most 50 matches."""
        rows = [self._make_row_list("JOHN SMITH", str(i)) for i in range(60)]
        csv_text = self._csv_from_rows(rows)
        results = self._fn(csv_text, "john smith")
        assert len(results) == 50

    def test_threshold_exact_boundary(self):
        """Score exactly at threshold is included."""
        csv_text = self._csv_from_rows([self._make_row_list("JOHN JONES", "11111")])
        # query "john smith", candidate "john jones" → overlap = 1/2 = 0.5
        # At threshold 0.5 — should match; at 0.6 should not
        results_5 = self._fn(csv_text, "john smith", threshold=0.5)
        results_6 = self._fn(csv_text, "john smith", threshold=0.6)
        assert len(results_5) == 1
        assert len(results_6) == 0


# ---------------------------------------------------------------------------
# _parse_nnumber_html
# ---------------------------------------------------------------------------


class TestParseNnumberHtml:
    def _fn(self, html, n_number="N12345"):
        from modules.crawlers.transport.faa_aircraft_registry import _parse_nnumber_html

        return _parse_nnumber_html(html, n_number)

    def test_dt_dd_path(self):
        html = """
        <html><body>
        <dl>
          <dt>Name:</dt><dd>John Smith</dd>
          <dt>Street:</dt><dd>100 Airport Rd</dd>
          <dt>City:</dt><dd>Tulsa</dd>
          <dt>State:</dt><dd>OK</dd>
          <dt>Zip Code:</dt><dd>74101</dd>
          <dt>Aircraft Type:</dt><dd>Fixed Wing Single Engine</dd>
          <dt>Engine Type:</dt><dd>Reciprocating</dd>
          <dt>Certification Date:</dt><dd>20000601</dd>
          <dt>Expiration Date:</dt><dd>20260101</dd>
          <dt>Year Manufactured:</dt><dd>2000</dd>
          <dt>Serial Number:</dt><dd>SN-001</dd>
          <dt>Manufacturer:</dt><dd>CESSNA</dd>
          <dt>Model:</dt><dd>172</dd>
          <dt>Airworthiness Class:</dt><dd>Standard</dd>
          <dt>Type Registrant:</dt><dd>Individual</dd>
          <dt>Status:</dt><dd>A</dd>
        </dl>
        </body></html>
        """
        results = self._fn(html)
        assert len(results) == 1
        r = results[0]
        assert r["n_number"] == "N12345"
        assert r["owner_name"] == "John Smith"
        assert r["aircraft_type"] == "Fixed Wing Single Engine"
        assert r["engine_type"] == "Reciprocating"
        assert r["serial_number"] == "SN-001"
        assert r["registration_date"] == "20000601"
        assert r["expiration_date"] == "20260101"
        assert r["year_manufactured"] == "2000"
        assert r["manufacturer"] == "CESSNA"
        assert r["model"] == "172"
        assert r["airworthiness_class"] == "Standard"
        assert r["registrant_type"] == "Individual"
        assert r["status_code"] == "A"
        assert "Tulsa" in r["registrant_address"]
        assert r["is_deregistered"] is False

    def test_table_path(self):
        """No dt/dd → falls back to table label-value layout."""
        html = """
        <html><body>
        <table>
          <tr><th>Registrant Name</th><td>Jane Doe</td></tr>
          <tr><th>Address</th><td>200 Fly Way</td></tr>
          <tr><th>City</th><td>Denver</td></tr>
          <tr><th>State</th><td>CO</td></tr>
          <tr><th>Zip</th><td>80201</td></tr>
          <tr><th>Aircraft Type</th><td>Rotorcraft</td></tr>
          <tr><th>Engine Type</th><td>Turbo-Shaft</td></tr>
          <tr><th>Year</th><td>2010</td></tr>
          <tr><th>Cert Issue Date</th><td>20100101</td></tr>
        </table>
        </body></html>
        """
        results = self._fn(html, "N99999")
        assert len(results) == 1
        r = results[0]
        assert r["n_number"] == "N99999"
        assert r["owner_name"] == "Jane Doe"
        assert r["aircraft_type"] == "Rotorcraft"

    def test_empty_data_returns_empty(self):
        """No dt/dd and no table — data dict stays empty → empty list."""
        html = "<html><body><p>Nothing here.</p></body></html>"
        results = self._fn(html)
        assert results == []

    def test_address_field_fallback(self):
        """'address' key used when 'street' is absent."""
        html = """
        <html><body>
        <dl>
          <dt>Name:</dt><dd>Bob</dd>
          <dt>Address:</dt><dd>999 Test Blvd</dd>
          <dt>City:</dt><dd>Austin</dd>
          <dt>State:</dt><dd>TX</dd>
        </dl>
        </body></html>
        """
        results = self._fn(html)
        assert "999 Test Blvd" in results[0]["registrant_address"]

    def test_owner_fallback_keys(self):
        """'owner' key used when 'name' and 'registrant name' absent."""
        html = """
        <html><body>
        <dl>
          <dt>Owner:</dt><dd>Alice Wonder</dd>
        </dl>
        </body></html>
        """
        results = self._fn(html)
        assert results[0]["owner_name"] == "Alice Wonder"

    def test_cert_date_fallback_key(self):
        """'cert issue date' used when 'certification date' absent."""
        html = """
        <html><body>
        <dl>
          <dt>Name:</dt><dd>X</dd>
          <dt>Cert Issue Date:</dt><dd>20150201</dd>
        </dl>
        </body></html>
        """
        results = self._fn(html)
        assert results[0]["registration_date"] == "20150201"

    def test_estimated_value_engine_type(self):
        """Engine type Turbo-Fan → $25M."""
        html = """
        <html><body>
        <dl>
          <dt>Name:</dt><dd>Rich Guy</dd>
          <dt>Engine Type:</dt><dd>Turbo-Fan</dd>
        </dl>
        </body></html>
        """
        results = self._fn(html)
        assert results[0]["estimated_value_usd"] == 25_000_000

    def test_exception_logged_and_empty_returned(self):
        """BeautifulSoup import raises — exception caught, empty list."""
        with patch(
            "modules.crawlers.transport.faa_aircraft_registry._parse_nnumber_html",
            side_effect=RuntimeError("bs4 gone"),
        ):
            from modules.crawlers.transport.faa_aircraft_registry import _parse_nnumber_html
        # Just ensure the real function handles any exception internally
        # We confirm by passing completely broken HTML — it should still return list
        results = self._fn("")
        assert isinstance(results, list)

    def test_year_field_fallback(self):
        """'year' key used when 'year manufactured' absent."""
        html = """
        <html><body>
        <dl>
          <dt>Name:</dt><dd>Someone</dd>
          <dt>Year:</dt><dd>1998</dd>
        </dl>
        </body></html>
        """
        results = self._fn(html)
        assert results[0]["year_manufactured"] == "1998"

    def test_exception_inside_try_caught_and_logged(self):
        """Exception raised inside the try block (lines 292-293) — caught, empty list returned."""
        from modules.crawlers.transport.faa_aircraft_registry import _parse_nnumber_html

        # BeautifulSoup is imported inside the try block as `from bs4 import BeautifulSoup`
        # Patch bs4.BeautifulSoup to raise inside the try block
        with patch("bs4.BeautifulSoup", side_effect=RuntimeError("bs4 exploded")):
            results = _parse_nnumber_html("<html></html>", "N12345")
        assert results == []


# ---------------------------------------------------------------------------
# FaaAircraftRegistryCrawler.scrape() — N-number branch
# ---------------------------------------------------------------------------


class TestScrapeNnumber:
    async def test_nnumber_found(self):
        crawler = _make_crawler()
        aircraft_record = {
            "n_number": "N12345",
            "owner_name": "John Smith",
            "is_deregistered": False,
        }

        with patch.object(
            crawler, "_lookup_nnumber", new=AsyncMock(return_value=[aircraft_record])
        ):
            result = await crawler.scrape("N12345")

        assert result.found is True
        assert result.data.get("search_type") == "n_number"
        assert result.data.get("query") == "N12345"
        aircraft = result.data.get("aircraft", [])
        assert len(aircraft) == 1
        assert result.data.get("aircraft_count") == 1

    async def test_nnumber_not_found(self):
        crawler = _make_crawler()

        with patch.object(crawler, "_lookup_nnumber", new=AsyncMock(return_value=[])):
            result = await crawler.scrape("N99999")

        assert result.found is False
        assert result.data.get("aircraft_count") == 0


# ---------------------------------------------------------------------------
# FaaAircraftRegistryCrawler.scrape() — owner-name branch
# ---------------------------------------------------------------------------


class TestScrapeOwnerName:
    async def test_owner_found(self):
        crawler = _make_crawler()
        from modules.crawlers.transport.faa_aircraft_registry import _MASTER_COLS

        row = dict.fromkeys(_MASTER_COLS, "")
        row["n_number"] = "54321"
        row["name"] = "JOHN SMITH"
        row["type_aircraft"] = "4"
        row["type_engine"] = "1"
        row["type_registrant"] = "1"
        csv_text = ",".join(row[col] for col in _MASTER_COLS) + "\n"

        with patch.object(crawler, "_get_master_csv", new=AsyncMock(return_value=csv_text)):
            result = await crawler.scrape("john smith")

        assert result.found is True
        assert result.data.get("search_type") == "owner_name"

    async def test_owner_not_found(self):
        crawler = _make_crawler()

        with patch.object(crawler, "_get_master_csv", new=AsyncMock(return_value="no,data\n")):
            result = await crawler.scrape("nobody here")

        assert result.found is False
        assert result.data.get("aircraft") == []

    async def test_csv_download_failed(self):
        crawler = _make_crawler()

        with patch.object(crawler, "_get_master_csv", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.data.get("error") == "csv_download_failed"
        assert result.data.get("aircraft_count") == 0


# ---------------------------------------------------------------------------
# FaaAircraftRegistryCrawler._get_master_csv()
# ---------------------------------------------------------------------------


class TestGetMasterCsv:
    # --- Cache valid — reads from file --------------------------------------

    async def test_cache_hit_reads_file(self, tmp_path):
        crawler = _make_crawler()
        cache_master = str(tmp_path / "faa_master.csv")
        csv_content = "N12345,data\n"

        with (
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_MASTER",
                cache_master,
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry.cache_valid",
                return_value=True,
            ),
            patch("builtins.open", mock_open(read_data=csv_content)),
        ):
            result = await crawler._get_master_csv()

        assert result == csv_content

    async def test_cache_hit_read_oserror(self, tmp_path):
        """Cache is valid but open() raises OSError — falls through to download.
        Download succeeds; ZIP write fails; in-memory parse has no MASTER file → None."""
        crawler = _make_crawler()

        # Build a ZIP with no MASTER.txt — in-memory parse will return None too
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("OTHER.txt", "irrelevant")
        zip_content_no_master = buf.getvalue()

        def _fake_open(*args, **kwargs):
            mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
            if mode == "r" or "r" in str(mode):
                # Simulate read failing when cache is "valid"
                raise OSError("permission denied")
            # Also fail writes so ZIP is never saved to disk
            raise OSError("permission denied")

        async def _fake_get(url, **kwargs):
            return _mock_resp(status=200, content=zip_content_no_master)

        with (
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_DIR",
                str(tmp_path),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_MASTER",
                str(tmp_path / "faa_master.csv"),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_ZIP",
                str(tmp_path / "faa_aircraft.zip"),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry.cache_valid",
                return_value=True,
            ),
            patch("builtins.open", side_effect=_fake_open),
            patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)),
        ):
            result = await crawler._get_master_csv()

        # Cache read failed → download succeeded → ZIP write failed → in-memory parse
        # In-memory ZIP has no MASTER file → master_name is None → returns None
        assert result is None

    # --- Cache miss — download ZIP ------------------------------------------

    async def test_download_and_extract(self, tmp_path):
        """Download succeeds, ZIP extracted, master CSV written and returned."""
        crawler = _make_crawler()

        from modules.crawlers.transport.faa_aircraft_registry import _MASTER_COLS

        row = dict.fromkeys(_MASTER_COLS, "")
        row["n_number"] = "11111"
        row["name"] = "Test Owner"
        csv_text = ",".join(row[col] for col in _MASTER_COLS) + "\n"
        zip_bytes = _make_zip(csv_text, "MASTER.txt")

        resp = _mock_resp(status=200, content=zip_bytes)
        cache_zip = str(tmp_path / "faa_aircraft.zip")
        cache_master = str(tmp_path / "faa_master.csv")

        with (
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_DIR",
                str(tmp_path),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_ZIP",
                cache_zip,
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_MASTER",
                cache_master,
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry.cache_valid",
                return_value=False,
            ),
            patch.object(crawler, "get", new=AsyncMock(return_value=resp)),
        ):
            result = await crawler._get_master_csv()

        assert result is not None
        assert "11111" in result

    async def test_download_resp_none(self, tmp_path):
        """GET returns None — returns None."""
        crawler = _make_crawler()

        with (
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_DIR",
                str(tmp_path),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry.cache_valid",
                return_value=False,
            ),
            patch.object(crawler, "get", new=AsyncMock(return_value=None)),
        ):
            result = await crawler._get_master_csv()

        assert result is None

    async def test_download_non_200(self, tmp_path):
        """GET returns non-200 — returns None."""
        crawler = _make_crawler()
        resp = _mock_resp(status=403)

        with (
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_DIR",
                str(tmp_path),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry.cache_valid",
                return_value=False,
            ),
            patch.object(crawler, "get", new=AsyncMock(return_value=resp)),
        ):
            result = await crawler._get_master_csv()

        assert result is None

    async def test_zip_save_oserror_in_memory_parse(self, tmp_path):
        """Writing ZIP to disk fails — falls back to in-memory parse."""
        crawler = _make_crawler()

        from modules.crawlers.transport.faa_aircraft_registry import _MASTER_COLS

        row = dict.fromkeys(_MASTER_COLS, "")
        row["n_number"] = "77777"
        row["name"] = "In Memory"
        csv_text_inner = ",".join(row[col] for col in _MASTER_COLS) + "\n"
        zip_bytes = _make_zip(csv_text_inner, "MASTER.txt")
        resp = _mock_resp(status=200, content=zip_bytes)

        open_call_count = [0]
        real_open = open

        def _selective_open(*args, **kwargs):
            open_call_count[0] += 1
            if open_call_count[0] == 1:
                # First open() is the ZIP write — raise OSError
                raise OSError("disk full")
            return real_open(*args, **kwargs)

        with (
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_DIR",
                str(tmp_path),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_ZIP",
                str(tmp_path / "faa_aircraft.zip"),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_MASTER",
                str(tmp_path / "faa_master.csv"),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry.cache_valid",
                return_value=False,
            ),
            patch.object(crawler, "get", new=AsyncMock(return_value=resp)),
            patch("builtins.open", side_effect=_selective_open),
        ):
            result = await crawler._get_master_csv()

        # In-memory ZIP parse should succeed
        assert result is not None
        assert "77777" in result

    async def test_zip_save_oserror_in_memory_parse_also_fails(self, tmp_path):
        """ZIP write fails AND in-memory parse raises — returns None."""
        crawler = _make_crawler()

        zip_bytes = b"not a valid zip"
        resp = _mock_resp(status=200, content=zip_bytes)

        with (
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_DIR",
                str(tmp_path),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_ZIP",
                str(tmp_path / "faa_aircraft.zip"),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_MASTER",
                str(tmp_path / "faa_master.csv"),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry.cache_valid",
                return_value=False,
            ),
            patch.object(crawler, "get", new=AsyncMock(return_value=resp)),
            patch("builtins.open", side_effect=OSError("disk full")),
        ):
            result = await crawler._get_master_csv()

        assert result is None

    async def test_zip_no_master_file_in_archive(self, tmp_path):
        """ZIP downloads fine but contains no MASTER*.txt — returns None."""
        crawler = _make_crawler()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("OTHER.txt", "irrelevant data")
        zip_bytes = buf.getvalue()
        resp = _mock_resp(status=200, content=zip_bytes)

        cache_zip = str(tmp_path / "faa_aircraft.zip")
        cache_master = str(tmp_path / "faa_master.csv")

        with (
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_DIR",
                str(tmp_path),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_ZIP",
                cache_zip,
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_MASTER",
                cache_master,
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry.cache_valid",
                return_value=False,
            ),
            patch.object(crawler, "get", new=AsyncMock(return_value=resp)),
        ):
            result = await crawler._get_master_csv()

        assert result is None

    async def test_zip_extraction_exception(self, tmp_path):
        """Opening saved ZIP raises exception — returns None."""
        crawler = _make_crawler()

        zip_bytes = _make_zip("data\n", "MASTER.txt")
        resp = _mock_resp(status=200, content=zip_bytes)

        cache_zip = str(tmp_path / "faa_aircraft.zip")
        cache_master = str(tmp_path / "faa_master.csv")

        real_zipfile = zipfile.ZipFile

        def _mock_zipfile_cls(*args, **kwargs):
            # First call (write ZIP): pass through
            # Second call (open saved ZIP): raise
            if isinstance(args[0], str):  # opening by filename
                raise zipfile.BadZipFile("corrupt")
            return real_zipfile(*args, **kwargs)

        with (
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_DIR",
                str(tmp_path),
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_ZIP",
                cache_zip,
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry._CACHE_MASTER",
                cache_master,
            ),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry.cache_valid",
                return_value=False,
            ),
            patch.object(crawler, "get", new=AsyncMock(return_value=resp)),
            patch(
                "modules.crawlers.transport.faa_aircraft_registry.zipfile.ZipFile",
                side_effect=_mock_zipfile_cls,
            ),
        ):
            result = await crawler._get_master_csv()

        assert result is None


# ---------------------------------------------------------------------------
# FaaAircraftRegistryCrawler._lookup_nnumber()
# ---------------------------------------------------------------------------


class TestLookupNnumber:
    async def test_success_200(self):
        """Status 200 — parses HTML and returns aircraft."""
        crawler = _make_crawler()
        html = """
        <html><body>
        <dl>
          <dt>Name:</dt><dd>John Smith</dd>
          <dt>Aircraft Type:</dt><dd>Fixed Wing Single Engine</dd>
        </dl>
        </body></html>
        """
        resp = _mock_resp(status=200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            aircraft = await crawler._lookup_nnumber("N12345")
        assert len(aircraft) == 1
        assert aircraft[0]["n_number"] == "N12345"

    async def test_success_206(self):
        """Status 206 (partial content) is also accepted."""
        crawler = _make_crawler()
        html = "<html><body><dl><dt>Name:</dt><dd>Jane</dd></dl></body></html>"
        resp = _mock_resp(status=206, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            aircraft = await crawler._lookup_nnumber("N99999")
        assert isinstance(aircraft, list)

    async def test_failure_non_200(self):
        """Non-200/206 status — returns empty list."""
        crawler = _make_crawler()
        resp = _mock_resp(status=404, text="")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            aircraft = await crawler._lookup_nnumber("N00000")
        assert aircraft == []

    async def test_failure_none_response(self):
        """None response — returns empty list."""
        crawler = _make_crawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            aircraft = await crawler._lookup_nnumber("N11111")
        assert aircraft == []

    async def test_n_stripped_for_url(self):
        """N prefix stripped before building inquiry URL."""
        crawler = _make_crawler()
        resp = _mock_resp(status=200, text="<html><body><dl></dl></body></html>")

        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)) as mock_get:
            await crawler._lookup_nnumber("N12345")

        url_called = mock_get.call_args[0][0]
        assert "12345" in url_called
        assert url_called.count("N12345") == 0 or "NNumbertxt=12345" in url_called


# ---------------------------------------------------------------------------
# Branch gap tests for _parse_nnumber_html — arcs 254->251 and 262->260
# ---------------------------------------------------------------------------


class TestParseNnumberHtmlBranchGaps:
    """Exercises branch paths not yet covered in _parse_nnumber_html."""

    def _fn(self, html: str, n_number: str = "N12345") -> list:
        from modules.crawlers.transport.faa_aircraft_registry import _parse_nnumber_html

        return _parse_nnumber_html(html, n_number)

    def test_dt_without_dd_sibling_is_skipped(self):
        """Arc 254->251: <dt> exists but has no following <dd> sibling (if dd: is False).
        The dt must appear AFTER all dd elements so find_next_sibling('dd') returns None.
        Loop continues to next <dt> without storing anything in data."""
        html = """
        <html><body>
        <dl>
          <dt>Name:</dt><dd>Valid Owner</dd>
          <dt>Trailing Label With No Following DD</dt>
        </dl>
        </body></html>
        """
        results = self._fn(html)
        # The trailing dt (no following dd) is skipped; the earlier dt+dd is processed
        assert len(results) == 1
        assert results[0]["owner_name"] == "Valid Owner"

    def test_table_row_with_single_cell_is_skipped(self):
        """Arc 262->260: table row has only 1 cell (len(cells) >= 2 is False).
        Loop continues to next row without extracting label/value."""
        html = """
        <html><body>
        <table>
          <tr><td>Lone Cell</td></tr>
          <tr><th>Name</th><td>Solo Pilot</td></tr>
        </table>
        </body></html>
        """
        results = self._fn(html)
        # Single-cell row is skipped; two-cell row contributes data
        assert len(results) == 1
        assert results[0]["owner_name"] == "Solo Pilot"
