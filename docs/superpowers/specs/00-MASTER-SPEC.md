# LYCAN OSINT/DATA BROKER PLATFORM — MASTER BUILD SPEC (v3.0)

## CRITICAL: How to Use This Specification

This document is **the** authoritative source for building Lycan from the ground up.

**Read this first. Then read docs 01-14 in the `/docs` folder for detailed specifications.**

Every developer receiving this should:
1. Start with this document to understand the complete system
2. Reference docs 01-14 as needed for implementation details (see doc 14 for deep code audit)
3. Verify all tool licenses comply with the License Safety Tier (below)
4. Follow the Phase Plan sequentially
5. Build modules in strict modular isolation (see Architecture section)
6. Run tests after every module completion
7. Validate against compliance rules in doc 12

**This is production software.** The existing codebase is ~70% MVP, ~10% production-ready, ~5% enterprise-grade. This spec elevates it to 100% production + enterprise capability.

---

## Project Overview

Lycan is a comprehensive **data broker and OSINT intelligence platform** that aggregates, deduplicates, enriches, and serves data on individuals and businesses at scale.

**Competitive Landscape:** Lycan competes with Axiom, LexisNexis, Spokeo, TransUnion, and Equifax in the data intelligence space.

**Core Business Model:**
- Data aggregation from 1,000+ public, semi-public, and open discovery sources
- Zero-duplicate guarantees via 4-pass entity resolution
- Enrichment to 2,350+ data points across 7 categories
- Alternative credit scoring and financial intelligence
- Marketing intelligence (segmentation, lead scoring, affinity modeling)
- Real-time pattern detection and anomaly alerting
- White-label API for enterprises, B2B2C, and fintech partners
- Government-grade compliance and data handling

### What Lycan Does (Capabilities)

1. **Data Collection & Aggregation** (docs 01, 09)
   - Maintains 1,000+ active scraper/crawler workflows (predefined + open discovery)
   - Collects from public records, open APIs, social platforms, government databases
   - Auto-detects scraper failures with never-give-up retry logic
   - Supports both push (webhook) and pull (polling) data sources
   - Open discovery via SpiderFoot, Amass, theHarvester, Sherlock, Maigret, Google dorking, CT logs, Common Crawl, Wayback

2. **Entity Resolution & Deduplication** (doc 03)
   - 4-pass dedup: exact → fuzzy → graph → ML-based matching via Splink (probabilistic)
   - Maintains golden record for each unique person/business
   - Tracks all mentions and aliases
   - Zero-duplicate guarantee — violations trigger alerts

3. **Data Enrichment** (docs 05, 06, 10)
   - Normalizes and validates all data fields
   - Enriches with external APIs (coordinates, reverse geocoding, etc.)
   - Cross-references records across sources
   - Assigns confidence scores to every data point
   - Enrichment Score (0-100) with gap analysis and one-click "deep enrich"

4. **Financial Intelligence** (doc 06)
   - Alternative credit scoring (for unbanked/subprime)
   - AML/KYC screening against sanctions lists
   - PEP (politically exposed person) detection
   - Fraud risk modeling
   - Adverse media monitoring

5. **Marketing Intelligence** (doc 10)
   - Consumer tagging (title loan candidates, gamblers, etc.)
   - Ticket size estimation (customer lifetime value)
   - Behavioral segmentation
   - Lead scoring and propensity models
   - List building and audience targeting

6. **Real-Time Search** (doc 11)
   - Fast single-person search with expanding result set
   - Progress bars showing active data collection
   - Editable search parameters mid-flight
   - Business search with officer/agent tracking
   - Reverse phone/email/address search
   - Multi-candidate presentation with photos and facial embeddings (pHash matching)

7. **Pattern Detection & Networks** (doc 07)
   - Graph analysis for relationship mapping
   - Anomaly detection (unusual activity patterns)
   - Fraud ring identification
   - Network visualization
   - Real-time alerting
   - Admiralty Code quality framework for data scoring

8. **API & Integration** (doc 01)
   - RESTful API for all operations
   - Server-Sent Events (SSE) for real-time streams
   - Webhook support for push data
   - Rate limiting, authentication, audit logging
   - White-label branding

### What Lycan Does NOT Do (Out of Scope)

- **Malware/Hacking:** No reverse shells, exploits, or network attacks
- **Deepfakes:** No video/audio synthesis or fraud creation tools
- **Impersonation:** No tools to masquerade as another person
- **Illegal Activities:** No facilitating theft, fraud, harassment, or stalking
- **Privacy Violations:** Respects GDPR, CCPA, and opt-out requests
- **Unrestricted Data Selling:** Compliance controls prevent misuse (see doc 12)

See doc 12 (Ethical & Legal Compliance) for the full framework.

---

## Licensing Compliance (Definitive Blueprint v3.0)

**ALL tools must use permissive open-source licenses. AGPL and BSL are BANNED.**

### License Safety Tier

| Category | Approved | Rejected | Reason |
|----------|----------|----------|--------|
| **MIT** | ✅ Apache 2.0 | ❌ AGPL | Permissive, government-safe |
| **BSD** | ✅ BSD 2/3-Clause | ❌ BSL 1.1 | Too restrictive, commercial conflict |
| **GPL** | ✅ GPL-2, GPL-3 | | Patent-safe, strong copyleft OK |
| **MPL** | ✅ MPL 2.0 | | File-level copyleft, enterprise-friendly |
| **LGPL** | ✅ LGPL-3 | | Lightweight copyleft, suitable for libraries |

### Critical Tool License Decisions (v3.0)

