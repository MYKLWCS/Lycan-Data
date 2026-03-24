"""
Tests for domain OSINT crawlers:
  - DomainHarvesterCrawler (domain_harvester) — 6 tests
  - DomainWhoisCrawler     (domain_whois)     — 6 tests

Total: 12 tests.
"""
from __future__ import annotations
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import modules.crawlers.domain_theharvester  # noqa: F401 — trigger @register
import modules.crawlers.domain_whois          # noqa: F401

from modules.crawlers.domain_theharvester import (
    DomainHarvesterCrawler,
    _parse_harvester_output,
    _run_harvester,
)
from modules.crawlers.domain_whois import DomainWhoisCrawler, _parse_whois
from modules.crawlers.registry import is_registered


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int = 200, text: str = "", json_data=None):
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    if json_data is not None:
        mock.json.return_value = json_data
    else:
        mock.json.side_effect = ValueError("no json")
    return mock


# ---------------------------------------------------------------------------
# DomainHarvesterCrawler — 6 tests
# ---------------------------------------------------------------------------

def test_domain_harvester_registered():
    assert is_registered("domain_harvester")


@pytest.mark.asyncio
async def test_harvester_found_results():
    """Harvester returns emails, subdomains, IPs, URLs when data present."""
    crawler = DomainHarvesterCrawler()

    raw = {
        "emails": ["admin@example.com", "info@example.com"],
        "hosts": ["mail.example.com", "www.example.com:93.184.216.34"],
        "ips": ["93.184.216.34"],
        "urls": ["http://example.com/login"],
    }

    with patch(
        "modules.crawlers.domain_theharvester._check_harvester_installed",
        new=AsyncMock(return_value=True),
    ), patch(
        "modules.crawlers.domain_theharvester._run_harvester",
        new=AsyncMock(return_value=raw),
    ):
        result = await crawler.scrape("example.com")

    assert result.found is True
    assert result.platform == "domain_harvester"
    assert result.data["emails"] == ["admin@example.com", "info@example.com"]
    assert "mail.example.com" in result.data["subdomains"]
    assert "www.example.com" in result.data["subdomains"]
    assert result.data["ips"] == ["93.184.216.34"]
    assert result.data["urls"] == ["http://example.com/login"]
    assert result.data["domain"] == "example.com"


@pytest.mark.asyncio
async def test_harvester_no_results_found_false():
    """Empty harvester output yields found=False."""
    crawler = DomainHarvesterCrawler()

    with patch(
        "modules.crawlers.domain_theharvester._check_harvester_installed",
        new=AsyncMock(return_value=True),
    ), patch(
        "modules.crawlers.domain_theharvester._run_harvester",
        new=AsyncMock(return_value={}),
    ):
        result = await crawler.scrape("empty.com")

    assert result.found is False
    assert result.data["emails"] == []
    assert result.data["subdomains"] == []


@pytest.mark.asyncio
async def test_harvester_not_installed():
    """Missing theHarvester binary returns graceful error."""
    crawler = DomainHarvesterCrawler()

    with patch(
        "modules.crawlers.domain_theharvester._check_harvester_installed",
        new=AsyncMock(return_value=False),
    ):
        result = await crawler.scrape("example.com")

    assert result.found is False
    assert result.error == "theharvester_not_installed"


def test_harvester_parse_host_strips_ip():
    """_parse_harvester_output strips IP suffixes from host entries."""
    raw = {
        "hosts": ["sub.example.com:1.2.3.4", "mail.example.com"],
        "emails": [],
        "ips": [],
        "urls": [],
    }
    parsed = _parse_harvester_output(raw)
    assert "sub.example.com" in parsed["subdomains"]
    assert "mail.example.com" in parsed["subdomains"]
    # No IP suffix should survive
    for s in parsed["subdomains"]:
        assert ":" not in s


def test_harvester_source_reliability():
    """DomainHarvesterCrawler.source_reliability should be 0.70."""
    crawler = DomainHarvesterCrawler()
    assert crawler.source_reliability == 0.70


def test_harvester_requires_tor_false():
    """theHarvester uses its own network; Tor is not required."""
    crawler = DomainHarvesterCrawler()
    assert crawler.requires_tor is False


# ---------------------------------------------------------------------------
# DomainWhoisCrawler — 6 tests
# ---------------------------------------------------------------------------

_WHOIS_HTML = """
<html><body>
<pre>
Domain Name: EXAMPLE.COM
Registrar: Example Registrar, Inc.
Creation Date: 1995-08-14T04:00:00Z
Registry Expiry Date: 2026-08-13T04:00:00Z
Registrant Name: John Doe
Registrant Organization: Example Corp
Registrant Country: US
Name Server: NS1.EXAMPLE.COM
Name Server: NS2.EXAMPLE.COM
</pre>
</body></html>
"""


def test_domain_whois_registered():
    assert is_registered("domain_whois")


@pytest.mark.asyncio
async def test_whois_parse_full_record():
    """WHOIS HTML with a full record is parsed into all expected fields."""
    crawler = DomainWhoisCrawler()

    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(200, text=_WHOIS_HTML))):
        result = await crawler.scrape("example.com")

    assert result.found is True
    assert result.platform == "domain_whois"
    assert result.data["registrar"] == "Example Registrar, Inc."
    assert result.data["creation_date"] == "1995-08-14T04:00:00Z"
    assert result.data["expiry_date"] == "2026-08-13T04:00:00Z"
    assert result.data["registrant_name"] == "John Doe"
    assert result.data["registrant_org"] == "Example Corp"
    assert result.data["registrant_country"] == "US"
    assert "ns1.example.com" in result.data["name_servers"]
    assert "ns2.example.com" in result.data["name_servers"]


@pytest.mark.asyncio
async def test_whois_http_error_none():
    """Network failure returns found=False with http_error."""
    crawler = DomainWhoisCrawler()

    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("example.com")

    assert result.found is False
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_whois_rate_limited_429():
    """HTTP 429 returns found=False with rate_limited error."""
    crawler = DomainWhoisCrawler()

    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(429))):
        result = await crawler.scrape("example.com")

    assert result.found is False
    assert result.error == "rate_limited"


def test_parse_whois_name_servers_lowercased():
    """_parse_whois returns name servers in lowercase."""
    text = "Name Server: NS1.EXAMPLE.COM\nName Server: NS2.EXAMPLE.COM\n"
    parsed = _parse_whois(text)
    assert parsed["name_servers"] == ["ns1.example.com", "ns2.example.com"]


def test_whois_source_reliability():
    """DomainWhoisCrawler.source_reliability should be 0.75."""
    crawler = DomainWhoisCrawler()
    assert crawler.source_reliability == 0.75


def test_whois_requires_tor_and_instance():
    """WHOIS crawler requires Tor and should use TOR2."""
    from shared.tor import TorInstance
    crawler = DomainWhoisCrawler()
    assert crawler.requires_tor is True
    assert crawler.tor_instance == TorInstance.TOR2
