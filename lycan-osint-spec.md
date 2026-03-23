# LYCAN OSINT ENGINE
## Recursive People Intelligence & Graph Discovery Platform
### Technical Specification v2.0

**Document:** WC-OSINT-SPEC-002  
**Date:** 24 March 2026  
**Author:** Michael Wolf  
**Classification:** CONFIDENTIAL

---

## 1. Executive Summary

Lycan is a recursive people-intelligence and graph-discovery platform. It ingests seed identifiers — a phone number, email address, Instagram handle, name, or literally anything typed into a single search box — resolves them to real-world identities, and then recursively discovers related persons, building an ever-growing web of interconnected people, relationships, contact points, and behavioural profiles.

The system is built on a strictly modular, compartmentalised architecture. Every capability is an isolated module with its own directory, config, tests, and interface contract. Modules communicate through a central event bus and shared PostgreSQL database. This means any module can be developed, tested, deployed, and replaced independently — maximising first-time build success.

The frontend is dead simple: a single text box. Type anything — a phone number, email, Instagram handle, name, URL, or any combination. Lycan figures out what it is and runs everything.

---

## 2. System Overview

### 2.1 Core Capabilities

- **Universal input**: Single text box accepts phone, email, Instagram, Twitter/X, LinkedIn, Telegram, name, URL, national ID — or any combination. The system auto-detects input type and routes accordingly.
- **Identity resolution**: Merge fragments from multiple sources into canonical person records with confidence scoring.
- **Recursive graph expansion**: Each resolved person becomes a new seed. The daemon crawls their connections, and those connections' connections, forever — growing like a web.
- **Phone intelligence**: Carrier lookup, line type (mobile/landline/VoIP), country detection, validity check, HLR live status, number portability, reverse lookup to name.
- **Email intelligence**: MX validation, disposable detection, breach exposure, domain WHOIS, gravatar resolution, social account discovery.
- **Instagram-to-everything extraction**: From an Instagram handle, extract phone number, email, real name, location, linked accounts, tagged people, and behavioural signals.
- **Social media enrichment**: Instagram, Twitter/X, LinkedIn, Facebook, TikTok, Telegram — full profile scraping, connection mapping, content analysis.
- **Behavioural profiling**: Detect if a person is a gambler, crypto trader, high-spender, politically exposed, involved in adult content, or other behavioural categories — derived from social signals, post content, followed accounts, and group memberships.
- **Relationship scoring**: Every connection between two people carries a composite score (0.0–1.0) that updates continuously as new evidence arrives.
- **Continuous growth**: The daemon never stops. It re-crawls, discovers new connections, merges webs, and surfaces alerts on changes.
- **Geolocation inference**: Phone prefix mapping, IP geolocation, self-declared locations, timezone analysis, geotagged posts.
- **Document output**: Structured JSON, CSV export, PDF dossiers, interactive graph visualisation.

### 2.2 High-Level Architecture

| Layer | Component | Technology |
|-------|-----------|------------|
| 1. Frontend | Universal Search Box, Graph Dashboard | React, Sigma.js, D3.js, TailwindCSS |
| 2. API Gateway | REST API, WebSocket, Auth | FastAPI, Pydantic, JWT |
| 3. Ingestion | Seed Parser, Input Router, Queue Dispatcher | Python, libphonenumber, Dragonfly |
| 4. Crawl Engine | Scrapy Spiders, Crawlee Actors, Proxy Manager | Scrapy, Crawlee (Playwright), Bright Data |
| 5. Enrichment | Phone/Email Validators, API Integrators, NLP | NumVerify, Hunter.io, spaCy, Claude API |
| 6. Resolution | Identity Merger, Confidence Scorer, Graph Builder | Python, pgvector, NetworkX |
| 7. Scoring | Relationship Scorer, Importance Scorer, Behavioural Profiler | Python, PostgreSQL |
| 8. Growth Daemon | Expansion Scheduler, Re-crawl Manager, Budget Controller, Alert Engine | Python, Windmill → Temporal |
| 9. Persistence | Relational Store, Graph Index, Cache, Search | PostgreSQL + AGE, Dragonfly, MeiliSearch |
| 10. Output | Report Generator, Export Engine | WeasyPrint, pandas |

---

## 3. Modular Architecture & Project Scaffolding

This is the most important section for build success. Every module is a self-contained unit. You can build and test each one independently before wiring them together.

### 3.1 Project Structure

