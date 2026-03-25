"""FamilyTreeSnapshot — persisted genealogy tree for a Person."""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, TimestampMixin

class FamilyTreeSnapshot(Base, TimestampMixin):
    """Cached BFS genealogy tree rooted at a Person."""
    __tablename__ = "family_tree_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    root_person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True)
    tree_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    depth_ancestors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    depth_descendants: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
