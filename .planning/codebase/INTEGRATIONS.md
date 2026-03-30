# External Integrations

**Analysis Date:** 2026-03-30

## APIs & External Services

**Property Data:**
- ATTOM Data Solutions - US property valuation, ownership history, foreclosure data
  - SDK/Client: httpx via `modules/crawlers/property/attom_gateway.py`
  - Auth: `ATTOM_API_KEY` env var (optional; falls back to public portal scraping)
  - Endpoint: `https://api.gateway.attomdata.com/propertyapi/v1.0.0/`

**Sanctions & Compliance:**
- OpenSanctions - PEP/sanctions screening
  - SDK/Client: httpx via crawlers
  - Auth: `OPENSANCTIONS_API_KEY` env var (optional)
  - Endpoint: `https://api.opensanctions.org`
- US Treasury OFAC - SDN list
  - Endpoint: `https://www.treasury.gov` (rate limited: 0.2 req/s)
- EU Consolidated Sanctions - European sanctions list
  - Endpoint: `https://webgate.ec.europa.eu` (rate limited: 0.1 req/s)
- World Bank Debarment - Debarred firms list
  - Client: `modules/crawlers/sanctions_worldbank_debarment.py`

**Corporate Intelligence:**
- OpenCorporates - Company registry data
  - Auth: `OPENCORPORATES_API_KEY` env var (optional)
- Crunchbase - Startup/company funding data
  - SDK/Client: curl-cffi via `modules/crawlers/financial_crunchbase.py`
  - Auth: `CRUNCHBASE_API_KEY` (optional; falls back to public page scraping)
  - Endpoint: `https://api.crunchbase.com/api/v4/searches/organizations`
- Companies House (UK) - UK company registry
  - Client: `modules/crawlers/company_companies_house.py`

**Cyber Intelligence:**
- Shodan - Host/IP intelligence, open ports, vulnerabilities
  - SDK/Client: curl-cffi via `modules/crawlers/cyber_shodan.py`
  - Auth: `SHODAN_API_KEY` (settings)
  - Endpoint: `https://api.shodan.io/shodan/host/`
- AlienVault OTX - Threat intelligence
  - Client: `modules/crawlers/cyber_alienvault.py`
- Wayback Machine - Historical web snapshots
  - Client: `modules/crawlers/cyber_wayback.py`

**Social Media (scraping-based, no official API keys):**
- Reddit - Via PRAW library (`praw` 7.8.1)
  - Client: `modules/crawlers/reddit.py`
- Instagram, LinkedIn, Twitter/X, Facebook, TikTok, Telegram - Scraped via Playwright/Camoufox/curl-cffi
  - Kill switches: `ENABLE_INSTAGRAM`, `ENABLE_LINKEDIN`, `ENABLE_TWITTER`, `ENABLE_FACEBOOK`, `ENABLE_TIKTOK`, `ENABLE_TELEGRAM`
- Threads - Profile scraping via `modules/crawlers/threads_profile.py`
- WhatsApp - Profile/status checking via `modules/crawlers/whatsapp.py`

**Maritime & Transport:**
- MarineTraffic - AIS vessel tracking
  - Auth: `MARINETRAFFIC_API_KEY` env var (optional)
  - Client: `modules/crawlers/transport/marine_vessel.py`
- FAA Aircraft Registry - US aircraft ownership
  - Client: `modules/crawlers/transport/faa_aircraft_registry.py`

**Government & Public Records:**
- USPTO Patents - Patent search
  - Client: `modules/crawlers/gov_uspto_patents.py`
- FRED (Federal Reserve) - Economic data
  - Client: `modules/crawlers/gov_fred.py`
- PACER Bankruptcy - US bankruptcy records
  - Client: `modules/crawlers/bankruptcy_pacer.py`
- NamUs - Missing persons (rate limited: 0.5 req/s)
- FEC - Campaign finance data (rate limited: 2 req/s)

**People Search (scraping-based):**
- ThatsThem - People search
  - Client: `modules/crawlers/people_thatsthem.py`
- PeekYou - People search
  - Client: `modules/crawlers/peekyou.py`

**Cryptocurrency:**
- BscScan - Binance Smart Chain address lookup
  - Client: `modules/crawlers/crypto_bscscan.py`
