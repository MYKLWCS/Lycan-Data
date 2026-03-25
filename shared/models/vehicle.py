"""Vehicles — ground (Vehicle), air (Aircraft), maritime (Vessel)."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, DataQualityMixin, TimestampMixin


class Vehicle(Base, TimestampMixin, DataQualityMixin):
    """Ground vehicle linked to a person via registration or title records."""

    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # VIN — not enforced unique; same VIN can link to multiple persons over time
    vin: Mapped[str | None] = mapped_column(String(17), nullable=True, index=True)

    # Manufacturer data
    make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trim: Mapped[str | None] = mapped_column(String(100), nullable=True)
    body_style: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # sedan|suv|truck|van|coupe|convertible|wagon|motorcycle

    # Appearance
    color_exterior: Mapped[str | None] = mapped_column(String(50), nullable=True)
    color_interior: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Mechanical
    engine: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transmission: Mapped[str | None] = mapped_column(String(50), nullable=True)
    drivetrain: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # gasoline|diesel|electric|hybrid|plug_in_hybrid
    mileage: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Registration / title
    license_plate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plate_state: Mapped[str | None] = mapped_column(String(10), nullable=True)
    registration_state: Mapped[str | None] = mapped_column(String(10), nullable=True)
    registration_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    title_state: Mapped[str | None] = mapped_column(String(10), nullable=True)
    title_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # clean|salvage|rebuilt|lemon|junk

    # Lien / financing
    lienholder_name: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Flags
    is_commercial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_stolen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # NHTSA recall data (list of recall campaign dicts)
    nhtsa_recalls: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # Value / acquisition
    estimated_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    acquisition_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    disposition_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    acquisition_price_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="vehicles")


class Aircraft(Base, TimestampMixin, DataQualityMixin):
    """FAA-registered aircraft linked to a person."""

    __tablename__ = "aircraft"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # FAA registration
    n_number: Mapped[str | None] = mapped_column(String(10), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Aircraft specs
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aircraft_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # fixed_wing|rotorcraft|glider|balloon|blimp|gyroplane
    engine_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # piston|turboprop|turbojet|turbofan|electric|none
    num_engines: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_manufactured: Mapped[int | None] = mapped_column(Integer, nullable=True)
    airworthiness_class: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Registration dates
    registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_action_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Registrant
    owner_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    registrant_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # individual|partnership|corporation|co_owned|government
    registrant_address: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    is_deregistered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    estimated_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="aircraft")


class Vessel(Base, TimestampMixin, DataQualityMixin):
    """Maritime vessel — yacht, cargo, passenger, etc. — linked to a person."""

    __tablename__ = "vessels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Maritime identifiers
    mmsi: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    imo_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vessel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    call_sign: Mapped[str | None] = mapped_column(String(50), nullable=True)
    flag_country: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Classification
    vessel_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # cargo|tanker|passenger|fishing|pleasure|tug|warship|yacht

    # Physical specs
    gross_tonnage: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    beam_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    draft_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    builder: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Ownership / operation
    owner_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    operator_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    port_of_registry: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Last known position / voyage
    last_port: Mapped[str | None] = mapped_column(String(255), nullable=True)
    destination_port: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    estimated_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="vessels")
