"""
mortgage_hmda.py — HMDA (Home Mortgage Disclosure Act) aggregate data.

Queries CFPB's HMDA Data Browser API for aggregate mortgage activity
by city/state or zip code. HMDA records are public but do NOT include
individual borrower names (privacy-protected by statute).

Registered as "mortgage_hmda".

identifier: "{city},{state}" or "{zip_code}"
  e.g. "Austin,TX" or "78701"

API: CFPB HMDA Data Browser 2023 aggregations endpoint.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_HMDA_AGG_URL = (
    "https://ffiec.cfpb.gov/api/data-browser/data/2023/aggregations"
    "?states={state}&cities={city}&actions_taken=1&loan_types=1,2&format=json"
)
_HMDA_ZIP_URL = (
    "https://ffiec.cfpb.gov/api/data-browser/data/2023/aggregations"
    "?zip_codes={zip_code}&actions_taken=1&loan_types=1,2&format=json"
)

_ZIP_PATTERN = re.compile(r'^\d{5}(-\d{4})?$')


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------

def _parse_identifier(identifier: str) -> tuple[str, str, str]:
    """
    Returns (city, state, zip_code).
    If identifier matches a zip pattern → zip_code populated.
    If "City,State" format → city/state populated.
    """
    identifier = identifier.strip()
    if _ZIP_PATTERN.match(identifier):
        return "", "", identifier[:5]
    if "," in identifier:
        city, state = identifier.split(",", 1)
        return city.strip(), state.strip().upper(), ""
    # Single token — treat as city with unknown state
    return identifier, "", ""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_hmda_aggregations(data: dict) -> dict[str, Any]:
    """
    Parse CFPB HMDA aggregations response into summary statistics.

    Response schema varies; we normalise to our standard keys.
    """
    summary: dict[str, Any] = {
        "total_loans":        0,
        "median_loan_amount": None,
        "median_income":      None,
        "denial_rate":        None,
        "top_lenders":        [],
    }

    # The aggregations endpoint returns { aggregations: [...] } or { data: [...] }
    rows = (
        data.get("aggregations")
        or data.get("data")
        or data.get("results")
        or []
    )

    if not rows:
        return summary

    total = 0
    loan_amounts: list[float] = []
    incomes: list[float] = []
    lender_counts: dict[str, int] = {}
    approved = 0
    denied  = 0

    for row in rows:
        count = int(row.get("count", row.get("loan_count", 0)))
        total += count

        action = str(row.get("action_taken", row.get("actions_taken_name", "")))
        if re.search(r"denied|reject", action, re.I):
            denied += count
        else:
            approved += count

        loan_amt = row.get("loan_amount", row.get("median_loan_amount"))
        if loan_amt:
            try:
                loan_amounts.append(float(loan_amt))
            except (ValueError, TypeError):
                pass

        income = row.get("income", row.get("median_income"))
        if income:
            try:
                incomes.append(float(income))
            except (ValueError, TypeError):
                pass

        lei = row.get("lei") or row.get("institution_name", "")
        if lei:
            lender_counts[lei] = lender_counts.get(lei, 0) + count

    summary["total_loans"] = total

    if loan_amounts:
        loan_amounts.sort()
        mid = len(loan_amounts) // 2
        summary["median_loan_amount"] = loan_amounts[mid]

    if incomes:
        incomes.sort()
        mid = len(incomes) // 2
        summary["median_income"] = incomes[mid]

    if approved + denied > 0:
        summary["denial_rate"] = round(denied / (approved + denied), 4)

    top_lenders = sorted(lender_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    summary["top_lenders"] = [{"lender": k, "loan_count": v} for k, v in top_lenders]

    return summary


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

@register("mortgage_hmda")
class MortgageHmdaCrawler(HttpxCrawler):
    """
    Fetches HMDA aggregate mortgage data for a US city/state or zip code.

    identifier: "City,State" or "ZipCode" (5-digit)

    Data keys returned:
        city, state, zip_code, total_loans, median_loan_amount,
        median_income, denial_rate, top_lenders (list of {lender, loan_count})
    """

    platform = "mortgage_hmda"
    source_reliability = 0.80
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        city, state, zip_code = _parse_identifier(identifier)

        if zip_code:
            url = _HMDA_ZIP_URL.format(zip_code=quote_plus(zip_code))
        elif city and state:
            url = _HMDA_AGG_URL.format(
                state=quote_plus(state),
                city=quote_plus(city),
            )
        elif city:
            # Best effort — no state filter
            url = _HMDA_AGG_URL.format(
                state="all",
                city=quote_plus(city),
            )
        else:
            return self._result(
                identifier, found=False, error="invalid_identifier",
                city=city, state=state, zip_code=zip_code,
                total_loans=0, median_loan_amount=None, median_income=None,
                denial_rate=None, top_lenders=[],
            )

        resp = await self.get(url)

        if resp is None:
            return self._result(
                identifier, found=False, error="http_error",
                city=city, state=state, zip_code=zip_code,
                total_loans=0, median_loan_amount=None, median_income=None,
                denial_rate=None, top_lenders=[],
            )

        if resp.status_code != 200:
            return self._result(
                identifier, found=False, error=f"http_{resp.status_code}",
                city=city, state=state, zip_code=zip_code,
                total_loans=0, median_loan_amount=None, median_income=None,
                denial_rate=None, top_lenders=[],
            )

        try:
            data = resp.json()
        except Exception as exc:
            logger.warning("HMDA JSON parse error: %s", exc)
            return self._result(
                identifier, found=False, error="json_parse_error",
                city=city, state=state, zip_code=zip_code,
                total_loans=0, median_loan_amount=None, median_income=None,
                denial_rate=None, top_lenders=[],
            )

        summary = _parse_hmda_aggregations(data)
        summary["city"]     = city
        summary["state"]    = state
        summary["zip_code"] = zip_code

        found = summary["total_loans"] > 0
        return self._result(identifier, found=found, **summary)
