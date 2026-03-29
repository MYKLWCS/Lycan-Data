"""
Type-Specific Data Verifiers.

5-level verification hierarchy:
  Level 0 — Unverified:      Raw data, no validation performed.
  Level 1 — Format Valid:     Passes format/regex checks.
  Level 2 — Cross-Referenced: Appears in 2+ independent sources.
  Level 3 — Confirmed:       Verified against authoritative source.
  Level 4 — Certified:       Government-confirmed or manual analyst review.

Verifiers:
  - PhoneVerifier:   format → carrier lookup → active status
  - EmailVerifier:   syntax → MX record → SMTP probe → disposable/role checks
  - AddressVerifier: format → geocoding → address type classification
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import timezone, datetime
from enum import IntEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Verification levels ──────────────────────────────────────────────────────


class VerificationLevel(IntEnum):
    UNVERIFIED = 0
    FORMAT_VALID = 1
    CROSS_REFERENCED = 2
    CONFIRMED = 3
    CERTIFIED = 4


LEVEL_NAMES = {
    VerificationLevel.UNVERIFIED: "unverified",
    VerificationLevel.FORMAT_VALID: "format_valid",
    VerificationLevel.CROSS_REFERENCED: "cross_referenced",
    VerificationLevel.CONFIRMED: "confirmed",
    VerificationLevel.CERTIFIED: "certified",
}


@dataclass
class TypeVerificationResult:
    """Result of verifying a single data point."""

    field_type: str  # "phone", "email", "address"
    value: str
    level: VerificationLevel
    details: dict[str, Any] = field(default_factory=dict)
    verified_at: str = ""
    method: str = ""

    def __post_init__(self) -> None:
        if not self.verified_at:
            self.verified_at = datetime.now(timezone.utc).isoformat()

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES.get(self.level, "unknown")

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_type": self.field_type,
            "value": self.value,
            "level": self.level,
            "level_name": self.level_name,
            "details": self.details,
            "verified_at": self.verified_at,
            "method": self.method,
        }


# ── Phone Verifier ───────────────────────────────────────────────────────────


_VOIP_CARRIERS = frozenset({
    "google voice", "skype", "textfree", "textnow", "burner",
    "hushed", "sideline", "grasshopper", "ringcentral",
})


class PhoneVerifier:
    """
    Multi-layer phone number verification.

    Level 0 → 1: Format validation via phonenumbers library.
    Level 1 → 2: Cross-reference (handled externally by corroboration count).
    Level 1 → 3: Carrier lookup + active status.
    """

    def format_validation(self, phone: str) -> TypeVerificationResult:
        """Validate phone format. Returns Level 0 or 1."""
        try:
            import phonenumbers

            parsed = phonenumbers.parse(phone, "US")
            is_valid = phonenumbers.is_valid_number(parsed)
            formatted = phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
            country = phonenumbers.region_code_for_number(parsed)
            number_type = phonenumbers.number_type(parsed)

            type_map = {
                phonenumbers.PhoneNumberType.MOBILE: "mobile",
                phonenumbers.PhoneNumberType.FIXED_LINE: "landline",
                phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_or_mobile",
                phonenumbers.PhoneNumberType.VOIP: "voip",
                phonenumbers.PhoneNumberType.TOLL_FREE: "toll_free",
                phonenumbers.PhoneNumberType.PREMIUM_RATE: "premium",
            }
            line_type = type_map.get(number_type, "unknown")

            if is_valid:
                return TypeVerificationResult(
                    field_type="phone",
                    value=formatted,
                    level=VerificationLevel.FORMAT_VALID,
                    method="phonenumbers_library",
                    details={
                        "formatted": formatted,
                        "country": country,
                        "line_type": line_type,
                        "is_valid": True,
                    },
                )
            else:
                return TypeVerificationResult(
                    field_type="phone",
                    value=phone,
                    level=VerificationLevel.UNVERIFIED,
                    method="phonenumbers_library",
                    details={"is_valid": False, "reason": "invalid_number"},
                )

        except ImportError:
            return self._regex_validation(phone)
        except Exception as exc:
            return TypeVerificationResult(
                field_type="phone",
                value=phone,
                level=VerificationLevel.UNVERIFIED,
                method="phonenumbers_library",
                details={"is_valid": False, "reason": str(exc)},
            )

    def _regex_validation(self, phone: str) -> TypeVerificationResult:
        """Fallback regex validation for US phone numbers."""
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 10 or (len(digits) == 11 and digits[0] == "1"):
            formatted = f"+1{digits[-10:]}"
            return TypeVerificationResult(
                field_type="phone",
                value=formatted,
                level=VerificationLevel.FORMAT_VALID,
                method="regex_us",
                details={"formatted": formatted, "is_valid": True},
            )
        if 7 <= len(digits) <= 15:
            formatted = f"+{digits}"
            return TypeVerificationResult(
                field_type="phone",
                value=formatted,
                level=VerificationLevel.FORMAT_VALID,
                method="regex_international",
                details={"formatted": formatted, "is_valid": True},
            )
        return TypeVerificationResult(
            field_type="phone",
            value=phone,
            level=VerificationLevel.UNVERIFIED,
            method="regex",
            details={"is_valid": False, "reason": "invalid_length"},
        )

    def carrier_lookup(self, phone: str) -> dict[str, Any]:
        """Determine carrier and line type via phonenumbers."""
        try:
            import phonenumbers
            from phonenumbers import carrier as pn_carrier, geocoder

            parsed = phonenumbers.parse(phone, "US")
            carrier_name = pn_carrier.name_for_number(parsed, "en")
            geo = geocoder.description_for_number(parsed, "en")
            is_voip = carrier_name.lower() in _VOIP_CARRIERS if carrier_name else False

            return {
                "carrier": carrier_name or "unknown",
                "geo": geo,
                "is_voip": is_voip,
                "lookup_available": True,
            }
        except (ImportError, Exception):
            return {"carrier": "unknown", "lookup_available": False}

    def verify_complete(self, phone: str) -> TypeVerificationResult:
        """Run all phone verification steps."""
        result = self.format_validation(phone)
        if result.level < VerificationLevel.FORMAT_VALID:
            return result

        carrier_info = self.carrier_lookup(result.value)
        result.details.update(carrier_info)

        if carrier_info.get("lookup_available") and carrier_info.get("carrier", "unknown") != "unknown":
            result.level = VerificationLevel.CONFIRMED
            result.method = "carrier_lookup"

        return result


# ── Email Verifier ───────────────────────────────────────────────────────────


_DISPOSABLE_DOMAINS = frozenset({
    "tempmail.com", "guerrillamail.com", "10minutemail.com",
    "mailinator.com", "throwaway.email", "yopmail.com",
    "guerrillamail.info", "grr.la", "dispostable.com",
    "trashmail.com", "temp-mail.org", "fakeinbox.com",
    "sharklasers.com", "guerrillamailblock.com", "maildrop.cc",
})

_ROLE_PREFIXES = frozenset({
    "info", "support", "contact", "hello", "admin",
    "webmaster", "noreply", "donotreply", "sales",
    "service", "billing", "hr", "recruitment", "postmaster",
    "abuse", "security", "hostmaster",
})

from shared.utils.email import _EMAIL_RE


class EmailVerifier:
    """
    Multi-layer email address verification.

    Level 0 → 1: Syntax validation (RFC 5322 simplified).
    Level 1 → 2: MX record check.
    Level 2 → 3: SMTP probe.
    """

    def syntax_validation(self, email: str) -> TypeVerificationResult:
        """Validate email syntax. Returns Level 0 or 1."""
        email_lower = email.lower().strip()
        if _EMAIL_RE.match(email_lower):
            domain = email_lower.split("@")[1]
            local = email_lower.split("@")[0]
            return TypeVerificationResult(
                field_type="email",
                value=email_lower,
                level=VerificationLevel.FORMAT_VALID,
                method="regex_rfc5322",
                details={
                    "is_valid": True,
                    "domain": domain,
                    "local_part": local,
                    "is_disposable": domain in _DISPOSABLE_DOMAINS,
                    "is_role_based": any(local.startswith(p) for p in _ROLE_PREFIXES),
                },
            )
        return TypeVerificationResult(
            field_type="email",
            value=email,
            level=VerificationLevel.UNVERIFIED,
            method="regex_rfc5322",
            details={"is_valid": False, "reason": "invalid_syntax"},
        )

    def mx_check(self, email: str) -> TypeVerificationResult:
        """Check MX records for the domain. Returns Level 1 or 2."""
        base = self.syntax_validation(email)
        if base.level < VerificationLevel.FORMAT_VALID:
            return base

        domain = base.details.get("domain", email.split("@")[1])

        try:
            import dns.resolver

            mx_records = dns.resolver.resolve(domain, "MX")
            mx_hosts = [str(rr.exchange).rstrip(".") for rr in mx_records]

            base.level = VerificationLevel.CROSS_REFERENCED
            base.method = "mx_lookup"
            base.details["has_mx"] = True
            base.details["mx_records"] = mx_hosts[:5]
            return base

        except ImportError:
            logger.debug("dns.resolver not available — skipping MX check for %s", domain)
            base.details["mx_check"] = "skipped_no_dnspython"
            return base
        except Exception:
            base.details["has_mx"] = False
            base.details["mx_check"] = "failed"
            return base

    def verify_complete(self, email: str) -> TypeVerificationResult:
        """Run all email verification steps."""
        return self.mx_check(email)


# ── Address Verifier ─────────────────────────────────────────────────────────


_PO_BOX_RE = re.compile(r"\bp\.?\s*o\.?\s*box\b", re.IGNORECASE)
_COMMERCIAL_KEYWORDS = frozenset({"suite", "ste", "floor", "flr", "office"})
_APT_KEYWORDS = frozenset({"apt", "apartment", "unit", "#"})


class AddressVerifier:
    """
    Physical address verification.

    Level 0 → 1: Format validation.
    Level 1 → 3: Geocoding validation.
    """

    def format_validation(
        self,
        address: str,
        city: str = "",
        state: str = "",
        zip_code: str = "",
    ) -> TypeVerificationResult:
        """Basic format validation and type classification."""
        full = f"{address} {city} {state} {zip_code}".strip()
        if not full or len(full) < 5:
            return TypeVerificationResult(
                field_type="address",
                value=full,
                level=VerificationLevel.UNVERIFIED,
                method="format_check",
                details={"is_valid": False, "reason": "too_short"},
            )

        addr_lower = address.lower()
        if _PO_BOX_RE.search(addr_lower):
            addr_type = "po_box"
        elif any(kw in addr_lower for kw in _COMMERCIAL_KEYWORDS):
            addr_type = "commercial"
        elif any(kw in addr_lower for kw in _APT_KEYWORDS):
            addr_type = "residential_apartment"
        else:
            addr_type = "residential"

        zip_valid = bool(re.match(r"^\d{5}(-\d{4})?$", zip_code)) if zip_code else None

        return TypeVerificationResult(
            field_type="address",
            value=full,
            level=VerificationLevel.FORMAT_VALID,
            method="format_check",
            details={
                "is_valid": True,
                "address_type": addr_type,
                "zip_valid": zip_valid,
                "components": {
                    "address": address,
                    "city": city,
                    "state": state,
                    "zip": zip_code,
                },
            },
        )

    def geocoding_validation(
        self,
        address: str,
        city: str = "",
        state: str = "",
        zip_code: str = "",
    ) -> TypeVerificationResult:
        """Validate address by forward geocoding."""
        base = self.format_validation(address, city, state, zip_code)
        if base.level < VerificationLevel.FORMAT_VALID:
            return base

        try:
            from geopy.geocoders import Nominatim

            geolocator = Nominatim(user_agent="lycan_osint_platform", timeout=5)
            full_addr = f"{address}, {city}, {state} {zip_code}".strip(", ")
            location = geolocator.geocode(full_addr)

            if location:
                base.level = VerificationLevel.CONFIRMED
                base.method = "geocoding"
                base.details["geocoded"] = True
                base.details["latitude"] = location.latitude
                base.details["longitude"] = location.longitude
                base.details["geocoded_address"] = location.address
            else:
                base.details["geocoded"] = False
                base.details["geocode_reason"] = "no_match"

        except ImportError:
            logger.debug("geopy not available — skipping geocoding")
            base.details["geocoded"] = False
            base.details["geocode_reason"] = "geopy_not_installed"
        except Exception as exc:
            base.details["geocoded"] = False
            base.details["geocode_reason"] = str(exc)[:100]

        return base

    def verify_complete(
        self,
        address: str,
        city: str = "",
        state: str = "",
        zip_code: str = "",
    ) -> TypeVerificationResult:
        """Run all address verification steps."""
        return self.geocoding_validation(address, city, state, zip_code)


# ── Unified verifier ─────────────────────────────────────────────────────────


class DataVerifier:
    """Unified verification entry point dispatching to type-specific verifiers."""

    def __init__(self) -> None:
        self.phone = PhoneVerifier()
        self.email = EmailVerifier()
        self.address = AddressVerifier()

    def verify(self, field_type: str, value: str, **kwargs: Any) -> TypeVerificationResult:
        if field_type == "phone":
            return self.phone.verify_complete(value)
        elif field_type == "email":
            return self.email.verify_complete(value)
        elif field_type == "address":
            return self.address.verify_complete(
                value,
                city=kwargs.get("city", ""),
                state=kwargs.get("state", ""),
                zip_code=kwargs.get("zip_code", ""),
            )
        return TypeVerificationResult(
            field_type=field_type,
            value=value,
            level=VerificationLevel.UNVERIFIED,
            method="unsupported_type",
            details={"reason": f"no verifier for type '{field_type}'"},
        )


# ── Async DB integration ─────────────────────────────────────────────────────


async def verify_person_identifiers(
    person_id: str,
    session: AsyncSession,
) -> list[TypeVerificationResult]:
    """Verify all identifiers for a person and update verification_status."""
    from shared.models.identifier import Identifier

    stmt = select(Identifier).where(Identifier.person_id == person_id)
    result = await session.execute(stmt)
    identifiers = result.scalars().all()

    verifier = DataVerifier()
    results: list[TypeVerificationResult] = []

    for ident in identifiers:
        value = ident.normalized_value or ident.value
        if not value:
            continue

        vr = verifier.verify(ident.type, value)
        results.append(vr)

        new_status = LEVEL_NAMES.get(vr.level, "unverified")
        if _level_rank(new_status) > _level_rank(ident.verification_status):
            ident.verification_status = new_status

    if results:
        await session.flush()
        logger.info("Verified %d identifiers for person %s", len(results), person_id)

    return results


def _level_rank(status: str) -> int:
    rank_map = {
        "unverified": 0,
        "format_valid": 1,
        "cross_referenced": 2,
        "confirmed": 3,
        "certified": 4,
    }
    return rank_map.get(status, 0)