| Layer | Old | New | License | Notes |
|-------|-----|-----|---------|-------|
| **Browser Automation** | Nodriver | Playwright + playwright-stealth | Apache 2.0 | AGPL rejected |
| **Full-Text Search** | MeiliSearch | Typesense | GPL-3 | BSL rejected, government-safe |
| **Instant Search** | None | Typesense | GPL-3 | Lightweight alternative to ES |
| **Cache/Broker** | Redis | Dragonfly | MIT/Polyform | 25x faster, MIT dual-licensed |
| **Graph Database** | None | Apache AGE | Apache 2.0 | Native Postgres graph queries |
| **Task Queue (Primary)** | Redis Streams | Temporal + Dramatiq | Temporal:Elastic / Dramatiq:LGPL-3 | Temporal: best-in-class, Dramatiq: lighter option |
| **Entity Resolution** | Custom matching | Splink | BSD | Probabilistic record linkage |
| **Source Discovery** | Custom | SpiderFoot + Amass + theHarvester + Sherlock + Maigret | Mix of MIT/GPL | Open discovery automation |
| **Page Monitoring** | None | ChangeDetection.io + ArchiveBox | AGPL / BSD | For freshness tracking |

**VERIFY ALL DEPENDENCIES** before deploying. Run `pip-audit` or `safety check` regularly.

---

## Technical Architecture

### Tech Stack Summary

| Layer | Tech | Justification | License |
|-------|------|---------------|---------|
| **Language** | Python 3.12+ (primary) | Existing codebase, ML/NLP ecosystem, rapid iteration | MIT |
| | Rust via PyO3 (secondary) | String matching, dedup engine, Bloom filters (performance-critical paths only) | MIT |
| **API Framework** | FastAPI | Async-native, performance, OpenAPI docs, Pydantic validation | MIT |
| **Database** | PostgreSQL 16 | JSONB, full-text search, pg_trgm, PostGIS, materialized views | PostgreSQL License |
| **Cache/Broker** | Dragonfly | Redis-compatible, 25x faster, lower memory footprint | MIT/Polyform |
| **Vector Search** | Qdrant | Semantic search, ML embeddings, similarity search | AGPL (optional, use internal embeddings) |
| **Full-Text Search (Primary)** | Typesense | Typo-tolerant, fast, government-safe, GPL-3 | GPL-3 |
| **Full-Text Search (Secondary)** | Elasticsearch | Enterprise-grade FTS with aggregations | SSPL (optional, proprietary use) |
| **Instant Search** | Typesense | Lightweight, GPL-3, alongside Elasticsearch | GPL-3 |
| **Graph Queries** | Apache AGE (on Postgres) | Native graph database without separate infrastructure | Apache 2.0 |
| **Workflow Engine** | Temporal.io | Distributed workflows, retry logic, resumability | Elastic License / SSPL |
| **Async Tasks** | Dramatiq + Apache Pulsar | Job queue, worker distribution, at-least-once delivery | LGPL-3 / Apache 2.0 |
| **Browser Automation** | Playwright + playwright-stealth | Headless automation, anti-bot stealth | Apache 2.0 |
| **Entity Resolution** | Splink | Probabilistic record linkage, dedup at scale | BSD |
| **Source Discovery** | SpiderFoot, Amass, theHarvester, Sherlock, Maigret | Open-source OSINT tools, automated reconnaissance | Mix of MIT/GPL |
| **Page Monitoring** | ChangeDetection.io | Monitor site changes for freshness tracking | AGPL (air-gapped instance OK) |
| **Page Archiving** | ArchiveBox | Self-hosted web archive, save snapshots | MIT |
| **Real-Time** | Server-Sent Events (SSE) | Browser-native, no WebSocket complexity, progress tracking | N/A |
| **Monitoring** | Prometheus + Grafana | Metrics, dashboards, alerting | Apache 2.0 / AGPL (SSPL option) |
| **Containerization** | Docker + Docker Compose | Reproducible environments, local dev, cloud deployment | Apache 2.0 |
| **CI/CD** | GitHub Actions | Already configured, integrated with existing repo | Proprietary |

### Why Python (Not Go/Rust/Node)?

**Decision: Python with Rust for hot paths only.**

**Reasoning:**
- Existing codebase is Python + team expertise
- ML/NLP ecosystem is unmatched (scikit-learn, XGBoost, sentence-transformers)
- Data enrichment pipelines use pandas/Polars (Python)
- OSINT tools (Sherlock, holehe, Maigret, SpiderFoot, Amass) are Python-based
- Development velocity is critical in early stages
- **Do not rewrite in Rust.** Profile first, optimize only where Python bottlenecks exist
- Use Rust via PyO3 only for: string similarity (Levenshtein at 100K+ records/sec), Bloom filters, cryptographic hashing

### Database Architecture

#### Primary Database: PostgreSQL 16

**Core Tables (34 total: 20 existing + 14 new)**

**Existing Person/Business Core:**
```
persons                — Person master records (dedup key tracking)
businesses             — Business master records
businesses_officers   — Corporate officers/agents
employment            — Employment history and current positions
education             — School/university records
addresses             — Full address history with dates
phones                — Phone number tracking with validation
emails                — Email address tracking with validation
social_profiles       — Social media accounts and handles
properties            — Real estate ownership
vehicles              — Vehicle registrations
court_cases           — Civil/small claims court records
criminal_records      — Criminal history
financial_records     — Bank/credit card data
liens_judgments       — Legal liens and judgments
bankruptcy            — Bankruptcy filings
data_sources          — Source attribution (URL, spider, date)
search_jobs           — Search request tracking
search_results        — Individual search result items
scraper_runs          — Execution logs for crawlers/spiders
```

