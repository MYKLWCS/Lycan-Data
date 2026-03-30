"""
Person Aggregation Pipeline.

Takes a CrawlerResult and writes it into the correct DB tables,
linked to the right Person. Handles all result types.
"""

import hashlib
import logging
import re
import uuid
from datetime import timezone, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from modules.crawlers.core.result import CrawlerResult
from shared.constants import (
    AlertSeverity,
    AlertType,
    IdentifierType,
    Platform,
)
from shared.data_quality import apply_quality_to_model
from shared.models.address import Address
from shared.models.alert import Alert
from shared.models.behavioural import BehaviouralProfile
from shared.models.breach import BreachRecord
from shared.models.criminal import CriminalRecord
from shared.models.darkweb import DarkwebMention
from shared.models.identifier import Identifier
from shared.models.identifier_history import IdentifierHistory
from shared.models.identity_document import CreditProfile
from shared.models.person import Person
from shared.models.social_profile import SocialProfile
from shared.models.watchlist import WatchlistMatch

try:
    from shared.models.employment import EmploymentHistory
except ImportError:
    EmploymentHistory = None  # type: ignore[assignment,misc]

try:
    from shared.models.education import Education
except ImportError:
    Education = None  # type: ignore[assignment,misc]

try:
    from shared.models.property import Property
except ImportError:
    Property = None  # type: ignore[assignment,misc]

try:
    from shared.models.vehicle import Vehicle
except ImportError:
    Vehicle = None  # type: ignore[assignment,misc]

try:
    from shared.models.darkweb import CryptoWallet
except ImportError:
    CryptoWallet = None  # type: ignore[assignment,misc]

try:
    from shared.models.professional import ProfessionalLicense, CorporateDirectorship
except ImportError:
    ProfessionalLicense = None  # type: ignore[assignment,misc]
    CorporateDirectorship = None  # type: ignore[assignment,misc]

try:
    from shared.models.compliance_ext import AdverseMedia
except ImportError:
    AdverseMedia = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Platforms that represent a social media profile (explicit list, not enum)
_SOCIAL_PLATFORMS = {
    "instagram", "facebook", "twitter", "linkedin", "tiktok", "snapchat",
    "reddit", "pinterest", "youtube", "github", "gitlab", "discord",
    "telegram", "whatsapp", "signal", "viber", "xing", "medium",
    "twitch", "steam", "spotify", "mastodon", "threads", "bluesky",
    "tumblr", "quora", "stackoverflow", "onlyfans", "irc",
    "social_twitter", "social_instagram", "social_facebook", "social_linkedin",
    "social_tiktok", "social_snapchat", "social_steam", "social_twitch",
    "social_spotify", "social_snscrape", "social_posts_analyzer",
    "peekyou", "about_me", "gravatar", "keybase",
    "truth_social_profile", "vk_profile", "bluesky_profile", "threads_profile",
    "username_sherlock", "username_maigret",
    "github_profile", "stackoverflow_profile", "social_mastodon", "social_ghunt", "social_graph", "spotify_public", "snscrape", "instaloader", "interests_extractor",
    "generic_web_scraper",
    "gravatar",
}

# Phone enrichment platform keys
_PHONE_PLATFORMS = {"phone_carrier", "phone_fonefinder", "phone_truecaller",
    "phone_numlookup", "phone_phoneinfoga",
}

# Email breach platform keys
_EMAIL_BREACH_PLATFORMS = {
    "email_hibp",
    "email_holehe",
    "email_leakcheck",
    "email_breach",
    "email_dehashed", "email_disposable", "email_emailrep", "email_socialscan", "email_mx_validator",
}

# Sanctions / watchlist platform keys
_SANCTIONS_PLATFORMS = {
    "sanctions_ofac", "sanctions_un", "sanctions_fbi",
    "sanctions_eu", "sanctions_uk", "sanctions_canada", "sanctions_australia",
    "sanctions_worldbank_debarment", "people_interpol", "people_usmarshals",
    "bis_entity_list", "fara_scraper",
    "sanctions_fatf", "sanctions_opensanctions", "open_pep_search", "world_check_mirror", "gov_bop",
}

# Dark-web / paste platform keys
_DARKWEB_PLATFORMS = {
    "darkweb_ahmia",
    "darkweb_torch",
    "paste_pastebin",
    "paste_ghostbin",
    "paste_psbdmp",
    "telegram_dark",
    "cyber_abuseipdb", "cyber_alienvault", "cyber_crt", "cyber_dns", "cyber_greynoise", "cyber_shodan", "cyber_urlscan", "cyber_virustotal", "domain_harvester", "domain_whois", "geo_ip",
}

# People-search platform keys
_PEOPLE_SEARCH_PLATFORMS = {
    "whitepages",
    "fastpeoplesearch",
    "truepeoplesearch",
    "people_thatsthem", "people_zabasearch", "people_familysearch", "people_findagrave", "people_namus", "people_usmarshals", "people_interpol", "people_fbi_wanted", "people_immigration", "people_phonebook", "people_intelx", "radaris", "spokeo", "peekyou", "clustrmaps", "familytreenow",
    "wikidata_lookup", "open_library",
}

# Court / criminal record platform keys
_COURT_PLATFORMS = {"court_courtlistener", "court_state",
    "ca_courts", "fl_courts", "txcourts",
}

# Sex offender registry
_SEX_OFFENDER_PLATFORMS = {"public_nsopw"}

# Government / voter / ID sources
_GOVERNMENT_PLATFORMS = {"public_voter", "public_npi", "public_faa",
    "gov_epa", "gov_fda", "gov_osha", "gov_uspto_patents", "gov_uspto_trademarks", "gov_gleif", "us_corporate_registry", "ca_courts", "fl_courts", "txcourts",
}

# Bankruptcy
_BANKRUPTCY_PLATFORMS = {"bankruptcy_pacer"}

# Employment / work history platforms
_EMPLOYMENT_PLATFORMS = {"linkedin", "glassdoor", "indeed", "xing"}

# Education platforms
_EDUCATION_PLATFORMS = {"linkedin", "classmates"}

# Property / real-estate platforms
_PROPERTY_PLATFORMS = {
    "property_zillow", "property_redfin", "property_county", "property_realtor",
    "property_trulia", "property_mls", "zillow_deep", "redfin_deep",
    "county_assessor_multi", "deed_recorder", "netronline_public",
    "property_tax_nationwide", "propertyradar_scraper",
    "attom_gateway", "county_assessor_fl", "county_assessor_tx", "redfin_property", "mortgage_deed", "mortgage_hmda", "google_maps", "geo_openstreetmap",
}

# Vehicle / craft ownership platforms
_VEHICLE_PLATFORMS = {
    "vehicle_ownership", "vehicle_vin", "vehicle_plate",
    "faa_aircraft_registry", "marine_vessel",
    "vehicle_nhtsa", "vehicle_nicb", "vin_decode_enhanced", "geo_adsbexchange",
}

