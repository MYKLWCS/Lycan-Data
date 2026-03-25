"""Temporal models — timeline events, analyst assessments, travel history."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin


class TimelineEvent(Base, TimestampMixin):
    """A single dated event in a person's life — sourced from any data category."""

    __tablename__ = "timeline_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # When — either a date or a full datetime (not both required)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Classification
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # birth|death|marriage|divorce|arrest|conviction|employment_start|employment_end|
    # address_change|property_purchase|property_sale|company_formed|company_dissolved|
    # travel|social_post|financial_transaction|legal_filing|media_mention|
    # watchlist_added|pep_appointed

    # Descriptive
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Source provenance
    source_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # court_record|property_record|social_media|news|government|financial
    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)

    # Related entities (UUIDs of other persons and arbitrary entity IDs)
    related_person_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    related_entity_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="timeline_events")


class AnalystAssessment(Base, TimestampMixin):
    """Human-authored risk or due-diligence assessment for a person."""

    __tablename__ = "analyst_assessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )

    analyst_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    assessment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # risk_profile|threat_assessment|background_check|due_diligence|kyc|enhanced_due_diligence

    overall_risk: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    # critical|high|medium|low|unknown
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0-1.0

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Structured findings (lists of strings or dicts)
    key_findings: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    red_flags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    recommendations: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # Handling / distribution controls
    classification_level: Mapped[str] = mapped_column(
        String(50), default="unclassified", nullable=False
    )
    # unclassified|restricted|confidential|secret
    tlp_color: Mapped[str] = mapped_column(String(20), default="white", nullable=False)
    # white|green|amber|red

    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="analyst_assessments")


class TravelHistory(Base, TimestampMixin):
    """A single recorded trip or border crossing for a person."""

    __tablename__ = "travel_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Departure
    departure_country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    departure_city: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Arrival
    arrival_country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    arrival_city: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Dates
    travel_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Mode / carrier
    travel_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # air|sea|land|unknown
    carrier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    flight_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Entry details
    visa_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    port_of_entry: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Watchlisting
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    flag_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="travel_history")
