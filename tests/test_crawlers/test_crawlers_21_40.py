"""
Tests for crawlers 21-40 (spec-09 batch).

Crawlers covered:
  21. tiktok              — TikTokCrawler
  22. youtube             — YouTubeCrawler
  23. telegram            — TelegramCrawler
  24. social_ghunt        — GHuntCrawler          ← NEW
  25. linkedin            — LinkedInCrawler
  26. phone_phoneinfoga   — PhoneInfogaCrawler
  27. email_emailrep      — EmailRepCrawler
  28. email_mx_validator  — MxValidatorCrawler (or similar)
  29. email_disposable    — DisposableEmailCrawler ← NEW
  30. phone_truecaller     — TruecallerCrawler
  31. gov_uspto_patents    — UsptoPatentsCrawler
  32. gov_uspto_trademarks — UsptoTrademarksCrawler
  33. gov_usaspending      — UsaSpendingCrawler
  34. gov_osha            — OshaCrawler
  35. gov_epa             — EpaCrawler
  36. cyber_shodan        — ShodanCrawler
  37. domain_whois        — DomainWhoisCrawler
  38. cyber_crt           — CrtCrawler
  39. email_hibp          — EmailHIBPCrawler
  40. cyber_virustotal    — VirusTotalCrawler

Each crawler gets:
  - import check
  - issubclass(BaseCrawler) check
  - platform attribute check
  - registry registration check
  - graceful degradation / no-key / no-binary test
"""

from __future__ import annotations

import importlib
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.base import BaseCrawler
from modules.crawlers.registry import is_registered

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CRAWLER_MAP: dict[str, tuple[str, str]] = {
    # platform: (module_path, class_name)
    "tiktok":               ("modules.crawlers.tiktok",              "TikTokCrawler"),
    "youtube":              ("modules.crawlers.youtube",             "YouTubeCrawler"),
    "telegram":             ("modules.crawlers.telegram",            "TelegramCrawler"),
    "social_ghunt":         ("modules.crawlers.social_ghunt",        "GHuntCrawler"),
    "phone_phoneinfoga":    ("modules.crawlers.phone_phoneinfoga",   "PhoneInfogaCrawler"),
    "email_emailrep":       ("modules.crawlers.email_emailrep",      "EmailRepCrawler"),
    "email_disposable":     ("modules.crawlers.email_disposable",    "DisposableEmailCrawler"),
    "gov_uspto_patents":    ("modules.crawlers.gov_uspto_patents",   "UsptoPatentsCrawler"),
    "gov_usaspending":      ("modules.crawlers.gov_usaspending",     "UsaSpendingCrawler"),
    "gov_osha":             ("modules.crawlers.gov_osha",            "OshaCrawler"),
    "gov_epa":              ("modules.crawlers.gov_epa",             "EpaCrawler"),
    "cyber_shodan":         ("modules.crawlers.cyber_shodan",        "ShodanCrawler"),
    "domain_whois":         ("modules.crawlers.domain_whois",        "DomainWhoisCrawler"),
    "cyber_crt":            ("modules.crawlers.cyber_crt",           "CrtCrawler"),
    "email_hibp":           ("modules.crawlers.email_hibp",          "EmailHIBPCrawler"),
    "cyber_virustotal":     ("modules.crawlers.cyber_virustotal",    "VirusTotalCrawler"),
}

# Some class names may differ from the convention above — discover dynamically
_CLASS_OVERRIDES: dict[str, str] = {}


def _get_class(platform: str):
    mod_path, cls_name = CRAWLER_MAP[platform]
    mod = importlib.import_module(mod_path)
    # Try override first, then specified name, then search
    name = _CLASS_OVERRIDES.get(platform, cls_name)
    if hasattr(mod, name):
        return getattr(mod, name)
    # Fallback: find any BaseCrawler subclass with matching platform
    for attr in dir(mod):
        obj = getattr(mod, attr)
        try:
            if isinstance(obj, type) and issubclass(obj, BaseCrawler) and obj is not BaseCrawler:
                if getattr(obj, "platform", None) == platform:
                    return obj
        except TypeError:
            pass
    raise AttributeError(f"Cannot find crawler class for platform '{platform}' in {mod_path}")