**New Tables (Phase 4-8):**
```
golden_records              — Canonical dedup'd person record
entity_graph                — Relationship edges (person-person, person-business)
aml_screenings              — AML/KYC check results with date
sanctions_hits              — Positive sanctions list matches
pep_records                 — Politically exposed person data
marketing_tags              — Consumer classification (title_loan_candidate, gambler, etc.)
consumer_segments           — Segment assignments (behavioral, demographic)
ticket_sizes                — Estimated customer lifetime value (CLV)
credit_scores               — Alternative credit score, model version, percentile
fraud_indicators            — Fraud risk scores and indicators
opt_outs                    — Opt-out requests (GDPR, CCPA, do-not-sell)
audit_log                   — Compliance audit trail (who accessed what, when)
webhooks                    — Webhook registrations for push data
progress_events             — Search progress tracking (SSE events)
growth_discoveries          — Expanding search results
data_quality_scores         — Per-record freshness and completeness
candidate_faces             — pHash fingerprints and facial embeddings for multi-candidate matching
source_discovery_log        — Review Tab: discovered sources awaiting approval
```

**Indexes (Critical for Performance):**
```sql
-- Dedup matching
CREATE INDEX idx_persons_phone_normalized ON persons (phone_normalized);
CREATE INDEX idx_persons_email_normalized ON persons (email_normalized);
CREATE INDEX idx_persons_name_dob ON persons (last_name, first_name, dob);
CREATE INDEX idx_addresses_normalized ON addresses (street_normalized, city, state, zip);

-- Search and lookup
CREATE INDEX idx_phones_person_id ON phones (person_id);
CREATE INDEX idx_emails_person_id ON emails (person_id);
CREATE INDEX idx_employment_person_id ON employment (person_id);

-- Time-series and freshness
CREATE INDEX idx_data_sources_collected_at ON data_sources (collected_at DESC);
CREATE INDEX idx_audit_log_access_time ON audit_log (access_time DESC);

-- Enrichment and quality scoring
CREATE INDEX idx_data_quality_scores_person_id ON data_quality_scores (person_id);
CREATE INDEX idx_data_quality_scores_freshness ON data_quality_scores (freshness_score DESC);

-- Multi-candidate matching
CREATE INDEX idx_candidate_faces_person_id ON candidate_faces (person_id);
CREATE INDEX idx_candidate_faces_phash ON candidate_faces (phash);

-- Source discovery review
CREATE INDEX idx_source_discovery_status ON source_discovery_log (status, created_at DESC);
```

#### Cache Layer: Dragonfly (Redis-Compatible)

Dragonfly replaces Redis with 25x faster performance and 40% less memory:

```
Cache Keys:
  person:{id}:full_record       — Full person record with all relations (TTL: 24h)
  person:{id}:enrichment_v2     — Enriched data only (TTL: 7d)
  person:{id}:enrichment_score  — Enrichment score 0-100 with gap analysis (TTL: 1h)
  phone:{normalized}:person_id  — Phone-to-person mapping (TTL: 30d)
  email:{normalized}:person_id  — Email-to-person mapping (TTL: 30d)
  search:{search_id}:status     — Search status (TTL: 7d)
  search:{search_id}:results    — Cached results (TTL: 24h)
  scraper:{name}:health        — Scraper health status (TTL: 5m)
  rate_limit:{api_key}         — Per-key rate limit counter (TTL: 1m)
  source_freshness:{source}    — Last crawl time and SLA tracking (TTL: depends on source)
  candidate_faces:{search_id}  — Multi-candidate faces for current search (TTL: 24h)
```

#### Vector Database: Qdrant

```
Collections:
  person_embeddings      — Sentence-BERT embeddings of person profiles (384-dim)
  social_profile_text    — Social profile text embeddings
  document_embeddings    — Text from documents (resumes, etc.)
  facial_embeddings      — Deep facial embeddings for pHash matching
```

Used for:
- Semantic similarity search
- Finding similar profiles across sources
- Anomaly detection (outlier embeddings)
- Multi-candidate facial matching (pHash + embedding cosine distance)

#### Full-Text Search: Typesense + Elasticsearch

**Typesense (Primary):**
- Fast, typo-tolerant search
- Government-safe (GPL-3)
- Instant search for single-record lookup
- Lighter than Elasticsearch, suitable for smaller deployments

**Elasticsearch (Optional Secondary):**
- Enterprise-scale FTS with complex aggregations
- Use only if Typesense capacity exceeded
- License: SSPL (commercial use requires agreement)

#### Graph Database: Apache AGE (on PostgreSQL)

```
Vertices:
  person (id, name, dob, risk_score)
  business (id, name, industry, risk_score)
  location (id, address, city, state, zip)
  phone (id, number, type)
  email (id, address)

Edges:
  OWNS (person -> property)
  WORKS_AT (person -> business)
  ASSOCIATED_WITH (person -> person, business -> business)
  LOCATED_AT (person/business -> location)
  PHONE_NUMBER (person -> phone)
  EMAIL_ADDRESS (person -> email)
  OFFICER_OF (person -> business)
  FAMILY_MEMBER (person -> person)
  CONNECTED_TO (person -> person, inferred from shared data)
```

