from __future__ import annotations

import logging
import random
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from patchright.async_api import Browser, BrowserContext, Page, async_playwright

from modules.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)

# Rotating user agents — Chrome 130+ only
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

# Navigator stealth init script — applied on every new page
_STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
"""


class PlaywrightCrawler(BaseCrawler):
    """
    Patchright-based scraper with stealth config and Tor routing.

    Subclasses call `async with self.page() as page:` to get a stealth browser page.
    Patchright patches canvas, WebGL, fonts, audio, and navigator at a deeper level
    than vanilla Playwright; the additional init script covers remaining gaps.
    """

    USER_AGENTS = USER_AGENTS

    @asynccontextmanager
    async def page(self, url: str | None = None) -> AsyncGenerator[Page, None]:
        """Context manager that yields a stealth Patchright page."""
        proxy = await self.get_proxy_async()
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
                user_agent=random.choice(self.USER_AGENTS),
                viewport={
                    "width": random.randint(1280, 1920),
                    "height": random.randint(720, 1080),
                },
                java_script_enabled=True,
                locale="en-US",
                timezone_id="America/New_York",
            )
            page: Page = await context.new_page()
            await page.add_init_script(_STEALTH_SCRIPT)
            try:
                if url:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                yield page
            finally:
                await browser.close()

    async def is_blocked(self, page: Page) -> bool:
        """Heuristic: detect common block pages."""
        title = await page.title()
        html = await page.content()
        return self.html_has_block_signals(html, title=title)

    @staticmethod
    def html_has_block_signals(html: str, title: str = "") -> bool:
        """Detect common anti-bot challenge pages in rendered HTML."""
        text = f"{title}\n{html}".lower()
        blocked_signals = (
            "access denied",
            "attention required",
            "blocked",
            "captcha",
            "cf-challenge",
            "cloudflare",
            "forbidden",
            "ray id",
            "unusual traffic",
            "verify you are human",
            "why do i have to complete a captcha",
        )
        return any(signal in text for signal in blocked_signals)


# Alias for callers expecting the plan-spec name
PlaywrightBaseCrawler = PlaywrightCrawler
