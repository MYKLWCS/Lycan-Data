from shared.utils.email import extract_domain, is_disposable_domain, is_valid_email, normalize_email
from shared.utils.phone import get_country_code, get_line_type, is_valid_phone, normalize_phone
from shared.utils.scoring import clamp, log_scale, tier_from_score, weighted_sum
from shared.utils.social import build_profile_url, extract_handle_from_url, normalize_handle


def normalize_name(name: str) -> str:
    """Lowercase, strip whitespace, collapse inner spaces for fuzzy matching."""
    return " ".join(name.lower().split())


__all__ = [
    "normalize_phone",
    "get_line_type",
    "get_country_code",
    "is_valid_phone",
    "normalize_email",
    "extract_domain",
    "is_valid_email",
    "is_disposable_domain",
    "normalize_handle",
    "extract_handle_from_url",
    "build_profile_url",
    "clamp",
    "weighted_sum",
    "log_scale",
    "tier_from_score",
    "normalize_name",
]
