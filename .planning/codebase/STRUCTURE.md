# Codebase Structure

**Analysis Date:** 2026-03-30

## Directory Layout

```
Lycan-Data/
├── api/                    # FastAPI application server
│   ├── main.py             # App factory, middleware, router registration
│   ├── deps.py             # Dependency injection (DB session, API key auth)
│   ├── serializers.py      # Response serialization helpers
│   └── routes/             # API route modules (one file per domain)
│       ├── search.py       # POST /search/ — seed-based investigation launch
│       ├── persons.py      # CRUD, merge, dedup for person records
│       ├── crawls.py       # Crawl job management
│       ├── enrichment.py   # Enrichment triggers
│       ├── graph.py        # Entity relationship graphs
│       ├── knowledge_graph.py  # Knowledge graph queries
│       ├── financial.py    # Financial intelligence
│       ├── patterns.py     # Anomaly/temporal patterns
│       ├── behavioural.py  # Behavioural profiling
│       ├── watchlist.py    # Sanctions/watchlist monitoring
│       ├── alerts.py       # Alert management
│       ├── compliance.py   # Compliance endpoints
│       ├── discovery.py    # Source discovery
│       ├── builder.py      # Criteria-based list building
│       ├── export.py       # Data export (GEDCOM, etc.)
│       ├── dedup.py        # Deduplication management
│       ├── relationships.py # Relationship CRUD
│       ├── marketing.py    # Marketing intelligence
│       ├── audit.py        # Audit log queries
│       ├── search_query.py # Advanced search/query
│       ├── system.py       # Health checks, admin endpoints
│       └── ws.py           # WebSocket + SSE real-time progress
├── modules/                # Business logic modules
│   ├── crawlers/           # Scraper framework (150+ crawlers)
│   │   ├── base.py         # BaseCrawler abstract class
│   │   ├── registry.py     # @register decorator + CRAWLER_REGISTRY
│   │   ├── core/           # Framework internals
│   │   │   ├── models.py   # CrawlerCategory, RateLimit, CrawlerHealth
│   │   │   ├── result.py   # CrawlerResult dataclass
│   │   │   └── orchestrator.py  # ScraperOrchestrator (concurrent runner)
│   │   ├── utils.py        # Crawler utility functions
│   │   ├── db_writer.py    # Direct DB write helpers for crawlers
│   │   ├── httpx_base.py   # Base for httpx-based crawlers
│   │   ├── curl_base.py    # Base for curl-cffi crawlers
│   │   ├── playwright_base.py   # Base for Playwright browser crawlers
│   │   ├── camoufox_base.py     # Base for Camoufox stealth browser
│   │   ├── flaresolverr_base.py # Base for FlareSolverr-backed crawlers
│   │   ├── instagram.py    # Instagram scraper
│   │   ├── twitter.py      # Twitter/X scraper
│   │   ├── facebook.py     # Facebook scraper
│   │   ├── linkedin.py     # LinkedIn scraper
│   │   ├── telegram.py     # Telegram scraper
│   │   ├── tiktok.py       # TikTok scraper
│   │   ├── whatsapp.py     # WhatsApp scraper
│   │   ├── sanctions_ofac.py    # OFAC sanctions
│   │   ├── sanctions_eu.py      # EU sanctions
│   │   ├── sanctions_un.py      # UN sanctions
│   │   ├── ... (130+ more crawler files)
│   │   ├── gov/            # Government database crawlers
│   │   ├── genealogy/      # Genealogy source crawlers
│   │   ├── media/          # Media/news crawlers
│   │   ├── pep/            # Politically Exposed Person crawlers
│   │   ├── property/       # Property record crawlers
│   │   ├── social/         # Additional social platform crawlers
│   │   ├── transport/      # Aircraft/vessel registry crawlers
│   │   └── monitoring/     # Monitoring crawlers
│   ├── dispatcher/         # Job queue processing
│   │   ├── dispatcher.py   # CrawlDispatcher — dequeue + run crawlers
│   │   ├── growth_daemon.py     # Auto-enqueues follow-up jobs from new identifiers
│   │   ├── freshness_scheduler.py # Re-queues stale records
│   │   └── pending_recovery.py  # Recovers stuck pending jobs
│   ├── pipeline/           # Data aggregation pipeline
│   │   ├── aggregator.py   # Routes CrawlerResult to correct DB tables
│   │   ├── ingestion_daemon.py  # Queue consumer for DB writes
│   │   ├── enrichment_orchestrator.py # Runs all enrichers sequentially
│   │   ├── pivot_enricher.py    # Discovers new identifiers, queues recursive searches
│   │   └── progress_tracker.py  # Tracks per-search progress state
│   ├── enrichers/          # Post-crawl intelligence engines
│   │   ├── financial_aml.py     # AML risk scoring
│   │   ├── marketing_tags.py    # Consumer segment tagging
│   │   ├── deduplication.py     # Record deduplication
│   │   ├── auto_dedup.py        # Automatic dedup daemon
│   │   ├── ml_dedup.py          # ML-based deduplication
│   │   ├── graph_dedup.py       # Graph-based dedup
│   │   ├── entity_resolution.py # Cross-source entity matching
│   │   ├── golden_record.py     # Canonical record builder
│   │   ├── confidence_scorer.py # Confidence/reliability scoring
│   │   ├── cascade_enricher.py  # Cascading enrichment chains
│   │   ├── biographical.py      # Bio extraction
│   │   ├── psychological.py     # Psychological profiling
│   │   ├── burner_detector.py   # Burner phone detection
│   │   ├── location_enricher.py # Geolocation enrichment
│   │   ├── timeline_builder.py  # Activity timeline construction
│   │   ├── verification.py      # Data verification
│   │   ├── data_verifiers.py    # Cross-source verification
│   │   ├── ranking.py           # Result ranking
│   │   ├── certification.py     # Professional cert lookups
│   │   ├── commercial_tagger.py # Commercial intelligence daemon
│   │   ├── genealogy_enricher.py # Family tree enrichment daemon
│   │   ├── property_enricher.py  # Property/asset enrichment daemon
│   │   ├── pep_enricher.py      # PEP classification daemon
│   │   └── adverse_media_enricher.py # Adverse media monitor daemon
│   ├── graph/              # Relationship graph engines
│   │   ├── entity_graph.py      # Person-centred multi-hop graph builder
│   │   ├── knowledge_graph.py   # Knowledge graph construction
│   │   ├── company_intel.py     # Company intelligence / UBO
│   │   ├── relationship_expansion.py # Graph expansion
│   │   ├── saturation_crawler.py    # Network saturation (depth crawling)
│   │   └── ubo_discovery.py    # Ultimate Beneficial Owner discovery
│   ├── search/             # Search/indexing
│   │   ├── typesense_indexer.py # Typesense HTTP client + schema definitions
│   │   └── index_daemon.py      # Queue consumer: PostgreSQL -> Typesense sync
│   ├── patterns/           # Pattern analysis
│   │   ├── anomaly.py      # Anomaly detection
│   │   ├── temporal.py     # Temporal pattern analysis
│   │   └── inverted_index.py # Inverted index for fast lookups
│   ├── builder/            # List building
│   │   ├── criteria_router.py   # Routes criteria to query builders
│   │   ├── discovery_engine.py  # Discovers persons matching criteria
│   │   └── filters.py          # Filter definitions
│   ├── discovery/          # Source discovery
│   │   ├── base.py         # Discovery base class
│   │   ├── orchestrator.py # Discovery orchestration
│   │   ├── crawler_builder.py # Dynamic crawler generation
│   │   └── tools.py        # Discovery tools
│   ├── audit/              # System auditing
│   │   └── audit_daemon.py # Periodic platform health snapshots
│   └── export/             # Export formats
│       └── gedcom.py       # GEDCOM genealogy export
├── shared/                 # Cross-cutting shared code
│   ├── config.py           # Pydantic Settings (env vars, .env file)
│   ├── db.py               # SQLAlchemy async engine + session factory
│   ├── events.py           # EventBus (Redis pub/sub + job queues)
│   ├── tor.py              # TorManager (3 Tor instance management)
│   ├── constants.py        # Enums: SeedType, IdentifierType, Platform, RelType, etc.
│   ├── cache.py            # Application caching helpers
│   ├── circuit_breaker.py  # Per-crawler circuit breaker
│   ├── rate_limiter.py     # Rate limiting logic
│   ├── proxy_pool.py       # Residential/datacenter proxy management
│   ├── data_quality.py     # Quality scoring functions
│   ├── freshness.py        # Freshness/staleness detection
│   ├── health.py           # Health check utilities
│   ├── transport_registry.py # Transport type registry
│   ├── models/             # SQLAlchemy ORM models (40+ tables)
│   │   ├── base.py         # DeclarativeBase, TimestampMixin, DataQualityMixin
│   │   ├── person.py       # Person + Alias (central entity)
│   │   ├── identifier.py   # Identifier (phone, email, username, etc.)
│   │   ├── social_profile.py # SocialProfile
│   │   ├── relationship.py  # Relationship + score history
│   │   ├── crawl.py         # CrawlJob, CrawlLog, DataSource
│   │   ├── address.py       # Address
│   │   ├── employment.py    # EmploymentHistory
│   │   ├── education.py     # Education
│   │   ├── criminal.py      # CriminalRecord
│   │   ├── darkweb.py       # DarkwebMention, CryptoWallet, CryptoTransaction
│   │   ├── breach.py        # BreachRecord
│   │   ├── property.py      # Property, Mortgage, Valuation, Ownership
│   │   ├── vehicle.py       # Vehicle, Aircraft, Vessel
│   │   ├── compliance_ext.py # PepClassification, AdverseMedia, ShellCompanyLink
│   │   ├── professional.py  # ProfessionalLicense, CorporateDirectorship, MilitaryRecord
│   │   ├── intelligence.py  # PhoneIntelligence, EmailIntelligence, IpIntelligence
│   │   ├── marketing.py     # MarketingTag, ConsumerSegment, TicketSize
│   │   ├── behavioural.py   # BehaviouralProfile, BehaviouralSignal
│   │   ├── watchlist.py     # WatchlistMatch
│   │   ├── wealth.py        # WealthAssessment
│   │   ├── audit.py         # AuditLog, SystemAudit, AuditRequestLog
│   │   ├── alert.py         # Alert
│   │   ├── quality.py       # DataQualityLog, FreshnessQueue
│   │   ├── progress.py      # SearchProgress
│   │   ├── timeline.py      # TimelineEvent, AnalystAssessment, TravelHistory
│   │   ├── family_tree.py   # FamilyTreeSnapshot
│   │   ├── builder_job.py   # BuilderJob, BuilderJobPerson
│   │   ├── discovery.py     # DiscoveredSource
│   │   ├── ... and more
│   │   └── __init__.py      # Re-exports all models
│   ├── schemas/            # Pydantic request/response schemas
│   │   ├── seed.py         # SeedInput (search input)
│   │   ├── person.py       # Person API schemas
│   │   ├── relationship.py # Relationship schemas
│   │   ├── alert.py        # Alert schemas
│   │   ├── progress.py     # EventType enum for progress events
│   │   └── web.py          # Web-related schemas
│   └── utils/              # Utility functions
│       ├── phone.py        # Phone number normalization
│       ├── email.py        # Email validation/normalization
│       ├── social.py       # Social handle extraction
│       └── scoring.py      # Scoring helpers
├── migrations/             # Alembic database migrations
│   └── versions/           # 16 migration scripts
├── tests/                  # Test suite (mirrors module structure)
│   ├── test_api/           # API route tests
│   ├── test_crawlers/      # Crawler tests
│   ├── test_enrichers/     # Enricher tests
│   ├── test_pipeline/      # Pipeline tests
│   ├── test_graph/         # Graph tests
│   ├── test_search/        # Search tests
│   ├── test_dispatcher/    # Dispatcher tests
│   ├── test_builder/       # Builder tests
│   ├── test_models/        # Model tests
│   ├── test_shared/        # Shared utility tests
│   ├── test_patterns/      # Pattern tests
│   ├── test_modules/       # Module integration tests
│   ├── test_daemon/        # Daemon tests
│   ├── test_darkweb/       # Dark web crawler tests
│   ├── test_enrichment/    # Enrichment tests
│   └── test_government/    # Government crawler tests
├── static/                 # SPA frontend (served by FastAPI)
├── scripts/                # Deployment/admin scripts
│   ├── entrypoint.sh       # Docker entrypoint
│   └── audit.py            # Audit script
├── reports/                # Generated reports output
├── docs/                   # Documentation
│   └── superpowers/        # Feature specs and plans
├── worker.py               # Background worker entry point
├── lycan.py                # CLI search runner
├── alembic.ini             # Alembic migration config
├── pyproject.toml          # Python project config
├── docker-compose.yml      # Production Docker stack
└── docker-compose.dev.yml  # Development Docker overrides
```

