"""Tests for genealogy crawlers — 100% coverage with all I/O mocked."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_response(status: int, body=None):
    """Build a mock httpx.Response. body=None causes json() to raise ValueError."""
    resp = MagicMock()
    resp.status_code = status
    if body is None:
        resp.json.side_effect = ValueError("no body")
    else:
        resp.json.return_value = body
    return resp


# ---------------------------------------------------------------------------
# AncestryHintsCrawler
# ---------------------------------------------------------------------------
class TestAncestryHintsCrawler:
    @pytest.fixture
    def crawler(self):
        from modules.crawlers.genealogy.ancestry_hints import AncestryHintsCrawler
        return AncestryHintsCrawler()

    @pytest.mark.asyncio
    async def test_happy_path_with_hints(self, crawler):
        body = {
            "hints": [
                {"id": "rec1", "title": "1920 Census", "recordType": "census", "year": "1920", "url": "http://x"}
            ]
        }
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is True
        assert len(result.data["records"]) == 1
        assert result.data["records"][0]["record_id"] == "rec1"
        assert result.data["name"] == "John Smith"
        assert result.data["birth_year"] == "1920"

    @pytest.mark.asyncio
    async def test_no_hints_found_not(self, crawler):
        body = {"hints": []}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("Jane Doe:1900")
        assert result.found is False
        assert result.data["records"] == []

    @pytest.mark.asyncio
    async def test_non_200_response(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(404, {}))):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is False
        assert result.error == "non_200"

    @pytest.mark.asyncio
    async def test_none_response(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is False
        assert result.error == "no_response"

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back_to_empty(self, crawler):
        """ancestry_hints falls back to {} on bad JSON — no early return."""
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, None))):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is False
        assert result.data["records"] == []

    @pytest.mark.asyncio
    async def test_identifier_without_year(self, crawler):
        body = {"hints": []}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("JohnSmith")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_single_name_token(self, crawler):
        body = {"hints": []}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("Madonna:1958")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_parse_results_defaults(self, crawler):
        """_parse_results fills defaults for missing fields."""
        records = crawler._parse_results({"hints": [{}]})
        assert records[0]["record_id"] == ""
        assert records[0]["title"] == ""
        assert records[0]["record_type"] == "census"
        assert records[0]["year"] == ""


# ---------------------------------------------------------------------------
# CensusRecordsCrawler
# ---------------------------------------------------------------------------
class TestCensusRecordsCrawler:
    @pytest.fixture
    def crawler(self):
        from modules.crawlers.genealogy.census_records import CensusRecordsCrawler
        return CensusRecordsCrawler()

    def _make_entry(self, full_name="John Smith", birth_date="1920", death_date=None,
                    rels=None):
        parts_list = [{"value": p} for p in full_name.split()]
        person = {
            "names": [{"nameForms": [{"parts": parts_list}]}],
            "facts": [],
        }
        person["facts"].append({"type": "Birth", "date": {"original": birth_date}})
        if death_date:
            person["facts"].append({"type": "Death", "date": {"original": death_date}})
        gedcomx = {"persons": [person], "relationships": rels or []}
        return {"id": "e1", "content": {"gedcomx": gedcomx}}

    @pytest.mark.asyncio
    async def test_happy_path(self, crawler):
        entry = self._make_entry()
        body = {"entries": [entry], "persons": []}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is True
        assert result.data["records"][0]["full_name"] == "John Smith"
        assert result.data["records"][0]["record_type"] == "census"

    @pytest.mark.asyncio
    async def test_non_200(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(500, {}))):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is False
        assert result.error == "non_200"

    @pytest.mark.asyncio
    async def test_no_response(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is False
        assert result.error == "no_response"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self, crawler):
        """census_records returns error on bad JSON (unlike ancestry_hints)."""
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, None))):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is False
        assert result.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_empty_entries(self, crawler):
        body = {"entries": [], "persons": []}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_entry_no_persons(self, crawler):
        body = {"entries": [{"id": "e1", "content": {"gedcomx": {"persons": [], "relationships": []}}}]}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_with_death_date(self, crawler):
        entry = self._make_entry(death_date="1985")
        body = {"entries": [entry], "persons": []}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.data["records"][0]["death_date"] == "1985"

    @pytest.mark.asyncio
    async def test_with_couple_relationship(self, crawler):
        rels = [
            {
                "type": "http://gedcomx.org/Couple",
                "person1": {"resourceId": "p1"},
                "person2": {"resourceId": "p2"},
            }
        ]
        entry = self._make_entry(rels=rels)
        body = {"entries": [entry], "persons": []}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.data["records"][0]["relationships"][0]["type"] == "spouse"

    @pytest.mark.asyncio
    async def test_with_parent_child_relationship(self, crawler):
        rels = [
            {
                "type": "http://gedcomx.org/ParentChild",
                "person1": {"resourceId": "p1"},
                "person2": {"resourceId": "p2"},
            }
        ]
        entry = self._make_entry(rels=rels)
        body = {"entries": [entry], "persons": []}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.data["records"][0]["relationships"][0]["type"] == "parent_child"

    def test_build_person_map(self, crawler):
        gedcomx = {
            "persons": [
                {
                    "id": "p1",
                    "names": [{"nameForms": [{"parts": [{"value": "John"}, {"value": "Smith"}]}]}],
                },
                {"id": "p2", "names": []},
            ]
        }
        person_map = crawler._build_person_map(gedcomx)
        assert person_map["p1"] == "John Smith"
        assert person_map["p2"] == "p2"  # fallback to ID

    def test_build_person_map_no_parts(self, crawler):
        gedcomx = {
            "persons": [{"id": "p3", "names": [{"nameForms": [{"parts": []}]}]}]
        }
        person_map = crawler._build_person_map(gedcomx)
        assert person_map["p3"] == "p3"  # empty full → fallback to id


# ---------------------------------------------------------------------------
# GeniPublicCrawler
# ---------------------------------------------------------------------------
class TestGeniPublicCrawler:
    @pytest.fixture
    def crawler(self):
        from modules.crawlers.genealogy.geni_public import GeniPublicCrawler
        return GeniPublicCrawler()

    @pytest.mark.asyncio
    async def test_happy_path_results_key(self, crawler):
        body = {
            "results": [
                {"name": "John Smith", "birth": {"year": 1920}, "death": {"year": 1990},
                 "url": "https://www.geni.com/people/John/123", "guid": "abc"}
            ]
        }
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith")
        assert result.found is True
        assert result.data["profiles"][0]["name"] == "John Smith"
        assert result.data["profiles"][0]["birth_year"] == 1920

    @pytest.mark.asyncio
    async def test_profiles_key(self, crawler):
        body = {"profiles": [{"name": "Jane Doe", "birth": {"year": 1930}, "url": "/people/Jane/456"}]}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("Jane Doe")
        assert result.found is True
        # Relative URL should be prefixed
        assert result.data["profiles"][0]["profile_url"].startswith("https://www.geni.com")

    @pytest.mark.asyncio
    async def test_list_response(self, crawler):
        body = [{"name": "Bob Jones", "url": "https://www.geni.com/bob"}]
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("Bob Jones")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_non_200(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(403, {}))):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error == "non_200"

    @pytest.mark.asyncio
    async def test_none_response(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error == "no_response"

    @pytest.mark.asyncio
    async def test_invalid_json(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, None))):
            result = await crawler.scrape("John Smith")
        assert result.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_empty_results(self, crawler):
        body = {"results": []}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_unknown_response_shape(self, crawler):
        """Non-dict, non-list JSON returns empty profiles."""
        body_mock = MagicMock()
        body_mock.status_code = 200
        body_mock.json.return_value = "unexpected string"
        with patch.object(crawler, "get", new=AsyncMock(return_value=body_mock)):
            result = await crawler.scrape("John Smith")
        assert result.found is False

    def test_parse_geni_profile_relative_url(self, crawler):
        profile = {"name": "Test", "url": "/people/Test/999", "birth": {}, "death": {}}
        parsed = crawler._parse_geni_profile(profile)
        assert parsed["profile_url"] == "https://www.geni.com/people/Test/999"

    def test_parse_geni_profile_absolute_url(self, crawler):
        profile = {"name": "Test", "url": "https://www.geni.com/people/Test/999"}
        parsed = crawler._parse_geni_profile(profile)
        assert parsed["profile_url"] == "https://www.geni.com/people/Test/999"

    def test_parse_geni_profile_no_birth_death(self, crawler):
        profile = {"name": "Test", "url": ""}
        parsed = crawler._parse_geni_profile(profile)
        assert parsed["birth_year"] == ""
        assert parsed["death_year"] == ""

    def test_parse_geni_profile_non_dict_birth(self, crawler):
        profile = {"name": "Test", "birth": "1920", "death": "1990", "url": ""}
        parsed = crawler._parse_geni_profile(profile)
        assert parsed["birth_year"] == ""
        assert parsed["death_year"] == ""


# ---------------------------------------------------------------------------
# NewspapersArchiveCrawler
# ---------------------------------------------------------------------------
class TestNewspapersArchiveCrawler:
    @pytest.fixture
    def crawler(self):
        from modules.crawlers.genealogy.newspapers_archive import NewspapersArchiveCrawler
        return NewspapersArchiveCrawler()

    @pytest.mark.asyncio
    async def test_happy_path_obituary(self, crawler):
        body = {
            "items": [
                {"title": "Smith Obituary", "date": "1985-03-12", "url": "http://x",
                 "ocr_eng": "John Smith died in March 1985 funeral services held"}
            ]
        }
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith")
        assert result.found is True
        assert result.data["records"][0]["record_type"] == "obituary"

    @pytest.mark.asyncio
    async def test_memorial_when_no_obit_keywords(self, crawler):
        body = {
            "items": [
                {"title": "Anniversary", "date": "1985-03-12", "url": "http://x",
                 "ocr_eng": "John Smith married Jane Doe in 1950"}
            ]
        }
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith")
        assert result.data["records"][0]["record_type"] == "memorial"

    @pytest.mark.asyncio
    async def test_death_keyword(self, crawler):
        body = {"items": [{"ocr_eng": "death notice for John Smith", "title": "", "date": "", "url": ""}]}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith")
        assert result.data["records"][0]["record_type"] == "obituary"

    @pytest.mark.asyncio
    async def test_obit_keyword(self, crawler):
        body = {"items": [{"ocr_eng": "obit section: john smith survived by", "title": "", "date": "", "url": ""}]}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith")
        assert result.data["records"][0]["record_type"] == "obituary"

    @pytest.mark.asyncio
    async def test_funeral_keyword(self, crawler):
        body = {"items": [{"ocr_eng": "funeral for john smith", "title": "", "date": "", "url": ""}]}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith")
        assert result.data["records"][0]["record_type"] == "obituary"

    @pytest.mark.asyncio
    async def test_non_200(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(503, {}))):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error == "non_200"

    @pytest.mark.asyncio
    async def test_none_response(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")
        assert result.found is False
        assert result.error == "no_response"

    @pytest.mark.asyncio
    async def test_invalid_json(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, None))):
            result = await crawler.scrape("John Smith")
        assert result.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_empty_items(self, crawler):
        body = {"items": []}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith")
        assert result.found is False

    def test_parse_loc_entry_no_ocr(self, crawler):
        item = {"title": "No OCR", "date": "1900-01-01", "url": "http://y"}
        parsed = crawler._parse_loc_entry(item, "test")
        assert parsed["record_type"] == "memorial"


# ---------------------------------------------------------------------------
# VitalsRecordsCrawler
# ---------------------------------------------------------------------------
class TestVitalsRecordsCrawler:
    @pytest.fixture
    def crawler(self):
        from modules.crawlers.genealogy.vitals_records import VitalsRecordsCrawler
        return VitalsRecordsCrawler()

    def _make_entry(self, facts=None):
        parts_list = [{"value": "John"}, {"value": "Smith"}]
        person = {
            "names": [{"nameForms": [{"parts": parts_list}]}],
            "facts": facts or [{"type": "Birth", "date": {"original": "1920"}}],
        }
        gedcomx = {"persons": [person]}
        return {"id": "v1", "content": {"gedcomx": gedcomx}}

    @pytest.mark.asyncio
    async def test_birth_cert(self, crawler):
        entry = self._make_entry(facts=[{"type": "Birth", "date": {"original": "1920"}}])
        body = {"entries": [entry]}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is True
        assert result.data["records"][0]["record_type"] == "birth_cert"

    @pytest.mark.asyncio
    async def test_death_fact(self, crawler):
        entry = self._make_entry(facts=[{"type": "Death", "date": {"original": "1990"}}])
        body = {"entries": [entry]}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.data["records"][0]["record_type"] == "obituary"

    @pytest.mark.asyncio
    async def test_marriage_fact(self, crawler):
        entry = self._make_entry(facts=[{"type": "Marriage", "date": {"original": "1950"}}])
        body = {"entries": [entry]}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.data["records"][0]["record_type"] == "memorial"

    @pytest.mark.asyncio
    async def test_death_then_marriage_last_wins(self, crawler):
        """Last fact wins — Death then Marriage → memorial."""
        facts = [
            {"type": "Death", "date": {"original": "1990"}},
            {"type": "Marriage", "date": {"original": "1950"}},
        ]
        entry = self._make_entry(facts=facts)
        body = {"entries": [entry]}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.data["records"][0]["record_type"] == "memorial"

    @pytest.mark.asyncio
    async def test_non_200(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(401, {}))):
            result = await crawler.scrape("John Smith:1920")
        assert result.error == "non_200"

    @pytest.mark.asyncio
    async def test_none_response(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith:1920")
        assert result.error == "no_response"

    @pytest.mark.asyncio
    async def test_invalid_json(self, crawler):
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, None))):
            result = await crawler.scrape("John Smith:1920")
        assert result.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_empty_entries(self, crawler):
        body = {"entries": []}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_entry_no_persons(self, crawler):
        body = {"entries": [{"id": "v2", "content": {"gedcomx": {"persons": []}}}]}
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, body))):
            result = await crawler.scrape("John Smith:1920")
        assert result.found is False
