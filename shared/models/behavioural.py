import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class BehaviouralProfile(Base, TimestampMixin):
    __tablename__ = "behavioural_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    gambling_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    drug_signal_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    fraud_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    violence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    financial_distress_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    criminal_signal_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    active_hours: Mapped[list] = mapped_column(ARRAY(String), default=list, nullable=False)
    top_locations: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    interests: Mapped[list] = mapped_column(ARRAY(String), default=list, nullable=False)
    languages_used: Mapped[list] = mapped_column(ARRAY(String), default=list, nullable=False)
    sentiment_avg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_assessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class BehaviouralSignal(Base, TimestampMixin):
    __tablename__ = "behavioural_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("behavioural_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)  # CriminalSignalType enum
    score: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_platform: Mapped[str | None] = mapped_column(String(50), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