## Directory Purposes

**`api/`:**
- Purpose: All HTTP-facing code
- Contains: FastAPI router modules, authentication dependencies, middleware
- Key files: `api/main.py` (app factory), `api/deps.py` (DI), `api/routes/search.py` (primary search endpoint)

**`modules/crawlers/`:**
- Purpose: Scraper plugins organized by data source type
- Contains: 150+ individual crawler files, base classes for different HTTP strategies, core framework
- Key files: `base.py` (BaseCrawler), `registry.py` (CRAWLER_REGISTRY), `core/result.py` (CrawlerResult)

**`modules/dispatcher/`:**
- Purpose: Queue-to-crawler execution and auto-growth
- Contains: Dispatcher workers, growth daemon, freshness scheduler
- Key files: `dispatcher.py` (CrawlDispatcher), `growth_daemon.py` (recursive expansion)

**`modules/pipeline/`:**
- Purpose: Data normalization and write path
- Contains: Aggregator (CrawlerResult to DB), ingestion daemon, enrichment orchestrator, pivot enricher
- Key files: `aggregator.py` (the big switch that routes results to tables), `ingestion_daemon.py`

**`modules/enrichers/`:**
- Purpose: Intelligence engines that run after crawling completes
- Contains: AML scoring, dedup (4 strategies), entity resolution, profiling, tagging
- Key files: `financial_aml.py`, `deduplication.py`, `auto_dedup.py`, `marketing_tags.py`

