from __future__ import annotations
import asyncio
import logging
import random
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from shared.config import settings
from shared.tor import tor_manager, TorInstance
from modules.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)

# Rotating user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:123.0) Gecko/20100101 Firefox/123.0",
]


class PlaywrightCrawler(BaseCrawler):
    """
    Playwright-based scraper with stealth config and Tor routing.

    Subclasses call `async with self.page() as page:` to get a stealth browser page.
    """

    @asynccontextmanager
    async def page(self, url: str | None = None) -> AsyncGenerator[Page, None]:
        """Context manager that yields a stealth Playwright page."""
        proxy = self.get_proxy()
        proxy_config = {"server": proxy} if proxy else None

        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(
                headless=True,
                proxy=proxy_config,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                ],
            )
            context: BrowserContext = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": random.randint(1200, 1920), "height": random.randint(768, 1080)},
                java_script_enabled=True,
                locale="en-US",
                timezone_id="America/New_York",
            )
            # Anti-detection: hide webdriver flag
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page: Page = await context.new_page()
            try:
                if url:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                yield page
            finally:
                await browser.close()

    def is_blocked(self, page: Page) -> bool:
        """Heuristic: detect common block pages."""
        title = page.title() if hasattr(page, "title") else ""
        blocked_signals = ["captcha", "blocked", "403", "access denied", "unusual traffic"]
        return any(s in str(title).lower() for s in blocked_signals)
