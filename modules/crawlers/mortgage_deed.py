"""
mortgage_deed.py — County deed and mortgage record scraper.

Scrapes publicrecordsnow.com (a free aggregator of county recorder data)
to find property deeds, mortgages, and liens associated with a person
or property address.

Registered as "mortgage_deed".

identifier: person name or property address
  e.g. "John Smith" or "123 Main St Austin TX"
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from shared.tor import TorInstance
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

_PRN_URL = "https://www.publicrecordsnow.com/search/?q={query}&type=property"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_publicrecordsnow_html(html: str) -> list[dict[str, Any]]:
    """
    Parse publicrecordsnow.com property search result HTML.

    Extracts deed/mortgage records: address, owner, deed_date,
    mortgage_amount, lender, lien_type.
    """
    records: list[dict[str, Any]] = []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # publicrecordsnow wraps each result in a card/row element
        result_blocks = soup.find_all(
            attrs={
                "class": re.compile(r"result-item|record-card|property-record|search-result", re.I)
            }
        )

        # Fallback: any <li> or <div> with address-like content
        if not result_blocks:
            result_blocks = soup.find_all("li", class_=re.compile(r"result|record|item", re.I))

        if not result_blocks:
            result_blocks = soup.find_all("div", class_=re.compile(r"result|record|property", re.I))

        for block in result_blocks[:20]:
            text = block.get_text(" ", strip=True)
            record: dict[str, Any] = {}

            # Address — look for number + street pattern
            addr_m = re.search(
                r"\d+\s+[A-Za-z0-9\s]+(?:St|Ave|Blvd|Dr|Rd|Ln|Ct|Way|Pl|Terr?|Circle|Loop)[.,\s]",
                text,
                re.I,
            )
            if addr_m:
                record["address"] = addr_m.group(0).strip().rstrip(",.")

            # Owner name
            owner_m = re.search(
                r"(?:Owner|Grantor|Grantee)[:\s]+([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)", text, re.I
            )
            if owner_m:
                record["owner"] = owner_m.group(1).strip()

            # Deed date
            date_m = re.search(
                r"(?:Deed\s+Date|Filed|Recorded)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d+,?\s+\d{4})",
                text,
                re.I,
            )
            if date_m:
                record["deed_date"] = date_m.group(1).strip()

            # Mortgage amount
            amt_m = re.search(
                r"(?:Mortgage|Loan|Amount|Lien)[:\s]+\$?([\d,]+(?:\.\d{2})?)", text, re.I
            )
            if amt_m:
                try:
                    record["mortgage_amount"] = float(amt_m.group(1).replace(",", ""))
                except ValueError:
                    record["mortgage_amount"] = amt_m.group(1)

            # Lender
            lender_m = re.search(
                r"(?:Lender|Bank|Mortgagee)[:\s]+([A-Za-z0-9\s&,\.]+?)(?:\s{2,}|\|)", text, re.I
            )
            if lender_m:
                record["lender"] = lender_m.group(1).strip()

            # Lien type
            lien_m = re.search(
                r"(?:Type|Instrument)[:\s]+(Deed of Trust|Mortgage|Warranty Deed|Quitclaim|Lien|Release)",
                text,
                re.I,
            )
            if lien_m:
                record["lien_type"] = lien_m.group(1).strip()

            if record:
                records.append(record)

        # Regex fallback if no structured blocks found
        if not records:
            for block in re.finditer(
                r"(\d+\s+\w+\s+(?:St|Ave|Blvd|Dr|Rd|Ln|Ct)[^\n<]{0,100})", html, re.I
            ):
                records.append({"address": block.group(1).strip()})
                if len(records) >= 10:
                    break

    except Exception as exc:
        logger.debug("publicrecordsnow parse error: %s", exc)

    return records


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


@register("mortgage_deed")
class MortgageDeedCrawler(HttpxCrawler):
    """
    Scrapes county deed and mortgage records from publicrecordsnow.com.

    identifier: person name or property address string.

    Data keys returned:
        query, records (list of {address, owner, deed_date, mortgage_amount, lender, lien_type}),
        result_count
    """

    platform = "mortgage_deed"
    category = CrawlerCategory.FINANCIAL
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.75
    requires_tor = True
    tor_instance = TorInstance.TOR2

    async def scrape(self, identifier: str) -> CrawlerResult:
        query = identifier.strip()

        if not query:
            return self._result(
                identifier, found=False, error="invalid_identifier", records=[], result_count=0
            )

        url = _PRN_URL.format(query=quote_plus(query))
        resp = await self.get(url)

        if resp is None:
            return self._result(
                identifier,
                found=False,
                error="http_error",
                query=query,
                records=[],
                result_count=0,
            )

        if resp.status_code != 200:
            return self._result(
                identifier,
                found=False,
                error=f"http_{resp.status_code}",
                query=query,
                records=[],
                result_count=0,
            )

        records = _parse_publicrecordsnow_html(resp.text)

        return self._result(
            identifier,
            found=len(records) > 0,
            query=query,
            records=records,
            result_count=len(records),
        )
