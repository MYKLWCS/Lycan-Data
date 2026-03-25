"""
test_property_enricher.py — Unit tests for modules/enrichers/property_enricher.py.

Covers:
  - start(): one loop iteration then stops via mocked asyncio.sleep side_effect
  - start(): batch exception is swallowed, sleep still called
  - _process_pending(): queries DB, iterates person_ids, calls enrich_person
  - _process_pending(): handles enrich_person failure per-person
  - enrich_person(): person not found → early return
  - enrich_person(): crawlers invoked, results persisted, meta updated
  - enrich_person(): crawler raising exception is swallowed per-crawler
  - enrich_person(): property data with list result vs dict result
  - enrich_person(): FAA crawler failure is swallowed
  - enrich_person(): marine crawler failure is swallowed
  - _upsert_property(): creates new property when no existing found
  - _upsert_property(): updates existing property keyed on parcel_number
  - _upsert_property(): updates existing property keyed on street_address
  - _upsert_ownership_history(): skips existing doc_num, inserts new record
  - _upsert_valuation(): skips when no year; updates existing; inserts new
  - _upsert_mortgage(): updates existing; inserts new (no instrument key)
  - _upsert_aircraft(): creates new; updates existing keyed on n_number
  - _upsert_vessel(): creates new keyed on mmsi; updates existing; keyed on imo
  - _compute_net_worth(): sums all asset categories
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.property_enricher import PropertyEnricher


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_person(name: str = "John Doe", meta: dict | None = None) -> MagicMock:
    p = MagicMock()
    p.id = uuid.uuid4()
    p.full_name = name
    p.meta = meta or {}
    return p


def _scalar_result(value):
    """Return a mock that behaves like session.execute(...).scalar()."""
    r = MagicMock()
    r.scalar.return_value = value
    r.scalar_one_or_none.return_value = None
    return r


def _scalars_result(items: list):
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    r.scalars.return_value.all.return_value = items
    return r


def _fetchall_result(rows: list):
    r = MagicMock()
    r.fetchall.return_value = rows
    return r


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


# ── start() loop ─────────────────────────────────────────────────────────────


class TestPropertyEnricherStart:
    async def test_start_runs_one_iteration_then_stops(self):
        """start() runs _process_pending() once, then sleep raises to break."""
        enricher = PropertyEnricher()
        enricher._process_pending = AsyncMock()

        with patch(
            "modules.enrichers.property_enricher.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=[None, Exception("stop")],
        ):
            with pytest.raises(Exception, match="stop"):
                await enricher.start()

        enricher._process_pending.assert_awaited()

    async def test_start_swallows_batch_exception(self):
        """start() catches _process_pending errors and continues to sleep."""
        enricher = PropertyEnricher()
        enricher._process_pending = AsyncMock(side_effect=RuntimeError("batch fail"))

        sleep_calls = 0

        async def fake_sleep(_):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 1:
                raise Exception("stop")

        with patch("modules.enrichers.property_enricher.asyncio.sleep", side_effect=fake_sleep):
            with pytest.raises(Exception, match="stop"):
                await enricher.start()

        assert sleep_calls >= 1


# ── _process_pending() ────────────────────────────────────────────────────────


class TestProcessPending:
    async def test_process_pending_calls_enrich_for_each_person(self):
        """_process_pending queries the DB and calls enrich_person per person."""
        pid1, pid2 = uuid.uuid4(), uuid.uuid4()
        enricher = PropertyEnricher()
        enricher.enrich_person = AsyncMock()

        # First session returns person IDs, subsequent sessions used per-person
        mock_session = _make_session()
        mock_session.execute = AsyncMock(return_value=_fetchall_result([(pid1,), (pid2,)]))

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.enrichers.property_enricher.AsyncSessionLocal", return_value=cm):
            await enricher._process_pending()

        assert enricher.enrich_person.await_count == 2

    async def test_process_pending_empty_batch(self):
        """_process_pending with no pending persons does nothing."""
        enricher = PropertyEnricher()
        enricher.enrich_person = AsyncMock()

        mock_session = _make_session()
        mock_session.execute = AsyncMock(return_value=_fetchall_result([]))

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.enrichers.property_enricher.AsyncSessionLocal", return_value=cm):
            await enricher._process_pending()

        enricher.enrich_person.assert_not_awaited()

    async def test_process_pending_swallows_per_person_error(self):
        """A failure for one person does not prevent others from being processed."""
        pid1, pid2 = uuid.uuid4(), uuid.uuid4()
        enricher = PropertyEnricher()

        call_order: list[uuid.UUID] = []

        async def _enrich(pid, session):
            call_order.append(pid)
            if pid == pid1:
                raise RuntimeError("person error")

        enricher.enrich_person = _enrich

        mock_session = _make_session()
        mock_session.execute = AsyncMock(return_value=_fetchall_result([(pid1,), (pid2,)]))

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("modules.enrichers.property_enricher.AsyncSessionLocal", return_value=cm):
            await enricher._process_pending()

        assert pid1 in call_order
        assert pid2 in call_order


# ── enrich_person() ──────────────────────────────────────────────────────────


class TestEnrichPerson:
    async def test_enrich_person_not_found(self):
        """enrich_person returns early when person does not exist."""
        enricher = PropertyEnricher()
        session = _make_session()
        session.get = AsyncMock(return_value=None)
        pid = uuid.uuid4()
        await enricher.enrich_person(pid, session)
        session.flush.assert_not_awaited()

    async def test_enrich_person_full_flow(self):
        """enrich_person runs all crawlers, persists results, updates person.meta."""
        enricher = PropertyEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)

        # Aggregate count queries return 1 each
        session.execute = AsyncMock(return_value=_scalar_result(1))

        prop = MagicMock()
        prop.id = uuid.uuid4()
        enricher._upsert_property = AsyncMock(return_value=prop)
        enricher._upsert_ownership_history = AsyncMock()
        enricher._upsert_valuation = AsyncMock()
        enricher._upsert_mortgage = AsyncMock()
        enricher._upsert_aircraft = AsyncMock()
        enricher._upsert_vessel = AsyncMock()
        enricher._compute_net_worth = AsyncMock(return_value=500000.0)

        crawler_result = MagicMock()
        crawler_result.found = True
        crawler_result.data = [
            {
                "parcel_number": "12345",
                "street_address": "123 Main St",
                "city": "Austin",
                "ownership_history": [{"document_number": "DOC1"}],
                "valuations": [{"valuation_year": 2023, "valuation_source": "county"}],
                "mortgages": [{"instrument_number": "MTG1"}],
            }
        ]
        mock_crawler = AsyncMock()
        mock_crawler.scrape = AsyncMock(return_value=crawler_result)

        faa_result = MagicMock()
        faa_result.found = True
        faa_result.data = [{"n_number": "N12345"}]
        faa_crawler = AsyncMock()
        faa_crawler.scrape = AsyncMock(return_value=faa_result)

        vessel_result = MagicMock()
        vessel_result.found = True
        vessel_result.data = {"mmsi": "123456789"}
        vessel_crawler = AsyncMock()
        vessel_crawler.scrape = AsyncMock(return_value=vessel_result)

        with (
            patch("modules.crawlers.zillow_deep.ZillowDeepCrawler", return_value=mock_crawler),
            patch("modules.crawlers.redfin_deep.RedfinDeepCrawler", return_value=mock_crawler),
            patch("modules.crawlers.deed_recorder.DeedRecorderCrawler", return_value=mock_crawler),
            patch(
                "modules.crawlers.county_assessor_multi.CountyAssessorMultiCrawler",
                return_value=mock_crawler,
            ),
            patch(
                "modules.crawlers.faa_aircraft_registry.FaaAircraftRegistryCrawler",
                return_value=faa_crawler,
            ),
            patch(
                "modules.crawlers.marine_vessel.MarineVesselCrawler",
                return_value=vessel_crawler,
            ),
        ):
            await enricher.enrich_person(person.id, session)

        assert "property_count" in person.meta
        assert "estimated_net_worth_usd" in person.meta
        assert person.meta["estimated_net_worth_usd"] == 500000.0

    async def test_enrich_person_crawler_dict_result(self):
        """enrich_person handles crawler returning a single dict (not a list)."""
        enricher = PropertyEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)
        session.execute = AsyncMock(return_value=_scalar_result(0))

        prop = MagicMock()
        prop.id = uuid.uuid4()
        enricher._upsert_property = AsyncMock(return_value=prop)
        enricher._upsert_ownership_history = AsyncMock()
        enricher._upsert_valuation = AsyncMock()
        enricher._upsert_mortgage = AsyncMock()
        enricher._upsert_aircraft = AsyncMock()
        enricher._upsert_vessel = AsyncMock()
        enricher._compute_net_worth = AsyncMock(return_value=0.0)

        crawler_result = MagicMock()
        crawler_result.found = True
        crawler_result.data = {"parcel_number": "9999"}  # single dict, not list

        no_result = MagicMock()
        no_result.found = False

        with (
            patch(
                "modules.crawlers.zillow_deep.ZillowDeepCrawler",
                return_value=MagicMock(scrape=AsyncMock(return_value=crawler_result)),
            ),
            patch(
                "modules.crawlers.redfin_deep.RedfinDeepCrawler",
                return_value=MagicMock(scrape=AsyncMock(return_value=no_result)),
            ),
            patch(
                "modules.crawlers.deed_recorder.DeedRecorderCrawler",
                return_value=MagicMock(scrape=AsyncMock(return_value=no_result)),
            ),
            patch(
                "modules.crawlers.county_assessor_multi.CountyAssessorMultiCrawler",
                return_value=MagicMock(scrape=AsyncMock(return_value=no_result)),
            ),
            patch(
                "modules.crawlers.faa_aircraft_registry.FaaAircraftRegistryCrawler",
                return_value=MagicMock(scrape=AsyncMock(return_value=no_result)),
            ),
            patch(
                "modules.crawlers.marine_vessel.MarineVesselCrawler",
                return_value=MagicMock(scrape=AsyncMock(return_value=no_result)),
            ),
        ):
            await enricher.enrich_person(person.id, session)

        enricher._upsert_property.assert_awaited_once()

    async def test_enrich_person_crawler_exception_swallowed(self):
        """A crawler that raises does not abort the rest of the enrichment."""
        enricher = PropertyEnricher()
        person = _make_person()
        session = _make_session()
        session.get = AsyncMock(return_value=person)
        session.execute = AsyncMock(return_value=_scalar_result(0))

        enricher._upsert_aircraft = AsyncMock()
        enricher._upsert_vessel = AsyncMock()
        enricher._compute_net_worth = AsyncMock(return_value=0.0)

        boom = MagicMock()
        boom.scrape = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch(
                "modules.crawlers.zillow_deep.ZillowDeepCrawler",
                return_value=boom,
            ),
            patch(
                "modules.crawlers.redfin_deep.RedfinDeepCrawler",
                return_value=boom,
            ),
            patch(
                "modules.crawlers.deed_recorder.DeedRecorderCrawler",
                return_value=boom,
            ),
            patch(
                "modules.crawlers.county_assessor_multi.CountyAssessorMultiCrawler",
                return_value=boom,
            ),
            patch(
                "modules.crawlers.faa_aircraft_registry.FaaAircraftRegistryCrawler",
                return_value=boom,
            ),
            patch(
                "modules.crawlers.marine_vessel.MarineVesselCrawler",
                return_value=boom,
            ),
        ):
            # Should complete without raising
            await enricher.enrich_person(person.id, session)

        assert "property_enriched_at" in person.meta

    async def test_enrich_person_uses_person_id_str_when_no_name(self):
        """When full_name is None the person_id string is used as identifier."""
        enricher = PropertyEnricher()
        person = _make_person(name=None)
        person.full_name = None
        session = _make_session()
        session.get = AsyncMock(return_value=person)
        session.execute = AsyncMock(return_value=_scalar_result(0))
        enricher._compute_net_worth = AsyncMock(return_value=0.0)

        no_result = MagicMock()
        no_result.found = False

        crawler = MagicMock(scrape=AsyncMock(return_value=no_result))

        with (
            patch("modules.crawlers.zillow_deep.ZillowDeepCrawler", return_value=crawler),
            patch("modules.crawlers.redfin_deep.RedfinDeepCrawler", return_value=crawler),
            patch("modules.crawlers.deed_recorder.DeedRecorderCrawler", return_value=crawler),
            patch(
                "modules.crawlers.county_assessor_multi.CountyAssessorMultiCrawler",
                return_value=crawler,
            ),
            patch(
                "modules.crawlers.faa_aircraft_registry.FaaAircraftRegistryCrawler",
                return_value=crawler,
            ),
            patch(
                "modules.crawlers.marine_vessel.MarineVesselCrawler",
                return_value=crawler,
            ),
        ):
            await enricher.enrich_person(person.id, session)

        assert "property_enriched_at" in person.meta


# ── _upsert_property() ───────────────────────────────────────────────────────


class TestUpsertProperty:
    async def test_creates_new_property(self):
        """No existing property → new Property row created and flushed."""
        enricher = PropertyEnricher()
        session = _make_session()
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=r)

        prop_data = {
            "parcel_number": "P001",
            "street_address": "1 Oak St",
            "city": "Dallas",
            "state": "TX",
            "country": "US",
        }
        result = await enricher._upsert_property(session, uuid.uuid4(), prop_data)
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    async def test_updates_existing_property_by_parcel(self):
        """Existing property keyed on parcel_number → fields updated, no new row."""
        enricher = PropertyEnricher()
        session = _make_session()

        existing = MagicMock()
        existing.last_scraped_at = None

        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        prop_data = {
            "parcel_number": "P001",
            "city": "Houston",
            "state": "TX",
        }
        result = await enricher._upsert_property(session, uuid.uuid4(), prop_data)

        assert result is existing
        session.add.assert_not_called()

    async def test_updates_existing_property_by_street_address(self):
        """No parcel — falls back to street_address key."""
        enricher = PropertyEnricher()
        session = _make_session()

        existing = MagicMock()
        existing.last_scraped_at = None

        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        prop_data = {"street_address": "2 Elm St", "city": "Phoenix"}
        result = await enricher._upsert_property(session, uuid.uuid4(), prop_data)
        assert result is existing

    async def test_creates_property_without_parcel_or_address(self):
        """Neither parcel nor address → still creates a new row."""
        enricher = PropertyEnricher()
        session = _make_session()
        # execute should not be called at all for lookup when both keys absent
        prop_data = {"city": "Miami", "state": "FL"}
        result = await enricher._upsert_property(session, uuid.uuid4(), prop_data)
        session.add.assert_called_once()


# ── _upsert_ownership_history() ──────────────────────────────────────────────


class TestUpsertOwnershipHistory:
    async def test_skips_existing_document(self):
        """Existing document_number → record is immutable, nothing inserted."""
        enricher = PropertyEnricher()
        session = _make_session()
        existing = MagicMock()
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        history = [{"document_number": "DOC-001", "owner_name": "Alice"}]
        await enricher._upsert_ownership_history(session, uuid.uuid4(), history)
        session.add.assert_not_called()

    async def test_inserts_new_record(self):
        """New document_number → inserts PropertyOwnershipHistory row."""
        enricher = PropertyEnricher()
        session = _make_session()
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=r)

        history = [{"document_number": "DOC-002", "owner_name": "Bob"}]
        await enricher._upsert_ownership_history(session, uuid.uuid4(), history)
        session.add.assert_called_once()

    async def test_inserts_record_without_document_number(self):
        """No document_number → always inserts (no dedup lookup)."""
        enricher = PropertyEnricher()
        session = _make_session()

        history = [{"owner_name": "Charlie"}]
        await enricher._upsert_ownership_history(session, uuid.uuid4(), history)
        session.add.assert_called_once()


# ── _upsert_valuation() ───────────────────────────────────────────────────────


class TestUpsertValuation:
    async def test_skips_when_no_year(self):
        """valuation_year absent → returns without touching DB."""
        enricher = PropertyEnricher()
        session = _make_session()
        await enricher._upsert_valuation(session, uuid.uuid4(), {"valuation_source": "county"})
        session.execute.assert_not_awaited()

    async def test_updates_existing_valuation(self):
        """Existing row found → updates numeric fields only."""
        enricher = PropertyEnricher()
        session = _make_session()
        existing = MagicMock()
        existing.assessed_value_usd = 100_000.0
        existing.market_value_usd = 150_000.0
        existing.tax_amount_usd = 3_000.0
        existing.tax_rate = 0.02
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        val_data = {
            "valuation_year": 2023,
            "valuation_source": "county",
            "market_value_usd": 200_000.0,
        }
        await enricher._upsert_valuation(session, uuid.uuid4(), val_data)
        assert existing.market_value_usd == 200_000.0
        session.add.assert_not_called()

    async def test_inserts_new_valuation(self):
        """No existing row → inserts PropertyValuation."""
        enricher = PropertyEnricher()
        session = _make_session()
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=r)

        val_data = {"valuation_year": 2022, "valuation_source": "zillow", "market_value_usd": 300_000.0}
        await enricher._upsert_valuation(session, uuid.uuid4(), val_data)
        session.add.assert_called_once()


# ── _upsert_mortgage() ────────────────────────────────────────────────────────


class TestUpsertMortgage:
    async def test_updates_existing_mortgage(self):
        """Existing instrument_number → updates is_active and is_delinquent."""
        enricher = PropertyEnricher()
        session = _make_session()
        existing = MagicMock()
        existing.is_active = True
        existing.is_delinquent = False
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        mtg_data = {"instrument_number": "MTG-001", "is_active": False, "is_delinquent": True}
        await enricher._upsert_mortgage(session, uuid.uuid4(), uuid.uuid4(), mtg_data)
        assert existing.is_active is False
        assert existing.is_delinquent is True
        session.add.assert_not_called()

    async def test_inserts_new_mortgage(self):
        """No existing instrument → inserts new PropertyMortgage row."""
        enricher = PropertyEnricher()
        session = _make_session()
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=r)

        mtg_data = {
            "instrument_number": "MTG-002",
            "lender_name": "Big Bank",
            "original_loan_amount_usd": 250_000.0,
        }
        await enricher._upsert_mortgage(session, uuid.uuid4(), uuid.uuid4(), mtg_data)
        session.add.assert_called_once()

    async def test_inserts_mortgage_without_instrument_number(self):
        """No instrument_number → inserts without dedup lookup."""
        enricher = PropertyEnricher()
        session = _make_session()
        mtg_data = {"lender_name": "Small Credit Union"}
        await enricher._upsert_mortgage(session, uuid.uuid4(), uuid.uuid4(), mtg_data)
        session.add.assert_called_once()
        session.execute.assert_not_awaited()


# ── _upsert_aircraft() ────────────────────────────────────────────────────────


class TestUpsertAircraft:
    async def test_creates_new_aircraft(self):
        """No existing n_number → inserts Aircraft."""
        enricher = PropertyEnricher()
        session = _make_session()
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=r)

        a_data = {"n_number": "N12345", "manufacturer": "Cessna", "model": "172"}
        result = await enricher._upsert_aircraft(session, uuid.uuid4(), a_data)
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    async def test_updates_existing_aircraft(self):
        """Existing n_number → fields updated, no new row."""
        enricher = PropertyEnricher()
        session = _make_session()
        existing = MagicMock()
        existing.last_scraped_at = None
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        a_data = {"n_number": "N12345", "manufacturer": "Piper", "estimated_value_usd": 90_000.0}
        result = await enricher._upsert_aircraft(session, uuid.uuid4(), a_data)
        assert result is existing
        session.add.assert_not_called()

    async def test_creates_aircraft_without_n_number(self):
        """No n_number → no lookup, inserts directly."""
        enricher = PropertyEnricher()
        session = _make_session()
        a_data = {"manufacturer": "Beechcraft"}
        result = await enricher._upsert_aircraft(session, uuid.uuid4(), a_data)
        session.add.assert_called_once()


# ── _upsert_vessel() ─────────────────────────────────────────────────────────


class TestUpsertVessel:
    async def test_creates_new_vessel_by_mmsi(self):
        """No existing vessel by mmsi → inserts Vessel."""
        enricher = PropertyEnricher()
        session = _make_session()
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=r)

        v_data = {"mmsi": "123456789", "vessel_name": "Sea Breeze", "vessel_type": "yacht"}
        result = await enricher._upsert_vessel(session, uuid.uuid4(), v_data)
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    async def test_updates_existing_vessel_by_mmsi(self):
        """Existing mmsi → fields updated, no new row."""
        enricher = PropertyEnricher()
        session = _make_session()
        existing = MagicMock()
        existing.last_scraped_at = None
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        v_data = {"mmsi": "123456789", "vessel_name": "Northern Star", "estimated_value_usd": 2_000_000.0}
        result = await enricher._upsert_vessel(session, uuid.uuid4(), v_data)
        assert result is existing
        session.add.assert_not_called()

    async def test_creates_vessel_by_imo_when_no_mmsi(self):
        """No mmsi, but imo_number present → lookup by imo."""
        enricher = PropertyEnricher()
        session = _make_session()
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=r)

        v_data = {"imo_number": "IMO9999999", "vessel_name": "Deep Blue"}
        result = await enricher._upsert_vessel(session, uuid.uuid4(), v_data)
        session.add.assert_called_once()

    async def test_updates_existing_vessel_by_imo(self):
        """imo_number found in DB → updates."""
        enricher = PropertyEnricher()
        session = _make_session()
        existing = MagicMock()
        existing.last_scraped_at = None
        r = MagicMock()
        r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        v_data = {"imo_number": "IMO9999999", "gross_tonnage": 500}
        result = await enricher._upsert_vessel(session, uuid.uuid4(), v_data)
        assert result is existing

    async def test_creates_vessel_without_identifiers(self):
        """No mmsi or imo → no lookup, inserts directly."""
        enricher = PropertyEnricher()
        session = _make_session()
        v_data = {"vessel_name": "Ghost Ship"}
        result = await enricher._upsert_vessel(session, uuid.uuid4(), v_data)
        session.add.assert_called_once()


# ── _compute_net_worth() ─────────────────────────────────────────────────────


class TestComputeNetWorth:
    async def test_compute_net_worth_sums_all_categories(self):
        """Returns sum of property + vehicle + aircraft + vessel values."""
        enricher = PropertyEnricher()
        session = _make_session()
        # Four execute calls: property, vehicle, aircraft, vessel
        session.execute = AsyncMock(
            side_effect=[
                _scalar_result(500_000.0),
                _scalar_result(30_000.0),
                _scalar_result(90_000.0),
                _scalar_result(2_000_000.0),
            ]
        )
        result = await enricher._compute_net_worth(session, uuid.uuid4())
        assert result == pytest.approx(2_620_000.0)

    async def test_compute_net_worth_handles_none_scalars(self):
        """None from scalar() is treated as 0.0."""
        enricher = PropertyEnricher()
        session = _make_session()
        session.execute = AsyncMock(
            side_effect=[
                _scalar_result(None),
                _scalar_result(None),
                _scalar_result(None),
                _scalar_result(None),
            ]
        )
        result = await enricher._compute_net_worth(session, uuid.uuid4())
        assert result == pytest.approx(0.0)