Query examples:
```sql
-- Find network around a person
MATCH (p:person)-[*1..3]-(connected:person) WHERE p.id = $person_id
RETURN connected, relationships

-- Find fraud rings (highly connected network)
MATCH (p1:person)-[r1]->(shared:phone)-[r2]->(p2:person)
WHERE p1.risk_score > 0.7 AND p2.risk_score > 0.7
RETURN p1, p2, shared
```

---

## Data Collection: Open Discovery Engine (NEW in v3.0)

### Two Parallel Tracks

**Track 1: Known Sources (1,000+)**
- Predefined connectors for major platforms (LinkedIn, Facebook, Twitter, etc.)
- Government records (courts, property, business registries)
- Data brokers and public record aggregators
- Financial and credit reporting (where legal)
- Bulk crawlers managed by Scrapy

**Track 2: Open Discovery**
- **SpiderFoot**: Automated reconnaissance across 100+ integrations
- **Amass**: Subdomain enumeration, certificate transparency logs, DNS
- **theHarvester**: Email harvesting, DNS brute force, search engines
- **Sherlock**: Username enumeration across 600+ platforms
- **Maigret**: Cross-platform username search
- **Google Dorking**: Automated search operators for deep indexing
- **Certificate Transparency Logs**: SSL/TLS certificate tracking
- **Common Crawl**: Historical web snapshots
- **Wayback Machine API**: Historical webpage archives

All discoverable sources feed into **Review Tab** for operator approval (see below).

---

## Review Tab: Source Approval & Crawler Self-Improvement (NEW in v3.0)

### Operator Workflow

1. **Discovery:** Open discovery tools find new data sources
2. **Review Tab UI:** Operators see pending sources with:
   - Source name, URL, category
   - Data quality estimate
   - Legal/licensing risk assessment
   - Proposed extraction pattern
3. **Approve/Reject:** One-click action
4. **Build Crawler:** Approved sources → one-click Scrapy spider generation
5. **Auto-Deploy:** Approved crawlers added to scraper fleet

### Self-Improving Loop

- Monitor crawler success/failure rates
- Failed sources → de-prioritized or removed
- High-quality sources → increase crawl frequency
- Feedback loop: crawler performance → Review Tab → approve high-value sources

---

## Search & Multi-Candidate Presentation (NEW in v3.0)

### Multi-Candidate Cards

When multiple people match a search:

1. **Card Presentation:**
   - Name, age, location
   - Photo (if available, from social profiles)
   - Match score (0-100)
   - Key identifiers (phone, email, address)

2. **Facial Matching (pHash + Embedding):**
   - Extract faces from discovered photos (social profiles, mugshots, business profiles)
   - Compute pHash (perceptual hash) for each face
   - Build facial embedding via deep neural network
   - Cross-platform matching: find same person in different sources
   - Cosine distance < threshold = same person (high confidence)

3. **Visual Deduplication:**
   - Merge candidates with same face across sources
   - Show consolidated profile card

### Implementation

```python
# Pseudo-code for facial matching
for candidate in candidates:
    faces = extract_faces(candidate.photos)
    for face in faces:
        phash = compute_phash(face)  # Perceptual hash
        embedding = facial_model.encode(face)  # 128-dim or 512-dim
        
        # Check against known faces
        for known_face in candidate_faces_db:
            if phash_distance(phash, known_face.phash) < 5:  # Very similar
                if cosine_distance(embedding, known_face.embedding) < 0.4:
                    # High confidence: same person
                    merge_candidates(candidate, known_face.person_id)
```

---

## Enrichment Score & Gap Analysis (NEW in v3.0)

### Visual Gauge: 0-100 Score

```
Enrichment Score: 73/100

Gap Analysis:
  [✓] Identity (90%) — Name, DOB, SSN, driver license
  [⊙] Financial (40%) — Missing: credit score, bank accounts, tax liens
  [✓] Employment (85%) — Current job, salary range
  [⊘] Social (20%) — Only 1 social profile found
  [✓] Legal (88%) — Court records, criminal history
  [⊙] Property (50%) — Missing: detailed property values, mortgages
  [✓] Relationships (80%) — Family, associates identified

One-Click Actions:
  [Deep Enrich] → Target gaps with targeted crawls
  [Refresh All] → Re-crawl all sources
  [Get Financial] → Trigger expensive financial data APIs
```

### Calculation

```
enrichment_score = (
  0.20 * identity_completeness +
  0.15 * financial_completeness +
  0.15 * employment_completeness +
  0.15 * social_completeness +
  0.15 * legal_completeness +
  0.10 * property_completeness +
  0.10 * relationships_completeness
)
```

---

## Favourited Profile Continuous Enrichment (NEW in v3.0)

### SLA-Based Freshness Re-Crawl

```
Freshness SLA by Source Type:
  Social Media:      6-12 hours (volatile)
  Business Profiles: Weekly (slower change)
  Court Records:     Monthly (static once filed)
  Sanctions Lists:   Daily (compliance-critical)
  Property:          Monthly
  Financial:         Weekly (APIs may rate-limit)
```

### Implementation

```python
# Batch job: refresh profiles by SLA
def refresh_favourites():
    profiles = get_favourited_profiles()
    for profile in profiles:
        for source in profile.data_sources:
            if time_since_last_crawl(source) > source.sla:
                # Re-crawl
                result = crawl_source(source)
                
                # Diff-check
                old_data = profile.data[source]
                new_data = result
                diffs = compare(old_data, new_data)
                
                if diffs:
                    # Notify operator of changes
                    send_notification({
                        'profile_id': profile.id,
                        'source': source,
                        'changes': diffs,
                        'timestamp': now()
                    })
                    
                    # Store change history
                    audit_log(profile, source, diffs)
```

