"""Criminal records — arrests, charges, convictions, warrants, mugshots."""
import uuid
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin, DataQualityMixin


class CriminalRecord(Base, TimestampMixin, DataQualityMixin):
    """One criminal event — arrest, charge, or conviction — for a person."""
    __tablename__ = "criminal_records"
    __table_args__ = (
        Index("ix_criminal_person_id", "person_id"),
        Index("ix_criminal_case_number", "court_case_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Classification
    record_type: Mapped[str] = mapped_column(String(50), nullable=False, default="charge")
    # charge | arrest | conviction | warrant | dismissed | acquitted | pending

    offense_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # felony | misdemeanor | infraction | unknown

    # Charge/offense
    charge: Mapped[str | None] = mapped_column(String(500), nullable=True)
    offense_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    statute: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Court details
    court_case_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    court_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # e.g. "Dallas County, TX" or "SDNY"

    # Dates
    arrest_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    charge_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    disposition_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    warrant_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Outcome
    disposition: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # guilty | not_guilty | dismissed | acquitted | pending | plea_deal | unknown
    sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentence_months: Mapped[int | None] = mapped_column(nullable=True)
    probation_months: Mapped[int | None] = mapped_column(nullable=True)
    fine_usd: Mapped[float | None] = mapped_column(nullable=True)

    # Mugshot
    has_mugshot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mugshot_url_hashed: Mapped[str | None] = mapped_column(String(64), nullable=True)  # sha256 of URL

    # Sex offender registry
    is_sex_offender: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Source
    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url_hashed: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    person: Mapped["Person"] = relationship(back_populates="criminal_records")
