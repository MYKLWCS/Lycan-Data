"""
test_cyber_crawlers.py — Pytest coverage for all cyber_* crawler modules.

Crawlers under test:
    cyber_abuseipdb, cyber_alienvault, cyber_crt, cyber_dns,
    cyber_greynoise, cyber_shodan, cyber_urlscan, cyber_virustotal,
    cyber_wayback

Strategy:
    - Mock self.get() via patch.object(crawler, 'get', new=AsyncMock(...))
    - Never hit real network or Redis/circuit-breaker during tests
    - Cover every branch in each scrape() / internal helper
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Crawler imports
# ---------------------------------------------------------------------------
from modules.crawlers.cyber_abuseipdb import CyberAbuseIPDBCrawler
from modules.crawlers.cyber_alienvault import (
    CyberAlienVaultCrawler,
    _detect_type,
    _trim_pulses,
)
from modules.crawlers.cyber_crt import CyberCrtCrawler, _parse_certs
from modules.crawlers.cyber_dns import DnsCrawler, _spf_subdomain_hints
from modules.crawlers.cyber_greynoise import GreyNoiseCrawler
from modules.crawlers.cyber_shodan import ShodanCrawler
from modules.crawlers.cyber_urlscan import CyberURLScanCrawler
from modules.crawlers.cyber_virustotal import VirusTotalCrawler, _vt_url_id
from modules.crawlers.cyber_wayback import CyberWaybackCrawler, _parse_cdx
from modules.crawlers.registry import is_registered


# ---------------------------------------------------------------------------
# Helper: build a mock httpx response
# ---------------------------------------------------------------------------

def _mock_resp(status: int = 200, json_data=None, raise_json: bool = False) -> MagicMock:
    """Return a MagicMock that looks like an httpx.Response."""
    resp = MagicMock()
    resp.status_code = status
    if raise_json:
        resp.json.side_effect = ValueError("bad json")
    else:
        resp.json.return_value = json_data if json_data is not None else {}
    resp.text = str(json_data or {})
    return resp


# ===========================================================================
# Registry smoke-tests
# ===========================================================================

def test_abuseipdb_registered():
    assert is_registered("cyber_abuseipdb")


def test_alienvault_registered():
    assert is_registered("cyber_alienvault")


def test_crt_registered():
    assert is_registered("cyber_crt")


def test_dns_registered():
    assert is_registered("cyber_dns")


def test_greynoise_registered():
    assert is_registered("cyber_greynoise")


def test_shodan_registered():
    assert is_registered("cyber_shodan")


def test_urlscan_registered():
    assert is_registered("cyber_urlscan")


def test_virustotal_registered():
    assert is_registered("cyber_virustotal")


def test_wayback_registered():
    assert is_registered("cyber_wayback")


# ===========================================================================
# CyberAbuseIPDBCrawler
# ===========================================================================

class TestAbuseIPDB:

    @pytest.mark.asyncio
    async def test_no_api_key(self):
        crawler = CyberAbuseIPDBCrawler()
        with patch("modules.crawlers.cyber_abuseipdb.settings") as mock_settings:
            mock_settings.abuseipdb_api_key = ""
            result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert "key" in result.error.lower()
        assert result.platform == "cyber_abuseipdb"

    @pytest.mark.asyncio
    async def test_network_error(self):
        crawler = CyberAbuseIPDBCrawler()
        with patch("modules.crawlers.cyber_abuseipdb.settings") as mock_settings:
            mock_settings.abuseipdb_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_401_invalid_key(self):
        crawler = CyberAbuseIPDBCrawler()
        with patch("modules.crawlers.cyber_abuseipdb.settings") as mock_settings:
            mock_settings.abuseipdb_api_key = "badkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(401))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.error == "invalid_api_key"

    @pytest.mark.asyncio
    async def test_rate_limited(self):
        crawler = CyberAbuseIPDBCrawler()
        with patch("modules.crawlers.cyber_abuseipdb.settings") as mock_settings:
            mock_settings.abuseipdb_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_bad_status(self):
        crawler = CyberAbuseIPDBCrawler()
        with patch("modules.crawlers.cyber_abuseipdb.settings") as mock_settings:
            mock_settings.abuseipdb_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.error == "http_503"

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        crawler = CyberAbuseIPDBCrawler()
        with patch("modules.crawlers.cyber_abuseipdb.settings") as mock_settings:
            mock_settings.abuseipdb_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, raise_json=True))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_empty_data_no_reports(self):
        crawler = CyberAbuseIPDBCrawler()
        payload = {"data": {"ipAddress": "1.2.3.4", "totalReports": 0}}
        with patch("modules.crawlers.cyber_abuseipdb.settings") as mock_settings:
            mock_settings.abuseipdb_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("1.2.3.4")
        # totalReports == 0 → found should be False
        assert result.found is False
        assert result.error is None

    @pytest.mark.asyncio
    async def test_success_with_reports(self):
        crawler = CyberAbuseIPDBCrawler()
        payload = {
            "data": {
                "ipAddress": "1.2.3.4",
                "abuseConfidenceScore": 90,
                "countryCode": "CN",
                "usageType": "Data Center/Web Hosting/Transit",
                "isp": "Shady ISP",
                "totalReports": 15,
                "lastReportedAt": "2024-01-01T00:00:00+00:00",
            }
        }
        with patch("modules.crawlers.cyber_abuseipdb.settings") as mock_settings:
            mock_settings.abuseipdb_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is True
        assert result.data["totalReports"] == 15
        assert result.data["countryCode"] == "CN"
        assert result.source_reliability == 0.85

    @pytest.mark.asyncio
    async def test_missing_data_block(self):
        """API response with no 'data' key → totalReports defaults to 0 → not found."""
        crawler = CyberAbuseIPDBCrawler()
        with patch("modules.crawlers.cyber_abuseipdb.settings") as mock_settings:
            mock_settings.abuseipdb_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, {}))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False


# ===========================================================================
# CyberAlienVaultCrawler
# ===========================================================================

class TestAlienVault:

    # --- _detect_type unit tests ---
    def test_detect_type_ipv4(self):
        assert _detect_type("8.8.8.8") == "IPv4"

    def test_detect_type_md5(self):
        assert _detect_type("a" * 32) == "file"

    def test_detect_type_sha1(self):
        assert _detect_type("b" * 40) == "file"

    def test_detect_type_sha256(self):
        assert _detect_type("c" * 64) == "file"

    def test_detect_type_domain(self):
        assert _detect_type("example.com") == "domain"

    # --- _trim_pulses unit test ---
    def test_trim_pulses_limits_to_five(self):
        raw = {"pulse_info": {"count": 10, "pulses": list(range(10))}}
        result = _trim_pulses(raw)
        assert len(result["pulse_info"]["pulses"]) == 5

    def test_trim_pulses_no_pulse_info(self):
        """When pulse_info key is absent, _trim_pulses still adds it with empty pulses list."""
        raw = {"reputation": 0}
        result = _trim_pulses(raw)
        # pulse_info defaults to {} internally; empty pulses list gets written back
        assert result["reputation"] == 0
        assert result["pulse_info"]["pulses"] == []

    def test_trim_pulses_non_dict_pulse_info(self):
        """When pulse_info is not a dict, it is left entirely unchanged."""
        raw = {"pulse_info": "not-a-dict", "reputation": 1}
        result = _trim_pulses(raw)
        assert result["pulse_info"] == "not-a-dict"

    # --- scrape() branch tests ---
    @pytest.mark.asyncio
    async def test_network_error(self):
        crawler = CyberAlienVaultCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("8.8.8.8")
        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_rate_limited(self):
        crawler = CyberAlienVaultCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_404_not_found(self):
        """OTX 404 = no data, but not an error — found=False with no error field."""
        crawler = CyberAlienVaultCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error is None
        assert result.data.get("indicator_type") == "domain"

    @pytest.mark.asyncio
    async def test_bad_status(self):
        crawler = CyberAlienVaultCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "http_500"

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        crawler = CyberAlienVaultCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, raise_json=True))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_empty_data_not_found(self):
        """pulse_count == 0 and reputation == 0 → found=False."""
        crawler = CyberAlienVaultCrawler()
        payload = {"pulse_info": {"count": 0, "pulses": []}, "reputation": 0}
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_success_with_pulses(self):
        crawler = CyberAlienVaultCrawler()
        payload = {
            "pulse_info": {"count": 3, "pulses": [{"name": "p1"}, {"name": "p2"}, {"name": "p3"}]},
            "reputation": 5,
        }
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
        ):
            result = await crawler.scrape("8.8.8.8")
        assert result.found is True
        assert result.data["indicator_type"] == "IPv4"

    @pytest.mark.asyncio
    async def test_success_reputation_only(self):
        """Non-zero reputation with zero pulses still counts as found."""
        crawler = CyberAlienVaultCrawler()
        payload = {"pulse_info": {"count": 0, "pulses": []}, "reputation": -3}
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is True

    @pytest.mark.asyncio
    async def test_api_key_added_to_headers_when_present(self):
        """Confirm X-OTX-API-KEY header is included when key is set."""
        crawler = CyberAlienVaultCrawler()
        captured: list = []

        async def _fake_get(url, **kwargs):
            captured.append(kwargs.get("headers", {}))
            return _mock_resp(200, {"pulse_info": {"count": 0, "pulses": []}, "reputation": 0})

        with patch("modules.crawlers.cyber_alienvault.settings") as ms:
            ms.otx_api_key = "my-secret-key"
            with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
                await crawler.scrape("example.com")

        assert captured[0].get("X-OTX-API-KEY") == "my-secret-key"

    @pytest.mark.asyncio
    async def test_no_api_key_no_header(self):
        """Without a key, the X-OTX-API-KEY header must be absent."""
        crawler = CyberAlienVaultCrawler()
        captured: list = []

        async def _fake_get(url, **kwargs):
            captured.append(kwargs.get("headers", {}))
            return _mock_resp(200, {"pulse_info": {"count": 0, "pulses": []}, "reputation": 0})

        with patch("modules.crawlers.cyber_alienvault.settings") as ms:
            ms.otx_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
                await crawler.scrape("example.com")

        assert "X-OTX-API-KEY" not in captured[0]


# ===========================================================================
# CyberCrtCrawler
# ===========================================================================

class TestCrt:

    # --- _parse_certs unit test ---
    def test_parse_certs_extracts_keep_fields(self):
        entries = [
            {"id": 1, "issuer_name": "Let's Encrypt", "name_value": "example.com",
             "not_before": "2024-01-01", "not_after": "2024-04-01", "extra": "ignored",
             "issuer_ca_id": 42}
        ]
        out = _parse_certs(entries)
        assert len(out) == 1
        assert "extra" not in out[0]
        assert out[0]["issuer_name"] == "Let's Encrypt"

    # --- scrape() branch tests ---
    @pytest.mark.asyncio
    async def test_network_error(self):
        crawler = CyberCrtCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_rate_limited(self):
        crawler = CyberCrtCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_bad_status(self):
        crawler = CyberCrtCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(502))):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "http_502"

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        crawler = CyberCrtCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, raise_json=True))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_non_list_response(self):
        """crt.sh returns a non-list (e.g. dict) — should flag unexpected format."""
        crawler = CyberCrtCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, {"error": "not a list"}))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "unexpected_response_format"

    @pytest.mark.asyncio
    async def test_empty_cert_list(self):
        crawler = CyberCrtCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, []))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.data["count"] == 0

    @pytest.mark.asyncio
    async def test_success(self):
        crawler = CyberCrtCrawler()
        payload = [
            {
                "id": 1,
                "issuer_ca_id": 10,
                "issuer_name": "Let's Encrypt",
                "name_value": "example.com",
                "not_before": "2024-01-01T00:00:00",
                "not_after": "2024-04-01T00:00:00",
            }
        ]
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
        ):
            result = await crawler.scrape("Example.COM")
        assert result.found is True
        assert result.data["count"] == 1
        # identifier should be lowercased
        assert result.data["domain"] == "example.com"
        assert result.source_reliability == 0.95

    @pytest.mark.asyncio
    async def test_capped_at_50_certs(self):
        """Result payload is capped at 50 certificates."""
        crawler = CyberCrtCrawler()
        payload = [
            {"id": i, "issuer_ca_id": i, "issuer_name": "CA", "name_value": f"sub{i}.example.com",
             "not_before": "2024-01-01", "not_after": "2025-01-01"}
            for i in range(100)
        ]
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
        ):
            result = await crawler.scrape("example.com")
        assert len(result.data["certificates"]) == 50
        assert result.data["count"] == 100


# ===========================================================================
# DnsCrawler
# ===========================================================================

class TestDnsCrawler:

    # --- _spf_subdomain_hints unit tests ---
    def test_spf_hints_extracts_includes(self):
        records = ["v=spf1 include:sendgrid.net include:mailgun.org ~all"]
        hints = _spf_subdomain_hints(records)
        assert "sendgrid.net" in hints
        assert "mailgun.org" in hints

    def test_spf_hints_non_spf_record_ignored(self):
        records = ["some other txt record"]
        hints = _spf_subdomain_hints(records)
        assert hints == []

    def test_spf_hints_empty(self):
        assert _spf_subdomain_hints([]) == []

    # --- scrape() — DoH lookup branches ---
    @pytest.mark.asyncio
    async def test_success_all_records(self):
        """Mock DoH lookups to return realistic data; socket calls mocked too."""
        crawler = DnsCrawler()

        mx_resp = _mock_resp(200, {"Answer": [{"data": "mail.example.com."}]})
        txt_resp = _mock_resp(200, {"Answer": [{"data": "v=spf1 include:sendgrid.net ~all"}]})
        ns_resp = _mock_resp(200, {"Answer": [{"data": "ns1.example.com."}]})

        # get() is called three times: MX, TXT, NS
        get_mock = AsyncMock(side_effect=[mx_resp, txt_resp, ns_resp])

        with patch.object(crawler, "get", new=get_mock):
            with patch.object(crawler, "_resolve_a", return_value=["93.184.216.34"]):
                with patch.object(crawler, "_resolve_aaaa", return_value=[]):
                    with patch.object(crawler, "_reverse_dns", return_value="example.com"):
                        result = await crawler.scrape("example.com")

        assert result.found is True
        assert "93.184.216.34" in result.data["a_records"]
        assert result.data["mx_records"] == ["mail.example.com"]
        assert result.data["ns_records"] == ["ns1.example.com"]
        assert "sendgrid.net" in result.data["subdomain_hints"]
        assert result.data["reverse_dns"] == "example.com"

    @pytest.mark.asyncio
    async def test_no_records_found(self):
        """All lookups return empty — found=False."""
        crawler = DnsCrawler()
        empty_resp = _mock_resp(200, {"Answer": []})
        get_mock = AsyncMock(return_value=empty_resp)

        with patch.object(crawler, "get", new=get_mock):
            with patch.object(crawler, "_resolve_a", return_value=[]):
                with patch.object(crawler, "_resolve_aaaa", return_value=[]):
                    result = await crawler.scrape("nonexistent-xyz.invalid")

        assert result.found is False

    @pytest.mark.asyncio
    async def test_doh_network_error_returns_empty_list(self):
        """None response from DoH → empty list, no crash."""
        crawler = DnsCrawler()
        get_mock = AsyncMock(return_value=None)

        with patch.object(crawler, "get", new=get_mock):
            with patch.object(crawler, "_resolve_a", return_value=["1.2.3.4"]):
                with patch.object(crawler, "_resolve_aaaa", return_value=[]):
                    with patch.object(crawler, "_reverse_dns", return_value=""):
                        result = await crawler.scrape("example.com")

        # A record present → found, but DoH records are empty
        assert result.found is True
        assert result.data["mx_records"] == []
        assert result.data["ns_records"] == []

    @pytest.mark.asyncio
    async def test_doh_bad_status_returns_empty_list(self):
        """Non-200 DoH status → empty list."""
        crawler = DnsCrawler()
        get_mock = AsyncMock(return_value=_mock_resp(503, {}))

        with patch.object(crawler, "get", new=get_mock):
            with patch.object(crawler, "_resolve_a", return_value=[]):
                with patch.object(crawler, "_resolve_aaaa", return_value=["::1"]):
                    with patch.object(crawler, "_reverse_dns", return_value=""):
                        result = await crawler.scrape("example.com")

        assert result.data["mx_records"] == []

    @pytest.mark.asyncio
    async def test_doh_invalid_json_returns_empty_list(self):
        """DoH returns 200 but unparseable JSON → empty list, no crash."""
        crawler = DnsCrawler()
        bad_resp = _mock_resp(200, raise_json=True)
        get_mock = AsyncMock(return_value=bad_resp)

        with patch.object(crawler, "get", new=get_mock):
            with patch.object(crawler, "_resolve_a", return_value=[]):
                with patch.object(crawler, "_resolve_aaaa", return_value=[]):
                    result = await crawler.scrape("example.com")

        assert result.data["txt_records"] == []

    @pytest.mark.asyncio
    async def test_reverse_dns_only_called_when_a_records_present(self):
        """_reverse_dns should not be invoked when a_records is empty."""
        crawler = DnsCrawler()
        get_mock = AsyncMock(return_value=_mock_resp(200, {"Answer": []}))

        with patch.object(crawler, "get", new=get_mock):
            with patch.object(crawler, "_resolve_a", return_value=[]) as mock_a:
                with patch.object(crawler, "_resolve_aaaa", return_value=[]):
                    with patch.object(crawler, "_reverse_dns") as mock_rev:
                        result = await crawler.scrape("example.com")

        mock_rev.assert_not_called()
        assert result.data["reverse_dns"] == ""

    # --- Stdlib helpers smoke tests ---
    def test_resolve_a_bad_hostname(self):
        crawler = DnsCrawler()
        result = crawler._resolve_a("this-hostname-does-not-exist-xyz-abc.invalid")
        assert result == []

    def test_resolve_aaaa_bad_hostname(self):
        crawler = DnsCrawler()
        result = crawler._resolve_aaaa("this-hostname-does-not-exist-xyz-abc.invalid")
        assert result == []

    def test_reverse_dns_bad_ip(self):
        crawler = DnsCrawler()
        result = crawler._reverse_dns("0.0.0.0")
        assert isinstance(result, str)


# ===========================================================================
# GreyNoiseCrawler
# ===========================================================================

class TestGreyNoise:

    # --- Community path (no api key) ---
    # All community and full-path errors use self._result() → error in result.data["error"]
    @pytest.mark.asyncio
    async def test_community_network_error(self):
        crawler = GreyNoiseCrawler()
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "http_error"

    @pytest.mark.asyncio
    async def test_community_404_not_found(self):
        crawler = GreyNoiseCrawler()
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "not_found"

    @pytest.mark.asyncio
    async def test_community_rate_limited(self):
        crawler = GreyNoiseCrawler()
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "rate_limited"

    @pytest.mark.asyncio
    async def test_community_bad_status(self):
        crawler = GreyNoiseCrawler()
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "http_500"

    @pytest.mark.asyncio
    async def test_community_invalid_json(self):
        crawler = GreyNoiseCrawler()
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = ""
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, raise_json=True))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "parse_error"

    @pytest.mark.asyncio
    async def test_community_success_noise(self):
        crawler = GreyNoiseCrawler()
        payload = {
            "ip": "1.2.3.4",
            "noise": True,
            "riot": False,
            "classification": "malicious",
            "name": "ThreatActor",
            "link": "https://viz.greynoise.io/ip/1.2.3.4",
            "last_seen": "2024-01-01",
            "message": "This IP is commonly seen scanning the internet.",
        }
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = ""
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is True
        assert result.data["api"] == "community"
        assert result.data["noise"] is True

    @pytest.mark.asyncio
    async def test_community_not_noise_not_riot(self):
        crawler = GreyNoiseCrawler()
        payload = {"ip": "1.2.3.4", "noise": False, "riot": False}
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = ""
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False

    # --- Full (authenticated) path ---
    @pytest.mark.asyncio
    async def test_full_success(self):
        crawler = GreyNoiseCrawler()
        payload = {
            "ip": "1.2.3.4",
            "noise": True,
            "riot": False,
            "classification": "malicious",
            "name": "Scanner",
            "link": "",
            "last_seen": "2024-01-01",
            "message": "",
        }
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = "validkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is True
        assert result.data["api"] == "full"

    @pytest.mark.asyncio
    async def test_full_network_error_falls_back_to_community(self):
        """Full API None → falls back to community endpoint."""
        crawler = GreyNoiseCrawler()
        community_payload = {"ip": "1.2.3.4", "noise": True, "riot": False}

        call_count = 0

        async def _get_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # full API fails
            return _mock_resp(200, community_payload)  # community succeeds

        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = "validkey"
            with patch.object(crawler, "get", new=AsyncMock(side_effect=_get_side_effect)):
                result = await crawler.scrape("1.2.3.4")

        assert result.found is True
        assert result.data["api"] == "community"

    @pytest.mark.asyncio
    async def test_full_401_falls_back_to_community(self):
        """Full API 401 → falls back to community endpoint."""
        crawler = GreyNoiseCrawler()
        community_payload = {"ip": "1.2.3.4", "noise": False, "riot": True}

        call_count = 0

        async def _get_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(401)
            return _mock_resp(200, community_payload)

        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = "badkey"
            with patch.object(crawler, "get", new=AsyncMock(side_effect=_get_side_effect)):
                result = await crawler.scrape("1.2.3.4")

        assert result.found is True
        assert result.data["api"] == "community"

    @pytest.mark.asyncio
    async def test_full_404_not_found(self):
        crawler = GreyNoiseCrawler()
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = "validkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "not_found"

    @pytest.mark.asyncio
    async def test_full_429_rate_limited(self):
        crawler = GreyNoiseCrawler()
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = "validkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "rate_limited"

    @pytest.mark.asyncio
    async def test_full_bad_status(self):
        crawler = GreyNoiseCrawler()
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = "validkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "http_503"

    @pytest.mark.asyncio
    async def test_full_invalid_json(self):
        crawler = GreyNoiseCrawler()
        with patch("modules.crawlers.cyber_greynoise.settings") as ms:
            ms.greynoise_api_key = "validkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, raise_json=True))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "parse_error"


# ===========================================================================
# ShodanCrawler
# ===========================================================================

class TestShodan:

    # All Shodan errors use self._result() → error stored in result.data["error"]
    @pytest.mark.asyncio
    async def test_no_api_key(self):
        crawler = ShodanCrawler()
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = ""
            result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "not_configured"

    # --- Host path (IPv4) ---
    @pytest.mark.asyncio
    async def test_host_network_error(self):
        crawler = ShodanCrawler()
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "http_error"

    @pytest.mark.asyncio
    async def test_host_404(self):
        crawler = ShodanCrawler()
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "not_found"

    @pytest.mark.asyncio
    async def test_host_401_invalid_key(self):
        crawler = ShodanCrawler()
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "badkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(401))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "invalid_api_key"

    @pytest.mark.asyncio
    async def test_host_bad_status(self):
        crawler = ShodanCrawler()
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "http_500"

    @pytest.mark.asyncio
    async def test_host_invalid_json(self):
        crawler = ShodanCrawler()
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, raise_json=True))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "parse_error"

    @pytest.mark.asyncio
    async def test_host_success(self):
        crawler = ShodanCrawler()
        payload = {
            "ports": [22, 80, 443],
            "vulns": {"CVE-2021-44228": {}, "CVE-2022-0001": {}},
            "org": "Google LLC",
            "country_name": "United States",
            "isp": "Google",
            "hostnames": ["dns.google"],
            "last_update": "2024-01-01T00:00:00",
        }
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("8.8.8.8")
        assert result.found is True
        assert result.data["mode"] == "host"
        assert set(result.data["vulns"]) == {"CVE-2021-44228", "CVE-2022-0001"}
        assert 80 in result.data["open_ports"]

    @pytest.mark.asyncio
    async def test_host_vulns_as_list(self):
        """When vulns is already a list (not dict), it should pass through unchanged."""
        crawler = ShodanCrawler()
        payload = {"ports": [22], "vulns": ["CVE-2021-44228"], "org": "", "country_name": "",
                   "isp": "", "hostnames": [], "last_update": ""}
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is True
        assert result.data["vulns"] == ["CVE-2021-44228"]

    # --- Search path (domain / query string) ---
    @pytest.mark.asyncio
    async def test_search_network_error(self):
        crawler = ShodanCrawler()
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("apache org:Google")
        assert result.found is False
        assert result.data["error"] == "http_error"

    @pytest.mark.asyncio
    async def test_search_401_invalid_key(self):
        crawler = ShodanCrawler()
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "badkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(401))):
                result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.data["error"] == "invalid_api_key"

    @pytest.mark.asyncio
    async def test_search_bad_status(self):
        crawler = ShodanCrawler()
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
                result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.data["error"] == "http_503"

    @pytest.mark.asyncio
    async def test_search_invalid_json(self):
        crawler = ShodanCrawler()
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, raise_json=True))
            ):
                result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.data["error"] == "parse_error"

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        crawler = ShodanCrawler()
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, {"total": 0, "matches": []}))
            ):
                result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.data["total"] == 0

    @pytest.mark.asyncio
    async def test_search_success(self):
        crawler = ShodanCrawler()
        payload = {
            "total": 2,
            "matches": [
                {
                    "ip_str": "1.2.3.4",
                    "ports": [80],
                    "org": "Acme Corp",
                    "location": {"country_code": "US"},
                },
                {
                    "ip_str": "5.6.7.8",
                    "ports": [443],
                    "org": "Example Inc",
                    "location": {"country_code": "DE"},
                },
            ],
        }
        with patch("modules.crawlers.cyber_shodan.settings") as ms:
            ms.shodan_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("example.com")
        assert result.found is True
        assert result.data["mode"] == "search"
        assert result.data["total"] == 2
        assert len(result.data["matches"]) == 2
        assert result.data["matches"][0]["country_code"] == "US"


# ===========================================================================
# CyberURLScanCrawler
# ===========================================================================

class TestURLScan:

    @pytest.mark.asyncio
    async def test_network_error(self):
        crawler = CyberURLScanCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_rate_limited(self):
        crawler = CyberURLScanCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "rate_limited"

    @pytest.mark.asyncio
    async def test_bad_status(self):
        crawler = CyberURLScanCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(500))):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "http_500"

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        crawler = CyberURLScanCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, raise_json=True))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "invalid_json"

    @pytest.mark.asyncio
    async def test_empty_results(self):
        crawler = CyberURLScanCrawler()
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, {"results": [], "total": 0}))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.data["total"] == 0

    @pytest.mark.asyncio
    async def test_non_list_results_treated_as_empty(self):
        """results field is not a list → treated as empty, no crash."""
        crawler = CyberURLScanCrawler()
        with patch.object(
            crawler,
            "get",
            new=AsyncMock(return_value=_mock_resp(200, {"results": "bad", "total": 1})),
        ):
            result = await crawler.scrape("example.com")
        assert result.found is False

    @pytest.mark.asyncio
    async def test_success(self):
        crawler = CyberURLScanCrawler()
        payload = {
            "total": 1,
            "results": [
                {
                    "task": {"url": "https://example.com", "time": "2024-01-01T00:00:00Z"},
                    "stats": {"malicious": 0},
                    "verdicts": {"overall": {"malicious": False, "score": 0}},
                }
            ],
        }
        with patch.object(
            crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
        ):
            result = await crawler.scrape("example.com")
        assert result.found is True
        assert len(result.data["results"]) == 1
        assert result.data["results"][0]["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_api_key_added_when_present(self):
        crawler = CyberURLScanCrawler()
        captured: list = []

        async def _fake_get(url, **kwargs):
            captured.append(kwargs.get("headers", {}))
            return _mock_resp(200, {"results": [], "total": 0})

        with patch("modules.crawlers.cyber_urlscan.settings") as ms:
            ms.urlscan_api_key = "my-urlscan-key"
            with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
                await crawler.scrape("example.com")

        assert captured[0].get("API-Key") == "my-urlscan-key"

    @pytest.mark.asyncio
    async def test_no_api_key_no_header(self):
        crawler = CyberURLScanCrawler()
        captured: list = []

        async def _fake_get(url, **kwargs):
            captured.append(kwargs.get("headers", {}))
            return _mock_resp(200, {"results": [], "total": 0})

        with patch("modules.crawlers.cyber_urlscan.settings") as ms:
            ms.urlscan_api_key = ""
            with patch.object(crawler, "get", new=AsyncMock(side_effect=_fake_get)):
                await crawler.scrape("example.com")

        assert "API-Key" not in captured[0]


# ===========================================================================
# VirusTotalCrawler
# ===========================================================================

class TestVirusTotal:

    # --- Helper utilities ---
    def test_vt_url_id_no_padding(self):
        """URL id must have no '=' padding."""
        url_id = _vt_url_id("https://example.com")
        assert "=" not in url_id

    # All VirusTotal errors use self._result() via _handle_response() → error in result.data["error"]
    # --- No API key ---
    @pytest.mark.asyncio
    async def test_no_api_key(self):
        crawler = VirusTotalCrawler()
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = ""
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.data["error"] == "not_configured"

    # --- IP path ---
    @pytest.mark.asyncio
    async def test_ip_network_error(self):
        crawler = VirusTotalCrawler()
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "http_error"

    @pytest.mark.asyncio
    async def test_ip_401(self):
        crawler = VirusTotalCrawler()
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = "badkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(401))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "invalid_api_key"

    @pytest.mark.asyncio
    async def test_ip_404(self):
        crawler = VirusTotalCrawler()
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
                result = await crawler.scrape("8.8.8.8")
        assert result.found is False
        assert result.data["error"] == "not_found"
        assert result.data.get("endpoint") == "ip"

    @pytest.mark.asyncio
    async def test_ip_rate_limited(self):
        crawler = VirusTotalCrawler()
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "rate_limited"

    @pytest.mark.asyncio
    async def test_ip_bad_status(self):
        crawler = VirusTotalCrawler()
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "http_503"

    @pytest.mark.asyncio
    async def test_ip_invalid_json(self):
        crawler = VirusTotalCrawler()
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, raise_json=True))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is False
        assert result.data["error"] == "parse_error"

    @pytest.mark.asyncio
    async def test_ip_success_malicious(self):
        crawler = VirusTotalCrawler()
        payload = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {"malicious": 5, "suspicious": 1, "undetected": 50},
                    "total_votes": {"harmless": 0, "malicious": 5},
                    "reputation": -10,
                    "categories": {},
                }
            }
        }
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("1.2.3.4")
        assert result.found is True
        assert result.data["malicious"] == 5
        assert result.data["endpoint"] == "ip"

    @pytest.mark.asyncio
    async def test_ip_success_clean(self):
        """Zero malicious + suspicious → found=False."""
        crawler = VirusTotalCrawler()
        payload = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {"malicious": 0, "suspicious": 0},
                    "total_votes": {},
                    "reputation": 0,
                    "categories": {},
                }
            }
        }
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("8.8.8.8")
        assert result.found is False

    # --- Domain path ---
    @pytest.mark.asyncio
    async def test_domain_success(self):
        crawler = VirusTotalCrawler()
        payload = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {"malicious": 2, "suspicious": 0},
                    "total_votes": {},
                    "reputation": -5,
                    "categories": {"Forcepoint ThreatSeeker": "phishing"},
                }
            }
        }
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("malicious-domain.example")
        assert result.found is True
        assert result.data["endpoint"] == "domain"

    # --- URL path ---
    @pytest.mark.asyncio
    async def test_url_success(self):
        crawler = VirusTotalCrawler()
        payload = {
            "data": {
                "attributes": {
                    "last_analysis_stats": {"malicious": 3, "suspicious": 0},
                    "total_votes": {},
                    "reputation": 0,
                    "categories": {},
                }
            }
        }
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = "testkey"
            with patch.object(
                crawler, "get", new=AsyncMock(return_value=_mock_resp(200, payload))
            ):
                result = await crawler.scrape("https://malicious.example.com/phish")
        assert result.found is True
        assert result.data["endpoint"] == "url"

    @pytest.mark.asyncio
    async def test_url_404_not_found(self):
        """URL not yet scanned returns 404."""
        crawler = VirusTotalCrawler()
        with patch("modules.crawlers.cyber_virustotal.settings") as ms:
            ms.virustotal_api_key = "testkey"
            with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
                result = await crawler.scrape("https://brand-new-url.example.com/")
        assert result.found is False
        assert result.data["error"] == "not_found"
        assert result.data.get("endpoint") == "url"


# ===========================================================================
# CyberWaybackCrawler
# ===========================================================================

class TestWayback:

    # --- _parse_cdx unit tests ---
    def test_parse_cdx_normal(self):
        raw = [
            ["timestamp", "original", "statuscode"],
            ["20240101120000", "http://example.com/", "200"],
            ["20231201090000", "http://example.com/page", "301"],
        ]
        result = _parse_cdx(raw)
        assert len(result) == 2
        assert result[0]["timestamp"] == "20240101120000"
        assert result[0]["statuscode"] == "200"

    def test_parse_cdx_empty_list(self):
        assert _parse_cdx([]) == []

    def test_parse_cdx_only_header_row(self):
        assert _parse_cdx([["timestamp", "original", "statuscode"]]) == []

    def test_parse_cdx_mismatched_row_length_skipped(self):
        raw = [
            ["timestamp", "original", "statuscode"],
            ["20240101120000"],  # too short — skipped
        ]
        result = _parse_cdx(raw)
        assert result == []

    # --- scrape() branches ---
    @pytest.mark.asyncio
    async def test_both_requests_fail(self):
        """Both availability and CDX returning None → http_error."""
        crawler = CyberWaybackCrawler()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("example.com")
        assert result.found is False
        assert result.error == "http_error"

    @pytest.mark.asyncio
    async def test_availability_ok_cdx_fails(self):
        """Availability has a snapshot, CDX fails → still found=True."""
        crawler = CyberWaybackCrawler()
        avail_payload = {
            "archived_snapshots": {
                "closest": {
                    "available": True,
                    "url": "https://web.archive.org/web/20240101/http://example.com/",
                    "timestamp": "20240101120000",
                    "status": "200",
                }
            }
        }

        call_count = 0

        async def _get_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(200, avail_payload)
            return None  # CDX fails

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_get_side_effect)):
            result = await crawler.scrape("example.com")

        assert result.found is True
        assert result.data["closest_snapshot"] is not None
        assert result.data["recent_snapshots"] == []

    @pytest.mark.asyncio
    async def test_availability_fails_cdx_ok(self):
        """Availability fails, CDX succeeds → found=False (no closest_snapshot)."""
        crawler = CyberWaybackCrawler()
        cdx_payload = [
            ["timestamp", "original", "statuscode"],
            ["20240101120000", "http://example.com/", "200"],
        ]

        call_count = 0

        async def _get_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # availability fails
            return _mock_resp(200, cdx_payload)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_get_side_effect)):
            result = await crawler.scrape("example.com")

        # closest_snapshot is None → found=False
        assert result.found is False
        assert result.data["recent_snapshots"] != []

    @pytest.mark.asyncio
    async def test_both_ok_full_success(self):
        crawler = CyberWaybackCrawler()
        avail_payload = {
            "archived_snapshots": {
                "closest": {
                    "available": True,
                    "url": "https://web.archive.org/web/20240101/http://example.com/",
                    "timestamp": "20240101120000",
                    "status": "200",
                }
            }
        }
        cdx_payload = [
            ["timestamp", "original", "statuscode"],
            ["20240101120000", "http://example.com/", "200"],
            ["20231201090000", "http://example.com/about", "200"],
        ]

        call_count = 0

        async def _get_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(200, avail_payload)
            return _mock_resp(200, cdx_payload)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_get_side_effect)):
            result = await crawler.scrape("example.com")

        assert result.found is True
        assert len(result.data["recent_snapshots"]) == 2
        assert result.data["url"] == "example.com"

    @pytest.mark.asyncio
    async def test_availability_bad_status_treated_gracefully(self):
        """Non-200 availability response → no closest_snapshot, continues to CDX."""
        crawler = CyberWaybackCrawler()
        cdx_payload = [
            ["timestamp", "original", "statuscode"],
            ["20240101120000", "http://example.com/", "200"],
        ]

        call_count = 0

        async def _get_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(503, {})
            return _mock_resp(200, cdx_payload)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_get_side_effect)):
            result = await crawler.scrape("example.com")

        # availability returned non-200 → no closest_snapshot → found=False
        assert result.found is False
        assert len(result.data["recent_snapshots"]) == 1

    @pytest.mark.asyncio
    async def test_availability_invalid_json_continues(self):
        """Availability JSON parse failure → no closest_snapshot, CDX still tried."""
        crawler = CyberWaybackCrawler()
        cdx_payload = [
            ["timestamp", "original", "statuscode"],
            ["20240101120000", "http://example.com/", "200"],
        ]

        call_count = 0

        async def _get_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(200, raise_json=True)
            return _mock_resp(200, cdx_payload)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_get_side_effect)):
            result = await crawler.scrape("example.com")

        assert result.found is False
        assert len(result.data["recent_snapshots"]) == 1

    @pytest.mark.asyncio
    async def test_cdx_invalid_json_continues(self):
        """CDX JSON parse failure → empty recent_snapshots, no crash."""
        crawler = CyberWaybackCrawler()
        avail_payload = {
            "archived_snapshots": {
                "closest": {
                    "available": True,
                    "url": "https://web.archive.org/web/20240101/http://example.com/",
                    "timestamp": "20240101120000",
                    "status": "200",
                }
            }
        }

        call_count = 0

        async def _get_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(200, avail_payload)
            return _mock_resp(200, raise_json=True)

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_get_side_effect)):
            result = await crawler.scrape("example.com")

        assert result.found is True
        assert result.data["recent_snapshots"] == []

    @pytest.mark.asyncio
    async def test_availability_snapshot_not_available(self):
        """Closest snapshot exists but available=False → closest_snapshot stays None."""
        crawler = CyberWaybackCrawler()
        avail_payload = {
            "archived_snapshots": {
                "closest": {
                    "available": False,
                    "url": "",
                    "timestamp": "",
                    "status": "",
                }
            }
        }

        call_count = 0

        async def _get_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(200, avail_payload)
            return _mock_resp(200, [])  # CDX empty

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_get_side_effect)):
            result = await crawler.scrape("example.com")

        assert result.found is False
        assert result.data["closest_snapshot"] is None

    @pytest.mark.asyncio
    async def test_cdx_non_list_response_ignored(self):
        """CDX returns a non-list JSON → recent_snapshots stays empty."""
        crawler = CyberWaybackCrawler()
        avail_payload = {"archived_snapshots": {}}

        call_count = 0

        async def _get_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_resp(200, avail_payload)
            return _mock_resp(200, {"error": "not a list"})

        with patch.object(crawler, "get", new=AsyncMock(side_effect=_get_side_effect)):
            result = await crawler.scrape("example.com")

        assert result.data["recent_snapshots"] == []
