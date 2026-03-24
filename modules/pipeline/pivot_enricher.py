"""
Pivot Enricher.

After a crawler returns data, extract newly discovered identifiers
(email, phone, full name) and queue fresh searches for each one.
This is what makes the tool recursive — one Instagram handle can
cascade into email breaches, phone carrier lookups, name-based
people-search, sanctions checks, and dark web exposure.

Only pivots on HIGH-VALUE identifier types (email, phone, full_name).
Never pivots on usernames to prevent social-graph explosion.
"""

import logging
import re
import uuid
from typing import Any

from sqlalchemy import select

from shared.db import AsyncSessionLocal
from shared.models.identifier import Identifier

logger = logging.getLogger(__name__)

# Max new pivot searches to spawn from a single result (safety cap)
_MAX_PIVOTS = 3

# Platforms to run per pivot type — ordered by signal value
_PIVOT_PLATFORMS: dict[str, list[str]] = {
    "email": [
        "email_hibp",
        "email_holehe",
        "email_leakcheck",
        "email_emailrep",
        "darkweb_ahmia",
        "paste_pastebin",
    ],
    "phone": [
        "phone_carrier",
        "phone_truecaller",
        "whatsapp",
        "telegram",
    ],
    "full_name": [
        "whitepages",
        "fastpeoplesearch",
        "truepeoplesearch",
        "sanctions_ofac",
        "sanctions_un",
        "sanctions_fbi",
        "sanctions_eu",
        "court_courtlistener",
        "people_interpol",
        "darkweb_ahmia",
        "news_search",
    ],
}


def _extract_pivots(data: dict[str, Any]) -> list[tuple[str, str]]:
    """Pull email, phone, full_name out of raw crawler data dict."""
    found: list[tuple[str, str]] = []

    # Email
    email = (
        data.get("email")
        or data.get("email_address")
        or data.get("contact_email")
        or data.get("emails", [None])[0]
        if isinstance(data.get("emails"), list)
        else None
    )
    if email and isinstance(email, str) and "@" in email and len(email) > 5:
        found.append(("email", email.strip().lower()))

    # Phone
    phone = data.get("phone") or data.get("phone_number") or data.get("mobile")
    if phone and isinstance(phone, str):
        digits = re.sub(r"\D", "", phone)
        if 7 <= len(digits) <= 15:
            found.append(("phone", phone.strip()))

    # Full name (must be multi-word, not just a handle)
    name = (
        data.get("full_name")
        or data.get("name")
        or data.get("display_name")
        or data.get("owner_name")
        or data.get("registrant_name")
    )
    _REJECT_WORDS = {
        "youtube",
        "snapchat",
        "instagram",
        "twitter",
        "facebook",
        "tiktok",
        "linkedin",
        "reddit",
        "telegram",
        "whatsapp",
        "discord",
        "twitch",
        "steam",
        "pinterest",
        "mastodon",
        "github",
        "cookie",
        "consent",
        "gdpr",
        "weitergehen",
        "continuer",
        "fortsätter",
        "continuar",
        "continue",
        "privacy",
        "terms",
        "sur",
        "auf",
    }
    if name and isinstance(name, str):
        clean = name.strip()
        words = clean.lower().split()
        # 2-4 words, letters only, no platform/consent keywords
        if (
            2 <= len(words) <= 4
            and len(clean) >= 5
            and re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ' \-\.]+$", clean)
            and not any(w in _REJECT_WORDS for w in words)
        ):
            found.append(("full_name", clean))

    return found[:_MAX_PIVOTS]


async def pivot_from_result(
    person_id: str,
    platform: str,
    data: dict[str, Any],
) -> int:
    """
    Inspect crawler result data, extract new identifiers, and queue searches.
    Returns count of new jobs queued.
    """
    from modules.crawlers.registry import CRAWLER_REGISTRY
    from modules.dispatcher.dispatcher import dispatch_job

    pivots = _extract_pivots(data)
    if not pivots:
        return 0

    pid = uuid.UUID(person_id) if isinstance(person_id, str) else person_id
    jobs_queued = 0

    async with AsyncSessionLocal() as session:
        for id_type, value in pivots:
            norm = value.lower()

            # Skip if person already has this identifier (avoid re-searching)
            existing = (
                await session.execute(
                    select(Identifier)
                    .where(
                        Identifier.person_id == pid,
                        Identifier.normalized_value == norm,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing:
                continue

            platforms = _PIVOT_PLATFORMS.get(id_type, [])
            queued_for_this = 0
            for platform_name in platforms:
                if platform_name not in CRAWLER_REGISTRY:
                    continue
                await dispatch_job(
                    platform=platform_name,
                    identifier=value,
                    person_id=person_id,
                    priority="normal",
                )
                queued_for_this += 1
                jobs_queued += 1

            if queued_for_this:
                logger.info(
                    "Pivot: person=%s platform=%s found %s=%r → queued %d jobs",
                    person_id,
                    platform,
                    id_type,
                    value,
                    queued_for_this,
                )

    return jobs_queued