**`shared/models/`:**
- Purpose: SQLAlchemy ORM model definitions for all database tables
- Contains: 40+ model files, one per domain entity
- Key files: `person.py` (central entity), `base.py` (Base + mixins), `crawl.py` (CrawlJob), `identifier.py`

**`shared/schemas/`:**
- Purpose: Pydantic models for API request/response validation
- Contains: Input schemas for seeds, persons, alerts, relationships
- Key files: `seed.py` (SeedInput), `person.py`, `progress.py` (EventType)

## Key File Locations

**Entry Points:**
- `api/main.py`: FastAPI application instance
- `worker.py`: Background worker process (all daemons)
- `lycan.py`: CLI tool for direct searches

**Configuration:**
- `shared/config.py`: All settings via Pydantic BaseSettings (reads .env)
- `alembic.ini`: Migration configuration
- `docker-compose.yml`: Full infrastructure stack definition
- `pyproject.toml`: Python project metadata

**Core Logic:**
- `modules/pipeline/aggregator.py`: Maps CrawlerResult types to DB tables (largest single file)
- `modules/dispatcher/dispatcher.py`: Queue-driven crawl job execution
- `modules/crawlers/base.py`: BaseCrawler with retry, circuit breaking, human simulation
- `modules/crawlers/registry.py`: Self-registration pattern for crawlers
- `shared/events.py`: EventBus pub/sub + queue abstraction

