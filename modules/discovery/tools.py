"""
Open Discovery Engine — tool runners.

Each class wraps one OSINT tool and returns DiscoveryHit objects.

Tools:
  SpiderFootTool      — automated recon via SpiderFoot REST API
  AmassTool           — subdomain / CT log enumeration
  TheHarvesterTool    — email / DNS harvesting
  SherlockTool        — username enumeration (600+ platforms)
  MaigretTool         — cross-platform username search
  GoogleDorkTool      — search-engine dorking via DuckDuckGo
  CrtShTool           — certificate transparency log mining
  CommonCrawlTool     — historical web snapshot search
  WaybackTool         — Wayback Machine archive search
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from datetime import datetime

import httpx

from modules.discovery.base import BaseDiscoveryTool, DiscoveryHit

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(30.0)


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True)


# ── SpiderFoot ────────────────────────────────────────────────────────────────

class SpiderFootTool(BaseDiscoveryTool):
    """Calls a running SpiderFoot REST server (default: http://localhost:5001)."""

    tool_name = "SpiderFoot"
    timeout = 300

    def __init__(self, base_url: str = "http://localhost:5001") -> None:
        self.base_url = base_url.rstrip("/")

    async def run(self, query: str) -> list[DiscoveryHit]:
        import asyncio
        hits: list[DiscoveryHit] = []
        try:
            async with _http() as client:
                scan_name = f"lycan_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                resp = await client.post(
                    f"{self.base_url}/startscan",
                    data={
                        "scanname": scan_name,
                        "scantarget": query,
                        "modulelist": "sfp_dnsresolve,sfp_ssl,sfp_whois,sfp_pgp,sfp_web_analytics",
                        "typelist": "",
                        "usecase": "Investigate",
                    },
                )
                if resp.status_code != 200:
                    return hits
                scan_id = resp.text.strip().strip('"')

                for _ in range(60):
                    await asyncio.sleep(5)
                    st = await client.get(f"{self.base_url}/scanstatus/{scan_id}")
                    if st.status_code == 200 and st.json().get("status") in (
                        "FINISHED", "ABORTED", "ERROR-FAILED"
                    ):
                        break

                res = await client.get(
                    f"{self.base_url}/scaneventresultsunique/{scan_id}/URL_FORM"
                )
                if res.status_code == 200:
                    for row in res.json():
                        url = row[1] if isinstance(row, list) and len(row) > 1 else str(row)
                        if url.startswith("http"):
                            hits.append(DiscoveryHit(
                                name=urllib.parse.urlparse(url).netloc,
                                url=url,
                                discovered_by=self.tool_name,
                                discovery_query=query,
                                category="web_form",
                                data_quality_estimate=0.6,
                                legal_risk="low",
                                raw_context={"scan_id": scan_id},
                            ))
        except Exception as exc:
            logger.debug("SpiderFoot run failed: %s", exc)
        return hits


# ── Amass ──────────────────────────────────────────────────────────────────────

class AmassTool(BaseDiscoveryTool):
    """Runs `amass enum -passive` against the query domain."""

    tool_name = "Amass"
    timeout = 180

    async def run(self, query: str) -> list[DiscoveryHit]:
        domain = _extract_domain(query)
        if not domain:
            return []

        stdout, _ = await self._exec([
            "amass", "enum", "-passive", "-d", domain,
        ])

        hits: list[DiscoveryHit] = []
        for line in stdout.splitlines():
            line = line.strip()
            if line and "." in line and " " not in line:
                hits.append(DiscoveryHit(
                    name=line,
                    url=f"https://{line}",
                    discovered_by=self.tool_name,
                    discovery_query=query,
                    category="subdomain",
                    data_quality_estimate=0.7,
                    legal_risk="low",
                    data_types=["subdomain", "dns"],
                    raw_context={"raw_line": line},
                ))
        return hits


# ── theHarvester ───────────────────────────────────────────────────────────────

class TheHarvesterTool(BaseDiscoveryTool):
    """Runs theHarvester to collect emails, URLs, and IPs."""

    tool_name = "theHarvester"
    timeout = 120

    async def run(self, query: str) -> list[DiscoveryHit]:
        domain = _extract_domain(query) or query
        stdout, _ = await self._exec([
            "theHarvester", "-d", domain,
            "-b", "google,bing,duckduckgo,crtsh",
            "-l", "200",
        ])

        hits: list[DiscoveryHit] = []
        emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", stdout)
        for email in set(emails):
            em_domain = email.split("@")[-1]
            hits.append(DiscoveryHit(
                name=f"Email source: {em_domain}",
                url=f"https://{em_domain}",
                discovered_by=self.tool_name,
                discovery_query=query,
                category="email_source",
                data_quality_estimate=0.65,
                legal_risk="low",
                data_types=["email"],
                raw_context={"email": email},
            ))

        urls = re.findall(r"https?://[^\s\"'<>]+", stdout)
        for url in set(urls):
            parsed = urllib.parse.urlparse(url)
            hits.append(DiscoveryHit(
                name=parsed.netloc,
                url=url,
                discovered_by=self.tool_name,
                discovery_query=query,
                category=_categorise_url(url),
                data_quality_estimate=0.55,
                legal_risk="low",
                data_types=["url"],
                raw_context={"raw_url": url},
            ))
        return hits


