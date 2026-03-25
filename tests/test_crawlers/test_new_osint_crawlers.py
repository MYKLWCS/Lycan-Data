"""
Tests for Tasks 13–15 new OSINT crawlers.

Covers:
- MaigretCrawler: BaseCrawler subclass, platform attribute, graceful no-binary path
- SocialscanCrawler: BaseCrawler subclass, platform attribute, graceful no-library path
- PhoneInfogaCrawler: BaseCrawler subclass, platform attribute, graceful no-binary path
- PhonebookCrawler: CurlCrawler subclass, platform attribute
- IntelXCrawler: CurlCrawler subclass, platform attribute, no API key returns error result
- DeHashedCrawler: CurlCrawler subclass, platform attribute, no API key returns error result
"""

from __future__ import annotations

import importlib

import pytest

from modules.crawlers.base import BaseCrawler
from modules.crawlers.curl_base import CurlCrawler


# ---------------------------------------------------------------------------
# Import checks — all modules must import without error
# ---------------------------------------------------------------------------


def _import(mod_path: str):
    return importlib.import_module(mod_path)


def test_username_maigret_imports():
    mod = _import("modules.crawlers.username_maigret")
    assert hasattr(mod, "MaigretCrawler")


def test_email_socialscan_imports():
    mod = _import("modules.crawlers.email_socialscan")
    assert hasattr(mod, "SocialscanCrawler")


def test_phone_phoneinfoga_imports():
    mod = _import("modules.crawlers.phone_phoneinfoga")
    assert hasattr(mod, "PhoneInfogaCrawler")


def test_people_phonebook_imports():
    mod = _import("modules.crawlers.people_phonebook")
    assert hasattr(mod, "PhonebookCrawler")


def test_people_intelx_imports():
    mod = _import("modules.crawlers.people_intelx")
    assert hasattr(mod, "IntelXCrawler")


def test_email_dehashed_imports():
    mod = _import("modules.crawlers.email_dehashed")
    assert hasattr(mod, "DeHashedCrawler")


# ---------------------------------------------------------------------------
# Inheritance checks
# ---------------------------------------------------------------------------


def test_maigret_is_base_crawler():
    from modules.crawlers.username_maigret import MaigretCrawler

    assert issubclass(MaigretCrawler, BaseCrawler)
    assert not issubclass(MaigretCrawler, CurlCrawler)


def test_socialscan_is_base_crawler():
    from modules.crawlers.email_socialscan import SocialscanCrawler

    assert issubclass(SocialscanCrawler, BaseCrawler)
    assert not issubclass(SocialscanCrawler, CurlCrawler)


def test_phoneinfoga_is_base_crawler():
    from modules.crawlers.phone_phoneinfoga import PhoneInfogaCrawler

    assert issubclass(PhoneInfogaCrawler, BaseCrawler)
    assert not issubclass(PhoneInfogaCrawler, CurlCrawler)


def test_phonebook_is_curl_crawler():
    from modules.crawlers.people_phonebook import PhonebookCrawler

    assert issubclass(PhonebookCrawler, CurlCrawler)


def test_intelx_is_curl_crawler():
    from modules.crawlers.people_intelx import IntelXCrawler

    assert issubclass(IntelXCrawler, CurlCrawler)


def test_dehashed_is_curl_crawler():
    from modules.crawlers.email_dehashed import DeHashedCrawler

    assert issubclass(DeHashedCrawler, CurlCrawler)


# ---------------------------------------------------------------------------
# Platform attribute checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mod_path,class_name,expected_platform",
    [
        ("modules.crawlers.username_maigret", "MaigretCrawler", "username_maigret"),
        ("modules.crawlers.email_socialscan", "SocialscanCrawler", "email_socialscan"),
        ("modules.crawlers.phone_phoneinfoga", "PhoneInfogaCrawler", "phone_phoneinfoga"),
        ("modules.crawlers.people_phonebook", "PhonebookCrawler", "people_phonebook"),
        ("modules.crawlers.people_intelx", "IntelXCrawler", "people_intelx"),
        ("modules.crawlers.email_dehashed", "DeHashedCrawler", "email_dehashed"),
    ],
)
def test_platform_attribute(mod_path, class_name, expected_platform):
    mod = importlib.import_module(mod_path)
    cls = getattr(mod, class_name)
    assert cls.platform == expected_platform


