# Technology Stack

**Analysis Date:** 2026-03-30

## Languages

**Primary:**
- Python 3.12 - All application code (API, workers, crawlers, enrichers, graph)

**Secondary:**
- SQL / Cypher - Database migrations (`migrations/`), Apache AGE graph queries (`modules/graph/knowledge_graph.py`)
- Lua - Redis token bucket rate limiter script (`shared/rate_limiter.py`)

## Runtime

**Environment:**
- Python 3.12-slim (Docker base image)
- uvloop 0.22.1 on Linux (async event loop, disabled on Windows)

**Package Manager:**
- Poetry 1.8.2 (primary dependency management)
- pip (supplementary runtime extras not in pyproject.toml)
- pipx (isolated CLI tools: sherlock-project, maigret)
- Lockfile: `poetry.lock` present

## Frameworks

**Core:**
- FastAPI 0.135.2 - HTTP API framework (`api/main.py`)
- Starlette 1.0.0 - ASGI foundation (middleware, static files, SSE)
- Uvicorn 0.42.0 - ASGI server (2 workers in production, `--reload` in dev)
- SQLAlchemy 2.0.48 (async mode) - ORM and database layer (`shared/db.py`)
- Pydantic 2.12.5 - Data validation, schemas, settings (`shared/config.py`, `shared/schemas/`)
- Pydantic-Settings 2.13.1 - Environment-based configuration (`shared/config.py`)

**Testing:**
- pytest 9.0.2 - Test runner
- pytest-asyncio 1.3.0 - Async test support (auto mode)
- pytest-cov 7.1.0 - Coverage reporting
- anyio 4.12.1 - Async test utilities

**Build/Dev:**
- Docker Compose 3.9 - Multi-service orchestration (`docker-compose.yml`)
- Alembic 1.18.4 - Database migrations (`alembic.ini`, `migrations/`)
- Ruff - Linter and formatter (configured in `pyproject.toml`)
- Make - Task runner (`Makefile`)

## Key Dependencies

**Critical:**
- asyncpg 0.31.0 - PostgreSQL async driver (connection pooling: 50 default, 100 overflow)
- redis 5.2.1 - Async Redis/Garnet client (pub/sub, queues, caching, circuit breakers)
- httpx 0.28.1 [socks] - Primary HTTP client for crawlers (SOCKS proxy support via socksio)
- Playwright 1.49+ - Chromium browser automation for JS-heavy sites (`modules/crawlers/playwright_base.py`)
- Patchright 1.49+ - Alternative Playwright fork for stealth browsing (`modules/crawlers/camoufox_base.py`)
- curl-cffi 0.14+ - Chrome TLS fingerprint impersonation (`modules/crawlers/curl_base.py`)
- Camoufox 0.4+ [geoip] - Firefox-based anti-fingerprint browser
- stem 1.8.2 - Tor control protocol (circuit rotation via `shared/tor.py`)
- spaCy 3.8+ - NLP pipeline with `en_core_web_lg` model (entity extraction, biographical enrichment)
- networkx 3.4.2 - Graph algorithms (relationship analysis, dedup graph)
- Typesense Python client 0.21.0 - Full-text search indexing (via raw HTTP, not official SDK)
- Scrapy 2.12+ - Spider framework (declared in pyproject.toml)

**Anti-Detection & OSINT:**
- fake-useragent 1.5+ - User-Agent rotation
- socialscan 1.3+ - Username availability checking across platforms
- beautifulsoup4 4.14.3 + lxml 6.0.2 - HTML parsing
- rapidfuzz 3.0+ - Fuzzy string matching (dedup, name matching)
- phonenumbers 9.0.26 - Phone number parsing and validation
- python-jose 3.3+ [cryptography] - JWT token handling
- passlib 1.7+ [bcrypt] - Password hashing

**Infrastructure:**
- slowapi 0.1.9 - API rate limiting middleware (backed by Garnet)
- aiofiles 24.1+ - Async file I/O
- jinja2 3.1.6 - HTML templating (static SPA)
- praw 7.8.1 - Reddit API client
- python-dateutil 2.9+ - Date parsing
- python-dotenv 1.2.2 - .env file loading

**External CLI Tools (installed via pipx/binary, not Python deps):**
- sherlock-project - Username OSINT across 400+ sites
- maigret - Advanced username search across 2500+ sites
- PhoneInfoga - Phone number OSINT (Go binary, not currently installed)

## Configuration

**Environment:**
- `.env` file present - loaded by Pydantic-Settings (`shared/config.py`)
- `.env.example` present - template for required variables
- All config via `shared/config.py` `Settings` class (single source of truth)
- Key env vars: `DATABASE_URL`, `CACHE_URL`, `TYPESENSE_URL`, `TYPESENSE_API_KEY`, `SECRET_KEY`, `API_KEYS`, `API_AUTH_ENABLED`, `TOR_CONTROL_PASSWORD`, `CORS_ORIGINS`, `LOG_LEVEL`
- Optional API keys: `ATTOM_API_KEY`, `OPENSANCTIONS_API_KEY`, `OPENCORPORATES_API_KEY`, `MARINETRAFFIC_API_KEY`
- Module kill switches: `ENABLE_INSTAGRAM`, `ENABLE_LINKEDIN`, `ENABLE_TWITTER`, `ENABLE_FACEBOOK`, `ENABLE_TIKTOK`, `ENABLE_TELEGRAM`, `ENABLE_DARKWEB`, etc.
- Proxy configuration: `RESIDENTIAL_PROXIES`, `DATACENTER_PROXIES`, `DEFAULT_PROXY_TIER`, `I2P_SOCKS`
- Anti-detection tuning: `HUMAN_DELAY_MIN`, `HUMAN_DELAY_MAX`, `JITTER_ENABLED`, `ROTATE_USER_AGENT`, `ROTATE_TLS_FINGERPRINT`

**Build:**
- `pyproject.toml` - Poetry dependencies, pytest config, ruff config, coverage settings
- `Dockerfile.app` - Application image (Python 3.12-slim + system deps + Playwright + spaCy)
- `Dockerfile.postgres` - Custom PostgreSQL 18 with Apache AGE + pgvector
- `docker-compose.yml` - Full stack (9 services)
- `docker-compose.dev.yml` - Dev overrides (hot-reload, debug DB name)
- `alembic.ini` - Migration configuration
- `Makefile` - Developer task shortcuts

## Platform Requirements

**Development:**
- Python 3.12+
- Docker + Docker Compose
- Poetry 1.8+
- ~4GB RAM minimum (PostgreSQL 2G + Garnet 1G + app 1G)
- Chromium dependencies (Playwright + Patchright install)

**Production:**
- Docker host with 8GB+ RAM recommended
- 9 containers: postgres, garnet, typesense, qdrant, pulsar, tor-1, tor-2, tor-3, flaresolverr, api, worker
- CPU: 10+ cores recommended (sum of container limits)
- Storage: persistent volumes for postgres_data, garnet_data, typesense_data, qdrant_data, pulsar_data

---

*Stack analysis: 2026-03-30*
