"""Tests for modules/enrichers/data_verifiers.py — phone, email, address verification."""

import pytest

from modules.enrichers.data_verifiers import (
    AddressVerifier,
    DataVerifier,
    EmailVerifier,
    PhoneVerifier,
    TypeVerificationResult,
    VerificationLevel,
)


# ── PhoneVerifier ────────────────────────────────────────────────────────────


class TestPhoneVerifier:
    def setup_method(self):
        self.verifier = PhoneVerifier()

    def test_valid_us_10_digit(self):
        # 202 is a valid DC area code; 555 numbers are fictional and rejected by phonenumbers
        result = self.verifier.format_validation("2025551234")
        assert result.level >= VerificationLevel.FORMAT_VALID
        assert result.details["is_valid"] is True

    def test_valid_us_with_country_code(self):
        result = self.verifier.format_validation("+12025551234")
        assert result.level >= VerificationLevel.FORMAT_VALID

    def test_valid_us_formatted(self):
        result = self.verifier.format_validation("(202) 555-1234")
        assert result.level >= VerificationLevel.FORMAT_VALID

    def test_too_short(self):
        result = self.verifier.format_validation("123")
        assert result.level == VerificationLevel.UNVERIFIED

    def test_empty_string(self):
        result = self.verifier.format_validation("")
        assert result.level == VerificationLevel.UNVERIFIED

    def test_carrier_lookup_returns_dict(self):
        info = self.verifier.carrier_lookup("+12025551234")
        assert isinstance(info, dict)
        assert "carrier" in info

    def test_verify_complete_valid(self):
        result = self.verifier.verify_complete("+12025551234")
        assert result.level >= VerificationLevel.FORMAT_VALID
        assert result.field_type == "phone"


# ── EmailVerifier ────────────────────────────────────────────────────────────


class TestEmailVerifier:
    def setup_method(self):
        self.verifier = EmailVerifier()

    def test_valid_email(self):
        result = self.verifier.syntax_validation("john@example.com")
        assert result.level == VerificationLevel.FORMAT_VALID
        assert result.details["is_valid"] is True
        assert result.details["domain"] == "example.com"

    def test_invalid_email_no_at(self):
        result = self.verifier.syntax_validation("john.example.com")
        assert result.level == VerificationLevel.UNVERIFIED

    def test_invalid_email_no_tld(self):
        result = self.verifier.syntax_validation("john@example")
        assert result.level == VerificationLevel.UNVERIFIED

    def test_disposable_domain_flagged(self):
        result = self.verifier.syntax_validation("test@mailinator.com")
        assert result.details["is_disposable"] is True

    def test_non_disposable_domain(self):
        result = self.verifier.syntax_validation("john@gmail.com")
        assert result.details["is_disposable"] is False

    def test_role_based_email_flagged(self):
        result = self.verifier.syntax_validation("support@company.com")
        assert result.details["is_role_based"] is True

    def test_personal_email_not_role_based(self):
        result = self.verifier.syntax_validation("john.smith@company.com")
        assert result.details["is_role_based"] is False

    def test_empty_email(self):
        result = self.verifier.syntax_validation("")
        assert result.level == VerificationLevel.UNVERIFIED

    def test_verify_complete_returns_result(self):
        result = self.verifier.verify_complete("test@example.com")
        assert isinstance(result, TypeVerificationResult)
        assert result.field_type == "email"


# ── AddressVerifier ──────────────────────────────────────────────────────────


class TestAddressVerifier:
    def setup_method(self):
        self.verifier = AddressVerifier()

    def test_valid_address(self):
        result = self.verifier.format_validation(
            "123 Main St", city="Springfield", state="IL", zip_code="62704"
        )
        assert result.level == VerificationLevel.FORMAT_VALID
        assert result.details["address_type"] == "residential"

    def test_po_box_detected(self):
        result = self.verifier.format_validation("P.O. Box 123")
        assert result.details["address_type"] == "po_box"

    def test_commercial_address(self):
        result = self.verifier.format_validation("100 Broadway Suite 200")
        assert result.details["address_type"] == "commercial"

    def test_apartment_address(self):
        result = self.verifier.format_validation("456 Oak Ave Apt 3B")
        assert result.details["address_type"] == "residential_apartment"

    def test_too_short_invalid(self):
        result = self.verifier.format_validation("Hi")
        assert result.level == VerificationLevel.UNVERIFIED

    def test_empty_address(self):
        result = self.verifier.format_validation("")
        assert result.level == VerificationLevel.UNVERIFIED

    def test_zip_validation_valid(self):
        result = self.verifier.format_validation("123 Main", zip_code="62704")
        assert result.details["zip_valid"] is True

    def test_zip_validation_zip_plus4(self):
        result = self.verifier.format_validation("123 Main", zip_code="62704-1234")
        assert result.details["zip_valid"] is True

    def test_zip_validation_invalid(self):
        result = self.verifier.format_validation("123 Main", zip_code="ABC")
        assert result.details["zip_valid"] is False


# ── DataVerifier (unified) ───────────────────────────────────────────────────


class TestDataVerifier:
    def setup_method(self):
        self.verifier = DataVerifier()

    def test_verify_phone(self):
        result = self.verifier.verify("phone", "+12025551234")
        assert result.field_type == "phone"
        assert result.level >= VerificationLevel.FORMAT_VALID

    def test_verify_email(self):
        result = self.verifier.verify("email", "john@example.com")
        assert result.field_type == "email"
        assert result.level >= VerificationLevel.FORMAT_VALID

    def test_verify_address(self):
        result = self.verifier.verify(
            "address", "123 Main St",
            city="Springfield", state="IL", zip_code="62704"
        )
        assert result.field_type == "address"
        assert result.level >= VerificationLevel.FORMAT_VALID

    def test_verify_unsupported_type(self):
        result = self.verifier.verify("fax", "12345")
        assert result.level == VerificationLevel.UNVERIFIED
        assert "unsupported_type" in result.method


# ── TypeVerificationResult ───────────────────────────────────────────────────


class TestTypeVerificationResult:
    def test_to_dict(self):
        result = TypeVerificationResult(
            field_type="phone",
            value="+15551234567",
            level=VerificationLevel.FORMAT_VALID,
            method="test",
        )
        d = result.to_dict()
        assert d["field_type"] == "phone"
        assert d["level"] == 1
        assert d["level_name"] == "format_valid"

    def test_auto_timestamp(self):
        result = TypeVerificationResult(
            field_type="email",
            value="test@test.com",
            level=VerificationLevel.UNVERIFIED,
        )
        assert result.verified_at != ""
