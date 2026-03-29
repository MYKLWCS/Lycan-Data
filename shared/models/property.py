"""Property records — ownership, valuations, mortgages."""

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, DataQualityMixin, TimestampMixin


class Property(Base, TimestampMixin, DataQualityMixin):
    """A real property parcel — residential, commercial, land, etc."""

    __tablename__ = "properties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Current / most-recent owner link (nullable — may be unknown or corporate)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Parcel identification
    parcel_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Location
    street_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    county: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="US", nullable=False)

    # Classification
    property_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # residential|commercial|industrial|land|mixed_use|agricultural
    sub_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # single_family|multi_family|condo|townhouse|mobile|vacant_land|office|retail|warehouse

    # Physical characteristics
    year_built: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sq_ft_living: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sq_ft_lot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms_full: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bathrooms_half: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stories: Mapped[int | None] = mapped_column(Integer, nullable=True)
    garage_spaces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_pool: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Zoning / land
    zoning: Mapped[str | None] = mapped_column(String(100), nullable=True)
    land_use_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    school_district: Mapped[str | None] = mapped_column(String(255), nullable=True)
    flood_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Coordinates
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Valuation / tax (current snapshot — full history in property_valuations)
    current_assessed_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_market_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_tax_annual_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Last recorded sale
    last_sale_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_sale_price_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_sale_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # arm_length|foreclosure|short_sale|reo|family_transfer|quit_claim

    # Owner as recorded at county (may differ from person_id entity)
    owner_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    owner_mailing_address: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_owner_occupied: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    homestead_exemption: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_investment_property: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="properties", foreign_keys=[person_id])
    ownership_history: Mapped[list["PropertyOwnershipHistory"]] = relationship(
        back_populates="property", cascade="all, delete-orphan"
    )
    valuations: Mapped[list["PropertyValuation"]] = relationship(
        back_populates="property", cascade="all, delete-orphan"
    )
    mortgages: Mapped[list["PropertyMortgage"]] = relationship(
        back_populates="property", cascade="all, delete-orphan"
    )


class PropertyOwnershipHistory(Base, TimestampMixin):
    """Chronological ownership chain for a parcel — sourced from deed records."""

    __tablename__ = "property_ownership_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional link to a resolved Lycan person entity
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Raw deed data
    owner_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    owner_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # individual|llc|corporation|trust|government|unknown

    # Acquisition
    acquisition_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    acquisition_price_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    acquisition_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # purchase|inheritance|gift|foreclosure|tax_deed|short_sale|transfer

    # Disposition (null disposition_date = current owner)
    disposition_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    disposition_price_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    disposition_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Deed / instrument
    document_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    grantor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    grantee: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title_company: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Financing at time of acquisition
    loan_amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    down_payment_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Computed / derived
    days_held: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    property: Mapped["Property"] = relationship(back_populates="ownership_history")
    person: Mapped["Person"] = relationship("Person", back_populates="property_ownership_history")


class PropertyValuation(Base, TimestampMixin):
    """Annual assessed / estimated values for a property."""

    __tablename__ = "property_valuations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    valuation_year: Mapped[int] = mapped_column(Integer, nullable=False)

    # Assessed values (county assessor)
    assessed_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    assessed_land_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    assessed_improvement_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Market / AVM estimate (Zillow, Redfin, ATTOM, etc.)
    market_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Tax
    tax_amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    tax_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Exemptions (homestead, veteran, senior, disability, etc.)
    exemptions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Source: county_assessor|zillow|redfin|attom
    valuation_source: Mapped[str | None] = mapped_column(String(100), nullable=True)

    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    property: Mapped["Property"] = relationship(back_populates="valuations")


class PropertyMortgage(Base, TimestampMixin):
    """Mortgage / lien recorded against a property."""

    __tablename__ = "property_mortgages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    lender_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    loan_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # conventional|fha|va|usda|heloc|second_mortgage|hard_money|reverse|construction

    original_loan_amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    interest_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    loan_term_months: Mapped[int | None] = mapped_column(Integer, nullable=True)

    origination_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    maturity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    recording_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    instrument_number: Mapped[str | None] = mapped_column(String(200), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_delinquent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Foreclosure tracking
    foreclosure_filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    foreclosure_sale_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Payoff
    payoff_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payoff_amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    property: Mapped["Property"] = relationship(back_populates="mortgages")
    person: Mapped["Person"] = relationship("Person", back_populates="property_mortgages")
