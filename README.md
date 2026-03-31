# Lycan-Data

Recursive people intelligence platform. Searches 150+ sources, deduplicates automatically, enriches with risk scoring, and serves everything through a real-time REST API.

## What it does

- **Multi-source scraping** — social media, sanctions lists, property records, court filings, dark web, financial disclosures, and more
- **Recursive enrichment** — found an email? It triggers a new search. Found a phone? Same. Keeps going until the graph is complete.
- **Auto-deduplication** — three-pass dedup (exact match, ML similarity, graph clustering) merges duplicate records without losing data
- **Real-time progress** — SSE stream shows exactly which scrapers are running, completed, or failed
- **Knowledge graph** — entity relationships, UBO discovery, fraud ring detection

## Prerequisites

- Docker and Docker Compose v2
- 8 GB RAM minimum (16 GB recommended)
- `.env` file with secrets (see below)

## Quick start

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd Lycan-Data

# 2. Create your .env file
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, TYPESENSE_API_KEY, TOR_CONTROL_PASSWORD, API_KEYS

# 3. Start all infrastructure services
make up

# 4. Install Python dependencies locally
make install

# 5. Wait for services to be healthy (~30 seconds)
docker compose ps

# 6. Run database migrations
make migrate

# 7. Start the API server (in one terminal)
make api

# 8. Start background workers (in another terminal)
make worker
```

The API is now available at `http://localhost:8000`.

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `POSTGRES_PASSWORD` | Yes | PostgreSQL password |
| `TYPESENSE_API_KEY` | Yes | Typesense API key (any random string) |
| `TOR_CONTROL_PASSWORD` | Yes | Tor control port password |
| `API_KEYS` | Yes | Comma-separated valid API keys (e.g. `key1,key2`) |
| `SECRET_KEY` | Yes | JWT signing key (32+ characters) |
| `POSTGRES_USER` | No | Defaults to `lycan` |
| `POSTGRES_DB` | No | Defaults to `lycan` |
| `ATTOM_API_KEY` | No | ATTOM property data (enhances property results) |
| `OPENSANCTIONS_API_KEY` | No | OpenSanctions premium (more AML data) |
| `OPENCORPORATES_API_KEY` | No | OpenCorporates (company data) |
| `RESIDENTIAL_PROXIES` | No | Comma-separated residential proxy list |
| `DATACENTER_PROXIES` | No | Comma-separated datacenter proxy list |

## Infrastructure services

| Service | Port | Purpose |
|---|---|---|
| PostgreSQL + AGE | 5432 | Main relational database + graph extension |
| Garnet | 6379 | Redis-compatible cache and job queue |
| Typesense | 8108 | Full-text + filter + hybrid / vector search |
| Qdrant | 6333 | Vector database for ML embeddings |
| Pulsar | 6650 / 8082 | Event streaming (broker / admin) |
| Tor (×3) | 9050–9055 | Anonymous proxy pool |
| FlareSolverr | 8191 | Cloudflare bypass |
| API | 8000 | FastAPI application |
| Worker | — | Background processing daemons |

## Make targets

```bash
make dev            # Start all services in foreground (with dev overrides)
make up             # Start all services in background
make down           # Stop all services

make test           # Run full test suite
make test-fast      # Run tests, skip slow crawler/playwright tests
make test-ci        # Run with coverage (fails if < 45%)
make test-load      # Run 50-concurrent-search load tests

make migrate        # Apply pending database migrations
make migrate-create MSG="add index"  # Create a new migration

make api            # Start API server (port 8000, with reload)
make worker         # Start 4 background workers
make worker-fast    # Start 8 background workers

make scraper-health # Check all scraper health and registry stats
make search QUERY="John Doe"  # Run a test search from CLI (requires API running)

make logs           # Follow all service logs
make shell          # Open psql shell in postgres container
make health         # Run selfheal health report
make selfheal       # Run selfheal auto-fix script
```

## Running a search

```bash
# Via CLI shortcut
make search QUERY="John Doe"

# Via curl
curl -X POST http://localhost:8000/search \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "John Doe", "max_results": 20}'

# Stream progress in real time
curl -N http://localhost:8000/ws/search/<person-id>/progress \
  -H "Authorization: Bearer your-api-key"
```

## Testing

```bash
# Full test suite
make test

# Fast suite (excludes live-crawl and Playwright tests)
make test-fast

# Load test (50 concurrent searches, all mocked)
make test-load

# Specific test file
python3 -m pytest tests/test_integration_search_pipeline.py -v

# With coverage
make test-ci
```

Tests never make live network calls — all external I/O is mocked.

## Architecture overview

```
Client
  │
  ▼
FastAPI (port 8000)
  │  POST /search
  │  GET  /persons/{id}/full
  │  SSE  /ws/search/{search_id}/progress
  │
  ▼
Garnet (Redis)  ──────────────────────────────────────┐
  │  Priority queues (high / normal / low)             │
  │  Pub/sub channels (progress, alerts, graph)        │
  ▼                                                    │
CrawlDispatcher (workers)                              │
  │  Pulls jobs → runs scrapers → pushes results       │
  │  150+ scrapers (social, sanctions, dark web, etc.) │
  ▼                                                    │
IngestionDaemon                                        │
  │  Writes CrawlerResult → PostgreSQL tables          │
  │  Triggers pivot enrichment (email → re-search)     │
  ▼                                                    │
PostgreSQL + AGE (port 5432)                          │
  │  38 tables: persons, identifiers, profiles, …      │
  │  Apache AGE: graph queries for relationships       │
  ▼                                                    │
IndexDaemon                                            │
  │  Builds Typesense documents                        │
  ▼                                                    │
Typesense (port 8108)                                  │
  │  Full-text + filter + sort search                  │
  ▼                                                    │
AutoDedupDaemon (every 10 min) ◄──────────────────────┘
  │  Pass 1: exact match (email, phone, SSN+DOB)
  │  Pass 2: ML similarity (fuzzy name, phonetics)
  │  Pass 3: graph clustering
  │  score ≥ 0.85 → auto-merge
  │  score 0.70–0.84 → manual review queue
  ▼
EnrichmentDaemons
     Risk scoring, PEP/AML, property detection,
     adverse media monitoring, genealogy, anomaly detection
```

## Development notes

- Python 3.12, FastAPI, SQLAlchemy 2.0 async
- All scrapers inherit from `BaseCrawler` — add new ones with `@register("platform_name")`
- Circuit breaker (`shared/circuit_breaker.py`) auto-disables flaky scrapers
- Kill switches per platform via env vars (`ENABLE_INSTAGRAM=false`)
- Tor + residential proxy fallback chain per crawler
- `asyncio_mode = "auto"` in pytest — all async tests just work