---

## Never-Give-Up Retry Logic (NEW in v3.0)

### Intelligent Backoff & Failover

**Failure Response Strategy:**

```
Attempt 1 (Immediate):
  → Fail: Rate-limited or temporarily down
  → Action: Switch proxy, try again

Attempt 2 (After 5 minutes):
  → Fail: Still down
  → Action: Change User-Agent, update TLS fingerprint, retry

Attempt 3 (Off-Peak):
  → Fail: Peak hours?
  → Action: Queue for batch crawl during low-traffic window (2-4am)

Attempt 4+ (Capacity-Based):
  → Monitor server load: if load < 60%, retry
  → Exponential backoff: 5m → 15m → 60m → 4h → 24h
  → Max retries: 10 per source
```

### Implementation

```python
# Retry decorator with smart backoff
@retry_with_backoff(
    max_attempts=10,
    base_delay_seconds=300,  # 5 min
    exponential_base=3,  # 5m → 15m → 60m
)
async def fetch_with_failover(url: str, source_name: str):
    attempt = 0
    while attempt < max_attempts:
        try:
            # Try with current proxy/UA
            async with aiohttp.ClientSession() as session:
                proxy = rotate_proxy()
                ua = rotate_user_agent()
                async with session.get(url, proxy=proxy, headers={'User-Agent': ua}) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status in (429, 503):  # Rate limit or service unavailable
                        raise TemporaryError(f"Status {resp.status}")
                    else:
                        raise PermanentError(f"Status {resp.status}")
        except TemporaryError:
            attempt += 1
            if attempt < max_attempts:
                delay = base_delay * (exponential_base ** (attempt - 1))
                # If off-peak, schedule for batch; otherwise wait
                if is_peak_hours() and attempt >= 3:
                    queue_for_batch(url, source_name, priority=HIGH)
                    return None  # Defer
                else:
                    await asyncio.sleep(delay)
            else:
                raise
        except PermanentError:
            log_source_failure(source_name, url)
            return None
    
    # Capacity-based retry
    if get_server_load() < 0.60:
        await asyncio.sleep(random.uniform(60, 300))
        return await fetch_with_failover(url, source_name)  # Retry
```

---

## Admiralty Code Quality Framework (NEW in v3.0)

### Quality Score Calculation

Each data point gets a quality score to inform relevance and trust:

```
quality_score = (
    timeliness × 0.25 +
    freshness × 0.25 +
    credibility × 0.25 +
    source_reliability × 0.25
)

where:
  timeliness = (1 - (days_old / 365)) * credibility_multiplier
  freshness = 1 - (days_since_last_refresh / max_age)
  credibility = source_accuracy_rate (0-1)
  source_reliability = source_uptime_percent (0-1)

Result: 0-100 quality_score
```

### Source Reliability Tiers

```
Tier 1 (95-100): Government records, court filings, official business registries
Tier 2 (85-95):  Major data brokers, social media APIs, credit bureaus
Tier 3 (70-85):  Public web scraping, business listings, volunteer databases
Tier 4 (50-70):  Third-party forums, user-submitted data, historical archives
Tier 5 (<50):    Unreliable, manually-submitted, unverified sources
```

### Display in UI

```
Data Point: Jane Doe @ Acme Corp (Senior Manager)
├─ Source: LinkedIn
├─ Last Updated: 2026-01-15 (69 days old)
├─ Quality Score: 87/100
│  ├─ Timeliness: 80
│  ├─ Freshness: 75 (should refresh weekly)
│  ├─ Credibility: 95 (LinkedIn accuracy ~95%)
│  └─ Source Reliability: 99 (LinkedIn uptime ~99.9%)
└─ [Refresh This Record]
```

---

## Task Orchestration & Queuing (NEW in v3.0)

### Primary: Temporal.io

Distributed workflow engine for:
- Complex multi-step crawling workflows
- Long-running searches
- Scheduled re-crawls by SLA
- Retry logic with exponential backoff
- Resumability after crashes

### Secondary: Dramatiq + Apache Pulsar

Lighter-weight task queue for:
- Simple fire-and-forget jobs (e.g., log entries)
- High-throughput async tasks
- Optional Pulsar for multi-region support
- LGPL-3 license (approved)

### Configuration

```yaml
# Temporal config
temporal:
  server_address: localhost:7233
  namespace: lycan
  worker_queue: default
  max_concurrent_activities: 100

# Dramatiq config (alternative)
dramatiq:
  broker: "amqp://rabbitmq:5672/"
  # OR
  broker: "redis://dragonfly:6379/"
  worker_threads: 32
  prefetch: 10
```

---

## API Specification (Complete Endpoint List)

All endpoints require authentication (JWT or API key). All responses are JSON.

### Authentication & Rate Limiting

**Request Headers:**
```
Authorization: Bearer {jwt_token}
  OR
X-API-Key: {api_key}

X-Request-ID: {uuid}  (optional, auto-generated if missing)
```

**Rate Limits (per API key):**
- Search endpoints: 100 req/min
- Data endpoints: 1000 req/min
- Batch endpoints: 10 req/min
- Admin endpoints: 50 req/min

### Search Endpoints

#### POST /api/v1/search/person
Search for a person by name, phone, email, or address.

