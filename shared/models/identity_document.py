"""Identity documents and financial identity markers."""
import uuid
from datetime import date
from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin, DataQualityMixin


class IdentityDocument(Base, TimestampMixin, DataQualityMixin):
    """A scraped or inferred identity document linked to a person.

    IMPORTANT: We never store full SSNs or document numbers. Only partial
    values (last 4 digits) are persisted. Full values are never written.
    """
    __tablename__ = "identity_documents"
    __table_args__ = (
        Index("ix_idoc_person_id", "person_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Document type
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # driver_license | passport | state_id | ssn_partial | national_id
    # military_id | green_card | visa | tax_id | voter_id

    # Partial document number ONLY — never full number
    doc_number_partial: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # e.g. "***-**-1234" or "****1234"

    issuing_country: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ISO 3166 alpha-2
    issuing_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    issuing_authority: Mapped[str | None] = mapped_column(String(200), nullable=True)

    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_expired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    person: Mapped["Person"] = relationship(back_populates="identity_documents")


class CreditProfile(Base, TimestampMixin, DataQualityMixin):
    """Credit and financial identity profile — inferred or scraped indicators.

    Note: We cannot scrape actual FICO scores — those require bureau access.
    This model stores available proxies and inferred credit tiers.
    """
    __tablename__ = "credit_profiles"
    __table_args__ = (
        Index("ix_credit_person_id", "person_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Inferred from public records — NOT actual bureau score
    estimated_credit_tier: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # excellent (750+) | good (700-749) | fair (650-699) | poor (<650) | unknown

    estimated_score_min: Mapped[int | None] = mapped_column(nullable=True)
    estimated_score_max: Mapped[int | None] = mapped_column(nullable=True)

    # Public record signals that affect credit
    bankruptcy_count: Mapped[int] = mapped_column(default=0, nullable=False)
    lien_count: Mapped[int] = mapped_column(default=0, nullable=False)
    judgment_count: Mapped[int] = mapped_column(default=0, nullable=False)
    foreclosure_count: Mapped[int] = mapped_column(default=0, nullable=False)
    eviction_count: Mapped[int] = mapped_column(default=0, nullable=False)

    # Financial distress indicators
    has_bankruptcy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_tax_lien: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_civil_judgment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_foreclosure: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Source context
    model_version: Mapped[str] = mapped_column(String(30), default="v1", nullable=False)
    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    person: Mapped["Person"] = relationship(back_populates="credit_profiles")
