import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class BuilderJob(Base, TimestampMixin):
    """People Builder discovery job — tracks discovery, build, filter, expand phases."""

    __tablename__ = "builder_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    # pending -> discovering -> building -> filtering -> expanding -> complete / failed / cancelled

    # Input criteria (stored as-is for replay)
    criteria: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Phase counters
    discovered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    built_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filtered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expanded_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    relationships_mapped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Max results cap
    max_results: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


class BuilderJobPerson(Base, TimestampMixin):
    """Links a person to the builder job that discovered them."""

    __tablename__ = "builder_job_persons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    phase: Mapped[str] = mapped_column(String(20), default="discovered", nullable=False)
    # discovered -> built -> filtered_in / filtered_out -> expanded
    enrichment_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    match_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
