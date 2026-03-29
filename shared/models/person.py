import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, DataQualityMixin, TimestampMixin


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
    merged_into: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("persons.id"),
        nullable=True,
        index=True,
    )

    # Overall risk scores
    relationship_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    behavioural_risk: Mapped[float] = mapped_column(default=0.0, nullable=False)
    darkweb_exposure: Mapped[float] = mapped_column(default=0.0, nullable=False)
    default_risk_score: Mapped[float] = mapped_column(default=0.0, nullable=False)

    # Physical description
    height_cm: Mapped[float | None] = mapped_column(nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(nullable=True)
    eye_color: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hair_color: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hair_length: Mapped[str | None] = mapped_column(String(30), nullable=True)
    build: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # slim|medium|heavy|athletic
    skin_tone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    distinguishing_marks: Mapped[str | None] = mapped_column(Text, nullable=True)  # tattoos, scars

    # Identity
    place_of_birth: Mapped[str | None] = mapped_column(String(500), nullable=True)
    country_of_birth: Mapped[str | None] = mapped_column(String(100), nullable=True)
    citizenship_countries: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    languages_spoken: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    religion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ethnicity: Mapped[str | None] = mapped_column(String(100), nullable=True)
    political_affiliation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    marital_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # single|married|divorced|widowed|separated|common_law
    number_of_children: Mapped[int | None] = mapped_column(nullable=True)

    # Wealth / financial summary (denormalised for fast access)
    estimated_net_worth_usd: Mapped[float | None] = mapped_column(nullable=True)
    estimated_annual_income_usd: Mapped[float | None] = mapped_column(nullable=True)
    wealth_tier: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # ultra_hnw|hnw|affluent|mass_affluent|mass_market
    property_count: Mapped[int] = mapped_column(default=0, nullable=False)
    vehicle_count: Mapped[int] = mapped_column(default=0, nullable=False)
    aircraft_count: Mapped[int] = mapped_column(default=0, nullable=False)
    vessel_count: Mapped[int] = mapped_column(default=0, nullable=False)

    # Risk / compliance summary
    pep_status: Mapped[bool] = mapped_column(default=False, nullable=False)
    pep_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_sanctioned: Mapped[bool] = mapped_column(default=False, nullable=False)
    sanctions_lists: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    adverse_media_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    adverse_media_count: Mapped[int] = mapped_column(default=0, nullable=False)
    is_deceased: Mapped[bool] = mapped_column(default=False, nullable=False)
    date_of_death: Mapped[date | None] = mapped_column(Date, nullable=True)
    cause_of_death: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Alternative credit score (300-850, FICO-compatible scale)
    alt_credit_score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    alt_credit_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # AML risk (0.0-1.0 composite)
    aml_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    aml_risk_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Denormalised marketing tag list for fast filtering
    marketing_tags_list: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # Enrichment quality
    enrichment_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    is_pep: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)

    # Data completeness
    data_completeness_pct: Mapped[float] = mapped_column(default=0.0, nullable=False)
    last_full_enrichment_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    identifiers: Mapped[list["Identifier"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    social_profiles: Mapped[list["SocialProfile"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    aliases: Mapped[list["Alias"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    criminal_records: Mapped[list["CriminalRecord"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    identity_documents: Mapped[list["IdentityDocument"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    credit_profiles: Mapped[list["CreditProfile"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    identifier_history: Mapped[list["IdentifierHistory"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    properties: Mapped[list["Property"]] = relationship(
        back_populates="person", cascade="all, delete-orphan", foreign_keys="Property.person_id"
    )
    vehicles: Mapped[list["Vehicle"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    aircraft: Mapped[list["Aircraft"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    vessels: Mapped[list["Vessel"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    addresses: Mapped[list["Address"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    pep_classifications: Mapped[list["PepClassification"]] = relationship(
        back_populates="person",
        cascade="all, delete-orphan",
        foreign_keys="PepClassification.person_id",
    )
    adverse_media: Mapped[list["AdverseMedia"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    shell_company_links: Mapped[list["ShellCompanyLink"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    professional_licenses: Mapped[list["ProfessionalLicense"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    corporate_directorships: Mapped[list["CorporateDirectorship"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    military_records: Mapped[list["MilitaryRecord"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    timeline_events: Mapped[list["TimelineEvent"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    analyst_assessments: Mapped[list["AnalystAssessment"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    travel_history: Mapped[list["TravelHistory"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )

    # --- Relationships added for complete bidirectional mapping ---
    education_history: Mapped[list["Education"]] = relationship(
        "Education", back_populates="person", cascade="all, delete-orphan"
    )
    employment_history: Mapped[list["EmploymentHistory"]] = relationship(
        "EmploymentHistory", back_populates="person", cascade="all, delete-orphan"
    )
    location_visits: Mapped[list["LocationVisit"]] = relationship(
        "LocationVisit", back_populates="person", cascade="all, delete-orphan"
    )
    watchlist_matches: Mapped[list["WatchlistMatch"]] = relationship(
        "WatchlistMatch", back_populates="person", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(
        "Alert", back_populates="person", cascade="all, delete-orphan"
    )
    breach_records: Mapped[list["BreachRecord"]] = relationship(
        "BreachRecord", back_populates="person", cascade="all, delete-orphan"
    )
    darkweb_mentions: Mapped[list["DarkwebMention"]] = relationship(
        "DarkwebMention", back_populates="person", cascade="all, delete-orphan"
    )
    crypto_wallets: Mapped[list["CryptoWallet"]] = relationship(
        "CryptoWallet", back_populates="person", cascade="all, delete-orphan"
    )
    media_assets: Mapped[list["MediaAsset"]] = relationship(
        "MediaAsset", back_populates="person", cascade="all, delete-orphan"
    )
    web_memberships: Mapped[list["WebMembership"]] = relationship(
        "WebMembership", back_populates="person", cascade="all, delete-orphan"
    )
    marketing_tags: Mapped[list["MarketingTag"]] = relationship(
        "MarketingTag", back_populates="person", cascade="all, delete-orphan"
    )
    consumer_segments: Mapped[list["ConsumerSegment"]] = relationship(
        "ConsumerSegment", back_populates="person", cascade="all, delete-orphan"
    )
    ticket_sizes: Mapped[list["TicketSize"]] = relationship(
        "TicketSize", back_populates="person", cascade="all, delete-orphan"
    )
    phone_intelligence: Mapped[list["PhoneIntelligence"]] = relationship(
        "PhoneIntelligence", back_populates="person", cascade="all, delete-orphan"
    )
    email_intelligence: Mapped[list["EmailIntelligence"]] = relationship(
        "EmailIntelligence", back_populates="person", cascade="all, delete-orphan"
    )
    ip_intelligence: Mapped[list["IpIntelligence"]] = relationship(
        "IpIntelligence", back_populates="person", cascade="all, delete-orphan"
    )
    credit_risk_assessments: Mapped[list["CreditRiskAssessment"]] = relationship(
        "CreditRiskAssessment", back_populates="person", cascade="all, delete-orphan"
    )
    behavioural_profiles: Mapped[list["BehaviouralProfile"]] = relationship(
        "BehaviouralProfile", back_populates="person", cascade="all, delete-orphan"
    )
    opt_outs: Mapped[list["OptOut"]] = relationship(
        "OptOut", back_populates="person", cascade="all, delete-orphan"
    )
    wealth_assessments: Mapped[list["WealthAssessment"]] = relationship(
        "WealthAssessment", back_populates="person", cascade="all, delete-orphan"
    )
    property_ownership_history: Mapped[list["PropertyOwnershipHistory"]] = relationship(
        "PropertyOwnershipHistory", back_populates="person", cascade="all, delete-orphan"
    )
    property_mortgages: Mapped[list["PropertyMortgage"]] = relationship(
        "PropertyMortgage", back_populates="person", cascade="all, delete-orphan"
    )
    family_tree_snapshots: Mapped[list["FamilyTreeSnapshot"]] = relationship(
        "FamilyTreeSnapshot", back_populates="person", foreign_keys="FamilyTreeSnapshot.root_person_id"
    )
    crawl_jobs: Mapped[list["CrawlJob"]] = relationship(
        "CrawlJob", back_populates="person"
    )
    data_quality_logs: Mapped[list["DataQualityLog"]] = relationship(
        "DataQualityLog", back_populates="person"
    )
    search_progress: Mapped[list["SearchProgress"]] = relationship(
        "SearchProgress", back_populates="person"
    )


class Alias(Base, TimestampMixin):
    __tablename__ = "aliases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alias_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # nickname, maiden_name, etc.
    confidence: Mapped[float] = mapped_column(default=0.5, nullable=False)

    person: Mapped["Person"] = relationship(back_populates="aliases")
