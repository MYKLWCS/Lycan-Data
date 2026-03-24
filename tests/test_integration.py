"""
Full integration test — exercises the entire shared foundation together.
Requires: postgres (localhost:5432) and dragonfly (localhost:6379) running.
"""

import uuid
from datetime import UTC, datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.constants import (
    BurnerConfidence,
    DefaultRiskTier,
    IdentifierType,
    LineType,
    Platform,
    SeedType,
    WealthBand,
)
from shared.data_quality import apply_quality_to_model, assess_quality
from shared.db import get_test_db
from shared.events import get_event_bus
from shared.freshness import compute_freshness, is_stale
from shared.models import (
    BehaviouralProfile,
    BurnerAssessment,
    CreditRiskAssessment,
    DarkwebMention,
    Identifier,
    Person,
    SocialProfile,
    WealthAssessment,
    Web,
    WebMembership,
)
from shared.schemas import PersonResponse, SeedInput, WebConfig
from shared.tor import TorInstance, tor_manager
from shared.utils import (
    build_profile_url,
    get_line_type,
    is_valid_email,
    normalize_email,
    normalize_handle,
    normalize_phone,
)

# ─── Database Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
async def db():
    async for session in get_test_db():
        yield session


@pytest.fixture
async def test_person(db: AsyncSession):
    """Create a test person and yield it. Rolled back after test."""
    person = Person(
        full_name="Jane Doe",
        date_of_birth=None,
        gender="female",
        nationality="US",
    )
    db.add(person)
    await db.flush()  # get ID without committing
    return person


# ─── Core Integration Tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_person_with_identifier(db: AsyncSession, test_person: Person):
    """Create a person and attach an identifier — verify both persist in session."""
    identifier = Identifier(
        person_id=test_person.id,
        type=IdentifierType.EMAIL.value,
        value="jane.doe@example.com",
        normalized_value="jane.doe@example.com",
        confidence=1.0,
    )
    db.add(identifier)
    await db.flush()

    # Verify via query
    result = await db.execute(select(Identifier).where(Identifier.person_id == test_person.id))
    identifiers = result.scalars().all()
    assert len(identifiers) == 1
    assert identifiers[0].value == "jane.doe@example.com"


@pytest.mark.asyncio
async def test_create_social_profile(db: AsyncSession, test_person: Person):
    """Attach a social profile to a person."""
    profile = SocialProfile(
        person_id=test_person.id,
        platform=Platform.INSTAGRAM.value,
        handle="janedoe",
        display_name="Jane Doe",
        follower_count=1500,
    )
    db.add(profile)
    await db.flush()

    result = await db.execute(
        select(SocialProfile).where(SocialProfile.person_id == test_person.id)
    )
    profiles = result.scalars().all()
    assert len(profiles) == 1
    assert profiles[0].handle == "janedoe"
    assert profiles[0].follower_count == 1500


@pytest.mark.asyncio
async def test_create_web_with_member(db: AsyncSession, test_person: Person):
    """Create an investigation web and add a person as a member."""
    web = Web(
        name="Test Investigation",
        seed_type=SeedType.EMAIL.value,
        seed_value="jane.doe@example.com",
        max_depth=3,
    )
    db.add(web)
    await db.flush()

    membership = WebMembership(
        web_id=web.id,
        person_id=test_person.id,
        role="seed",
        depth_found=0,
    )
    db.add(membership)
    await db.flush()

    result = await db.execute(select(WebMembership).where(WebMembership.web_id == web.id))
    members = result.scalars().all()
    assert len(members) == 1
    assert members[0].role == "seed"


@pytest.mark.asyncio
async def test_behavioural_profile(db: AsyncSession, test_person: Person):
    """Create a behavioural profile for a person."""
    profile = BehaviouralProfile(
        person_id=test_person.id,
        gambling_score=0.75,
        fraud_score=0.20,
        financial_distress_score=0.50,
    )
    db.add(profile)
    await db.flush()

    result = await db.execute(
        select(BehaviouralProfile).where(BehaviouralProfile.person_id == test_person.id)
    )
    bp = result.scalar_one()
    assert bp.gambling_score == 0.75


@pytest.mark.asyncio
async def test_credit_risk_assessment(db: AsyncSession, test_person: Person):
    """Store a credit risk assessment."""
    assessment = CreditRiskAssessment(
        person_id=test_person.id,
        default_risk_score=0.65,
        risk_tier=DefaultRiskTier.HIGH_RISK.value,
        gambling_weight=0.25,
        assessed_at=datetime.now(UTC),
    )
    db.add(assessment)
    await db.flush()

    result = await db.execute(
        select(CreditRiskAssessment).where(CreditRiskAssessment.person_id == test_person.id)
    )
    ra = result.scalar_one()
    assert ra.risk_tier == "high_risk"
    assert ra.default_risk_score == 0.65


