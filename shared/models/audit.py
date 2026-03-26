import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_api_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    access_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_actor_access_time", "actor_api_key", "access_time"),
        Index("ix_audit_resource_access_time", "resource_type", "resource_id", "access_time"),
    )


class AuditRequestLog(Base):
    """Per-request audit log for authenticated API calls (FIX 5)."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    api_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_api_key", "api_key"),
    )


class SystemAudit(Base, TimestampMixin):
    """Hourly snapshot of platform health metrics written by AuditDaemon."""

    __tablename__ = "system_audits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Per-person quality metrics
    persons_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persons_low_coverage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persons_stale: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persons_conflict: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Crawler health
    crawlers_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    crawlers_healthy: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    crawlers_degraded: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Data volume (today)
    tags_assigned_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    merges_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persons_ingested_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Freeform extra data
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_system_audits_run_at", "run_at"),)
