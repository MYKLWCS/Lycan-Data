import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, DataQualityMixin, TimestampMixin


class Identifier(Base, TimestampMixin, DataQualityMixin):
    __tablename__ = "identifiers"
    __table_args__ = (
        UniqueConstraint("type", "normalized_value", name="uq_identifier_type_normalized"),
        Index("ix_identifier_value", "value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # IdentifierType enum value
    value: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(1024), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    confidence: Mapped[float] = mapped_column(default=1.0, nullable=False)
    is_primary: Mapped[bool] = mapped_column(default=False, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    person: Mapped["Person | None"] = relationship(back_populates="identifiers")
