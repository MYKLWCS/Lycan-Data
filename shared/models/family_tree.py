import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class FamilyTreeSnapshot(Base, TimestampMixin):
    __tablename__ = "family_tree_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    root_person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tree_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    depth_ancestors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    depth_descendants: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
