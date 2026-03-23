# Lycan Phase 1: Shared Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the complete shared infrastructure layer — Docker services, PostgreSQL with all 28 tables, SQLAlchemy async models, Pydantic schemas, Dragonfly event bus, Tor circuit manager, and data quality engine — so every subsequent module has a working foundation to build on.

**Architecture:** PostgreSQL 16 with Apache AGE (graph traversal) and pgvector (embeddings) as the primary store. Dragonfly (Redis-compatible) for the pub/sub event bus and cache. Three Tor instances for anonymised outbound requests. All shared code lives in `shared/` — modules never import from each other's internals, only from `shared/`.

**Tech Stack:** Python 3.12, PostgreSQL 16 + AGE + pgvector, SQLAlchemy 2.x async + asyncpg, Alembic, Pydantic v2, Dragonfly, stem (Tor), Docker Compose v2

---

## File Map

```
lycan/
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── .env                          # gitignored
├── Makefile
├── pyproject.toml
├── shared/
│   ├── __init__.py
│   ├── config.py                 # Pydantic Settings — all env vars + kill switches
│   ├── db.py                     # SQLAlchemy async engine + session factory
│   ├── constants.py              # Enums: SeedType, RelType, AlertSeverity, WealthBand, etc.
│   ├── events.py                 # Dragonfly pub/sub wrapper
│   ├── tor.py                    # TorManager + helper functions
│   ├── data_quality.py           # DataQuality mixin + composite score computation
│   ├── freshness.py              # Freshness decay functions + half-life table
│   ├── scrapy_middleware.py      # TorProxyMiddleware for Scrapy
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py               # Base declarative class + DataQuality mixin
│   │   ├── person.py             # Person, Alias
│   │   ├── identifier.py         # Identifier
│   │   ├── relationship.py       # Relationship, RelationshipScoreHistory
│   │   ├── social_profile.py     # SocialProfile
│   │   ├── web.py                # Web, WebMembership
│   │   ├── crawl.py              # CrawlJob, CrawlLog, DataSource
│   │   ├── alert.py              # Alert
│   │   ├── address.py            # Address
│   │   ├── employment.py         # EmploymentHistory
│   │   ├── education.py          # Education
│   │   ├── breach.py             # BreachRecord
│   │   ├── media.py              # MediaAsset
│   │   ├── watchlist.py          # WatchlistMatch
│   │   ├── behavioural.py        # BehaviouralProfile, BehaviouralSignal
│   │   ├── burner.py             # BurnerAssessment
│   │   ├── darkweb.py            # DarkwebMention, CryptoWallet, CryptoTransaction
│   │   ├── credit_risk.py        # CreditRiskAssessment
│   │   ├── wealth.py             # WealthAssessment
│   │   └── quality.py            # DataQualityLog, FreshnessQueue
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── seed.py               # SeedInput, SeedType
│   │   ├── person.py             # PersonResponse, PersonSummary
│   │   ├── relationship.py       # RelationshipResponse, ScoreBreakdown
│   │   ├── web.py                # WebResponse, WebConfig
│   │   └── alert.py              # AlertResponse
│   └── utils/
│       ├── __init__.py
│       ├── phone.py              # libphonenumber wrappers
│       ├── email.py              # Email normalisation
│       ├── social.py             # Handle normalisation
│       └── scoring.py            # Score computation helpers
├── migrations/
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
└── tests/
    ├── conftest.py               # Shared fixtures: test DB, event bus, Tor mock
    ├── test_shared/
    │   ├── test_config.py
    │   ├── test_db.py
    │   ├── test_events.py
    │   ├── test_tor.py
    │   ├── test_data_quality.py
    │   ├── test_freshness.py
    │   └── test_models.py
    └── test_migrations.py
```

---

## Task 1: Project Scaffold + Docker Compose

**Files:**
- Create: `docker-compose.yml`
- Create: `docker-compose.dev.yml`
- Create: `.env.example`
- Create: `Makefile`
- Create: `pyproject.toml`

- [ ] **Step 1.1: Create pyproject.toml**

```toml
[tool.poetry]
name = "lycan"
version = "0.1.0"
description = "Recursive people intelligence platform"
python = "^3.12"

[tool.poetry.dependencies]
python = "^3.12"
fastapi = "^0.115"
uvicorn = {extras = ["standard"], version = "^0.32"}
sqlalchemy = {extras = ["asyncio"], version = "^2.0"}
asyncpg = "^0.30"
alembic = "^1.14"
pydantic = "^2.10"
pydantic-settings = "^2.7"
redis = "^5.2"
stem = "^1.8"
phonenumbers = "^8.13"
spacy = "^3.8"
networkx = "^3.4"
httpx = "^0.28"
playwright = "^1.49"
scrapy = "^2.12"
python-jose = {extras = ["cryptography"], version = "^3.3"}
passlib = "^1.7"
python-multipart = "^0.0.20"

[tool.poetry.dev-dependencies]
pytest = "^8.3"
pytest-asyncio = "^0.24"
pytest-cov = "^6.0"
anyio = "^4.7"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 1.2: Create docker-compose.yml**

```yaml
version: "3.9"

services:
  postgres:
    image: apache/age:PG16
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-lycan}
      POSTGRES_USER: ${POSTGRES_USER:-lycan}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init_db.sql:/docker-entrypoint-initdb.d/01_init.sql
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-lycan}"]
      interval: 5s
      timeout: 5s
      retries: 10

  dragonfly:
    image: docker.dragonflydb.io/dragonflydb/dragonfly:latest
    ulimits:
      memlock: -1
    volumes:
      - dragonfly_data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  meilisearch:
    image: getmeili/meilisearch:latest
    environment:
      MEILI_MASTER_KEY: ${MEILI_MASTER_KEY}
    volumes:
      - meili_data:/meili_data
    ports:
      - "7700:7700"

  tor-1:
    image: dperson/torproxy:latest
    environment:
      TOR_CONTROL_PORT: "9051"
      TOR_CONTROL_PASSWD: ${TOR_CONTROL_PASSWORD}
    ports:
      - "9050:9050"
      - "9051:9051"

  tor-2:
    image: dperson/torproxy:latest
    environment:
      TOR_CONTROL_PORT: "9053"
      TOR_CONTROL_PASSWD: ${TOR_CONTROL_PASSWORD}
    ports:
      - "9052:9050"
      - "9053:9051"

  tor-3:
    image: dperson/torproxy:latest
    environment:
      TOR_CONTROL_PORT: "9055"
      TOR_CONTROL_PASSWD: ${TOR_CONTROL_PASSWORD}
    ports:
      - "9054:9050"
      - "9055:9051"

volumes:
  postgres_data:
  dragonfly_data:
  meili_data:
```

- [ ] **Step 1.3: Create scripts/init_db.sql**

```sql
-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "age";
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
```

- [ ] **Step 1.4: Create .env.example**

```env
# Database
POSTGRES_DB=lycan
POSTGRES_USER=lycan
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql+asyncpg://lycan:changeme@localhost:5432/lycan
DATABASE_URL_SYNC=postgresql://lycan:changeme@localhost:5432/lycan

# Dragonfly / Redis
DRAGONFLY_URL=redis://localhost:6379/0

# MeiliSearch
MEILI_URL=http://localhost:7700
MEILI_MASTER_KEY=changeme

# Tor
TOR_CONTROL_PASSWORD=changeme
TOR_ENABLED=true

# Proxy override (leave blank to use Tor)
PROXY_OVERRIDE=

# Module kill switches
ENABLE_INSTAGRAM=true
ENABLE_LINKEDIN=true
ENABLE_TWITTER=true
ENABLE_FACEBOOK=true
ENABLE_TIKTOK=true
ENABLE_TELEGRAM=true
ENABLE_DARKWEB=true
ENABLE_BURNER_CHECK=true
ENABLE_CREDIT_RISK=true
ENABLE_WEALTH=true
ENABLE_CRIMINAL_SIGNALS=true
ENABLE_CRYPTO_TRACE=true

# Budget
DAILY_API_BUDGET_USD=0

# App
SECRET_KEY=changeme-32-chars-minimum-please
DEBUG=false
LOG_LEVEL=INFO
```

- [ ] **Step 1.5: Create Makefile**

```makefile
.PHONY: dev test migrate shell logs down

dev:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up

up:
	docker compose up -d

down:
	docker compose down

test:
	pytest tests/ -v --cov=shared --cov-report=term-missing

