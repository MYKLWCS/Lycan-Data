"""
test_timeline_builder.py — Unit tests for modules/enrichers/timeline_builder.py.

Covers:
  - _to_date(): None → None
  - _to_date(): datetime → date
  - _to_date(): date passthrough
  - _to_date(): ISO string → date
  - _to_date(): invalid string → None
  - _to_date(): non-string invalid → None
  - build(): no source tables → 0 new events
  - build(): events without date are skipped
  - build(): existing event (duplicate) → not counted as new
  - build(): new events counted correctly
  - build(): calls all 11 source extractors
  - _upsert_event(): new event → returns True, session.add called
  - _upsert_event(): duplicate lower confidence → returns False, no update
  - _upsert_event(): duplicate higher confidence → returns False but updates fields
  - _upsert_event(): meta merging on high-confidence update
  - _events_from_criminal(): arrest / charge / disposition / warrant events
  - _events_from_employment(): start and end events
  - _events_from_education(): start and graduation events
  - _events_from_addresses(): address_change events; skips records without created_at
  - _events_from_properties(): property_purchase events; skips if no last_sale_date
  - _events_from_social_profiles(): social_profile_created; skips if no profile_created_at
  - _events_from_adverse_media(): adverse_media events; skips retracted; skips no pub_date
  - _events_from_pep(): pep_appointment; skips if no start_date
  - _events_from_watchlist(): watchlist_listed; falls back to created_at when listed_date absent
  - _events_from_breaches(): breach_exposure; falls back to created_at
  - _events_from_travel(): travel events; includes flag reason when flagged
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.enrichers.timeline_builder import TimelineBuilder, _to_date

# ── _to_date() ────────────────────────────────────────────────────────────────


class TestToDate:
    def test_none_returns_none(self):
        assert _to_date(None) is None

    def test_datetime_returns_date(self):
        dt = datetime(2023, 6, 15, 10, 30, 0, tzinfo=UTC)
        result = _to_date(dt)
        assert result == date(2023, 6, 15)

    def test_date_passthrough(self):
        d = date(2020, 1, 1)
        assert _to_date(d) is d

    def test_iso_string_parsed(self):
        assert _to_date("2021-09-01") == date(2021, 9, 1)

    def test_iso_datetime_string_parsed(self):
        assert _to_date("2021-09-01T14:30:00") == date(2021, 9, 1)

    def test_invalid_string_returns_none(self):
        assert _to_date("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert _to_date("") is None

    def test_integer_returns_none(self):
        # int cast to str is not a valid ISO date
        assert _to_date(20210901) is None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _mock_execute_empty(session: AsyncMock) -> None:
    """Make session.execute always return an empty scalars list."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=r)


