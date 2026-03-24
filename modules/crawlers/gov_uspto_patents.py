"""
gov_uspto_patents.py — USPTO PatentsView patent search.

Searches the PatentsView API for patents by inventor last name or
assignee/company name. No authentication required.
Registered as "gov_uspto_patents".
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_BASE = "https://search.patentsview.org/api/v1/patent/"

_FIELDS = json.dumps(
    [
        "patent_id",
        "patent_title",
        "patent_date",
        "assignee_organization",
    ]
)

_OPTIONS = json.dumps({"per_page": 10})


def _build_inventor_url(last_name: str) -> str:
    query = json.dumps({"_contains": {"inventor_last_name": last_name}})
    return f"{_BASE}?q={quote(query)}&f={quote(_FIELDS)}&o={quote(_OPTIONS)}"


def _build_assignee_url(org_name: str) -> str:
    query = json.dumps({"_contains": {"assignee_organization": org_name}})
    return f"{_BASE}?q={quote(query)}&f={quote(_FIELDS)}&o={quote(_OPTIONS)}"


def _parse_patents(payload: dict) -> tuple[list[dict[str, Any]], int]:
    """Return (patents, total_count) from PatentsView response."""
    patents: list[dict[str, Any]] = []
    for item in payload.get("patents") or []:
        # assignee_organization may be a list of dicts or a single value
        assignee_raw = item.get("assignee_organization")
        if isinstance(assignee_raw, list):
            assignees = [
                a.get("assignee_organization", "") if isinstance(a, dict) else str(a)
                for a in assignee_raw
            ]
            assignee_str = ", ".join(filter(None, assignees))
        else:
            assignee_str = assignee_raw or ""

        patents.append(
            {
                "patent_id": item.get("patent_id", ""),
                "patent_title": item.get("patent_title", ""),
                "patent_date": item.get("patent_date", ""),
                "assignee_organization": assignee_str,
            }
        )
    total = payload.get("total_patent_count", len(patents))
    return patents, total


@register("gov_uspto_patents")
class GovUsptoPatentsCrawler(HttpxCrawler):
    """
    Searches PatentsView (USPTO) for patents by inventor name or company.

    identifier: inventor name or company/assignee name.

    Data keys returned:
        patents     — list of patent records (up to 10)
        total       — total matching patents
    """

    platform = "gov_uspto_patents"
    source_reliability = 0.99
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        # Derive last name for inventor search: take the last token
        parts = query.split()
        last_name = parts[-1] if parts else query

        # Try inventor search first
        inventor_url = _build_inventor_url(last_name)
        resp = await self.get(inventor_url)

        patents: list[dict[str, Any]] = []
        total = 0

        if resp is not None and resp.status_code == 200:
            try:
                payload = resp.json()
                patents, total = _parse_patents(payload)
            except Exception as exc:
                logger.warning("PatentsView inventor parse error: %s", exc)

        # If no results, try assignee/company search
        if not patents:
            assignee_url = _build_assignee_url(query)
            resp2 = await self.get(assignee_url)
            if resp2 is not None and resp2.status_code == 200:
                try:
                    payload2 = resp2.json()
                    patents, total = _parse_patents(payload2)
                except Exception as exc:
                    logger.warning("PatentsView assignee parse error: %s", exc)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                patents=[],
                total=0,
            )

        return self._result(
            identifier,
            found=len(patents) > 0,
            patents=patents,
            total=total,
        )