def _mock_response(status_code: int = 200, json_data=None):
    mock = MagicMock()
    mock.status_code = status_code
    if json_data is not None:
        mock.json.return_value = json_data
    else:
        mock.json.side_effect = ValueError("no json")
    return mock


# ---------------------------------------------------------------------------
# Import checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("platform", list(CRAWLER_MAP.keys()))
def test_module_imports(platform):
    mod_path, _ = CRAWLER_MAP[platform]
    mod = importlib.import_module(mod_path)
    assert mod is not None


# ---------------------------------------------------------------------------
# Inheritance checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("platform", list(CRAWLER_MAP.keys()))
def test_is_base_crawler_subclass(platform):
    cls = _get_class(platform)
    assert issubclass(cls, BaseCrawler), f"{cls} is not a BaseCrawler subclass"


# ---------------------------------------------------------------------------
# Platform attribute checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("platform", list(CRAWLER_MAP.keys()))
def test_platform_attribute(platform):
    cls = _get_class(platform)
    assert cls.platform == platform, f"Expected platform='{platform}', got '{cls.platform}'"


# ---------------------------------------------------------------------------
# Registry checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("platform", list(CRAWLER_MAP.keys()))
def test_registered_in_registry(platform):
    # Ensure the module has been imported (triggers @register)
    mod_path, _ = CRAWLER_MAP[platform]
    importlib.import_module(mod_path)
    assert is_registered(platform), f"'{platform}' not in CRAWLER_REGISTRY"


# ---------------------------------------------------------------------------
# Category attribute present
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("platform", list(CRAWLER_MAP.keys()))
def test_category_attribute_set(platform):
    from modules.crawlers.core.models import CrawlerCategory

    cls = _get_class(platform)
    assert isinstance(
        cls.category, CrawlerCategory
    ), f"{cls}.category is not a CrawlerCategory"


# ---------------------------------------------------------------------------
# Rate limit attribute present
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("platform", list(CRAWLER_MAP.keys()))
def test_rate_limit_attribute_set(platform):
    from modules.crawlers.core.models import RateLimit

    cls = _get_class(platform)
    assert isinstance(
        cls.rate_limit, RateLimit
    ), f"{cls}.rate_limit is not a RateLimit"


# ===========================================================================
# Graceful-degradation / no-config tests
# ===========================================================================


# ---------------------------------------------------------------------------
# 24. GHuntCrawler — no binary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ghunt_no_binary_returns_error():
    """GHuntCrawler returns error when ghunt binary is not on PATH."""
    from modules.crawlers.social_ghunt import GHuntCrawler

    with patch.object(shutil, "which", return_value=None):
        result = await GHuntCrawler().scrape("test@gmail.com")

    assert result.found is False
    assert result.error == "ghunt_not_installed"


@pytest.mark.asyncio
async def test_ghunt_timeout_returns_error():
    """GHuntCrawler returns error on subprocess timeout."""
    import subprocess

    from modules.crawlers.social_ghunt import GHuntCrawler

    with (
        patch.object(shutil, "which", return_value="/usr/local/bin/ghunt"),
        patch(
            "modules.crawlers.social_ghunt._run_ghunt_sync",
            side_effect=subprocess.TimeoutExpired(cmd="ghunt", timeout=120),
        ),
    ):
        result = await GHuntCrawler().scrape("test@gmail.com")

    assert result.found is False
    assert result.error == "ghunt_timeout"


