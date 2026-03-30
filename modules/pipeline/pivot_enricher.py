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

# Max crawl jobs to queue from a single pivot_from_result call (applied in caller)
_MAX_JOBS_PER_CALL = 30

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
    "instagram_handle": ["instagram", "username_maigret", "username_sherlock"],
    "twitter_handle": ["twitter", "username_maigret", "username_sherlock"],
    "linkedin_url": ["linkedin"],
    "domain": ["domain_whois", "domain_harvester", "cyber_crt"],
}


def _extract_pivots(data: dict[str, Any]) -> list[tuple[str, str]]:
    """Pull email, phone, full_name out of raw crawler data dict."""
    found: list[tuple[str, str]] = []

    # Email
    email = data.get("email") or data.get("email_address") or data.get("contact_email")
    if not email and isinstance(data.get("emails"), list) and data.get("emails"):
        email = data.get("emails")[0]

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

    # Instagram handle
    ig = data.get("instagram") or data.get("instagram_handle") or data.get("instagram_username")
    if ig:
        found.append(("instagram_handle", ig.lstrip("@").lower()))

    # Twitter handle
    tw = data.get("twitter") or data.get("twitter_handle") or data.get("twitter_username")
    if tw:
        found.append(("twitter_handle", tw.lstrip("@").lower()))

    # LinkedIn URL
    li = data.get("linkedin") or data.get("linkedin_url") or data.get("linkedin_profile")
    if li:
        found.append(("linkedin_url", li))

    # Domain
    domain = data.get("domain") or data.get("website") or data.get("url")
    if domain and "." in str(domain):
        found.append(("domain", domain.lower()))

    return found


async def pivot_from_result(
    person_id: str,
    platform: str,
    data: dict[str, Any],
    depth: int = 0,
) -> int:
    """
    Inspect crawler result data, extract new identifiers, and queue searches.
    Returns count of new jobs queued.
    """
    from modules.crawlers.registry import CRAWLER_REGISTRY
    from modules.dispatcher.dispatcher import dispatch_job

    # Check recursion depth before pivoting (fail open if Redis unavailable)
    try:
        from modules.dispatcher.dispatcher import check_search_depth
        if not await check_search_depth(person_id):
            logger.info("Skipping pivots for person %s — max depth reached", person_id)
            return 0
    except Exception:
        pass  # Depth check failed — allow pivot to proceed

    pivots = _extract_pivots(data)
    if not pivots:
        return 0

    pid = uuid.UUID(person_id) if isinstance(person_id, str) else person_id
    jobs_queued = 0

    async with AsyncSessionLocal() as session:
        for id_type, value in pivots:
            if jobs_queued >= _MAX_JOBS_PER_CALL:
                break
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

            # Store the discovered identifier on the person
            new_ident = Identifier(
                id=uuid.uuid4(),
                person_id=pid,
                type=id_type,
                value=value,
                normalized_value=norm,
                confidence=0.8,
                meta={"discovered_from": platform, "pivot": True},
            )
            session.add(new_ident)
            try:
                await session.flush()
            except Exception:
                await session.rollback()

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
                    depth=depth + 1,
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

        # Cross-person identifier match detection
        # Flag potential duplicates when a new identifier matches a different person
        from shared.models.dedup_review import DedupReview

        new_identifiers = [(t, v) for t, v in pivots if v]
        for ident_type, ident_value in new_identifiers:
            norm = ident_value.lower()
            existing = await session.execute(
                select(Identifier.person_id).where(
                    Identifier.normalized_value == norm,
                    Identifier.type == ident_type,
                    Identifier.person_id != pid,
                )
            )
            for (other_id,) in existing.all():
                # Check if review already exists for this pair
                review_exists = await session.execute(
                    select(DedupReview.id).where(
                        (
                            (DedupReview.person_a_id == pid)
                            & (DedupReview.person_b_id == other_id)
                        )
                        | (
                            (DedupReview.person_a_id == other_id)
                            & (DedupReview.person_b_id == pid)
                        )
                    ).limit(1)
                )
                if not review_exists.scalar_one_or_none():
                    # Compute actual similarity from name comparison
                    from shared.models.person import Person as _Person
                    from rapidfuzz import fuzz as _fuzz_mod
                    _person_a = await session.get(_Person, pid)
                    _person_b = await session.get(_Person, other_id)
                    _name_a = getattr(_person_a, 'full_name', '') or ''
                    _name_b = getattr(_person_b, 'full_name', '') or ''
                    _name_sim = _fuzz_mod.token_sort_ratio(_name_a, _name_b) / 100.0
                    _similarity_score = min(1.0, 0.4 + _name_sim * 0.6)
                    session.add(
                        DedupReview(
                            id=uuid.uuid4(),
                            person_a_id=pid,
                            person_b_id=other_id,
                            similarity_score=_similarity_score,
                        )
                    )
                    logger.info(
                        "Cross-person match: %s shared %s=%s with %s, flagged for dedup review",
                        pid,
                        ident_type,
                        norm,
                        other_id,
                    )
        await session.commit()

    return jobs_queued