```json
Request:
{
  "first_name": "John",
  "last_name": "Doe",
  "phone": "555-0123",
  "email": "john@example.com",
  "address": "123 Main St, Springfield, IL 62701",
  "dob": "1980-01-15",
  "expand_networks": true,
  "timeout_seconds": 60,
  "preferred_sources": ["linkedin", "facebook", "court_records"],
  "skip_sources": ["rumor_sites"]
}

Response (201 Created):
{
  "search_id": "search_abc123def456",
  "status": "running",
  "created_at": "2026-03-24T10:00:00Z",
  "expires_at": "2026-03-25T10:00:00Z",
  "progress_url": "/api/v1/search/search_abc123def456/progress",
  "status_url": "/api/v1/search/search_abc123def456/status",
  "results_url": "/api/v1/search/search_abc123def456/results"
}
```

#### GET /api/v1/search/{search_id}/status
Poll for search status.

```json
Response:
{
  "search_id": "search_abc123def456",
  "status": "complete",
  "result_count": 3,
  "sources_checked": 47,
  "sources_pending": 0,
  "progress_percent": 100,
  "completed_at": "2026-03-24T10:05:30Z",
  "duration_seconds": 330
}
```

#### GET /api/v1/search/{search_id}/results
Get search results. Paginated. Shows multi-candidate cards.

```json
Response:
{
  "search_id": "search_abc123def456",
  "total_matches": 3,
  "results": [
    {
      "person_id": "person_xyz789",
      "match_score": 0.98,
      "name": "John Michael Doe",
      "dob": "1980-01-15",
      "current_address": "123 Main St, Springfield, IL 62701",
      "phone": "555-0123",
      "email": "john@example.com",
      "sources": ["spokeo", "whitepages", "linkedin"],
      "last_updated": "2026-03-20T00:00:00Z",
      "confidence_score": 0.95,
      "photos": [
        {
          "url": "https://...",
          "source": "linkedin",
          "phash": "8f8f8f8f...",
          "facial_embedding": [0.1, 0.2, ...],
          "confirmed_face": true
        }
      ],
      "enrichment_score": 73,
      "enrichment_gaps": ["financial", "property_details"]
    },
    ...
  ],
  "pagination": {
    "page": 1,
    "per_page": 10,
    "total_pages": 1
  }
}
```

#### GET /api/v1/search/{search_id}/progress (Server-Sent Events)
Real-time progress stream with expanding results.

```
event: progress
data: {"progress_percent": 25, "sources_checked": 12, "results_so_far": 1}

event: result
data: {
  "person_id": "person_abc",
  "name": "John Doe",
  "match_score": 0.98,
  "candidate_faces": [...],
  "enrichment_score": 73
}

event: source_status
data: {"source": "facebook", "status": "checking"}

event: enrichment_gap
data: {"category": "financial", "action": "start_deep_enrich"}

event: complete
data: {"total_results": 3, "duration_seconds": 330}
```

#### PATCH /api/v1/search/{search_id}/params
Update search parameters while search is running.

```json
Request:
{
  "expand_networks": true,
  "timeout_seconds": 120,
  "preferred_sources": ["linkedin", "facebook"]
}

Response (200 OK):
{
  "search_id": "search_abc123def456",
  "updated_params": {...}
}
```

#### POST /api/v1/search/{person_id}/enrichment/deep
Trigger deep enrichment targeting specific gaps.

```json
Request:
{
  "target_categories": ["financial", "property"]
}

Response (202 Accepted):
{
  "person_id": "person_xyz789",
  "enrichment_job_id": "job_123",
  "status": "queued",
  "estimated_completion": "2026-03-24T11:00:00Z"
}
```

#### POST /api/v1/profiles/favourite
Mark a profile as favourite for continuous enrichment.

```json
Request:
{
  "person_id": "person_xyz789"
}

Response (201 Created):
{
  "person_id": "person_xyz789",
  "favourite_id": "fav_123",
  "refresh_sla": {...}
}
```

#### GET /api/v1/profiles/favourite/{person_id}/changes
Get recent changes to a favourited profile (continuous enrichment).

```json
Response:
{
  "person_id": "person_xyz789",
  "recent_changes": [
    {
      "timestamp": "2026-03-24T09:30:00Z",
      "source": "linkedin",
      "field": "current_employer",
      "old_value": "Acme Corp",
      "new_value": "TechCorp Inc",
      "quality_score": 92
    },
    ...
  ]
}
```

#### GET /api/v1/sources/review
Get pending discovered sources awaiting approval (Review Tab).

```json
Response:
{
  "pending_sources": [
    {
      "source_id": "src_123",
      "name": "example.com/people",
      "url": "https://example.com/people",
      "category": "business_profiles",
      "data_quality_estimate": 0.82,
      "legal_risk": "low",
      "proposed_pattern": {
        "selectors": {"name": "h1.name", "email": "span.email"},
        "pagination": "next_link"
      },
      "discovered_by": "SpiderFoot",
      "discovered_at": "2026-03-24T08:00:00Z"
    },
    ...
  ]
}
```

#### POST /api/v1/sources/{source_id}/approve
Approve a discovered source and build crawler.

```json
Request:
{
  "approval_notes": "High-quality business directory"
}

Response (201 Created):
{
  "source_id": "src_123",
  "status": "approved",
  "crawler_job_id": "job_456",
  "estimated_first_crawl": "2026-03-24T12:00:00Z"
}
```

---

## Phase Plan (Updated for v3.0)

### Phase 1: Foundation & Security (Week 1-2) ⚠️ CRITICAL PRIORITY

**Goals:**
- Verify license compliance for all dependencies (new: Playwright, Typesense, Dramatiq)
- Set up Dragonfly cache layer (replaces Redis)
- Deploy Typesense instance (alongside or replacing MeiliSearch)
- Begin Playwright + playwright-stealth integration (replaces Nodriver)
- Set up Temporal.io or Dramatiq task queue

