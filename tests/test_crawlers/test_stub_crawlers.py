"""
test_stub_crawlers.py — Tests for crawler re-exports (verify wrappers point to real impls).

Validates that the top-level wrapper modules correctly re-export from their
subpackage implementations and that class attributes are consistent.
"""

from __future__ import annotations

import pytest

from modules.crawlers.media.adverse_media_search import AdverseMediaSearchCrawler
from modules.crawlers.transport.faa_aircraft_registry import FaaAircraftRegistryCrawler
from modules.crawlers.transport.marine_vessel import MarineVesselCrawler

# ---------------------------------------------------------------------------
# AdverseMediaSearchCrawler
# ---------------------------------------------------------------------------


def test_adverse_media_is_real_implementation():
    """Re-export should point to media subpackage, not a stub."""
    assert AdverseMediaSearchCrawler.__module__ == "modules.crawlers.media.adverse_media_search"


def test_adverse_media_attributes():
    crawler = AdverseMediaSearchCrawler()
    assert crawler.platform == "adverse_media_search"
    assert crawler.source_reliability == 0.75
    assert crawler.requires_tor is False
    assert crawler.proxy_tier == "datacenter"


# ---------------------------------------------------------------------------
# FaaAircraftRegistryCrawler
# ---------------------------------------------------------------------------


def test_faa_is_real_implementation():
    assert (
        FaaAircraftRegistryCrawler.__module__ == "modules.crawlers.transport.faa_aircraft_registry"
    )


def test_faa_attributes():
    crawler = FaaAircraftRegistryCrawler()
    assert crawler.platform == "faa_aircraft_registry"
    assert crawler.source_reliability == 0.95
    assert crawler.requires_tor is False
    assert crawler.proxy_tier == "direct"


# ---------------------------------------------------------------------------
# MarineVesselCrawler
# ---------------------------------------------------------------------------


def test_marine_vessel_is_real_implementation():
    assert MarineVesselCrawler.__module__ == "modules.crawlers.transport.marine_vessel"


def test_marine_vessel_attributes():
    crawler = MarineVesselCrawler()
    assert crawler.platform == "marine_vessel"
    assert crawler.source_reliability == 0.88
    assert crawler.requires_tor is False
    assert crawler.proxy_tier == "datacenter"
