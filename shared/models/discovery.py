import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class DiscoveredSource(Base, TimestampMixin):
    """
    Review queue for open-discovery finds.

    Populated by Track 2 tools: SpiderFoot, Amass, theHarvester, Sherlock,
    Maigret, Google dorking, crt.sh, Common Crawl, Wayback Machine.

    Operators review pending rows via the Review Tab, then approve or reject.
    Approved rows may have a crawler template auto-generated.
    """

    __tablename__ = "source_discovery_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    category: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # business_profiles, social, government, darkweb, news, …

    # ── Discovery provenance ──────────────────────────────────────────────────
    discovered_by: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # SpiderFoot | Amass | theHarvester | Sherlock | Maigret | GoogleDork | crt.sh | CommonCrawl | Wayback
    discovery_query: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )  # the seed query that produced this hit
    raw_context: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )  # raw tool output snippet

    # ── Quality / risk estimates ───────────────────────────────────────────────
    data_quality_estimate: Mapped[float] = mapped_column(
        Float, default=0.5, nullable=False
    )
    legal_risk: Mapped[str] = mapped_column(
        String(20), default="unknown", nullable=False
    )  # low | medium | high | unknown
    data_types: Mapped[list | None] = mapped_column(
        ARRAY(String), nullable=True
    )  # ["name", "email", "phone", …]

    # ── Proposed extraction pattern ────────────────────────────────────────────
    proposed_pattern: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ── Review outcome ─────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending | approved | rejected
    reliability_tier: Mapped[str | None] = mapped_column(
        String(2), nullable=True
    )  # A | B | C | D | E | F
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Generated crawler ──────────────────────────────────────────────────────
    crawler_template: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    crawler_deployed: Mapped[bool] = mapped_column(default=False, nullable=False)

    # ── Self-improvement signals ───────────────────────────────────────────────
    crawl_success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_records_harvested: Mapped[int] = mapped_column(default=0, nullable=False)
    last_crawled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_high_value: Mapped[bool] = mapped_column(default=False, nullable=False)