def _scalars_result(items: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _scalar_one_or_none(value) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


# ── build() ───────────────────────────────────────────────────────────────────


class TestBuild:
    async def test_build_empty_tables_returns_zero(self):
        """All source tables empty → 0 new events."""
        builder = TimelineBuilder()
        session = _make_session()
        _mock_execute_empty(session)

        result = await builder.build(uuid.uuid4(), session)
        assert result == 0

    async def test_build_skips_events_without_date(self):
        """Events returned from extractors with event_date=None are dropped."""
        builder = TimelineBuilder()
        session = _make_session()

        dateless_event = {
            "event_type": "criminal_arrest",
            "event_date": None,
            "title": "No date",
        }
        builder._events_from_criminal = AsyncMock(return_value=[dateless_event])
        builder._events_from_employment = AsyncMock(return_value=[])
        builder._events_from_education = AsyncMock(return_value=[])
        builder._events_from_addresses = AsyncMock(return_value=[])
        builder._events_from_properties = AsyncMock(return_value=[])
        builder._events_from_social_profiles = AsyncMock(return_value=[])
        builder._events_from_adverse_media = AsyncMock(return_value=[])
        builder._events_from_pep = AsyncMock(return_value=[])
        builder._events_from_watchlist = AsyncMock(return_value=[])
        builder._events_from_breaches = AsyncMock(return_value=[])
        builder._events_from_travel = AsyncMock(return_value=[])
        builder._upsert_event = AsyncMock(return_value=True)

        result = await builder.build(uuid.uuid4(), session)
        assert result == 0
        builder._upsert_event.assert_not_awaited()

    async def test_build_counts_new_events(self):
        """Each _upsert_event returning True increments the count."""
        builder = TimelineBuilder()
        session = _make_session()

        ev = {"event_type": "employment_start", "event_date": date(2020, 1, 1), "title": "Job"}
        builder._events_from_criminal = AsyncMock(return_value=[ev])
        builder._events_from_employment = AsyncMock(return_value=[ev])
        builder._events_from_education = AsyncMock(return_value=[])
        builder._events_from_addresses = AsyncMock(return_value=[])
        builder._events_from_properties = AsyncMock(return_value=[])
        builder._events_from_social_profiles = AsyncMock(return_value=[])
        builder._events_from_adverse_media = AsyncMock(return_value=[])
        builder._events_from_pep = AsyncMock(return_value=[])
        builder._events_from_watchlist = AsyncMock(return_value=[])
        builder._events_from_breaches = AsyncMock(return_value=[])
        builder._events_from_travel = AsyncMock(return_value=[])
        builder._upsert_event = AsyncMock(return_value=True)

        result = await builder.build(uuid.uuid4(), session)
        assert result == 2

    async def test_build_calls_all_extractors(self):
        """Verifies all 11 source extractor methods are awaited."""
        builder = TimelineBuilder()
        session = _make_session()

        for attr in [
            "_events_from_criminal",
            "_events_from_employment",
            "_events_from_education",
            "_events_from_addresses",
            "_events_from_properties",
            "_events_from_social_profiles",
            "_events_from_adverse_media",
            "_events_from_pep",
            "_events_from_watchlist",
            "_events_from_breaches",
            "_events_from_travel",
        ]:
            setattr(builder, attr, AsyncMock(return_value=[]))

        await builder.build(uuid.uuid4(), session)

        for attr in [
            "_events_from_criminal",
            "_events_from_employment",
            "_events_from_education",
            "_events_from_addresses",
            "_events_from_properties",
            "_events_from_social_profiles",
            "_events_from_adverse_media",
            "_events_from_pep",
            "_events_from_watchlist",
            "_events_from_breaches",
            "_events_from_travel",
        ]:
            getattr(builder, attr).assert_awaited_once()

    async def test_build_duplicate_not_counted(self):
        """_upsert_event returning False means already existed → not counted."""
        builder = TimelineBuilder()
        session = _make_session()

        ev = {"event_type": "employment_start", "event_date": date(2020, 1, 1), "title": "Job"}
        for attr in [
            "_events_from_criminal",
            "_events_from_employment",
            "_events_from_education",
            "_events_from_addresses",
            "_events_from_properties",
            "_events_from_social_profiles",
            "_events_from_adverse_media",
            "_events_from_pep",
            "_events_from_watchlist",
            "_events_from_breaches",
            "_events_from_travel",
        ]:
            setattr(
                builder,
                attr,
                AsyncMock(return_value=[ev] if attr == "_events_from_criminal" else []),
            )

        builder._upsert_event = AsyncMock(return_value=False)

        result = await builder.build(uuid.uuid4(), session)
        assert result == 0


# ── _upsert_event() ───────────────────────────────────────────────────────────


class TestUpsertEvent:
    async def test_inserts_new_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        session.execute = AsyncMock(return_value=_scalar_one_or_none(None))

        result = await builder._upsert_event(
            session=session,
            person_id=uuid.uuid4(),
            event_type="employment_start",
            event_date=date(2020, 3, 1),
            title="Started job",
            description="Finance industry",
            confidence=0.75,
            source_type="employment_record",
            source_platform=None,
        )

        assert result is True
        session.add.assert_called_once()

    async def test_existing_lower_confidence_not_updated(self):
        """Existing record with higher confidence → not overwritten."""
        builder = TimelineBuilder()
        session = _make_session()
        existing = MagicMock()
        existing.confidence = 0.9
        existing.meta = {}
        session.execute = AsyncMock(return_value=_scalar_one_or_none(existing))

        result = await builder._upsert_event(
            session=session,
            person_id=uuid.uuid4(),
            event_type="employment_start",
            event_date=date(2020, 3, 1),
            title="Started job",
            description=None,
            confidence=0.5,  # lower
            source_type="employment_record",
            source_platform=None,
        )

        assert result is False
        assert existing.confidence == 0.9  # unchanged
        session.add.assert_not_called()

    async def test_existing_higher_confidence_updates_fields(self):
        """New record has higher confidence → fields updated."""
        builder = TimelineBuilder()
        session = _make_session()
        existing = MagicMock()
        existing.confidence = 0.5
        existing.title = "Old title"
        existing.description = "Old desc"
        existing.source_type = "old_source"
        existing.source_platform = None
        existing.location = None
        existing.meta = {}
        session.execute = AsyncMock(return_value=_scalar_one_or_none(existing))

        result = await builder._upsert_event(
            session=session,
            person_id=uuid.uuid4(),
            event_type="employment_start",
            event_date=date(2020, 3, 1),
            title="New title",
            description="New desc",
            confidence=0.95,
            source_type="court_record",
            source_platform="pacer",
            location="Texas",
            meta={"extra": "data"},
        )

        assert result is False
        assert existing.confidence == 0.95
        assert existing.title == "New title"
        assert existing.description == "New desc"
        assert existing.source_type == "court_record"
        assert existing.location == "Texas"

    async def test_meta_merged_on_high_confidence_update(self):
        """Existing meta is merged with new meta on high-confidence update."""
        builder = TimelineBuilder()
        session = _make_session()
        existing = MagicMock()
        existing.confidence = 0.4
        existing.title = "T"
        existing.description = None
        existing.source_type = None
        existing.source_platform = None
        existing.location = None
        existing.meta = {"old_key": "old_val"}
        session.execute = AsyncMock(return_value=_scalar_one_or_none(existing))

        await builder._upsert_event(
            session=session,
            person_id=uuid.uuid4(),
            event_type="criminal_arrest",
            event_date=date(2021, 1, 1),
            title="Arrest",
            description=None,
            confidence=0.85,
            source_type="court_record",
            source_platform=None,
            meta={"new_key": "new_val"},
        )

        assert existing.meta["old_key"] == "old_val"
        assert existing.meta["new_key"] == "new_val"

    async def test_upsert_with_no_meta_does_not_clear_existing_meta(self):
        """meta=None on high-confidence update → existing meta untouched."""
        builder = TimelineBuilder()
        session = _make_session()
        existing = MagicMock()
        existing.confidence = 0.4
        existing.title = "T"
        existing.description = None
        existing.source_type = None
        existing.source_platform = None
        existing.location = None
        existing.meta = {"preserved": True}
        session.execute = AsyncMock(return_value=_scalar_one_or_none(existing))

        await builder._upsert_event(
            session=session,
            person_id=uuid.uuid4(),
            event_type="criminal_arrest",
            event_date=date(2021, 1, 1),
            title="Arrest",
            description=None,
            confidence=0.85,
            source_type="court_record",
            source_platform=None,
            meta=None,
        )

        # meta should not be overwritten when None
        assert existing.meta == {"preserved": True}


# ── _events_from_criminal() ───────────────────────────────────────────────────


class TestEventsFromCriminal:
    def _make_record(self):
        r = MagicMock()
        r.id = uuid.uuid4()
        r.charge = "Fraud"
        r.offense_description = "Wire fraud"
        r.jurisdiction = "TX"
        r.source_platform = "pacer"
        r.offense_level = "felony"
        r.court_case_number = "21-CR-001"
        r.court_name = "SDTX"
        r.statute = "18 USC 1343"
        r.disposition = "guilty"
        r.sentence = "3 years"
        r.sentence_months = 36
        r.fine_usd = 50000.0
        r.arrest_date = date(2020, 3, 1)
        r.charge_date = date(2020, 4, 1)
        r.disposition_date = date(2021, 1, 15)
        r.warrant_date = date(2020, 2, 28)
        return r

    async def test_produces_arrest_charge_disposition_warrant_events(self):
        builder = TimelineBuilder()
        session = _make_session()
        record = self._make_record()
        session.execute = AsyncMock(return_value=_scalars_result([record]))

        events = await builder._events_from_criminal(session, uuid.uuid4())
        event_types = {e["event_type"] for e in events}
        assert "criminal_arrest" in event_types
        assert "criminal_charge" in event_types
        assert "criminal_conviction" in event_types
        assert "criminal_warrant" in event_types

    async def test_no_dates_produces_no_events(self):
        builder = TimelineBuilder()
        session = _make_session()
        record = MagicMock()
        record.id = uuid.uuid4()
        record.charge = None
        record.arrest_date = None
        record.charge_date = None
        record.disposition_date = None
        record.warrant_date = None
        record.disposition = None
        session.execute = AsyncMock(return_value=_scalars_result([record]))

        events = await builder._events_from_criminal(session, uuid.uuid4())
        assert events == []

    async def test_non_guilty_disposition_maps_to_criminal_charge(self):
        builder = TimelineBuilder()
        session = _make_session()
        record = self._make_record()
        record.arrest_date = None
        record.charge_date = None
        record.warrant_date = None
        record.disposition = "acquitted"
        record.disposition_date = date(2021, 5, 1)
        session.execute = AsyncMock(return_value=_scalars_result([record]))

        events = await builder._events_from_criminal(session, uuid.uuid4())
        assert any(e["event_type"] == "criminal_charge" for e in events)


# ── _events_from_employment() ────────────────────────────────────────────────


class TestEventsFromEmployment:
    async def test_produces_start_and_end_events(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.job_title = "Engineer"
        r.employer_name = "Acme Corp"
        r.industry = "Tech"
        r.location = "Austin, TX"
        r.estimated_salary_usd = 120_000.0
        r.started_at = date(2018, 1, 1)
        r.ended_at = date(2022, 6, 30)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_employment(session, uuid.uuid4())
        types = {e["event_type"] for e in events}
        assert "employment_start" in types
        assert "employment_end" in types

    async def test_no_started_at_produces_no_start_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.job_title = "Analyst"
        r.employer_name = "Corp"
        r.industry = None
        r.location = None
        r.estimated_salary_usd = None
        r.started_at = None
        r.ended_at = date(2020, 1, 1)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_employment(session, uuid.uuid4())
        assert not any(e["event_type"] == "employment_start" for e in events)

    async def test_no_ended_at_produces_no_end_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.job_title = "Analyst"
        r.employer_name = "Corp"
        r.industry = None
        r.location = None
        r.estimated_salary_usd = None
        r.started_at = date(2018, 1, 1)
        r.ended_at = None
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_employment(session, uuid.uuid4())
        assert not any(e["event_type"] == "employment_end" for e in events)


# ── _events_from_education() ─────────────────────────────────────────────────


class TestEventsFromEducation:
    async def test_produces_start_and_graduation(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.degree = "BSc"
        r.institution = "MIT"
        r.field_of_study = "Computer Science"
        r.tier = "university"
        r.started_at = date(2010, 9, 1)
        r.ended_at = date(2014, 6, 1)
        r.is_completed = True
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_education(session, uuid.uuid4())
        types = {e["event_type"] for e in events}
        assert "education_start" in types
        assert "education_graduation" in types

    async def test_not_completed_no_graduation_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.degree = "PhD"
        r.institution = "Stanford"
        r.field_of_study = "Physics"
        r.tier = "university"
        r.started_at = date(2015, 9, 1)
        r.ended_at = date(2021, 6, 1)
        r.is_completed = False
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_education(session, uuid.uuid4())
        assert not any(e["event_type"] == "education_graduation" for e in events)


# ── _events_from_addresses() ─────────────────────────────────────────────────


class TestEventsFromAddresses:
    async def test_produces_address_change_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.street = "123 Main St"
        r.city = "Dallas"
        r.state_province = "TX"
        r.country = "US"
        r.address_type = "residential"
        r.is_current = True
        r.created_at = date(2019, 5, 10)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_addresses(session, uuid.uuid4())
        assert len(events) == 1
        assert events[0]["event_type"] == "address_change"
        assert "Dallas" in events[0]["title"]

    async def test_skips_record_without_created_at(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.street = None
        r.city = None
        r.state_province = None
        r.country = None
        r.address_type = "unknown"
        r.is_current = False
        r.created_at = None
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_addresses(session, uuid.uuid4())
        assert events == []

    async def test_address_with_no_parts_uses_unknown_address(self):
        """All address parts None → 'Unknown address' in title."""
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.street = None
        r.city = None
        r.state_province = None
        r.country = None
        r.address_type = "residential"
        r.is_current = True
        r.created_at = date(2020, 1, 1)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_addresses(session, uuid.uuid4())
        assert "Unknown address" in events[0]["title"]


# ── _events_from_properties() ────────────────────────────────────────────────


class TestEventsFromProperties:
    async def test_produces_property_purchase_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.street_address = "456 Oak Ave"
        r.city = "Houston"
        r.state = "TX"
        r.property_type = "residential"
        r.last_sale_date = date(2018, 7, 4)
        r.last_sale_price_usd = 350_000.0
        r.last_sale_type = "arm_length"
        r.parcel_number = "P999"
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_properties(session, uuid.uuid4())
        assert len(events) == 1
        assert events[0]["event_type"] == "property_purchase"

    async def test_skips_if_no_last_sale_date(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.last_sale_date = None
        r.property_type = "commercial"
        r.last_sale_price_usd = None
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_properties(session, uuid.uuid4())
        assert events == []


# ── _events_from_social_profiles() ───────────────────────────────────────────


class TestEventsFromSocialProfiles:
    async def test_produces_social_profile_created_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.platform = "Twitter"
        r.handle = "johndoe"
        r.display_name = "John Doe"
        r.bio = "Developer"
        r.is_verified = False
        r.follower_count = 500
        r.profile_created_at = date(2010, 3, 21)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_social_profiles(session, uuid.uuid4())
        assert len(events) == 1
        assert events[0]["event_type"] == "social_profile_created"
        assert "@johndoe" in events[0]["title"]

    async def test_skips_if_no_profile_created_at(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.platform = "LinkedIn"
        r.handle = None
        r.display_name = "Jane"
        r.bio = None
        r.is_verified = False
        r.follower_count = 0
        r.profile_created_at = None
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_social_profiles(session, uuid.uuid4())
        assert events == []

    async def test_no_handle_uses_display_name(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.platform = "Instagram"
        r.handle = None
        r.display_name = "Alice Smith"
        r.bio = None
        r.is_verified = True
        r.follower_count = 10_000
        r.profile_created_at = date(2015, 6, 1)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_social_profiles(session, uuid.uuid4())
        assert "Alice Smith" in events[0]["title"]


# ── _events_from_adverse_media() ─────────────────────────────────────────────


class TestEventsFromAdverseMedia:
    async def test_produces_adverse_media_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.headline = "CEO indicted"
        r.summary = "Federal charges filed"
        r.severity = "high"
        r.source_name = "Reuters"
        r.category = "financial_crime"
        r.url_hash = "abc123"
        r.source_country = "US"
        r.is_verified = True
        r.is_retracted = False
        r.publication_date = date(2023, 2, 10)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_adverse_media(session, uuid.uuid4())
        assert len(events) == 1
        assert events[0]["event_type"] == "adverse_media"
        assert events[0]["confidence"] == 0.80  # high severity

    async def test_skips_no_publication_date(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.headline = None
        r.severity = "medium"
        r.source_name = None
        r.category = None
        r.url_hash = None
        r.source_country = None
        r.is_verified = False
        r.is_retracted = False
        r.publication_date = None
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_adverse_media(session, uuid.uuid4())
        assert events == []


# ── _events_from_pep() ────────────────────────────────────────────────────────


class TestEventsFromPep:
    async def test_produces_pep_appointment_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.position_title = "Minister"
        r.organization = "Ministry of Finance"
        r.pep_level = "tier2"
        r.pep_category = "government"
        r.country = "ZA"
        r.jurisdiction = "South Africa"
        r.source_platform = "open_pep_search"
        r.confidence = 0.85
        r.is_current = True
        r.end_date = None
        r.start_date = date(2019, 5, 1)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_pep(session, uuid.uuid4())
        assert len(events) == 1
        assert events[0]["event_type"] == "pep_appointment"
        assert "Ministry of Finance" in events[0]["title"]

    async def test_skips_if_no_start_date(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.position_title = "Official"
        r.organization = None
        r.start_date = None
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_pep(session, uuid.uuid4())
        assert events == []

    async def test_end_date_isoformat_in_meta(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.position_title = "Senator"
        r.organization = "Senate"
        r.pep_level = "tier1"
        r.pep_category = "legislative"
        r.country = "US"
        r.jurisdiction = None
        r.source_platform = None
        r.confidence = 0.9
        r.is_current = False
        r.end_date = date(2022, 11, 8)
        r.start_date = date(2016, 1, 3)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_pep(session, uuid.uuid4())
        assert events[0]["meta"]["end_date"] == "2022-11-08"


# ── _events_from_watchlist() ─────────────────────────────────────────────────


class TestEventsFromWatchlist:
    async def test_produces_watchlist_listed_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.list_name = "OFAC SDN"
        r.reason = "Sanctions violation"
        r.list_type = "sanctions"
        r.match_name = "John Doe"
        r.is_confirmed = True
        r.match_score = 0.95
        r.listed_date = date(2020, 8, 15)
        r.created_at = date(2020, 8, 16)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_watchlist(session, uuid.uuid4())
        assert len(events) == 1
        assert events[0]["event_type"] == "watchlist_listed"
        assert events[0]["event_date"] == date(2020, 8, 15)

    async def test_falls_back_to_created_at_when_listed_date_absent(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.list_name = "EU Sanctions"
        r.reason = None
        r.list_type = "sanctions"
        r.match_name = "Jane Doe"
        r.is_confirmed = False
        r.match_score = 0.7
        r.listed_date = None
        r.created_at = date(2021, 1, 5)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_watchlist(session, uuid.uuid4())
        assert len(events) == 1
        assert events[0]["event_date"] == date(2021, 1, 5)

    async def test_skips_when_no_dates(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.list_name = "PEP List"
        r.reason = None
        r.list_type = "pep"
        r.match_name = "Unknown"
        r.is_confirmed = False
        r.match_score = 0.5
        r.listed_date = None
        r.created_at = None
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_watchlist(session, uuid.uuid4())
        assert events == []


# ── _events_from_breaches() ──────────────────────────────────────────────────


class TestEventsFromBreaches:
    async def test_produces_breach_exposure_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.breach_name = "LinkedIn 2016"
        r.severity = "high"
        r.exposed_fields = ["email", "password_hash", "name"]
        r.source_type = "hibp"
        r.breach_date = date(2016, 5, 17)
        r.created_at = date(2016, 5, 18)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_breaches(session, uuid.uuid4())
        assert len(events) == 1
        assert events[0]["event_type"] == "breach_exposure"

    async def test_falls_back_to_created_at(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.breach_name = "Unknown Breach"
        r.severity = "medium"
        r.exposed_fields = []
        r.source_type = "manual"
        r.breach_date = None
        r.created_at = date(2023, 11, 1)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_breaches(session, uuid.uuid4())
        assert events[0]["event_date"] == date(2023, 11, 1)

    async def test_skips_when_no_dates(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.breach_name = "Ghost Breach"
        r.severity = "low"
        r.exposed_fields = None
        r.source_type = "unknown"
        r.breach_date = None
        r.created_at = None
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_breaches(session, uuid.uuid4())
        assert events == []

    async def test_exposed_fields_truncated_to_five(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.breach_name = "Big Breach"
        r.severity = "critical"
        r.exposed_fields = ["a", "b", "c", "d", "e", "f", "g"]
        r.source_type = "hibp"
        r.breach_date = date(2022, 1, 1)
        r.created_at = date(2022, 1, 2)
        session.execute = AsyncMock(return_value=_scalars_result([r]))

        events = await builder._events_from_breaches(session, uuid.uuid4())
        # Description should contain at most 5 fields
        desc = events[0]["description"]
        # "a, b, c, d, e" — 5 fields joined
        assert "f" not in desc


# ── _events_from_travel() ────────────────────────────────────────────────────


class TestEventsFromTravel:
    async def test_produces_travel_event(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.travel_date = date(2022, 3, 15)
        r.arrival_city = "Paris"
        r.arrival_country = "France"
        r.departure_city = "New York"
        r.departure_country = "US"
        r.travel_mode = "air"
        r.carrier = "Air France"
        r.is_flagged = False
        r.flag_reason = None
        r.source_platform = "border_control"
        r.confidence = 0.90
        r.visa_type = "tourist"

        from unittest.mock import patch as _patch

        with _patch(
            "modules.enrichers.timeline_builder.TravelHistory",
            autospec=False,
        ):
            session.execute = AsyncMock(return_value=_scalars_result([r]))
            events = await builder._events_from_travel(session, uuid.uuid4())

        assert len(events) == 1
        assert events[0]["event_type"] == "travel"
        assert "Paris" in events[0]["title"]

    async def test_skips_when_no_travel_date(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.travel_date = None
        r.arrival_city = "Tokyo"
        r.arrival_country = "Japan"
        r.departure_city = None
        r.departure_country = "US"
        r.travel_mode = "air"
        r.carrier = None
        r.is_flagged = False
        r.flag_reason = None
        r.source_platform = None
        r.confidence = 0.5
        r.visa_type = None

        from unittest.mock import patch as _patch

        with _patch("modules.enrichers.timeline_builder.TravelHistory", autospec=False):
            session.execute = AsyncMock(return_value=_scalars_result([r]))
            events = await builder._events_from_travel(session, uuid.uuid4())

        assert events == []

    async def test_flagged_travel_includes_reason(self):
        builder = TimelineBuilder()
        session = _make_session()
        r = MagicMock()
        r.id = uuid.uuid4()
        r.travel_date = date(2021, 7, 4)
        r.arrival_city = "Dubai"
        r.arrival_country = "UAE"
        r.departure_city = "Moscow"
        r.departure_country = "Russia"
        r.travel_mode = "air"
        r.carrier = "Emirates"
        r.is_flagged = True
        r.flag_reason = "Sanction screening hit"
        r.source_platform = "interpol"
        r.confidence = 0.85
        r.visa_type = "business"

        from unittest.mock import patch as _patch

        with _patch("modules.enrichers.timeline_builder.TravelHistory", autospec=False):
            session.execute = AsyncMock(return_value=_scalars_result([r]))
            events = await builder._events_from_travel(session, uuid.uuid4())

        assert "Sanction screening hit" in events[0]["description"]
