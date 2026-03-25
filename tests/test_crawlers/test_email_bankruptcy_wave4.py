"""
test_email_bankruptcy_wave4.py — Branch-coverage gap tests (wave 4).

Crawlers covered:
  email_breach, email_holehe, bankruptcy_pacer

Each test targets specific uncovered lines identified in the coverage report.
All subprocess / HTTP I/O is mocked.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ===========================================================================
# email_breach.py — lines 118-120, 151-153
# ===========================================================================


class TestEmailBreachCrawler:
    def _make_crawler(self):
        from modules.crawlers.email_breach import EmailBreachCrawler

        return EmailBreachCrawler()

    # --- lines 118-120: github resp.json() raises → return [] (breaches empty) ---
    @pytest.mark.asyncio
    async def test_github_json_parse_error_returns_empty(self):
        """Lines 118-120: GitHub code-search JSON parse error → breaches=[]."""
        crawler = self._make_crawler()

        # email_breach always returns found=True; we just check breaches list
        psbdmp_resp = _mock_resp(200, json_data={"data": []})
        github_resp = _mock_resp(200)
        github_resp.json.side_effect = ValueError("bad json")
        leakcheck_resp = _mock_resp(200, json_data={"success": False, "found": 0})

        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[psbdmp_resp, github_resp, leakcheck_resp]),
        ):
            result = await crawler.scrape("test@example.com")

        assert result.found is True  # always True by design
        assert result.data.get("breaches") == []

    # --- lines 151-153: leakcheck resp.json() raises → breaches empty ---
    @pytest.mark.asyncio
    async def test_leakcheck_json_parse_error_returns_empty(self):
        """Lines 151-153: LeakCheck JSON parse error → breaches=[]."""
        crawler = self._make_crawler()

        psbdmp_resp = _mock_resp(200, json_data={"data": []})
        github_resp = _mock_resp(200, json_data={"items": []})
        leakcheck_resp = _mock_resp(200)
        leakcheck_resp.json.side_effect = ValueError("bad leakcheck json")

        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[psbdmp_resp, github_resp, leakcheck_resp]),
        ):
            result = await crawler.scrape("test@example.com")

        assert result.found is True  # always True by design
        assert result.data.get("breaches") == []

    # --- lines 118-120 alt: github non-200 → breaches empty ---
    @pytest.mark.asyncio
    async def test_github_non200_returns_empty(self):
        """Lines 110-114: GitHub non-200 → github returns empty list."""
        crawler = self._make_crawler()

        psbdmp_resp = _mock_resp(200, json_data={"data": []})
        github_resp = _mock_resp(403)
        leakcheck_resp = _mock_resp(200, json_data={"success": False, "found": 0})

        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[psbdmp_resp, github_resp, leakcheck_resp]),
        ):
            result = await crawler.scrape("test@example.com")

        assert result.data.get("breaches") == []

    # --- end-to-end: full hit from leakcheck ---
    @pytest.mark.asyncio
    async def test_leakcheck_hit_populates_breaches(self):
        """Leakcheck returns a real hit → breaches list is populated."""
        crawler = self._make_crawler()

        psbdmp_resp = _mock_resp(200, json_data={"data": []})
        github_resp = _mock_resp(200, json_data={"items": []})
        leakcheck_resp = _mock_resp(
            200,
            json_data={
                "success": True,
                "found": 1,
                "sources": [
                    {
                        "name": "BreachDB",
                        "date": "2021-01-01",
                        "unverified": False,
                    }
                ],
            },
        )

        with patch.object(
            crawler,
            "get",
            new=AsyncMock(side_effect=[psbdmp_resp, github_resp, leakcheck_resp]),
        ):
            result = await crawler.scrape("victim@example.com")

        assert result.found is True
        assert len(result.data.get("breaches", [])) > 0


# ===========================================================================
# email_holehe.py — lines 49-50
# ===========================================================================


class TestEmailHoleheCrawler:
    # --- lines 49-50: _check_holehe_installed TimeoutError or FileNotFoundError ---
    @pytest.mark.asyncio
    async def test_check_holehe_installed_timeout(self):
        """Line 49-50 (TimeoutError): returns False on timeout."""
        from modules.crawlers.email_holehe import _check_holehe_installed

        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=TimeoutError("timed out")),
        ):
            result = await _check_holehe_installed()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_holehe_installed_file_not_found(self):
        """Line 49-50 (FileNotFoundError): returns False when holehe not on PATH."""
        from modules.crawlers.email_holehe import _check_holehe_installed

        with patch(
            "asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=FileNotFoundError("holehe not found")),
        ):
            result = await _check_holehe_installed()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_holehe_installed_wait_for_timeout(self):
        """Line 49-50: asyncio.wait_for TimeoutError returns False."""
        from modules.crawlers.email_holehe import _check_holehe_installed

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            with patch(
                "asyncio.wait_for",
                new=AsyncMock(side_effect=TimeoutError("wait timeout")),
            ):
                result = await _check_holehe_installed()

        assert result is False


# ===========================================================================
# bankruptcy_pacer.py — lines 64, 96, 115, 156, 186, 221-222
# ===========================================================================


class TestBankruptcyPacerCrawler:
    def _make_crawler(self):
        from modules.crawlers.bankruptcy_pacer import BankruptcyPacerCrawler

        return BankruptcyPacerCrawler()

    # --- line 64: _parse_recap_results "bankrupt" fallback chapter="7" ---
    def test_parse_recap_results_bankrupt_fallback_chapter(self):
        """Line 64: case_name contains 'bankrupt' → chapter defaults to '7'."""
        from modules.crawlers.bankruptcy_pacer import _parse_recap_results

        data = {
            "results": [
                {
                    "case_name": "Smith Bankruptcy Estate",
                    "court": "TXEB",
                    "nature_of_suit": "",
                    "dateFiled": "2022-01-01",
                    "status": "closed",
                    "absolute_url": "/docket/123/",
                }
            ]
        }
        cases = _parse_recap_results(data)
        assert len(cases) == 1
        assert cases[0]["chapter"] == "7"

    # --- line 96: _parse_cfpb_complaints hits-dict is not a dict → empty list ---
    def test_parse_cfpb_complaints_hits_not_dict(self):
        """Line 96: hits is a list (not dict) → hit_list = []."""
        from modules.crawlers.bankruptcy_pacer import _parse_cfpb_complaints

        # hits is a list, not a dict
        data = {"hits": ["unexpected", "list"]}
        complaints = _parse_cfpb_complaints(data)
        assert complaints == []

    # --- line 115: _parse_cfpb_complaints alternate shape: data.results ---
    def test_parse_cfpb_complaints_results_shape(self):
        """Line 115: alternate response with 'results' key instead of 'hits'."""
        from modules.crawlers.bankruptcy_pacer import _parse_cfpb_complaints

        data = {
            "results": [
                {
                    "product": "Credit card",
                    "sub_product": "",
                    "issue": "Billing dispute",
                    "company": "BigBank",
                    "date_received": "2023-06-01",
                    "company_response": "Closed",
                    "complaint_id": "999",
                }
            ]
        }
        complaints = _parse_cfpb_complaints(data)
        assert len(complaints) == 1
        assert complaints[0]["product"] == "Credit card"

    # --- line 156: scrape() with empty identifier → invalid_identifier ---
    @pytest.mark.asyncio
    async def test_scrape_empty_identifier(self):
        """Line 156: empty identifier → found=False, error=invalid_identifier."""
        crawler = self._make_crawler()
        result = await crawler.scrape("   ")
        assert result.found is False
        assert result.data.get("error") == "invalid_identifier"

    # --- line 186: recap_resp non-200 → http_NNN error ---
    @pytest.mark.asyncio
    async def test_scrape_recap_non200(self):
        """Line 186: RECAP returns non-200 → http_NNN error."""
        crawler = self._make_crawler()
        recap_resp = _mock_resp(503)

        with patch.object(crawler, "get", new=AsyncMock(return_value=recap_resp)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert "http_503" in (result.data.get("error") or "")

    # --- lines 221-222: cfpb_resp.json() raises, debug logged, complaints empty ---
    @pytest.mark.asyncio
    async def test_cfpb_json_parse_error_silently_ignored(self):
        """Lines 221-222: CFPB JSON parse error is swallowed; result still valid."""
        crawler = self._make_crawler()

        recap_resp = _mock_resp(
            200,
            json_data={
                "results": [
                    {
                        "case_name": "Test v. Debtor",
                        "court": "CAEB",
                        "nature_of_suit": "Chapter 13",
                        "dateFiled": "2021-05-01",
                        "status": "open",
                        "absolute_url": "/docket/456/",
                    }
                ]
            },
        )
        cfpb_resp = _mock_resp(200)
        cfpb_resp.json.side_effect = ValueError("bad cfpb json")

        with patch.object(
            crawler, "get", new=AsyncMock(side_effect=[recap_resp, cfpb_resp])
        ):
            result = await crawler.scrape("Test Debtor")

        assert result.found is True
        assert result.data.get("complaints") == []

    # --- recap_resp None → http_error ---
    @pytest.mark.asyncio
    async def test_scrape_recap_none(self):
        """recap_resp is None → found=False, error=http_error."""
        crawler = self._make_crawler()

        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.data.get("error") == "http_error"

    # --- recap json parse error ---
    @pytest.mark.asyncio
    async def test_scrape_recap_json_parse_error(self):
        """RECAP JSON parse error → found=False, error=json_parse_error."""
        crawler = self._make_crawler()
        recap_resp = _mock_resp(200)
        recap_resp.json.side_effect = ValueError("bad recap json")

        with patch.object(crawler, "get", new=AsyncMock(return_value=recap_resp)):
            result = await crawler.scrape("John Smith")

        assert result.found is False
        assert result.data.get("error") == "json_parse_error"
