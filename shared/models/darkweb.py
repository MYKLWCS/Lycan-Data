import uuid

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, TimestampMixin


class DarkwebMention(Base, TimestampMixin):
    __tablename__ = "darkweb_mentions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    identifier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identifiers.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # dark_paste, dark_forum, dark_market, paste_site
    source_url_hashed: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # SHA256 of URL
    mention_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    exposure_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    person: Mapped["Person"] = relationship("Person", back_populates="darkweb_mentions")


class CryptoWallet(Base, TimestampMixin):
    __tablename__ = "crypto_wallets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    address: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    chain: Mapped[str] = mapped_column(String(20), nullable=False)  # Chain enum
    first_seen_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_seen_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_volume_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    mixer_exposure: Mapped[bool] = mapped_column(default=False, nullable=False)
    exchange_flags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    person: Mapped["Person"] = relationship("Person", back_populates="crypto_wallets")


class CryptoTransaction(Base, TimestampMixin):
    __tablename__ = "crypto_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crypto_wallets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tx_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    counterparty_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # in, out
    amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    block_time: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risk_flags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
