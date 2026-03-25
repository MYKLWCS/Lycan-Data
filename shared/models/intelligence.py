"""Signal intelligence — phone, email, IP address enrichment."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, DataQualityMixin, TimestampMixin


class PhoneIntelligence(Base, TimestampMixin, DataQualityMixin):
    """Carrier, line-type, fraud, and spam enrichment for a phone number."""

    __tablename__ = "phone_intelligence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Optional link to an Identifier row (phone identifier)
    identifier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identifiers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Carrier
    carrier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    carrier_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # mobile|landline|voip|toll_free|premium|unknown
    line_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Geo / time
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    area_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    time_zone: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Status flags
    is_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_ported: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_prepaid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_commercial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Risk signals
    spam_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fraud_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    robocall_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Aliases / other names this number appears under
    known_aliases: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    last_seen_active: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class EmailIntelligence(Base, TimestampMixin, DataQualityMixin):
    """MX validation, breach exposure, deliverability, and fraud signals for an email."""

    __tablename__ = "email_intelligence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Optional link to an Identifier row (email identifier)
    identifier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identifiers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    email_address: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(500), nullable=True)
    domain_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # personal|corporate|edu|gov|mil|provider|disposable|alias
    provider_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Validation
    mx_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    smtp_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_disposable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_role_address: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_catch_all: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Breach exposure
    breach_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_seen_breach: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Risk / reputation
    spam_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fraud_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reputation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    deliverability: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # deliverable|undeliverable|risky|unknown

    # Social footprint — platforms where this email was found
    platforms_found: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class IpIntelligence(Base, TimestampMixin, DataQualityMixin):
    """Geolocation, ASN, proxy/VPN/Tor detection, and threat signals for an IP address."""

    __tablename__ = "ip_intelligence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)  # supports IPv6
    ip_version: Mapped[int] = mapped_column(Integer, default=4, nullable=False)

    # Network
    asn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asn_org: Mapped[str | None] = mapped_column(String(500), nullable=True)
    isp: Mapped[str | None] = mapped_column(String(500), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Geolocation
    country_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_zone: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Privacy / anonymisation flags
    is_vpn: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_proxy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_tor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_datacenter: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_residential: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_mobile: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Threat
    threat_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # spam|malware|botnet|scanner|bruteforce|none
    abuse_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fraud_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
