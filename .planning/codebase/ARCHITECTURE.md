# Architecture

**Analysis Date:** 2026-03-30

## Pattern Overview

**Overall:** Event-driven pipeline with async workers

**Key Characteristics:**
- Two-process model: FastAPI API server + background worker process
- Redis-compatible queue (Garnet) as the message bus between API and workers
- Self-registering crawler framework with 150+ scrapers auto-discovered at startup
- Recursive enrichment: crawl results produce new identifiers that trigger follow-up crawl jobs
- PostgreSQL as the single source of truth, Typesense for full-text search indexing

## Layers

**API Layer:**
- Purpose: HTTP REST + WebSocket interface for clients
- Location: `api/`
- Contains: FastAPI routers, auth dependency, serializers, rate limiting
- Depends on: `shared/`, `modules/` (for dispatching jobs and querying)
- Used by: External clients (browser SPA at `static/index.html`, API consumers)
- Entry: `api/main.py` creates the FastAPI `app` instance

**Shared Layer:**
- Purpose: Cross-cutting concerns shared by API and workers
- Location: `shared/`
- Contains: SQLAlchemy models (`shared/models/`), Pydantic schemas (`shared/schemas/`), config, DB sessions, event bus, Tor manager, rate limiter, circuit breaker, data quality, caching
- Depends on: External libraries (SQLAlchemy, Pydantic, redis.asyncio, stem)
- Used by: Everything (API, modules, workers)

**Crawler Framework:**
- Purpose: Self-registering scraper plugins for 150+ data sources
- Location: `modules/crawlers/`
- Contains: `BaseCrawler` abstract class (`modules/crawlers/base.py`), registry (`modules/crawlers/registry.py`), core models (`modules/crawlers/core/`), individual crawler implementations
- Depends on: `shared/` (config, Tor, events), HTTP clients (httpx, patchright/playwright, curl-cffi)
- Used by: Dispatcher workers

**Dispatcher Layer:**
- Purpose: Queue-driven job execution engine
- Location: `modules/dispatcher/`
- Contains: `CrawlDispatcher` (pulls jobs from queues, runs crawlers), `GrowthDaemon` (auto-enqueues follow-up jobs), `FreshnessScheduler` (re-queues stale records), `PendingJobRecovery`
- Depends on: `modules/crawlers/`, `shared/events`, `shared/db`
- Used by: Worker process (`worker.py`)

**Pipeline Layer:**
- Purpose: Aggregates crawler output into normalized database records
- Location: `modules/pipeline/`
- Contains: `aggregate_result` (routes CrawlerResult to correct DB tables), `IngestionDaemon` (queue consumer for DB writes), `EnrichmentOrchestrator` (runs all enrichers sequentially), `PivotEnricher` (discovers new identifiers from results, queues recursive searches), `ProgressTracker`
- Depends on: `shared/models/`, `shared/events`, `modules/enrichers/`
- Used by: Worker process (ingestion daemons)

**Enricher Layer:**
- Purpose: Post-crawl intelligence processing (scoring, tagging, dedup, AML)
- Location: `modules/enrichers/`
- Contains: Financial AML engine (`financial_aml.py`), marketing tags (`marketing_tags.py`), deduplication (`deduplication.py`, `auto_dedup.py`, `ml_dedup.py`, `graph_dedup.py`), entity resolution, confidence scoring, biographical/psychological profiling, genealogy, property, PEP, adverse media enrichers
- Depends on: `shared/models/`, `shared/db`
- Used by: Pipeline layer, worker daemons

**Graph Layer:**
- Purpose: Relationship graph construction and analysis
- Location: `modules/graph/`
- Contains: `EntityGraphBuilder` (person-centred multi-hop graphs), `KnowledgeGraphBuilder`, `CompanyIntelligenceEngine` (UBO discovery), `SaturationCrawler` (network expansion)
- Depends on: `shared/models/`
- Used by: API routes (`/graph`, `/kg`)

**Search Layer:**
- Purpose: Full-text + faceted search via Typesense
- Location: `modules/search/`
- Contains: `TypesenseIndexer` (CRUD against Typesense HTTP API), `IndexDaemon` (queue consumer that syncs PostgreSQL to Typesense), `build_person_doc` helper
- Depends on: `shared/config`, `shared/events`, `shared/models/`
- Used by: API routes (`/search`, `/query`), worker process

