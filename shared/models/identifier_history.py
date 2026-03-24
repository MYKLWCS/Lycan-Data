"""Identifier history — tracks all past phones, emails, handles per person.

When an identifier changes or a new one is discovered, the old value is
archived here so we never lose alternate numbers, past emails, old handles.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin


class IdentifierHistory(Base, TimestampMixin):
    """Archives every observed phone/email/handle associated with a person.

    This is append-only. Never delete rows — they represent historical fact.
    Deduplication is enforced by the unique constraint on (person_id, type, value).
    """

    __tablename__ = "identifier_history"
    __table_args__ = (
        UniqueConstraint("person_id", "type", "value", name="uq_idhistory_person_type_value"),
        Index("ix_idhistory_person_id", "person_id"),
        Index("ix_idhistory_value", "value"),
        Index("ix_idhistory_type", "type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False
    )

    type: Mapped[str] = mapped_column(String(50), nullable=False)
    # phone | email | handle | username | ip_address | device_id | etc.

    value: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # When this value was first and last observed
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Status of this historical identifier
    is_current: Mapped[bool] = mapped_column(default=False, nullable=False)
    # True only if this is still the active identifier
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    # False if number/email is confirmed dead/disconnected

    # Confidence that this identifier belongs to this person
    confidence: Mapped[float] = mapped_column(default=0.7, nullable=False)

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    person: Mapped["Person"] = relationship(back_populates="identifier_history")