migrate:
	alembic upgrade head

migrate-create:
	alembic revision --autogenerate -m "$(MSG)"

shell:
	docker compose exec postgres psql -U lycan -d lycan

logs:
	docker compose logs -f

install:
	pip install poetry && poetry install
	python -m spacy download en_core_web_lg
	playwright install chromium
```

- [ ] **Step 1.6: Start services and verify**

```bash
cp .env.example .env
# Edit .env with real passwords
docker compose up -d postgres dragonfly
docker compose ps
```

Expected: postgres and dragonfly showing "healthy"

- [ ] **Step 1.7: Commit**

```bash
git init
git add docker-compose.yml docker-compose.dev.yml .env.example Makefile pyproject.toml scripts/
git commit -m "feat: project scaffold and docker compose"
```

---

## Task 2: Config + Constants

**Files:**
- Create: `shared/config.py`
- Create: `shared/constants.py`
- Create: `tests/test_shared/test_config.py`

- [ ] **Step 2.1: Write failing test**

```python
# tests/test_shared/test_config.py
from shared.config import settings

def test_settings_loads():
    assert settings.database_url.startswith("postgresql+asyncpg://")

def test_kill_switches_default_true():
    assert settings.enable_instagram is True
    assert settings.enable_darkweb is True
    assert settings.enable_burner_check is True

def test_tor_enabled_default():
    assert settings.tor_enabled is True
```

- [ ] **Step 2.2: Run — expect ImportError**

```bash
pytest tests/test_shared/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'shared'`

- [ ] **Step 2.3: Implement shared/config.py**

```python
# shared/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn, RedisDsn


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://lycan:lycan@localhost:5432/lycan"
    database_url_sync: str = "postgresql://lycan:lycan@localhost:5432/lycan"

    # Dragonfly
    dragonfly_url: str = "redis://localhost:6379/0"

    # MeiliSearch
    meili_url: str = "http://localhost:7700"
    meili_master_key: str = "changeme"

    # Tor
    tor_control_password: str = "changeme"
    tor_enabled: bool = True
    proxy_override: str = ""

    # Module kill switches
    enable_instagram: bool = True
    enable_linkedin: bool = True
    enable_twitter: bool = True
    enable_facebook: bool = True
    enable_tiktok: bool = True
    enable_telegram: bool = True
    enable_darkweb: bool = True
    enable_burner_check: bool = True
    enable_credit_risk: bool = True
    enable_wealth: bool = True
    enable_criminal_signals: bool = True
    enable_crypto_trace: bool = True

    # Budget
    daily_api_budget_usd: float = 0.0

    # App
    secret_key: str = "changeme"
    debug: bool = False
    log_level: str = "INFO"


settings = Settings()
```

- [ ] **Step 2.4: Create shared/constants.py**

```python
# shared/constants.py
from enum import StrEnum


class SeedType(StrEnum):
    PHONE = "phone"
    EMAIL = "email"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    TELEGRAM = "telegram"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"
    WHATSAPP = "whatsapp"
    WEBSITE = "website"
    NATIONAL_ID = "national_id"
    NAME = "name"
    USERNAME = "username"
    WALLET = "wallet"


class IdentifierType(StrEnum):
    PHONE = "phone"
    EMAIL = "email"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    TELEGRAM = "telegram"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"
    WHATSAPP = "whatsapp"
    WEBSITE = "website"
    NATIONAL_ID = "national_id"


class RelationshipType(StrEnum):
    FAMILY = "family"
    SPOUSE = "spouse"
    PARENT = "parent"
    CHILD = "child"
    SIBLING = "sibling"
    FRIEND = "friend"
    COLLEAGUE = "colleague"
    BUSINESS_ASSOCIATE = "business_associate"
    ROMANTIC = "romantic"
    CO_TAGGED = "co_tagged"
    MUTUAL_FOLLOWER = "mutual_follower"
    CO_RESIDENT = "co_resident"
    CO_DIRECTOR = "co_director"
    CLASSMATE = "classmate"
    UNKNOWN = "unknown"


class RelationshipTier(StrEnum):
    CRITICAL = "CRITICAL"    # 0.80–1.00
    STRONG = "STRONG"        # 0.60–0.79
    MODERATE = "MODERATE"    # 0.40–0.59
    WEAK = "WEAK"            # 0.20–0.39
    TENUOUS = "TENUOUS"      # 0.00–0.19


class AlertSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AlertType(StrEnum):
    SANCTIONS_HIT = "sanctions_hit"
    PROFILE_DELETED = "profile_deleted"
    BREACH_EXPOSURE = "breach_exposure"
    IDENTITY_CHANGE = "identity_change"
    NEW_CONNECTION = "new_connection"
    SCORE_THRESHOLD = "score_threshold"
    WEB_MERGER = "web_merger"
    LOCATION_CHANGE = "location_change"
    RECRAWL_ANOMALY = "recrawl_anomaly"
    BEHAVIOURAL_CHANGE = "behavioural_change"
    DARKWEB_MENTION = "darkweb_mention"
    BURNER_DETECTED = "burner_detected"
    CREDIT_RISK_HIGH = "credit_risk_high"


class WebMode(StrEnum):
    PERPETUAL = "perpetual"
    BOUNDED = "bounded"
    MANUAL = "manual"
    PAUSED = "paused"


class WealthBand(StrEnum):
    ULTRA_HNW = "ULTRA_HNW"
    HIGH_HNW = "HIGH_HNW"
    AFFLUENT = "AFFLUENT"
    MIDDLE = "MIDDLE"
    LOWER = "LOWER"
    STRESSED = "STRESSED"
    UNKNOWN = "UNKNOWN"


class BurnerTier(StrEnum):
    CONFIRMED = "CONFIRMED"
    LIKELY = "LIKELY"
    POSSIBLE = "POSSIBLE"
    CLEAN = "CLEAN"


class CreditRiskTier(StrEnum):
    DO_NOT_LEND = "DO_NOT_LEND"
    HIGH_RISK = "HIGH_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    LOW_RISK = "LOW_RISK"
    PREFERRED = "PREFERRED"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    CORROBORATED = "corroborated"
    VERIFIED = "verified"


# Score tiers for relationship strength
SCORE_TIERS = {
    RelationshipTier.CRITICAL: (0.80, 1.00),
    RelationshipTier.STRONG: (0.60, 0.79),
    RelationshipTier.MODERATE: (0.40, 0.59),
    RelationshipTier.WEAK: (0.20, 0.39),
    RelationshipTier.TENUOUS: (0.00, 0.19),
}

# Source reliability scores
SOURCE_RELIABILITY = {
    "government_registry": 0.95,
    "court_records": 0.92,
    "sanctions_list": 0.98,
    "linkedin_verified": 0.75,
    "whitepages": 0.65,
    "instagram_profile": 0.55,
    "twitter_bio": 0.50,
    "paste_site": 0.30,
    "darkweb_mention": 0.20,
}

# Freshness half-lives in hours
FRESHNESS_HALF_LIFE_HOURS = {
    "sanctions": 6,
    "breach_database": 24,
    "social_profile": 168,       # 7 days
    "social_post": 72,            # 3 days
    "phone_registration": 336,    # 14 days
    "employment": 1440,           # 60 days
    "property": 2160,             # 90 days
    "court_records": 720,         # 30 days
    "education": 8760,            # 365 days
}
```

- [ ] **Step 2.5: Create shared/__init__.py**

```python
# shared/__init__.py
```

- [ ] **Step 2.6: Run tests — expect pass**

```bash
pytest tests/test_shared/test_config.py -v
```

Expected: 3 tests PASSED

- [ ] **Step 2.7: Commit**

```bash
git add shared/config.py shared/constants.py shared/__init__.py tests/
git commit -m "feat: shared config and constants"
```

---

## Task 3: Database Engine

**Files:**
- Create: `shared/db.py`
- Create: `tests/test_shared/test_db.py`
- Create: `tests/conftest.py`

- [ ] **Step 3.1: Write failing test**

```python
# tests/test_shared/test_db.py
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from shared.db import get_session, engine


@pytest.mark.asyncio
async def test_engine_connects():
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_session_factory():
    async with get_session() as session:
        assert isinstance(session, AsyncSession)