# ── Sherlock ───────────────────────────────────────────────────────────────────

class SherlockTool(BaseDiscoveryTool):
    """Runs sherlock to find accounts across 600+ platforms."""

    tool_name = "Sherlock"
    timeout = 180

    async def run(self, query: str) -> list[DiscoveryHit]:
        username = query.strip().split()[0] if query.strip() else query
        stdout, _ = await self._exec([
            "sherlock", username, "--print-found", "--no-color",
        ])

        hits: list[DiscoveryHit] = []
        for line in stdout.splitlines():
            m = re.match(r"\[\+\]\s+(.+?):\s+(https?://\S+)", line)
            if m:
                platform, url = m.group(1).strip(), m.group(2).strip()
                hits.append(DiscoveryHit(
                    name=f"{platform} — @{username}",
                    url=url,
                    discovered_by=self.tool_name,
                    discovery_query=query,
                    category="social",
                    data_quality_estimate=0.75,
                    legal_risk="low",
                    data_types=["username", "social_profile"],
                    raw_context={"platform": platform, "username": username},
                ))
        return hits


# ── Maigret ────────────────────────────────────────────────────────────────────

class MaigretTool(BaseDiscoveryTool):
    """Runs maigret for deeper cross-platform username search."""

    tool_name = "Maigret"
    timeout = 240

    async def run(self, query: str) -> list[DiscoveryHit]:
        username = query.strip().split()[0] if query.strip() else query
        stdout, _ = await self._exec([
            "maigret", username, "--no-color",
        ])

        hits: list[DiscoveryHit] = []
        for line in stdout.splitlines():
            m = re.search(r"\[.\]\s+(.+?)\s+(https?://\S+)", line)
            if m and "+" in line:
                site, url = m.group(1).strip(), m.group(2).strip()
                hits.append(DiscoveryHit(
                    name=f"{site} — @{username}",
                    url=url,
                    discovered_by=self.tool_name,
                    discovery_query=query,
                    category="social",
                    data_quality_estimate=0.75,
                    legal_risk="low",
                    data_types=["username", "social_profile"],
                    raw_context={"site": site, "username": username},
                ))
        return hits


# ── Google Dorking ─────────────────────────────────────────────────────────────

class GoogleDorkTool(BaseDiscoveryTool):
    """
    Issues Google dork queries via DuckDuckGo HTML search.
    No API key required.
    """

    tool_name = "GoogleDork"

    DORK_TEMPLATES = [
        'site:linkedin.com/in/ "{q}"',
        '"{q}" email OR phone OR address',
        'site:pacer.gov "{q}"',
        'intext:"{q}" filetype:pdf',
        '"{q}" site:facebook.com OR site:instagram.com OR site:twitter.com',
        '"{q}" criminal OR arrest OR lawsuit OR court',
    ]

    async def run(self, query: str) -> list[DiscoveryHit]:
        hits: list[DiscoveryHit] = []
        seen_urls: set[str] = set()

        async with _http() as client:
            for template in self.DORK_TEMPLATES:
                dork = template.replace("{q}", query)
                try:
                    resp = await client.get(
                        "https://duckduckgo.com/html/",
                        params={"q": dork},
                        headers={
                            "User-Agent": (
                                "Mozilla/5.0 (X11; Linux x86_64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/120.0 Safari/537.36"
                            )
                        },
                    )
                    urls = re.findall(r'href="(https?://[^"&]+)"', resp.text)
                    for url in urls:
                        if url in seen_urls:
                            continue
                        parsed = urllib.parse.urlparse(url)
                        netloc = parsed.netloc
                        if "duckduckgo" in netloc:
                            continue
                        seen_urls.add(url)
                        hits.append(DiscoveryHit(
                            name=netloc,
                            url=url,
                            discovered_by=self.tool_name,
                            discovery_query=dork,
                            category=_categorise_url(url),
                            data_quality_estimate=0.55,
                            legal_risk="low",
                            raw_context={"dork": dork},
                        ))
                except Exception as exc:
                    logger.debug("GoogleDork failed for %r: %s", dork, exc)

        return hits


# ── crt.sh ─────────────────────────────────────────────────────────────────────