# Financial / crypto platforms
_FINANCIAL_PLATFORMS = {
    "crypto_blockchain", "crypto_etherscan", "crypto_bscscan",
    "crypto_polygonscan", "financial_sec", "financial_crunchbase",
    "icij_offshoreleaks", "company_sec", "gov_propublica",
    "gov_fec", "gov_usaspending", "gov_sam",
    "crypto_bitcoin", "crypto_blockchair", "crypto_ethereum", "financial_finra", "financial_worldbank", "gov_fdic", "gov_finra", "gov_nmls", "gov_fred", "gov_worldbank", "gov_grants", "sec_edgar", "sec_insider",
    "company_companies_house", "company_opencorporates",
}

# News / adverse-media platforms
_NEWS_PLATFORMS = {
    "news_search", "news_google", "google_news_rss",
    "adverse_media_search", "gdelt_mentions", "obituary_search",
    "news_wikipedia",
    "bing_news", "news_archive", "newspapers_archive", "cyber_wayback",
    "ancestry_hints", "census_records", "geni_public", "vitals_records",
}


async def _safe_upsert_identifier(
    session: AsyncSession,
    person_id: uuid.UUID,
    id_type: str,
    raw_value: str,
    normalized_value: str,
    *,
    confidence: float = 1.0,
    is_primary: bool = False,
    meta: dict | None = None,
    source_reliability: float | None = None,
) -> None:
    """Insert an Identifier using PostgreSQL ON CONFLICT DO NOTHING.

    Relies on the ``uq_identifier_person_type_value`` unique constraint
    so that duplicate (person_id, type, normalized_value) tuples are
    silently skipped instead of raising IntegrityError.
    """
    values: dict = {
        "id": uuid.uuid4(),
        "person_id": person_id,
        "type": id_type,
        "value": raw_value,
        "normalized_value": normalized_value,
        "confidence": confidence,
        "is_primary": is_primary,
        "meta": meta or {},
    }
    if source_reliability is not None:
        values["source_reliability"] = source_reliability

    stmt = (
        pg_insert(Identifier)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_identifier_person_type_value")
    )
    await session.execute(stmt)


async def aggregate_result(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: str | None = None,
) -> dict[str, Any]:
    """
    Main entry point. Routes result to the correct sub-handlers based on platform.

    Returns a summary dict describing what was written. Commits the session on
    success so the caller doesn't have to.
    """
    if not result.found or not result.data:
        return {"written": False, "reason": "no data"}

    written: dict[str, Any] = {}

    person = await _get_or_create_person(session, person_id, result)
    written["person_id"] = str(person.id)

    # Backfill Person.full_name if still blank and result carries a real name
    if not person.full_name and result.data:
        candidate = (
            result.data.get("full_name")
            or result.data.get("name")
            or result.data.get("display_name")
            or result.data.get("owner_name")
        )
        import re as _re

        _PLATFORM_WORDS = {
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
            # Consent page markers
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
        }
        if candidate and isinstance(candidate, str):
            c = candidate.strip()
            words = c.lower().split()
            # Must be 2-4 words (real names), all letters, no platform/consent words
            if (
                2 <= len(words) <= 4
                and len(c) >= 5
                and _re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ' \-\.]+$", c)
                and not any(w in _PLATFORM_WORDS for w in words)
            ):
                person.full_name = c

    platform = (result.platform or "").lower()

    _handled = False

    # Social profile ─────────────────────────────────────────────────────────
    if platform in _SOCIAL_PLATFORMS:
        profile = await _upsert_social_profile(session, result, person.id)
        written["social_profile"] = str(profile.id) if profile else None
        # Extract embedded employment / education from social profiles
        data = result.data or {}
        if data.get("employment") or data.get("work_history") or data.get("jobs"):
            await _handle_employment(session, result, person.id)
            written["embedded_employment"] = True
        if data.get("education") or data.get("schools"):
            await _handle_education(session, result, person.id)
            written["embedded_education"] = True
        _handled = True

    # WhatsApp / Telegram confirmation: identifier IS a phone number — also
    # store it as a proper phone Identifier so it's visible in identifiers list.
    if platform in {"whatsapp", "telegram"} and result.identifier:
        phone_val = result.data.get("phone") or result.identifier
        if _looks_like_phone_number(phone_val):
            await _upsert_phone_identifier(session, phone_val, person.id, platform)
            written["phone_identifier"] = phone_val

    # Phone enrichment ────────────────────────────────────────────────────────
    if platform in _PHONE_PLATFORMS:
        await _handle_phone_enrichment(session, result, person.id)
        written["phone_enrichment"] = True
        _handled = True

    # Email breach data ───────────────────────────────────────────────────────
    if platform in _EMAIL_BREACH_PLATFORMS:
        count = await _handle_breach_data(session, result, person.id)
        written["breach_data"] = True
        written["breach_count"] = count
        _handled = True

    # Sanctions / watchlist hits ──────────────────────────────────────────────
    if platform in _SANCTIONS_PLATFORMS:
        hits = await _handle_watchlist(session, result, person.id)
        written["watchlist_hits"] = hits
        _handled = True

    # Dark-web / paste mentions ───────────────────────────────────────────────
    if platform in _DARKWEB_PLATFORMS:
        await _handle_darkweb(session, result, person.id)
        written["darkweb"] = True
        _handled = True

    # People-search addresses ─────────────────────────────────────────────────
    if platform in _PEOPLE_SEARCH_PLATFORMS:
        await _handle_people_search(session, result, person.id)
        written["addresses"] = True
        _handled = True

    # Court / legal records ───────────────────────────────────────────────────
    if platform in _COURT_PLATFORMS:
        count = await _handle_court_records(session, result, person.id)
        written["criminal_records"] = count
        _handled = True

    # Sex offender registry
    if platform in _SEX_OFFENDER_PLATFORMS:
        count = await _handle_sex_offender(session, result, person.id)
        written["sex_offender_records"] = count
        _handled = True

    # Bankruptcy
    if platform in _BANKRUPTCY_PLATFORMS:
        await _handle_bankruptcy(session, result, person.id)
        written["bankruptcy"] = True
        _handled = True

    # Employment (skip if already handled via social embedding)
    if platform in _EMPLOYMENT_PLATFORMS and not written.get("embedded_employment"):
        await _handle_employment(session, result, person.id)
        written["employment"] = True
        _handled = True

    # Property / real-estate ──────────────────────────────────────────────────
    if platform in _PROPERTY_PLATFORMS:
        await _handle_property(session, result, person.id)
        written["property"] = True
        _handled = True

    # Vehicle / craft ownership ───────────────────────────────────────────────
    if platform in _VEHICLE_PLATFORMS:
        await _handle_vehicle(session, result, person.id)
        written["vehicle"] = True
        _handled = True

    # Government / voter / professional license ───────────────────────────────
    if platform in _GOVERNMENT_PLATFORMS:
        await _handle_government(session, result, person.id)
        written["government"] = True
        _handled = True

    # Financial / crypto ──────────────────────────────────────────────────────
    if platform in _FINANCIAL_PLATFORMS:
        await _handle_financial(session, result, person.id)
        written["financial"] = True
        _handled = True

    # News / adverse media ────────────────────────────────────────────────────
    if platform in _NEWS_PLATFORMS:
        await _handle_news(session, result, person.id)
        written["news"] = True
        _handled = True

    # Education (skip if already handled via social embedding)
    if platform in _EDUCATION_PLATFORMS and not written.get("embedded_education"):
        await _handle_education(session, result, person.id)
        written["education"] = True
        _handled = True

    if not _handled:
        logger.warning(
            "Unhandled platform %s for person %s — data keys: %s",
            platform, person.id, list((result.data or {}).keys()),
        )

    # Identifier history ───────────────────────────────────────────────────────
    await _record_identifier_history(session, result, person.id)

    # Behavioural signals ─────────────────────────────────────────────────────
    if platform == "social_posts_analyzer":
        await _handle_behavioural(session, result, person.id)
        written["behavioural"] = True

    # ── Update Person.source_reliability ────────────────────────────────────
    # Raise person reliability toward the contributing crawler's score.
    # Each additional source that confirms this person adds a corroboration
    # bonus, so reliability climbs as evidence accumulates.
    if result.source_reliability > 0.5:
        try:
            corr = int(person.corroboration_count or 1)
        except (TypeError, ValueError):
            corr = 1
        person.corroboration_count = corr + 1
        bonus = min(0.20, corr * 0.05)
        try:
            current_rel = float(person.source_reliability or 0.0)
        except (TypeError, ValueError):
            current_rel = 0.0
        person.source_reliability = round(
            min(0.95, max(current_rel, result.source_reliability) + bonus), 3
        )

    await session.commit()
    return written


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