```
lycan/
├── docker-compose.yml                  # All services
├── docker-compose.dev.yml              # Dev overrides (hot reload, debug ports)
├── .env.example                        # All config vars with comments
├── Makefile                            # Common commands: make dev, make test, make migrate
├── README.md
│
├── shared/                             # Shared code used by multiple modules
│   ├── __init__.py
│   ├── config.py                       # Pydantic Settings (loads from .env)
│   ├── db.py                           # SQLAlchemy async engine + session factory
│   ├── models/                         # SQLAlchemy ORM models (source of truth for schema)
│   │   ├── __init__.py
│   │   ├── person.py                   # Person, Alias
│   │   ├── identifier.py              # Identifier (phone, email, handle, etc.)
│   │   ├── relationship.py            # Relationship, RelationshipScoreHistory
│   │   ├── social_profile.py          # SocialProfile
│   │   ├── web.py                      # Web, WebMembership
│   │   ├── crawl.py                    # CrawlJob, CrawlLog
│   │   ├── alert.py                    # Alert
│   │   ├── address.py                 # Address
│   │   ├── employment.py              # EmploymentHistory
│   │   ├── education.py               # Education
│   │   ├── breach.py                  # BreachRecord
│   │   ├── media.py                   # MediaAsset
│   │   ├── watchlist.py               # WatchlistMatch
│   │   └── behavioural.py            # BehaviouralProfile, BehaviouralSignal
│   ├── schemas/                        # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── seed.py                     # SeedInput, SeedType enum
│   │   ├── person.py                  # PersonResponse, PersonSummary
│   │   ├── relationship.py           # RelationshipResponse, ScoreBreakdown
│   │   ├── web.py                      # WebResponse, WebConfig
│   │   └── alert.py                   # AlertResponse
│   ├── events.py                       # Event bus (Dragonfly pub/sub)
│   ├── constants.py                    # Enums, score tiers, relationship types
│   └── utils/
│       ├── phone.py                    # libphonenumber wrappers
│       ├── email.py                    # Email normalisation
│       ├── social.py                   # Handle normalisation (@, URLs → username)
│       └── scoring.py                 # Score computation helpers
│
├── modules/                            # Each module is independent
│   │
│   ├── ingestion/                      # MODULE 1: Input parsing & routing
│   │   ├── __init__.py
│   │   ├── README.md                   # Module docs: what it does, how to test
│   │   ├── parser.py                   # Universal input parser (detect type from raw text)
│   │   ├── normaliser.py              # Normalise each seed type to canonical form
│   │   ├── router.py                   # Route normalised seed to appropriate crawl modules
│   │   ├── validators/
│   │   │   ├── phone_validator.py     # libphonenumber + format checks
│   │   │   ├── email_validator.py     # RFC 5322 + MX check
│   │   │   ├── social_validator.py    # Handle format + existence check
│   │   │   └── id_validator.py        # National ID format validators (RSA, UK, IL, etc.)
│   │   └── tests/
│   │       ├── test_parser.py
│   │       ├── test_normaliser.py
│   │       └── test_validators.py
│   │
│   ├── crawlers/                       # MODULE 2: All scraping/crawling
│   │   ├── __init__.py
│   │   ├── README.md
│   │   ├── base_spider.py             # Abstract base for all Scrapy spiders
│   │   ├── base_actor.py              # Abstract base for all Crawlee actors
│   │   ├── proxy_manager.py           # Rotating proxy pool (Bright Data / Oxylabs)
│   │   ├── anti_detect.py             # Fingerprint randomisation, human-like delays
│   │   ├── captcha_solver.py          # 2Captcha / Anti-Captcha integration
│   │   ├── spiders/                    # Scrapy spiders (structured sources)
│   │   │   ├── whitepages.py
│   │   │   ├── company_registry.py    # CIPC, Companies House, SEC EDGAR
│   │   │   ├── court_records.py
│   │   │   ├── property.py
│   │   │   ├── sanctions.py           # OFAC, UN, EU, HMT
│   │   │   ├── breach.py              # HIBP, DeHashed
│   │   │   ├── domain_whois.py
│   │   │   └── google_dork.py
│   │   ├── actors/                     # Crawlee actors (JS-rendered sources)
│   │   │   ├── instagram.py           # Full profile, posts, tagged, phone/email extraction
│   │   │   ├── linkedin.py
│   │   │   ├── facebook.py
│   │   │   ├── twitter.py
│   │   │   ├── tiktok.py
│   │   │   ├── telegram.py
│   │   │   └── generic_web.py         # Fallback for arbitrary URLs
│   │   └── tests/
│   │       ├── test_instagram.py
│   │       ├── test_proxy_manager.py
│   │       └── fixtures/              # Saved HTML/JSON responses for offline testing
│   │
│   ├── enrichment/                     # MODULE 3: External API enrichment
│   │   ├── __init__.py
│   │   ├── README.md
│   │   ├── base_enricher.py           # Abstract base with rate limiting + caching
│   │   ├── phone/
│   │   │   ├── numverify.py
│   │   │   ├── hlr_lookup.py
│   │   │   ├── truecaller.py
│   │   │   ├── whatsapp_probe.py
│   │   │   └── telegram_probe.py
│   │   ├── email/
│   │   │   ├── mx_validator.py
│   │   │   ├── smtp_probe.py
│   │   │   ├── hunter_io.py
│   │   │   ├── hibp.py
│   │   │   ├── epieos.py
│   │   │   ├── holehe.py             # Email → registered services mapping
│   │   │   └── gravatar.py
│   │   ├── username/
│   │   │   ├── sherlock.py            # Username → 400+ site search
│   │   │   └── whatsmyname.py
│   │   ├── identity/
│   │   │   ├── pipl.py
│   │   │   ├── fullcontact.py
│   │   │   └── social_searcher.py
│   │   ├── geo/
│   │   │   ├── ipinfo.py
│   │   │   └── phone_geo.py          # Phone prefix → country/region
│   │   └── tests/
│   │       └── test_enrichers.py
│   │
│   ├── resolution/                     # MODULE 4: Identity resolution & dedup
│   │   ├── __init__.py
│   │   ├── README.md
│   │   ├── candidate_gen.py           # Blocking: generate candidate pairs
│   │   ├── feature_extract.py         # Compute similarity features per pair
│   │   ├── scorer.py                   # Weighted scoring → match probability
│   │   ├── merger.py                   # Merge confirmed matches into canonical record
│   │   ├── embedding.py               # Generate name+bio embeddings (pgvector)
│   │   └── tests/
│   │       └── test_resolution.py
│   │
│   ├── scoring/                        # MODULE 5: Relationship & person scoring
│   │   ├── __init__.py
│   │   ├── README.md
│   │   ├── relationship_scorer.py     # Composite edge scoring (all evidence types)
│   │   ├── importance_scorer.py       # Node importance scoring (expansion priority)
│   │   ├── classifier.py              # Relationship type classification
│   │   ├── decay.py                    # Score decay over time (no new interactions)
│   │   ├── score_history.py           # Track and persist score changes
│   │   └── tests/
│   │       └── test_scoring.py
│   │
│   ├── behavioural/                    # MODULE 6: Behavioural profiling
│   │   ├── __init__.py
│   │   ├── README.md
│   │   ├── profiler.py                # Main profiler — aggregates all signals
│   │   ├── signals/
│   │   │   ├── gambling.py            # Gambling detection
│   │   │   ├── crypto.py             # Crypto trading signals
│   │   │   ├── political.py          # PEP / political activity
│   │   │   ├── lifestyle.py          # High-spender, luxury, travel patterns
│   │   │   ├── adult.py              # Adult content involvement
│   │   │   ├── substance.py          # Substance use signals
│   │   │   └── risk.py               # General risk indicators
│   │   ├── nlp/
│   │   │   ├── keyword_matcher.py    # Fast keyword/regex matching
│   │   │   ├── claude_analyser.py    # Claude API for nuanced text analysis
│   │   │   └── sentiment.py          # Sentiment analysis on posts
│   │   └── tests/
│   │       └── test_profiler.py
│   │
│   ├── daemon/                         # MODULE 7: Continuous growth engine
│   │   ├── __init__.py
│   │   ├── README.md
│   │   ├── growth_daemon.py           # Main daemon loop
│   │   ├── expansion_scheduler.py     # Priority queue for expansion
│   │   ├── recrawl_scheduler.py       # TTL-based revisit scheduling
│   │   ├── budget_controller.py       # API spend + crawl volume limits
│   │   ├── web_merger.py              # Cross-web overlap detection
│   │   ├── anomaly_detector.py        # Change detection + alert generation
│   │   └── tests/
│   │       └── test_daemon.py
│   │
│   ├── alerts/                         # MODULE 8: Alert engine
│   │   ├── __init__.py
│   │   ├── README.md
│   │   ├── alert_engine.py            # Core alert creation + severity assignment
│   │   ├── delivery/
│   │   │   ├── telegram_bot.py        # Telegram notification delivery
│   │   │   ├── email_digest.py        # Daily email summary
│   │   │   ├── webhook.py             # Generic webhook POST
│   │   │   └── websocket.py           # Real-time push to dashboard
│   │   └── tests/
│   │       └── test_alerts.py
│   │
│   └── export/                         # MODULE 9: Report & export generation
│       ├── __init__.py
│       ├── README.md
│       ├── pdf_dossier.py             # WeasyPrint HTML → PDF
│       ├── csv_export.py
│       ├── json_export.py
│       ├── graphml_export.py          # For Gephi / Neo4j import
│       ├── maltego_export.py
│       ├── templates/                  # HTML templates for PDF dossiers
│       │   ├── dossier.html
│       │   ├── graph_static.html
│       │   └── styles.css
│       └── tests/
│           └── test_exports.py
│
├── api/                                # FastAPI application
│   ├── __init__.py
│   ├── main.py                         # FastAPI app factory
│   ├── dependencies.py                # Dependency injection (DB sessions, auth)
│   ├── middleware.py                   # CORS, rate limiting, audit logging
│   ├── auth.py                         # JWT token management
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── search.py                  # Universal search endpoint
│   │   ├── webs.py                    # Web CRUD + management
│   │   ├── persons.py                 # Person endpoints
│   │   ├── relationships.py          # Relationship + score history
│   │   ├── lookup.py                  # Quick lookup (phone, email, social)
│   │   ├── alerts.py                  # Alert management
│   │   ├── export.py                  # Export endpoints
│   │   └── stats.py                   # System stats
│   ├── websocket.py                    # WebSocket handler for real-time events
│   └── tests/
│       └── test_api.py
│
├── frontend/                           # React application
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── SearchBox.tsx          # THE single text box
│   │   │   ├── GraphView.tsx          # Sigma.js graph renderer
│   │   │   ├── PersonPanel.tsx        # Dossier side panel
│   │   │   ├── RelationshipPanel.tsx  # Edge detail + score breakdown
│   │   │   ├── AlertsPanel.tsx        # Alert feed
│   │   │   ├── StatsBar.tsx           # Growth metrics overlay
│   │   │   ├── ScoreOverlay.tsx       # Toggle-able score visualisations
│   │   │   ├── TimelineScrubber.tsx   # Historical graph state slider
│   │   │   └── BehaviourBadges.tsx    # Gambler, crypto, PEP badges on nodes
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts        # Real-time event subscription
│   │   │   └── useGraph.ts            # Graph data management
│   │   ├── services/
│   │   │   └── api.ts                 # API client
│   │   └── types/
│   │       └── index.ts               # TypeScript types matching API schemas
│   └── public/
│
├── migrations/                         # Alembic migrations
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── scripts/
│   ├── seed_db.py                      # Seed test data
│   ├── run_single_lookup.py           # CLI tool for quick lookups
│   └── health_check.py                # Verify all services are up
│
└── tests/
    ├── conftest.py                     # Shared fixtures (test DB, mock APIs)
    ├── integration/
    │   ├── test_full_pipeline.py      # Seed → resolve → expand → score
    │   └── test_web_growth.py         # Daemon expansion test
    └── e2e/
        └── test_search_box.py         # Frontend search → API → results
```

### 3.2 Module Interface Contracts

Every module exposes a clean interface. Modules never import from each other's internals — only from the shared layer or from the module's public interface.

| Module | Input | Output | Interface |
|--------|-------|--------|-----------|
| ingestion | Raw text string | List of typed, normalised seeds | `parse_input(raw: str) → list[Seed]` |
| crawlers | Seed + person context | Raw scraped data items | `crawl(seed: Seed) → list[RawDataItem]` |
| enrichment | Identifier (phone/email/etc) | Enriched metadata | `enrich(identifier: Identifier) → EnrichmentResult` |
| resolution | List of data fragments | Canonical person record | `resolve(fragments: list[Fragment]) → Person` |
| scoring | Person pair + evidence | Relationship score + classification | `score(person_a, person_b, evidence) → ScoredRelationship` |
| behavioural | Person + all their data | Behavioural profile with signals | `profile(person: Person) → BehaviouralProfile` |
| daemon | Web config | Continuous expansion (side effects) | `run(web_id: UUID) → never returns` |
| alerts | Event stream | Alert records | `evaluate(event: Event) → list[Alert]` |
| export | Person/Web ID + format | File bytes | `export(target_id, format) → bytes` |

### 3.3 Module Communication

Modules communicate through two mechanisms:

