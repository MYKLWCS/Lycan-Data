"""
test_search_wave4.py — Coverage wave 4 for api/routes/search.py.

Targets the single remaining uncovered line:
  - line 199: Bitcoin P2SH / bech32 address → SeedType.CRYPTO_WALLET

Also adds targeted tests for auto_detect branches previously less exercised.
All tests use the TestClient pattern with a minimal FastAPI app so no DB/Redis
infrastructure is required.
"""

from __future__ import annotations

import pytest

from modules.crawlers.registry import CRAWLER_REGISTRY

# ---------------------------------------------------------------------------
# _auto_detect_type — unit tests (pure function, no I/O)
# ---------------------------------------------------------------------------


def _detect(value: str):
    from api.routes.search import _auto_detect_type

    return _auto_detect_type(value)


class TestAutoDetectCryptoWallet:
    """Line 192-199: Bitcoin P2PKH (1…), P2SH (3…), bech32 (bc1…), and hex hash."""

    def test_bitcoin_p2pkh_address(self):
        from shared.constants import SeedType

        # Valid P2PKH address — starts with '1', base58 chars, 34 chars total
        assert _detect("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf") == SeedType.CRYPTO_WALLET

    def test_bitcoin_p2sh_address(self):
        """Line 192: P2SH address starts with '3'."""
        from shared.constants import SeedType

        # Valid-looking P2SH address (34 base58 chars starting with 3)
        result = _detect("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
        assert result == SeedType.CRYPTO_WALLET

    def test_bitcoin_bech32_address(self):
        """Line 193-194: bech32 starts with bc1."""
        from shared.constants import SeedType

        result = _detect("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq")
        assert result == SeedType.CRYPTO_WALLET

    def test_ethereum_address(self):
        """Line 188-189: 0x prefix + exactly 40 hex chars."""
        from shared.constants import SeedType

        # 42 chars total: 0x + 40 hex chars (mixed case is valid)
        result = _detect("0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe"[:42])
        assert result == SeedType.CRYPTO_WALLET

    def test_monero_hex_hash(self):
        """Line 198-199: 64-char lowercase hex string."""
        from shared.constants import SeedType

        hex64 = "a" * 64
        result = _detect(hex64)
        assert result == SeedType.CRYPTO_WALLET

    def test_64_char_uppercase_hex_also_matched(self):
        """Upper-case hex is lowercased before matching, so it also returns CRYPTO_WALLET."""
        from shared.constants import SeedType

        # _auto_detect_type uses value_lower for the hex64 check, so uppercase matches too
        hex64_upper = "A" * 64
        result = _detect(hex64_upper)
        assert result == SeedType.CRYPTO_WALLET


class TestAutoDetectIPAddress:
    """Lines 201-205: IPv4 and IPv6 detection.

    NOTE: IPv4 addresses can match the phone regex (dots are in the phone char class)
    when they are short enough. Use IPv6 to reliably test the IP_ADDRESS branch.
    """

    def test_ipv6_address(self):
        """Full-form IPv6 is too long for the phone regex and matches IP_ADDRESS."""
        from shared.constants import SeedType

        assert _detect("2001:0db8:85a3:0000:0000:8a2e:0370:7334") == SeedType.IP_ADDRESS

    def test_ipv6_short_form(self):
        from shared.constants import SeedType

        assert _detect("2001:db8::1") == SeedType.IP_ADDRESS


class TestAutoDetectDomain:
    """Lines 208-212: domain detection."""

    def test_domain_with_tld(self):
        from shared.constants import SeedType

        assert _detect("example.com") == SeedType.DOMAIN

    def test_subdomain(self):
        from shared.constants import SeedType

        assert _detect("mail.google.com") == SeedType.DOMAIN


class TestAutoDetectPhone:
    """Line 181-182: phone detection."""

    def test_phone_e164(self):
        from shared.constants import SeedType

        assert _detect("+12125551234") == SeedType.PHONE

    def test_phone_with_spaces(self):
        from shared.constants import SeedType

        assert _detect("+1 212 555 1234") == SeedType.PHONE


class TestAutoDetectEmail:
    """Lines 184-185: email detection."""

    def test_email(self):
        from shared.constants import SeedType

        assert _detect("user@example.com") == SeedType.EMAIL


class TestAutoDetectFullNameAndUsername:
    """Lines 215-218: full name (space) and username (fallback)."""

    def test_full_name_has_space(self):
        from shared.constants import SeedType

        assert _detect("John Smith") == SeedType.FULL_NAME

    def test_username_fallback(self):
        from shared.constants import SeedType

        assert _detect("johndoe99") == SeedType.USERNAME