```

- [ ] **Step 3.2: Run — expect ImportError**

```bash
pytest tests/test_shared/test_db.py -v
```

Expected: `ModuleNotFoundError: No module named 'shared.db'`

- [ ] **Step 3.3: Implement shared/db.py**

```python
# shared/db.py
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from shared.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_session_dep() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency."""
    async with get_session() as session:
        yield session
```

- [ ] **Step 3.4: Create tests/conftest.py**

```python
# tests/conftest.py
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text

TEST_DB_URL = "postgresql+asyncpg://lycan:lycan@localhost:5432/lycan_test"


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    """
    Each test gets a session wrapped in a SAVEPOINT. The outer transaction
    is never committed, so all test data is rolled back automatically.
    """
    async with test_engine.connect() as conn:
        await conn.begin()
        await conn.begin_nested()  # SAVEPOINT

        factory = async_sessionmaker(conn, expire_on_commit=False)
        async with factory() as session:
            yield session

        await conn.rollback()  # Roll back the outer transaction — cleans all test data
```

- [ ] **Step 3.5: Create test database**

```bash
docker compose exec postgres psql -U lycan -c "CREATE DATABASE lycan_test;"
docker compose exec postgres psql -U lycan -d lycan_test -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"; CREATE EXTENSION IF NOT EXISTS vector;"
```

- [ ] **Step 3.6: Run tests**

```bash
pytest tests/test_shared/test_db.py -v
```

Expected: 2 tests PASSED

- [ ] **Step 3.7: Commit**

```bash
git add shared/db.py tests/conftest.py tests/test_shared/test_db.py
git commit -m "feat: SQLAlchemy async engine + session factory"
```

---

## Task 4: ORM Models — Base + Core Tables

**Files:**
- Create: `shared/models/base.py`
- Create: `shared/models/__init__.py`
- Create: `shared/models/person.py`
- Create: `shared/models/identifier.py`
- Create: `shared/models/relationship.py`
- Create: `tests/test_shared/test_models.py`

- [ ] **Step 4.1: Write failing tests**

```python
# tests/test_shared/test_models.py
import pytest
import uuid
from shared.models.person import Person
from shared.models.identifier import Identifier
from shared.constants import IdentifierType


@pytest.mark.asyncio
async def test_create_person(db_session):
    person = Person(
        canonical_name="John Doe",
        confidence_score=0.85,
    )
    db_session.add(person)
    await db_session.flush()
    assert person.id is not None
    assert isinstance(person.id, uuid.UUID)


@pytest.mark.asyncio
async def test_create_identifier(db_session):
    person = Person(canonical_name="Jane Doe", confidence_score=0.70)
    db_session.add(person)
    await db_session.flush()

    identifier = Identifier(
        person_id=person.id,
        type=IdentifierType.PHONE,
        value="+27821234567",
        source="test",
    )
    db_session.add(identifier)
    await db_session.flush()
    assert identifier.id is not None


@pytest.mark.asyncio
async def test_person_has_quality_fields(db_session):
    person = Person(canonical_name="Test", confidence_score=0.5)
    assert hasattr(person, "data_quality")
```

- [ ] **Step 4.2: Run — expect ImportError**

```bash
pytest tests/test_shared/test_models.py -v
```

- [ ] **Step 4.3: Create shared/models/base.py**

```python
# shared/models/base.py
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DataQualityMixin:
    """Every persisted fact carries data quality metadata."""
    data_quality: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "freshness_score": 1.0,
            "source_reliability": 0.5,
            "corroboration_count": 1,
            "corroboration_score": 0.5,
            "conflict_flag": False,
            "verification_status": "unverified",
            "composite_quality": 0.5,
            "last_refreshed_at": None,
        },
    )
```

- [ ] **Step 4.4: Create shared/models/person.py**

```python
# shared/models/person.py
import uuid
from typing import Optional, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Float, Date, Text, ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, UUIDMixin, TimestampMixin, DataQualityMixin


class Person(Base, UUIDMixin, TimestampMixin, DataQualityMixin):
    __tablename__ = "persons"

    canonical_name: Mapped[str] = mapped_column(String(512), nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(256))
    last_name: Mapped[Optional[str]] = mapped_column(String(256))
    date_of_birth: Mapped[Optional[Any]] = mapped_column(Date)
    gender: Mapped[Optional[str]] = mapped_column(String(32))
    nationality: Mapped[Optional[str]] = mapped_column(String(3))
    country_of_residence: Mapped[Optional[str]] = mapped_column(String(3))
    city: Mapped[Optional[str]] = mapped_column(String(256))
    bio_text: Mapped[Optional[str]] = mapped_column(Text)
    profile_image_url: Mapped[Optional[str]] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String))
    embedding: Mapped[Optional[Any]] = mapped_column(Vector(768))

    # Relationships
    identifiers: Mapped[list["Identifier"]] = relationship(
        "Identifier", back_populates="person", lazy="selectin"
    )


class Alias(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "aliases"

    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    alias_name: Mapped[str] = mapped_column(String(512), nullable=False)
    alias_type: Mapped[str] = mapped_column(String(64))  # maiden, nickname, transliteration
    source: Mapped[str] = mapped_column(String(256), nullable=False)
```

- [ ] **Step 4.5: Create shared/models/identifier.py**

```python
# shared/models/identifier.py
import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base import Base, UUIDMixin, TimestampMixin, DataQualityMixin
from shared.constants import IdentifierType


class Identifier(Base, UUIDMixin, TimestampMixin, DataQualityMixin):
    __tablename__ = "identifiers"

    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    type: Mapped[IdentifierType] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    raw_value: Mapped[Optional[str]] = mapped_column(String(1024))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_method: Mapped[Optional[str]] = mapped_column(String(128))
    country_code: Mapped[Optional[str]] = mapped_column(String(3))
    carrier: Mapped[Optional[str]] = mapped_column(String(256))
    line_type: Mapped[Optional[str]] = mapped_column(String(32))  # mobile/landline/voip/toll_free
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Relationships
    person: Mapped["Person"] = relationship("Person", back_populates="identifiers")
```

- [ ] **Step 4.6: Create shared/models/relationship.py**

```python
# shared/models/relationship.py
import uuid
from typing import Optional, Any
from datetime import datetime

from sqlalchemy import String, Float, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, UUIDMixin, TimestampMixin, DataQualityMixin
from shared.constants import RelationshipType


class Relationship(Base, UUIDMixin, TimestampMixin, DataQualityMixin):
    __tablename__ = "relationships"

    person_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    person_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    rel_type: Mapped[RelationshipType] = mapped_column(String(64), nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[Optional[list[Any]]] = mapped_column(JSONB)
    bidirectional: Mapped[bool] = mapped_column(Boolean, default=True)
    score_trend: Mapped[Optional[str]] = mapped_column(String(16))  # rising/stable/declining
    last_scored_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class RelationshipScoreHistory(Base, UUIDMixin):
    __tablename__ = "relationship_score_history"

    relationship_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    old_score: Mapped[Optional[float]] = mapped_column(Float)
    new_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_delta: Mapped[Optional[float]] = mapped_column(Float)
    tier_before: Mapped[Optional[str]] = mapped_column(String(32))
    tier_after: Mapped[Optional[str]] = mapped_column(String(32))
    evidence_delta: Mapped[Optional[Any]] = mapped_column(JSONB)
    trigger_source: Mapped[str] = mapped_column(String(256), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4.7: Create shared/models/__init__.py**

```python
# shared/models/__init__.py
from shared.models.base import Base
from shared.models.person import Person, Alias
from shared.models.identifier import Identifier
from shared.models.relationship import Relationship, RelationshipScoreHistory

__all__ = [
    "Base",
    "Person", "Alias",
    "Identifier",
    "Relationship", "RelationshipScoreHistory",
]
```

- [ ] **Step 4.8: Run tests**

```bash
pytest tests/test_shared/test_models.py -v
```

Expected: 3 tests PASSED (will fail until migrations run — see Task 6)

- [ ] **Step 4.9: Commit**

```bash
git add shared/models/ tests/test_shared/test_models.py
git commit -m "feat: core ORM models (person, identifier, relationship)"
```

---

## Task 5: Remaining ORM Models

**Files:**
- Create: `shared/models/social_profile.py`
- Create: `shared/models/web.py`
- Create: `shared/models/crawl.py`
- Create: `shared/models/alert.py`
- Create: `shared/models/address.py`
- Create: `shared/models/employment.py`
- Create: `shared/models/education.py`
- Create: `shared/models/breach.py`
- Create: `shared/models/media.py`
- Create: `shared/models/watchlist.py`
- Create: `shared/models/behavioural.py`
- Create: `shared/models/burner.py`
- Create: `shared/models/darkweb.py`
- Create: `shared/models/credit_risk.py`
- Create: `shared/models/wealth.py`
- Create: `shared/models/quality.py`

- [ ] **Step 5.1: Create shared/models/social_profile.py**

```python
# shared/models/social_profile.py
import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, Integer, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, UUIDMixin, TimestampMixin, DataQualityMixin


class SocialProfile(Base, UUIDMixin, TimestampMixin, DataQualityMixin):
    __tablename__ = "social_profiles"

    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)  # instagram, twitter, etc.
    username: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(512))
    bio: Mapped[Optional[str]] = mapped_column(Text)
    follower_count: Mapped[Optional[int]] = mapped_column(Integer)
    following_count: Mapped[Optional[int]] = mapped_column(Integer)
    post_count: Mapped[Optional[int]] = mapped_column(Integer)
    profile_pic_url: Mapped[Optional[str]] = mapped_column(Text)
    external_url: Mapped[Optional[str]] = mapped_column(Text)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    profile_url: Mapped[Optional[str]] = mapped_column(Text)
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 5.2: Create shared/models/web.py**

```python
# shared/models/web.py
import uuid
from typing import Optional, Any
from datetime import datetime

from sqlalchemy import String, Integer, Float, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, UUIDMixin, TimestampMixin
from shared.constants import WebMode


class Web(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "webs"

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    seed_person_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[WebMode] = mapped_column(String(32), nullable=False, default=WebMode.PERPETUAL)
    total_persons: Mapped[int] = mapped_column(Integer, default=0)
    total_relationships: Mapped[int] = mapped_column(Integer, default=0)
    max_depth_reached: Mapped[int] = mapped_column(Integer, default=0)
    avg_relationship_score: Mapped[Optional[float]] = mapped_column(Float)
    growth_rate_24h: Mapped[Optional[float]] = mapped_column(Float)
    merged_from: Mapped[Optional[list[uuid.UUID]]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_expansion_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class WebMembership(Base, TimestampMixin):
    __tablename__ = "web_memberships"
    __table_args__ = ({"schema": None},)

    web_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    hop_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_expanded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 5.3: Create shared/models/crawl.py**

```python
# shared/models/crawl.py
import uuid
from typing import Optional, Any
from datetime import datetime

from sqlalchemy import String, Integer, Float, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, UUIDMixin, TimestampMixin


class CrawlJob(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "crawl_jobs"

    web_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    person_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    seed_type: Mapped[str] = mapped_column(String(64), nullable=False)
    seed_value: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    depth: Mapped[int] = mapped_column(Integer, default=0)
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0)
    identifiers_found: Mapped[int] = mapped_column(Integer, default=0)
    persons_resolved: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error: Mapped[Optional[str]] = mapped_column(Text)


class CrawlLog(Base, UUIDMixin):
    __tablename__ = "crawl_logs"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer)
    proxy_used: Mapped[Optional[str]] = mapped_column(String(256))
    tor_circuit_id: Mapped[Optional[str]] = mapped_column(String(64))
    spider_name: Mapped[Optional[str]] = mapped_column(String(128))
    error: Mapped[Optional[str]] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DataSource(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "data_sources"

    name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(String(64))  # scrape, api, open_source
    base_url: Mapped[Optional[str]] = mapped_column(Text)
    reliability_score: Mapped[float] = mapped_column(Float, default=0.5)
    rate_limit_rps: Mapped[Optional[float]] = mapped_column(Float)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_enabled: Mapped[bool] = mapped_column(default=True)
    metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
```

- [ ] **Step 5.4: Create shared/models/alert.py**

```python
# shared/models/alert.py
import uuid
from typing import Optional, Any
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, UUIDMixin
from shared.constants import AlertSeverity, AlertType


class Alert(Base, UUIDMixin):
    __tablename__ = "alerts"

    web_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    person_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    alert_type: Mapped[AlertType] = mapped_column(String(64), nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 5.5: Create remaining models (address, employment, education, breach, media, watchlist, behavioural)**

```python
# shared/models/address.py
import uuid
from typing import Optional
from sqlalchemy import String, Boolean, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin, TimestampMixin, DataQualityMixin

class Address(Base, UUIDMixin, TimestampMixin, DataQualityMixin):
    __tablename__ = "addresses"
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    address_type: Mapped[str] = mapped_column(String(32))  # home/work/mailing
    street: Mapped[Optional[str]] = mapped_column(String(512))
    city: Mapped[Optional[str]] = mapped_column(String(256))
    state: Mapped[Optional[str]] = mapped_column(String(256))
    postal_code: Mapped[Optional[str]] = mapped_column(String(32))
    country: Mapped[Optional[str]] = mapped_column(String(3))
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False)
```

```python
# shared/models/employment.py
import uuid
from typing import Optional, Any
from datetime import date
from sqlalchemy import String, Boolean, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin, TimestampMixin, DataQualityMixin

class EmploymentHistory(Base, UUIDMixin, TimestampMixin, DataQualityMixin):
    __tablename__ = "employment_history"
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(256))
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(512))
```

```python
# shared/models/education.py
import uuid
from typing import Optional
from sqlalchemy import String, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin, TimestampMixin, DataQualityMixin

class Education(Base, UUIDMixin, TimestampMixin, DataQualityMixin):
    __tablename__ = "education"
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    institution: Mapped[str] = mapped_column(String(512), nullable=False)
    degree: Mapped[Optional[str]] = mapped_column(String(256))
    field: Mapped[Optional[str]] = mapped_column(String(256))
    graduation_year: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(256), nullable=False)
```

```python
# shared/models/breach.py
import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin, TimestampMixin

class BreachRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "breach_records"
    identifier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    breach_name: Mapped[str] = mapped_column(String(256), nullable=False)
    breach_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    data_classes: Mapped[Optional[str]] = mapped_column(String(512))  # comma-separated
    source: Mapped[str] = mapped_column(String(256), nullable=False)
```

```python
# shared/models/media.py
import uuid
from typing import Optional
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin, TimestampMixin

class MediaAsset(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "media_assets"
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32))  # profile_photo, post_image
    platform: Mapped[Optional[str]] = mapped_column(String(64))
    perceptual_hash: Mapped[Optional[str]] = mapped_column(String(64))
    local_path: Mapped[Optional[str]] = mapped_column(Text)
```

```python
# shared/models/watchlist.py
import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import String, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin, TimestampMixin

class WatchlistMatch(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "watchlist_matches"
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    list_name: Mapped[str] = mapped_column(String(256), nullable=False)  # OFAC, UN, EU, HMT, PEP
    match_name: Mapped[str] = mapped_column(String(512), nullable=False)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    match_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[Optional[str]] = mapped_column(String(512))
```

```python
# shared/models/behavioural.py
import uuid
from typing import Optional, Any
from datetime import datetime
from sqlalchemy import String, Boolean, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin, TimestampMixin

class BehaviouralProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "behavioural_profiles"
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    is_gambler: Mapped[bool] = mapped_column(Boolean, default=False)
    gambling_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_crypto_trader: Mapped[bool] = mapped_column(Boolean, default=False)
    is_high_spender: Mapped[bool] = mapped_column(Boolean, default=False)
    is_pep: Mapped[bool] = mapped_column(Boolean, default=False)
    is_adult_content: Mapped[bool] = mapped_column(Boolean, default=False)
    is_substance_user: Mapped[bool] = mapped_column(Boolean, default=False)
    # Criminal signals
    is_drug_dealer: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fraud_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    is_money_launderer: Mapped[bool] = mapped_column(Boolean, default=False)
    is_weapons_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    is_financial_crime_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_category: Mapped[str] = mapped_column(String(32), default="low")
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_profiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class BehaviouralSignal(Base, UUIDMixin):
    __tablename__ = "behavioural_signals"
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_platform: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_value: Mapped[str] = mapped_column(String(2048), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 5.6: Create new module models**

```python
# shared/models/burner.py
import uuid
from typing import Optional, Any
from datetime import datetime
from sqlalchemy import String, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin
from shared.constants import BurnerTier

class BurnerAssessment(Base, UUIDMixin):
    __tablename__ = "burner_assessments"
    identifier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    burner_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    burner_tier: Mapped[BurnerTier] = mapped_column(String(32), nullable=False, default=BurnerTier.CLEAN)
    line_type: Mapped[Optional[str]] = mapped_column(String(32))
    carrier_name: Mapped[Optional[str]] = mapped_column(String(256))
    carrier_category: Mapped[Optional[str]] = mapped_column(String(64))
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

```python
# shared/models/darkweb.py
import uuid
from typing import Optional, Any
from datetime import datetime
from sqlalchemy import String, Float, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin

class DarkwebMention(Base, UUIDMixin):
    __tablename__ = "darkweb_mentions"
    identifier_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), index=True)
    person_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), index=True)
    source_url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    mention_context: Mapped[Optional[str]] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="MEDIUM")
    darkweb_score: Mapped[float] = mapped_column(Float, default=0.0)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class CryptoWallet(Base, UUIDMixin):
    __tablename__ = "crypto_wallets"
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)  # BTC, ETH, USDT, etc.
    first_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    total_volume_usd: Mapped[Optional[float]] = mapped_column(Float)
    mixer_exposure: Mapped[bool] = mapped_column(default=False)
    exchange_flags: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

class CryptoTransaction(Base, UUIDMixin):
    __tablename__ = "crypto_transactions"
    wallet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    tx_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    counterparty_address: Mapped[Optional[str]] = mapped_column(String(256))
    amount_usd: Mapped[Optional[float]] = mapped_column(Float)
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    risk_flags: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
```

```python
# shared/models/credit_risk.py
import uuid
from typing import Optional, Any
from datetime import datetime
from sqlalchemy import String, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin
from shared.constants import CreditRiskTier

class CreditRiskAssessment(Base, UUIDMixin):
    __tablename__ = "credit_risk_assessments"
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tier: Mapped[CreditRiskTier] = mapped_column(String(32), nullable=False)
    signal_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
```

```python
# shared/models/wealth.py
import uuid
from typing import Optional, Any
from datetime import datetime
from sqlalchemy import String, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin
from shared.constants import WealthBand

class WealthAssessment(Base, UUIDMixin):
    __tablename__ = "wealth_assessments"
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    wealth_band: Mapped[WealthBand] = mapped_column(String(32), nullable=False, default=WealthBand.UNKNOWN)
    income_estimate_usd_annual: Mapped[Optional[float]] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    signal_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

```python
# shared/models/quality.py
import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import String, Float, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, UUIDMixin

class DataQualityLog(Base, UUIDMixin):
    __tablename__ = "data_quality_log"
    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    quality_before: Mapped[Optional[float]] = mapped_column(Float)
    quality_after: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(256), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class FreshnessQueue(Base, UUIDMixin):
    __tablename__ = "freshness_queue"
    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(256), nullable=False)
    next_refresh_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 5.7: Update shared/models/__init__.py**

```python
# shared/models/__init__.py
from shared.models.base import Base
from shared.models.person import Person, Alias
from shared.models.identifier import Identifier
from shared.models.relationship import Relationship, RelationshipScoreHistory
from shared.models.social_profile import SocialProfile
from shared.models.web import Web, WebMembership
from shared.models.crawl import CrawlJob, CrawlLog, DataSource
from shared.models.alert import Alert
from shared.models.address import Address
from shared.models.employment import EmploymentHistory
from shared.models.education import Education
from shared.models.breach import BreachRecord
from shared.models.media import MediaAsset
from shared.models.watchlist import WatchlistMatch
from shared.models.behavioural import BehaviouralProfile, BehaviouralSignal
from shared.models.burner import BurnerAssessment
from shared.models.darkweb import DarkwebMention, CryptoWallet, CryptoTransaction
from shared.models.credit_risk import CreditRiskAssessment
from shared.models.wealth import WealthAssessment
from shared.models.quality import DataQualityLog, FreshnessQueue

__all__ = [
    "Base",
    "Person", "Alias",
    "Identifier",
    "Relationship", "RelationshipScoreHistory",
    "SocialProfile",
    "Web", "WebMembership",
    "CrawlJob", "CrawlLog", "DataSource",
    "Alert",
    "Address",
    "EmploymentHistory",
    "Education",
    "BreachRecord",
    "MediaAsset",
    "WatchlistMatch",
    "BehaviouralProfile", "BehaviouralSignal",
    "BurnerAssessment",
    "DarkwebMention", "CryptoWallet", "CryptoTransaction",
    "CreditRiskAssessment",
    "WealthAssessment",
    "DataQualityLog", "FreshnessQueue",
]
```

- [ ] **Step 5.8: Commit**

```bash
git add shared/models/
git commit -m "feat: complete ORM model layer — all 28 tables"
```

---

## Task 6: Alembic Migrations

**Files:**
- Create: `migrations/alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/versions/001_initial_schema.py`

- [ ] **Step 6.1: Initialise Alembic**

```bash
alembic init migrations
```

- [ ] **Step 6.2: Update migrations/env.py**

```python
# migrations/env.py
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from shared.config import settings
from shared.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 6.3: Write failing migration test**

```python
# tests/test_migrations.py
import subprocess
import pytest

def test_migrations_run_clean():
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Migration failed: {result.stderr}"

def test_migrations_can_downgrade():
    result = subprocess.run(
        ["alembic", "downgrade", "base"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"Downgrade failed: {result.stderr}"
```

- [ ] **Step 6.4: Autogenerate migration**

```bash
alembic revision --autogenerate -m "initial schema"
```

Review the generated file — verify all 28 tables are present.

- [ ] **Step 6.5: Run migration**

```bash
alembic upgrade head
```

Expected: All tables created. Check in psql:
```bash
docker compose exec postgres psql -U lycan -d lycan -c "\dt"
```

- [ ] **Step 6.6: Run migration test**

```bash
pytest tests/test_migrations.py -v
```

Expected: 2 tests PASSED

- [ ] **Step 6.7: Run model tests**

```bash
pytest tests/test_shared/test_models.py -v
```

Expected: All PASSED (DB now has schema)

- [ ] **Step 6.8: Commit**

```bash
git add migrations/
git commit -m "feat: Alembic migration — complete initial schema (28 tables)"
```

---

## Task 7: Event Bus (Dragonfly pub/sub)

**Files:**
- Create: `shared/events.py`
- Create: `tests/test_shared/test_events.py`

- [ ] **Step 7.1: Write failing test**

```python
# tests/test_shared/test_events.py
import pytest
import asyncio
from shared.events import EventBus, Event


@pytest.mark.asyncio
async def test_publish_subscribe():
    bus = EventBus()
    received = []

    async def handler(event: Event):
        received.append(event)

    await bus.subscribe("person.resolved", handler)
    await bus.publish("person.resolved", {"person_id": "123", "name": "Test"})
    await asyncio.sleep(0.1)
    assert len(received) == 1
    assert received[0].type == "person.resolved"
    assert received[0].data["name"] == "Test"


@pytest.mark.asyncio
async def test_multiple_subscribers():
    bus = EventBus()
    calls = []

    await bus.subscribe("test.event", lambda e: calls.append(1))
    await bus.subscribe("test.event", lambda e: calls.append(2))
    await bus.publish("test.event", {})
    await asyncio.sleep(0.1)
    assert len(calls) == 2
```

- [ ] **Step 7.2: Run — expect ImportError**

```bash
pytest tests/test_shared/test_events.py -v
```

- [ ] **Step 7.3: Implement shared/events.py**

```python
# shared/events.py
import json
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable
import redis.asyncio as aioredis

from shared.config import settings


@dataclass
class Event:
    type: str
    data: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "data": self.data, "timestamp": self.timestamp})

    @classmethod
    def from_json(cls, raw: str) -> "Event":
        d = json.loads(raw)
        return cls(type=d["type"], data=d["data"], timestamp=d.get("timestamp", ""))


EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self):
        self._client = aioredis.from_url(settings.dragonfly_url, decode_responses=True)
        self._handlers: dict[str, list[EventHandler]] = {}
        self._pubsub = None
        self._listener_task = None

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        event = Event(type=event_type, data=data)
        await self._client.publish(f"lycan:{event_type}", event.to_json())

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        await self._ensure_listener()
        if self._pubsub:
            await self._pubsub.subscribe(f"lycan:{event_type}")

    async def _ensure_listener(self):
        if self._listener_task is None or self._listener_task.done():
            self._pubsub = self._client.pubsub()
            self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self):
        async for message in self._pubsub.listen():
            if message["type"] == "message":
                channel = message["channel"].replace("lycan:", "")
                event = Event.from_json(message["data"])
                for handler in self._handlers.get(channel, []):
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event)
                        else:
                            handler(event)
                    except Exception as e:
                        print(f"Event handler error: {e}")

    async def close(self):
        if self._listener_task:
            self._listener_task.cancel()
        await self._client.aclose()


# Module-level singleton
_bus: EventBus | None = None

def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
```

- [ ] **Step 7.4: Run tests**

```bash
pytest tests/test_shared/test_events.py -v
```

Expected: 2 tests PASSED

- [ ] **Step 7.5: Commit**

```bash
git add shared/events.py tests/test_shared/test_events.py
git commit -m "feat: Dragonfly pub/sub event bus"
```

---

## Task 8: Tor Circuit Manager

**Files:**
- Create: `shared/tor.py`
- Create: `shared/scrapy_middleware.py`
- Create: `tests/test_shared/test_tor.py`

- [ ] **Step 8.1: Write failing tests**

```python
# tests/test_shared/test_tor.py
import pytest
from unittest.mock import MagicMock, patch
from shared.tor import TorManager, tor_playwright_args


def test_tor_manager_socks_ports():
    assert TorManager(instance=1).get_socks_port() == 9050
    assert TorManager(instance=2).get_socks_port() == 9052
    assert TorManager(instance=3).get_socks_port() == 9054


def test_playwright_args_correct_port():
    args = tor_playwright_args(instance=1)
    assert "--proxy-server=socks5://127.0.0.1:9050" in args

    args = tor_playwright_args(instance=2)
    assert "--proxy-server=socks5://127.0.0.1:9052" in args


def test_proxy_override_env(monkeypatch):
    import shared.config as cfg
    monkeypatch.setattr(cfg.settings, "proxy_override", "socks5://myproxy:1080")
    from shared.tor import tor_playwright_args
    args = tor_playwright_args(instance=1)
    assert "socks5://myproxy:1080" in args


@patch("shared.tor.Controller")
def test_new_circuit(mock_controller_class):
    mock_controller = MagicMock()
    mock_controller_class.from_port.return_value.__enter__ = MagicMock(return_value=mock_controller)
    mock_controller_class.from_port.return_value.__exit__ = MagicMock(return_value=False)

    manager = TorManager(instance=1)
    manager.new_circuit()
    mock_controller.signal.assert_called_once()
```

- [ ] **Step 8.2: Implement shared/tor.py**

```python
# shared/tor.py
from stem import Signal
from stem.control import Controller
import requests
import socks
import socket

from shared.config import settings


INSTANCE_CONFIG = {
    1: {"socks_port": 9050, "control_port": 9051},
    2: {"socks_port": 9052, "control_port": 9053},
    3: {"socks_port": 9054, "control_port": 9055},
}


class TorManager:
    def __init__(self, instance: int = 1):
        if instance not in INSTANCE_CONFIG:
            raise ValueError(f"Tor instance must be 1, 2, or 3. Got {instance}")
        self._instance = instance
        self._cfg = INSTANCE_CONFIG[instance]

    def get_socks_port(self) -> int:
        return self._cfg["socks_port"]

    def get_control_port(self) -> int:
        return self._cfg["control_port"]

    def new_circuit(self) -> None:
        """Request a new Tor circuit (new exit node)."""
        with Controller.from_port(port=self._cfg["control_port"]) as controller:
            controller.authenticate(password=settings.tor_control_password)
            controller.signal(Signal.NEWNYM)

    def get_exit_country(self) -> str:
        """Return the two-letter country code of the current exit node."""
        try:
            session = self.create_requests_session()
            resp = session.get("https://api.country.is/", timeout=10)
            return resp.json().get("country", "XX")
        except Exception:
            return "XX"

    def check_connectivity(self) -> bool:
        """Verify the Tor circuit is working."""
        try:
            session = self.create_requests_session()
            resp = session.get("https://check.torproject.org/api/ip", timeout=10)
            return resp.json().get("IsTor", False)
        except Exception:
            return False

    def create_requests_session(self) -> requests.Session:
        """Create a requests Session routed through this Tor instance."""
        session = requests.Session()
        proxy_url = _get_proxy_url(self._cfg["socks_port"])
        session.proxies = {"http": proxy_url, "https": proxy_url}
        return session


def _get_proxy_url(socks_port: int) -> str:
    if settings.proxy_override:
        return settings.proxy_override
    return f"socks5h://127.0.0.1:{socks_port}"


def tor_session(instance: int = 1) -> requests.Session:
    """Return a requests Session routed through the given Tor instance."""
    return TorManager(instance=instance).create_requests_session()


def tor_playwright_args(instance: int = 1) -> list[str]:
    """Return Playwright launch args to route through the given Tor instance."""
    if settings.proxy_override:
        proxy_url = settings.proxy_override
    else:
        socks_port = INSTANCE_CONFIG[instance]["socks_port"]
        proxy_url = f"socks5://127.0.0.1:{socks_port}"
    return [f"--proxy-server={proxy_url}"]
```

- [ ] **Step 8.3: Create shared/scrapy_middleware.py**

```python
# shared/scrapy_middleware.py
"""
Scrapy downloader middleware: routes all requests through Tor.
Add to Scrapy settings:
    DOWNLOADER_MIDDLEWARES = {
        'shared.scrapy_middleware.TorProxyMiddleware': 610,
    }