**Patterns Layer:**
- Purpose: Anomaly detection and temporal analysis
- Location: `modules/patterns/`
- Contains: `anomaly.py`, `temporal.py`, `inverted_index.py`
- Used by: API routes (`/patterns`)

**Builder Layer:**
- Purpose: Criteria-based person list building
- Location: `modules/builder/`
- Contains: `criteria_router.py`, `discovery_engine.py`, `filters.py`
- Used by: API routes (`/builder`)

**Export Layer:**
- Purpose: Data export in various formats
- Location: `modules/export/`
- Contains: `gedcom.py` (GEDCOM genealogy format)
- Used by: API routes (`/export`)

## Data Flow

**Search-to-Enrichment Pipeline (core flow):**

1. Client sends search request to `POST /search/` with a seed (phone, email, username, name, etc.)
2. API route (`api/routes/search.py`) creates a `Person` record in PostgreSQL and maps the seed type to applicable crawler platforms via `SEED_PLATFORM_MAP`
3. For each applicable platform, API calls `dispatch_job()` which creates a `CrawlJob` DB record and enqueues the job onto a Garnet priority queue (high/normal/low) via `event_bus.enqueue()`
4. Worker process `CrawlDispatcher` (`modules/dispatcher/dispatcher.py`) dequeues jobs from Garnet using `event_bus.dequeue_any()`, looks up the registered crawler via `get_crawler(platform)`, and runs `crawler.run(identifier)`
5. Crawler returns a `CrawlerResult` dataclass. Dispatcher serializes it and pushes to the `ingest` queue
6. `IngestionDaemon` (`modules/pipeline/ingestion_daemon.py`) dequeues from `ingest`, calls `aggregate_result()` to write data into the correct PostgreSQL tables (social profiles, identifiers, addresses, breaches, etc.)
7. `PivotEnricher` (`modules/pipeline/pivot_enricher.py`) extracts newly discovered identifiers (email, phone, name) from the result and dispatches follow-up crawl jobs (recursive expansion)
8. When all crawl jobs for a person reach terminal state, `EnrichmentOrchestrator` runs all enrichers sequentially (AML scoring, marketing tags, dedup, etc.)
9. After aggregation, a signal is pushed to the `index` queue. `IndexDaemon` (`modules/search/index_daemon.py`) reads person state from PostgreSQL and upserts a document into Typesense

**Real-time Progress:**

1. Throughout the pipeline, progress events are published via `event_bus.publish("progress", ...)`
2. WebSocket endpoint (`api/routes/ws.py`) subscribes to progress channel and streams events to connected clients
3. `ProgressAggregator` (`modules/pipeline/progress_tracker.py`) maintains per-search state

**Growth/Freshness Loop:**

1. `GrowthDaemon` listens on the `enrichment` event channel for `crawl_complete` events
2. When new identifiers are found, it enqueues follow-up crawl jobs respecting `MAX_DEPTH` (default 4), `MAX_FANOUT_PER_PERSON` (50), and `MAX_DAILY_GROWTH_JOBS` (5000)
3. `FreshnessScheduler` periodically scans for stale person records and re-enqueues crawl jobs based on `freshness_threshold` config

**State Management:**
- PostgreSQL is the authoritative data store for all person records, identifiers, social profiles, and crawl job state
- Garnet (Redis-compatible) serves as the message queue (priority queues for crawl jobs, ingest, index) and pub/sub bus for events
- Typesense mirrors a denormalized view of persons for search
- All state transitions flow through the event bus -- no direct inter-daemon communication

## Key Abstractions

**Person:**
- Purpose: Central entity that all intelligence data links to
- Definition: `shared/models/person.py` -- SQLAlchemy model with 60+ columns and 40+ relationships
- Pattern: Star schema hub -- every data table (identifiers, social profiles, addresses, criminal records, etc.) has a `person_id` FK

**CrawlerResult:**
- Purpose: Standardized output from every scraper
- Definition: `modules/crawlers/core/result.py` -- Python dataclass
- Pattern: Uniform interface across 150+ crawlers. Contains `platform`, `identifier`, `found`, `data` dict, `source_reliability`

**BaseCrawler:**
- Purpose: Abstract base class for all scrapers
- Definition: `modules/crawlers/base.py`
- Pattern: Template method. `run()` wraps `scrape()` with kill switch check, circuit breaker, retry with exponential backoff, human delay simulation. Subclasses only implement `scrape()`

