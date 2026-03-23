import uuid
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from shared.models.base import Base, TimestampMixin, DataQualityMixin


class SocialProfile(Base, TimestampMixin, DataQualityMixin):
    __tablename__ = "social_profiles"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_social_platform_uid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handle: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    follower_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    following_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    post_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    profile_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profile_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    person: Mapped["Person | None"] = relationship(back_populates="social_profiles")