**Testing:**
- `tests/`: Mirrors the module structure with `test_` prefix directories

## Naming Conventions

**Files:**
- Snake_case for all Python files: `financial_aml.py`, `growth_daemon.py`
- Crawlers named by `{source}_{platform}.py` or just `{platform}.py`: `sanctions_ofac.py`, `instagram.py`, `email_hibp.py`
- Models named by domain entity: `person.py`, `criminal.py`, `property.py`

**Directories:**
- Lowercase snake_case: `modules/crawlers/`, `shared/models/`
- Crawler subdirectories by category: `gov/`, `genealogy/`, `property/`, `pep/`, `social/`, `transport/`, `media/`, `monitoring/`

**Classes:**
- PascalCase: `BaseCrawler`, `CrawlDispatcher`, `IngestionDaemon`, `EnrichmentOrchestrator`
- Crawlers: `{Platform}Crawler` (e.g., `InstagramCrawler`, `OfacSanctionsCrawler`)
- Models: Domain noun (e.g., `Person`, `CrawlJob`, `SocialProfile`)
- Daemons: `{Function}Daemon` (e.g., `IngestionDaemon`, `IndexDaemon`, `AuditDaemon`)

**Constants/Enums:**
- StrEnum classes in `shared/constants.py`: `SeedType`, `IdentifierType`, `Platform`, `RelType`, `CrawlStatus`