"""
from scrapy.exceptions import NotConfigured
from scrapy import signals
from shared.tor import TorManager


class TorProxyMiddleware:
    def __init__(self, tor_instance: int = 2):
        self._manager = TorManager(instance=tor_instance)
        socks_port = self._manager.get_socks_port()
        self._proxy = f"socks5h://127.0.0.1:{socks_port}"

    @classmethod
    def from_crawler(cls, crawler):
        tor_instance = crawler.settings.getint("TOR_INSTANCE", 2)
        return cls(tor_instance=tor_instance)

    def process_request(self, request, spider):
        request.meta["proxy"] = self._proxy

    def process_response(self, request, response, spider):
        if response.status in (429, 403):
            self._manager.new_circuit()
        return response

    def process_exception(self, request, exception, spider):
        self._manager.new_circuit()
        return None
```

- [ ] **Step 8.4: Run tests (mocked — no live Tor needed)**

```bash
pytest tests/test_shared/test_tor.py -v
```

Expected: 4 tests PASSED

- [ ] **Step 8.5: Commit**

```bash
git add shared/tor.py shared/scrapy_middleware.py tests/test_shared/test_tor.py
git commit -m "feat: Tor circuit manager + Scrapy middleware"
```

---

## Task 9: Data Quality Engine

**Files:**
- Create: `shared/data_quality.py`
- Create: `shared/freshness.py`
- Create: `tests/test_shared/test_data_quality.py`

- [ ] **Step 9.1: Write failing tests**

```python
# tests/test_shared/test_data_quality.py
import pytest
from shared.data_quality import compute_composite_quality, update_quality
from shared.freshness import compute_freshness, hours_since


def test_composite_quality_calculation():
    quality = compute_composite_quality(
        freshness_score=0.8,
        source_reliability=0.75,
        corroboration_count=2,
        conflict_flag=False,
    )
    assert 0.0 <= quality <= 1.0
    assert quality > 0.5  # should be decent quality


def test_conflict_lowers_quality():
    without_conflict = compute_composite_quality(0.8, 0.75, 2, False)
    with_conflict = compute_composite_quality(0.8, 0.75, 2, True)
    assert with_conflict < without_conflict


def test_freshness_decay():
    score = compute_freshness(hours_ago=168, half_life_hours=168)  # exactly 1 half-life
    assert abs(score - 0.5) < 0.01  # should be ~0.5


def test_freshness_recent():
    score = compute_freshness(hours_ago=0, half_life_hours=168)
    assert score == 1.0


def test_corroboration_boosts_quality():
    single = compute_composite_quality(0.7, 0.6, 1, False)
    triple = compute_composite_quality(0.7, 0.6, 3, False)
    assert triple > single
```

- [ ] **Step 9.2: Implement shared/freshness.py**

```python
# shared/freshness.py
import math
from datetime import datetime, timezone
from shared.constants import FRESHNESS_HALF_LIFE_HOURS


def compute_freshness(hours_ago: float, half_life_hours: float) -> float:
    """
    Exponential decay: score = 2^(-t/half_life)
    Returns 1.0 when hours_ago=0, ~0.5 at half_life, ~0 as hours_ago → ∞
    """
    if hours_ago <= 0:
        return 1.0
    return math.pow(2, -(hours_ago / half_life_hours))


def hours_since(dt: datetime | None) -> float:
    """Return hours elapsed since a datetime. Returns a large number if None."""
    if dt is None:
        return 8760.0  # default to 1 year stale
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    return delta.total_seconds() / 3600


def freshness_for_source(source_type: str, last_scraped_at: datetime | None) -> float:
    """Compute freshness score for a given source type."""
    half_life = FRESHNESS_HALF_LIFE_HOURS.get(source_type, 720)
    elapsed = hours_since(last_scraped_at)
    return compute_freshness(elapsed, half_life)


def next_refresh_hours(source_type: str, current_freshness: float, threshold: float = 0.4) -> float:
    """How many hours until this source drops below the freshness threshold?"""
    half_life = FRESHNESS_HALF_LIFE_HOURS.get(source_type, 720)
    if current_freshness <= threshold:
        return 0.0
    # Solve: threshold = current * 2^(-t/half_life) for t
    return -half_life * math.log2(threshold / current_freshness)
```

- [ ] **Step 9.3: Implement shared/data_quality.py**

```python
# shared/data_quality.py
from typing import Any
from shared.constants import SOURCE_RELIABILITY, FRESHNESS_HALF_LIFE_HOURS
from shared.freshness import freshness_for_source, hours_since


def compute_composite_quality(
    freshness_score: float,
    source_reliability: float,
    corroboration_count: int,
    conflict_flag: bool,
) -> float:
    """
    Composite quality = weighted combination of all dimensions.
    Range: 0.0 – 1.0
    """
    # Corroboration bonus: log scale, caps out around 0.95 with 5+ sources
    import math
    corroboration_bonus = min(0.15, 0.05 * math.log1p(corroboration_count))
    corroboration_score = min(1.0, source_reliability + corroboration_bonus)

    # Conflict penalty
    conflict_penalty = 0.20 if conflict_flag else 0.0

    composite = (
        freshness_score * 0.35
        + corroboration_score * 0.45
        + (1.0 - conflict_penalty) * 0.20
    )
    return max(0.0, min(1.0, composite))


def make_quality_dict(
    source_type: str,
    source: str,
    verification_status: str = "unverified",
    corroboration_count: int = 1,
    conflict_flag: bool = False,
    last_refreshed_at=None,
) -> dict[str, Any]:
    """Create a fresh DataQuality JSONB dict for a new record."""
    freshness = freshness_for_source(source_type, last_refreshed_at)
    reliability = SOURCE_RELIABILITY.get(source, 0.5)
    composite = compute_composite_quality(freshness, reliability, corroboration_count, conflict_flag)

    return {
        "freshness_score": freshness,
        "source_reliability": reliability,
        "corroboration_count": corroboration_count,
        "corroboration_score": min(1.0, reliability + 0.05 * (corroboration_count - 1)),
        "conflict_flag": conflict_flag,
        "verification_status": verification_status,
        "composite_quality": composite,
        "last_refreshed_at": last_refreshed_at.isoformat() if last_refreshed_at else None,
    }


def update_quality(existing: dict[str, Any], new_source: str, source_type: str) -> dict[str, Any]:
    """Update quality dict when a new source corroborates an existing fact."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    corroboration_count = existing.get("corroboration_count", 1) + 1
    new_reliability = SOURCE_RELIABILITY.get(new_source, 0.5)
    avg_reliability = (existing.get("source_reliability", 0.5) + new_reliability) / 2
    freshness = freshness_for_source(source_type, now)

    updated = existing.copy()
    updated["corroboration_count"] = corroboration_count
    updated["source_reliability"] = avg_reliability
    updated["freshness_score"] = freshness
    updated["last_refreshed_at"] = now.isoformat()
    updated["composite_quality"] = compute_composite_quality(
        freshness, avg_reliability, corroboration_count, existing.get("conflict_flag", False)
    )
    return updated