**1. Database (PostgreSQL):** All modules read/write the shared database. The ORM models in `shared/models/` are the single source of truth. Modules never create their own tables — all schema changes go through Alembic migrations.

**2. Event Bus (Dragonfly pub/sub):** When a module does something noteworthy, it publishes an event. Other modules subscribe to events they care about.

Event types:

| Event | Publisher | Subscribers |
|-------|-----------|-------------|
| `seed.parsed` | ingestion | crawlers, daemon |
| `data.scraped` | crawlers | resolution, enrichment |
| `person.resolved` | resolution | scoring, behavioural, daemon |
| `person.updated` | resolution | scoring, behavioural, alerts |
| `relationship.created` | resolution | scoring, daemon, frontend (WS) |
| `relationship.scored` | scoring | daemon, alerts, frontend (WS) |
| `behaviour.profiled` | behavioural | alerts, frontend (WS) |
| `alert.created` | alerts | frontend (WS), telegram, email |
| `web.person_added` | daemon | frontend (WS), stats |
| `web.merged` | daemon | alerts, frontend (WS) |
| `crawl.completed` | crawlers | daemon, stats |
| `crawl.failed` | crawlers | alerts, daemon |

### 3.4 Build Order (Critical Path)

Build in this exact order. Each step is independently testable before moving to the next.

**Step 1: Shared Foundation**
- Set up PostgreSQL + Alembic migrations
- Build all ORM models
- Build Pydantic schemas
- Build event bus (Dragonfly pub/sub wrapper)
- Test: Migrations run, models create/read/update, events publish/subscribe

**Step 2: Ingestion Module**
- Build universal parser (regex + libphonenumber + heuristics)
- Build normalisers for each seed type
- Build validators
- Test: Feed 50 sample inputs (phones, emails, handles, names, garbage) → correct type detection and normalisation

**Step 3: Enrichment Module**
- Build base enricher with rate limiting + caching
- Implement phone enrichers (NumVerify, HLR, TrueCaller)
- Implement email enrichers (MX, SMTP, HIBP, Holehe)
- Implement username search (Sherlock)
- Test: Lookup known numbers/emails → correct metadata returned

**Step 4: Crawlers Module**
- Build proxy manager + anti-detection
- Build InstagramActor first (highest value target)
- Build WhitePagesSpider
- Build Google Dork actor
- Test: Scrape a public Instagram profile → structured data returned

**Step 5: Resolution Module**
- Build candidate generation (blocking on identifiers)
- Build feature extraction + pairwise scoring
- Build merger
- Test: Feed two fragments for the same person → correctly merged

**Step 6: Scoring Module**
- Build relationship scorer with all evidence types
- Build importance scorer
- Build classifier
- Test: Two persons with known evidence → correct score and classification

**Step 7: API + Frontend**
- Build FastAPI with routers
- Build React frontend with SearchBox + GraphView
- Wire WebSocket for real-time updates
- Test: Type input in search box → see results and graph

**Step 8: Behavioural Module**
- Build keyword matchers for each signal type
- Wire Claude API for nuanced analysis
- Test: Feed a person with gambling-related follows → gambling flag set

**Step 9: Daemon Module**
- Build expansion scheduler
- Build re-crawl scheduler
- Build budget controller
- Wire to all other modules
- Test: Plant a seed → watch the web grow autonomously

**Step 10: Alerts + Export**
- Build alert engine with severity rules
- Build Telegram bot delivery
- Build PDF dossier generator
- Test: Trigger alert conditions → notifications delivered

---

## 4. Data Model

### 4.1 Core Entities

All tables live in PostgreSQL 16 with Apache AGE extension for graph traversal and pgvector for fuzzy dedup.

#### 4.1.1 persons

| Column | Type | Constraint | Description |
|--------|------|------------|-------------|
| id | UUID | PK, DEFAULT gen | Canonical person identifier |
| canonical_name | VARCHAR(512) | NOT NULL | Best-known full name |
| first_name | VARCHAR(256) | | Parsed first name |
| last_name | VARCHAR(256) | | Parsed last name / surname |
| date_of_birth | DATE | | DOB if discovered |
| gender | VARCHAR(32) | | Inferred or declared gender |
| nationality | VARCHAR(3) | ISO 3166-1 | Primary nationality ISO alpha-3 |
| country_of_residence | VARCHAR(3) | ISO 3166-1 | Current country of residence |
| city | VARCHAR(256) | | City / metro area |
| bio_text | TEXT | | Aggregated bio / about text from all sources |
| profile_image_url | TEXT | | Best available profile photo URL |
| confidence_score | FLOAT | 0.0–1.0 | Identity resolution confidence |
| risk_score | FLOAT | 0.0–1.0 | Composite risk / flags score |
| tags | TEXT[] | | Freeform tags (e.g. PEP, sanctioned, gambler) |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Record creation timestamp |
| updated_at | TIMESTAMPTZ | AUTO UPDATE | Last modification timestamp |
| embedding | VECTOR(768) | pgvector | Name + bio embedding for fuzzy dedup |

#### 4.1.2 identifiers

| Column | Type | Constraint | Description |
|--------|------|------------|-------------|
| id | UUID | PK | Identifier record ID |
| person_id | UUID | FK persons | Owning person |
| type | ENUM | NOT NULL | phone, email, instagram, twitter, linkedin, telegram, facebook, tiktok, whatsapp, website, national_id |
| value | VARCHAR(1024) | NOT NULL | The identifier value (normalised) |
| raw_value | VARCHAR(1024) | | Original input before normalisation |
| is_verified | BOOLEAN | DEFAULT FALSE | Verification status |
| verification_method | VARCHAR(128) | | How verified (HLR, MX, API, scrape) |
| country_code | VARCHAR(3) | ISO 3166-1 | Country associated with identifier |
| carrier | VARCHAR(256) | | Phone carrier name |
| line_type | VARCHAR(32) | | mobile, landline, voip, toll_free |
| is_primary | BOOLEAN | DEFAULT FALSE | Primary identifier of this type |
| source | VARCHAR(256) | NOT NULL | Where this identifier was found |
| discovered_at | TIMESTAMPTZ | DEFAULT NOW() | When discovered |

#### 4.1.3 relationships

| Column | Type | Constraint | Description |
|--------|------|------------|-------------|
| id | UUID | PK | Relationship record ID |
| person_a_id | UUID | FK persons | First person |
| person_b_id | UUID | FK persons | Second person |
| rel_type | ENUM | NOT NULL | family, spouse, parent, child, sibling, friend, colleague, business_associate, romantic, co_tagged, mutual_follower, co_resident, co_director, classmate, unknown |
| strength | FLOAT | 0.0–1.0 | Composite relationship score |
| evidence | JSONB | | Array of evidence objects with source, type, timestamp |
| bidirectional | BOOLEAN | DEFAULT TRUE | Whether relationship is mutual |
| score_trend | VARCHAR(16) | | rising, stable, declining (30-day delta) |
| last_scored_at | TIMESTAMPTZ | | When score was last recomputed |

#### 4.1.4 relationship_score_history

| Column | Type | Constraint | Description |
|--------|------|------------|-------------|
| id | UUID | PK | Score event ID |
| relationship_id | UUID | FK relationships | The relationship being scored |
| old_score | FLOAT | | Previous composite score |
| new_score | FLOAT | NOT NULL | Updated composite score |
| score_delta | FLOAT | | Absolute change (new − old) |
| tier_before | VARCHAR(32) | | CRITICAL, STRONG, MODERATE, WEAK, TENUOUS |
| tier_after | VARCHAR(32) | | Tier after score change |
| evidence_delta | JSONB | | What evidence changed |
| trigger_source | VARCHAR(256) | NOT NULL | Which crawl/enrichment caused this change |
| recorded_at | TIMESTAMPTZ | DEFAULT NOW() | When the score changed |

#### 4.1.5 webs

| Column | Type | Constraint | Description |
|--------|------|------------|-------------|
| id | UUID | PK | Web identifier |
| name | VARCHAR(256) | NOT NULL | User-assigned web name |
| seed_person_id | UUID | FK persons | The original root seed person |
| mode | VARCHAR(32) | NOT NULL | perpetual, bounded, manual, paused |
| total_persons | INTEGER | DEFAULT 0 | Current person count |
| total_relationships | INTEGER | DEFAULT 0 | Current edge count |
| max_depth_reached | INTEGER | DEFAULT 0 | Furthest hop from seed |
| avg_relationship_score | FLOAT | | Mean score across all edges |
| growth_rate_24h | FLOAT | | Persons discovered per hour (24h rolling avg) |
| merged_from | UUID[] | | IDs of webs merged into this one |
| config | JSONB | NOT NULL | Growth controls: max_persons, thresholds, TTLs, budget |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | Web creation time |
| last_expansion_at | TIMESTAMPTZ | | Last daemon expansion time |

#### 4.1.6 web_memberships

