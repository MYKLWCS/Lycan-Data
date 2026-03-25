"""
test_domain_paste_wave4.py — Targeted branch-coverage tests.

Crawlers covered:
  domain_theharvester, paste_pastebin, domain_whois, phone_fonefinder

Each test targets specific uncovered lines identified in the coverage report.
No real network or subprocess calls are made.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _mock_resp(status: int = 200, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text else ""
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ===========================================================================
# domain_theharvester.py
# Lines: 47-50, 65-66
# ===========================================================================


class TestDomainHarvesterCrawler:
    def _make(self):
        from modules.crawlers.domain_theharvester import DomainHarvesterCrawler

        return DomainHarvesterCrawler()

    # lines 47-50 — json file present path exercised via _run_harvester internals
    @pytest.mark.asyncio
    async def test_run_harvester_reads_json_file(self, tmp_path):
        import json as _json
        import os

        fake_data = {"emails": ["a@b.com"], "hosts": [], "ips": [], "urls": []}

        fake_proc = AsyncMock()
        fake_proc.communicate = AsyncMock(return_value=(b"", b""))

        written_paths = []

        async def fake_create(*args, **kwargs):
            # Write JSON at the path passed as the -f arg
            outfile = args[args.index("-f") + 1]
            json_path = outfile + ".json"
            with open(json_path, "w") as fh:
                _json.dump(fake_data, fh)
            written_paths.append(json_path)
            return fake_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_create):
            from modules.crawlers.domain_theharvester import _run_harvester

            result = await _run_harvester("example.com")

        assert result.get("emails") == ["a@b.com"]
        # cleanup
        for p in written_paths:
            if os.path.exists(p):
                os.unlink(p)

    # lines 65-66 — _check_harvester_installed returns False on FileNotFoundError
    @pytest.mark.asyncio
    async def test_check_harvester_not_installed(self):
        from modules.crawlers.domain_theharvester import _check_harvester_installed

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("theHarvester not found"),
        ):
            result = await _check_harvester_installed()

        assert result is False

    # lines 65-66 — _check_harvester_installed returns False on TimeoutError
    @pytest.mark.asyncio
    async def test_check_harvester_timeout(self):
        from modules.crawlers.domain_theharvester import _check_harvester_installed

        fake_proc = MagicMock()
        fake_proc.returncode = 0

        with (
            patch("asyncio.create_subprocess_exec", return_value=fake_proc),
            patch("asyncio.wait_for", side_effect=TimeoutError()),
        ):
            result = await _check_harvester_installed()

        assert result is False

    # scrape — harvester not installed (lines 107-113)
    @pytest.mark.asyncio
    async def test_scrape_not_installed(self):
        crawler = self._make()
        with patch(
            "modules.crawlers.domain_theharvester._check_harvester_installed",
            new=AsyncMock(return_value=False),
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "theharvester_not_installed"

    # scrape — harvester installed, run returns empty dict (found=False)
    @pytest.mark.asyncio
    async def test_scrape_empty_results(self):
        crawler = self._make()
        with (
            patch(
                "modules.crawlers.domain_theharvester._check_harvester_installed",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "modules.crawlers.domain_theharvester._run_harvester",
                new=AsyncMock(return_value={}),
            ),
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False

    # scrape — harvester installed, run raises TimeoutError
    @pytest.mark.asyncio
    async def test_scrape_timeout(self):
        crawler = self._make()
        with (
            patch(
                "modules.crawlers.domain_theharvester._check_harvester_installed",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "modules.crawlers.domain_theharvester._run_harvester",
                new=AsyncMock(side_effect=TimeoutError()),
            ),
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "harvester_timeout"

    # scrape — data found
    @pytest.mark.asyncio
    async def test_scrape_success(self):
        crawler = self._make()
        raw = {
            "emails": ["info@example.com"],
            "hosts": ["sub.example.com:1.2.3.4"],
            "ips": ["1.2.3.4"],
            "urls": [],
        }
        with (
            patch(
                "modules.crawlers.domain_theharvester._check_harvester_installed",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "modules.crawlers.domain_theharvester._run_harvester",
                new=AsyncMock(return_value=raw),
            ),
        ):
            result = await crawler.scrape("example.com")
        assert result.found is True
        assert "info@example.com" in result.data["emails"]
        assert "sub.example.com" in result.data["subdomains"]


# ===========================================================================
# paste_pastebin.py
# Lines: 42, 51, 56, 101, 119
# ===========================================================================


class TestPastePastebinCrawler:
    def _make(self):
        from modules.crawlers.paste_pastebin import PastePastebinCrawler

        return PastePastebinCrawler()

    # line 42 — None response => http_error
    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("user@example.com")
        assert result.found is False
        assert result.error == "http_error"

    # line 51 — absolute URL preserved in _parse_pastebin_html
    def test_parse_pastebin_html_absolute_url(self):
        from modules.crawlers.paste_pastebin import _parse_pastebin_html

        html = """
        <html><body>
          <div class="search-result">
            <a href="https://pastebin.com/AbCd1234">Paste Title</a>
            <span class="date">2024-01-15</span>
            <p>Some preview text here.</p>
          </div>
        </body></html>
        """
        mentions = _parse_pastebin_html(html)
        assert len(mentions) == 1
        assert mentions[0]["url"] == "https://pastebin.com/AbCd1234"
        assert mentions[0]["date"] == "2024-01-15"

    # line 56 — date found via <time> fallback when no span.date
    def test_parse_pastebin_html_time_tag_fallback(self):
        from modules.crawlers.paste_pastebin import _parse_pastebin_html

        html = """
        <html><body>
          <div class="search-result">
            <a href="/XyZ9876">Another Paste</a>
            <time>March 2024</time>
            <p>Preview snippet.</p>
          </div>
        </body></html>
        """
        mentions = _parse_pastebin_html(html)
        assert len(mentions) == 1
        assert mentions[0]["date"] == "March 2024"
        assert mentions[0]["url"].startswith("https://pastebin.com")

    # line 101 — 429 rate limit response
    @pytest.mark.asyncio
    async def test_scrape_rate_limited(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
            result = await crawler.scrape("test@example.com")
        assert result.found is False
        assert result.error == "rate_limited"

    # line 119 — non-200/non-429 status
    @pytest.mark.asyncio
    async def test_scrape_non_200(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("test@example.com")
        assert result.found is False
        assert result.error == "http_503"

    # success path with paste results
    @pytest.mark.asyncio
    async def test_scrape_success(self):
        crawler = self._make()
        html = """
        <html><body>
          <div class="search-result">
            <a href="/AbCd1234">Found Paste</a>
            <span class="date">2024-02-20</span>
            <p>Contains the query term.</p>
          </div>
        </body></html>
        """
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=html))):
            result = await crawler.scrape("user@example.com")
        assert result.found is True
        assert result.data["mention_count"] == 1


# ===========================================================================
# phone_fonefinder.py
# Lines: 161, 166, 184-189
# ===========================================================================


class TestFoneFinderCrawler:
    def _make(self):
        from modules.crawlers.phone_fonefinder import FoneFinderCrawler

        return FoneFinderCrawler()

    # line 161 — None response
    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("+15125550100")
        assert result.found is False
        assert result.error == "http_error"

    # line 166 — 404 response
    @pytest.mark.asyncio
    async def test_scrape_404(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
            result = await crawler.scrape("+15125550100")
        assert result.found is False
        assert result.error == "not_found"

    # lines 184-189 — fallback carrier detection via div/p/span with sibling
    def test_parse_response_carrier_fallback_sibling(self):
        crawler = self._make()
        # No table, just a div followed by a sibling containing the carrier name
        html = (
            "<html><body>"
            "<div>Carrier</div><div>AT&amp;T Mobility</div>"
            "<p>Austin TX</p>"
            "</body></html>"
        )
        result = crawler._parse_response(html, "US")
        assert isinstance(result, dict)
        assert "carrier_name" in result

    # lines 184-189 — fallback ignores sibling with len <= 2
    def test_parse_response_carrier_fallback_short_sibling_ignored(self):
        crawler = self._make()
        # sibling text is only 2 chars — should be ignored per the len > 2 guard
        html = "<html><body><span>Provider</span><span>OK</span></body></html>"
        result = crawler._parse_response(html, "US")
        assert isinstance(result, dict)
        # carrier_name stays empty because sibling is too short
        assert result.get("carrier_name", "") == ""

    # success path — carrier found in table
    @pytest.mark.asyncio
    async def test_scrape_success_with_carrier(self):
        crawler = self._make()
        html = (
            "<html><body>"
            "<table>"
            "<tr><td>Carrier</td><td>AT&amp;T Mobility</td></tr>"
            "<tr><td>City/State</td><td>Austin, TX</td></tr>"
            "</table>"
            "</body></html>"
        )
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=html))):
            result = await crawler.scrape("+15125550100")
        assert result.found is True
        assert result.data["carrier_name"] == "AT&T Mobility"

    # no carrier found — returns found=False, error=no_data
    @pytest.mark.asyncio
    async def test_scrape_no_carrier(self):
        crawler = self._make()
        html = "<html><body><p>No information found.</p></body></html>"
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=html))):
            result = await crawler.scrape("+15125550100")
        assert result.found is False
        assert result.error == "no_data"

    # non-200 non-404 path
    @pytest.mark.asyncio
    async def test_scrape_non_200(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("+15125550100")
        assert result.found is False
        assert result.error == "http_503"


# ===========================================================================
# domain_whois.py
# Lines: 44, 51, 108
# ===========================================================================


class TestDomainWhoisCrawler:
    def _make(self):
        from modules.crawlers.domain_whois import DomainWhoisCrawler

        return DomainWhoisCrawler()

    # line 44 — _extract_whois_text uses .df-value spans
    def test_extract_whois_text_df_value(self):
        from modules.crawlers.domain_whois import _extract_whois_text

        html = (
            "<html><body>"
            "<span class='df-value'>Registrar: GoDaddy</span>"
            "<span class='df-value'>Expiry: 2025-01-01</span>"
            "</body></html>"
        )
        text = _extract_whois_text(html)
        assert "GoDaddy" in text
        assert "Expiry" in text

    # line 51 — _extract_whois_text fallback via <pre> blocks
    def test_extract_whois_text_pre_fallback(self):
        from modules.crawlers.domain_whois import _extract_whois_text

        html = (
            "<html><body>"
            "<pre>Domain Name: example.com\n"
            "Registrar: Namecheap\n"
            "Creation Date: 2000-01-01</pre>"
            "</body></html>"
        )
        text = _extract_whois_text(html)
        assert "Namecheap" in text
        assert "Creation Date" in text

    # fallback to soup.get_text when no df-value and no pre
    def test_extract_whois_text_full_text_fallback(self):
        from modules.crawlers.domain_whois import _extract_whois_text

        html = "<html><body><div>Registrar Name Here</div></body></html>"
        text = _extract_whois_text(html)
        assert "Registrar Name Here" in text

    # line 108 — non-200 non-429 status
    @pytest.mark.asyncio
    async def test_scrape_non_200(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "http_503"

    # 429 rate limit
    @pytest.mark.asyncio
    async def test_scrape_rate_limited(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "rate_limited"

    # None response
    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "http_error"

    # success path — full whois data
    @pytest.mark.asyncio
    async def test_scrape_success(self):
        crawler = self._make()
        whois_html = (
            "<html><body><pre>"
            "Domain Name: example.com\n"
            "Registrar: GoDaddy LLC\n"
            "Creation Date: 2000-01-01T00:00:00Z\n"
            "Registry Expiry Date: 2030-01-01T00:00:00Z\n"
            "Registrant Name: John Doe\n"
            "Registrant Organization: Acme Corp\n"
            "Registrant Country: US\n"
            "Name Server: ns1.godaddy.com\n"
            "Name Server: ns2.godaddy.com"
            "</pre></body></html>"
        )
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=whois_html))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is True
        assert result.data["registrar"] == "GoDaddy LLC"
        assert result.data["registrant_name"] == "John Doe"
        assert "ns1.godaddy.com" in result.data["name_servers"]