- Blockchair - Multi-chain blockchain explorer
  - Client: `modules/crawlers/crypto_blockchair.py`

**Dark Web:**
- Ahmia.fi - Tor hidden service search engine
  - Client: `modules/crawlers/darkweb_ahmia.py`
  - Routed through TOR3 instance

**Geolocation:**
- OpenStreetMap - Geocoding and address validation
  - Client: `modules/crawlers/geo_openstreetmap.py`

**Email Intelligence:**
- Socialscan - Email/username existence across platforms
  - Client: `modules/crawlers/email_socialscan.py`
- Disposable Email Check
  - Client: `modules/crawlers/email_disposable.py`

**Phone Intelligence:**
- FoneFinder - Phone carrier/location lookup
  - Client: `modules/crawlers/phone_fonefinder.py`

**Anti-Bot Bypass:**
- FlareSolverr - Cloudflare/JS challenge solver
  - Endpoint: `http://flaresolverr:8191/v1` (self-hosted Docker container)
  - Client: `modules/crawlers/flaresolverr_base.py`
  - Auto-promoted via `shared/transport_registry.py` after repeated blocks

**OSINT CLI Tools (subprocess):**
- sherlock-project - Username search across 400+ platforms (installed via pipx)
- maigret - Username search across 2500+ platforms (installed via pipx)

## Data Storage

**Databases:**
- PostgreSQL 18 + Apache AGE + pgvector (custom Docker image: `Dockerfile.postgres`)
  - Connection: `DATABASE_URL` env var (default: `postgresql+asyncpg://lycan:lycan@postgres:5432/lycan`)
  - Client: SQLAlchemy 2.0 async with asyncpg driver (`shared/db.py`)
  - Pool: 50 connections default, 100 overflow (`LYCAN_DB_POOL_SIZE`, `LYCAN_DB_MAX_OVERFLOW`)
  - Extensions: `uuid-ossp`, `vector` (pgvector), `age` (Apache AGE graph)
  - Graph: `osint_graph` knowledge graph via Cypher queries through AGE SQL wrapper (`modules/graph/knowledge_graph.py`)
  - Migrations: Alembic (`migrations/`, `alembic.ini`)

**Search Engine:**
- Typesense 27.0 - Full-text search + faceted filtering
  - Connection: `TYPESENSE_URL` (default: `http://typesense:8108`)
  - Auth: `TYPESENSE_API_KEY`
  - Client: Custom HTTP client via httpx (`modules/search/typesense_indexer.py`)
  - Collections: `persons`, `identifiers`, `social_profiles`
  - Replaced MeiliSearch (BSL 1.1 licensing concern)

**Vector Database:**
- Qdrant (latest) - ML embeddings and vector dedup
  - Ports: 6333 (HTTP), 6334 (gRPC)
  - Volume: `qdrant_data`
  - Used for: ML-based deduplication (`modules/enrichers/ml_dedup.py`)

**Caching & Queues:**
- Microsoft Garnet (Redis-compatible) - Caching, pub/sub, job queues, circuit breakers, rate limiters
  - Connection: `CACHE_URL` (default: `redis://garnet:6379/0`)
  - Client: `redis.asyncio` (`shared/cache.py`, `shared/events.py`)
  - Pub/Sub channels: `lycan:crawl_jobs`, `lycan:enrichment`, `lycan:alerts`, `lycan:freshness`, `lycan:graph`, `lycan:progress`
  - Job queues (LPUSH/BRPOP): `lycan:queue:high`, `lycan:queue:normal`, `lycan:queue:low`, `lycan:queue:ingest`, `lycan:queue:index`
  - Circuit breaker keys: `lycan:cb:{domain}` (hash with state/failures/successes)
  - Rate limiter keys: `lycan:rl:{domain}` (hash with token bucket via Lua script)
  - Transport registry keys: `transport:{domain}`, `blocks:{domain}`
  - Legacy alias: `DRAGONFLY_URL` maps to `CACHE_URL` (`shared/config.py`)

**Event Streaming:**
- Apache Pulsar 3.3.0 - High-throughput event streaming
  - Ports: 6650 (broker), 8082 (admin)
  - Volume: `pulsar_data`
  - Status: Declared in docker-compose but no Python client integration found in application code yet

