import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin


class SearchProgress(Base, TimestampMixin):
    __tablename__ = "search_progress"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False
    )
    search_session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    total_crawlers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_crawlers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    found_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="running", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    person: Mapped["Person"] = relationship("Person", back_populates="search_progress")

    __table_args__ = (
        Index("ix_search_progress_person_status", "person_id", "status"),
        Index("ix_search_progress_session_id", "search_session_id"),
    )
