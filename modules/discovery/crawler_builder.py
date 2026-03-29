"""
Crawler Template Builder.

Given an approved DiscoveredSource, generates a Python crawler template
that follows the existing modules/crawlers/* patterns (BaseHTTPXCrawler,
BasePlaywrightCrawler, etc.).

The template is stored as a JSONB blob in DiscoveredSource.crawler_template
and can be rendered to a .py file for deployment.
"""

from __future__ import annotations

import logging
import re
import textwrap
import urllib.parse
from datetime import timezone, datetime

logger = logging.getLogger(__name__)

# ── Category → base class mapping ─────────────────────────────────────────────

_BASE_CLASS_MAP: dict[str, tuple[str, str]] = {
    # category: (base_class_name, import_path)
    "social":          ("BaseHTTPXCrawler",      "modules.crawlers.httpx_base"),
    "professional":    ("BaseHTTPXCrawler",      "modules.crawlers.httpx_base"),
    "people_search":   ("BasePlaywrightCrawler", "modules.crawlers.playwright_base"),
    "court":           ("BaseHTTPXCrawler",      "modules.crawlers.httpx_base"),
    "government":      ("BaseHTTPXCrawler",      "modules.crawlers.httpx_base"),
    "business":        ("BaseHTTPXCrawler",      "modules.crawlers.httpx_base"),
    "property":        ("BasePlaywrightCrawler", "modules.crawlers.playwright_base"),
    "criminal":        ("BaseHTTPXCrawler",      "modules.crawlers.httpx_base"),
    "email_source":    ("BaseHTTPXCrawler",      "modules.crawlers.httpx_base"),
    "subdomain":       ("BaseHTTPXCrawler",      "modules.crawlers.httpx_base"),
    "web":             ("BaseHTTPXCrawler",      "modules.crawlers.httpx_base"),
    "web_form":        ("BasePlaywrightCrawler", "modules.crawlers.playwright_base"),
    "archive":         ("BaseHTTPXCrawler",      "modules.crawlers.httpx_base"),
}

_DEFAULT_BASE = ("BaseHTTPXCrawler", "modules.crawlers.httpx_base")


def build_template(
    name: str,
    url: str,
    category: str | None,
    data_types: list[str] | None,
    proposed_pattern: dict | None,
    reliability_tier: str | None,
) -> dict:
    """
    Generate a crawler template dict with:
      - class_name: PEP-8 class name
      - module_name: snake_case module filename (without .py)
      - base_class / base_import: which base to extend
      - source_code: rendered Python source as a string
      - created_at: ISO timestamp
    """
    cat = (category or "web").lower()
    base_class, base_import = _BASE_CLASS_MAP.get(cat, _DEFAULT_BASE)

    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.replace("www.", "").replace(".", "_").replace("-", "_")
    class_name = _to_pascal(netloc) + "Crawler"
    module_name = netloc.lower() + "_crawler"

    selectors = (proposed_pattern or {}).get("selectors", {})
    pagination = (proposed_pattern or {}).get("pagination", "next_link")

    source = _render_source(
        class_name=class_name,
        base_class=base_class,
        base_import=base_import,
        url=url,
        netloc=netloc,
        category=cat,
        data_types=data_types or [],
        selectors=selectors,
        pagination=pagination,
        reliability_tier=reliability_tier or "C",
    )

    return {
        "class_name": class_name,
        "module_name": module_name,
        "file_path": f"modules/crawlers/{module_name}.py",
        "base_class": base_class,
        "base_import": base_import,
        "category": cat,
        "source_code": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _render_source(
    *,
    class_name: str,
    base_class: str,
    base_import: str,
    url: str,
    netloc: str,
    category: str,
    data_types: list[str],
    selectors: dict,
    pagination: str,
    reliability_tier: str,
) -> str:
    sel_lines = "\n".join(
        f'        "{k}": "{v}",'
        for k, v in selectors.items()
    ) or '        # TODO: add CSS/XPath selectors\n        "name": "h1",'

    if base_class == "BasePlaywrightCrawler":
        scrape_body = textwrap.dedent(f"""
            async def scrape(self, identifier: str) -> CrawlerResult:
                url = self._build_url(identifier)
                async with self._page() as page:
                    await page.goto(url, wait_until="networkidle")
                    data = await self._extract(page)
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=bool(data),
                    data=data,
                )

            def _build_url(self, identifier: str) -> str:
                # TODO: build target URL from identifier
                return f"{url}/search?q={{identifier}}"

            async def _extract(self, page) -> dict:
                # TODO: implement extraction using Playwright page object
                data = {{}}
                selectors = {{
        {sel_lines}
                }}
                for field, sel in selectors.items():
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            data[field] = await el.inner_text()
                    except Exception:
                        pass
                return data
        """)
    else:
        scrape_body = textwrap.dedent(f"""
            async def scrape(self, identifier: str) -> CrawlerResult:
                url = self._build_url(identifier)
                resp = await self._get(url)
                if not resp or resp.status_code != 200:
                    return CrawlerResult(platform=self.platform, identifier=identifier, found=False)
                data = self._extract(resp.text)
                return CrawlerResult(
                    platform=self.platform,
                    identifier=identifier,
                    found=bool(data),
                    data=data,
                )

            def _build_url(self, identifier: str) -> str:
                # TODO: build target URL from identifier
                import urllib.parse
                return f"{url}/search?q={{urllib.parse.quote(identifier)}}"

            def _extract(self, html: str) -> dict:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "lxml")
                data = {{}}
                selectors = {{
        {sel_lines}
                }}
                for field, sel in selectors.items():
                    el = soup.select_one(sel)
                    if el:
                        data[field] = el.get_text(strip=True)
                return data
        """)

    return textwrap.dedent(f"""\
        \"\"\"
        Auto-generated crawler for {url}
        Category: {category}
        Data types: {", ".join(data_types) or "unknown"}
        Reliability tier: {reliability_tier}
        Generated by Lycan Open Discovery Engine.
        \"\"\"

        from modules.crawlers.registry import register
        from modules.crawlers.result import CrawlerResult
        from {base_import} import {base_class}


        @register("{netloc}")
        class {class_name}({base_class}):
            platform = "{netloc}"
            base_url = "{url}"
            reliability = {_tier_to_float(reliability_tier)}

        {textwrap.indent(scrape_body.strip(), "    ")}
    """)


def _to_pascal(snake: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[_\-\s]+", snake) if w)


def _tier_to_float(tier: str) -> float:
    return {"A": 0.95, "B": 0.8, "C": 0.65, "D": 0.5, "E": 0.35, "F": 0.2}.get(
        (tier or "C").upper(), 0.65
    )