```

- [ ] **Step 9.4: Run tests**

```bash
pytest tests/test_shared/test_data_quality.py -v
```

Expected: 5 tests PASSED

- [ ] **Step 9.5: Commit**

```bash
git add shared/data_quality.py shared/freshness.py tests/test_shared/test_data_quality.py
git commit -m "feat: data quality engine + freshness decay functions"
```

---

## Task 10: Shared Utilities + Schemas

**Files:**
- Create: `shared/utils/phone.py`
- Create: `shared/utils/email.py`
- Create: `shared/utils/social.py`
- Create: `shared/utils/scoring.py`
- Create: `shared/utils/__init__.py`
- Create: `shared/schemas/seed.py`
- Create: `shared/schemas/person.py`
- Create: `shared/schemas/relationship.py` — RelationshipResponse, ScoreBreakdown
- Create: `shared/schemas/web.py`
- Create: `shared/schemas/alert.py`
- Create: `shared/schemas/__init__.py`

- [ ] **Step 10.1: Create shared/utils/phone.py**

```python
# shared/utils/phone.py
import phonenumbers
from phonenumbers import NumberParseException
from typing import Optional


def normalise_phone(raw: str, default_region: str = "ZA") -> Optional[str]:
    """Parse and normalise a phone number to E.164 format. Returns None if invalid."""
    try:
        parsed = phonenumbers.parse(raw, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except NumberParseException:
        pass
    return None


def get_line_type(number: str) -> str:
    """Return line type string: mobile, landline, voip, toll_free, unknown."""
    try:
        parsed = phonenumbers.parse(number, None)
        nt = phonenumbers.number_type(parsed)
        mapping = {
            phonenumbers.PhoneNumberType.MOBILE: "mobile",
            phonenumbers.PhoneNumberType.FIXED_LINE: "landline",
            phonenumbers.PhoneNumberType.VOIP: "voip",
            phonenumbers.PhoneNumberType.TOLL_FREE: "toll_free",
            phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "mobile",
        }
        return mapping.get(nt, "unknown")
    except Exception:
        return "unknown"


def get_country_code(number: str) -> Optional[str]:
    """Return ISO 3166-1 alpha-2 country code for a phone number."""
    try:
        parsed = phonenumbers.parse(number, None)
        region = phonenumbers.region_code_for_number(parsed)
        return region
    except Exception:
        return None
```

- [ ] **Step 10.2: Create shared/utils/email.py**

```python
# shared/utils/email.py
import re
from typing import Optional


EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def normalise_email(raw: str) -> Optional[str]:
    """Lowercase and strip whitespace. Returns None if not a valid email format."""
    cleaned = raw.strip().lower()
    if EMAIL_RE.match(cleaned):
        return cleaned
    return None


def extract_domain(email: str) -> Optional[str]:
    """Extract the domain part of an email address."""
    try:
        return email.split("@")[1].lower()
    except (IndexError, AttributeError):
        return None
```

- [ ] **Step 10.3: Create shared/utils/social.py**

```python
# shared/utils/social.py
import re
from typing import Optional


def normalise_handle(raw: str) -> str:
    """Strip leading @ and whitespace from a social handle."""
    return raw.strip().lstrip("@").strip()


def extract_instagram_username(raw: str) -> Optional[str]:
    """Extract Instagram username from URL or handle."""
    patterns = [
        r"instagram\.com/([A-Za-z0-9_.]+)/?",
        r"^@?([A-Za-z0-9_.]+)$",
    ]
    for pattern in patterns:
        m = re.search(pattern, raw.strip())
        if m:
            return m.group(1).lower()
    return None


def extract_twitter_username(raw: str) -> Optional[str]:
    patterns = [
        r"(?:twitter|x)\.com/([A-Za-z0-9_]+)/?",
        r"^@?([A-Za-z0-9_]+)$",
    ]
    for pattern in patterns:
        m = re.search(pattern, raw.strip())
        if m:
            return m.group(1).lower()
    return None


def extract_linkedin_slug(raw: str) -> Optional[str]:
    m = re.search(r"linkedin\.com/in/([A-Za-z0-9\-]+)/?", raw.strip())
    return m.group(1).lower() if m else None


def extract_telegram_username(raw: str) -> Optional[str]:
    patterns = [
        r"t\.me/([A-Za-z0-9_]+)/?",
        r"^@?([A-Za-z0-9_]+)$",
    ]
    for pattern in patterns:
        m = re.search(pattern, raw.strip())
        if m:
            return m.group(1).lower()
    return None
```

- [ ] **Step 10.4: Create shared/utils/scoring.py**

```python
# shared/utils/scoring.py
from shared.constants import RelationshipTier, SCORE_TIERS, CreditRiskTier, BurnerTier


def score_to_relationship_tier(score: float) -> RelationshipTier:
    for tier, (low, high) in SCORE_TIERS.items():
        if low <= score <= high:
            return tier
    return RelationshipTier.TENUOUS


def score_to_credit_tier(score: float) -> CreditRiskTier:
    if score >= 0.80:
        return CreditRiskTier.DO_NOT_LEND
    elif score >= 0.60:
        return CreditRiskTier.HIGH_RISK
    elif score >= 0.40:
        return CreditRiskTier.MEDIUM_RISK
    elif score >= 0.20:
        return CreditRiskTier.LOW_RISK
    return CreditRiskTier.PREFERRED


def score_to_burner_tier(score: float) -> BurnerTier:
    if score >= 0.70:
        return BurnerTier.CONFIRMED
    elif score >= 0.40:
        return BurnerTier.LIKELY
    elif score >= 0.20:
        return BurnerTier.POSSIBLE
    return BurnerTier.CLEAN


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))
```

- [ ] **Step 10.5: Create shared/utils/__init__.py**

```python
# shared/utils/__init__.py
```

- [ ] **Step 10.6: Create Pydantic schemas**

```python
# shared/schemas/seed.py
from pydantic import BaseModel
from shared.constants import SeedType


