"""
public_faa.py — FAA Airmen Inquiry scraper.

Uses the FAA Airmen Inquiry portal to look up pilot certificates by name.
Submits a POST form to:
  https://amsrvs.registry.faa.gov/airmeninquiry/Main.aspx

Registered as "public_faa".

identifier: "First Last" name of the airman.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_INQUIRY_URL = "https://amsrvs.registry.faa.gov/airmeninquiry/Main.aspx"
_MAX_RESULTS = 20


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _split_name(identifier: str) -> tuple[str, str]:
    """Split "First Last" into (first, last)."""
    parts = identifier.strip().split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return "", identifier.strip()


def _parse_airmen_html(html: str) -> list[dict[str, Any]]:
    """
    Parse the FAA airmen inquiry HTML result table.

    Expected table columns (varies):
      Certificate Number | First Name | Last Name | City | State | Certificates
    """
    pilots: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            headers = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]
            if len(headers) < 3:
                continue

            # Must look like an airmen table
            header_text = " ".join(headers)
            if not any(
                kw in header_text for kw in ("certificate", "first", "last", "city", "name")
            ):
                continue

            for row in rows[1 : _MAX_RESULTS + 1]:
                cells = row.find_all("td")
                if not cells:
                    continue
                record: dict[str, str] = {}
                for i, cell in enumerate(cells):
                    key = headers[i] if i < len(headers) else f"col_{i}"
                    record[key] = cell.get_text(strip=True)

                # Normalise field names
                cert_num = (
                    record.get("certificate number")
                    or record.get("cert #")
                    or record.get("certificate #")
                    or ""
                )
                first = record.get("first name") or record.get("firstname") or ""
                last = record.get("last name") or record.get("lastname") or ""
                city = record.get("city", "")
                state = record.get("state", "")
                certs = record.get("certificates") or record.get("certificate type") or ""

                if cert_num or first or last:
                    pilots.append(
                        {
                            "certificate_number": cert_num,
                            "name": (first + " " + last).strip(),
                            "city": city,
                            "state": state,
                            "certificates": [c.strip() for c in certs.split(",") if c.strip()],
                        }
                    )
            if pilots:
                break

    except Exception as exc:
        logger.debug("FAA HTML parse error: %s", exc)

    return pilots


def _extract_viewstate(html: str) -> dict[str, str]:
    """Extract ASP.NET form hidden fields needed for POST."""
    fields: dict[str, str] = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        m = re.search(
            rf'<input[^>]+name="{re.escape(name)}"[^>]+value="([^"]*)"',
            html,
        )
        if m:
            fields[name] = m.group(1)
    return fields


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


_parse_faa_html = _parse_airmen_html  # alias


@register("public_faa")
class PublicFAACrawler(HttpxCrawler):
    """
    Queries the FAA Airmen Inquiry portal for pilot certificate records.

    identifier: full name, e.g. "John Smith"

    Data keys returned:
        pilots       — list of {certificate_number, name, city, state, certificates}
        result_count — integer
        query        — original identifier
    """

    platform = "public_faa"
    category = CrawlerCategory.PUBLIC_RECORDS
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.90
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()
        first, last = _split_name(query)

        # Step 1: GET the form to collect ViewState tokens
        get_resp = await self.get(_INQUIRY_URL)
        if get_resp is None or get_resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error="http_error_get",
                pilots=[],
                result_count=0,
                query=query,
            )

        hidden = _extract_viewstate(get_resp.text)

        # Step 2: POST the search form
        form_data = {
            **hidden,
            "ctl00$content$txtLastName": last,
            "ctl00$content$txtFirstName": first,
            "ctl00$content$btnSearch": "Search",
        }

        post_resp = await self.post(
            _INQUIRY_URL,
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if post_resp is None or post_resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error="http_error_post",
                pilots=[],
                result_count=0,
                query=query,
            )

        pilots = _parse_airmen_html(post_resp.text)

        return self._result(
            identifier,
            found=len(pilots) > 0,
            pilots=pilots,
            result_count=len(pilots),
            query=query,
        )
