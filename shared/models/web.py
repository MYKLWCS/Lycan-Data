import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin


class Web(Base, TimestampMixin):
    __tablename__ = "webs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    seed_type: Mapped[str] = mapped_column(String(50), nullable=False)
    seed_value: Mapped[str] = mapped_column(String(1024), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    depth: Mapped[int] = mapped_column(default=0, nullable=False)
    max_depth: Mapped[int] = mapped_column(default=3, nullable=False)
    person_count: Mapped[int] = mapped_column(default=0, nullable=False)
    edge_count: Mapped[int] = mapped_column(default=0, nullable=False)

    memberships: Mapped[list["WebMembership"]] = relationship(
        back_populates="web", cascade="all, delete-orphan"
    )


class WebMembership(Base, TimestampMixin):
    __tablename__ = "web_memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    web_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(50), default="member", nullable=False
    )  # seed, discovered
    depth_found: Mapped[int] = mapped_column(default=0, nullable=False)

    web: Mapped["Web"] = relationship(back_populates="memberships")
