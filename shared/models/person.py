import uuid
from datetime import date, datetime
from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from shared.models.base import Base, TimestampMixin, DataQualityMixin


class Person(Base, TimestampMixin, DataQualityMixin):
    __tablename__ = "persons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(100), nullable=True)
    primary_language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Overall risk scores
    relationship_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    behavioural_risk: Mapped[float] = mapped_column(default=0.0, nullable=False)
    darkweb_exposure: Mapped[float] = mapped_column(default=0.0, nullable=False)
    default_risk_score: Mapped[float] = mapped_column(default=0.0, nullable=False)

    # Relationships
    identifiers: Mapped[list["Identifier"]] = relationship(back_populates="person", cascade="all, delete-orphan")
    social_profiles: Mapped[list["SocialProfile"]] = relationship(back_populates="person", cascade="all, delete-orphan")
    aliases: Mapped[list["Alias"]] = relationship(back_populates="person", cascade="all, delete-orphan")
    criminal_records: Mapped[list["CriminalRecord"]] = relationship(back_populates="person", cascade="all, delete-orphan")
    identity_documents: Mapped[list["IdentityDocument"]] = relationship(back_populates="person", cascade="all, delete-orphan")
    credit_profiles: Mapped[list["CreditProfile"]] = relationship(back_populates="person", cascade="all, delete-orphan")
    identifier_history: Mapped[list["IdentifierHistory"]] = relationship(back_populates="person", cascade="all, delete-orphan")


class Alias(Base, TimestampMixin):
    __tablename__ = "aliases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alias_type: Mapped[str] = mapped_column(String(50), nullable=False)  # nickname, maiden_name, etc.
    confidence: Mapped[float] = mapped_column(default=0.5, nullable=False)

    person: Mapped["Person"] = relationship(back_populates="aliases")