class SeedInput(BaseModel):
    raw: str
    detected_type: SeedType | None = None
    normalised_value: str | None = None


# shared/schemas/person.py
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class PersonSummary(BaseModel):
    id: UUID
    canonical_name: str
    confidence_score: float
    risk_score: float
    tags: list[str] = []
    updated_at: datetime

    model_config = {"from_attributes": True}


class PersonResponse(PersonSummary):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    nationality: Optional[str] = None
    country_of_residence: Optional[str] = None
    city: Optional[str] = None
    bio_text: Optional[str] = None
    profile_image_url: Optional[str] = None


# shared/schemas/web.py
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, Any
from shared.constants import WebMode


class WebConfig(BaseModel):
    mode: WebMode = WebMode.PERPETUAL
    max_persons: int = 10000
    max_depth: Optional[int] = None
    max_persons_per_hop: int = 50
    min_expansion_threshold: float = 0.25
    daily_api_budget_usd: float = 0.0
    max_concurrent_crawlers: int = 5
    auto_merge_webs: bool = True


class WebResponse(BaseModel):
    id: UUID
    name: str
    mode: WebMode
    total_persons: int
    total_relationships: int
    config: dict[str, Any]
    created_at: datetime
    last_expansion_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# shared/schemas/alert.py
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, Any
from shared.constants import AlertSeverity, AlertType


