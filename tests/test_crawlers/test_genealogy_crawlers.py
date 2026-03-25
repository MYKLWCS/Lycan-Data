"""Tests for genealogy crawlers."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock

def _make_resp(json_data):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = 200
    return resp

class TestAncestryHintsCrawler:
    @pytest.fixture
    def crawler(self):
        from modules.crawlers.genealogy.ancestry_hints import AncestryHintsCrawler
        c = AncestryHintsCrawler(); c.get = AsyncMock(); return c

    @pytest.mark.asyncio
    async def test_found(self, crawler):
        crawler.get.return_value = _make_resp({"results": [{"name": "Jane Doe", "relationship": "parent", "url": "http://a.com/1"}]})
        result = await crawler.scrape("John Doe")
        assert result.found is True
        assert result.platform == "ancestry_hints"
        assert result.data["relatives"][0]["full_name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_not_found(self, crawler):
        crawler.get.return_value = _make_resp({"results": []})
        result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_missing_name_returns_not_found(self, crawler):
        result = await crawler.scrape("")
        assert result.found is False
        crawler.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_returns_not_found(self, crawler):
        crawler.get.return_value = None
        result = await crawler.scrape("John Doe")
        assert result.found is False

class TestCensusRecordsCrawler:
    @pytest.fixture
    def crawler(self):
        from modules.crawlers.genealogy.census_records import CensusRecordsCrawler
        c = CensusRecordsCrawler(); c.get = AsyncMock(); return c

    @pytest.mark.asyncio
    async def test_found_couple_relationship(self, crawler):
        crawler.get.return_value = _make_resp({"entries": [{"content": {"gedcomx": {
            "persons": [{"id": "p1", "names": [{"fullText": "John Doe"}]},
                        {"id": "p2", "names": [{"fullText": "Jane Doe"}]}],
            "relationships": [{"type": "http://gedcomx.org/Couple",
                                "person1": {"resourceId": "p1"}, "person2": {"resourceId": "p2"}}]
        }}}]})
        result = await crawler.scrape("John Doe")
        assert result.found is True
        assert result.data["relatives"][0]["relationship"] == "spouse_of"

    @pytest.mark.asyncio
    async def test_not_found_empty_entries(self, crawler):
        crawler.get.return_value = _make_resp({"entries": []})
        result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_error_returns_not_found(self, crawler):
        crawler.get.return_value = None
        result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_missing_name_returns_not_found(self, crawler):
        result = await crawler.scrape("JohnOnly")
        assert result.found is False
        crawler.get.assert_not_called()

class TestVitalsRecordsCrawler:
    @pytest.fixture
    def crawler(self):
        from modules.crawlers.genealogy.vitals_records import VitalsRecordsCrawler
        c = VitalsRecordsCrawler(); c.get = AsyncMock(); return c

    @pytest.mark.asyncio
    async def test_found_parent_relationship(self, crawler):
        crawler.get.return_value = _make_resp({"entries": [{"content": {"gedcomx": {
            "persons": [{"id": "p1", "names": [{"fullText": "John Doe"}]},
                        {"id": "p2", "names": [{"fullText": "Baby Doe"}]}],
            "relationships": [{"type": "http://gedcomx.org/ParentChild",
                                "person1": {"resourceId": "p1"}, "person2": {"resourceId": "p2"}}]
        }}}]})
        result = await crawler.scrape("John Doe")
        assert result.found is True
        assert result.data["relatives"][0]["relationship"] == "parent_of"

    @pytest.mark.asyncio
    async def test_not_found(self, crawler):
        crawler.get.return_value = _make_resp({"entries": []})
        result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_error_returns_not_found(self, crawler):
        crawler.get.return_value = None
        result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_source_reliability(self, crawler):
        assert crawler.source_reliability == 0.90

class TestNewspapersArchiveCrawler:
    @pytest.fixture
    def crawler(self):
        from modules.crawlers.genealogy.newspapers_archive import NewspapersArchiveCrawler
        c = NewspapersArchiveCrawler(); c.get = AsyncMock(); return c

    @pytest.mark.asyncio
    async def test_found_obituary(self, crawler):
        crawler.get.return_value = _make_resp({"items": [{"title": "John Doe Obituary", "ocr_eng": "obituary notice", "url": "/pages/1"}]})
        result = await crawler.scrape("John Doe")
        assert result.found is True
        assert result.data["relatives"][0]["relationship"] == "obituary"

    @pytest.mark.asyncio
    async def test_not_found(self, crawler):
        crawler.get.return_value = _make_resp({"items": []})
        result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_error_returns_not_found(self, crawler):
        crawler.get.return_value = None
        result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_url_prefix_added(self, crawler):
        from modules.crawlers.genealogy.newspapers_archive import _parse_loc_entry
        entry = {"title": "Test", "url": "/pages/123", "ocr_eng": ""}
        result = _parse_loc_entry(entry, "John Doe")
        assert result["source_url"].startswith("https://chroniclingamerica.loc.gov")

class TestGeniPublicCrawler:
    @pytest.fixture
    def crawler(self):
        from modules.crawlers.genealogy.geni_public import GeniPublicCrawler
        c = GeniPublicCrawler(); c.get = AsyncMock(); return c

    @pytest.mark.asyncio
    async def test_found_results_shape(self, crawler):
        crawler.get.return_value = _make_resp({"results": [{"unions": [{"partners": [{"name": "Jane Doe"}]}]}]})
        result = await crawler.scrape("John Doe")
        assert result.found is True
        assert result.data["relatives"][0]["relationship"] == "spouse_of"

    @pytest.mark.asyncio
    async def test_found_profiles_shape(self, crawler):
        crawler.get.return_value = _make_resp({"profiles": {"p1": {"unions": [{"partners": [{"name": "Jane Doe"}]}]}}})
        result = await crawler.scrape("John Doe")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_not_found(self, crawler):
        crawler.get.return_value = _make_resp({"results": []})
        result = await crawler.scrape("John Doe")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_error_returns_not_found(self, crawler):
        crawler.get.return_value = None
        result = await crawler.scrape("John Doe")
        assert result.found is False

class TestCrawlerRegistration:
    def test_ancestry_hints_registered(self):
        import modules.crawlers.genealogy.ancestry_hints
        from modules.crawlers.registry import CRAWLER_REGISTRY
        assert "ancestry_hints" in CRAWLER_REGISTRY

    def test_census_records_registered(self):
        import modules.crawlers.genealogy.census_records
        from modules.crawlers.registry import CRAWLER_REGISTRY
        assert "census_records" in CRAWLER_REGISTRY

    def test_vitals_records_registered(self):
        import modules.crawlers.genealogy.vitals_records
        from modules.crawlers.registry import CRAWLER_REGISTRY
        assert "vitals_records" in CRAWLER_REGISTRY

    def test_newspapers_archive_registered(self):
        import modules.crawlers.genealogy.newspapers_archive
        from modules.crawlers.registry import CRAWLER_REGISTRY
        assert "newspapers_archive" in CRAWLER_REGISTRY

    def test_geni_public_registered(self):
        import modules.crawlers.genealogy.geni_public
        from modules.crawlers.registry import CRAWLER_REGISTRY
        assert "geni_public" in CRAWLER_REGISTRY

    def test_source_reliability_values(self):
        from modules.crawlers.genealogy.ancestry_hints import AncestryHintsCrawler
        from modules.crawlers.genealogy.census_records import CensusRecordsCrawler
        from modules.crawlers.genealogy.vitals_records import VitalsRecordsCrawler
        assert AncestryHintsCrawler.source_reliability == 0.55
        assert CensusRecordsCrawler.source_reliability == 0.85
        assert VitalsRecordsCrawler.source_reliability == 0.90
