from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _apply_column_defaults(target: Any, args: tuple, kwargs: dict) -> None:
    """SQLAlchemy init event: apply Python-side column defaults before ORM init.

    SQLAlchemy only applies mapped_column(default=...) at INSERT time, not at
    object construction. This listener ensures defaults are visible immediately
    after instantiation, which is required for unit tests that don't hit the DB.
    """
    cls = type(target)
    if not hasattr(cls, "__table__"):
        return
    for col in cls.__table__.columns:
        if col.name in kwargs:
            continue
        if col.default is None:
            continue
        d = col.default
        if d.is_scalar:
            kwargs[col.name] = d.arg
        elif d.is_callable:  # pragma: no branch
            kwargs[col.name] = d.arg({})


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


event.listen(Base, "init", _apply_column_defaults, propagate=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DataQualityMixin:
    """Every row carries data quality metadata."""

    source_reliability: Mapped[float] = mapped_column(default=0.5, nullable=False)
    freshness_score: Mapped[float] = mapped_column(default=1.0, nullable=False)
    corroboration_count: Mapped[int] = mapped_column(default=1, nullable=False)
    corroboration_score: Mapped[float] = mapped_column(default=0.5, nullable=False)
    conflict_flag: Mapped[bool] = mapped_column(default=False, nullable=False)
    verification_status: Mapped[str] = mapped_column(default="unverified", nullable=False)
    composite_quality: Mapped[float] = mapped_column(default=0.5, nullable=False)
    data_quality: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scraped_from: Mapped[str | None] = mapped_column(nullable=True)
