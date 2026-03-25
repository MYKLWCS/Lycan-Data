"""Professional records — licenses, corporate directorships, military service."""

import uuid
from datetime import date

from sqlalchemy import BigInteger, Boolean, Date, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, DataQualityMixin, TimestampMixin


class ProfessionalLicense(Base, TimestampMixin, DataQualityMixin):
    """State- or body-issued professional license held by a person."""

    __tablename__ = "professional_licenses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )

    license_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Medical Doctor|Attorney|CPA|Real Estate Agent|Financial Advisor|
    # Contractor|Nurse|Pharmacist|Engineer|Pilot
    license_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issuing_body: Mapped[str | None] = mapped_column(String(500), nullable=True)
    issuing_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    issuing_country: Mapped[str] = mapped_column(String(100), default="US", nullable=False)

    # Validity window
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Status flags
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Disciplinary history and specialisation areas (lists of dicts)
    disciplinary_actions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    specializations: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verification_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="professional_licenses")


class CorporateDirectorship(Base, TimestampMixin, DataQualityMixin):
    """Executive, board, or ownership role at a company."""

    __tablename__ = "corporate_directorships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Company details
    company_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_registration: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company_jurisdiction: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Role
    role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # CEO|CFO|Director|Chairman|Secretary|Treasurer|President|Managing_Director
    is_executive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_board_member: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Equity / shareholding
    ownership_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    share_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    share_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Appointment window
    appointment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    resignation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Company financials / status
    company_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # active|dissolved|dormant|liquidation
    company_industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_revenue_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    company_employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="corporate_directorships")


class MilitaryRecord(Base, TimestampMixin, DataQualityMixin):
    """Military service record for a person."""

    __tablename__ = "military_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )

    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Army|Navy|Air Force|Marines|Coast Guard|Space Force|National Guard|Reserves
    country: Mapped[str] = mapped_column(String(100), default="US", nullable=False)
    rank: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rank_grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # E1-E9 (enlisted) | O1-O10 (commissioned) | W1-W5 (warrant)
    service_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Service window
    enlistment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    discharge_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    discharge_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # honorable|general|other_than_honorable|bad_conduct|dishonorable|entry_level

    # Specialty
    mos_afi_nec: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Military Occupational Specialty / Air Force Specialty Code / Navy Enlisted Classification

    # Service history (lists of dicts)
    deployments: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    decorations: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # Security clearance
    security_clearance: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # none|confidential|secret|top_secret|ts_sci|yankee_white
    clearance_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # active|inactive|revoked|unknown

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="military_records")
