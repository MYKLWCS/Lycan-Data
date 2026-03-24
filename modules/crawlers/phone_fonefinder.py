from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.phone_carrier import _detect_line_type, parse_phone_parts
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.constants import LineType
from shared.tor import TorInstance

logger = logging.getLogger(__name__)

# US state abbreviation set for basic city/state detection
_US_STATES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}


def _parse_city_state(text: str) -> tuple[str, str]:
    """Extract city and state from a string like 'Austin, TX' or 'AUSTIN TX'."""
    text = text.strip()
    # Pattern: City, ST  or  City ST
    match = re.search(r"([A-Za-z\s]+),?\s+([A-Z]{2})\b", text)
    if match:
        city = match.group(1).strip().title()
        state = match.group(2).upper()
        if state in _US_STATES:
            return city, state
    return "", ""


@register("phone_fonefinder")
class FoneFinderCrawler(HttpxCrawler):
    """Enriches a US phone number via fonefinder.net — carrier, city, state, line type."""

    platform = "phone_fonefinder"
    source_reliability = 0.60
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        parts = parse_phone_parts(identifier)

        url = (
            f"https://www.fonefinder.net/findome.php"
            f"?npa={parts['area_code']}&nxx={parts['exchange']}&thoublock={parts['last4']}"
        )

        response = await self.get(url)

        if response is None:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="http_error",
                source_reliability=self.source_reliability,
            )

        if response.status_code == 404:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="not_found",
                source_reliability=self.source_reliability,
            )

        if response.status_code != 200:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error=f"http_{response.status_code}",
                source_reliability=self.source_reliability,
            )

        data = self._parse_response(response.text, parts["country_code"])

        if not data.get("carrier_name"):
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="no_data",
                source_reliability=self.source_reliability,
            )

        return self._result(identifier, found=True, **data)

    def _parse_response(self, html: str, country_code: str) -> dict:
        """Parse carrier, location, line type from fonefinder HTML."""
        soup = BeautifulSoup(html, "html.parser")
        result: dict = {
            "carrier_name": "",
            "city": "",
            "state": "",
            "line_type": LineType.UNKNOWN.value,
            "country_code": country_code,
        }

        # Fonefinder renders results in a table — walk all rows
        rows = soup.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True).lower()
            value = cells[-1].get_text(strip=True)

            if not value:
                continue

            if "carrier" in label or "company" in label or "provider" in label:
                result["carrier_name"] = value
            elif "city" in label or "location" in label or "city/state" in label:
                city, state = _parse_city_state(value)
                if city:
                    result["city"] = city
                if state:
                    result["state"] = state
            elif "state" in label:
                result["state"] = value.strip().upper()[:2]

        # Fallback: scan all divs / paragraphs for carrier clues
        if not result["carrier_name"]:
            for tag in soup.find_all(["div", "p", "span"]):
                text = tag.get_text(strip=True)
                if re.search(r"carrier|provider|company", text, re.IGNORECASE):
                    sibling = tag.find_next_sibling()
                    if sibling:
                        val = sibling.get_text(strip=True)
                        if val and len(val) > 2:
                            result["carrier_name"] = val
                            break

        # City/state fallback from free text
        if not result["city"]:
            full_text = soup.get_text(" ")
            city, state = _parse_city_state(full_text)
            if city:
                result["city"] = city
            if state:
                result["state"] = state

        # Line type from page text
        result["line_type"] = _detect_line_type(html).value

        return result
