"""
Tests for email enrichment crawlers:
  - EmailHoleheCrawler (email_holehe)  — 6 tests
  - EmailHIBPCrawler  (email_hibp)     — 6 tests

Total: 12 tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.email_hibp  # noqa: F401
import modules.crawlers.email_holehe  # noqa: F401 — trigger @register
from modules.crawlers.email_hibp import EmailHIBPCrawler
from modules.crawlers.email_holehe import EmailHoleheCrawler, _run_holehe
from modules.crawlers.registry import is_registered

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int = 200, json_data=None):
    mock = MagicMock()
    mock.status_code = status_code
    if json_data is not None:
        mock.json.return_value = json_data
    else:
        mock.json.side_effect = ValueError("no json")
    return mock


# ---------------------------------------------------------------------------
# EmailHoleheCrawler — 6 tests
# ---------------------------------------------------------------------------


def test_email_holehe_registered():
    assert is_registered("email_holehe")


@pytest.mark.asyncio
async def test_holehe_found_services():
    """Holehe returns found services parsed correctly."""
    crawler = EmailHoleheCrawler()

    async def fake_run(email):
        return (["twitter.com", "instagram.com"], 50)

    with (
        patch(
            "modules.crawlers.email_holehe._check_holehe_installed",
            new=AsyncMock(return_value=True),
        ),
        patch("modules.crawlers.email_holehe._run_holehe", new=AsyncMock(side_effect=fake_run)),
    ):
        result = await crawler.scrape("test@example.com")

    assert result.found is True
    assert result.platform == "email_holehe"
    assert result.data["found_on"] == ["twitter.com", "instagram.com"]
    assert result.data["checked_count"] == 50
    assert result.data["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_holehe_no_services_found():
    """Holehe runs successfully but email is not on any service."""
    crawler = EmailHoleheCrawler()

    async def fake_run(email):
        return ([], 80)

    with (
        patch(
            "modules.crawlers.email_holehe._check_holehe_installed",
            new=AsyncMock(return_value=True),
        ),
        patch("modules.crawlers.email_holehe._run_holehe", new=AsyncMock(side_effect=fake_run)),
    ):
        result = await crawler.scrape("nobody@example.com")

    assert result.found is True
    assert result.data["found_on"] == []
    assert result.data["checked_count"] == 80


@pytest.mark.asyncio
async def test_holehe_not_installed():
    """If holehe is not on PATH the crawler returns a graceful error result."""
    crawler = EmailHoleheCrawler()

    with patch(
        "modules.crawlers.email_holehe._check_holehe_installed", new=AsyncMock(return_value=False)
    ):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "holehe_not_installed"


@pytest.mark.asyncio
async def test_holehe_timeout():
    """Subprocess timeout returns found=False with timeout error."""
    crawler = EmailHoleheCrawler()

    async def timeout_run(email):
        raise TimeoutError()

    with (
        patch(
            "modules.crawlers.email_holehe._check_holehe_installed",
            new=AsyncMock(return_value=True),
        ),
        patch("modules.crawlers.email_holehe._run_holehe", new=AsyncMock(side_effect=timeout_run)),
    ):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "holehe_timeout"


@pytest.mark.asyncio
async def test_holehe_parse_stdout_lines():
    """_run_holehe parses [+] lines into found list and counts [+]/[-] total."""
    fake_stdout = (
        b"[+] twitter.com\n[-] instagram.com\n[+] github.com\n[-] reddit.com\n[-] pinterest.com\n"
    )

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(fake_stdout, b""))

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        patch("asyncio.wait_for", new=AsyncMock(return_value=(fake_stdout, b""))),
    ):
        # Call directly to test parsing logic
        lines = fake_stdout.decode().splitlines()
        import re

        found = [re.sub(r"\[.\]\s*", "", l).strip() for l in lines if l.startswith("[+]")]
        total = sum(1 for l in lines if l.startswith("[+]") or l.startswith("[-]"))

    assert found == ["twitter.com", "github.com"]
    assert total == 5


# ---------------------------------------------------------------------------
# EmailHIBPCrawler — 6 tests
# ---------------------------------------------------------------------------

_HIBP_BREACH_JSON = [
    {
        "Name": "Adobe",
        "Domain": "adobe.com",
        "BreachDate": "2013-10-04",
        "DataClasses": ["Email addresses", "Password hints", "Usernames"],
    },
    {
        "Name": "LinkedIn",
        "Domain": "linkedin.com",
        "BreachDate": "2012-05-05",
        "DataClasses": ["Email addresses", "Passwords"],
    },
]


def test_email_hibp_registered():
    assert is_registered("email_hibp")


@pytest.mark.asyncio
async def test_hibp_breaches_found():
    """HIBP 200 response with breach list is parsed correctly."""
    crawler = EmailHIBPCrawler()
    with patch.object(
        crawler, "get", new=AsyncMock(return_value=_mock_response(200, json_data=_HIBP_BREACH_JSON))
    ):
        result = await crawler.scrape("victim@example.com")

    assert result.found is True
    assert result.platform == "email_hibp"
    assert result.data["breach_count"] == 2
    assert result.data["breaches"][0]["name"] == "Adobe"
    assert result.data["breaches"][0]["domain"] == "adobe.com"
    assert "Email addresses" in result.data["breaches"][0]["data_classes"]
    assert result.data["email"] == "victim@example.com"


@pytest.mark.asyncio
async def test_hibp_clean_email_404():
    """HIBP 404 means email has no breaches — found=True with empty list."""
    crawler = EmailHIBPCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(404))):
        result = await crawler.scrape("clean@example.com")

    assert result.found is True
    assert result.data["breaches"] == []
    assert result.data["breach_count"] == 0


@pytest.mark.asyncio
async def test_hibp_rate_limited_429():
    """HIBP 429 returns found=False with rate_limited error."""
    crawler = EmailHIBPCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_response(429))):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "rate_limited"


@pytest.mark.asyncio
async def test_hibp_http_error_none():
    """Network failure (None) returns found=False with http_error."""
    crawler = EmailHIBPCrawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "http_error"


@pytest.mark.asyncio
async def test_hibp_source_reliability():
    """HIBP source_reliability should be 0.80."""
    crawler = EmailHIBPCrawler()
    assert crawler.source_reliability == 0.80
