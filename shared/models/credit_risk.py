import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class CreditRiskAssessment(Base, TimestampMixin):
    __tablename__ = "credit_risk_assessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    default_risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(30), nullable=False)  # DefaultRiskTier enum
    gambling_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    financial_distress_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    court_judgment_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    burner_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    synthetic_identity_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    darkweb_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    criminal_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    signal_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