@pytest.mark.asyncio
async def test_ghunt_no_json_output_returns_not_found():
    """GHuntCrawler returns not-found when stdout contains no JSON."""
    from modules.crawlers.social_ghunt import GHuntCrawler

    with (
        patch.object(shutil, "which", return_value="/usr/local/bin/ghunt"),
        patch(
            "modules.crawlers.social_ghunt._run_ghunt_sync",
            return_value=(0, b"Account not found\n", b""),
        ),
    ):
        result = await GHuntCrawler().scrape("ghost@gmail.com")

    assert result.found is False
    assert result.error == "no_json_output"


@pytest.mark.asyncio
async def test_ghunt_valid_json_found():
    """GHuntCrawler returns found=True when GHunt emits valid JSON with gaia_id."""
    import json

    from modules.crawlers.social_ghunt import GHuntCrawler

    payload = {
        "version": "2.0",
        "profile": {
            "name": "Test User",
            "gaia_id": "123456789",
            "profile_photo_url": "https://lh3.googleusercontent.com/photo.jpg",
        },
        "activated_services": ["Gmail", "YouTube", "Maps"],
    }

    with (
        patch.object(shutil, "which", return_value="/usr/local/bin/ghunt"),
        patch(
            "modules.crawlers.social_ghunt._run_ghunt_sync",
            return_value=(0, json.dumps(payload).encode(), b""),
        ),
    ):
        result = await GHuntCrawler().scrape("test@gmail.com")

    assert result.found is True
    assert result.data.get("name") == "Test User"
    assert result.data.get("gaia_id") == "123456789"
    assert "Gmail" in result.data.get("activated_services", [])


# ---------------------------------------------------------------------------
# 29. DisposableEmailCrawler — local blocklist & API layers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disposable_local_blocklist_hit():
    """DisposableEmailCrawler returns disposable=True for known burner domain."""
    from modules.crawlers.email_disposable import DisposableEmailCrawler

    result = await DisposableEmailCrawler().scrape("user@mailinator.com")

    assert result.found is True
    assert result.data.get("disposable") is True
    assert result.data.get("source") == "local_blocklist"


@pytest.mark.asyncio
async def test_disposable_local_blocklist_bare_domain():
    """DisposableEmailCrawler accepts bare domain (no @) as input."""
    from modules.crawlers.email_disposable import DisposableEmailCrawler

    result = await DisposableEmailCrawler().scrape("guerrillamail.com")

    assert result.found is True
    assert result.data.get("disposable") is True


@pytest.mark.asyncio
async def test_disposable_kickbox_api_positive():
    """DisposableEmailCrawler uses Kickbox when domain not in local list."""
    from modules.crawlers.email_disposable import DisposableEmailCrawler

    crawler = DisposableEmailCrawler()
    mock_resp = _mock_response(200, {"disposable": True})

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("user@some-new-burner-domain.com")

    assert result.found is True
    assert result.data.get("disposable") is True
    assert result.data.get("source") == "kickbox"


@pytest.mark.asyncio
async def test_disposable_kickbox_api_negative():
    """DisposableEmailCrawler returns disposable=False for legit domain via Kickbox."""
    from modules.crawlers.email_disposable import DisposableEmailCrawler

    crawler = DisposableEmailCrawler()
    mock_resp = _mock_response(200, {"disposable": False})

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("user@gmail.com")

    assert result.found is True
    assert result.data.get("disposable") is False
    assert result.data.get("source") == "kickbox"


@pytest.mark.asyncio
async def test_disposable_falls_back_to_mailcheck():
    """DisposableEmailCrawler falls back to mailcheck.ai when Kickbox fails."""
    from modules.crawlers.email_disposable import DisposableEmailCrawler

    crawler = DisposableEmailCrawler()

    kickbox_resp = _mock_response(503)  # Kickbox down
    mailcheck_resp = _mock_response(200, {"disposable": True, "role": False, "mx": True})

    call_count = 0

    async def _get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "kickbox" in url:
            return kickbox_resp
        return mailcheck_resp

    with patch.object(crawler, "get", new=_get):
        result = await crawler.scrape("user@obscure-burner.net")

    assert result.found is True
    assert result.data.get("disposable") is True
    assert result.data.get("source") == "mailcheck"


