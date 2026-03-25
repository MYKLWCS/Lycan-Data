from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult
from shared.constants import BURNER_CARRIERS, LineType
from shared.tor import TorInstance
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)


def parse_phone_parts(phone: str) -> dict:
    """Extract area_code, exchange, last4, e164, country_code from E.164 or plain number."""
    digits = re.sub(r"\D", "", phone)
    if phone.startswith("+1") or (len(digits) == 11 and digits[0] == "1"):
        national = digits[-10:]
        return {
            "area_code": national[:3],
            "exchange": national[3:6],
            "last4": national[6:],
            "e164": f"+1{national}",
            "country_code": "US",
        }
    return {
        "area_code": digits[:3] if len(digits) >= 10 else digits,
        "exchange": digits[3:6] if len(digits) >= 10 else "",
        "last4": digits[6:10] if len(digits) >= 10 else "",
        "e164": f"+{digits}",
        "country_code": "INTL",
    }


def _detect_line_type(text: str) -> LineType:
    """Infer LineType from carrier lookup response text."""
    lower = text.lower()
    if "voip" in lower:
        return LineType.VOIP
    if "mobile" in lower or "wireless" in lower or "cellular" in lower:
        return LineType.MOBILE
    if "landline" in lower or "land line" in lower or "wireline" in lower:
        return LineType.LANDLINE
    if "prepaid" in lower or "pre-paid" in lower:
        return LineType.PREPAID
    if "toll" in lower and "free" in lower:
        return LineType.TOLL_FREE
    return LineType.UNKNOWN


def _is_burner_carrier(carrier_name: str) -> bool:
    """Return True if carrier name contains a known burner/VoIP provider substring."""
    lower = carrier_name.lower()
    return any(burner in lower for burner in BURNER_CARRIERS)


@register("phone_carrier")
class CarrierLookupCrawler(HttpxCrawler):
    """Enriches a phone number via carrierlookup.com — returns carrier, line type, burner flag."""

    platform = "phone_carrier"
    category = CrawlerCategory.PHONE_EMAIL
    rate_limit = RateLimit(requests_per_second=0.5, burst_size=3, cooldown_seconds=1.0)
    source_reliability = 0.65
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        parts = parse_phone_parts(identifier)
        country_code = parts["country_code"]

        if country_code == "US":
            url = (
                f"https://www.carrierlookup.com/index.php"
                f"?npa={parts['area_code']}&nxx={parts['exchange']}"
            )
        else:
            e164_digits = re.sub(r"\D", "", parts["e164"])
            url = f"https://www.carrierlookup.com/index.php?number={e164_digits}"

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

        carrier_name, line_type = self._parse_response(response.text)

        if not carrier_name:
            return CrawlerResult(
                platform=self.platform,
                identifier=identifier,
                found=False,
                error="no_carrier_data",
                source_reliability=self.source_reliability,
            )

        is_voip = line_type == LineType.VOIP
        is_burner = _is_burner_carrier(carrier_name) or is_voip

        return self._result(
            identifier,
            found=True,
            carrier_name=carrier_name,
            line_type=line_type.value,
            is_voip=is_voip,
            is_burner=is_burner,
            country_code=country_code,
        )

    def _parse_response(self, html: str) -> tuple[str, LineType]:
        """Parse carrier name and line type from carrierlookup.com HTML."""
        soup = BeautifulSoup(html, "html.parser")
        carrier_name = ""
        line_type = LineType.UNKNOWN

        # Common patterns: table cells, divs with "carrier" label
        for tag in soup.find_all(["td", "div", "span", "p"]):
            text = tag.get_text(strip=True)

            # Look for carrier label followed by value
            if re.search(r"carrier|provider|company", text, re.IGNORECASE):
                # Try next sibling
                sibling = tag.find_next_sibling()
                if sibling:
                    val = sibling.get_text(strip=True)
                    if val and len(val) > 2:
                        carrier_name = val
                        break
                # Try parent's next td
                parent = tag.parent
                if parent:  # pragma: no branch
                    tds = parent.find_all(["td", "span"])
                    if len(tds) >= 2:
                        carrier_name = tds[-1].get_text(strip=True)
                        break

        # Fallback: look for a result container
        if not carrier_name:
            result_div = soup.find(class_=re.compile(r"result|carrier|lookup", re.I))
            if result_div:
                carrier_name = result_div.get_text(strip=True)[:80]

        # Detect line type from full page text
        line_type = _detect_line_type(html)

        return carrier_name.strip(), line_type