| Column | Type | Constraint | Description |
|--------|------|------------|-------------|
| web_id | UUID | FK webs, PK | The web |
| person_id | UUID | FK persons, PK | The person |
| hop_depth | INTEGER | NOT NULL | Hops from seed |
| importance_score | FLOAT | 0.0–1.0 | Person importance within this web |
| is_frozen | BOOLEAN | DEFAULT FALSE | Daemon will not expand from this person |
| is_pinned | BOOLEAN | DEFAULT FALSE | Priority expansion and re-crawl |
| discovered_at | TIMESTAMPTZ | DEFAULT NOW() | When discovered in this web |
| last_expanded_at | TIMESTAMPTZ | | Last expansion time |

#### 4.1.7 behavioural_profiles

| Column | Type | Constraint | Description |
|--------|------|------------|-------------|
| id | UUID | PK | Profile ID |
| person_id | UUID | FK persons, UNIQUE | One profile per person |
| is_gambler | BOOLEAN | DEFAULT FALSE | Gambling behaviour detected |
| gambling_confidence | FLOAT | 0.0–1.0 | How confident is the gambling signal |
| is_crypto_trader | BOOLEAN | DEFAULT FALSE | Crypto trading signals detected |
| is_high_spender | BOOLEAN | DEFAULT FALSE | Luxury / high-spend lifestyle |
| is_pep | BOOLEAN | DEFAULT FALSE | Politically exposed person |
| is_adult_content | BOOLEAN | DEFAULT FALSE | Involvement in adult content |
| is_substance_user | BOOLEAN | DEFAULT FALSE | Substance use signals |
| risk_category | VARCHAR(32) | | low, medium, high, critical |
| signals | JSONB | NOT NULL | Array of all detected signals with evidence |
| last_profiled_at | TIMESTAMPTZ | DEFAULT NOW() | When profile was last updated |

#### 4.1.8 behavioural_signals

| Column | Type | Constraint | Description |
|--------|------|------------|-------------|
| id | UUID | PK | Signal ID |
| person_id | UUID | FK persons | Person this signal applies to |
| signal_type | VARCHAR(64) | NOT NULL | gambling, crypto, luxury, pep, adult, substance, risk |
| source_platform | VARCHAR(64) | NOT NULL | Where signal was detected (instagram, twitter, etc.) |
| evidence_type | VARCHAR(64) | NOT NULL | follows_account, post_content, group_membership, bio_keyword, hashtag, tagged_location, bet_slip_image |
| evidence_value | TEXT | NOT NULL | The specific evidence (account name, keyword, post text) |
| confidence | FLOAT | 0.0–1.0 | Signal confidence |
| detected_at | TIMESTAMPTZ | DEFAULT NOW() | When signal was detected |

#### 4.1.9 alerts

| Column | Type | Constraint | Description |
|--------|------|------------|-------------|
| id | UUID | PK | Alert ID |
| web_id | UUID | FK webs | Which web |
| person_id | UUID | FK persons | Related person |
| alert_type | VARCHAR(64) | NOT NULL | sanctions_hit, profile_deleted, breach_exposure, identity_change, new_connection, score_threshold, web_merger, location_change, recrawl_anomaly, behavioural_change |
| severity | VARCHAR(16) | NOT NULL | CRITICAL, HIGH, MEDIUM, LOW |
| title | VARCHAR(512) | NOT NULL | Human-readable summary |
| details | JSONB | | Full alert data payload |
| is_read | BOOLEAN | DEFAULT FALSE | User acknowledged |
| created_at | TIMESTAMPTZ | DEFAULT NOW() | When generated |

#### 4.1.10 Additional Tables

- **social_profiles**: Full scraped profile data per platform (followers, following, post_count, bio, profile_pic_url, is_private, is_verified, external_url, last_scraped_at)
- **addresses**: Physical addresses with geocoordinates, address_type (home/work/mailing), verification status
- **employment_history**: Company name, title, start/end dates, source, LinkedIn URL
- **education**: Institution, degree, field, graduation year
- **crawl_jobs**: Job tracking with seed, status, depth, pages_crawled, identifiers_found, persons_resolved
- **crawl_logs**: Per-request logs with URL, status_code, response_time, proxy_used, spider_name, error details
- **data_sources**: Registry of all external API and scrape sources with rate limits, last_used, credits_remaining
- **breach_records**: Known breach exposures per identifier
- **media_assets**: Downloaded profile photos, post images with perceptual hashes
- **aliases**: Name variants, maiden names, nicknames, transliterations
- **watchlists**: Sanctions, PEP, adverse media matches

---

## 5. The Universal Search Box

### 5.1 How It Works

The frontend is a single text box. The user types anything. Lycan does the rest.

**Input flow:**
1. User types raw text into the search box
2. The ingestion module's universal parser analyses the input
3. Parser detects one or more seed types from the raw text
4. Each detected seed is normalised
5. If the person already exists in the database, their full dossier is returned immediately along with their web graph
6. If the person doesn't exist, a new investigation is launched: crawlers fire, enrichers run, resolution merges fragments, scoring begins, the daemon starts expanding

**Detection logic:**

| Pattern | Detection Rule | Seed Type |
|---------|---------------|-----------|
| Starts with + followed by digits | E.164 phone | phone |
| 10–15 digits, optionally with spaces/dashes | Phone number (try parse with libphonenumber) | phone |
| Contains @ and a TLD | Email address | email |
| Starts with @ (no TLD) | Social handle (try Instagram first, then Twitter) | instagram / twitter |
| Contains instagram.com/ | Instagram URL → extract username | instagram |
| Contains twitter.com/ or x.com/ | Twitter URL → extract username | twitter |
| Contains linkedin.com/in/ | LinkedIn URL → extract slug | linkedin |
| Contains t.me/ | Telegram URL → extract username | telegram |
| Contains facebook.com/ | Facebook URL → extract profile | facebook |
| Contains tiktok.com/@ | TikTok URL → extract username | tiktok |
| 13 digits matching SA ID pattern | South African ID number | national_id |
| 9 digits matching IL ID pattern | Israeli Teudat Zehut | national_id |
| Any other URL | Generic website → scrape for person data | website |
| Two or more words, no special chars | Full name | name |
| Single word, no special chars | Username (try Sherlock across platforms) | username |

**Multiple inputs:** The search box accepts multiple seeds separated by commas or newlines. All are processed together and resolved into a single investigation.

### 5.2 Search Box Behaviour

- **Autocomplete from existing data**: As you type, if matching persons already exist in the database, they appear as suggestions below the input. Click to view their existing dossier and web.
- **Loading states**: After submitting, the search box shows real-time progress: "Parsing input...", "Looking up phone...", "Scraping Instagram...", "Resolving identity...", "Building graph..."
- **Results display**: Once results arrive, the view transitions to the graph view centred on the target person, with their dossier panel open on the right.
- **Empty state**: If nothing is found, Lycan shows what it tried and offers to keep monitoring (create a dormant web that checks periodically).

### 5.3 Existing vs New Lookup

When you search for something that already exists in the database:

- **Exact match on identifier**: Instantly return the person dossier + their web graph. Show "last updated X minutes ago" timestamp.
- **Fuzzy match on name**: Show top 5 candidates ranked by embedding similarity + data overlap. Let user confirm which one, or create new.
- **No match**: Launch full investigation pipeline. Create new web in configured mode (perpetual by default).

---

## 6. Input Processing Pipeline

### 6.1 Seed Types & Normalisation

| Seed Type | Input Example | Normalised Form | Validation |
|-----------|--------------|-----------------|------------|
| Phone | +27 82 123 4567 | +27821234567 (E.164) | libphonenumber parse + HLR |
| Email | John.Doe@Gmail.com | john.doe@gmail.com | MX lookup + SMTP probe |
| Instagram | @johndoe or instagram.com/johndoe | johndoe | Profile existence check |
| Twitter/X | @johndoe or x.com/johndoe | johndoe | Profile existence check |
| LinkedIn | linkedin.com/in/john-doe | john-doe (slug) | Profile existence check |
| Telegram | @johndoe or t.me/johndoe | johndoe | Bot API user lookup |
| Name | "John Michael Doe" | Parsed: first/middle/last | N/A (fuzzy match entry) |
| National ID | SA ID: 9510305012080 | Validated + DOB/gender extracted | Luhn check + format |
| Username | johndoe95 | johndoe95 | Sherlock cross-platform search |

### 6.2 Phone Number Intelligence

Every phone number seed passes through a multi-stage verification pipeline:

1. **Format parsing**: libphonenumber extracts country code, national number, region, number type (mobile/fixed/VoIP/toll_free)
2. **Carrier lookup**: Identify MNO or MVNO operator, detect ported numbers
3. **HLR query**: Real-time Home Location Register check — confirms number is live, roaming status, IMSI
4. **Reverse lookup**: Search TrueCaller, Sync.me, CallerID databases for associated name
5. **WhatsApp probe**: Check registration status, extract profile photo and status text
6. **Telegram probe**: Check registration, extract username if public
7. **Breach search**: Cross-reference against known data breaches for associated accounts

