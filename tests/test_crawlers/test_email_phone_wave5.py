"""
test_email_phone_wave5.py — Coverage gap tests (wave 5).

Crawlers covered:
  email_emailrep       — lines 37-105 (entire scrape method)
  email_mx_validator   — lines 57-95 (scrape method body)
  phone_numlookup      — lines 41-110 (entire scrape method)
  email_breach         — lines 75-76, 80-82, 87, 124-126, 146-147
  phone_carrier        — lines 29, 46, 48, 50, 79-80, 103
  phone_truecaller     — lines 78, 88-90
  phone_fonefinder     — line 177

All external I/O is mocked; no real network calls are made.
"""

from __future__ import annotations

import socket
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
# email_emailrep.py
# Lines 37-105: entire scrape() method
# ===========================================================================


class TestEmailRepCrawler:
    def _make(self):
        from modules.crawlers.email_emailrep import EmailRepCrawler

        return EmailRepCrawler()

    # Lines 42-49: response is None → http_error
    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        """None response → error='http_error'."""
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("test@example.com")
        assert result.found is False
        assert result.error == "http_error"

    # Lines 51-58: 429 → rate_limited
    @pytest.mark.asyncio
    async def test_scrape_429_rate_limited(self):
        """429 status → error='rate_limited'."""
        crawler = self._make()
        resp = _mock_resp(429)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")
        assert result.found is False
        assert result.error == "rate_limited"

    # Lines 60-67: non-200 other status → http_{N}
    @pytest.mark.asyncio
    async def test_scrape_non200_status(self):
        """503 status → error='http_503'."""
        crawler = self._make()
        resp = _mock_resp(503)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")
        assert result.found is False
        assert result.error == "http_503"

    # Lines 60-67: 404 status → http_404
    @pytest.mark.asyncio
    async def test_scrape_404_status(self):
        """404 → error='http_404'."""
        crawler = self._make()
        resp = _mock_resp(404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")
        assert result.found is False
        assert result.error == "http_404"

    # Lines 69-78: JSON parse failure → invalid_json
    @pytest.mark.asyncio
    async def test_scrape_invalid_json(self):
        """JSON parse error → error='invalid_json'."""
        crawler = self._make()
        resp = _mock_resp(200)
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")
        assert result.found is False
        assert result.error == "invalid_json"

    # Lines 80-105: success path — reputation != "none" → found=True
    @pytest.mark.asyncio
    async def test_scrape_success_good_reputation(self):
        """Reputation not 'none' → found=True, data populated."""
        crawler = self._make()
        json_data = {
            "email": "test@example.com",
            "reputation": "high",
            "suspicious": False,
            "references": 5,
            "details": {
                "blacklisted": False,
                "malicious_activity": False,
                "credentials_leaked": True,
                "data_breach": True,
                "profiles": ["github", "twitter"],
                "spam": False,
                "deliverability": "DELIVERABLE",
                "days_since_domain_creation": 3650,
                "last_seen": "1 month ago",
            },
        }
        resp = _mock_resp(200, json_data=json_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("test@example.com")
        assert result.found is True
        assert result.data["reputation"] == "high"
        assert result.data["suspicious"] is False
        assert result.data["references"] == 5
        assert result.data["details"]["credentials_leaked"] is True
        assert result.data["details"]["profiles"] == ["github", "twitter"]

    # Lines 85: found = suspicious is True (reputation == "none" but suspicious=True)
    @pytest.mark.asyncio
    async def test_scrape_success_suspicious_flag(self):
        """reputation='none' but suspicious=True → found=True."""
        crawler = self._make()
        json_data = {
            "email": "suspicious@example.com",
            "reputation": "none",
            "suspicious": True,
            "references": 0,
            "details": {},
        }
        resp = _mock_resp(200, json_data=json_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("suspicious@example.com")
        assert result.found is True
        assert result.data["suspicious"] is True

    # Lines 85: both reputation=="none" and suspicious==False → found=False
    @pytest.mark.asyncio
    async def test_scrape_success_not_found(self):
        """reputation='none' and suspicious=False → found=False."""
        crawler = self._make()
        json_data = {
            "email": "nobody@example.com",
            "reputation": "none",
            "suspicious": False,
            "references": 0,
            "details": {},
        }
        resp = _mock_resp(200, json_data=json_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("nobody@example.com")
        assert result.found is False
        assert result.data["reputation"] == "none"

    # Lines 87-103: details dict with missing keys uses defaults
    @pytest.mark.asyncio
    async def test_scrape_success_missing_detail_keys(self):
        """Details dict partially populated — missing keys return None/[]."""
        crawler = self._make()
        json_data = {
            "reputation": "low",
            "suspicious": False,
            "references": 1,
            "details": {"blacklisted": True},
        }
        resp = _mock_resp(200, json_data=json_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("partial@example.com")
        assert result.found is True
        assert result.data["details"]["blacklisted"] is True
        assert result.data["details"]["profiles"] == []
        assert result.data["details"]["malicious_activity"] is None
        assert result.data["email"] == "partial@example.com"

    # Lines 37-38: email is stripped and lowercased before use
    @pytest.mark.asyncio
    async def test_scrape_strips_and_lowercases_identifier(self):
        """Identifier is stripped + lowercased; URL uses normalised form."""
        crawler = self._make()
        captured_urls = []

        async def capturing_get(url, **kwargs):
            captured_urls.append(url)
            return _mock_resp(200, json_data={"reputation": "none", "suspicious": False})

        with patch.object(crawler, "get", new=capturing_get):
            await crawler.scrape("  TEST@EXAMPLE.COM  ")

        assert len(captured_urls) == 1
        assert "test@example.com" in captured_urls[0]


# ===========================================================================
# email_mx_validator.py
# Lines 57-95: scrape() method body
# ===========================================================================


class TestEmailMXValidatorCrawler:
    def _make(self):
        from modules.crawlers.email_mx_validator import EmailMXValidatorCrawler

        return EmailMXValidatorCrawler()

    # Lines 57-64: no "@" in identifier → Not an email address
    @pytest.mark.asyncio
    async def test_scrape_not_an_email(self):
        """No '@' in identifier → error='Not an email address'."""
        crawler = self._make()
        result = await crawler.scrape("notanemail")
        assert result.found is False
        assert result.error == "Not an email address"

    # Lines 68-73: dns.resolver.resolve succeeds → mx_available=True, records populated
    @pytest.mark.asyncio
    async def test_scrape_dns_resolve_success(self):
        """dns.resolver.resolve returns records → mx_available=True, found=True."""
        import sys

        crawler = self._make()

        mock_record_1 = MagicMock()
        mock_record_1.preference = 10
        mock_record_1.exchange = "mail.example.com."
        mock_record_2 = MagicMock()
        mock_record_2.preference = 20
        mock_record_2.exchange = "mail2.example.com."

        mock_dns_resolver = MagicMock()
        mock_dns_resolver.resolve.return_value = [mock_record_1, mock_record_2]
        mock_dns = MagicMock()
        mock_dns.resolver = mock_dns_resolver

        with patch.dict(sys.modules, {"dns": mock_dns, "dns.resolver": mock_dns_resolver}):
            result = await crawler.scrape("user@example.com")

        assert result.found is True
        assert result.data["mx_available"] is True
        assert len(result.data["mx_records"]) == 2
        assert result.data["domain"] == "example.com"
        assert result.data["is_disposable"] is False

    # Lines 74-79: dns.resolver.resolve raises → socket fallback succeeds → mx_available=True
    @pytest.mark.asyncio
    async def test_scrape_dns_fails_socket_fallback_success(self):
        """DNS exception → socket.gethostbyname succeeds → mx_available=True, mx_records=[]."""
        import sys

        crawler = self._make()

        mock_dns_resolver = MagicMock()
        mock_dns_resolver.resolve.side_effect = Exception("DNS failure")
        mock_dns = MagicMock()
        mock_dns.resolver = mock_dns_resolver

        with (
            patch.dict(sys.modules, {"dns": mock_dns, "dns.resolver": mock_dns_resolver}),
            patch("socket.gethostbyname", return_value="93.184.216.34"),
        ):
            result = await crawler.scrape("user@example.com")

        assert result.found is True
        assert result.data["mx_available"] is True
        assert result.data["mx_records"] == []

    # Lines 80-82: dns.resolver raises + socket.gaierror → mx_available=False
    @pytest.mark.asyncio
    async def test_scrape_dns_fails_socket_gaierror(self):
        """DNS exception → socket.gaierror → mx_available=False, found=False."""
        import sys

        crawler = self._make()

        mock_dns_resolver = MagicMock()
        mock_dns_resolver.resolve.side_effect = Exception("DNS failure")
        mock_dns = MagicMock()
        mock_dns.resolver = mock_dns_resolver

        with (
            patch.dict(sys.modules, {"dns": mock_dns, "dns.resolver": mock_dns_resolver}),
            patch("socket.gethostbyname", side_effect=socket.gaierror("no such host")),
        ):
            result = await crawler.scrape("user@nonexistent-domain-xyz.com")

        assert result.found is False
        assert result.data["mx_available"] is False
        assert result.data["mx_records"] == []

    # Line 84: is_disposable = True for mailinator.com
    @pytest.mark.asyncio
    async def test_scrape_disposable_domain(self):
        """Domain in _DISPOSABLE_DOMAINS → is_disposable=True."""
        import sys

        crawler = self._make()

        mock_record = MagicMock()
        mock_record.preference = 10
        mock_record.exchange = "mail.mailinator.com."

        mock_dns_resolver = MagicMock()
        mock_dns_resolver.resolve.return_value = [mock_record]
        mock_dns = MagicMock()
        mock_dns.resolver = mock_dns_resolver

        with patch.dict(sys.modules, {"dns": mock_dns, "dns.resolver": mock_dns_resolver}):
            result = await crawler.scrape("throwaway@mailinator.com")

        assert result.data["is_disposable"] is True
        assert result.data["domain"] == "mailinator.com"

    # Lines 91: mx_records[:5] truncates to 5
    @pytest.mark.asyncio
    async def test_scrape_mx_records_truncated_to_five(self):
        """More than 5 MX records are truncated to 5 in result."""
        import sys

        crawler = self._make()

        records = []
        for i in range(8):
            r = MagicMock()
            r.preference = i * 10
            r.exchange = f"mail{i}.example.com."
            records.append(r)

        mock_dns_resolver = MagicMock()
        mock_dns_resolver.resolve.return_value = records
        mock_dns = MagicMock()
        mock_dns.resolver = mock_dns_resolver

        with patch.dict(sys.modules, {"dns": mock_dns, "dns.resolver": mock_dns_resolver}):
            result = await crawler.scrape("user@example.com")

        assert len(result.data["mx_records"]) == 5

    # Lines 66: domain extracted correctly from multi-part identifier
    @pytest.mark.asyncio
    async def test_scrape_domain_extracted_from_identifier(self):
        """Domain portion is the part after '@', lowercased."""
        import sys

        crawler = self._make()

        mock_record = MagicMock()
        mock_record.preference = 5
        mock_record.exchange = "mail.CORP.COM."

        mock_dns_resolver = MagicMock()
        mock_dns_resolver.resolve.return_value = [mock_record]
        mock_dns = MagicMock()
        mock_dns.resolver = mock_dns_resolver

        with patch.dict(sys.modules, {"dns": mock_dns, "dns.resolver": mock_dns_resolver}):
            result = await crawler.scrape("User.Name@CORP.COM")

        assert result.data["domain"] == "corp.com"
        assert result.data["email"] == "User.Name@CORP.COM"

    # dns module not installed: import inside try raises ImportError → socket path
    @pytest.mark.asyncio
    async def test_scrape_dns_not_installed_socket_fallback(self):
        """ImportError on dns.resolver → socket fallback path."""
        crawler = self._make()

        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "dns" in name:
                raise ImportError("No module named 'dns'")
            return real_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=mock_import),
            patch("socket.gethostbyname", return_value="1.2.3.4"),
        ):
            result = await crawler.scrape("user@example.com")

        assert result.found is True
        assert result.data["mx_available"] is True
        assert result.data["mx_records"] == []


# ===========================================================================
# phone_numlookup.py
# Lines 41-110: entire scrape() method
# ===========================================================================


class TestPhoneNumLookupCrawler:
    def _make(self):
        from modules.crawlers.phone_numlookup import PhoneNumLookupCrawler

        return PhoneNumLookupCrawler()

    # Lines 44-45: api_key present → uses key URL
    @pytest.mark.asyncio
    async def test_scrape_uses_key_url_when_api_key_set(self):
        """When numlookup_api_key is set, the key is included in the URL."""
        crawler = self._make()
        captured_urls = []

        async def capturing_get(url, **kwargs):
            captured_urls.append(url)
            return _mock_resp(200, json_data={"valid": True, "number_type": "mobile"})

        with (
            patch("modules.crawlers.phone_numlookup.settings") as mock_settings,
            patch.object(crawler, "get", new=capturing_get),
        ):
            mock_settings.numlookup_api_key = "testkey123"
            result = await crawler.scrape("+12025551234")

        assert len(captured_urls) == 1
        assert "testkey123" in captured_urls[0]
        assert "apikey" in captured_urls[0]

    # Lines 46-47: no api_key → uses keyless URL
    @pytest.mark.asyncio
    async def test_scrape_uses_keyless_url_when_no_api_key(self):
        """When numlookup_api_key is empty, the keyless URL is used."""
        crawler = self._make()
        captured_urls = []

        async def capturing_get(url, **kwargs):
            captured_urls.append(url)
            return _mock_resp(200, json_data={"valid": False})

        with (
            patch("modules.crawlers.phone_numlookup.settings") as mock_settings,
            patch.object(crawler, "get", new=capturing_get),
        ):
            mock_settings.numlookup_api_key = ""
            result = await crawler.scrape("+12025551234")

        assert len(captured_urls) == 1
        assert "apikey" not in captured_urls[0]

    # Lines 51-58: response is None → http_error
    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        """None response → error='http_error'."""
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "http_error"

    # Lines 60-67: 401 → unauthorized_no_api_key
    @pytest.mark.asyncio
    async def test_scrape_401_unauthorized(self):
        """401 status → error='unauthorized_no_api_key'."""
        crawler = self._make()
        resp = _mock_resp(401)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "unauthorized_no_api_key"

    # Lines 69-76: 429 → rate_limited
    @pytest.mark.asyncio
    async def test_scrape_429_rate_limited(self):
        """429 status → error='rate_limited'."""
        crawler = self._make()
        resp = _mock_resp(429)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "rate_limited"

    # Lines 78-85: non-200 other → http_{N}
    @pytest.mark.asyncio
    async def test_scrape_non200_other(self):
        """503 status → error='http_503'."""
        crawler = self._make()
        resp = _mock_resp(503)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "http_503"

    # Lines 87-96: JSON parse error → invalid_json
    @pytest.mark.asyncio
    async def test_scrape_invalid_json(self):
        """JSON parse failure → error='invalid_json'."""
        crawler = self._make()
        resp = _mock_resp(200)
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "invalid_json"

    # Lines 98-110: success path — valid=True → found=True
    @pytest.mark.asyncio
    async def test_scrape_success_valid_number(self):
        """valid=True → found=True, all fields populated in result.data."""
        crawler = self._make()
        json_data = {
            "valid": True,
            "number_type": "mobile",
            "carrier": "AT&T",
            "country_code": "US",
            "country_name": "United States",
            "formatted": "+1 (202) 555-1234",
        }
        resp = _mock_resp(200, json_data=json_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is True
        assert result.data["number_type"] == "mobile"
        assert result.data["carrier"] == "AT&T"
        assert result.data["country_code"] == "US"
        assert result.data["country_name"] == "United States"
        assert result.data["valid"] is True
        assert result.data["formatted"] == "+1 (202) 555-1234"

    # Lines 98-99: valid=False → found=False
    @pytest.mark.asyncio
    async def test_scrape_success_invalid_number(self):
        """valid=False → found=False."""
        crawler = self._make()
        json_data = {"valid": False, "number_type": None, "carrier": None}
        resp = _mock_resp(200, json_data=json_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+19995550000")
        assert result.found is False
        assert result.data["valid"] is False

    # Lines 41: identifier is stripped
    @pytest.mark.asyncio
    async def test_scrape_strips_identifier(self):
        """Identifier whitespace is stripped before URL construction."""
        crawler = self._make()
        captured_urls = []

        async def capturing_get(url, **kwargs):
            captured_urls.append(url)
            return _mock_resp(200, json_data={"valid": False})

        with patch.object(crawler, "get", new=capturing_get):
            await crawler.scrape("  +12025551234  ")

        assert len(captured_urls) == 1
        assert "+12025551234" in captured_urls[0]
        assert "  " not in captured_urls[0]


# ===========================================================================
# email_breach.py
# Lines 75-76, 80-82, 87, 124-126, 146-147
# ===========================================================================


class TestEmailBreachSubMethods:
    def _make(self):
        from modules.crawlers.email_breach import EmailBreachCrawler

        return EmailBreachCrawler()

    # Lines 74-76: _check_psbdmp — None response → return []
    @pytest.mark.asyncio
    async def test_check_psbdmp_none_response(self):
        """resp is None → _check_psbdmp returns []."""
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._check_psbdmp("test@example.com")
        assert result == []

    # Lines 74-76: _check_psbdmp — non-200 status → return []
    @pytest.mark.asyncio
    async def test_check_psbdmp_non200_response(self):
        """non-200 response → _check_psbdmp returns []."""
        crawler = self._make()
        resp = _mock_resp(403)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_psbdmp("test@example.com")
        assert result == []

    # Lines 80-82: _check_psbdmp — JSON parse error → return []
    @pytest.mark.asyncio
    async def test_check_psbdmp_json_error(self):
        """JSON parse error → _check_psbdmp returns []."""
        crawler = self._make()
        resp = _mock_resp(200)
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_psbdmp("test@example.com")
        assert result == []

    # Line 84-86 (data is list path) + line 87 (empty list → []): data=[] → return []
    @pytest.mark.asyncio
    async def test_check_psbdmp_empty_list_data(self):
        """JSON returns empty list → _check_psbdmp returns []."""
        crawler = self._make()
        resp = _mock_resp(200, json_data=[])
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_psbdmp("test@example.com")
        assert result == []

    # Line 84 (data.get("data", []) path) + line 87: data={"data": []} → return []
    @pytest.mark.asyncio
    async def test_check_psbdmp_empty_data_key(self):
        """JSON returns {"data": []} → _check_psbdmp returns []."""
        crawler = self._make()
        resp = _mock_resp(200, json_data={"data": []})
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_psbdmp("test@example.com")
        assert result == []

    # Lines 86-96: data is a list with items → returns mapped records
    @pytest.mark.asyncio
    async def test_check_psbdmp_with_items(self):
        """Non-empty list data → returns mapped paste records."""
        crawler = self._make()
        items = [{"id": "abc123", "text": "leaked data here"}]
        resp = _mock_resp(200, json_data=items)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_psbdmp("test@example.com")
        assert len(result) == 1
        assert result[0]["source"] == "psbdmp"
        assert "psbdmp:abc123" in result[0]["name"]

    # Lines 108-114: _check_github — None response → return []
    @pytest.mark.asyncio
    async def test_check_github_none_response(self):
        """None response → _check_github returns []."""
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._check_github("test@example.com")
        assert result == []

    # Lines 108-114: _check_github — non-200 status → return []
    @pytest.mark.asyncio
    async def test_check_github_non200_response(self):
        """non-200 (403 rate-limited) → _check_github returns []."""
        crawler = self._make()
        resp = _mock_resp(403)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_github("test@example.com")
        assert result == []

    # Lines 116-119: _check_github — JSON parse error → return []
    @pytest.mark.asyncio
    async def test_check_github_json_error(self):
        """JSON parse error → _check_github returns []."""
        crawler = self._make()
        resp = _mock_resp(200)
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_github("test@example.com")
        assert result == []

    # Lines 122-136: _check_github — success with items
    @pytest.mark.asyncio
    async def test_check_github_success_with_items(self):
        """200 with items → returns mapped github records."""
        crawler = self._make()
        json_data = {
            "items": [
                {
                    "repository": {"full_name": "owner/repo"},
                    "path": "config/settings.py",
                }
            ]
        }
        resp = _mock_resp(200, json_data=json_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_github("test@example.com")
        assert len(result) == 1
        assert result[0]["source"] == "github"
        assert "owner/repo" in result[0]["name"]

    # Lines 144-147: _check_leakcheck — None response → return []
    @pytest.mark.asyncio
    async def test_check_leakcheck_none_response(self):
        """None response → _check_leakcheck returns []."""
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler._check_leakcheck("test@example.com")
        assert result == []

    # Lines 144-147: _check_leakcheck — non-200 → return []
    @pytest.mark.asyncio
    async def test_check_leakcheck_non200_response(self):
        """non-200 status → _check_leakcheck returns []."""
        crawler = self._make()
        resp = _mock_resp(500)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_leakcheck("test@example.com")
        assert result == []

    # Lines 149-153: _check_leakcheck — JSON parse error → return []
    @pytest.mark.asyncio
    async def test_check_leakcheck_json_error(self):
        """JSON parse error → _check_leakcheck returns []."""
        crawler = self._make()
        resp = _mock_resp(200)
        resp.json.side_effect = ValueError("bad json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_leakcheck("test@example.com")
        assert result == []

    # Lines 155-156: _check_leakcheck — success=False → return []
    @pytest.mark.asyncio
    async def test_check_leakcheck_not_found(self):
        """success=False → _check_leakcheck returns []."""
        crawler = self._make()
        resp = _mock_resp(200, json_data={"success": False, "found": 0})
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_leakcheck("test@example.com")
        assert result == []

    # Lines 158-167: _check_leakcheck — found with sources
    @pytest.mark.asyncio
    async def test_check_leakcheck_success_with_sources(self):
        """success=True, found>0 → returns mapped leakcheck records."""
        crawler = self._make()
        json_data = {"success": True, "found": 2, "sources": ["BreachA", "BreachB"]}
        resp = _mock_resp(200, json_data=json_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler._check_leakcheck("test@example.com")
        assert len(result) == 2
        assert result[0]["source"] == "leakcheck"
        assert result[0]["name"] == "BreachA"

    # Full scrape integration: all three sources hit
    @pytest.mark.asyncio
    async def test_scrape_combines_all_sources(self):
        """scrape() aggregates results from all three sub-methods."""
        crawler = self._make()

        psbdmp_resp = _mock_resp(200, json_data=[{"id": "p1", "text": "data"}])
        github_resp = _mock_resp(200, json_data={"items": []})
        leakcheck_resp = _mock_resp(200, json_data={"success": False})

        call_count = 0

        async def multi_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "psbdmp" in url:
                return psbdmp_resp
            elif "github" in url:
                return github_resp
            elif "leakcheck" in url:
                return leakcheck_resp
            return None

        with patch.object(crawler, "get", new=multi_get):
            result = await crawler.scrape("test@example.com")

        assert result.found is True
        assert result.data["breach_count"] == 1
        assert "psbdmp" in result.data["checked_sources"]
        assert "github" in result.data["checked_sources"]
        assert "leakcheck" in result.data["checked_sources"]


# ===========================================================================
# phone_carrier.py
# Lines 29 (VOIP), 46 (_is_burner_carrier body), 48, 50, 79-80, 103
# ===========================================================================


class TestDetectLineType:
    """Tests for _detect_line_type() standalone function — all branches."""

    def _fn(self, text):
        from modules.crawlers.phone_carrier import _detect_line_type

        return _detect_line_type(text)

    # Line 29: "voip" in text → LineType.VOIP
    def test_voip_detection(self):
        """Text containing 'voip' → VOIP."""
        from shared.constants import LineType

        assert self._fn("This is a VoIP service") == LineType.VOIP

    def test_voip_detection_lowercase(self):
        """'voip' lowercase → VOIP."""
        from shared.constants import LineType

        assert self._fn("voip provider registered") == LineType.VOIP

    # Line 43: "mobile" → MOBILE
    def test_mobile_detection(self):
        """'mobile' in text → MOBILE."""
        from shared.constants import LineType

        assert self._fn("AT&T Mobile Wireless") == LineType.MOBILE

    # Line 43: "wireless" → MOBILE
    def test_wireless_detection(self):
        """'wireless' in text → MOBILE."""
        from shared.constants import LineType

        assert self._fn("T-Mobile Wireless USA") == LineType.MOBILE

    # Line 43: "cellular" → MOBILE
    def test_cellular_detection(self):
        """'cellular' in text → MOBILE."""
        from shared.constants import LineType

        assert self._fn("Verizon Cellular Network") == LineType.MOBILE

    # Line 45: "landline" → LANDLINE
    def test_landline_detection(self):
        """'landline' in text → LANDLINE."""
        from shared.constants import LineType

        assert self._fn("standard landline service") == LineType.LANDLINE

    # Line 45: "land line" → LANDLINE
    def test_land_line_two_words(self):
        """'land line' (two words) → LANDLINE."""
        from shared.constants import LineType

        assert self._fn("traditional land line") == LineType.LANDLINE

    # Line 45: "wireline" → LANDLINE
    def test_wireline_detection(self):
        """'wireline' in text → LANDLINE."""
        from shared.constants import LineType

        assert self._fn("wireline PSTN service") == LineType.LANDLINE

    # Line 47: "prepaid" → PREPAID (line 48)
    def test_prepaid_detection(self):
        """'prepaid' in text → PREPAID."""
        from shared.constants import LineType

        assert self._fn("TracFone prepaid plan") == LineType.PREPAID

    # Line 47: "pre-paid" → PREPAID (line 48)
    def test_pre_paid_hyphen(self):
        """'pre-paid' in text → PREPAID."""
        from shared.constants import LineType

        assert self._fn("pre-paid calling card") == LineType.PREPAID

    # Lines 49-50: "toll" and "free" → TOLL_FREE
    def test_toll_free_detection(self):
        """Both 'toll' and 'free' in text → TOLL_FREE."""
        from shared.constants import LineType

        assert self._fn("toll free number 800") == LineType.TOLL_FREE

    # Line 51: nothing matches → UNKNOWN
    def test_unknown_fallback(self):
        """No matching keyword → UNKNOWN."""
        from shared.constants import LineType

        assert self._fn("some random carrier text") == LineType.UNKNOWN

    def test_empty_string_returns_unknown(self):
        """Empty string → UNKNOWN."""
        from shared.constants import LineType

        assert self._fn("") == LineType.UNKNOWN

    # VOIP takes priority over mobile (first match wins)
    def test_voip_priority_over_mobile(self):
        """'voip' appears before 'mobile' in conditions → VOIP wins."""
        from shared.constants import LineType

        assert self._fn("voip mobile service") == LineType.VOIP

    # "toll" alone without "free" → UNKNOWN (not TOLL_FREE)
    def test_toll_without_free_is_unknown(self):
        """'toll' without 'free' → UNKNOWN."""
        from shared.constants import LineType

        assert self._fn("toll road billing") == LineType.UNKNOWN


class TestIsBurnerCarrier:
    """Tests for _is_burner_carrier() — lines 46-57."""

    def _fn(self, name):
        from modules.crawlers.phone_carrier import _is_burner_carrier

        return _is_burner_carrier(name)

    # Line 57: known burner substring → True
    def test_known_burner_textnow(self):
        """'textnow' substring → True."""
        assert self._fn("TextNow Inc.") is True

    def test_known_burner_google_voice(self):
        """'google voice' substring → True."""
        assert self._fn("Google Voice Services") is True

    def test_known_burner_twilio(self):
        """'twilio' substring → True."""
        assert self._fn("Twilio Carrier") is True

    def test_known_burner_case_insensitive(self):
        """Match is case-insensitive."""
        assert self._fn("TWILIO COMMUNICATIONS") is True

    # Not a burner carrier → False
    def test_clean_carrier(self):
        """Legitimate carrier → False."""
        assert self._fn("AT&T Mobility LLC") is False

    def test_empty_string(self):
        """Empty string → False."""
        assert self._fn("") is False


class TestPhoneCarrierScrape:
    """Tests for CarrierLookupCrawler.scrape() — lines 79-80, 103."""

    def _make(self):
        from modules.crawlers.phone_carrier import CarrierLookupCrawler

        c = CarrierLookupCrawler.__new__(CarrierLookupCrawler)
        c.platform = "phone_carrier"
        c.source_reliability = 0.65
        return c

    # Lines 79-80: international number → uses number= URL param
    @pytest.mark.asyncio
    async def test_scrape_international_number_uses_e164_url(self):
        """Non-US number → URL uses number=digits param."""
        crawler = self._make()
        captured_urls = []

        async def capturing_get(url, **kwargs):
            captured_urls.append(url)
            return _mock_resp(
                200,
                text="<html><table><tr><td>Carrier</td><td>Vodacom South Africa</td></tr>"
                "<tr><td>Type</td><td>mobile wireless</td></tr></table></html>",
            )

        with patch.object(crawler, "get", new=capturing_get):
            result = await crawler.scrape("+27821234567")

        assert len(captured_urls) == 1
        assert "number=" in captured_urls[0]
        assert "npa=" not in captured_urls[0]

    # Line 103: non-200 non-404 → http_{N}
    @pytest.mark.asyncio
    async def test_scrape_non200_non404(self):
        """500 response → error='http_500'."""
        crawler = self._make()
        resp = _mock_resp(500)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "http_500"

    # VOIP carrier — is_voip=True and is_burner=True
    @pytest.mark.asyncio
    async def test_scrape_voip_carrier_sets_flags(self):
        """VoIP line type → is_voip=True, is_burner=True."""
        from shared.constants import LineType

        crawler = self._make()
        html = (
            "<html><table>"
            "<tr><td>Carrier</td><td>Twilio Inc.</td></tr>"
            "</table><p>VoIP provider</p></html>"
        )
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is True
        assert result.data["is_voip"] is True
        assert result.data["is_burner"] is True
        assert result.data["line_type"] == LineType.VOIP.value


# ===========================================================================
# phone_truecaller.py
# Lines 78, 88-90
# ===========================================================================


class TestTruecallerCrawler:
    def _make(self):
        from modules.crawlers.phone_truecaller import TruecallerCrawler

        c = TruecallerCrawler.__new__(TruecallerCrawler)
        c.platform = "phone_truecaller"
        c.source_reliability = 0.70
        return c

    # Line 78: non-200/non-404 → http_{N}
    @pytest.mark.asyncio
    async def test_scrape_non200_non404(self):
        """500 response → error='http_500'."""
        crawler = self._make()
        resp = _mock_resp(503)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "http_503"

    # Lines 88-90: JSON parse error → json_parse_error
    @pytest.mark.asyncio
    async def test_scrape_json_parse_error(self):
        """JSON parse failure → error='json_parse_error'."""
        crawler = self._make()
        resp = _mock_resp(200)
        resp.json.side_effect = ValueError("malformed json")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "json_parse_error"

    # Line 78 path (scrape method call) + full success path
    @pytest.mark.asyncio
    async def test_scrape_success_with_data(self):
        """200 with valid payload → found=True, name/carrier/score set."""
        crawler = self._make()
        json_data = {
            "data": [
                {
                    "name": "John Doe",
                    "phones": [{"carrier": "Verizon", "type": "MOBILE"}],
                    "score": 0.85,
                    "tags": [{"tag": "business"}, "spam"],
                }
            ]
        }
        resp = _mock_resp(200, json_data=json_data)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is True
        assert result.data["name"] == "John Doe"
        assert result.data["carrier"] == "Verizon"
        assert result.data["score"] == 0.85

    # None response → http_error
    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        """None response → error='http_error'."""
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "http_error"

    # 404 → not_found
    @pytest.mark.asyncio
    async def test_scrape_404_not_found(self):
        """404 → error='not_found'."""
        crawler = self._make()
        resp = _mock_resp(404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "not_found"

    # Empty data list → no_data
    @pytest.mark.asyncio
    async def test_scrape_empty_data_list(self):
        """200 with empty data list → error='no_data'."""
        crawler = self._make()
        resp = _mock_resp(200, json_data={"data": []})
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "no_data"

    # Line 88-90: exception type preserved in warning message (exc passed to logger)
    @pytest.mark.asyncio
    async def test_scrape_json_parse_error_various_exceptions(self):
        """Any exception from response.json() → json_parse_error."""
        crawler = self._make()
        resp = _mock_resp(200)
        resp.json.side_effect = TypeError("not a dict")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "json_parse_error"


# ===========================================================================
# phone_fonefinder.py
# Line 177: result["state"] = value.strip().upper()[:2]
# ===========================================================================


class TestFoneFinderCrawler:
    def _make(self):
        from modules.crawlers.phone_fonefinder import FoneFinderCrawler

        c = FoneFinderCrawler.__new__(FoneFinderCrawler)
        c.platform = "phone_fonefinder"
        c.source_reliability = 0.60
        return c

    # Line 177: "state" label in table row → result["state"] = value[:2].upper()
    def test_parse_response_state_label_branch(self):
        """Table row with 'state' label → state extracted via value.strip().upper()[:2]."""
        from modules.crawlers.phone_fonefinder import FoneFinderCrawler

        crawler = FoneFinderCrawler.__new__(FoneFinderCrawler)
        # Use a label that contains "state" but not "city"/"location"/"city/state"
        html = """<html><body>
          <table>
            <tr><td>Carrier</td><td>Verizon Wireless</td></tr>
            <tr><td>State/Province</td><td>texas</td></tr>
          </table>
          <p>mobile service</p>
        </body></html>"""
        result = crawler._parse_response(html, "US")
        assert result["state"] == "TE"

    def test_parse_response_state_label_two_char_state(self):
        """State label with two-letter abbreviation value."""
        from modules.crawlers.phone_fonefinder import FoneFinderCrawler

        crawler = FoneFinderCrawler.__new__(FoneFinderCrawler)
        html = """<html><body>
          <table>
            <tr><td>Carrier</td><td>AT&amp;T Mobility</td></tr>
            <tr><td>State</td><td>  CA  </td></tr>
          </table>
        </body></html>"""
        result = crawler._parse_response(html, "US")
        assert result["state"] == "CA"

    def test_parse_response_state_label_longer_value_truncated(self):
        """State label with longer value → only first 2 chars kept."""
        from modules.crawlers.phone_fonefinder import FoneFinderCrawler

        crawler = FoneFinderCrawler.__new__(FoneFinderCrawler)
        html = """<html><body>
          <table>
            <tr><td>Carrier</td><td>T-Mobile USA</td></tr>
            <tr><td>State</td><td>Florida</td></tr>
          </table>
        </body></html>"""
        result = crawler._parse_response(html, "US")
        assert result["state"] == "FL"

    # Full scrape integration with state label in HTML
    @pytest.mark.asyncio
    async def test_scrape_with_state_label(self):
        """Full scrape where HTML has a 'State' label row → state in result.data."""
        crawler = self._make()
        html = """<html><body>
          <table>
            <tr><td>Carrier</td><td>Sprint PCS</td></tr>
            <tr><td>State</td><td>NY</td></tr>
          </table>
          <p>mobile wireless</p>
        </body></html>"""
        resp = _mock_resp(200, text=html)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12125551234")
        assert result.found is True
        assert result.data["state"] == "NY"
        assert result.data["carrier_name"] == "Sprint PCS"

    # None response → http_error
    @pytest.mark.asyncio
    async def test_scrape_none_response(self):
        """None response → error='http_error'."""
        crawler = self._make()
        with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "http_error"

    # 404 → not_found
    @pytest.mark.asyncio
    async def test_scrape_404_not_found(self):
        """404 → error='not_found'."""
        crawler = self._make()
        resp = _mock_resp(404)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "not_found"

    # non-200/non-404 → http_{N}
    @pytest.mark.asyncio
    async def test_scrape_non200_non404(self):
        """500 → error='http_500'."""
        crawler = self._make()
        resp = _mock_resp(500)
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "http_500"

    # No carrier data extracted → no_data
    @pytest.mark.asyncio
    async def test_scrape_no_carrier_data(self):
        """Empty HTML → no carrier found → error='no_data'."""
        crawler = self._make()
        resp = _mock_resp(200, text="<html><body><p>No information available.</p></body></html>")
        with patch.object(crawler, "get", new=AsyncMock(return_value=resp)):
            result = await crawler.scrape("+12025551234")
        assert result.found is False
        assert result.error == "no_data"
