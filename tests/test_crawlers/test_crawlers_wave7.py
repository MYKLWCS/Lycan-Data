"""
test_crawlers_wave7.py — Branch-coverage gap tests (wave 7).

Each test exercises a specific branch path that was missing.
All HTTP calls are mocked — no real network traffic.

Crawlers covered:
  company_companies_house, company_opencorporates, company_sec,
  financial_crunchbase, financial_finra, financial_worldbank,
  gov_nmls, gov_osha, github,
  sanctions_eu, sanctions_worldbank_debarment, sanctions_fatf, sanctions_uk,
  bankruptcy_pacer, cyber_alienvault,
  crypto_bscscan, crypto_polygonscan
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = "", json_raises: bool = False):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_raises:
        resp.json = MagicMock(side_effect=ValueError("bad json"))
    elif json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(return_value={})
    return resp


# ===========================================================================
# 1. company_companies_house.py
#    [101,108]: co_resp.status_code != 200 → company parse skipped
#    [110,116]: off_resp is None or status != 200 → officer parse skipped
# ===========================================================================

import modules.crawlers.company_companies_house  # noqa: F401
from modules.crawlers.company_companies_house import CompaniesHouseCrawler


class TestCompaniesHouseNon200Company:
    """Branch [101,108]: co_resp status != 200 → companies list stays empty."""

    @pytest.mark.asyncio
    async def test_w7_company_non200_skips_company_parse(self):
        """co_resp is 404 → company parse skipped; officer search still runs."""
        crawler = CompaniesHouseCrawler()
        mock_co = _mock_resp(status=404)
        mock_off = _mock_resp(200, json_data={"items": []})
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
            result = await crawler.scrape("Acme Ltd")
        assert result.data["companies"] == []
        assert result.found is False


class TestCompaniesHouseOfficerNoneOrNon200:
    """Branch [110,116]: off_resp is None or status != 200 → officers list empty."""

    @pytest.mark.asyncio
    async def test_w7_officer_resp_none_skips_officer_parse(self):
        """off_resp is None → officers list stays empty."""
        crawler = CompaniesHouseCrawler()
        mock_co = _mock_resp(200, json_data={"items": []})
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, None])):
            result = await crawler.scrape("Test Corp")
        assert result.data["officers"] == []

    @pytest.mark.asyncio
    async def test_w7_officer_resp_non200_skips_officer_parse(self):
        """off_resp is 403 → officers list stays empty."""
        crawler = CompaniesHouseCrawler()
        mock_co = _mock_resp(200, json_data={"items": []})
        mock_off = _mock_resp(status=403)
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
            result = await crawler.scrape("Test Corp")
        assert result.data["officers"] == []


# ===========================================================================
# 2. company_opencorporates.py
#    [109,116]: co_resp.status_code != 200 → company parse skipped
#    [118,124]: off_resp is None or status != 200 → officer parse skipped
# ===========================================================================

import modules.crawlers.company_opencorporates  # noqa: F401
from modules.crawlers.company_opencorporates import OpenCorporatesCrawler


class TestOpenCorporatesNon200Company:
    """Branch [109,116]: co_resp.status_code != 200 → company parse skipped."""

    @pytest.mark.asyncio
    async def test_w7_oc_company_non200_skips_company_parse(self):
        """co_resp is 429 → company list stays empty, officer search still runs."""
        crawler = OpenCorporatesCrawler()
        mock_co = _mock_resp(status=429)
        mock_off = _mock_resp(200, json_data={"results": {"officers": []}})
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
            result = await crawler.scrape("BigCorp")
        assert result.data["companies"] == []


class TestOpenCorporatesOfficerNoneOrNon200:
    """Branch [118,124]: off_resp is None or status != 200."""

    @pytest.mark.asyncio
    async def test_w7_oc_officer_resp_none_skips_parse(self):
        """off_resp is None → officers list stays empty."""
        crawler = OpenCorporatesCrawler()
        mock_co = _mock_resp(200, json_data={"results": {"companies": []}})
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, None])):
            result = await crawler.scrape("BigCorp")
        assert result.data["officers"] == []

    @pytest.mark.asyncio
    async def test_w7_oc_officer_resp_non200_skips_parse(self):
        """off_resp is 500 → officers list stays empty."""
        crawler = OpenCorporatesCrawler()
        mock_co = _mock_resp(200, json_data={"results": {"companies": []}})
        mock_off = _mock_resp(status=500)
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[mock_co, mock_off])):
            result = await crawler.scrape("BigCorp")
        assert result.data["officers"] == []


# ===========================================================================
# 3. company_sec.py
#    [80,86]: "CIK" in content_text but no digit token of length >= 7 → cik=""
#    [81,86]: for-loop iterates but all parts are short digits → cik stays ""
# ===========================================================================

from modules.crawlers.company_sec import _parse_atom_feed


class TestSECParseAtomFeedCIKBranches:
    """Branches [80,86] and [81,86]: CIK tag present but no long-digit token."""

    def test_w7_cik_in_content_no_long_digit_leaves_cik_empty(self):
        """CIK in content but only short digits → cik stays ''."""
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            "<entry>"
            "<title>10-K for TEST CORP</title>"
            "<updated>2024-01-01T00:00:00-04:00</updated>"
            '<link href="https://www.sec.gov/"/>'
            '<category label="10-K" term="form-type"/>'
            "<content>CIK 123 456 TEST</content>"
            "</entry>"
            "</feed>"
        )
        filings = _parse_atom_feed(xml)
        assert len(filings) == 1
        # No numeric token is >= 7 digits → cik stays ""
        assert filings[0]["cik"] == ""

    def test_w7_cik_long_digit_found(self):
        """CIK present and a 10-digit token → cik populated correctly."""
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            "<entry>"
            "<title>10-K for REAL CORP</title>"
            "<updated>2024-03-01T00:00:00-04:00</updated>"
            '<link href="https://www.sec.gov/"/>'
            '<category label="10-K" term="form-type"/>'
            "<content>CIK 0001234567 REAL CORP</content>"
            "</entry>"
            "</feed>"
        )
        filings = _parse_atom_feed(xml)
        assert len(filings) == 1
        assert filings[0]["cik"] == "0001234567"


# ===========================================================================
# 4. financial_crunchbase.py
#    [65,69]: funding_total is a nested dict → unwrapped to value_usd
#    [70,73]: founded_on is a nested dict → unwrapped to value
# ===========================================================================

from modules.crawlers.financial_crunchbase import _parse_api_response


class TestCrunchbaseParseNestedFields:
    """Branches [65,69] and [70,73]: nested-dict values are unwrapped."""

    def test_w7_funding_total_dict_extracted(self):
        """funding_total is a dict with value_usd → scalar extracted."""
        data = {
            "entities": [
                {
                    "identifier": {"value": "Acme Inc"},
                    "properties": {
                        "funding_total": {"value_usd": 5_000_000, "currency": "USD"},
                        "short_description": "A test company",
                        "founded_on": "2010-01-01",
                        "num_funding_rounds": 3,
                        "num_employees_enum": "c_00011_to_00050",
                    },
                }
            ]
        }
        orgs = _parse_api_response(data)
        assert len(orgs) == 1
        assert orgs[0]["funding_total"] == 5_000_000

    def test_w7_founded_on_dict_extracted(self):
        """founded_on is a dict with value → date string extracted."""
        data = {
            "entities": [
                {
                    "identifier": {"value": "Beta Corp"},
                    "properties": {
                        "funding_total": 1_000_000,
                        "founded_on": {"value": "2015-06-15", "precision": "day"},
                        "short_description": "Beta description",
                        "num_funding_rounds": 1,
                        "num_employees_enum": "c_00001_to_00010",
                    },
                }
            ]
        }
        orgs = _parse_api_response(data)
        assert len(orgs) == 1
        assert orgs[0]["founded_on"] == "2015-06-15"

    def test_w7_both_fields_dict_extracted(self):
        """Both funding_total and founded_on are nested dicts → both unwrapped."""
        data = {
            "entities": [
                {
                    "identifier": {"value": "Gamma Ltd"},
                    "properties": {
                        "funding_total": {"value_usd": 2_000_000},
                        "founded_on": {"value": "2020-03-01"},
                        "short_description": "",
                        "num_funding_rounds": 2,
                        "num_employees_enum": "",
                    },
                }
            ]
        }
        orgs = _parse_api_response(data)
        assert len(orgs) == 1
        assert orgs[0]["funding_total"] == 2_000_000
        assert orgs[0]["founded_on"] == "2020-03-01"


# ===========================================================================
# 5. financial_finra.py
#    [43,46]: isinstance(total_meta, int) True branch → total assigned directly
# ===========================================================================

from modules.crawlers.financial_finra import _parse_brokers


class TestFinraParseBrokersIntTotal:
    """Branch [43,46]: total_meta is a plain int, not a dict."""

    def test_w7_total_meta_as_int_is_used_directly(self):
        """total is plain int 42 → assigned directly via elif branch."""
        payload = {"hits": {"total": 42, "hits": []}}
        brokers, total = _parse_brokers(payload)
        assert total == 42

    def test_w7_total_meta_zero_int(self):
        """total=0 as plain int → elif branch, total=0."""
        payload = {"hits": {"total": 0, "hits": []}}
        brokers, total = _parse_brokers(payload)
        assert total == 0
        assert brokers == []


# ===========================================================================
# 6. financial_worldbank.py — [110,161]: non-ISO2 name-resolution path
#    Tests for: None response, non-200, parse error, not-found, and success.
# ===========================================================================

import modules.crawlers.financial_worldbank  # noqa: F401
from modules.crawlers.financial_worldbank import FinancialWorldBankCrawler

_WB_COUNTRY_RESP = [
    {"page": 1},
    [
        {
            "iso2Code": "NG",
            "name": "Nigeria",
            "capitalCity": "Abuja",
            "region": {"value": "Sub-Saharan Africa"},
            "incomeLevel": {"value": "Lower middle income"},
        }
    ],
]

_WB_INDICATOR_RESP = [
    {"page": 1},
    [{"date": "2023", "value": 477_000_000_000}],
]


class TestWorldBankNameResolutionPath:
    """Branch [110,161]: non-ISO2 identifier → name-resolution path."""

    @pytest.mark.asyncio
    async def test_w7_name_search_none_gives_http_error(self):
        """search_resp is None → found=False, error='http_error'."""
        crawler = FinancialWorldBankCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("Nigeria")
        assert result.found is False
        assert result.data.get("error") == "http_error"

    @pytest.mark.asyncio
    async def test_w7_name_search_non200_gives_http_error(self):
        """search_resp is 503 → found=False, error contains '503'."""
        crawler = FinancialWorldBankCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("Nigeria")
        assert result.found is False
        assert "503" in (result.data.get("error") or "")

    @pytest.mark.asyncio
    async def test_w7_name_search_parse_error_returns_country_not_found(self):
        """json() raises → country_info=None → error='country_not_found'."""
        crawler = FinancialWorldBankCrawler()
        bad_resp = _mock_resp(200, json_raises=True)
        with patch.object(crawler, "get", new=AsyncMock(return_value=bad_resp)):
            result = await crawler.scrape("Nigeria")
        assert result.found is False
        assert result.data.get("error") == "country_not_found"

    @pytest.mark.asyncio
    async def test_w7_name_search_empty_result_gives_country_not_found(self):
        """_resolve_country_info returns None → error='country_not_found'."""
        crawler = FinancialWorldBankCrawler()
        empty_resp = _mock_resp(200, json_data=[{"page": 1}, []])
        with patch.object(crawler, "get", new=AsyncMock(return_value=empty_resp)):
            result = await crawler.scrape("NonexistentCountryXXX")
        assert result.found is False
        assert result.data.get("error") == "country_not_found"

    @pytest.mark.asyncio
    async def test_w7_name_search_success_indicators_fetched(self):
        """Full name path: country found, indicators fetched and returned."""
        crawler = FinancialWorldBankCrawler()
        country_resp = _mock_resp(200, json_data=_WB_COUNTRY_RESP)
        indicator_resp = _mock_resp(200, json_data=_WB_INDICATOR_RESP)
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(
                side_effect=[country_resp, indicator_resp, indicator_resp, indicator_resp]
            ),
        ):
            result = await crawler.scrape("Nigeria")
        assert result.found is True
        assert result.data["country_info"]["iso2"] == "NG"
        assert result.data["country_info"]["name"] == "Nigeria"


# ===========================================================================
# 7. gov_nmls.py
#    [38,44]: data is a dict → extract items from a recognized key
#    [39,44]: inner loop runs with populated items
# ===========================================================================

from modules.crawlers.gov_nmls import _parse_licensees


class TestNMLSParseLicenseesDict:
    """Branches [38,44] and [39,44]: dict input with known wrapper keys."""

    def test_w7_dict_with_IndividualList_key(self):
        """data is dict with 'IndividualList' → items extracted."""
        data = {
            "IndividualList": [{"EntityName": "John Doe", "NmlsId": "12345", "PrimaryState": "TX"}]
        }
        results = _parse_licensees(data)
        assert len(results) == 1
        assert results[0]["EntityName"] == "John Doe"

    def test_w7_dict_with_Results_key(self):
        """data is dict with 'Results' → items extracted."""
        data = {"Results": [{"EntityName": "Jane Smith", "NmlsId": "67890", "PrimaryState": "CA"}]}
        results = _parse_licensees(data)
        assert len(results) == 1
        assert results[0]["EntityName"] == "Jane Smith"

    def test_w7_dict_with_data_key(self):
        """data is dict with 'data' → items extracted."""
        data = {"data": [{"FullName": "Bob Jones", "NmlsId": "11111", "PrimaryState": "FL"}]}
        results = _parse_licensees(data)
        assert len(results) == 1
        assert results[0]["EntityName"] == "Bob Jones"

    def test_w7_dict_with_items_key(self):
        """data is dict with 'items' → items extracted."""
        data = {"items": [{"EntityName": "Alice Brown", "NmlsId": "22222"}]}
        results = _parse_licensees(data)
        assert len(results) == 1
        assert results[0]["EntityName"] == "Alice Brown"

    def test_w7_dict_without_known_key_returns_empty(self):
        """data is dict with no recognized key → items stays empty."""
        data = {"unknownKey": [{"EntityName": "Nobody"}]}
        results = _parse_licensees(data)
        assert results == []


# ===========================================================================
# 8. gov_osha.py — [34,43]: data is a dict → DOL dict-wrapper branch
# ===========================================================================

from modules.crawlers.gov_osha import _parse_dol_inspections


class TestOSHAParseDolInspectionsDict:
    """Branch [34,43]: data is a dict with a wrapper key."""

    def test_w7_dict_with_data_key(self):
        """data is dict with 'data' key → rows extracted."""
        data = {
            "data": [
                {
                    "activity_nr": "123456",
                    "estab_name": "Widget Factory",
                    "open_date": "2022-01-10",
                    "close_date": "2022-02-15",
                }
            ]
        }
        inspections = _parse_dol_inspections(data)
        assert len(inspections) == 1
        assert inspections[0]["establishment_name"] == "Widget Factory"

    def test_w7_dict_with_inspections_key(self):
        """data is dict with 'inspections' key → rows extracted."""
        data = {"inspections": [{"activity_nr": "999", "estab_name": "Steel Mill"}]}
        inspections = _parse_dol_inspections(data)
        assert len(inspections) == 1
        assert inspections[0]["activity_nr"] == "999"

    def test_w7_dict_with_results_key(self):
        """data is dict with 'results' key → rows extracted."""
        data = {"results": [{"activity_nr": "777", "estab_name": "Timber Co"}]}
        inspections = _parse_dol_inspections(data)
        assert len(inspections) == 1

    def test_w7_dict_no_known_key_uses_dict_itself(self):
        """dict has no recognized key → fallback is [data] if truthy."""
        data = {"activity_nr": "555", "estab_name": "Solo Facility"}
        inspections = _parse_dol_inspections(data)
        assert len(inspections) == 1
        assert inspections[0]["establishment_name"] == "Solo Facility"


# ===========================================================================
# 9. github.py — [60,59]: field NOT in payload → loop body skips assignment
#    This is the FALSE branch of `if field in payload` — field absent from resp
# ===========================================================================

import modules.crawlers.github  # noqa: F401
from modules.crawlers.github import GITHUB_FIELDS, GitHubCrawler


class TestGitHubFieldNotInPayload:
    """Branch [60,59]: field from GITHUB_FIELDS absent from payload → not added."""

    @pytest.mark.asyncio
    async def test_w7_missing_fields_not_added_to_data(self):
        """Payload has only 'login'; all other GITHUB_FIELDS absent → not in data."""
        crawler = GitHubCrawler()
        payload = {"login": "sparseuser"}
        resp = _mock_resp(200, json_data=payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("sparseuser")
        assert result.found is True
        # Fields absent in payload must not appear in data
        for field in GITHUB_FIELDS:
            if field not in payload:
                assert field not in result.data, f"Unexpected field: {field}"

    @pytest.mark.asyncio
    async def test_w7_partial_fields_only_present_ones_in_data(self):
        """Payload has some fields; absent ones excluded from data dict."""
        crawler = GitHubCrawler()
        payload = {"login": "partialuser", "name": "Partial User", "public_repos": 10}
        resp = _mock_resp(200, json_data=payload)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("partialuser")
        assert result.found is True
        assert result.data.get("name") == "Partial User"
        assert result.data.get("public_repos") == 10
        # A field not in payload should be absent
        if "following" not in payload:
            assert "following" not in result.data


# ===========================================================================
# 10. sanctions_eu.py
#     [145,147]: whole name present → appended to candidates
#     [147,150]: first or last present → constructed name appended
#     [162,165]: entity_id non-empty → added to seen_ids (dedup)
#
# EU CSV is comma-delimited; column layout:
#   [0]=any [1]=entity_id [2]=lang [3]=first [4]=middle [5]=last
#   [6]=whole [7]=any [8]=subject_type
# ===========================================================================

from modules.crawlers.sanctions_eu import EUSanctionsCrawler


class TestSanctionsEUSearchBranches:
    """Branches in EU sanctions CSV row processing."""

    def _eu_csv(self, *rows):
        """Build a comma-delimited EU CSV with the given data rows."""
        header = "id,entity_id,lang,first,middle,last,whole,x,subject_type"
        lines = [header] + [",".join(r) for r in rows]
        return "\n".join(lines) + "\n"

    def test_w7_whole_name_branch_adds_to_candidates(self):
        """[145,147]: whole name present → added to candidates and matched."""
        csv_text = self._eu_csv(["1", "E001", "en", "", "", "", "Vladimir Putin", "x", "Person"])
        crawler = EUSanctionsCrawler()
        results = crawler._search(csv_text, "Vladimir Putin")
        assert any(r["entity_id"] == "E001" for r in results)
        assert any(r["whole_name"] == "Vladimir Putin" for r in results)

    def test_w7_first_and_last_name_branch_adds_constructed(self):
        """[147,150]: first and last present → '{first} {last}' appended to candidates."""
        csv_text = self._eu_csv(["1", "E002", "en", "Alexei", "", "Navalny", "", "x", "Person"])
        crawler = EUSanctionsCrawler()
        results = crawler._search(csv_text, "Alexei Navalny")
        assert any(r["entity_id"] == "E002" for r in results)

    def test_w7_entity_id_deduplication(self):
        """[162,165]: entity_id non-empty → added to seen_ids; duplicate row skipped."""
        # Two rows with same entity_id — second should be deduped
        csv_text = self._eu_csv(
            ["1", "E003", "en", "John", "", "Doe", "John Doe", "x", "Person"],
            ["2", "E003", "en", "John", "", "Doe", "John Doe", "x", "Person"],
        )
        crawler = EUSanctionsCrawler()
        results = crawler._search(csv_text, "John Doe")
        entity_ids = [r["entity_id"] for r in results]
        assert entity_ids.count("E003") == 1

    def test_w7_no_whole_no_names_no_match(self):
        """No whole name and no first/last → candidates empty → no match."""
        csv_text = self._eu_csv(["1", "E004", "en", "", "", "", "", "x", "Person"])
        crawler = EUSanctionsCrawler()
        results = crawler._search(csv_text, "Someone")
        assert results == []


# ===========================================================================
# 11. sanctions_worldbank_debarment.py — [46,56]: dict payload with named key
# ===========================================================================

from modules.crawlers.sanctions_worldbank_debarment import _parse_debarred


class TestWorldBankDebarmentDictPayload:
    """Branch [46,56]: payload is a dict → extract records from known key."""

    def test_w7_debarred_firms_key_extracted(self):
        """'debarredFirms' key → records extracted and matched."""
        payload = {
            "debarredFirms": [
                {
                    "firmName": "Corrupt Construction Ltd",
                    "country": "ZZ",
                    "fromDate": "2020-01-01",
                    "toDate": "2025-01-01",
                    "grounds": "Fraud",
                    "ineligibilityPeriod": "5 years",
                }
            ]
        }
        results = _parse_debarred(payload, "Corrupt Construction")
        assert len(results) == 1
        assert results[0]["firm_name"] == "Corrupt Construction Ltd"

    def test_w7_data_key_extracted(self):
        """'data' key → records extracted."""
        payload = {"data": [{"firmName": "Dodgy Builders Inc", "country": "XX"}]}
        results = _parse_debarred(payload, "Dodgy Builders")
        assert len(results) == 1

    def test_w7_debarred_firm_singular_dict_wrapped(self):
        """'debarredFirm' key (singular) with dict value → wrapped in list."""
        payload = {
            "debarredFirm": {
                "firmName": "Solo Firm Corp",
                "country": "AA",
                "grounds": "Collusion",
            }
        }
        results = _parse_debarred(payload, "Solo Firm")
        assert len(results) == 1
        assert results[0]["firm_name"] == "Solo Firm Corp"

    def test_w7_debarred_firm_singular_list_used_directly(self):
        """'debarredFirm' key (singular) with list value → used as-is."""
        payload = {
            "debarredFirm": [
                {"firmName": "List Firm A", "country": "BB"},
                {"firmName": "List Firm B", "country": "CC"},
            ]
        }
        results = _parse_debarred(payload, "List Firm")
        assert len(results) == 2


# ===========================================================================
# 12. sanctions_fatf.py — [246,258]: live parse returns ([], []) → use embedded
# ===========================================================================

import modules.crawlers.sanctions_fatf  # noqa: F401
from modules.crawlers.sanctions_fatf import FATFCrawler


class TestFATFLiveParseEmpty:
    """Branch [246,258]: resp 200 but live parse empty → fall back to embedded."""

    @pytest.mark.asyncio
    async def test_w7_live_parse_empty_uses_embedded(self):
        """_parse_fatf_page returns ([], []) → embedded lists retained, source='embedded'."""
        crawler = FATFCrawler()
        resp = _mock_resp(200, text="<html>no relevant content</html>")
        with (
            patch.object(crawler, "get", new=AsyncMock(return_value=resp)),
            patch(
                "modules.crawlers.sanctions_fatf._parse_fatf_page",
                return_value=([], []),
            ),
        ):
            result = await crawler.scrape("Iran")
        assert result.data.get("source") == "embedded"

    @pytest.mark.asyncio
    async def test_w7_live_parse_has_black_updates_source(self):
        """live parse returns non-empty black list → source='live', black_list=True."""
        crawler = FATFCrawler()
        resp = _mock_resp(200, text="<html>fatf page</html>")
        with (
            patch.object(crawler, "get", new=AsyncMock(return_value=resp)),
            patch(
                "modules.crawlers.sanctions_fatf._parse_fatf_page",
                return_value=(["Iran", "North Korea"], []),
            ),
        ):
            result = await crawler.scrape("Iran")
        assert result.data.get("source") == "live"
        assert result.data.get("black_list") is True


# ===========================================================================
# 13. sanctions_uk.py — [166,169]: group_id non-empty → added to seen_groups
#
# UK CSV (comma-delimited, first 2 rows are headers i<2 skipped):
#   col 0=GroupID, 1=any, 2=GroupName, 3=LastName, 4=FirstName, 5=Middle
#   8=DOB, 11=Nationality, 14=Regime
# Rows need >= 3 columns, scores >= 0.6 for match.
# ===========================================================================

from modules.crawlers.sanctions_uk import UKSanctionsCrawler


def _uk_csv(*data_rows):
    """Build UK sanctions CSV: 2 header rows then data rows."""
    # Each data row must be a list of >= 15 strings (indices 0-14)
    header1 = ",".join(
        [
            "GroupID",
            "Col1",
            "GroupName",
            "LastName",
            "FirstName",
            "Middle",
            "c6",
            "c7",
            "DOB",
            "c9",
            "c10",
            "Nationality",
            "c12",
            "c13",
            "Regime",
        ]
    )
    header2 = ",".join(
        ["id", "c", "n", "ln", "fn", "m", "", "", "dob", "", "", "nat", "", "", "reg"]
    )
    rows = [",".join(r) for r in data_rows]
    return "\n".join([header1, header2] + rows) + "\n"


class TestUKSanctionsGroupIdDedup:
    """Branch [166,169]: group_id present → added to seen_groups (dedup logic)."""

    def test_w7_group_id_deduplication(self):
        """Two rows with same group_id → only one result returned."""
        row1 = [
            "G001",
            "x",
            "Sanctioned Entity",
            "Doe",
            "John",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "RUSSIA",
        ]
        row2 = [
            "G001",
            "x",
            "Sanctioned Entity",
            "Doe",
            "John",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "RUSSIA",
        ]
        csv_text = _uk_csv(row1, row2)
        crawler = UKSanctionsCrawler()
        results = crawler._search(csv_text, "John Doe")
        group_ids = [r["group_id"] for r in results]
        assert group_ids.count("G001") == 1

    def test_w7_group_id_empty_no_dedup(self):
        """group_id is empty → not added to seen_groups; rows matched independently."""
        row1 = ["", "x", "", "Smith", "Alice", "", "", "", "", "", "", "", "", "", "UK"]
        row2 = ["", "x", "", "Smith", "Alice", "", "", "", "", "", "", "", "", "", "UK"]
        csv_text = _uk_csv(row1, row2)
        crawler = UKSanctionsCrawler()
        results = crawler._search(csv_text, "Alice Smith")
        # Both rows should match (no dedup because group_id is empty)
        assert len(results) >= 1

    def test_w7_non_empty_group_id_added_to_seen(self):
        """Single row with non-empty group_id → it is added to seen_groups."""
        row1 = ["G002", "x", "Entity B", "Brown", "Bob", "", "", "", "", "", "", "", "", "", "EU"]
        csv_text = _uk_csv(row1)
        crawler = UKSanctionsCrawler()
        results = crawler._search(csv_text, "Bob Brown")
        assert len(results) == 1
        assert results[0]["group_id"] == "G002"


# ===========================================================================
# 14. bankruptcy_pacer.py — [217,224]: cfpb_resp is valid 200 with complaints
# ===========================================================================

import modules.crawlers.bankruptcy_pacer  # noqa: F401
from modules.crawlers.bankruptcy_pacer import BankruptcyPacerCrawler

_PACER_RECAP_RESP = {
    "results": [
        {
            "case_name": "Smith v. BigBank",
            "court": "TXEB",
            "nature_of_suit": "Chapter 7",
            "dateFiled": "2022-03-15",
            "status": "open",
            "absolute_url": "/docket/789/",
        }
    ]
}

_PACER_CFPB_RESP = {
    "hits": {
        "hits": [
            {
                "_source": {
                    "product": "Mortgage",
                    "sub_product": "FHA mortgage",
                    "issue": "Payment processing",
                    "company": "BigBank",
                    "date_received": "2022-04-01",
                    "company_response": "Closed with explanation",
                    "complaint_id": "1234567",
                }
            }
        ]
    }
}


class TestBankruptcyPacerCFPBSuccessPath:
    """Branch [217,224]: cfpb_resp valid 200 → complaints parsed and added."""

    @pytest.mark.asyncio
    async def test_w7_cfpb_success_populates_complaints(self):
        """CFPB 200 with valid hits → complaints list populated."""
        crawler = BankruptcyPacerCrawler()
        recap_resp = _mock_resp(200, json_data=_PACER_RECAP_RESP)
        cfpb_resp = _mock_resp(200, json_data=_PACER_CFPB_RESP)
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[recap_resp, cfpb_resp])):
            result = await crawler.scrape("Smith BigBank")
        assert result.found is True
        assert len(result.data.get("complaints", [])) >= 1
        assert result.data["complaints"][0]["product"] == "Mortgage"

    @pytest.mark.asyncio
    async def test_w7_cfpb_200_empty_hits_no_complaints(self):
        """CFPB 200 but empty hits → complaints=[], result still valid."""
        crawler = BankruptcyPacerCrawler()
        recap_resp = _mock_resp(200, json_data=_PACER_RECAP_RESP)
        cfpb_resp = _mock_resp(200, json_data={"hits": {"hits": []}})
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[recap_resp, cfpb_resp])):
            result = await crawler.scrape("Smith BigBank")
        assert result.found is True
        assert result.data.get("complaints") == []


# ===========================================================================
# 15. cyber_alienvault.py — [43,48]: isinstance(pulses, list) is FALSE
#     pulse_info is a dict but pulses value is NOT a list → block skipped
# ===========================================================================

from modules.crawlers.cyber_alienvault import _trim_pulses


class TestTrimPulsesPulsesNotList:
    """Branch [43,48]: pulses key is present but is not a list → inner block skipped."""

    def test_w7_pulses_is_string_not_modified(self):
        """pulses is a string → isinstance(pulses, list) False → raw unchanged."""
        raw = {"pulse_info": {"count": 5, "pulses": "not-a-list"}}
        result = _trim_pulses(raw)
        assert result["pulse_info"]["pulses"] == "not-a-list"

    def test_w7_pulses_is_none_not_modified(self):
        """pulses is None → not a list → raw returned unchanged."""
        raw = {"pulse_info": {"count": 0, "pulses": None}}
        result = _trim_pulses(raw)
        assert result["pulse_info"]["pulses"] is None

    def test_w7_pulses_is_dict_not_modified(self):
        """pulses is a dict → not a list → not sliced."""
        raw = {"pulse_info": {"pulses": {"unexpected": "structure"}}}
        result = _trim_pulses(raw)
        assert result["pulse_info"]["pulses"] == {"unexpected": "structure"}


# ===========================================================================
# 16. crypto_bscscan.py — [123,128]: tx_data.get("status") != "1" (FALSE branch)
#     tx_resp is valid 200 with parseable JSON but status != "1"
# ===========================================================================

from modules.crawlers.crypto_bscscan import CryptoBscscanCrawler

_BSC_BALANCE_OK = {"status": "1", "message": "OK", "result": str(int(1.0 * 1e18))}


class TestBscScanTxStatusNotOne:
    """Branch [123,128]: tx_resp valid JSON but status != '1' → empty transactions."""

    @pytest.mark.asyncio
    async def test_w7_bsc_tx_status_zero_empty_transactions(self):
        """tx status='0' → recent_transactions stays []; found=True from balance."""
        crawler = CryptoBscscanCrawler()
        balance_resp = _mock_resp(200, json_data=_BSC_BALANCE_OK)
        tx_resp = _mock_resp(
            200,
            json_data={"status": "0", "message": "No transactions", "result": []},
        )
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[balance_resp, tx_resp])):
            result = await crawler.scrape("0xBSCADDR")
        assert result.found is True
        assert result.data["recent_transactions"] == []

    @pytest.mark.asyncio
    async def test_w7_bsc_tx_missing_status_empty_transactions(self):
        """tx data has no 'status' key → .get() → None != '1' → empty."""
        crawler = CryptoBscscanCrawler()
        balance_resp = _mock_resp(200, json_data=_BSC_BALANCE_OK)
        tx_resp = _mock_resp(200, json_data={"message": "OK", "result": []})
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[balance_resp, tx_resp])):
            result = await crawler.scrape("0xBSCADDR")
        assert result.found is True
        assert result.data["recent_transactions"] == []


# ===========================================================================
# 17. crypto_polygonscan.py — [123,128]: same FALSE branch as BSCScan
# ===========================================================================

from modules.crawlers.crypto_polygonscan import CryptoPolygonscanCrawler

_POLY_BALANCE_OK = {"status": "1", "message": "OK", "result": str(int(5.0 * 1e18))}


class TestPolygonScanTxStatusNotOne:
    """Branch [123,128]: tx_resp valid JSON but status != '1' → empty transactions."""

    @pytest.mark.asyncio
    async def test_w7_poly_tx_status_zero_empty_transactions(self):
        """tx status='0' → recent_transactions stays []; found=True from balance."""
        crawler = CryptoPolygonscanCrawler()
        balance_resp = _mock_resp(200, json_data=_POLY_BALANCE_OK)
        tx_resp = _mock_resp(
            200,
            json_data={"status": "0", "message": "No transactions", "result": []},
        )
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[balance_resp, tx_resp])):
            result = await crawler.scrape("0xPOLYADDR")
        assert result.found is True
        assert result.data["recent_transactions"] == []

    @pytest.mark.asyncio
    async def test_w7_poly_tx_missing_status_empty_transactions(self):
        """tx data missing 'status' key → None != '1' → empty transactions."""
        crawler = CryptoPolygonscanCrawler()
        balance_resp = _mock_resp(200, json_data=_POLY_BALANCE_OK)
        tx_resp = _mock_resp(200, json_data={"result": []})
        with patch.object(crawler, "get", new=AsyncMock(side_effect=[balance_resp, tx_resp])):
            result = await crawler.scrape("0xPOLYADDR")
        assert result.found is True
        assert result.data["recent_transactions"] == []