### 6.3 Email Intelligence

1. **Syntax validation**: RFC 5322 compliance
2. **MX record check**: Verify receiving domain exists and accepts mail
3. **SMTP probe**: Non-destructive RCPT TO check for mailbox existence
4. **Disposable detection**: Check against 10K+ disposable email provider list
5. **Gravatar / avatar resolution**: MD5 hash lookup for profile images
6. **Breach exposure**: HIBP API and internal breach DB cross-reference
7. **Domain WHOIS**: Registrant info, creation date, hosting provider
8. **Social account discovery**: Use email as registration lookup (Holehe across 120+ services)

### 6.4 Instagram-to-Everything Extraction

This is a key capability: given an Instagram handle, extract maximum intelligence including phone numbers and emails that aren't publicly displayed.

**Direct extraction (from profile):**
- Full name, bio text, external URL, is_verified, is_private
- Profile photo (HD), follower/following counts, post count
- Bio link parsing: Linktree → extract all linked accounts, phone, email
- Business account detection: Business accounts often expose phone, email, address, category via Instagram API or page source
- External URL scraping: Visit the linked website, extract contact info from there

**Indirect extraction (from content analysis):**
- Post captions: NLP extraction of phone numbers, emails, location mentions
- Story highlights: Often contain "Contact Me" or "Book Now" with phone/email
- Tagged users: Build relationship edges from co-tagged photos
- Location tags: Geotagged posts → movement timeline
- Hashtag analysis: Industry, interests, behavioural signals
- Comment analysis: Frequent commenters → relationship candidates
- Following list analysis: Categorise followed accounts (gambling, crypto, luxury, adult, etc.)

**Cross-platform pivoting:**
- Username search: Try the same Instagram username on Twitter, TikTok, LinkedIn, Facebook, Telegram, GitHub, Reddit, Pinterest, Snapchat, etc. (via Sherlock / WhatsMyName)
- Reverse image search: Use profile photo to find the same person on other platforms
- Email discovery: If username is found on a platform that exposes email (GitHub, some forums), extract it
- Phone discovery: If username leads to a WhatsApp business profile, personal website, or directory listing, extract phone

---

## 7. Crawl Engine Architecture

### 7.1 Scrapy Spiders (Structured Sources)

| Spider | Target | Data Extracted |
|--------|--------|----------------|
| WhitePagesSpider | Whitepages, TruePeopleSearch, FastPeopleSearch | Name, address, phone, relatives, associates |
| CompanyRegSpider | CIPC (ZA), Companies House (UK), SEC EDGAR | Directorships, shareholdings, company details |
| CourtRecordSpider | PACER, ZA court rolls, public case records | Litigation history, party names, case outcomes |
| PropertySpider | Deeds registries, property24.co.za, Zillow | Property ownership, valuations, addresses |
| SanctionsSpider | OFAC SDN, UN Consolidated, EU sanctions, HMT | Sanctions matches, PEP status, adverse media |
| BreachSpider | HIBP, DeHashed, breach paste sites | Exposed credentials, associated emails/phones |
| DomainSpider | WHOIS, DNS records, certificate transparency | Domain registrant, hosting, SSL cert names |

### 7.2 Crawlee Actors (Dynamic / JS-Rendered Sources)

| Actor | Target | Data Extracted |
|-------|--------|----------------|
| InstagramActor | instagram.com (profile, posts, tagged) | Full profile, posts, tagged users, phone/email extraction, locations |
| LinkedInActor | linkedin.com (profiles, companies) | Work history, education, connections, endorsements |
| FacebookActor | facebook.com (public profiles, about pages) | Name, location, family, work, education, photos |
| TwitterActor | x.com (profiles, tweets, connections) | Bio, location, followers, following, tweets |
| TikTokActor | tiktok.com (profiles, videos) | Bio, followers, video captions, tagged users |
| TelegramActor | web.telegram.org, t.me | Profile info, group memberships, messages |
| GoogleDorkActor | Google search (targeted queries) | Mentions, cached pages, PDF metadata, forum posts |
| GenericWebActor | Any URL | Contact info, about pages, team pages, structured data |

### 7.3 Proxy & Anti-Detection

- Rotating residential proxy pool (Bright Data or Oxylabs) with geo-targeting per spider
- Browser fingerprint randomisation: User-Agent, viewport, WebGL, canvas, timezone, language
- Human-like behaviour simulation: random delays (2–8s), scroll patterns, mouse movements
- Session management: cookie jars per target domain, login session rotation
- Rate limiting: per-domain configurable RPS with exponential backoff on 429/captcha
- CAPTCHA solving: 2Captcha / Anti-Captcha integration for blocked requests
- Request header rotation: Accept, Accept-Language, Accept-Encoding randomised per request

---

## 8. Identity Resolution Engine

### 8.1 Entity Resolution Pipeline

1. **Candidate Generation**: Blocking on normalised phone, email, and exact name match to generate candidate pairs efficiently
2. **Feature Extraction**: For each pair, compute similarity: Jaro-Winkler on names (0.92 threshold), exact match on identifiers, address overlap, employer overlap, age proximity
3. **Pairwise Scoring**: Weighted features → match probability (0.0–1.0). Thresholds: ≥0.85 auto-merge, 0.60–0.85 manual review queue, <0.60 distinct
4. **Transitive Closure**: If A=B and B=C, evaluate A-C. Connected components form person clusters
5. **Canonical Record Creation**: Best name (longest, most formal), merge all identifiers, aggregate metadata, compute confidence

### 8.2 Confidence Scoring

| Signal | Weight | Notes |
|--------|--------|-------|
| Exact phone match (verified) | 0.95 | Strongest single signal |
| Exact email match (verified) | 0.90 | Very strong |
| Same name + same city | 0.70 | Requires additional corroboration |
| Same name + same employer | 0.75 | Strong with temporal overlap |
| Facial match (perceptual hash) | 0.60 | Supplementary, not standalone |
| Username pattern match | 0.40 | e.g. johndoe95 across platforms |
| Co-tagged in photo | 0.30 | Relationship signal, not identity |

---

## 9. Behavioural Profiling Engine

### 9.1 Overview

For every person in the graph, Lycan builds a behavioural profile by analysing their social media activity, followed accounts, group memberships, post content, and associated data. The primary use case is detecting gambling behaviour, but the system profiles across multiple dimensions.

### 9.2 Gambling Detection

Gambling is detected through multiple signal types, each contributing to the `gambling_confidence` score:

| Signal Type | Detection Method | Confidence Weight | Examples |
|-------------|-----------------|-------------------|----------|
| Follows gambling accounts | Check if person follows known sportsbook, casino, or tipster accounts on Instagram/Twitter | 0.25 | @bet365, @draftkings, @betway, @saborbet, tipster accounts |
| Gambling hashtags in posts | Scan post captions for gambling-related hashtags | 0.20 | #betting, #accumulator, #parlay, #casino, #slots, #poker, #sportsbetting |
| Gambling keywords in bio | Check bio text for gambling references | 0.15 | "punter", "tipster", "betting", "poker player", "casino", "degening" |
| Bet slip images | Detect bet slip screenshots in post images (Claude Vision) | 0.30 | Bet slip screenshots, casino win screenshots, odds displays |
| Gambling group membership | Check Telegram/Facebook group memberships | 0.20 | Betting tips groups, VIP tipster channels, casino promo groups |
| Gambling app presence | Check if device has gambling apps (via Holehe / app store reviews) | 0.15 | Bet365, DraftKings, FanDuel, PokerStars app activity |
| Casino/sportsbook location tags | Geotagged posts at known gambling venues | 0.10 | Sun City, Monte Carlo Casino, Las Vegas Strip, local casinos |
| Financial stress signals | Posts about money problems, loan requests, "last bet" rhetoric | 0.10 | NLP analysis of post content for financial distress patterns |

**Gambling confidence tiers:**
- 0.80–1.00: **Confirmed gambler** — multiple strong signals across platforms
- 0.50–0.79: **Likely gambler** — consistent signals from 2+ sources
- 0.25–0.49: **Possible gambler** — some signals but could be casual
- 0.00–0.24: **No indication** — no gambling signals detected

### 9.3 Other Behavioural Dimensions

| Dimension | Signals Detected |
|-----------|-----------------|
| **Crypto trader** | Follows crypto accounts, crypto hashtags, wallet addresses in bio, token discussion, NFT activity, DeFi group membership |
| **High spender / luxury** | Luxury brand follows, expensive location tags (5-star hotels, first class lounges), designer hashtags, yacht/supercar content |
| **Politically exposed** | Government position mentions, political party follows, campaign activity, media appearances, declared political roles |
| **Adult content** | OnlyFans link in bio, adult hashtags, adult platform follows, explicit content detection |
| **Substance use** | Cannabis/drug references in posts, follows dispensary accounts, substance-related hashtags, coded language patterns |
| **General risk** | Association with sanctioned persons, breach exposure frequency, identity inconsistencies, fake profile signals, rapid account creation pattern |

