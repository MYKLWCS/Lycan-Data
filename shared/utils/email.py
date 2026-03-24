"""Email normalization and validation."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def normalize_email(raw: str) -> str | None:
    """
    Normalize email to lowercase. Return None if invalid format.
    Strips whitespace, converts to lowercase.
    """
    if not raw:
        return None
    cleaned = raw.strip().lower()
    if not _EMAIL_RE.match(cleaned):
        return None
    return cleaned


def extract_domain(email: str) -> str | None:
    """Extract the domain from an email address."""
    normalized = normalize_email(email)
    if not normalized:
        return None
    parts = normalized.split("@")
    return parts[1] if len(parts) == 2 else None


def is_valid_email(raw: str) -> bool:
    return normalize_email(raw) is not None


def is_disposable_domain(domain: str) -> bool:
    """Check if domain is a known disposable/temp email provider."""
    DISPOSABLE = frozenset(
        [
            "mailinator.com",
            "guerrillamail.com",
            "tempmail.com",
            "throwaway.email",
            "yopmail.com",
            "sharklasers.com",
            "guerrillamailblock.com",
            "grr.la",
            "guerrillamail.info",
            "spam4.me",
            "trashmail.at",
            "trashmail.com",
            "dispostable.com",
            "maildrop.cc",
            "fakeinbox.com",
            "tempinbox.com",
            "10minutemail.com",
            "getnada.com",
            "spamgourmet.com",
            "mailnull.com",
        ]
    )
    return domain.lower() in DISPOSABLE
