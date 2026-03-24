import uuid
from datetime import date
from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, TimestampMixin


class BreachRecord(Base, TimestampMixin):
    __tablename__ = "breach_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    identifier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identifiers.id", ondelete="SET NULL"), nullable=True
    )
    breach_name: Mapped[str] = mapped_column(String(255), nullable=False)
    breach_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), default="clearweb", nullable=False)  # clearweb, darkweb, paste
    exposed_fields: Mapped[list] = mapped_column(ARRAY(String), default=list, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    raw_sample: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