**Crawler Registry:**
- Purpose: Maps platform names to crawler classes
- Definition: `modules/crawlers/registry.py`
- Pattern: Self-registration via `@register("platform_name")` decorator. Auto-discovery at startup walks `modules/crawlers/` directory tree and imports all `.py` files

**EventBus:**
- Purpose: Async pub/sub + job queue abstraction over Garnet/Redis
- Definition: `shared/events.py`
- Pattern: Singleton with named channels (`lycan:crawl_jobs`, `lycan:enrichment`, `lycan:alerts`, etc.) and priority queues (`lycan:queue:high/normal/low/ingest/index`). LPUSH/BRPOP for queues, PUBLISH/SUBSCRIBE for events

**DataQualityMixin:**
- Purpose: Every data row carries provenance and quality metadata
- Definition: `shared/models/base.py`
- Pattern: SQLAlchemy mixin adding `source_reliability`, `freshness_score`, `corroboration_count`, `composite_quality`, `conflict_flag`, `verification_status` to all models

## Entry Points

**API Server:**
- Location: `api/main.py`
- Triggers: HTTP requests, WebSocket connections
- Responsibilities: Route requests, authenticate via API key, dispatch crawl jobs, query data, serve static SPA
- Run: `uvicorn api.main:app`

**Worker Process:**
- Location: `worker.py`
- Triggers: Started as a separate process
- Responsibilities: Runs all background daemons concurrently -- dispatcher workers (4 default), ingestion daemons (2), index daemon, growth daemon, freshness scheduler, auto-dedup, commercial tagger, audit daemon, genealogy/property/PEP/adverse-media enrichers
- Run: `python worker.py [--workers N] [--no-growth] [--no-freshness] ...`

**CLI Runner:**
- Location: `lycan.py`
- Triggers: Command-line invocation
- Responsibilities: Direct scraper execution without the queue system. Runs crawlers in-process via `ScraperOrchestrator`
- Run: `python lycan.py --name "John Smith"` or `--phone`, `--email`, `--username`, `--vin`, `--domain`

**Database Migrations:**
- Location: `alembic.ini` + `migrations/`
- Triggers: `alembic upgrade head`
- Responsibilities: Schema evolution (16 migration versions)

## Error Handling

**Strategy:** Fail-open for non-critical paths, fail-closed for auth

**Patterns:**
- Crawlers must never raise -- `BaseCrawler.run()` catches all exceptions and returns a `CrawlerResult` with `found=False` and `error` set
- Retry with exponential backoff + jitter (3 retries default, 2s base backoff, 30s max)
- Circuit breaker per crawler platform (`shared/circuit_breaker.py`) -- skip crawlers with high failure rates
- Ingestion daemon logs errors but continues processing the queue
- Enrichment orchestrator runs enrichers sequentially; failures in one enricher do not block others
- Audit logging middleware catches errors silently -- must never block HTTP responses
- Import guards with `try/except ImportError` for optional models (graceful degradation)

## Cross-Cutting Concerns

**Logging:** Python `logging` module throughout. Structured format with `AUDIT` prefix for API access logs. Log level controlled via `shared/config.py` `log_level` setting.

**Validation:** Pydantic models for API input validation (`shared/schemas/`). SQLAlchemy mapped columns with type constraints for DB layer. `field_validator` decorators on schemas.

**Authentication:** Bearer token API key authentication via `api/deps.py`. Comma-separated keys in config. Kill switch `api_auth_enabled` for dev mode. WebSocket auth via query param `?token=`.

**Rate Limiting:** SlowAPI middleware on the FastAPI app (100 req/min default, backed by Garnet). Per-crawler rate limits via `RateLimit` model on `BaseCrawler`.

**Anonymity:** 3 Tor instances managed by `shared/tor.py` (TOR1=social, TOR2=spiders, TOR3=dark web). Residential and datacenter proxy pools. Human delay simulation (1.5-6s), user-agent rotation, TLS fingerprint rotation via curl-cffi.

**Data Quality:** `DataQualityMixin` on all models. `shared/data_quality.py` applies quality scoring. `shared/freshness.py` manages freshness/staleness detection.

**Caching:** Redis-compatible cache helpers on EventBus. `shared/cache.py` for application caching.

---

*Architecture analysis: 2026-03-30*
