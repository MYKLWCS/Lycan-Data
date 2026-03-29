import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin


class DataSource(Base, TimestampMixin):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # social, clearweb, darkweb, registry
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    reliability: Mapped[float] = mapped_column(default=0.5, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    requires_tor: Mapped[bool] = mapped_column(default=False, nullable=False)
    rate_limit_per_min: Mapped[int] = mapped_column(default=10, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class CrawlJob(Base, TimestampMixin):
    __tablename__ = "crawl_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    web_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # social, enrichment, darkweb, freshness
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False, index=True)
    priority: Mapped[int] = mapped_column(default=5, nullable=False)
    seed_identifier: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_count: Mapped[int] = mapped_column(default=0, nullable=False)
    tor_circuit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class CrawlLog(Base, TimestampMixin):
    __tablename__ = "crawl_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_received: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tor_exit_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
