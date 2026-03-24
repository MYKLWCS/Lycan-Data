"""
public_voter.py — Voter registration lookup (Michigan public portal).

Michigan's voter information portal is publicly accessible and returns
JSON registration status. This crawler submits a name + birth date query
to the Michigan Voter Information Center.

Portal: https://mvic.sos.state.mi.us/Voter/SearchByName (POST, JSON response)

Registered as "public_voter".

identifier format options:
  "First Last"                         → name only (birth info unknown)
  "First Last|MM|YYYY"                 → name + birth month + year
  "First Last|MM|YYYY|city"            → name + birth + city filter
"""
from __future__ import annotations

import logging
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://mvic.sos.state.mi.us/Voter/SearchByName"

_HEADERS = {
    "Content-Type":  "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer":       "https://mvic.sos.state.mi.us/",
    "Origin":        "https://mvic.sos.state.mi.us",
    "Accept":        "application/json, text/javascript, */*",
}


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------

def _parse_identifier(identifier: str) -> dict[str, str]:
    """
    Parse the composite identifier into name + birth components.

    Supported formats:
        "John Smith"              → {first: "John", last: "Smith", month: "", year: ""}
        "John Smith|03|1985"      → adds birthMonth=03, birthYear=1985
        "John Smith|03|1985|Troy" → adds city="Troy"
    """
    parts = identifier.split("|")
    name_part = parts[0].strip()
    name_words = name_part.split()

    first = name_words[0] if name_words else ""
    last  = " ".join(name_words[1:]) if len(name_words) > 1 else ""

    month = parts[1].strip() if len(parts) > 1 else ""
    year  = parts[2].strip() if len(parts) > 2 else ""
    city  = parts[3].strip() if len(parts) > 3 else ""

    return {"first": first, "last": last, "month": month, "year": year, "city": city}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_voter_response(data: Any) -> dict[str, Any]:
    """
    Normalise the Michigan MVIC JSON response.

    The portal returns HTML fragments embedded in a JSON envelope, or a
    simple status dict. We handle both.
    """
    result: dict[str, Any] = {
        "registered": False,
        "state":      "MI",
        "county":     None,
        "jurisdiction": None,
        "status":     None,
    }

    if not isinstance(data, dict):
        return result

    # Direct JSON shape (newer API)
    if "Registered" in data:
        result["registered"] = bool(data.get("Registered"))
        result["county"]     = data.get("CountyName") or data.get("county")
        result["jurisdiction"] = data.get("JurisdictionName") or data.get("jurisdiction")
        result["status"]     = data.get("VoterStatus") or data.get("status")
        return result

    # HTML-in-JSON shape — look for registration cues
    html_fragment = " ".join(str(v) for v in data.values())
    lower = html_fragment.lower()
    if "you are registered" in lower or "registered to vote" in lower:
        result["registered"] = True

    import re
    county_m = re.search(r'county[:\s]+([A-Za-z\s]+)', html_fragment, re.I)
    if county_m:
        result["county"] = county_m.group(1).strip()

    return result


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

@register("public_voter")
class PublicVoterCrawler(HttpxCrawler):
    """
    Queries the Michigan MVIC portal for voter registration status.

    identifier: "First Last" or "First Last|MM|YYYY" or "First Last|MM|YYYY|city"

    Data keys returned:
        registered   — bool
        state        — "MI"
        county       — string or None
        jurisdiction — string or None
        status       — string or None
        query        — original identifier
    """

    platform = "public_voter"
    source_reliability = 0.85
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        parsed = _parse_identifier(query)

        form_data = {
            "firstName":   parsed["first"],
            "lastName":    parsed["last"],
            "birthMonth":  parsed["month"],
            "birthYear":   parsed["year"],
            "addressLine": "",
            "unitNumber":  "",
            "city":        parsed["city"],
            "zipCode":     "",
        }

        response = await self.post(
            _SEARCH_URL,
            data=form_data,
            headers=_HEADERS,
        )

        if response is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                registered=False,
                state="MI",
                county=None,
                jurisdiction=None,
                status=None,
                query=query,
            )

        if response.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{response.status_code}",
                registered=False,
                state="MI",
                county=None,
                jurisdiction=None,
                status=None,
                query=query,
            )

        try:
            data = response.json()
        except Exception as exc:
            logger.warning("Voter: JSON parse error: %s", exc)
            return self._result(
                identifier,
                found=False,
                error="json_parse_error",
                registered=False,
                state="MI",
                county=None,
                jurisdiction=None,
                status=None,
                query=query,
            )

        voter_info = _parse_voter_response(data)

        return self._result(
            identifier,
            found=voter_info.get("registered", False),
            query=query,
            **voter_info,
        )
