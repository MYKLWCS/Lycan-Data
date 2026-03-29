import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin


class WatchlistMatch(Base, TimestampMixin):
    __tablename__ = "watchlist_matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    list_name: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # OFAC, UN, EU, FBI, Interpol
    list_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # sanctions, pep, terrorist, fugitive
    match_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    match_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    listed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_confirmed: Mapped[bool] = mapped_column(default=False, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    person: Mapped["Person"] = relationship("Person", back_populates="watchlist_matches")
