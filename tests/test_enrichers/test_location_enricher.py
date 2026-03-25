"""
test_location_enricher.py — Unit tests for modules/enrichers/location_enricher.py.

Covers:
  - _resolve_country_code: ISO2 from code, name lookup, invalid → None
  - _from_addresses: country_code + name fields, no country → skip
  - _from_social_profiles: profile_data country_code / country fields
  - _from_ip_geo: Identifier.meta.geo fields
  - _upsert: new visit → INSERT; existing visit → update last_seen + visit_count
  - enrich: orchestrates all three sources, returns total count
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.location_enricher import LocationEnricher, _resolve_country_code

# ── _resolve_country_code tests ───────────────────────────────────────────────


class TestResolveCountryCode:
    def test_valid_iso2_code_returned_uppercase(self):
        assert _resolve_country_code("us", None) == "US"
        assert _resolve_country_code("GB", None) == "GB"

    def test_invalid_iso2_falls_back_to_name(self):
        assert _resolve_country_code("USA", "United States") == "US"

    def test_name_lookup_works(self):
        assert _resolve_country_code(None, "united kingdom") == "GB"
        assert _resolve_country_code(None, "Australia") == "AU"

    def test_unknown_name_returns_none(self):
        assert _resolve_country_code(None, "Narnia") is None

    def test_both_none_returns_none(self):
        assert _resolve_country_code(None, None) is None

    def test_three_letter_code_falls_back_to_name(self):
        # 3-letter code fails ISO2 regex, falls back to name
        result = _resolve_country_code("ZAF", "South Africa")
        assert result == "ZA"


# ── Session helper ────────────────────────────────────────────────────────────


def _make_session(addresses=None, profiles=None, identifiers=None, existing_visit=None):
    """Build mock session returning given lists in execute() call order."""
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    calls = []
    for lst in (addresses or [], profiles or [], identifiers or []):
        r = MagicMock()
        r.scalars.return_value.all.return_value = lst
        calls.append(r)

    # For _upsert, each call needs a scalar_one_or_none for existing-visit lookup
    # We'll add those at the end
    for _ in range(len(addresses or []) + len(profiles or []) + len(identifiers or [])):
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing_visit
        calls.append(r)

    session.execute = AsyncMock(side_effect=calls)
    return session


def _mock_address(country_code=None, country=None, city=None, state=None):
    a = MagicMock()
    a.country_code = country_code
    a.country = country
    a.city = city
    a.state_province = state
    return a


def _mock_profile(profile_data=None):
    p = MagicMock()
    p.profile_data = profile_data or {}
    return p


def _mock_identifier(meta=None):
    i = MagicMock()
    i.meta = meta or {}
    return i


# ── _from_addresses ───────────────────────────────────────────────────────────


class TestFromAddresses:
    @pytest.mark.asyncio
    async def test_address_with_country_code_creates_visit(self):
        addr = _mock_address(country_code="US", country="United States", city="Austin", state="TX")
        session = AsyncMock()
        session.flush = AsyncMock()

        # First call: addresses list; second: existing visit lookup
        addr_result = MagicMock()
        addr_result.scalars.return_value.all.return_value = [addr]
        visit_result = MagicMock()
        visit_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[addr_result, visit_result])
        session.add = MagicMock()

        enricher = LocationEnricher()
        count = await enricher._from_addresses(uuid.uuid4(), session)
        assert count == 1
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_address_without_country_skipped(self):
        addr = _mock_address(country_code=None, country=None)
        session = AsyncMock()
        addr_result = MagicMock()
        addr_result.scalars.return_value.all.return_value = [addr]
        session.execute = AsyncMock(return_value=addr_result)

        enricher = LocationEnricher()
        count = await enricher._from_addresses(uuid.uuid4(), session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_address_with_existing_visit_updates_count(self):
        addr = _mock_address(country_code="GB")
        existing_visit = MagicMock()
        existing_visit.visit_count = 2
        existing_visit.country_name = None
        existing_visit.city = None
        existing_visit.region = None
        existing_visit.last_seen = None

        session = AsyncMock()
        session.flush = AsyncMock()
        addr_result = MagicMock()
        addr_result.scalars.return_value.all.return_value = [addr]
        visit_result = MagicMock()
        visit_result.scalar_one_or_none.return_value = existing_visit
        session.execute = AsyncMock(side_effect=[addr_result, visit_result])

        enricher = LocationEnricher()
        count = await enricher._from_addresses(uuid.uuid4(), session)
        assert count == 1
        assert existing_visit.visit_count == 3


# ── _from_social_profiles ─────────────────────────────────────────────────────


class TestFromSocialProfiles:
    @pytest.mark.asyncio
    async def test_profile_data_country_code_creates_visit(self):
        profile = _mock_profile({"country_code": "DE", "city": "Berlin"})
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()

        profiles_result = MagicMock()
        profiles_result.scalars.return_value.all.return_value = [profile]
        visit_result = MagicMock()
        visit_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[profiles_result, visit_result])

        enricher = LocationEnricher()
        count = await enricher._from_social_profiles(uuid.uuid4(), session)
        assert count == 1

    @pytest.mark.asyncio
    async def test_profile_data_country_name_used_as_fallback(self):
        profile = _mock_profile({"country": "France"})
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()

        profiles_result = MagicMock()
        profiles_result.scalars.return_value.all.return_value = [profile]
        visit_result = MagicMock()
        visit_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[profiles_result, visit_result])

        enricher = LocationEnricher()
        count = await enricher._from_social_profiles(uuid.uuid4(), session)
        assert count == 1

    @pytest.mark.asyncio
    async def test_profile_data_no_country_skipped(self):
        profile = _mock_profile({"bio": "I love dogs"})
        session = AsyncMock()
        profiles_result = MagicMock()
        profiles_result.scalars.return_value.all.return_value = [profile]
        session.execute = AsyncMock(return_value=profiles_result)

        enricher = LocationEnricher()
        count = await enricher._from_social_profiles(uuid.uuid4(), session)
        assert count == 0


# ── _from_ip_geo ──────────────────────────────────────────────────────────────


class TestFromIpGeo:
    @pytest.mark.asyncio
    async def test_ip_geo_meta_creates_visit(self):
        ident = _mock_identifier(meta={"geo": {"country_code": "BR", "city": "São Paulo"}})
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add = MagicMock()

        idents_result = MagicMock()
        idents_result.scalars.return_value.all.return_value = [ident]
        visit_result = MagicMock()
        visit_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[idents_result, visit_result])

        enricher = LocationEnricher()
        count = await enricher._from_ip_geo(uuid.uuid4(), session)
        assert count == 1

    @pytest.mark.asyncio
    async def test_ip_geo_no_country_in_meta_skipped(self):
        ident = _mock_identifier(meta={"geo": {"isp": "Comcast"}})  # no country
        session = AsyncMock()
        idents_result = MagicMock()
        idents_result.scalars.return_value.all.return_value = [ident]
        session.execute = AsyncMock(return_value=idents_result)

        enricher = LocationEnricher()
        count = await enricher._from_ip_geo(uuid.uuid4(), session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_ip_geo_empty_meta_skipped(self):
        ident = _mock_identifier(meta={})
        session = AsyncMock()
        idents_result = MagicMock()
        idents_result.scalars.return_value.all.return_value = [ident]
        session.execute = AsyncMock(return_value=idents_result)

        enricher = LocationEnricher()
        count = await enricher._from_ip_geo(uuid.uuid4(), session)
        assert count == 0


# ── _upsert: backfill fields on existing visit ────────────────────────────────


class TestUpsertBackfill:
    @pytest.mark.asyncio
    async def test_existing_visit_backfills_missing_fields(self):
        """If existing visit has no city/region/country_name, they get filled in."""
        existing = MagicMock()
        existing.visit_count = 1
        existing.country_name = None
        existing.city = None
        existing.region = None
        existing.last_seen = None

        session = AsyncMock()
        session.flush = AsyncMock()
        visit_result = MagicMock()
        visit_result.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=visit_result)

        enricher = LocationEnricher()
        result = await enricher._upsert(
            session=session,
            pid=uuid.uuid4(),
            country_code="AU",
            country_name="Australia",
            city="Sydney",
            region="NSW",
            source="address",
            confidence=0.9,
        )

        assert result is True
        assert existing.country_name == "Australia"
        assert existing.city == "Sydney"
        assert existing.region == "NSW"
        assert existing.visit_count == 2


# ── enrich: full integration ──────────────────────────────────────────────────


class TestEnrichIntegration:
    @pytest.mark.asyncio
    async def test_enrich_returns_total_from_all_sources(self):
        """enrich() calls _from_addresses, _from_social_profiles, _from_ip_geo."""
        enricher = LocationEnricher()
        pid = str(uuid.uuid4())
        session = AsyncMock()

        with (
            patch.object(enricher, "_from_addresses", new=AsyncMock(return_value=2)),
            patch.object(enricher, "_from_social_profiles", new=AsyncMock(return_value=1)),
            patch.object(enricher, "_from_ip_geo", new=AsyncMock(return_value=3)),
        ):
            total = await enricher.enrich(pid, session)

        assert total == 6

    @pytest.mark.asyncio
    async def test_enrich_returns_zero_when_all_empty(self):
        enricher = LocationEnricher()
        pid = str(uuid.uuid4())
        session = AsyncMock()

        with (
            patch.object(enricher, "_from_addresses", new=AsyncMock(return_value=0)),
            patch.object(enricher, "_from_social_profiles", new=AsyncMock(return_value=0)),
            patch.object(enricher, "_from_ip_geo", new=AsyncMock(return_value=0)),
        ):
            total = await enricher.enrich(pid, session)

        assert total == 0