# ---------------------------------------------------------------------------
# Registry checks — all must be registered
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "platform",
    [
        "username_maigret",
        "email_socialscan",
        "phone_phoneinfoga",
        "people_phonebook",
        "people_intelx",
        "email_dehashed",
    ],
)
def test_registered_in_registry(platform):
    # Import each module first to trigger @register decorator
    _mod_map = {
        "username_maigret": "modules.crawlers.username_maigret",
        "email_socialscan": "modules.crawlers.email_socialscan",
        "phone_phoneinfoga": "modules.crawlers.phone_phoneinfoga",
        "people_phonebook": "modules.crawlers.people_phonebook",
        "people_intelx": "modules.crawlers.people_intelx",
        "email_dehashed": "modules.crawlers.email_dehashed",
    }
    importlib.import_module(_mod_map[platform])
    from modules.crawlers.registry import CRAWLER_REGISTRY

    assert platform in CRAWLER_REGISTRY


# ---------------------------------------------------------------------------
# Graceful degradation — no binary / no library / no API key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maigret_no_binary_returns_error():
    """MaigretCrawler returns an error result when maigret is not on PATH."""
    import shutil
    from unittest.mock import patch

    from modules.crawlers.username_maigret import MaigretCrawler

    with patch.object(shutil, "which", return_value=None):
        result = await MaigretCrawler().scrape("testuser")

    assert result.found is False
    assert result.error == "maigret_not_installed"


@pytest.mark.asyncio
async def test_socialscan_no_library_returns_error():
    """SocialscanCrawler returns an error result when socialscan is not installed."""
    import builtins
    from unittest.mock import patch

    real_import = builtins.__import__

    def _block_socialscan(name, *args, **kwargs):
        if name.startswith("socialscan"):
            raise ImportError("No module named 'socialscan'")
        return real_import(name, *args, **kwargs)

    from modules.crawlers.email_socialscan import SocialscanCrawler

    with patch("builtins.__import__", side_effect=_block_socialscan):
        result = await SocialscanCrawler().scrape("test@example.com")

    assert result.found is False
    assert result.error == "socialscan_not_installed"


@pytest.mark.asyncio
async def test_phoneinfoga_no_binary_returns_error():
    """PhoneInfogaCrawler returns an error result when phoneinfoga is not on PATH."""
    import shutil
    from unittest.mock import patch

    from modules.crawlers.phone_phoneinfoga import PhoneInfogaCrawler

    with patch.object(shutil, "which", return_value=None):
        result = await PhoneInfogaCrawler().scrape("+15551234567")

    assert result.found is False
    assert result.error == "phoneinfoga_not_installed"


@pytest.mark.asyncio
async def test_intelx_no_api_key_returns_error():
    """IntelXCrawler returns an error result when INTELX_API_KEY is not set."""
    from unittest.mock import patch

    from modules.crawlers.people_intelx import IntelXCrawler

    with patch.dict("os.environ", {}, clear=True):
        result = await IntelXCrawler().scrape("john.doe@example.com")

    assert result.found is False
    assert "INTELX_API_KEY" in result.error


@pytest.mark.asyncio
async def test_dehashed_no_credentials_returns_error():
    """DeHashedCrawler returns an error result when credentials are not set."""
    from unittest.mock import patch

    from modules.crawlers.email_dehashed import DeHashedCrawler

    with patch.dict("os.environ", {}, clear=True):
        result = await DeHashedCrawler().scrape("john.doe@example.com")

    assert result.found is False
    assert "DEHASHED" in result.error