@pytest.mark.asyncio
async def test_wealth_assessment(db: AsyncSession, test_person: Person):
    """Store a wealth assessment."""
    wa = WealthAssessment(
        person_id=test_person.id,
        wealth_band=WealthBand.MIDDLE.value,
        income_estimate_usd=75000.0,
        confidence=0.6,
        assessed_at=datetime.now(UTC),
    )
    db.add(wa)
    await db.flush()

    result = await db.execute(
        select(WealthAssessment).where(WealthAssessment.person_id == test_person.id)
    )
    w = result.scalar_one()
    assert w.wealth_band == "middle"
    assert w.income_estimate_usd == 75000.0


@pytest.mark.asyncio
async def test_darkweb_mention(db: AsyncSession, test_person: Person):
    """Record a dark web mention for a person."""
    mention = DarkwebMention(
        person_id=test_person.id,
        source_type="dark_paste",
        mention_context="Email found in paste dump",
        severity="high",
        exposure_score=0.40,
    )
    db.add(mention)
    await db.flush()

    result = await db.execute(
        select(DarkwebMention).where(DarkwebMention.person_id == test_person.id)
    )
    m = result.scalar_one()
    assert m.severity == "high"
    assert m.exposure_score == 0.40


# ─── Event Bus Integration ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_bus_queue_roundtrip():
    """Publish a crawl job to the event bus and retrieve it."""
    async with get_event_bus() as bus:
        job = {
            "job_type": "social_scrape",
            "platform": "instagram",
            "identifier": "janedoe",
            "person_id": str(uuid.uuid4()),
        }
        await bus.enqueue(job, priority="high")
        retrieved = await bus.dequeue("high", timeout=3)
        assert retrieved is not None
        assert retrieved["job_type"] == "social_scrape"
        assert retrieved["identifier"] == "janedoe"


# ─── Data Quality Integration ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_data_quality_applied_to_model(db: AsyncSession, test_person: Person):
    """Apply quality scores to an identifier and verify they're set."""
    identifier = Identifier(
        person_id=test_person.id,
        type=IdentifierType.PHONE.value,
        value="+15558675309",
    )
    db.add(identifier)
    await db.flush()

    apply_quality_to_model(
        identifier,
        last_scraped_at=datetime.now(UTC),
        source_type="social_media_profile",
        source_name="truecaller",
        corroboration_count=2,
    )
    assert identifier.composite_quality > 0.0
    assert identifier.freshness_score >= 0.99
    assert identifier.source_reliability > 0.0


# ─── Utility Integration ─────────────────────────────────────────────────────


def test_full_phone_pipeline():
    """Phone normalization → line type → country code chain."""
    raw = "+14155552671"
    normalized = normalize_phone(raw)
    assert normalized == "+14155552671"
    line_type = get_line_type(raw)
    assert line_type in (LineType.MOBILE, LineType.LANDLINE, LineType.UNKNOWN)


def test_full_email_pipeline():
    normalized = normalize_email("  Test.User@Gmail.COM  ")
    assert normalized == "test.user@gmail.com"
    assert is_valid_email(normalized)


def test_full_social_pipeline():
    handle = normalize_handle("@NatGeo")
    url = build_profile_url("instagram", handle)
    assert handle == "natgeo"
    assert "natgeo" in url


# ─── Schema Integration ───────────────────────────────────────────────────────


def test_seed_input_schema():
    s = SeedInput(
        seed_type=SeedType.EMAIL,
        seed_value="  target@example.com  ",
        max_depth=5,
    )
    assert s.seed_value == "target@example.com"
    assert s.max_depth == 5


def test_web_config_schema():
    cfg = WebConfig(max_depth=2, enable_darkweb=False)
    assert cfg.max_depth == 2
    assert cfg.enable_darkweb is False


# ─── Tor Manager (offline) ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tor_manager_graceful_offline():
    """TorManager handles offline Tor gracefully in test environment."""
    await tor_manager.connect_all()
    status = tor_manager.status()
    # In test env Tor is not running — all should be False (gracefully)
    assert isinstance(status, dict)
    assert set(status.keys()) == {"tor1", "tor2", "tor3"}
