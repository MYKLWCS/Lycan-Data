import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class WealthAssessment(Base, TimestampMixin):
    __tablename__ = "wealth_assessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    wealth_band: Mapped[str] = mapped_column(String(20), nullable=False)  # WealthBand enum
    income_estimate_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_worth_estimate_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    employer_signal: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    property_signal: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    vehicle_signal: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    travel_signal: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    crypto_signal: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    luxury_signal: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    education_signal: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    signals: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
