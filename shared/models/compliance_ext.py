"""Extended compliance models — PEP classification, adverse media, shell company links."""

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, DataQualityMixin, TimestampMixin


class PepClassification(Base, TimestampMixin):
    """Politically Exposed Person classification for a given role / appointment period."""

    __tablename__ = "pep_classifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # PEP tier: tier1=head of state, tier2=senior official, tier3=local/regional
    pep_level: Mapped[str] = mapped_column(String(20), nullable=False)
    # tier1|tier2|tier3|family|associate

    pep_category: Mapped[str] = mapped_column(String(100), nullable=False)
    # government|military|judiciary|legislative|state_enterprise|
    # diplomat|international_org|party_official

    # Role details
    position_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(500), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Tenure
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # null = current
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_former: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Family / associate link — references another Person row
    related_to_pep_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )
    relationship_to_pep: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # spouse|child|parent|sibling|business_partner

    source_platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(
        back_populates="pep_classifications", foreign_keys=[person_id]
    )


class AdverseMedia(Base, TimestampMixin, DataQualityMixin):
    """Negative news / adverse media article linked to a person."""

    __tablename__ = "adverse_media"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    headline: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Classification
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # corruption|fraud|money_laundering|drug_trafficking|human_trafficking|
    # terrorism|organized_crime|sanctions_violations|bribery|embezzlement|
    # sexual_misconduct|tax_evasion
    severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    # critical|high|medium|low

    # Sentiment: -1.0 (very negative) → 1.0 (very positive)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_retracted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Other persons / organisations named in the article
    entities_mentioned: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="adverse_media")


class ShellCompanyLink(Base, TimestampMixin, DataQualityMixin):
    """Links a person to an offshore / shell company from leak data or corporate registries."""

    __tablename__ = "shell_company_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Company details
    company_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # llc|corporation|trust|foundation|partnership|holding
    jurisdiction: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # e.g. BVI, Cayman, Delaware, Singapore
    registration_number: Mapped[str | None] = mapped_column(String(200), nullable=True)
    incorporation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dissolution_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Person's role in the company
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # director|shareholder|beneficiary|nominee|authorized_signatory|ubo
    ownership_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_beneficial_owner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_nominee: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Related financial infrastructure
    linked_bank_accounts: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    linked_properties: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # Data provenance
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # ICIJ, Companies House, OpenCorporates, etc.
    leak_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Panama Papers, Pandora Papers, FinCEN Files, etc.

    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    person: Mapped["Person"] = relationship(back_populates="shell_company_links")
