"""
test_stub_crawlers.py — Tests for stub crawlers that always return found=False.

Covers:
- AdverseMediaSearchCrawler.scrape(): returns CrawlerResult(found=False)
- FaaAircraftRegistryCrawler.scrape(): returns CrawlerResult(found=False)
"""

from __future__ import annotations

import pytest

from modules.crawlers.adverse_media_search import AdverseMediaSearchCrawler
from modules.crawlers.faa_aircraft_registry import FaaAircraftRegistryCrawler
from modules.crawlers.result import CrawlerResult


# ---------------------------------------------------------------------------
# AdverseMediaSearchCrawler
# ---------------------------------------------------------------------------


async def test_adverse_media_scrape_returns_crawler_result():
    crawler = AdverseMediaSearchCrawler()
    result = await crawler.scrape("John Smith")
    assert isinstance(result, CrawlerResult)


async def test_adverse_media_scrape_found_is_false():
    crawler = AdverseMediaSearchCrawler()
    result = await crawler.scrape("John Smith")
    assert result.found is False


async def test_adverse_media_scrape_platform():
    crawler = AdverseMediaSearchCrawler()
    result = await crawler.scrape("Jane Doe")
    assert result.platform == "adverse_media_search"


async def test_adverse_media_scrape_identifier_propagated():
    crawler = AdverseMediaSearchCrawler()
    result = await crawler.scrape("target-entity")
    assert result.identifier == "target-entity"


async def test_adverse_media_scrape_data_is_dict():
    crawler = AdverseMediaSearchCrawler()
    result = await crawler.scrape("anyone")
    assert isinstance(result.data, dict)


async def test_adverse_media_scrape_empty_identifier():
    crawler = AdverseMediaSearchCrawler()
    result = await crawler.scrape("")
    assert result.found is False
    assert result.identifier == ""


async def test_adverse_media_source_reliability():
    crawler = AdverseMediaSearchCrawler()
    assert crawler.source_reliability == 0.7


async def test_adverse_media_requires_tor_false():
    crawler = AdverseMediaSearchCrawler()
    assert crawler.requires_tor is False


async def test_adverse_media_proxy_tier():
    crawler = AdverseMediaSearchCrawler()
    assert crawler.proxy_tier == "direct"


# ---------------------------------------------------------------------------
# FaaAircraftRegistryCrawler
# ---------------------------------------------------------------------------


async def test_faa_scrape_returns_crawler_result():
    crawler = FaaAircraftRegistryCrawler()
    result = await crawler.scrape("Wolf Aviation LLC")
    assert isinstance(result, CrawlerResult)


async def test_faa_scrape_found_is_false():
    crawler = FaaAircraftRegistryCrawler()
    result = await crawler.scrape("Wolf Aviation LLC")
    assert result.found is False


async def test_faa_scrape_platform():
    crawler = FaaAircraftRegistryCrawler()
    result = await crawler.scrape("N12345")
    assert result.platform == "faa_aircraft_registry"


async def test_faa_scrape_identifier_propagated():
    crawler = FaaAircraftRegistryCrawler()
    result = await crawler.scrape("N99999")
    assert result.identifier == "N99999"


async def test_faa_scrape_data_is_dict():
    crawler = FaaAircraftRegistryCrawler()
    result = await crawler.scrape("anyone")
    assert isinstance(result.data, dict)


async def test_faa_scrape_empty_identifier():
    crawler = FaaAircraftRegistryCrawler()
    result = await crawler.scrape("")
    assert result.found is False
    assert result.identifier == ""


async def test_faa_source_reliability():
    crawler = FaaAircraftRegistryCrawler()
    assert crawler.source_reliability == 0.95


async def test_faa_requires_tor_false():
    crawler = FaaAircraftRegistryCrawler()
    assert crawler.requires_tor is False


async def test_faa_proxy_tier():
    crawler = FaaAircraftRegistryCrawler()
    assert crawler.proxy_tier == "direct"
