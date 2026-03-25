"""
property_enricher.py — Async daemon that enriches persons with property,
vehicle, aircraft, and vessel data.

Polls every 30 minutes. Finds persons with property_count=0 (stored in
Person.meta) or stale property data (last_scraped_at older than the
freshness threshold). Runs multiple property/asset crawlers in parallel,
persists results across several tables, and updates aggregate counts and
estimated net worth on the Person record.

Crawlers used:
    zillow_deep, redfin_deep, deed_recorder, county_assessor_multi,
    faa_aircraft_registry, marine_vessel
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import AsyncSessionLocal
from shared.models.person import Person
from shared.models.property import (
    Property,
    PropertyMortgage,
    PropertyOwnershipHistory,
    PropertyValuation,
)
from shared.models.vehicle import Aircraft, Vehicle, Vessel

logger = logging.getLogger(__name__)

_SLEEP_INTERVAL = 1800  # 30 minutes
_BATCH_SIZE = 20
_STALE_THRESHOLD_HOURS = 48  # re-enrich after 48 hours


class PropertyEnricher:
    """Continuously enriches persons with real-property and asset data."""

    async def start(self) -> None:
        """Entry point — runs forever, sleeping between batches."""
        logger.info("PropertyEnricher started (interval=%ds)", _SLEEP_INTERVAL)
        while True:
            try:
                await self._process_pending()
            except Exception as exc:
                logger.exception("PropertyEnricher batch error: %s", exc)
            await asyncio.sleep(_SLEEP_INTERVAL)

    # ── Batch selection ───────────────────────────────────────────────────────

    async def _process_pending(self) -> None:
        stale_cutoff = datetime.now(UTC) - timedelta(hours=_STALE_THRESHOLD_HOURS)

        async with AsyncSessionLocal() as session:
            # Persons whose property_count is 0 (key absent or explicitly 0)
            # OR whose last_scraped_at for properties is stale.
            # We use Person.meta JSONB to track the property enrichment timestamp
            # via meta["property_enriched_at"].
            result = await session.execute(
                select(Person.id)
                .where(
                    # property_count key missing → needs enrichment
                    (Person.meta["property_count"].astext.cast(Integer) == 0)
                    | (Person.meta["property_enriched_at"].astext.cast(DateTime) < stale_cutoff)
                    | (~Person.meta.has_key("property_enriched_at"))
                )
                .limit(_BATCH_SIZE)
            )
            person_ids = [row[0] for row in result.fetchall()]

        logger.info("PropertyEnricher: %d persons to process", len(person_ids))
        for pid in person_ids:
            try:
                async with AsyncSessionLocal() as session:
                    await self.enrich_person(pid, session)
                    await session.commit()
            except Exception as exc:
                logger.exception("PropertyEnricher: failed person_id=%s — %s", pid, exc)

    # ── Main per-person enrichment ────────────────────────────────────────────

    async def enrich_person(self, person_id: uuid.UUID, session: AsyncSession) -> None:
        """Run all property/asset crawlers for one person and persist results."""
        from modules.crawlers.county_assessor_multi import CountyAssessorMultiCrawler
        from modules.crawlers.deed_recorder import DeedRecorderCrawler
        from modules.crawlers.faa_aircraft_registry import FaaAircraftRegistryCrawler
        from modules.crawlers.marine_vessel import MarineVesselCrawler
        from modules.crawlers.redfin_deep import RedfinDeepCrawler
        from modules.crawlers.zillow_deep import ZillowDeepCrawler

        person = await session.get(Person, person_id)
        if not person:
            logger.warning("PropertyEnricher: person_id=%s not found", person_id)
            return

        identifier = person.full_name or str(person_id)

        property_crawlers = [
            ZillowDeepCrawler(),
            RedfinDeepCrawler(),
            DeedRecorderCrawler(),
            CountyAssessorMultiCrawler(),
        ]
        [
            FaaAircraftRegistryCrawler(),
            MarineVesselCrawler(),
        ]

        # ── Property crawlers ─────────────────────────────────────────────────
        property_results: list[dict] = []
        for crawler in property_crawlers:
            try:
                r = await crawler.scrape(identifier)
                if r and r.found and isinstance(r.data, list):
                    property_results.extend(r.data)
                elif r and r.found and isinstance(r.data, dict):
                    property_results.append(r.data)
            except Exception as exc:
                logger.debug(
                    "PropertyEnricher: crawler %s failed for %s — %s",
                    type(crawler).__name__, identifier, exc,
                )

        for prop_data in property_results:
            prop = await self._upsert_property(session, person_id, prop_data)
            ownership = prop_data.get("ownership_history", [])
            if ownership:
                await self._upsert_ownership_history(session, prop.id, ownership)
            valuations = prop_data.get("valuations", [])
            for val in valuations:
                await self._upsert_valuation(session, prop.id, val)
            mortgages = prop_data.get("mortgages", [])
            for mtg in mortgages:
                await self._upsert_mortgage(session, prop.id, person_id, mtg)

        # ── Aircraft crawler ──────────────────────────────────────────────────
        try:
            r = await FaaAircraftRegistryCrawler().scrape(identifier)
            if r and r.found:
                aircraft_list = r.data if isinstance(r.data, list) else [r.data]
                for a_data in aircraft_list:
                    await self._upsert_aircraft(session, person_id, a_data)
        except Exception as exc:
            logger.debug("PropertyEnricher: FAA crawler failed — %s", exc)

        # ── Vessel crawler ────────────────────────────────────────────────────
        try:
            r = await MarineVesselCrawler().scrape(identifier)
            if r and r.found:
                vessel_list = r.data if isinstance(r.data, list) else [r.data]
                for v_data in vessel_list:
                    await self._upsert_vessel(session, person_id, v_data)
        except Exception as exc:
            logger.debug("PropertyEnricher: marine crawler failed — %s", exc)

        # ── Flush so counts are accurate ──────────────────────────────────────
        await session.flush()

        # ── Aggregate counts ──────────────────────────────────────────────────
        prop_count = (
            await session.execute(
                select(func.count(Property.id)).where(Property.person_id == person_id)
            )
        ).scalar() or 0

        aircraft_count = (
            await session.execute(
                select(func.count(Aircraft.id)).where(Aircraft.person_id == person_id)
            )
        ).scalar() or 0

        vessel_count = (
            await session.execute(
                select(func.count(Vessel.id)).where(Vessel.person_id == person_id)
            )
        ).scalar() or 0

        vehicle_count = (
            await session.execute(
                select(func.count(Vehicle.id)).where(Vehicle.person_id == person_id)
            )
        ).scalar() or 0

        net_worth = await self._compute_net_worth(session, person_id)

        # Persist counts and net worth into Person.meta
        meta = dict(person.meta or {})
        meta["property_count"] = int(prop_count)
        meta["aircraft_count"] = int(aircraft_count)
        meta["vessel_count"] = int(vessel_count)
        meta["vehicle_count"] = int(vehicle_count)
        meta["estimated_net_worth_usd"] = net_worth
        meta["property_enriched_at"] = datetime.now(UTC).isoformat()
        person.meta = meta

        logger.info(
            "PropertyEnricher: person_id=%s — props=%d aircraft=%d vessels=%d "
            "vehicles=%d net_worth=%.2f",
            person_id, prop_count, aircraft_count, vessel_count, vehicle_count, net_worth,
        )

    # ── Upsert helpers ────────────────────────────────────────────────────────

    async def _upsert_property(
        self, session: AsyncSession, person_id: uuid.UUID, prop_data: dict
    ) -> Property:
        """Upsert a property record keyed on parcel_number (if present) or address."""
        parcel = prop_data.get("parcel_number")
        street = prop_data.get("street_address")

        existing: Property | None = None
        if parcel:
            result = await session.execute(
                select(Property).where(
                    Property.person_id == person_id,
                    Property.parcel_number == parcel,
                ).limit(1)
            )
            existing = result.scalar_one_or_none()
        elif street:
            result = await session.execute(
                select(Property).where(
                    Property.person_id == person_id,
                    Property.street_address == street,
                ).limit(1)
            )
            existing = result.scalar_one_or_none()

        if existing:
            # Update mutable fields
            for field in (
                "city", "state", "zip_code", "county", "country",
                "property_type", "sub_type", "year_built", "sq_ft_living",
                "sq_ft_lot", "bedrooms", "bathrooms_full", "bathrooms_half",
                "stories", "garage_spaces", "has_pool", "zoning",
                "current_assessed_value_usd", "current_market_value_usd",
                "current_tax_annual_usd", "last_sale_date", "last_sale_price_usd",
                "last_sale_type", "owner_name", "is_owner_occupied",
                "homestead_exemption", "is_investment_property",
                "latitude", "longitude",
            ):
                val = prop_data.get(field)
                if val is not None:
                    setattr(existing, field, val)
            existing.last_scraped_at = datetime.now(UTC)
            return existing

        prop = Property(
            person_id=person_id,
            parcel_number=parcel,
            street_address=street,
            city=prop_data.get("city"),
            state=prop_data.get("state"),
            zip_code=prop_data.get("zip_code"),
            county=prop_data.get("county"),
            country=prop_data.get("country", "US"),
            property_type=prop_data.get("property_type"),
            sub_type=prop_data.get("sub_type"),
            year_built=prop_data.get("year_built"),
            sq_ft_living=prop_data.get("sq_ft_living"),
            sq_ft_lot=prop_data.get("sq_ft_lot"),
            bedrooms=prop_data.get("bedrooms"),
            bathrooms_full=prop_data.get("bathrooms_full"),
            bathrooms_half=prop_data.get("bathrooms_half"),
            stories=prop_data.get("stories"),
            garage_spaces=prop_data.get("garage_spaces"),
            has_pool=bool(prop_data.get("has_pool", False)),
            zoning=prop_data.get("zoning"),
            land_use_code=prop_data.get("land_use_code"),
            school_district=prop_data.get("school_district"),
            flood_zone=prop_data.get("flood_zone"),
            latitude=prop_data.get("latitude"),
            longitude=prop_data.get("longitude"),
            current_assessed_value_usd=prop_data.get("current_assessed_value_usd"),
            current_market_value_usd=prop_data.get("current_market_value_usd"),
            current_tax_annual_usd=prop_data.get("current_tax_annual_usd"),
            last_sale_date=prop_data.get("last_sale_date"),
            last_sale_price_usd=prop_data.get("last_sale_price_usd"),
            last_sale_type=prop_data.get("last_sale_type"),
            owner_name=prop_data.get("owner_name"),
            owner_mailing_address=prop_data.get("owner_mailing_address"),
            is_owner_occupied=prop_data.get("is_owner_occupied"),
            homestead_exemption=bool(prop_data.get("homestead_exemption", False)),
            is_investment_property=bool(prop_data.get("is_investment_property", False)),
            last_scraped_at=datetime.now(UTC),
            meta=prop_data.get("meta", {}),
        )
        session.add(prop)
        await session.flush()
        return prop

    async def _upsert_ownership_history(
        self, session: AsyncSession, property_id: uuid.UUID, history: list[dict]
    ) -> None:
        """Insert ownership history records — keyed on document_number if available."""
        for record in history:
            doc_num = record.get("document_number")
            existing = None
            if doc_num:
                result = await session.execute(
                    select(PropertyOwnershipHistory).where(
                        PropertyOwnershipHistory.property_id == property_id,
                        PropertyOwnershipHistory.document_number == doc_num,
                    ).limit(1)
                )
                existing = result.scalar_one_or_none()
            if existing:
                continue  # deed record is immutable once recorded
            row = PropertyOwnershipHistory(
                property_id=property_id,
                owner_name=record.get("owner_name"),
                owner_type=record.get("owner_type"),
                acquisition_date=record.get("acquisition_date"),
                acquisition_price_usd=record.get("acquisition_price_usd"),
                acquisition_type=record.get("acquisition_type"),
                disposition_date=record.get("disposition_date"),
                disposition_price_usd=record.get("disposition_price_usd"),
                disposition_type=record.get("disposition_type"),
                document_number=doc_num,
                grantor=record.get("grantor"),
                grantee=record.get("grantee"),
                title_company=record.get("title_company"),
                loan_amount_usd=record.get("loan_amount_usd"),
                down_payment_usd=record.get("down_payment_usd"),
                days_held=record.get("days_held"),
                source_platform=record.get("source_platform"),
                meta=record.get("meta", {}),
            )
            session.add(row)

    async def _upsert_valuation(
        self, session: AsyncSession, property_id: uuid.UUID, val_data: dict
    ) -> None:
        """Upsert a PropertyValuation row keyed on (property_id, valuation_year, source)."""
        year = val_data.get("valuation_year")
        source = val_data.get("valuation_source")
        if not year:
            return
        result = await session.execute(
            select(PropertyValuation).where(
                PropertyValuation.property_id == property_id,
                PropertyValuation.valuation_year == year,
                PropertyValuation.valuation_source == source,
            ).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.assessed_value_usd = val_data.get("assessed_value_usd", existing.assessed_value_usd)
            existing.market_value_usd = val_data.get("market_value_usd", existing.market_value_usd)
            existing.tax_amount_usd = val_data.get("tax_amount_usd", existing.tax_amount_usd)
            existing.tax_rate = val_data.get("tax_rate", existing.tax_rate)
            return
        row = PropertyValuation(
            property_id=property_id,
            valuation_year=int(year),
            assessed_value_usd=val_data.get("assessed_value_usd"),
            assessed_land_value_usd=val_data.get("assessed_land_value_usd"),
            assessed_improvement_value_usd=val_data.get("assessed_improvement_value_usd"),
            market_value_usd=val_data.get("market_value_usd"),
            tax_amount_usd=val_data.get("tax_amount_usd"),
            tax_rate=val_data.get("tax_rate"),
            exemptions=val_data.get("exemptions", {}),
            valuation_source=source,
            meta=val_data.get("meta", {}),
        )
        session.add(row)

    async def _upsert_mortgage(
        self,
        session: AsyncSession,
        property_id: uuid.UUID,
        person_id: uuid.UUID,
        mtg_data: dict,
    ) -> None:
        """Upsert a PropertyMortgage keyed on instrument_number."""
        instrument = mtg_data.get("instrument_number")
        existing = None
        if instrument:
            result = await session.execute(
                select(PropertyMortgage).where(
                    PropertyMortgage.property_id == property_id,
                    PropertyMortgage.instrument_number == instrument,
                ).limit(1)
            )
            existing = result.scalar_one_or_none()
        if existing:
            existing.is_active = mtg_data.get("is_active", existing.is_active)
            existing.is_delinquent = mtg_data.get("is_delinquent", existing.is_delinquent)
            return
        row = PropertyMortgage(
            property_id=property_id,
            person_id=person_id,
            lender_name=mtg_data.get("lender_name"),
            loan_type=mtg_data.get("loan_type"),
            original_loan_amount_usd=mtg_data.get("original_loan_amount_usd"),
            interest_rate=mtg_data.get("interest_rate"),
            loan_term_months=mtg_data.get("loan_term_months"),
            origination_date=mtg_data.get("origination_date"),
            maturity_date=mtg_data.get("maturity_date"),
            recording_date=mtg_data.get("recording_date"),
            instrument_number=instrument,
            is_active=bool(mtg_data.get("is_active", True)),
            is_delinquent=bool(mtg_data.get("is_delinquent", False)),
            foreclosure_filing_date=mtg_data.get("foreclosure_filing_date"),
            foreclosure_sale_date=mtg_data.get("foreclosure_sale_date"),
            payoff_date=mtg_data.get("payoff_date"),
            payoff_amount_usd=mtg_data.get("payoff_amount_usd"),
            source_platform=mtg_data.get("source_platform"),
            meta=mtg_data.get("meta", {}),
        )
        session.add(row)

    async def _upsert_aircraft(
        self, session: AsyncSession, person_id: uuid.UUID, aircraft_data: dict
    ) -> Aircraft:
        """Upsert an aircraft record keyed on n_number."""
        n_number = aircraft_data.get("n_number")
        existing = None
        if n_number:
            result = await session.execute(
                select(Aircraft).where(
                    Aircraft.person_id == person_id,
                    Aircraft.n_number == n_number,
                ).limit(1)
            )
            existing = result.scalar_one_or_none()

        if existing:
            for field in (
                "manufacturer", "model", "aircraft_type", "engine_type",
                "num_engines", "num_seats", "year_manufactured",
                "airworthiness_class", "registration_date", "expiration_date",
                "last_action_date", "owner_name", "registrant_type",
                "registrant_address", "is_deregistered", "estimated_value_usd",
            ):
                val = aircraft_data.get(field)
                if val is not None:
                    setattr(existing, field, val)
            existing.last_scraped_at = datetime.now(UTC)
            return existing

        aircraft = Aircraft(
            person_id=person_id,
            n_number=n_number,
            serial_number=aircraft_data.get("serial_number"),
            manufacturer=aircraft_data.get("manufacturer"),
            model=aircraft_data.get("model"),
            aircraft_type=aircraft_data.get("aircraft_type"),
            engine_type=aircraft_data.get("engine_type"),
            num_engines=aircraft_data.get("num_engines"),
            num_seats=aircraft_data.get("num_seats"),
            year_manufactured=aircraft_data.get("year_manufactured"),
            airworthiness_class=aircraft_data.get("airworthiness_class"),
            registration_date=aircraft_data.get("registration_date"),
            expiration_date=aircraft_data.get("expiration_date"),
            last_action_date=aircraft_data.get("last_action_date"),
            owner_name=aircraft_data.get("owner_name"),
            registrant_type=aircraft_data.get("registrant_type"),
            registrant_address=aircraft_data.get("registrant_address"),
            is_deregistered=bool(aircraft_data.get("is_deregistered", False)),
            estimated_value_usd=aircraft_data.get("estimated_value_usd"),
            source_platform=aircraft_data.get("source_platform", "faa_aircraft_registry"),
            last_scraped_at=datetime.now(UTC),
            meta=aircraft_data.get("meta", {}),
        )
        session.add(aircraft)
        await session.flush()
        return aircraft

    async def _upsert_vessel(
        self, session: AsyncSession, person_id: uuid.UUID, vessel_data: dict
    ) -> Vessel:
        """Upsert a vessel record keyed on mmsi or imo_number."""
        mmsi = vessel_data.get("mmsi")
        imo = vessel_data.get("imo_number")
        existing = None

        if mmsi:
            result = await session.execute(
                select(Vessel).where(
                    Vessel.person_id == person_id,
                    Vessel.mmsi == mmsi,
                ).limit(1)
            )
            existing = result.scalar_one_or_none()
        elif imo:
            result = await session.execute(
                select(Vessel).where(
                    Vessel.person_id == person_id,
                    Vessel.imo_number == imo,
                ).limit(1)
            )
            existing = result.scalar_one_or_none()

        if existing:
            for field in (
                "vessel_name", "call_sign", "flag_country", "vessel_type",
                "gross_tonnage", "length_meters", "beam_meters", "draft_meters",
                "year_built", "builder", "owner_name", "operator_name",
                "port_of_registry", "last_port", "destination_port",
                "last_seen_lat", "last_seen_lon", "last_seen_at",
                "is_active", "estimated_value_usd",
            ):
                val = vessel_data.get(field)
                if val is not None:
                    setattr(existing, field, val)
            existing.last_scraped_at = datetime.now(UTC)
            return existing

        vessel = Vessel(
            person_id=person_id,
            mmsi=mmsi,
            imo_number=imo,
            vessel_name=vessel_data.get("vessel_name"),
            call_sign=vessel_data.get("call_sign"),
            flag_country=vessel_data.get("flag_country"),
            vessel_type=vessel_data.get("vessel_type"),
            gross_tonnage=vessel_data.get("gross_tonnage"),
            length_meters=vessel_data.get("length_meters"),
            beam_meters=vessel_data.get("beam_meters"),
            draft_meters=vessel_data.get("draft_meters"),
            year_built=vessel_data.get("year_built"),
            builder=vessel_data.get("builder"),
            owner_name=vessel_data.get("owner_name"),
            operator_name=vessel_data.get("operator_name"),
            port_of_registry=vessel_data.get("port_of_registry"),
            last_port=vessel_data.get("last_port"),
            destination_port=vessel_data.get("destination_port"),
            last_seen_lat=vessel_data.get("last_seen_lat"),
            last_seen_lon=vessel_data.get("last_seen_lon"),
            last_seen_at=vessel_data.get("last_seen_at"),
            is_active=bool(vessel_data.get("is_active", True)),
            estimated_value_usd=vessel_data.get("estimated_value_usd"),
            source_platform=vessel_data.get("source_platform", "marine_vessel"),
            last_scraped_at=datetime.now(UTC),
            meta=vessel_data.get("meta", {}),
        )
        session.add(vessel)
        await session.flush()
        return vessel

    # ── Net worth computation ─────────────────────────────────────────────────

    async def _compute_net_worth(
        self, session: AsyncSession, person_id: uuid.UUID
    ) -> float:
        """Sum of current market values across properties, vehicles, aircraft, vessels."""
        prop_value = (
            await session.execute(
                select(func.coalesce(func.sum(Property.current_market_value_usd), 0.0)).where(
                    Property.person_id == person_id,
                    Property.current_market_value_usd.isnot(None),
                )
            )
        ).scalar() or 0.0

        vehicle_value = (
            await session.execute(
                select(func.coalesce(func.sum(Vehicle.estimated_value_usd), 0.0)).where(
                    Vehicle.person_id == person_id,
                    Vehicle.estimated_value_usd.isnot(None),
                    Vehicle.disposition_date.is_(None),  # currently owned
                )
            )
        ).scalar() or 0.0

        aircraft_value = (
            await session.execute(
                select(func.coalesce(func.sum(Aircraft.estimated_value_usd), 0.0)).where(
                    Aircraft.person_id == person_id,
                    Aircraft.estimated_value_usd.isnot(None),
                    Aircraft.is_deregistered.is_(False),
                )
            )
        ).scalar() or 0.0

        vessel_value = (
            await session.execute(
                select(func.coalesce(func.sum(Vessel.estimated_value_usd), 0.0)).where(
                    Vessel.person_id == person_id,
                    Vessel.estimated_value_usd.isnot(None),
                    Vessel.is_active.is_(True),
                )
            )
        ).scalar() or 0.0

        return float(prop_value) + float(vehicle_value) + float(aircraft_value) + float(vessel_value)