class AlertResponse(BaseModel):
    id: UUID
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    details: Optional[dict[str, Any]] = None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 10.7: Create shared/schemas/__init__.py**

```python
# shared/schemas/relationship.py
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, Any
from shared.constants import RelationshipType, RelationshipTier


class ScoreBreakdown(BaseModel):
    evidence_type: str
    score: float
    weight: float
    source: str


class RelationshipResponse(BaseModel):
    id: UUID
    person_a_id: UUID
    person_b_id: UUID
    rel_type: RelationshipType
    strength: float
    tier: RelationshipTier
    score_trend: Optional[str] = None
    evidence: Optional[list[Any]] = None
    last_scored_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# shared/schemas/__init__.py
from shared.schemas.seed import SeedInput
from shared.schemas.person import PersonSummary, PersonResponse
from shared.schemas.relationship import RelationshipResponse, ScoreBreakdown
from shared.schemas.web import WebConfig, WebResponse
from shared.schemas.alert import AlertResponse
```

- [ ] **Step 10.8: Write and run util tests**

```python
# tests/test_shared/test_utils.py
from shared.utils.phone import normalise_phone, get_line_type
from shared.utils.email import normalise_email, extract_domain
from shared.utils.social import extract_instagram_username, extract_twitter_username

def test_phone_normalise_south_african():
    assert normalise_phone("+27 82 123 4567") == "+27821234567"
    assert normalise_phone("082 123 4567", "ZA") == "+27821234567"

def test_phone_invalid():
    assert normalise_phone("not a phone") is None

def test_email_normalise():
    assert normalise_email("John.Doe@Gmail.com") == "john.doe@gmail.com"
    assert normalise_email("notanemail") is None

def test_extract_instagram():
    assert extract_instagram_username("@johndoe") == "johndoe"
    assert extract_instagram_username("https://instagram.com/johndoe/") == "johndoe"

def test_extract_twitter():
    assert extract_twitter_username("https://x.com/johndoe") == "johndoe"
```