## Where to Add New Code

**New Crawler:**
- Create `modules/crawlers/{platform_name}.py`
- Extend `BaseCrawler`, implement `async def scrape(self, identifier: str) -> CrawlerResult`
- Apply `@register("platform_name")` decorator
- Set `platform`, `category`, `source_reliability`, `requires_tor`, `proxy_tier`
- The crawler auto-registers at startup via `_import_all_crawlers()` in `api/main.py` and `worker.py`
- Add platform to `SEED_PLATFORM_MAP` in `api/routes/search.py` and `PLATFORM_ACCEPTS` in `modules/dispatcher/growth_daemon.py`

**New API Route:**
- Create `api/routes/{domain}.py` with `router = APIRouter()`
- Import and register in `api/main.py`: `app.include_router(module.router, prefix="/path", tags=["tag"], dependencies=_auth)`

**New Database Table:**
- Create model in `shared/models/{entity}.py` extending `Base` + `TimestampMixin` + optionally `DataQualityMixin`
- Import in `shared/models/__init__.py`
- Create Alembic migration: `alembic revision --autogenerate -m "description"`

**New Enricher:**
- Create `modules/enrichers/{enricher_name}.py`
- If it runs as a background daemon, add it to `worker.py` with a `--no-{name}` CLI flag
- If it runs as part of the enrichment pipeline, register it in `modules/pipeline/enrichment_orchestrator.py`

**New Pydantic Schema:**
- Create in `shared/schemas/{domain}.py`
- Use in API route for request validation

**New Background Daemon:**
- Create in the appropriate `modules/` subdirectory
- Implement `start()` and `stop()` async methods
- Register in `worker.py` with optional enable/disable flag

## Special Directories

**`migrations/`:**
- Purpose: Alembic database migration scripts
- Generated: Yes (via `alembic revision --autogenerate`)
- Committed: Yes

**`static/`:**
- Purpose: Frontend SPA files served by FastAPI
- Generated: No (manually maintained)
- Committed: Yes

**`reports/`:**
- Purpose: Output directory for generated reports
- Generated: Yes (at runtime)
- Committed: Directory structure only

**`.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`:**
- Purpose: Tool caches
- Generated: Yes
- Committed: No (should be in .gitignore)

---

*Structure analysis: 2026-03-30*
