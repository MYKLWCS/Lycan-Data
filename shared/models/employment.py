import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, DataQualityMixin, TimestampMixin


class EmploymentHistory(Base, TimestampMixin, DataQualityMixin):
    __tablename__ = "employment_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    employer_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    ended_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(default=False, nullable=False)
    estimated_salary_usd: Mapped[float | None] = mapped_column(nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    person: Mapped["Person"] = relationship("Person", back_populates="employment_history")
