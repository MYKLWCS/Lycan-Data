"""
location_enricher.py — Countries visited inference enricher.

Derives LocationVisit records for a person by mining:
  1. Address records  (country_code + city already stored)
  2. SocialProfile.profile_data  (location, city, country, country_code fields)
  3. IP geo results stored in Identifier meta  (geo_ip crawl results)

Each unique (person_id, country_code, source) triple is upserted:
  - new → INSERT
  - existing → update last_seen + increment visit_count

Known ISO-3166-1 alpha-2 codes are accepted as-is.
Country names are normalised to 2-letter codes via a compact lookup table.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timezone, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.address import Address
from shared.models.identifier import Identifier
from shared.models.location_visit import LocationVisit
from shared.models.social_profile import SocialProfile

logger = logging.getLogger(__name__)

# Compact name → ISO 3166-1 alpha-2 lookup (most common countries)
_NAME_TO_CODE: dict[str, str] = {
    "united states": "US",
    "usa": "US",
    "u.s.a.": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "england": "GB",
    "australia": "AU",
    "canada": "CA",
    "germany": "DE",
    "france": "FR",
    "spain": "ES",
    "italy": "IT",
    "netherlands": "NL",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "switzerland": "CH",
    "austria": "AT",
    "belgium": "BE",
    "portugal": "PT",
    "poland": "PL",
    "russia": "RU",
    "china": "CN",
    "japan": "JP",
    "south korea": "KR",
    "india": "IN",
    "brazil": "BR",
    "mexico": "MX",
    "south africa": "ZA",
    "nigeria": "NG",
    "kenya": "KE",
    "ghana": "GH",
    "zambia": "ZM",
    "botswana": "BW",
    "zimbabwe": "ZW",
    "singapore": "SG",
    "malaysia": "MY",
    "indonesia": "ID",
    "thailand": "TH",
    "vietnam": "VN",
    "philippines": "PH",
    "new zealand": "NZ",
    "israel": "IL",
    "turkey": "TR",
    "uae": "AE",
    "united arab emirates": "AE",
    "saudi arabia": "SA",
    "egypt": "EG",
    "argentina": "AR",
    "colombia": "CO",
    "chile": "CL",
    "peru": "PE",
    "pakistan": "PK",
    "bangladesh": "BD",
    "sri lanka": "LK",
    "ukraine": "UA",
    "czech republic": "CZ",
    "hungary": "HU",
    "romania": "RO",
    "ireland": "IE",
    "greece": "GR",
    "hong kong": "HK",
    "taiwan": "TW",
}

import re

# Valid ISO 3166-1 alpha-2 codes (2 uppercase letters)
_ISO2 = re.compile(r"^[A-Z]{2}$")


def _resolve_country_code(code: str | None, name: str | None) -> str | None:
    """Return a valid ISO-2 country code or None."""
    if code:
        upper = code.strip().upper()
        if _ISO2.match(upper):
            return upper
    if name:
        normalized = name.strip().lower()
        return _NAME_TO_CODE.get(normalized)
    return None


class LocationEnricher:
    """
    Infers countries visited from stored records and upserts LocationVisit rows.
    """

    async def enrich(self, person_id: str, session: AsyncSession) -> int:
        """
        Run location inference for one person.
        Returns the number of LocationVisit rows created or updated.
        """
        pid = uuid.UUID(person_id)
        touched = 0

        touched += await self._from_addresses(pid, session)
        touched += await self._from_social_profiles(pid, session)
        touched += await self._from_ip_geo(pid, session)

        return touched

    async def _from_addresses(self, pid: uuid.UUID, session: AsyncSession) -> int:
        result = await session.execute(select(Address).where(Address.person_id == pid))
        addresses: list[Address] = list(result.scalars().all())
        count = 0
        for addr in addresses:
            cc = _resolve_country_code(addr.country_code, addr.country)
            if not cc:
                continue
            updated = await self._upsert(
                session=session,
                pid=pid,
                country_code=cc,
                country_name=addr.country,
                city=addr.city,
                region=addr.state_province,
                source="address",
                confidence=0.9,
            )
            if updated:
                count += 1
        return count

    async def _from_social_profiles(self, pid: uuid.UUID, session: AsyncSession) -> int:
        result = await session.execute(select(SocialProfile).where(SocialProfile.person_id == pid))
        profiles: list[SocialProfile] = list(result.scalars().all())
        count = 0
        for profile in profiles:
            data: dict = profile.profile_data or {}
            cc = _resolve_country_code(
                data.get("country_code") or data.get("country_iso"),
                data.get("country") or data.get("location_country"),
            )
            if not cc:
                continue
            city = data.get("city") or data.get("location_city")
            region = data.get("state") or data.get("region") or data.get("location_region")
            updated = await self._upsert(
                session=session,
                pid=pid,
                country_code=cc,
                country_name=data.get("country"),
                city=city,
                region=region,
                source="social_checkin",
                confidence=0.75,
            )
            if updated:
                count += 1
        return count

    async def _from_ip_geo(self, pid: uuid.UUID, session: AsyncSession) -> int:
        """Read Identifier rows of type 'ip_address' whose meta has geo data."""
        result = await session.execute(
            select(Identifier).where(
                Identifier.person_id == pid,
                Identifier.type == "ip_address",
            )
        )
        identifiers: list[Identifier] = list(result.scalars().all())
        count = 0
        for ident in identifiers:
            meta: dict = ident.meta or {}
            geo = meta.get("geo") or {}
            cc = _resolve_country_code(
                geo.get("country_code") or geo.get("country_iso"),
                geo.get("country"),
            )
            if not cc:
                continue
            updated = await self._upsert(
                session=session,
                pid=pid,
                country_code=cc,
                country_name=geo.get("country"),
                city=geo.get("city"),
                region=geo.get("region"),
                source="ip_geo",
                confidence=0.6,
            )
            if updated:
                count += 1
        return count

    async def _upsert(
        self,
        session: AsyncSession,
        pid: uuid.UUID,
        country_code: str,
        country_name: str | None,
        city: str | None,
        region: str | None,
        source: str,
        confidence: float,
    ) -> bool:
        """
        Insert a new LocationVisit or update an existing one's last_seen /
        visit_count. Returns True if a row was affected.
        """
        existing_result = await session.execute(
            select(LocationVisit).where(
                LocationVisit.person_id == pid,
                LocationVisit.country_code == country_code,
                LocationVisit.source == source,
            )
        )
        existing = existing_result.scalar_one_or_none()
        now = datetime.now(timezone.utc)

        if existing:
            existing.last_seen = now
            existing.visit_count = (existing.visit_count or 0) + 1
            if not existing.country_name and country_name:
                existing.country_name = country_name
            if not existing.city and city:
                existing.city = city
            if not existing.region and region:
                existing.region = region
        else:
            visit = LocationVisit(
                person_id=pid,
                country_code=country_code,
                country_name=country_name,
                city=city,
                region=region,
                source=source,
                confidence=confidence,
                first_seen=now,
                last_seen=now,
                visit_count=1,
            )
            session.add(visit)

        await session.flush()
        return True
