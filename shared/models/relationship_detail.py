import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class RelationshipDetail(Base, TimestampMixin):
    """Extended relationship metadata with scoring and verification."""

    __tablename__ = "relationship_details"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    relationship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("relationships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )

    # Detailed type (more granular than Relationship.rel_type)
    detailed_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # spouse, ex_spouse, parent, child, sibling, grandparent, grandchild,
    # aunt_uncle, cousin, in_law, girlfriend, boyfriend, partner, ex_partner,
    # friend, best_friend, acquaintance, neighbor, roommate, classmate,
    # employer, employee, business_partner, co_founder, colleague, client, mentor,
    # lawyer, co_defendant, plaintiff, witness,
    # co_signer, beneficiary, trustee, power_of_attorney

    # Scoring (0-100)
    strength: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    freshness_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    composite_score: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)

    # Discovery metadata
    discovered_via: Mapped[str | None] = mapped_column(String(100), nullable=True)
    discovery_sources: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Verification
    verification_level: Mapped[str] = mapped_column(String(30), default="unverified", nullable=False)
    # unverified -> format_valid -> single_source -> cross_referenced -> confirmed -> certified

    # Dates
    relationship_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    relationship_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflict: Mapped[bool] = mapped_column(default=False, nullable=False)