### 9.4 Profiling Pipeline

1. **Keyword/regex scan** (fast, runs on every crawl): Check bio, post captions, hashtags against keyword lists for each dimension
2. **Account analysis** (medium, runs when follower list available): Categorise followed accounts against a curated database of 50K+ categorised accounts (gambling operators, crypto exchanges, political parties, adult platforms, etc.)
3. **Claude Vision analysis** (expensive, runs on flagged content): Send post images to Claude API for bet slip detection, casino screenshot detection, lifestyle analysis
4. **Claude text analysis** (moderate, runs on flagged text): Nuanced NLP analysis of post captions, comments, and bio text for coded language, sentiment, and context
5. **Aggregation**: All signals are aggregated into the behavioural profile with per-signal confidence scores. The overall dimension score is a weighted sum.

### 9.5 Curated Account Database

A key data asset: a database of categorised accounts across platforms. Used for "follows analysis" — if a person follows 15 gambling accounts, that's a strong signal.

Categories maintained:
- **Gambling**: Sportsbooks, casinos, tipsters, betting communities, poker rooms (target: 5K+ accounts)
- **Crypto**: Exchanges, projects, influencers, DeFi protocols, NFT collections (target: 10K+ accounts)
- **Luxury**: Brands, hotels, car dealers, luxury lifestyle influencers (target: 3K+ accounts)
- **Political**: Parties, politicians, PACs, advocacy groups by country (target: 10K+ accounts)
- **Adult**: Platforms, creators, communities (target: 2K+ accounts)
- **Substance**: Dispensaries, advocacy, culture accounts (target: 1K+ accounts)
- **News/Media**: For cross-referencing mentions and context (target: 5K+ accounts)

This database is seeded manually and grows through discovery: when the system finds a new gambling tipster account followed by multiple confirmed gamblers, it auto-suggests adding it to the database.

---

## 10. Continuous Web Growth Engine

### 10.1 The Growth Daemon

The Lycan Growth Daemon (`lycan-daemon`) is a long-running background service. Once a seed is planted, the daemon takes over and autonomously expands the graph indefinitely.

**Daemon lifecycle:**
1. **Seed planted**: User submits input via search box. Creates root node of a new web.
2. **Initial resolution**: Seed resolved to canonical person. All sources crawled.
3. **First-hop discovery**: Every related person found (tagged photos, listed relative, mutual follower, co-director, shared address) queued as new seed.
4. **Recursive expansion**: Each discovered person is resolved, crawled, scored. Their connections discovered. Repeats outward, hop by hop.
5. **Perpetual re-crawl**: Daemon revisits previously crawled persons on configurable TTL, looking for new connections, updated profiles, new posts.
6. **Cross-web linking**: When a person in Web A connects to someone in Web B, a bridge edge is created — merging separate investigations.

### 10.2 Daemon Architecture

| Component | Function | Details |
|-----------|----------|---------|
| Expansion Scheduler | Prioritises which persons to expand next | Priority queue sorted by: staleness, relationship score, depth from seed, unresolved identifiers |
| Re-crawl Scheduler | Manages TTL-based revisits | Social profiles: 7d. Company records: 30d. Sanctions: 24h. Breaches: 6h. |
| Budget Controller | Rate-limits API spend and crawl volume | Daily API credit caps, concurrent crawler limits, proxy bandwidth. Pauses when exhausted. |
| Web Merger | Detects cross-web overlaps | When a person appears in multiple webs, creates bridge relationships and optionally merges. |
| Anomaly Detector | Flags suspicious changes | Profile deletions, follower drops, name changes, new sanctions, identity inconsistencies. |
| Event Emitter | Broadcasts growth events | WebSocket + Dragonfly pub/sub: new_person, new_relationship, score_change, anomaly_detected, web_merged |

### 10.3 Perpetual Expansion Algorithm

```
DAEMON LOOP (runs continuously):
    next_task = expansion_queue.pop_highest_priority()

    IF next_task IS expansion:
        person = resolve_identity(next_task.seed)
        related_seeds = crawl_all_sources(person)
        FOR EACH related_seed IN related_seeds:
            related_person = resolve_or_create(related_seed)
            edge = create_or_update_relationship(person, related_person)
            compute_relationship_score(edge)
            compute_person_importance_score(related_person)
            run_behavioural_profiler(related_person)
            IF related_person.importance_score >= min_expansion_threshold:
                expansion_queue.push(related_person, priority=importance_score)
            emit_event(new_relationship, {person, related_person, edge})

    ELIF next_task IS re_crawl:
        person = next_task.person
        old_data = snapshot(person)
        new_data = crawl_all_sources(person)
        diff = compute_diff(old_data, new_data)
        IF diff.has_new_connections:
            FOR EACH new_connection IN diff.new_connections:
                expansion_queue.push(new_connection)
        IF diff.has_changes:
            emit_event(person_updated, {person, changes: diff})
        schedule_next_recrawl(person, ttl_for_source)

    check_budget_limits()
    sleep(crawl_interval)
```

### 10.4 Growth Controls

| Parameter | Default | Description |
|-----------|---------|-------------|
| mode | perpetual | perpetual (never stops), bounded (stops at max_depth), manual (expand on demand) |
| max_depth | unlimited | In bounded mode: max hops. In perpetual: ignored. |
| max_persons_per_hop | 50 | Max new persons queued per single expansion event |
| max_total_persons | 10,000 | Hard ceiling per web. Prevents runaway on celebrity accounts. |
| min_expansion_threshold | 0.25 | Min importance score to queue for expansion. Lower = wider, higher = focused. |
| recrawl_ttl_social | 168h (7d) | Re-crawl interval for social profiles |
| recrawl_ttl_records | 720h (30d) | Re-crawl for company/property/court records |
| recrawl_ttl_sanctions | 24h | Re-check for sanctions/PEP/watchlists |
| daily_api_budget_usd | $10 | Max daily spend on paid APIs. Daemon pauses when exceeded. |
| max_concurrent_crawlers | 5 | Simultaneous Crawlee/Scrapy sessions |
| priority_rel_types | family, business | Relationship types prioritised in expansion queue |
| exclude_platforms | [] | Skip specific platforms (e.g. tiktok) |
| auto_merge_webs | true | Automatically merge webs when bridge persons detected |

### 10.5 Person Importance Scoring

Every person gets an importance score determining expansion priority.

| Factor | Weight | Logic |
|--------|--------|-------|
| Connection count | 0.20 | More connections = likely a hub. Normalised against graph average. |
| Relationship to seed | 0.25 | Direct family/business of seed scores highest. Decays with hop distance. |
| Data richness | 0.15 | Many verified identifiers, active social profiles, public records = higher. |
| Freshness | 0.10 | Recently active profiles score higher than dormant. |
| Cross-platform presence | 0.10 | Present on 3+ platforms = more data to harvest. |
| Risk signals | 0.15 | Sanctions, breach exposure, adverse media boost priority. |
| Manual boost | 0.05 | User can pin/boost specific persons. |

---

## 11. Relationship Scoring Engine

### 11.1 Score Components

| Evidence Type | Max | Weight | Scoring Logic |
|---------------|-----|--------|---------------|
| Declared relationship | 1.0 | 0.30 | Facebook family tag, LinkedIn colleague, WhitePages relative. Type-specific: spouse=1.0, parent/child=0.95, sibling=0.90, colleague=0.70, friend=0.60 |
| Co-tagged in photos | 1.0 | 0.15 | Score = min(tag_count / 10, 1.0). Recency-weighted: last 6mo tags count 2x. |
| Mutual followers | 1.0 | 0.10 | 0.3 base + 0.7 × (shared_mutuals / max(followers_a, followers_b)) |
| Shared address | 1.0 | 0.15 | 1.0 exact match, 0.5 same street, 0.2 same suburb/zip |
| Shared employer | 1.0 | 0.10 | 1.0 if same-period overlap, 0.5 same company different periods |
| Surname match | 1.0 | 0.05 | 1.0 exact + same city, 0.5 exact only, 0.2 phonetic (Soundex/Metaphone) |
| Communication signals | 1.0 | 0.10 | Public @mentions, comment interactions, shared groups. Frequency-weighted. |
| Co-directorship | 1.0 | 0.05 | 1.0 current, 0.5 historical |

### 11.2 Score Tiers

| Score Range | Label | Meaning |
|-------------|-------|---------|
| 0.90–1.00 | **CRITICAL** | Immediate family, business partner, romantic partner. Multiple evidence types. |
| 0.70–0.89 | **STRONG** | Extended family, close friends, frequent collaborators. 3+ evidence types. |
| 0.50–0.69 | **MODERATE** | Colleagues, acquaintances with multiple touchpoints. 2–3 evidence types. |
| 0.25–0.49 | **WEAK** | Single evidence type, or indirect signals. Mutual followers only. |
| 0.00–0.24 | **TENUOUS** | Very weak. May be noise. Same group membership, single public interaction. |