**Tasks:**
1. License audit: run `pip-audit` + check all transitive dependencies against license safety tier
2. Dragonfly: deploy and validate Redis-compatible cache
3. Typesense: deploy and configure full-text search
4. Playwright: install `playwright` + `playwright-stealth`, remove `nodriver`
5. Task queue: set up Temporal.io server or Dramatiq broker
6. Database: add new tables (reviewed above)
7. Tests: unit tests for all license compliance

**Definition of Done:**
- All tools are MIT/Apache/BSD/GPL/LGPL/MPL-2.0 only
- Dragonfly operational, tests passing
- Typesense operational, typo-tolerant search working
- Playwright stealth mode active, anti-bot detection bypass verified
- Task queue operational, test jobs completing

### Phase 2: Core Infrastructure (Week 3-4)

**Goals:**
- Finalize PostgreSQL schema (34 tables)
- Deploy Apache AGE for graph queries
- Deploy Qdrant for vector embeddings
- Integrate all databases

**Tasks:**
1. PostgreSQL: create all 34 tables with indexes
2. Apache AGE: install and configure on PostgreSQL
3. Qdrant: deploy and create collections (person_embeddings, facial_embeddings)
4. Migration scripts: populate existing data into new schema
5. Validation: test all indexes and query performance
6. Tests: integration tests across databases

**Definition of Done:**
- All 34 tables present with data
- AGE graph queries working
- Qdrant collections operational
- Index performance validated (P99 < 100ms for common queries)

### Phase 3: Dedup & Entity Resolution (Week 5-6)

**Goals:**
- Implement 4-pass dedup engine
- Integrate Splink for probabilistic matching
- Build golden record creation and merging

**Tasks:**
1. Splink: integrate for probabilistic record linkage
2. Pass 1: exact match (name + DOB + phone)
3. Pass 2: fuzzy match (Levenshtein on normalized fields)
4. Pass 3: graph-based (shared phone/email → linked)
5. Pass 4: ML-based (Splink model trained on known duplicates)
6. Golden record: create canonical record, merge aliases
7. Tests: dedup validation, golden record integrity

**Definition of Done:**
- All records have golden_record_id
- 4-pass pipeline working end-to-end
- Splink model trained and deployed
- Zero-duplicate guarantee enforced

### Phase 4: Scraper Expansion & Open Discovery (Week 7-10)

**Goals:**
- Expand scraper count from 100+ to 1000+ sources
- Implement Track 1 (predefined) and Track 2 (open discovery)
- Deploy SpiderFoot, Amass, theHarvester, Sherlock, Maigret
- Build Review Tab for source approval

**Tasks:**
1. SpiderFoot: deploy and integrate all 100+ reconnaissance modules
2. Amass: configure for subdomain/DNS enumeration, CT logs
3. theHarvester: email harvesting, search engine dorking
4. Sherlock: username enumeration across 600+ platforms
5. Maigret: cross-platform username search
6. Google Dorking: automated search operator generation
7. Common Crawl + Wayback: historical data ingestion
8. Review Tab UI: operator approval workflow
9. Auto-crawler: one-click spider generation from approved sources
10. Never-give-up retry logic: proxy rotation, UA switching, off-peak batching
11. Tests: crawler success rates, source quality scoring

**Definition of Done:**
- 1,000+ sources configured (500 predefined + 500 discovered)
- Track 1 and Track 2 both operational
- Review Tab deployed and tested
- Never-give-up retry hitting 95%+ success rate
- Freshness SLA enforcement live

### Phase 5: Financial & AML Intelligence (Week 11-13)

**Goals:**
- Alternative credit scoring
- AML/KYC screening
- PEP detection
- Fraud risk modeling

**Tasks:**
1. Credit model: train on unbanked/subprime data, deploy scoring
2. AML lists: integrate OFAC, EU sanctions, UK sanctions lists
3. PEP detection: cross-reference against public PEP databases
4. Fraud indicators: build risk model from historical fraud patterns
5. APIs: integrate with external providers (if needed)
6. Tests: compliance validation, risk score accuracy

**Definition of Done:**
- Credit scores computed for 90%+ of records
- AML screening automated, alert triggering working
- PEP detection for all officers/associates
- Fraud risk scoring deployed

### Phase 6: Marketing Intelligence (Week 14-15)

**Goals:**
- Consumer tagging (title loans, gambling interest, etc.)
- Ticket size (CLV) estimation
- Behavioral segmentation
- Lead scoring

**Tasks:**
1. Tags: define 50+ consumer tags, build classification model
2. CLV: train ticket size model from engagement data
3. Segmentation: behavioral/demographic clustering
4. Lead scoring: propensity models for common use cases
5. Tests: tag accuracy, model calibration

**Definition of Done:**
- Tags assigned to 95%+ of records
- CLV estimated for all records
- Segments created and validated
- Lead scores computed and calibrated

### Phase 7: Search & UI Enhancements (Week 16-17)

**Goals:**
- Real-time search with progress bars
- Multi-candidate cards with photos
- Facial matching (pHash + embeddings)
- Enrichment Score gauge with gap analysis
- Favourited profile continuous enrichment

**Tasks:**
1. Real-time search: SSE stream with progress
2. Multi-candidate UI: card-based presentation
3. Facial matching: extract faces, compute pHash, build embeddings
4. Enrichment Score: calculate 0-100 score with gaps
5. "Deep Enrich" button: trigger targeted crawls
6. Favourites: SLA-based re-crawl, diff notifications
7. UI tests: visual regression, performance