from rapidfuzz import fuzz as _fuzz
from shared.utils import normalize_identifier, normalize_name as _normalize_name


async def _get_or_create_person(
    session: AsyncSession,
    person_id: str | None,
    result: CrawlerResult,
) -> Person:
    """Return an existing Person or create a new one.

    Resolution order:
      1. person_id provided → look up directly
      2. Exact identifier match (email, phone)
      3. Exact normalized full_name match
      4. Fuzzy name match (token_sort_ratio >= 90)
      5. Create new Person
    """
    if person_id:
        try:
            p = await session.get(Person, uuid.UUID(person_id))
            if p:
                return p
        except (ValueError, Exception):
            pass

    data = result.data or {}

    # Try exact identifier match first (email or phone)
    email = data.get("email") or (
        result.identifier if result.identifier and "@" in result.identifier else None
    )
    phone = data.get("phone") or (
        result.identifier if result.identifier and _looks_like_phone_number(result.identifier) else None
    )

    if email:
        ident_match = (
            await session.execute(
                select(Identifier)
                .where(
                    Identifier.type == "email",
                    Identifier.normalized_value == email.lower().strip(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if ident_match:
            p = await session.get(Person, ident_match.person_id)
            if p:
                return p

    if phone:
        import re as _re_phone
        digits = _re_phone.sub(r"\D", "", phone)
        normalized_phone = f"+{digits}"
        ident_match = (
            await session.execute(
                select(Identifier)
                .where(
                    Identifier.type == "phone",
                    Identifier.normalized_value == normalized_phone,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if ident_match:
            p = await session.get(Person, ident_match.person_id)
            if p:
                return p

    # Try to find by normalized full_name if result carries one
    full_name = (
        data.get("name") or data.get("full_name") or data.get("display_name")
    )
    if full_name:
        norm = _normalize_name(full_name)
        # Exact normalized name match
        existing = (
            await session.execute(select(Person).where(Person.full_name.ilike(norm)).limit(1))
        ).scalar_one_or_none()
        if existing:
            return existing

        # Fuzzy name match: prefix-blocked to reduce comparison set
        candidates = (
            await session.execute(
                select(Person)
                .where(Person.full_name.isnot(None))
                .where(Person.full_name.ilike(f"{norm[:3]}%"))
                .order_by(Person.created_at.desc())
                .limit(200)
            )
        ).scalars().all()

        for candidate in candidates:
            score = _fuzz.token_sort_ratio(norm, candidate.full_name or "")
            if score >= 87:
                return candidate

    p = Person(id=uuid.uuid4(), full_name=full_name)
    session.add(p)
    await session.flush()
    return p


async def _upsert_social_profile(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> SocialProfile | None:
    """Insert or update a SocialProfile row from a CrawlerResult."""
    data = result.data or {}
    handle = (
        data.get("handle") or data.get("username") or data.get("display_name") or result.identifier
    )

    existing = (
        await session.execute(
            select(SocialProfile)
            .where(
                SocialProfile.platform == result.platform,
                SocialProfile.handle == handle,
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if existing:
        # Update mutable fields — never overwrite with None
        existing.follower_count = data.get("follower_count") or existing.follower_count
        existing.following_count = data.get("following_count") or existing.following_count
        existing.post_count = data.get("post_count") or existing.post_count
        existing.bio = data.get("bio") or existing.bio
        existing.display_name = data.get("display_name") or existing.display_name
        existing.is_verified = data.get("is_verified", False) or existing.is_verified
        existing.is_private = data.get("is_private", False) or existing.is_private
        existing.last_scraped_at = now
        existing.person_id = person_id
        apply_quality_to_model(
            existing,
            last_scraped_at=now,
            source_type="social_media_profile",
            source_name=result.platform,
            corroboration_count=1,
        )
        # Capture profile image for Person if available
        avatar = (
            data.get("profile_image_url") or data.get("avatar_url")
            or data.get("profile_photo") or data.get("photo_url")
        )
        if avatar and isinstance(avatar, str) and avatar.startswith("http"):
            person = await session.get(Person, person_id)
            if person and not person.profile_image_url:
                person.profile_image_url = avatar
        return existing

    profile = SocialProfile(
        id=uuid.uuid4(),
        person_id=person_id,
        platform=result.platform,
        handle=handle,
        url=result.profile_url,
        display_name=data.get("display_name"),
        follower_count=data.get("follower_count"),
        following_count=data.get("following_count"),
        post_count=data.get("post_count"),
        bio=data.get("bio"),
        is_verified=data.get("is_verified", False),
        is_private=data.get("is_private", False),
        is_active=result.found,
        profile_data=data,
        last_scraped_at=now,
        scraped_from=result.profile_url or result.platform,
        source_reliability=result.source_reliability,
    )
    apply_quality_to_model(
        profile,
        last_scraped_at=now,
        source_type="social_media_profile",
        source_name=result.platform,
        corroboration_count=1,
    )
    session.add(profile)
    await session.flush()
    # Capture profile image for Person if available
    avatar = (
        data.get("profile_image_url") or data.get("avatar_url")
        or data.get("profile_photo") or data.get("photo_url")
    )
    if avatar and isinstance(avatar, str) and avatar.startswith("http"):
        person = await session.get(Person, person_id)
        if person and not person.profile_image_url:
            person.profile_image_url = avatar

    # Store handle/email/phone as Identifiers for cross-search discovery
    try:
        data = result.data or {}
        handle = data.get("handle") or data.get("username") or data.get("screen_name")
        if handle and isinstance(handle, str) and len(handle) >= 2:
            await _safe_upsert_identifier(session, person_id, "username", handle, handle.lower().lstrip("@"))

        social_email = data.get("email") or data.get("contact_email")
        if social_email and isinstance(social_email, str) and "@" in social_email:
            await _safe_upsert_identifier(session, person_id, "email", social_email, social_email.strip().lower())

        social_phone = data.get("phone") or data.get("phone_number")
        if social_phone and isinstance(social_phone, str):
            digits = re.sub(r"[^\d]", "", social_phone)
            if len(digits) >= 7:
                norm = f"+1{digits}" if len(digits) == 10 else f"+{digits}"
                await _safe_upsert_identifier(session, person_id, "phone", social_phone, norm)
    except Exception:
        pass

    return profile


async def _handle_phone_enrichment(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Persist phone-carrier enrichment and compute a burner score."""
    from modules.enrichers.burner_detector import compute_burner_score, persist_burner_assessment

    data = result.data or {}

    # Find or create the phone Identifier
    ident = (
        await session.execute(
            select(Identifier)
            .where(
                Identifier.person_id == person_id,
                Identifier.type == IdentifierType.PHONE.value,
                Identifier.value == result.identifier,
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    if not ident:
        await _safe_upsert_identifier(
            session,
            person_id=person_id,
            id_type=IdentifierType.PHONE.value,
            raw_value=result.identifier,
            normalized_value=normalize_identifier(result.identifier, "phone"),
            confidence=0.9,
        )
        await session.flush()
        # Re-fetch the identifier row (may have existed via concurrent insert)
        _phone_norm = normalize_identifier(result.identifier, "phone")
        ident = (
            await session.execute(
                select(Identifier)
                .where(
                    Identifier.person_id == person_id,
                    Identifier.type == IdentifierType.PHONE.value,
                    Identifier.normalized_value == _phone_norm,
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    carrier_name = data.get("carrier_name")
    line_type = data.get("line_type")
    area_code = result.identifier[2:5] if result.identifier.startswith("+1") else None

    score = compute_burner_score(
        phone=result.identifier,
        carrier_name=carrier_name,
        line_type=line_type,
        area_code=area_code,
    )
    if ident:
        await persist_burner_assessment(session, ident.id, score)

    # Backfill person name from phone enrichment results
    data = result.data or {}
    discovered_name = data.get("owner_name") or data.get("name") or data.get("subscriber_name")
    if discovered_name and isinstance(discovered_name, str) and len(discovered_name) >= 3:
        person = await session.get(Person, person_id)
        if person and not person.full_name:
            # Validate it looks like a real name (2+ words, all alpha)
            parts = discovered_name.strip().split()
            if len(parts) >= 2 and all(p.isalpha() for p in parts):
                person.full_name = discovered_name.strip()


async def _handle_breach_data(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> int:
    """Write BreachRecord rows from HIBP-style or Holehe-style results."""
    data = result.data or {}
    count = 0

    # Store the searched email as an Identifier on the person
    email = result.identifier
    if email and "@" in email:
        try:
            await _safe_upsert_identifier(session, person_id, "email", email, email.strip().lower())
        except Exception:
            pass

    # HIBP-style: list of breach dicts
    for breach in data.get("breaches") or []:
        raw_date = breach.get("date") or breach.get("breach_date")
        breach_date = None
        if raw_date:
            try:
                from datetime import date

                breach_date = date.fromisoformat(str(raw_date))
            except (ValueError, TypeError):
                breach_date = None

        br = BreachRecord(
            id=uuid.uuid4(),
            person_id=person_id,
            breach_name=breach.get("name") or breach.get("domain") or "unknown",
            breach_date=breach_date,
            source_type="clearweb",
            exposed_fields=breach.get("data_classes") or [],
            raw_sample=str(breach),
            meta={"source_platform": result.platform},
        )
        session.add(br)
        count += 1

    # Holehe / registration-presence style: list of service names
    for service in data.get("found_on") or []:
        br = BreachRecord(
            id=uuid.uuid4(),
            person_id=person_id,
            breach_name=str(service),
            source_type="clearweb",
            exposed_fields=["email_registration"],
            meta={"source_platform": "holehe"},
        )
        session.add(br)
        count += 1

    # LeakCheck / generic source list
    for item in data.get("sources") or []:
        br = BreachRecord(
            id=uuid.uuid4(),
            person_id=person_id,
            breach_name=str(item.get("db") if isinstance(item, dict) else item),
            source_type="clearweb",
            exposed_fields=[],
            meta={"source_platform": result.platform},
        )
        session.add(br)
        count += 1

    return count


async def _handle_watchlist(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> int:
    """Write WatchlistMatch rows and raise CRITICAL alerts for each hit."""
    data = result.data or {}
    matches = data.get("matches") or []
    count = 0

    list_name = result.platform.replace("sanctions_", "").upper()

    for match in matches:
        wm = WatchlistMatch(
            id=uuid.uuid4(),
            person_id=person_id,
            list_name=list_name,
            list_type="sanctions",
            match_name=match.get("name", ""),
            match_score=float(match.get("score", 0.8)),
            reason=match.get("reason"),
            is_confirmed=False,
            meta={"raw": match, "source": result.platform},
        )
        session.add(wm)

        alert = Alert(
            id=uuid.uuid4(),
            person_id=person_id,
            alert_type=AlertType.SANCTIONS_HIT.value,
            severity=AlertSeverity.CRITICAL.value,
            title=f"Sanctions hit on {list_name}",
            body=f"Matched name: {match.get('name')} — score {match.get('score', 0.8):.2f}",
            payload={"match": match, "platform": result.platform},
        )
        session.add(alert)
        count += 1

    return count


async def _handle_darkweb(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Write DarkwebMention rows and HIGH alerts for dark-web hits."""
    data = result.data or {}
    mentions = data.get("mentions") or data.get("results") or []

    # Map platform to a source_type the model accepts
    platform = (result.platform or "").lower()
    if "paste" in platform:
        source_type = "paste_site"
    elif "market" in platform:
        source_type = "dark_market"
    elif "forum" in platform:
        source_type = "dark_forum"
    else:
        source_type = "dark_paste"

    for mention in mentions[:10]:
        url = mention.get("url") or mention.get("onion_url") or ""
        url_hash = hashlib.sha256(url.encode()).hexdigest() if url else None
        snippet = (
            mention.get("description") or mention.get("preview") or mention.get("content") or ""
        )[:500]

        dm = DarkwebMention(
            id=uuid.uuid4(),
            person_id=person_id,
            source_type=source_type,
            source_url_hashed=url_hash,
            mention_context=snippet or None,
            severity=AlertSeverity.HIGH.value,
            exposure_score=0.5,
            meta={
                "platform": result.platform,
                "title": mention.get("title", "")[:200],
                "url_preview": url[:100] if url else None,
            },
        )
        session.add(dm)

        title_preview = mention.get("title", "")[:80]
        alert = Alert(
            id=uuid.uuid4(),
            person_id=person_id,
            alert_type=AlertType.DARKWEB_MENTION.value,
            severity=AlertSeverity.HIGH.value,
            title=f"Dark web mention — {result.platform}",
            body=title_preview or f"Mention found on {result.platform}",
            payload={"platform": result.platform, "url_hash": url_hash},
        )
        session.add(alert)


async def _handle_people_search(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Write Address rows from people-search results (up to 3 per scrape)."""
    data = result.data or {}
    results = data.get("results") or []
    now = datetime.now(timezone.utc)

    for r in results[:5]:
        if not isinstance(r, dict):
            continue

        # Crawlers return addresses in multiple formats — handle all
        raw_addresses = r.get("addresses") or []  # list of strings (FPS, TPS)
        single_addr = r.get("address")  # single string
        if single_addr and isinstance(single_addr, str):
            raw_addresses.append(single_addr)
        # Also check structured fields
        if r.get("street"):
            raw_addresses.append(f"{r.get('street', '')} {r.get('city', '')} {r.get('state', '')}".strip())

        for raw in raw_addresses[:3]:
            if not isinstance(raw, str) or len(raw.strip()) < 5:
                continue
            raw = raw.strip()

            # Parse "123 Main St, Dallas, TX 75001" into components
            parts = [p.strip() for p in raw.replace(",", " ").split() if p.strip()]
            city = r.get("city") or ""
            state = r.get("state") or ""
            # Try to extract city/state from city_state field
            city_state = r.get("city_state", "")
            if city_state and not city:
                cs_parts = [p.strip() for p in city_state.split(",")]
                if len(cs_parts) >= 2:
                    city = cs_parts[0]
                    state = cs_parts[-1].split()[0] if cs_parts[-1] else ""
                elif len(cs_parts) == 1:
                    city = cs_parts[0]

            addr = Address(
                id=uuid.uuid4(),
                person_id=person_id,
                street=raw,
                city=city,
                state_province=state,
                country="US",
                country_code="US",
                meta={"raw_address": raw, "scraped_from": result.platform},
                last_scraped_at=now,
                scraped_from=result.platform,
                source_reliability=result.source_reliability,
            )
            apply_quality_to_model(
                addr,
                last_scraped_at=now,
                source_type="default",
                source_name=result.platform,
                corroboration_count=1,
            )
            session.add(addr)

        # Convert age to approximate DOB
        age = r.get("age")
        if age and person_id:
            try:
                age_int = int(str(age).strip())
                if 1 < age_int < 120:
                    from datetime import date
                    approx_year = date.today().year - age_int
                    person = await session.get(Person, person_id)
                    if person and not person.date_of_birth:
                        person.date_of_birth = date(approx_year, 1, 1)
                        if not person.meta:
                            person.meta = {}
                        person.meta["dob_approximate"] = True
            except (ValueError, TypeError):
                pass

        # Also extract phone numbers from per-result card
        card_phones = r.get("phone_numbers") or r.get("phones") or []
        if isinstance(card_phones, str):
            card_phones = [card_phones]
        for ph in card_phones[:3]:
            if not isinstance(ph, str):
                continue
            digits = re.sub(r"[^\d]", "", ph)
            normalized = None
            if len(digits) == 10:
                normalized = f"+1{digits}"
            elif len(digits) == 11 and digits[0] == "1":
                normalized = f"+{digits}"
            elif len(digits) >= 7:
                normalized = f"+{digits}"
            if normalized:
                await _safe_upsert_identifier(session, person_id, "phone", ph, normalized)

    # Extract phone numbers from people search results
    for key in ("phone", "phones", "phone_number", "phone_numbers", "related_phones"):
        phones = data.get(key)
        if phones:
            if isinstance(phones, str):
                phones = [phones]
            for ph in (phones if isinstance(phones, list) else []):
                if not isinstance(ph, str):
                    continue
                digits = re.sub(r"[^\d]", "", ph)
                normalized = None
                if len(digits) == 10:
                    normalized = f"+1{digits}"
                elif len(digits) == 11 and digits[0] == "1":
                    normalized = f"+{digits}"
                elif len(digits) >= 7:
                    normalized = f"+{digits}"
                if normalized:
                    await _safe_upsert_identifier(session, person_id, "phone", ph, normalized)

    # Extract emails from people search results
    for key in ("email", "emails", "email_address", "email_addresses"):
        emails = data.get(key)
        if emails:
            if isinstance(emails, str):
                emails = [emails]
            for em in (emails if isinstance(emails, list) else []):
                if isinstance(em, str) and "@" in em:
                    await _safe_upsert_identifier(session, person_id, "email", em, em.strip().lower())

    # Extract relatives/associated people
    for r in results[:5]:
        if not isinstance(r, dict):
            continue
        relatives = r.get("relatives") or r.get("associated_people") or r.get("family") or []
        if isinstance(relatives, str):
            relatives = [rel.strip() for rel in relatives.split(",") if rel.strip()]
        for rel_name in relatives[:10]:
            if not isinstance(rel_name, str) or len(rel_name.strip()) < 3:
                continue
            rel_name = rel_name.strip()
            # Skip if it's just a descriptor like "son" or "daughter"
            if len(rel_name.split()) < 2:
                continue
            try:
                from shared.models.relationship import Relationship
                # Create or find the relative person
                rel_person = await _get_or_create_person(session, None,
                    CrawlerResult(platform=result.platform, identifier=rel_name, found=True, data={"full_name": rel_name}))
                if rel_person and rel_person.id != person_id:
                    # Check for existing relationship
                    from sqlalchemy import or_, and_
                    existing = (await session.execute(
                        select(Relationship.id).where(
                            or_(
                                and_(Relationship.person_a_id == person_id, Relationship.person_b_id == rel_person.id),
                                and_(Relationship.person_a_id == rel_person.id, Relationship.person_b_id == person_id),
                            )
                        ).limit(1)
                    )).scalar_one_or_none()
                    if not existing:
                        session.add(Relationship(
                            id=uuid.uuid4(),
                            person_a_id=person_id,
                            person_b_id=rel_person.id,
                            relationship_type="associate",
                            confidence_score=0.5,
                            source=result.platform,
                        ))
            except Exception as exc:
                logger.debug("Relative extraction failed for %s: %s", rel_name, exc)


async def _handle_court_records(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> int:
    """Persist structured CriminalRecord rows and raise an alert."""
    data = result.data or {}
    cases = data.get("cases") or []
    count = 0

    for case in cases:
        if not isinstance(case, dict):
            continue

        raw_arrest = case.get("arrest_date") or case.get("date")
        arrest_date = None
        if raw_arrest:
            try:
                from datetime import date as _date

                arrest_date = _date.fromisoformat(str(raw_arrest)[:10])
            except (ValueError, TypeError):
                pass

        raw_disp = case.get("disposition_date") or case.get("closed_date")
        disposition_date = None
        if raw_disp:
            try:
                from datetime import date as _date

                disposition_date = _date.fromisoformat(str(raw_disp)[:10])
            except (ValueError, TypeError):
                pass

        import hashlib

        source_url = case.get("url") or case.get("case_url") or ""
        url_hash = hashlib.sha256(source_url.encode()).hexdigest() if source_url else None

        rec = CriminalRecord(
            id=uuid.uuid4(),
            person_id=person_id,
            record_type="charge",
            offense_level=_normalize_offense_level(case.get("level") or case.get("offense_level")),
            charge=str(case.get("charge") or case.get("offense") or "")[:500] or None,
            offense_description=str(case.get("description") or case.get("details") or "")[:2000]
            or None,
            statute=str(case.get("statute") or case.get("code") or "")[:200] or None,
            court_case_number=str(case.get("case_number") or case.get("docket") or "")[:200]
            or None,
            court_name=str(case.get("court") or case.get("court_name") or "")[:300] or None,
            jurisdiction=str(case.get("jurisdiction") or case.get("county") or "")[:200] or None,
            arrest_date=arrest_date,
            disposition_date=disposition_date,
            disposition=str(case.get("disposition") or case.get("outcome") or "")[:100] or None,
            sentence=str(case.get("sentence") or "")[:500] or None,
            source_platform=result.platform,
            source_url_hashed=url_hash,
            meta={"raw": case, "source_platform": result.platform},
            source_reliability=result.source_reliability,
        )
        session.add(rec)
        count += 1

    if count:
        alert = Alert(
            id=uuid.uuid4(),
            person_id=person_id,
            alert_type=AlertType.CRIMINAL_SIGNAL.value,
            severity=AlertSeverity.MEDIUM.value,
            title=f"Court records found — {result.platform}",
            body=f"{count} case(s) recorded.",
            payload={"case_count": count, "platform": result.platform},
        )
        session.add(alert)

    return count


async def _handle_sex_offender(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> int:
    """Persist sex offender registry hits as CriminalRecord rows."""
    data = result.data or {}
    hits = data.get("hits") or data.get("results") or data.get("offenders") or []
    count = 0

    for hit in hits:
        if not isinstance(hit, dict):
            continue
        rec = CriminalRecord(
            id=uuid.uuid4(),
            person_id=person_id,
            record_type="conviction",
            offense_level="felony",
            charge=str(hit.get("offense") or "Sex Offender Registry")[:500],
            jurisdiction=str(hit.get("jurisdiction") or hit.get("state") or "")[:200] or None,
            is_sex_offender=True,
            source_platform=result.platform,
            meta={"raw": hit, "source_platform": "nsopw"},
            source_reliability=result.source_reliability,
        )
        session.add(rec)
        count += 1

    if count:
        alert = Alert(
            id=uuid.uuid4(),
            person_id=person_id,
            alert_type=AlertType.CRIMINAL_SIGNAL.value,
            severity=AlertSeverity.CRITICAL.value,
            title="Sex offender registry match",
            body=f"{count} match(es) found in NSOPW.",
            payload={"count": count},
        )
        session.add(alert)

    return count


async def _handle_bankruptcy(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Update or create a CreditProfile with bankruptcy indicators."""
    data = result.data or {}
    cases = data.get("cases") or data.get("filings") or []
    if not cases:
        return

    existing = (
        await session.execute(
            select(CreditProfile).where(CreditProfile.person_id == person_id).limit(1)
        )
    ).scalar_one_or_none()

    if existing:
        existing.has_bankruptcy = True
        existing.bankruptcy_count = max(existing.bankruptcy_count, len(cases))
        existing.source_platform = result.platform
    else:
        cp = CreditProfile(
            id=uuid.uuid4(),
            person_id=person_id,
            has_bankruptcy=True,
            bankruptcy_count=len(cases),
            source_platform=result.platform,
            meta={"raw_cases": cases[:3]},
            source_reliability=result.source_reliability,
        )
        session.add(cp)


async def _record_identifier_history(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Append every observed identifier to identifier_history (upsert on conflict)."""
    if not result.identifier:
        return

    now = datetime.now(timezone.utc)

    # Determine type from platform context
    platform = (result.platform or "").lower()
    if "phone" in platform:
        id_type = "phone"
    elif "email" in platform:
        id_type = "email"
    elif platform in {
        "instagram",
        "twitter",
        "tiktok",
        "snapchat",
        "facebook",
        "linkedin",
        "reddit",
        "youtube",
        "telegram",
        "discord",
        "whatsapp",
        "pinterest",
        "github",
    }:
        id_type = "handle"
    else:
        id_type = "identifier"

    normalized = result.identifier.lower().strip()

    existing = (
        await session.execute(
            select(IdentifierHistory)
            .where(
                IdentifierHistory.person_id == person_id,
                IdentifierHistory.type == id_type,
                IdentifierHistory.value == result.identifier,
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    if existing:
        existing.last_seen_at = now
        existing.is_current = True
    else:
        entry = IdentifierHistory(
            id=uuid.uuid4(),
            person_id=person_id,
            type=id_type,
            value=result.identifier,
            normalized_value=normalized,
            first_seen_at=now,
            last_seen_at=now,
            is_current=True,
            confidence=result.source_reliability,
            source_platform=result.platform,
        )
        session.add(entry)


def _normalize_offense_level(level: str | None) -> str | None:
    if not level:
        return None
    level = level.lower().strip()
    if "felony" in level or "fel" == level:
        return "felony"
    if "misdemeanor" in level or "misd" in level:
        return "misdemeanor"
    if "infraction" in level or "violation" in level:
        return "infraction"
    return "unknown"


async def _handle_behavioural(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Update or create a BehaviouralProfile from social-post analysis signals."""
    data = result.data or {}

    gambling = 1.0 if data.get("gambling_language") else 0.0
    financial = 1.0 if data.get("financial_stress_language") else 0.0
    substance = 1.0 if data.get("substance_language") else 0.0
    aggression = 1.0 if data.get("aggression_language") else 0.0

    existing = (
        await session.execute(
            select(BehaviouralProfile).where(BehaviouralProfile.person_id == person_id).limit(1)
        )
    ).scalar_one_or_none()

    if existing:
        existing.gambling_score = max(existing.gambling_score or 0.0, gambling)
        existing.financial_distress_score = max(existing.financial_distress_score or 0.0, financial)
        existing.drug_signal_score = max(existing.drug_signal_score or 0.0, substance)
        existing.violence_score = max(existing.violence_score or 0.0, aggression)
        existing.last_assessed_at = datetime.now(timezone.utc)
        if "ocean_openness" in data:
            existing.meta = existing.meta or {}
            existing.meta["ocean_openness"] = data["ocean_openness"]
            existing.meta["ocean_conscientiousness"] = data.get("ocean_conscientiousness")
            existing.meta["ocean_extraversion"] = data.get("ocean_extraversion")
            existing.meta["ocean_agreeableness"] = data.get("ocean_agreeableness")
            existing.meta["ocean_neuroticism"] = data.get("ocean_neuroticism")
    else:
        meta: dict = {}
        if "ocean_openness" in data:
            meta["ocean_openness"] = data["ocean_openness"]
            meta["ocean_conscientiousness"] = data.get("ocean_conscientiousness")
            meta["ocean_extraversion"] = data.get("ocean_extraversion")
            meta["ocean_agreeableness"] = data.get("ocean_agreeableness")
            meta["ocean_neuroticism"] = data.get("ocean_neuroticism")
        bp = BehaviouralProfile(
            id=uuid.uuid4(),
            person_id=person_id,
            gambling_score=gambling,
            financial_distress_score=financial,
            fraud_score=0.0,
            drug_signal_score=substance,
            violence_score=aggression,
            criminal_signal_score=0.0,
            last_assessed_at=datetime.now(timezone.utc),
            meta=meta,
        )
        session.add(bp)


def _parse_date_field(item: dict, *keys: str):
    """Try multiple dict keys to extract a date, return datetime or None."""
    from dateutil import parser as _dp
    for k in keys:
        v = item.get(k)
        if v and isinstance(v, str):
            try:
                return _dp.parse(v)
            except (ValueError, OverflowError):
                pass
    return None


async def _handle_employment(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Persist employment / work-history rows from crawl data."""
    if EmploymentHistory is None:
        return
    data = result.data or {}
    items = data.get("employment") or data.get("work_history") or data.get("jobs") or []
    if isinstance(items, dict):
        items = [items]
    now = datetime.now(timezone.utc)
    for item in items:
        if not isinstance(item, dict):
            continue
        obj = EmploymentHistory(
            id=uuid.uuid4(),
            person_id=person_id,
            employer_name=str(item.get("company") or item.get("employer") or item.get("employer_name") or "")[:500] or None,
            job_title=str(item.get("title") or item.get("job_title") or item.get("position") or "")[:500] or None,
            industry=str(item.get("industry") or "")[:255] or None,
            is_current=bool(item.get("is_current") or item.get("current")),
            location=str(item.get("location") or "")[:255] or None,
            started_at=_parse_date_field(item, "start_date", "started_at", "date_started", "from"),
            ended_at=_parse_date_field(item, "end_date", "ended_at", "date_ended", "to"),
            meta={"raw": item, "source_platform": result.platform},
        )
        apply_quality_to_model(
            obj, last_scraped_at=now, source_type="employment",
            source_name=result.platform, corroboration_count=1,
        )
        session.add(obj)


async def _handle_education(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Persist education rows from crawl data."""
    if Education is None:
        return
    data = result.data or {}
    items = data.get("education") or data.get("schools") or []
    if isinstance(items, dict):
        items = [items]
    now = datetime.now(timezone.utc)
    for item in items:
        if not isinstance(item, dict):
            continue
        obj = Education(
            id=uuid.uuid4(),
            person_id=person_id,
            institution=str(item.get("school") or item.get("institution") or item.get("university") or "")[:500] or None,
            degree=str(item.get("degree") or "")[:255] or None,
            field_of_study=str(item.get("field_of_study") or item.get("major") or item.get("field") or "")[:255] or None,
            is_completed=bool(item.get("is_completed", True)),
            tier=str(item.get("tier") or "")[:50] or None,
            meta={"raw": item, "source_platform": result.platform},
        )
        apply_quality_to_model(
            obj, last_scraped_at=now, source_type="education",
            source_name=result.platform, corroboration_count=1,
        )
        session.add(obj)


async def _handle_property(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Persist property rows from crawl data."""
    if Property is None:
        return
    data = result.data or {}
    items = data.get("properties") or data.get("results") or data.get("parcels") or []
    if isinstance(items, dict):
        items = [items]
    now = datetime.now(timezone.utc)
    for item in items:
        if not isinstance(item, dict):
            continue
        obj = Property(
            id=uuid.uuid4(),
            person_id=person_id,
            street_address=str(item.get("address") or item.get("street_address") or "")[:500] or None,
            city=str(item.get("city") or "")[:255] or None,
            state=str(item.get("state") or "")[:100] or None,
            zip_code=str(item.get("zip") or item.get("zip_code") or "")[:20] or None,
            county=str(item.get("county") or "")[:255] or None,
            country=str(item.get("country") or "US")[:100],
            property_type=str(item.get("property_type") or item.get("type") or "")[:50] or None,
            year_built=item.get("year_built"),
            sq_ft_living=item.get("sq_ft") or item.get("sq_ft_living"),
            bedrooms=item.get("bedrooms") or item.get("beds"),
            bathrooms_full=item.get("bathrooms") or item.get("bathrooms_full") or item.get("baths"),
            parcel_number=str(item.get("parcel_number") or item.get("apn") or "")[:100] or None,
            meta={"raw": item, "source_platform": result.platform},
        )
        apply_quality_to_model(
            obj, last_scraped_at=now, source_type="property_record",
            source_name=result.platform, corroboration_count=1,
        )
        session.add(obj)


async def _handle_vehicle(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Persist vehicle rows from crawl data."""
    if Vehicle is None:
        return
    data = result.data or {}
    items = data.get("vehicles") or data.get("results") or []
    if isinstance(items, dict):
        items = [items]
    now = datetime.now(timezone.utc)
    for item in items:
        if not isinstance(item, dict):
            continue
        obj = Vehicle(
            id=uuid.uuid4(),
            person_id=person_id,
            vin=str(item.get("vin") or "")[:17] or None,
            make=str(item.get("make") or "")[:100] or None,
            model=str(item.get("model") or "")[:100] or None,
            year=int(item["year"]) if item.get("year") and str(item["year"]).isdigit() else None,
            body_style=str(item.get("body_style") or item.get("type") or "")[:50] or None,
            color_exterior=str(item.get("color") or item.get("color_exterior") or "")[:50] or None,
            license_plate=str(item.get("plate") or item.get("license_plate") or "")[:50] or None,
            plate_state=str(item.get("plate_state") or item.get("state") or "")[:10] or None,
            title_status=str(item.get("title_status") or "")[:50] or None,
            meta={"raw": item, "source_platform": result.platform},
        )
        apply_quality_to_model(
            obj, last_scraped_at=now, source_type="vehicle_record",
            source_name=result.platform, corroboration_count=1,
        )
        session.add(obj)


async def _handle_financial(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Persist crypto wallet and corporate directorship rows from financial crawlers."""
    data = result.data or {}

    # Crypto wallets
    if CryptoWallet is not None:
        wallets = data.get("wallets") or data.get("addresses") or []
        if isinstance(wallets, dict):
            wallets = [wallets]
        for w in wallets:
            if not isinstance(w, dict):
                continue
            addr = w.get("address") or w.get("wallet")
            if not addr:
                continue
            obj = CryptoWallet(
                id=uuid.uuid4(),
                person_id=person_id,
                address=str(addr)[:255],
                chain=str(w.get("chain") or w.get("blockchain") or "unknown")[:20],
                total_volume_usd=float(w.get("total_volume_usd") or w.get("volume") or 0.0),
                mixer_exposure=bool(w.get("mixer_exposure")),
                risk_score=float(w.get("risk_score") or 0.0),
                meta={"raw": w, "source_platform": result.platform},
            )
            session.add(obj)

    # SEC / FINRA / corporate filings -> CorporateDirectorship
    if CorporateDirectorship is not None:
        filings = data.get("filings") or data.get("directorships") or data.get("officers") or []
        if isinstance(filings, dict):
            filings = [filings]
        now = datetime.now(timezone.utc)
        for f in filings:
            if not isinstance(f, dict):
                continue
            obj = CorporateDirectorship(
                id=uuid.uuid4(),
                person_id=person_id,
                company_name=str(f.get("company") or f.get("company_name") or f.get("entity") or "")[:500] or None,
                company_registration=str(f.get("cik") or f.get("registration") or "")[:200] or None,
                company_jurisdiction=str(f.get("jurisdiction") or f.get("state") or "")[:255] or None,
                role=str(f.get("role") or f.get("title") or f.get("position") or "")[:200] or None,
                is_executive=bool(f.get("is_executive")),
                is_board_member=bool(f.get("is_board_member")),
                is_current=bool(f.get("is_current", True)),
                meta={"raw": f, "source_platform": result.platform},
            )
            apply_quality_to_model(
                obj, last_scraped_at=now, source_type="financial_record",
                source_name=result.platform, corroboration_count=1,
            )
            session.add(obj)


async def _handle_news(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Persist adverse media / news article rows."""
    if AdverseMedia is None:
        return
    data = result.data or {}
    items = data.get("articles") or data.get("results") or data.get("news") or data.get("mentions") or []
    if isinstance(items, dict):
        items = [items]
    now = datetime.now(timezone.utc)
    for item in items[:50]:  # cap at 50 articles per crawl
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("link") or "")[:2048] or None
        url_hash = hashlib.sha256(url.encode()).hexdigest() if url else None

        raw_date = item.get("date") or item.get("published_date") or item.get("publication_date")
        pub_date = None
        if raw_date:
            try:
                from datetime import date as _date
                pub_date = _date.fromisoformat(str(raw_date)[:10])
            except (ValueError, TypeError):
                pass

        obj = AdverseMedia(
            id=uuid.uuid4(),
            person_id=person_id,
            headline=str(item.get("title") or item.get("headline") or "")[:2000] or None,
            summary=str(item.get("snippet") or item.get("summary") or item.get("description") or "")[:5000] or None,
            url=url,
            url_hash=url_hash,
            publication_date=pub_date,
            source_name=str(item.get("source") or item.get("source_name") or item.get("publisher") or "")[:255] or None,
            language=str(item.get("language") or "en")[:20],
            category=str(item.get("category") or "")[:100] or None,
            severity="medium",
            sentiment_score=item.get("sentiment_score") or item.get("sentiment"),
            meta={"raw": item, "source_platform": result.platform},
        )
        apply_quality_to_model(
            obj, last_scraped_at=now, source_type="news_article",
            source_name=result.platform, corroboration_count=1,
        )
        session.add(obj)


async def _handle_government(
    session: AsyncSession,
    result: CrawlerResult,
    person_id: uuid.UUID,
) -> None:
    """Persist voter registration addresses and professional licenses from gov sources."""
    data = result.data or {}
    now = datetime.now(timezone.utc)

    # Voter registration -> Address rows
    addresses = data.get("addresses") or data.get("voter_addresses") or []
    if isinstance(addresses, dict):
        addresses = [addresses]
    for item in addresses:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("address") or item.get("street") or "").strip()
        if not raw:
            continue
        addr = Address(
            id=uuid.uuid4(),
            person_id=person_id,
            street=item.get("street") or raw,
            city=item.get("city"),
            state_province=item.get("state"),
            country=item.get("country", "US"),
            country_code=item.get("country_code", "US"),
            meta={"raw_address": raw, "scraped_from": result.platform},
            last_scraped_at=now,
            scraped_from=result.platform,
            source_reliability=result.source_reliability,
        )
        apply_quality_to_model(
            addr, last_scraped_at=now, source_type="government_record",
            source_name=result.platform, corroboration_count=1,
        )
        session.add(addr)

    # Professional licenses
    if ProfessionalLicense is not None:
        licenses = data.get("licenses") or data.get("professional_licenses") or []
        if isinstance(licenses, dict):
            licenses = [licenses]
        for lic in licenses:
            if not isinstance(lic, dict):
                continue
            obj = ProfessionalLicense(
                id=uuid.uuid4(),
                person_id=person_id,
                license_type=str(lic.get("type") or lic.get("license_type") or "")[:200] or None,
                license_number=str(lic.get("number") or lic.get("license_number") or "")[:200] or None,
                issuing_body=str(lic.get("issuing_body") or lic.get("board") or "")[:500] or None,
                issuing_state=str(lic.get("state") or lic.get("issuing_state") or "")[:100] or None,
                is_active=bool(lic.get("is_active", True)),
                is_revoked=bool(lic.get("is_revoked")),
                is_suspended=bool(lic.get("is_suspended")),
                meta={"raw": lic, "source_platform": result.platform},
            )
            apply_quality_to_model(
                obj, last_scraped_at=now, source_type="government_record",
                source_name=result.platform, corroboration_count=1,
            )
            session.add(obj)


def _looks_like_phone_number(value: str) -> bool:
    """True if value looks like a phone number (7-15 digits, optional + prefix)."""
    import re

    digits = re.sub(r"\D", "", value)
    return 7 <= len(digits) <= 15


async def _upsert_phone_identifier(
    session: AsyncSession,
    phone: str,
    person_id: uuid.UUID,
    source_platform: str,
) -> None:
    """Ensure this phone number exists as an Identifier row for the person."""
    # Normalize: strip spaces/dashes, ensure leading +
    import re

    digits = re.sub(r"\D", "", phone)
    normalized = f"+{digits}"

    existing = (
        await session.execute(
            select(Identifier)
            .where(
                Identifier.person_id == person_id,
                Identifier.type == IdentifierType.PHONE.value,
                Identifier.normalized_value == normalized,
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    if existing:
        # Confirm on an additional platform
        existing.corroboration_count = (existing.corroboration_count or 1) + 1
        existing.meta = {**(existing.meta or {}), f"confirmed_{source_platform}": True}
        return

    await _safe_upsert_identifier(
        session,
        person_id=person_id,
        id_type=IdentifierType.PHONE.value,
        raw_value=phone,
        normalized_value=normalized,
        confidence=0.9,
        is_primary=False,
        meta={"confirmed_via": source_platform, f"confirmed_{source_platform}": True},
        source_reliability=0.8,
    )