### 11.3 Score Evolution

Scores evolve continuously as the daemon discovers new evidence or detects decay:
- **Increase**: New co-tag, new shared address, new mutual follower, declared relationship appears
- **Decrease (decay)**: No interactions in 6 months, unfollow, employer no longer current, address change
- **History**: Every change logged in relationship_score_history with timestamp, delta, evidence, trigger
- **Trend**: Dashboard shows rising / stable / declining arrow based on 30-day delta

### 11.4 Relationship Classification

| Classification | Evidence Pattern | Confidence |
|----------------|-----------------|------------|
| Spouse / Partner | Declared + shared address + frequent co-tags + surname match | High if 3+ signals |
| Parent / Child | Declared family + age gap 18–45y + shared surname + shared address | High with age + surname |
| Sibling | Declared family + similar age + shared surname + shared historical address | High with surname + age |
| Business Associate | Co-directorship + shared employer + LinkedIn connection + no family signals | High with registry data |
| Close Friend | Frequent co-tags + mutual follows + comment interactions + no family/work signals | Moderate — inferred |
| Romantic Interest | Frequent 1-on-1 co-tags + emoji interactions + recent connection + no family surname | Low — speculative |

---

## 12. Web Visualisation & Dashboard

### 12.1 Graph Rendering

- **Engine**: Sigma.js for large graphs (10K+ nodes, WebGL), D3.js for focused views
- **Nodes**: Sized by importance score. Coloured by role: seed=gold, family=red, business=blue, friend=green, unknown=grey. Profile photo on hover. Behavioural badges (gambling chip icon, crypto icon, etc.) shown on flagged persons.
- **Edges**: Thickness = relationship score. Colour = relationship type. Animated pulse for new evidence. Dashed for TENUOUS (<0.25).
- **Layouts**: Force-directed (default), Hierarchical (concentric rings from seed), Timeline (x=discovery time), Geographic (world map)

### 12.2 Real-Time Growth Animation

- **New node**: Fades in with pulse, positioned near strongest connection
- **New edge**: Animated line drawing from source to target
- **Score change**: Edge thickness smoothly transitions
- **Web merger**: Zoom out, animate merge
- **Live counter**: Total persons, relationships, active crawlers, growth rate (persons/hour)

### 12.3 Scoring Overlays

Toggle-able visual overlays:

| Overlay | Colours | Purpose |
|---------|---------|---------|
| Relationship Strength | Red (critical) → Orange → Blue → Grey (tenuous) | See strongest/weakest connections |
| Person Importance | Large/bright → small/dim | Identify hubs |
| Data Completeness | Green → Yellow → Red | See who needs more enrichment |
| Risk Score | Red (high) → Green (clean) | Sanctions, breach, adverse media heat map |
| Staleness | Green (fresh) → Red (stale) | What's due for re-crawl |
| Behavioural Flags | Custom icons per dimension | Gamblers, crypto, PEP at a glance |
| Cluster Detection | Auto-coloured (Louvain algorithm) | Tightly-knit groups |

### 12.4 Interactive Features

- **Click node**: Full person dossier panel (identifiers, profiles, addresses, employment, scores, behavioural profile, source attribution)
- **Click edge**: Relationship detail (evidence items, score breakdown, score history chart, classification)
- **Right-click node → Expand Now**: Immediate expansion, bypass queue
- **Right-click node → Pin/Boost**: Priority expansion and re-crawl
- **Right-click node → Freeze**: Stop expansion from this person (for celebrity nodes)
- **Right-click node → Remove**: Exclude person and unique-to-them connections
- **Search box** (persistent): Full-text search, highlights matching node + shortest path from seed
- **Filters panel**: Filter by relationship type, score range, platform, country, depth, tags, behavioural flags
- **Time scrubber**: Slider showing graph state at any historical point

### 12.5 Web Statistics

| Metric | Description |
|--------|-------------|
| Total Persons | Canonical person records in this web |
| Total Relationships | Scored edges |
| Max Depth Reached | Furthest hop from seed |
| Growth Rate | New persons/hour (7-day rolling average) |
| Avg Relationship Score | Mean across all edges |
| Score Distribution | Histogram by tier (Critical/Strong/Moderate/Weak/Tenuous) |
| Platform Coverage | % of persons with Instagram, LinkedIn, phone, email, etc. |
| Countries Represented | Choropleth map of person locations |
| Risk Summary | Count of sanctions hits, breach exposures, PEP status |
| Behavioural Summary | Count of gamblers, crypto traders, high spenders, etc. |
| Stale Nodes | Persons past re-crawl TTL |
| Queue Depth | Persons waiting for expansion or re-crawl |
| API Budget Remaining | Daily usage vs budget, projected exhaustion |
| Active Alerts | Anomalies: profile deletions, changes, sanctions hits |

---

## 13. Alerts & Change Detection

### 13.1 Alert Types

| Alert | Severity | Trigger |
|-------|----------|---------|
| New sanctions hit | CRITICAL | Person matches new OFAC/UN/EU/HMT entry |
| Profile deleted | HIGH | Social profile returns 404/deleted |
| New breach exposure | HIGH | Email or phone in new data breach |
| Identity change detected | HIGH | Name change, username change, profile contradiction |
| Behavioural change | HIGH | Gambling/crypto/risk flag newly detected or escalated |
| New high-value connection | MEDIUM | Connects to person with importance >0.7 or risk flags |
| Score threshold crossed | MEDIUM | Relationship crosses tier boundary (e.g. WEAK→STRONG) |
| Web merger detected | MEDIUM | Two webs overlap via bridge person |
| Location change | LOW | Declared location or geotagged activity shifts |
| Re-crawl anomaly | LOW | >20% follower change, privacy toggle, bio overhaul |

### 13.2 Alert Delivery

- **Dashboard**: Bell icon with count badge, alert panel with severity filtering
- **Telegram bot**: Instant notification with summary and dashboard link
- **Email digest**: Daily summary of all alerts (configurable schedule)
- **WebSocket**: Real-time push to open dashboard sessions
- **Webhook**: POST to configurable URL for external integrations

---

## 14. API Design

### 14.1 Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/v1/search | **Universal search**: accepts raw text, auto-detects type, returns existing match or launches investigation |
| POST | /api/v1/webs | Create new web with seed(s) and growth mode |
| GET | /api/v1/webs/{id} | Web status, growth metrics, score distribution, alert count |
| GET | /api/v1/webs/{id}/graph | Full graph: nodes, edges, scores, importance, depth |
| PATCH | /api/v1/webs/{id}/config | Update growth controls: mode, thresholds, budgets, TTLs |
| POST | /api/v1/webs/{id}/pause | Pause daemon for this web |
| POST | /api/v1/webs/{id}/resume | Resume paused web |
| GET | /api/v1/persons/{id} | Full person dossier with all identifiers |
| GET | /api/v1/persons/{id}/relationships | All relationships with scores |
| GET | /api/v1/persons/{id}/behaviour | Behavioural profile with all signals |
| POST | /api/v1/webs/{id}/persons/{pid}/expand | Force immediate expansion |
| POST | /api/v1/webs/{id}/persons/{pid}/pin | Pin for priority expansion |
| POST | /api/v1/webs/{id}/persons/{pid}/freeze | Stop expansion from this person |
| POST | /api/v1/lookup/phone | Quick phone lookup without full investigation |
| POST | /api/v1/lookup/email | Quick email lookup |
| POST | /api/v1/lookup/social | Quick social handle lookup |
| GET | /api/v1/relationships/{id}/score-history | Score evolution timeline |
| GET | /api/v1/webs/{id}/growth-timeline | Time-series: persons, edges, avg score over time |
| GET | /api/v1/webs/{id}/alerts | Alerts with severity filtering |
| GET | /api/v1/webs/{id}/export | Export as PDF, CSV, JSON, GraphML |
| GET | /api/v1/stats | System: total persons, queue depth, API credits |

### 14.2 WebSocket Events

Real-time via `/ws/webs/{id}`:

- `person_discovered`: New person resolved (name, identifier, depth)
- `relationship_created`: New edge (person_a, person_b, type, score)
- `relationship_scored`: Score updated (old_score, new_score, tier)
- `behaviour_flagged`: New behavioural signal detected (person, dimension, confidence)
- `crawl_progress`: Spider status (pages crawled, errors, queue depth)
- `web_merged`: Two webs bridged
- `alert_created`: New alert (type, severity, summary)
- `investigation_complete`: All queued work finished (bounded mode only)

---

## 15. External API Integrations