**Definition of Done:**
- Search returns multi-candidate cards within 5 seconds
- Facial matching finds same person across platforms (90%+ accuracy)
- Enrichment Score accurate and actionable
- Favourites re-crawl on schedule, diffs detected

### Phase 8: Pattern Detection & ML (Week 18-20)

**Goals:**
- Graph analysis for networks
- Anomaly detection
- Fraud ring identification
- Admiralty Code quality framework
- Real-time alerting

**Tasks:**
1. Graph queries: Apache AGE for network traversal
2. Anomaly detection: isolation forest on embeddings
3. Fraud rings: detect highly connected high-risk networks
4. Admiralty Code: implement quality_score formula
5. Alerting: real-time anomaly notifications
6. Tests: fraud ring detection accuracy, alert precision

**Definition of Done:**
- Graph queries fast (< 500ms for 3-hop traversal)
- Anomalies detected with precision > 90%
- Fraud rings identified (validated against known cases)
- Quality scores accurate and useful

### Phase 9: Compliance & Hardening (Week 21-22)

**Goals:**
- GDPR/CCPA compliance
- Opt-out enforcement
- Audit logging
- Data retention policies

**Tasks:**
1. Opt-outs: store and enforce against all searches
2. Audit log: log all data access with user/timestamp/purpose
3. Data deletion: implement GDPR right-to-be-forgotten
4. Retention: automated data archival and deletion by policy
5. Tests: compliance validation, audit trail integrity

**Definition of Done:**
- Opt-out requests enforced within 24 hours
- Audit log 100% complete (no gaps)
- Data deletion working correctly
- GDPR/CCPA assessments passing

### Phase 10: Testing & Production (Week 23-24)

**Goals:**
- End-to-end testing
- Load testing
- Security hardening
- Production deployment

**Tasks:**
1. E2E tests: all workflows from search to enrichment
2. Load testing: 1000 concurrent searches, 100 scraper threads
3. Security: penetration testing, OWASP validation
4. Monitoring: Prometheus + Grafana dashboards
5. Deployment: Kubernetes or container orchestration
6. Documentation: API docs, operator manuals, runbooks

**Definition of Done:**
- All tests passing (unit, integration, E2E)
- Load test results meet SLAs
- Security audit passed
- Production metrics healthy
- Documentation complete

---

## Reference Documentation

All specifications are detailed in docs 01-14:

1. **01-tech-stack.md** — Detailed tech stack decisions and justifications
2. **02-modular-architecture.md** — Service boundaries, inter-service communication
3. **03-deduplication-verification.md** — 4-pass dedup and golden record logic
4. **04-collection-crawling.md** — Scraper architecture, Scrapy setup, retry logic
5. **05-data-enrichment-categories.md** — 2,350+ data points across 7 categories
6. **06-financial-aml-credit.md** — Credit scoring, AML/KYC, PEP detection
7. **07-patterns-indexing-future.md** — Graph analysis, anomaly detection, ML roadmap
8. **08-osint-audit-report.md** — Compliance audit findings and remediation
9. **09-bots-crawlers-catalog.md** — Catalog of 1,000+ source crawlers
10. **10-marketing-tags-scoring.md** — Consumer tagging, CLV, segmentation, lead scoring
11. **11-progress-realtime-ui.md** — Real-time search, SSE, progress tracking
12. **12-ethical-legal-compliance.md** — GDPR, CCPA, terms of service, opt-out framework
13. **13-knowledge-graph-company-intel.md** — Company graph, officer tracking, network analysis
14. **14-deep-code-audit.md** — Code review, security audit, performance bottlenecks, refactoring recommendations

---

## Key Decisions Summary (v3.0)

1. **Licensing:** All tools must be MIT/Apache/BSD/GPL/LGPL/MPL-2.0. No AGPL or BSL. Playwright replaces Nodriver. Typesense replaces MeiliSearch.

2. **Scale:** 1,000+ data sources (predefined + open discovery via SpiderFoot, Amass, theHarvester, Sherlock, Maigret).

3. **Quality:** Admiralty Code framework for data quality scoring (timeliness × freshness + credibility × source_reliability + completeness + corroboration).

4. **Continuous Enrichment:** Favourited profiles re-crawled per SLA (social 6-12h, business weekly, courts monthly, sanctions daily). Diff notifications on change.

5. **Retry Logic:** Never-give-up with smart failover (proxy rotation → UA/TLS change → off-peak batch → capacity-based).

6. **Multi-Candidate Matching:** Facial photos with pHash + embedding cosine distance for cross-platform deduplication.

7. **Enrichment Score:** 0-100 gauge with gap analysis. One-click "Deep Enrich" to target gaps.

8. **Review Tab:** Operators approve discovered sources. One-click crawler auto-generation and deployment.

9. **Task Orchestration:** Temporal.io (primary) + Dramatiq (lightweight alternative).

10. **Government-Grade:** Enterprise compliance, audit logging, opt-out enforcement, GDPR/CCPA ready.

---

## Building from This Spec

**For Claude Code or other agents:**

1. Read this document in full
2. Reference docs 01-14 for implementation details
3. Follow the Phase Plan sequentially
4. Use the API Specification as your contract
5. Validate against the License Safety Tier before committing any dependency
6. Run tests after every phase

This spec is complete and actionable. You have everything needed to build Lycan.

---

**Document Version:** 3.0 (March 25, 2026)
**Status:** Production-Ready
**Next Review:** After Phase 10 completion
