"""
adverse_media_search.py — Adverse media and criminal record search.

Aggregates negative news and legal records from:
1. Google News RSS  — https://news.google.com/rss/search?q="NAME"+fraud|corruption|...
2. GDELT Document API — https://api.gdeltproject.org/api/v2/doc/doc
3. CourtListener case search — https://www.courtlistener.com/api/rest/v3/search/
4. ProPublica Nonprofit Explorer — https://projects.propublica.org/nonprofits/api/v2/search

Scores severity: critical (terrorism, murder) → high (fraud, corruption,
money laundering) → medium (civil suits, regulatory) → low (minor violations).

Registered as "adverse_media_search".
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

# --- Source URLs ---
_GNEWS_RSS = 'https://news.google.com/rss/search?q="{query}"+{terms}&hl=en-US&gl=US&ceid=US:en'
_ADVERSE_TERMS = (
    "fraud|corruption|arrested|indicted|convicted|bribery|laundering|sanctions|terrorist"
)

_GDELT_API = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query={query}&mode=ArtList&maxrecords=50&format=json&sort=DateDesc"
)
_COURTLISTENER_SEARCH = (
    "https://www.courtlistener.com/api/rest/v3/search/"
    "?q={query}&type=o&order_by=score+desc&stat_Precedential=on"
)
_PROPUBLICA_NP = "https://projects.propublica.org/nonprofits/api/v2/search.json?q={query}"

# --- Severity classification ---
_SEVERITY_CRITICAL = {
    "terrorism",
    "terrorist",
    "murder",
    "homicide",
    "genocide",
    "war crime",
    "mass shooting",
    "bomb",
    "explosive",
}
_SEVERITY_HIGH = {
    "fraud",
    "corruption",
    "money laundering",
    "bribery",
    "embezzlement",
    "indicted",
    "convicted",
    "arrested",
    "criminal",
    "racketeering",
    "cartel",
    "drug trafficking",
    "human trafficking",
    "sanctions",
    "ponzi",
    "insider trading",
    "wire fraud",
    "bank fraud",
}
_SEVERITY_MEDIUM = {
    "lawsuit",
    "civil suit",
    "regulatory",
    "fine",
    "penalty",
    "violation",
    "sec investigation",
    "doj",
    "fbi",
    "investigation",
    "probe",
    "alleged",
    "misconduct",
    "breach",
    "negligence",
    "whistleblower",
}
_SEVERITY_LOW = {
    "complaint",
    "minor",
    "dispute",
    "arbitration",
    "settlement",
    "controversy",
    "criticism",
}


def _score_severity(text: str) -> tuple[str, float]:
    """
    Return (severity_label, numeric_score) for a piece of text.
    numeric_score: critical=1.0, high=0.75, medium=0.5, low=0.25
    """
    lower = text.lower()
    if any(kw in lower for kw in _SEVERITY_CRITICAL):
        return "critical", 1.0
    if any(kw in lower for kw in _SEVERITY_HIGH):
        return "high", 0.75
    if any(kw in lower for kw in _SEVERITY_MEDIUM):
        return "medium", 0.5
    if any(kw in lower for kw in _SEVERITY_LOW):
        return "low", 0.25
    return "low", 0.1


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _parse_gnews_rss(xml_text: str) -> list[dict[str, Any]]:
    """Parse Google News RSS feed XML into article records."""
    articles: list[dict[str, Any]] = []
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return articles
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            description = (item.findtext("description") or "").strip()
            # Strip HTML tags from description
            description = re.sub(r"<[^>]+>", " ", description).strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            source_el = item.find("source")
            source_name = source_el.text.strip() if source_el is not None and source_el.text else ""

            combined_text = f"{title} {description}"
            severity, score = _score_severity(combined_text)

            articles.append(
                {
                    "headline": title,
                    "summary": description[:500],
                    "url": link,
                    "url_hash": _url_hash(link),
                    "publication_date": pub_date,
                    "source_name": source_name,
                    "source_country": "US",
                    "category": "news",
                    "severity": severity,
                    "sentiment_score": round(-score, 3),  # negative = adverse
                    "data_source": "google_news_rss",
                }
            )
    except Exception as exc:
        logger.debug("Google News RSS parse error: %s", exc)
    return articles


def _parse_gdelt(data: Any) -> list[dict[str, Any]]:
    """Parse GDELT ArtList API JSON response."""
    articles: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return articles
    for art in data.get("articles", []):
        if not isinstance(art, dict):
            continue
        url = art.get("url", "")
        title = art.get("title", "")
        summary = art.get("seendates", {}) or ""
        if isinstance(summary, dict):
            summary = str(summary)
        pub_date = art.get("seendate", "") or art.get("crawldate", "")
        source_name = art.get("domain", "")
        source_country = art.get("sourcecountry", "")

        severity, score = _score_severity(title)
        articles.append(
            {
                "headline": title,
                "summary": str(summary)[:500],
                "url": url,
                "url_hash": _url_hash(url),
                "publication_date": str(pub_date),
                "source_name": source_name,
                "source_country": source_country,
                "category": "news",
                "severity": severity,
                "sentiment_score": round(-score, 3),
                "data_source": "gdelt",
            }
        )
    return articles


def _parse_courtlistener(data: dict) -> list[dict[str, Any]]:
    """Parse CourtListener search API response."""
    articles: list[dict[str, Any]] = []
    for result in data.get("results", []):
        if not isinstance(result, dict):
            continue
        case_name = result.get("caseName", "")
        court = result.get("court_id", "")
        date_filed = result.get("dateFiled", "")
        url = result.get("absolute_url", "")
        if url and not url.startswith("http"):
            url = f"https://www.courtlistener.com{url}"
        snippet = result.get("snippet", "")

        severity, score = _score_severity(f"{case_name} {snippet}")
        articles.append(
            {
                "headline": case_name,
                "summary": snippet[:500],
                "url": url,
                "url_hash": _url_hash(url),
                "publication_date": date_filed,
                "source_name": f"CourtListener ({court})",
                "source_country": "US",
                "category": "court_record",
                "severity": severity,
                "sentiment_score": round(-score, 3),
                "data_source": "courtlistener",
            }
        )
    return articles


def _parse_propublica(data: dict, query: str) -> list[dict[str, Any]]:
    """
    Parse ProPublica Nonprofit Explorer search results.
    Returns organisation connections — not adverse media per se, but
    useful for identifying shell orgs and charitable front connections.
    """
    articles: list[dict[str, Any]] = []
    for org in data.get("organizations", [])[:10]:
        if not isinstance(org, dict):
            continue
        name = org.get("name", "")
        ntee = org.get("ntee_code", "")
        state = org.get("state", "")
        url = f"https://projects.propublica.org/nonprofits/organizations/{org.get('ein', '')}"
        articles.append(
            {
                "headline": f"Nonprofit connection: {name}",
                "summary": f"EIN: {org.get('ein', '')} | NTEE: {ntee} | State: {state}",
                "url": url,
                "url_hash": _url_hash(url),
                "publication_date": str(org.get("updated", "")),
                "source_name": "ProPublica Nonprofit Explorer",
                "source_country": "US",
                "category": "nonprofit_connection",
                "severity": "low",
                "sentiment_score": 0.0,
                "data_source": "propublica_nonprofit",
            }
        )
    return articles


@register("adverse_media_search")
class AdverseMediaSearchCrawler(HttpxCrawler):
    """
    Searches news, courts, and public records for adverse media on a person.

    Aggregates: Google News RSS, GDELT, CourtListener, ProPublica.
    Scores each result by severity (critical/high/medium/low).

    identifier: person full name, optionally with org "John Smith | Acme Corp"

    Data keys returned:
        adverse_media       — list of {headline, summary, url, url_hash,
                              publication_date, source_name, source_country,
                              category, severity, sentiment_score, data_source}
        adverse_media_score — float 0-1 (highest severity normalised)
        adverse_media_count — integer total articles found
        query               — normalised name query
    """

    platform = "adverse_media_search"
    source_reliability = 0.75
    requires_tor = False
    proxy_tier = "datacenter"

    async def scrape(self, identifier: str) -> CrawlerResult:
        # Parse optional org hint: "John Smith | Acme Corp"
        parts = identifier.split("|", 1)
        name = parts[0].strip()
        org_hint = parts[1].strip() if len(parts) > 1 else ""

        search_query = f"{name} {org_hint}".strip() if org_hint else name
        encoded = quote_plus(search_query)
        encoded_name = quote_plus(f'"{name}"')

        all_articles: list[dict[str, Any]] = []

        gnews = await self._search_gnews(encoded_name)
        all_articles.extend(gnews)

        gdelt = await self._search_gdelt(encoded)
        all_articles.extend(gdelt)

        court = await self._search_courtlistener(encoded)
        all_articles.extend(court)

        np_articles = await self._search_propublica(encoded, name)
        all_articles.extend(np_articles)

        # Deduplicate by url_hash
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for art in all_articles:
            h = art.get("url_hash", "")
            if h and h not in seen:
                seen.add(h)
                deduped.append(art)

        # Compute overall adverse media score (max severity found, normalised)
        severity_map = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
        scores = [severity_map.get(a.get("severity", "low"), 0.1) for a in deduped]
        adverse_score = max(scores) if scores else 0.0

        return self._result(
            identifier,
            found=len(deduped) > 0,
            adverse_media=deduped,
            adverse_media_score=round(adverse_score, 3),
            adverse_media_count=len(deduped),
            query=search_query,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _search_gnews(self, encoded_name: str) -> list[dict[str, Any]]:
        url = _GNEWS_RSS.format(query=encoded_name, terms=_ADVERSE_TERMS)
        resp = await self.get(url, headers={"Accept": "application/rss+xml, application/xml"})
        if resp is None or resp.status_code != 200:
            logger.debug("Google News RSS returned %s", resp.status_code if resp else "None")
            return []
        return _parse_gnews_rss(resp.text)

    async def _search_gdelt(self, encoded: str) -> list[dict[str, Any]]:
        url = _GDELT_API.format(query=encoded)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is None or resp.status_code != 200:
            return []
        try:
            return _parse_gdelt(resp.json())
        except Exception as exc:
            logger.debug("GDELT parse error: %s", exc)
            return []

    async def _search_courtlistener(self, encoded: str) -> list[dict[str, Any]]:
        url = _COURTLISTENER_SEARCH.format(query=encoded)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is None or resp.status_code != 200:
            return []
        try:
            return _parse_courtlistener(resp.json())
        except Exception as exc:
            logger.debug("CourtListener parse error: %s", exc)
            return []

    async def _search_propublica(self, encoded: str, name: str) -> list[dict[str, Any]]:
        url = _PROPUBLICA_NP.format(query=encoded)
        resp = await self.get(url, headers={"Accept": "application/json"})
        if resp is None or resp.status_code != 200:
            return []
        try:
            return _parse_propublica(resp.json(), name)
        except Exception as exc:
            logger.debug("ProPublica parse error: %s", exc)
            return []
