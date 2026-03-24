import uuid

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class BurnerAssessment(Base, TimestampMixin):
    __tablename__ = "burner_assessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identifier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identifiers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    burner_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)  # BurnerConfidence enum
    line_type: Mapped[str | None] = mapped_column(String(30), nullable=True)  # LineType enum
    carrier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    carrier_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # voip, prepaid, mobile, unknown
    is_ported: Mapped[bool | None] = mapped_column(nullable=True)
    whatsapp_registered: Mapped[bool | None] = mapped_column(nullable=True)
    telegram_registered: Mapped[bool | None] = mapped_column(nullable=True)
    signals: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )  # individual signal scores
