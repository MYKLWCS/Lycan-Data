"""
CamoufoxCrawler — Firefox-based stealth browser.

Uses camoufox (patched Firefox) which defeats PerimeterX, DataDome, and other
fingerprinting systems that have signatures for Chrome-based headless browsers.
Provides a different fingerprint than patchright/Playwright (Firefox vs Chrome).

Falls back gracefully if camoufox is not installed (ImportError is caught).
"""

from __future__ import annotations

import logging
import random

from modules.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)


class CamoufoxCrawler(BaseCrawler):
    """BaseCrawler variant using camoufox (patched Firefox) for stealth browsing."""

    async def get_page(self, url: str) -> str:
        """
        Fetch page HTML via camoufox stealth Firefox.
        Returns rendered HTML string. Falls back to empty string on error.
        """
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError:
            logger.warning("camoufox not installed; returning empty string for %s", url)
            return ""

        try:
            await self._human_delay()
            proxy = self.get_proxy()
            proxy_dict = {"server": proxy} if proxy else None

            async with AsyncCamoufox(
                headless=True,
                proxy=proxy_dict,
                geoip=True,
                viewport={
                    "width": random.randint(1280, 1920),
                    "height": random.randint(720, 1080),
                },
            ) as browser:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                return await page.content()
        except Exception as exc:
            logger.warning("CamoufoxCrawler.get_page failed for %s: %s", url, exc)
            return ""