**File Storage:**
- Local filesystem only (static files in `static/`)

## Authentication & Identity

**Auth Provider:**
- Custom API key authentication
  - Implementation: Bearer token via `Authorization` header (`api/deps.py`)
  - Keys: Comma-separated in `API_KEYS` env var
  - Kill switch: `API_AUTH_ENABLED=false` disables auth (dev only)
  - WebSocket auth: `?token=<api_key>` query parameter (`api/routes/ws.py`)
  - SSE auth: Bearer header or `?token=<api_key>` query param
  - No user management, no JWT-based sessions, no OAuth

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Datadog, etc.)

**Logs:**
- Python stdlib `logging` module throughout
- Structured format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Audit logging middleware persists every API call to database (`api/main.py` AuditLogMiddleware -> `shared/models/audit.py`)
- Startup health checks log status of all services (`api/main.py` lifespan, `shared/health.py`)

**Health Checks:**
- `/system/health` endpoint (public, no auth)
- Docker healthchecks on all containers
- `shared/health.py` checks: FlareSolverr, Tor (3 instances), Garnet, PostgreSQL
- `make health` / `make scraper-health` CLI diagnostics

## CI/CD & Deployment

**Hosting:**
- Docker Compose on self-hosted infrastructure
- Target: Ubuntu 24.04 server

**CI Pipeline:**
- None detected (no `.github/workflows/`, no `.gitlab-ci.yml`)
- `make test-ci` command available for manual CI runs (coverage threshold: 45%)

## Environment Configuration

**Required env vars:**
- `DATABASE_URL` - PostgreSQL connection string
- `CACHE_URL` - Redis/Garnet connection string
- `TYPESENSE_URL` - Typesense HTTP endpoint
- `TYPESENSE_API_KEY` - Typesense authentication
- `SECRET_KEY` - Application secret (min 32 chars)
- `API_KEYS` - Comma-separated API keys for authentication
- `TOR_CONTROL_PASSWORD` - Tor control port authentication

**Optional env vars (third-party APIs):**
- `ATTOM_API_KEY` - ATTOM property data
- `OPENSANCTIONS_API_KEY` - OpenSanctions premium
- `OPENCORPORATES_API_KEY` - OpenCorporates
- `MARINETRAFFIC_API_KEY` - MarineTraffic AIS
- `SHODAN_API_KEY` - Shodan host intelligence
- `CRUNCHBASE_API_KEY` - Crunchbase company data

**Secrets location:**
- `.env` file (gitignored)
- `.env.example` template present
- Docker Compose environment blocks with defaults

## Anonymization & Proxy Infrastructure

**Tor Network (3 independent circuits):**
- TOR1 (port 9050/9051) - Social media crawlers (Playwright)
- TOR2 (port 9052/9053) - Scrapy spiders, enrichment
- TOR3 (port 9054/9055) - Dark web (.onion) crawling
- Managed by: `shared/tor.py` TorManager singleton
- Circuit rotation: `stem` library via control port

**Proxy Pool (tiered, `shared/proxy_pool.py`):**
- Tier 1: Residential proxies (lowest detection) - `RESIDENTIAL_PROXIES`
- Tier 2: Datacenter proxies (fast, cheap) - `DATACENTER_PROXIES`
- Tier 3: Tor (anonymity) - via TorManager
- Tier 4: Direct (no proxy, fallback only)
- Features: round-robin selection, auto-ban/unban, slow-marking, tier fallback chain

**Transport Auto-Promotion (`shared/transport_registry.py`):**
- Tier chain: httpx -> curl (Chrome TLS) -> FlareSolverr (Cloudflare bypass)
- Auto-promotes after 3 consecutive blocks per domain
- State persisted in Garnet (Redis)

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- None detected

## Real-Time Communication

**WebSocket:**
- `/ws/progress/{person_id}` - Real-time scrape progress per person (`api/routes/ws.py`)

**Server-Sent Events (SSE):**
- `/sse/progress/{person_id}` - SSE scrape progress stream
- `/search/{person_id}/progress` - Phase-based search progress (collecting -> deduplicating -> enriching -> finalizing -> complete)

---

*Integration audit: 2026-03-30*
