"""
email_breach.py — Free multi-source email breach/leak detector.

Replaces HIBP (now paid-only) with three free sources:
  1. PSBDMP     — paste-site dump index (already used for paste search)
  2. GitHub     — code-search for email exposure in committed code
  3. LeakCheck  — public API (free tier, no key required)

Registered as "email_breach".
"""

from __future__ import annotations

import logging
import urllib.parse

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


@register("email_breach")
class EmailBreachCrawler(CurlCrawler):
    """
    Checks an email address across three free breach/leak data sources.

    Returns a unified CrawlerResult where result.data["breaches"] is a list
    of dicts — one per hit — compatible with the aggregator pipeline's
    _handle_breach_data().
    """

    platform = "email_breach"
    category = CrawlerCategory.PHONE_EMAIL
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.65
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        email = identifier.strip().lower()
        results: list[dict] = []

        # Source 1: PSBDMP (paste site dump index)
        psbdmp = await self._check_psbdmp(email)
        results.extend(psbdmp)

        # Source 2: GitHub code search (emails exposed in commits / files)
        github = await self._check_github(email)
        results.extend(github)

        # Source 3: LeakCheck.io public free API
        leakcheck = await self._check_leakcheck(email)
        results.extend(leakcheck)

        return self._result(
            identifier=email,
            found=True,  # we always attempted a check
            breaches=results,
            breach_count=len(results),
            email=email,
            checked_sources=["psbdmp", "github", "leakcheck"],
        )

    # ------------------------------------------------------------------
    # Source implementations
    # ------------------------------------------------------------------

    async def _check_psbdmp(self, email: str) -> list[dict]:
        """
        Query PSBDMP paste-site index for the email.
        Returns up to 5 paste hits as pseudo-breach records.
        """
        url = f"https://psbdmp.ws/api/v3/search/{urllib.parse.quote(email)}"
        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            logger.debug("psbdmp: no response or non-200 for %s", email)
            return []

        try:
            data = resp.json()
        except Exception:
            logger.debug("psbdmp: invalid JSON for %s", email)
            return []

        items = data if isinstance(data, list) else data.get("data", [])
        out = []
        for item in items[:5]:
            out.append(
                {
                    "name": f"psbdmp:{item.get('id', 'unknown')}",
                    "source": "psbdmp",
                    "date": None,
                    "data_classes": ["paste_dump"],
                    "preview": str(item.get("text", ""))[:200],
                }
            )
        return out

    async def _check_github(self, email: str) -> list[dict]:
        """
        Use the GitHub public code-search API to find the email in committed code.
        No authentication required; returns up to 5 hits.
        """
        url = f"https://api.github.com/search/code?q={urllib.parse.quote(email)}+in:file&per_page=5"
        resp = await self.get(
            url,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        if not resp or resp.status_code != 200:
            logger.debug(
                "github code-search: non-200 for %s (status=%s)",
                email,
                resp.status_code if resp else "no response",
            )
            return []

        try:
            items = resp.json().get("items", [])
        except Exception:
            logger.debug("github code-search: invalid JSON for %s", email)
            return []

        out = []
        for item in items:
            repo = item.get("repository", {}).get("full_name", "unknown")
            file_path = item.get("path", "")
            out.append(
                {
                    "name": f"github:{repo}:{file_path}",
                    "source": "github",
                    "date": None,
                    "data_classes": ["source_code_exposure"],
                    "repo": repo,
                    "file": file_path,
                }
            )
        return out

    async def _check_leakcheck(self, email: str) -> list[dict]:
        """
        Query the LeakCheck.io public (keyless) API.
        Free tier returns which breach databases the email appears in.
        """
        url = f"https://leakcheck.io/api/public?key=&type=email&look={urllib.parse.quote(email)}"
        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            logger.debug("leakcheck: non-200 for %s", email)
            return []

        try:
            data = resp.json()
        except Exception:
            logger.debug("leakcheck: invalid JSON for %s", email)
            return []

        if not (data.get("success") and data.get("found")):
            return []

        out = []
        for source in data.get("sources", []):
            out.append(
                {
                    "name": str(source),
                    "source": "leakcheck",
                    "date": None,
                    "data_classes": [],
                }
            )
        return out