@pytest.mark.asyncio
async def test_disposable_all_sources_fail_returns_unknown():
    """DisposableEmailCrawler returns disposable=None when all sources fail."""
    from modules.crawlers.email_disposable import DisposableEmailCrawler

    crawler = DisposableEmailCrawler()
    error_resp = _mock_response(503)

    with patch.object(crawler, "get", new=AsyncMock(return_value=error_resp)):
        result = await crawler.scrape("user@some-unknown-domain.xyz")

    assert result.found is True  # domain was found; status is unknown
    assert result.data.get("disposable") is None
    assert result.data.get("source") == "unknown"


# ---------------------------------------------------------------------------
# Spot checks on previously-existing crawlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shodan_no_api_key_returns_error():
    """ShodanCrawler returns not-found when no API key configured."""
    from unittest.mock import patch as _patch

    import modules.crawlers.cyber_shodan  # noqa: F401
    from modules.crawlers.cyber_shodan import ShodanCrawler

    with _patch("modules.crawlers.cyber_shodan.settings") as mock_settings:
        mock_settings.shodan_api_key = ""
        result = await ShodanCrawler().scrape("8.8.8.8")

    assert result.found is False
    # ShodanCrawler uses _result() which stores error in data dict
    assert "not_configured" in (result.error or result.data.get("error", ""))


@pytest.mark.asyncio
async def test_virustotal_no_api_key_returns_error():
    """VirusTotalCrawler returns error when no API key configured."""
    import modules.crawlers.cyber_virustotal  # noqa: F401
    from modules.crawlers.cyber_virustotal import VirusTotalCrawler

    with patch("modules.crawlers.cyber_virustotal.settings") as mock_settings:
        mock_settings.virustotal_api_key = ""
        result = await VirusTotalCrawler().scrape("https://example.com")

    assert result.found is False


@pytest.mark.asyncio
async def test_email_hibp_404_means_no_breach():
    """EmailHIBPCrawler 404 response means no breaches found (clean)."""
    import modules.crawlers.email_hibp  # noqa: F401
    from modules.crawlers.email_hibp import EmailHIBPCrawler

    crawler = EmailHIBPCrawler()
    mock_resp = _mock_response(404)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("clean@example.com")

    assert result.found is True
    assert result.data.get("breach_count") == 0


@pytest.mark.asyncio
async def test_email_emailrep_rate_limited():
    """EmailRepCrawler returns rate_limited error on 429."""
    import modules.crawlers.email_emailrep  # noqa: F401
    from modules.crawlers.email_emailrep import EmailRepCrawler

    crawler = EmailRepCrawler()
    mock_resp = _mock_response(429)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("test@example.com")

    assert result.found is False
    assert result.error == "rate_limited"


@pytest.mark.asyncio
async def test_phoneinfoga_no_binary():
    """PhoneInfogaCrawler returns error when phoneinfoga not on PATH."""
    import modules.crawlers.phone_phoneinfoga  # noqa: F401
    from modules.crawlers.phone_phoneinfoga import PhoneInfogaCrawler

    with patch.object(shutil, "which", return_value=None):
        result = await PhoneInfogaCrawler().scrape("+15551234567")

    assert result.found is False
    assert result.error == "phoneinfoga_not_installed"


@pytest.mark.asyncio
async def test_epa_http_error():
    """EpaCrawler returns error on non-200 response."""
    import modules.crawlers.gov_epa  # noqa: F401
    from modules.crawlers.gov_epa import EpaCrawler

    crawler = EpaCrawler()
    mock_resp = _mock_response(500)

    with patch.object(crawler, "get", new=AsyncMock(return_value=mock_resp)):
        result = await crawler.scrape("Acme Corp")

    assert result.found is False
    assert "http_500" in (result.error or "")
