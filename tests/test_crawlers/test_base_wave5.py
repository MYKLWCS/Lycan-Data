"""
test_base_wave5.py — Coverage gap tests for modules/crawlers/base.py.

Targets:
  - Lines 88-89: rotate_circuit() calls tor_manager.new_circuit() and logs info.
    This is the async rotate_circuit method on BaseCrawler.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.base import BaseCrawler
from modules.crawlers.result import CrawlerResult
from shared.tor import TorInstance


# ---------------------------------------------------------------------------
# Concrete subclass for testing (BaseCrawler is abstract)
# ---------------------------------------------------------------------------


class _DummyCrawler(BaseCrawler):
    platform = "dummy"
    source_reliability = 0.5
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        return self._result(identifier, found=False)


# ---------------------------------------------------------------------------
# Lines 88-89: rotate_circuit()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rotate_circuit_calls_tor_manager():
    """
    Line 88: await tor_manager.new_circuit(self.tor_instance)
    Line 89: logger.info(...)
    Both are exercised when rotate_circuit() is called.
    """
    crawler = _DummyCrawler()

    with patch("modules.crawlers.base.tor_manager") as mock_tor_mgr:
        mock_tor_mgr.new_circuit = AsyncMock()

        await crawler.rotate_circuit()

        mock_tor_mgr.new_circuit.assert_awaited_once_with(TorInstance.TOR2)


@pytest.mark.asyncio
async def test_rotate_circuit_logs_platform_name():
    """
    Line 89: logger.info logs the platform name after rotating.
    """
    crawler = _DummyCrawler()

    with patch("modules.crawlers.base.tor_manager") as mock_tor_mgr:
        mock_tor_mgr.new_circuit = AsyncMock()
        with patch("modules.crawlers.base.logger") as mock_log:
            await crawler.rotate_circuit()

            mock_log.info.assert_called_once()
            call_args = mock_log.info.call_args
            # The platform name "dummy" appears in the log message
            assert "dummy" in str(call_args)


@pytest.mark.asyncio
async def test_rotate_circuit_uses_crawler_tor_instance():
    """
    Line 88: The crawler's tor_instance attribute is passed to new_circuit.
    """
    crawler = _DummyCrawler()
    crawler.tor_instance = TorInstance.TOR1

    with patch("modules.crawlers.base.tor_manager") as mock_tor_mgr:
        mock_tor_mgr.new_circuit = AsyncMock()
        await crawler.rotate_circuit()

        mock_tor_mgr.new_circuit.assert_awaited_once_with(TorInstance.TOR1)