| Service | Purpose | Pricing |
|---------|---------|---------|
| NumVerify | Phone validation + carrier | Freemium, 100/mo free |
| AbstractAPI | Phone + email validation | $49/mo for 10K |
| Hunter.io | Email finder + verifier | $49/mo for 1K |
| HIBP | Breach exposure | $3.50/mo per domain |
| Bright Data | Residential proxies | $10.50/GB |
| TrueCaller API | Reverse phone lookup | Enterprise pricing |
| Pipl / FullContact | People data enrichment | $99+/mo |
| Epieos | Email OSINT (Google ID) | Free tier |
| Social Searcher | Social media monitoring | $3.49/mo |
| 2Captcha | CAPTCHA solving | $2.99/1K solves |
| IPinfo.io | IP geolocation | 50K/mo free |
| Sherlock | Username search 400+ sites | Open source |
| Holehe | Email registration check 120+ services | Open source |
| WhatsMyName | Username enumeration | Open source |
| Claude API (Sonnet) | NLP, image analysis, relationship inference | Per-token pricing |

---

## 16. Technology Stack

| Component | Technology | Justification |
|-----------|------------|---------------|
| Language | Python 3.12 | Scrapy/Crawlee native, ML ecosystem |
| API Framework | FastAPI | Async, auto-docs, Pydantic |
| Task Queue | Windmill (Phase 1) → Temporal (Phase 2) | Durable workflows, retry, observability |
| Structured Scraping | Scrapy 2.11+ | Mature, middleware, pipelines |
| Dynamic Scraping | Crawlee (Python) + Playwright | JS rendering, anti-bot, sessions |
| Database | PostgreSQL 16 + Apache AGE | Relational + graph in single engine |
| Vector Search | pgvector | Name/bio embedding similarity |
| Cache | Dragonfly | Redis-compatible, multi-tenant, lower RAM |
| Search | MeiliSearch | Typo-tolerant full-text |
| NLP | spaCy + Claude API (Sonnet) | NER, relationship extraction, image analysis |
| Frontend | React + Sigma.js + D3.js + TailwindCSS | Interactive graph visualisation |
| PDF Reports | WeasyPrint | HTML-to-PDF dossiers |
| Containerisation | Docker + Docker Compose | Deployable on home server or cloud |
| Reverse Proxy | Nginx Proxy Manager | SSL termination, routing |
| Monitoring | Uptime Kuma + Portainer | Health checks, container management |
| Access | Tailscale | Zero-config VPN for remote access |

---

## 17. Deployment

### 17.1 Docker Compose Services

| Service | Port | Image | Notes |
|---------|------|-------|-------|
| lycan-api | 8100 | Custom (FastAPI) | Main API + WebSocket |
| lycan-crawler | - | Custom (Scrapy/Crawlee) | Crawl worker pool (scale: 3) |
| lycan-resolver | - | Custom (Python) | Identity resolution worker |
| lycan-daemon | - | Custom (Python) | Continuous growth engine (always-on) |
| lycan-ui | 3100 | Custom (React) | Dashboard + graph viewer |
| postgres | 5432 | postgres:16-alpine + AGE | Primary datastore |
| dragonfly | 6379 | dragonflydb/dragonfly | Cache + job queue + event bus |
| meilisearch | 7700 | getmeili/meilisearch | Full-text search |
| playwright | - | mcr.microsoft.com/playwright | Shared browser pool |

### 17.2 Resource Estimates (Home Server)

Target: ASUS Gryphon Z87, i7-4770, 32GB DDR3, Ubuntu 22.04 via Tailscale (100.67.202.94).

- PostgreSQL: 2GB RAM, 50GB+ SSD
- Dragonfly: 512MB RAM
- MeiliSearch: 512MB RAM, 10GB SSD
- Crawler workers (×3): 2GB RAM total (Playwright browsers)
- API + Resolver + Daemon: 1.5GB RAM
- **Total baseline: ~6.5GB RAM**, leaving headroom for other services

---

## 18. Development Roadmap

### Phase 1: Foundation (Weeks 1–4)

- shared/ layer: models, schemas, config, event bus, db
- PostgreSQL schema + Alembic migrations
- FastAPI skeleton with JWT auth
- Ingestion module: universal parser + all validators
- Phone enrichment pipeline (libphonenumber + NumVerify + HLR)
- Email enrichment pipeline (MX + SMTP + HIBP + Holehe)
- Identity resolution v1 (exact match)
- Docker Compose on home server
- **Test milestone**: Feed a phone number → get name, carrier, country, breach status

### Phase 2: Social Intelligence (Weeks 5–8)

- Crawlee + Playwright setup with proxy rotation
- InstagramActor: full profile + posts + tagged + phone/email extraction
- TwitterActor: profile + tweets + connections
- FacebookActor: public profile scraping
- Username search (Sherlock + WhatsMyName)
- Recursive graph expansion engine
- React frontend: SearchBox + GraphView
- **Test milestone**: Search an Instagram handle → see person + tagged connections in graph

### Phase 3: Scoring & Behaviour (Weeks 9–12)

- Relationship scoring engine (all evidence types)
- Person importance scoring
- Score history tracking + trend computation
- Behavioural profiling engine
- Gambling detection pipeline
- Crypto/luxury/PEP/risk detection
- Curated account database (initial seed: 5K accounts)
- Dashboard: score overlays, behavioural badges, filters
- **Test milestone**: Graph shows scored edges with colour-coding, gambler badges on flagged persons

### Phase 4: Growth & Intelligence (Weeks 13–16)

- Growth daemon: expansion scheduler + re-crawl + budget controller
- Web merger for cross-investigation bridging
- Alert engine + Telegram bot delivery
- LinkedInActor with session management
- Company registry + sanctions spiders
- Claude API for relationship inference + bet slip detection
- Fuzzy resolution with pgvector embeddings
- WebSocket real-time streaming
- Time scrubber for historical graph states
- PDF dossier generation
- Full export suite (JSON, CSV, GraphML, Maltego)
- **Test milestone**: Plant a seed, leave it overnight, come back to a web of 100+ persons with scored relationships and behavioural profiles

---

## 19. Security & Access Control

- All access via Tailscale VPN only — no public exposure
- API authentication: JWT bearer tokens with configurable expiry
- Role-based access: admin (full), analyst (read + create), viewer (read only)
- Encryption at rest: PostgreSQL TDE or LUKS volume encryption
- Audit log: Every API call, crawl action, data access logged
- Data retention: Configurable auto-purge (default 90d for crawl logs, indefinite for persons)
- Proxy credentials: Docker secrets, never environment variables
- API keys for third-party services: Rotated via Windmill secrets manager

---

## 20. Legal & Compliance

- System designed for processing publicly available information only
- **POPIA (South Africa)**: Comply with lawful purpose requirements for SA persons' data
- **GDPR (EU)**: Lawful basis, data minimisation, right to erasure if processing EU subjects
- **CCPA (US/California)**: Honour opt-out and do-not-sell requests
- **CFAA (US)**: Respect robots.txt and ToS; no credential stuffing or unauthorised access
- **Platform ToS**: Instagram/LinkedIn/Facebook scraping may violate ToS — browser automation reduces detection, accept operational risk
- **Data retention**: Configurable auto-deletion for compliance
- **Access logging**: Full audit trail for lawful access demonstration

---

## 21. Appendix

### A. Identifier Types
phone, email, instagram, twitter, linkedin, telegram, facebook, tiktok, whatsapp, website, national_id, passport, company_reg, tax_id, vehicle_reg

### B. Relationship Types
family, spouse, parent, child, sibling, friend, colleague, business_associate, romantic, co_tagged, mutual_follower, co_resident, co_director, classmate, unknown

### C. Behavioural Dimensions
gambling, crypto, high_spender, pep, adult_content, substance, risk

### D. Crawl Statuses
queued, running, completed, failed, rate_limited, blocked, captcha_required, skipped

### E. Alert Types
sanctions_hit, profile_deleted, breach_exposure, identity_change, behavioural_change, new_connection, score_threshold, web_merger, location_change, recrawl_anomaly

### F. Score Tiers
CRITICAL (0.90–1.00), STRONG (0.70–0.89), MODERATE (0.50–0.69), WEAK (0.25–0.49), TENUOUS (0.00–0.24)

### G. National ID Parsers
- **South Africa (RSA ID)**: 13 digits — DOB (YYMMDD), gender (digits 7–10), citizenship, Luhn checksum
- **United States (SSN)**: Format validation only
- **United Kingdom (NI Number)**: Format + prefix/suffix rules
- **Israel (Teudat Zehut)**: 9 digits, Luhn-variant check digit

### H. Google Dork Templates
- Name: `"John Doe" site:linkedin.com | site:facebook.com | site:instagram.com`
- Email: `"@domain.com" "john doe"`
- Documents: `"john doe" filetype:pdf | filetype:xlsx | filetype:docx`
- Phone: `"john doe" "+27" | "082" | "083"`
- Cached: `cache:targetdomain.com/profile`

---

**— END OF SPECIFICATION —**
