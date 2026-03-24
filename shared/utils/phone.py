"""Phone number normalisation and analysis using libphonenumber."""
from __future__ import annotations
import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberType
from shared.constants import LineType


def normalize_phone(raw: str, default_region: str = "US") -> str | None:
    """
    Normalize a phone number to E.164 format.
    Returns None if invalid.
    """
    try:
        parsed = phonenumbers.parse(raw, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        return None
    except NumberParseException:
        return None


def get_line_type(raw: str, default_region: str = "US") -> LineType:
    """
    Determine line type from a phone number.
    Returns LineType enum value.
    """
    try:
        parsed = phonenumbers.parse(raw, default_region)
        if not phonenumbers.is_valid_number(parsed):
            return LineType.UNKNOWN
        number_type = phonenumbers.number_type(parsed)
        mapping = {
            PhoneNumberType.MOBILE: LineType.MOBILE,
            PhoneNumberType.FIXED_LINE: LineType.LANDLINE,
            PhoneNumberType.FIXED_LINE_OR_MOBILE: LineType.MOBILE,
            PhoneNumberType.VOIP: LineType.VOIP,
            PhoneNumberType.TOLL_FREE: LineType.TOLL_FREE,
            PhoneNumberType.PREMIUM_RATE: LineType.LANDLINE,
            PhoneNumberType.PERSONAL_NUMBER: LineType.MOBILE,
            PhoneNumberType.PAGER: LineType.MOBILE,
        }
        return mapping.get(number_type, LineType.UNKNOWN)
    except NumberParseException:
        return LineType.UNKNOWN


def get_country_code(raw: str, default_region: str = "US") -> str | None:
    """Return ISO 3166-1 alpha-2 country code for the phone number."""
    try:
        parsed = phonenumbers.parse(raw, default_region)
        if not phonenumbers.is_valid_number(parsed):
            return None
        from phonenumbers.geocoder import country_name_for_number
        region = phonenumbers.region_code_for_number(parsed)
        return region
    except NumberParseException:
        return None


def is_valid_phone(raw: str, default_region: str = "US") -> bool:
    """Return True if the number is valid."""
    try:
        parsed = phonenumbers.parse(raw, default_region)
        return phonenumbers.is_valid_number(parsed)
    except NumberParseException:
        return False