class CrtShTool(BaseDiscoveryTool):
    """Queries crt.sh for SSL/TLS certificates."""

    tool_name = "crt.sh"

    async def run(self, query: str) -> list[DiscoveryHit]:
        domain = _extract_domain(query) or query
        hits: list[DiscoveryHit] = []

        try:
            async with _http() as client:
                resp = await client.get(
                    "https://crt.sh/",
                    params={"q": f"%.{domain}", "output": "json"},
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    return hits
                entries = resp.json()
        except Exception as exc:
            logger.debug("crt.sh failed for %r: %s", domain, exc)
            return hits

        seen: set[str] = set()
        for entry in entries[:200]:
            name_value = entry.get("name_value", "")
            for name in name_value.splitlines():
                name = name.strip().lstrip("*.")
                if not name or name in seen:
                    continue
                seen.add(name)
                hits.append(DiscoveryHit(
                    name=name,
                    url=f"https://{name}",
                    discovered_by=self.tool_name,
                    discovery_query=query,
                    category="subdomain",
                    data_quality_estimate=0.8,
                    legal_risk="low",
                    data_types=["subdomain", "ssl_certificate"],
                    raw_context={
                        "issuer": entry.get("issuer_name", ""),
                        "not_before": entry.get("not_before", ""),
                        "serial": entry.get("serial_number", ""),
                    },
                ))
        return hits


# ── Common Crawl ───────────────────────────────────────────────────────────────

class CommonCrawlTool(BaseDiscoveryTool):
    """Searches the Common Crawl CDX index for pages mentioning the query domain."""

    tool_name = "CommonCrawl"
    CDX_API = "http://index.commoncrawl.org/CC-MAIN-2024-10-index"

    async def run(self, query: str) -> list[DiscoveryHit]:
        domain = _extract_domain(query) or query
        hits: list[DiscoveryHit] = []

        try:
            async with _http() as client:
                resp = await client.get(
                    self.CDX_API,
                    params={
                        "url": f"*.{domain}/*",
                        "output": "json",
                        "limit": "100",
                        "filter": "statuscode:200",
                        "fl": "url,timestamp,mime",
                    },
                )
                if resp.status_code != 200:
                    return hits

                seen: set[str] = set()
                for line in resp.text.splitlines():
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    url = obj.get("url", "")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    parsed = urllib.parse.urlparse(url)
                    hits.append(DiscoveryHit(
                        name=parsed.netloc,
                        url=url,
                        discovered_by=self.tool_name,
                        discovery_query=query,
                        category=_categorise_url(url),
                        data_quality_estimate=0.5,
                        legal_risk="low",
                        raw_context={
                            "timestamp": obj.get("timestamp", ""),
                            "mime": obj.get("mime", ""),
                        },
                    ))
        except Exception as exc:
            logger.debug("CommonCrawl failed for %r: %s", query, exc)
        return hits


# ── Wayback Machine ────────────────────────────────────────────────────────────

class WaybackTool(BaseDiscoveryTool):
    """Queries the Wayback Machine CDX API for archived snapshots."""

    tool_name = "Wayback"

    async def run(self, query: str) -> list[DiscoveryHit]:
        domain = _extract_domain(query) or query
        hits: list[DiscoveryHit] = []

        try:
            async with _http() as client:
                resp = await client.get(
                    "http://web.archive.org/cdx/search/cdx",
                    params={
                        "url": f"*.{domain}/*",
                        "output": "json",
                        "limit": "100",
                        "filter": "statuscode:200",
                        "fl": "original,timestamp,mimetype",
                        "collapse": "urlkey",
                    },
                )
                if resp.status_code != 200:
                    return hits
                rows = resp.json()
                if not rows:
                    return hits

                header = rows[0]
                seen: set[str] = set()
                for row in rows[1:]:
                    obj = dict(zip(header, row))
                    url = obj.get("original", "")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    parsed = urllib.parse.urlparse(url)
                    hits.append(DiscoveryHit(
                        name=parsed.netloc,
                        url=url,
                        discovered_by=self.tool_name,
                        discovery_query=query,
                        category=_categorise_url(url),
                        data_quality_estimate=0.45,
                        legal_risk="low",
                        data_types=["archive"],
                        raw_context={
                            "timestamp": obj.get("timestamp", ""),
                            "mimetype": obj.get("mimetype", ""),
                            "archive_url": (
                                f"https://web.archive.org/web/"
                                f"{obj.get('timestamp', '')}/{url}"
                            ),
                        },
                    ))
        except Exception as exc:
            logger.debug("Wayback failed for %r: %s", domain, exc)
        return hits


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_domain(text: str) -> str | None:
    m = re.search(r"https?://([a-zA-Z0-9.\-]+)", text)
    if m:
        return m.group(1)
    m = re.match(r"([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", text.strip())
    if m:
        return m.group(1)
    return None


_CATEGORY_MAP = {
    "linkedin.com": "professional",
    "facebook.com": "social",
    "instagram.com": "social",
    "twitter.com": "social",
    "x.com": "social",
    "pacer.gov": "court",
    "courtlistener.com": "court",
    ".gov": "government",
    "mugshots": "criminal",
    "arrest": "criminal",
    "whitepages": "people_search",
    "spokeo": "people_search",
    "radaris": "people_search",
    "zillow": "property",
    "redfin": "property",
    "crunchbase": "business",
    "opencorporates": "business",
    "bloomberg": "business",
}


def _categorise_url(url: str) -> str:
    url_lower = url.lower()
    for key, cat in _CATEGORY_MAP.items():
        if key in url_lower:
            return cat
    return "web"


ALL_TOOLS: list[type[BaseDiscoveryTool]] = [
    AmassTool,
    TheHarvesterTool,
    SherlockTool,
    MaigretTool,
    GoogleDorkTool,
    CrtShTool,
    CommonCrawlTool,
    WaybackTool,
    SpiderFootTool,
]