```bash
pytest tests/test_shared/ -v
```

Expected: All PASSED

- [ ] **Step 10.9: Commit**

```bash
git add shared/utils/ shared/schemas/ tests/test_shared/test_utils.py
git commit -m "feat: shared utilities, Pydantic schemas"
```

---

## Task 11: Full Integration Test

- [ ] **Step 11.1: Write integration test**

```python
# tests/integration/test_foundation.py
import pytest
import asyncio
from shared.db import get_session
from shared.models import Person, Identifier, Web
from shared.events import get_event_bus
from shared.constants import IdentifierType, WebMode


@pytest.mark.asyncio
async def test_full_person_lifecycle():
    """Create a person, add identifier, verify persistence and quality metadata."""
    from shared.data_quality import make_quality_dict
    from datetime import datetime, timezone

    quality = make_quality_dict("social_profile", "instagram_profile")

    async with get_session() as session:
        person = Person(
            canonical_name="Integration Test Person",
            confidence_score=0.75,
            data_quality=quality,
        )
        session.add(person)
        await session.flush()

        identifier = Identifier(
            person_id=person.id,
            type=IdentifierType.PHONE,
            value="+27821234567",
            source="test",
            discovered_at=datetime.now(timezone.utc),
            data_quality=make_quality_dict("phone_registration", "whitepages"),
        )
        session.add(identifier)
        await session.flush()

        assert person.id is not None
        assert identifier.person_id == person.id
        assert person.data_quality["composite_quality"] > 0


@pytest.mark.asyncio
async def test_event_roundtrip():
    """Publish and receive an event through Dragonfly."""
    bus = get_event_bus()
    received = []

    async def handler(event):
        received.append(event)

    await bus.subscribe("test.integration", handler)
    await bus.publish("test.integration", {"test": True})
    await asyncio.sleep(0.2)
    assert len(received) >= 1


@pytest.mark.asyncio
async def test_create_web():
    from shared.schemas.web import WebConfig
    import json

    config = WebConfig()
    async with get_session() as session:
        web = Web(
            name="Test Investigation",
            mode=WebMode.PERPETUAL,
            config=config.model_dump(),
        )
        session.add(web)
        await session.flush()
        assert web.id is not None
        assert web.config["mode"] == "perpetual"
```

- [ ] **Step 11.2: Run full test suite**

```bash
pytest tests/ -v --cov=shared --cov-report=term-missing
```

Expected: All tests PASSED, coverage > 70% on shared/

- [ ] **Step 11.3: Final commit**

```bash
git add tests/integration/
git commit -m "feat: Phase 1 complete — shared foundation fully tested"
```

---

## Phase 1 Complete — Verification Checklist

Before moving to Phase 2:

- [ ] `docker compose ps` — postgres, dragonfly, tor-1/2/3 all healthy
- [ ] `alembic upgrade head` — runs clean, all 28 tables created
- [ ] `pytest tests/ -v` — all tests pass
- [ ] `make test` — coverage report shows > 70% on shared/
- [ ] Event bus: can publish and receive events
- [ ] Tor: `TorManager(1).check_connectivity()` returns True (with Tor running)

---

## What's Next

**Phase 2 (Plan 2):** Ingestion, enrichment, burner detection, crawlers
**Phase 3 (Plan 3):** Resolution, scoring, behavioural, dark web
**Phase 4 (Plan 4):** Credit risk, wealth
**Phase 5 (Plan 5):** API + Frontend
**Phase 6 (Plan 6):** Daemon + alerts + export

Each plan is written before its phase begins.
