# LYCAN OSINT/DATA BROKER PLATFORM — MASTER BUILD SPEC

## CRITICAL: How to Use This Specification

This document is **the** authoritative source for building Lycan from the ground up.

**Read this first. Then read docs 01-12 in the `/docs` folder for detailed specifications.**

Every developer receiving this should:
1. Start with this document to understand the complete system
2. Reference docs 01-12 as needed for implementation details
3. Follow the Phase Plan sequentially
4. Build modules in strict modular isolation (see Architecture section)
5. Run tests after every module completion
6. Validate against compliance rules in doc 12

**This is production software.** The existing codebase is ~70% MVP, ~10% production-ready, ~5% enterprise-grade. This spec elevates it to 100% production + enterprise capability.

---

## Project Overview

Lycan is a comprehensive **data broker and OSINT intelligence platform** that aggregates, deduplicates, enriches, and serves data on individuals and businesses at scale.

**Competitive Landscape:** Lycan competes with Axiom, LexisNexis, Spokeo, TransUnion, and Equifax in the data intelligence space.

**Core Business Model:**
- Data aggregation from 100+ public and semi-public sources
- Zero-duplicate guarantees via 4-pass entity resolution
- Enrichment to 2,350+ data points across 7 categories
- Alternative credit scoring and financial intelligence
- Marketing intelligence (segmentation, lead scoring, affinity modeling)
- Real-time pattern detection and anomaly alerting
- White-label API for enterprises, B2B2C, and fintech partners

### What Lycan Does (Capabilities)

1. **Data Collection & Aggregation** (docs 01, 09)
   - Maintains 100+ active scraper/crawler workflows
   - Collects from public records, open APIs, social platforms, government databases
   - Auto-detects scraper failures and resets them
   - Supports both push (webhook) and pull (polling) data sources

2. **Entity Resolution & Deduplication** (doc 03)
   - 4-pass dedup: exact → fuzzy → graph → ML-based matching
   - Maintains golden record for each unique person/business
   - Tracks all mentions and aliases
   - Zero-duplicate guarantee — violations trigger alerts

3. **Data Enrichment** (docs 05, 06, 10)
   - Normalizes and validates all data fields
   - Enriches with external APIs (coordinates, reverse geocoding, etc.)
   - Cross-references records across sources
   - Assigns confidence scores to every data point

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

7. **Pattern Detection & Networks** (doc 07)
   - Graph analysis for relationship mapping
   - Anomaly detection (unusual activity patterns)
   - Fraud ring identification
   - Network visualization
   - Real-time alerting

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

## Technical Architecture

### Tech Stack Summary

| Layer | Tech | Justification |
|-------|------|---------------|
| **Language** | Python 3.12+ (primary) | Existing codebase, ML/NLP ecosystem, rapid iteration |
| | Rust via PyO3 (secondary) | String matching, dedup engine, Bloom filters (performance-critical paths only) |
| **API Framework** | FastAPI | Async-native, performance, OpenAPI docs, Pydantic validation |
| **Database** | PostgreSQL 16 | JSONB, full-text search, pg_trgm, PostGIS, materialized views |
| **Cache/Broker** | Dragonfly | Redis-compatible, 25x faster, lower memory footprint |
| **Vector Search** | Qdrant | Semantic search, ML embeddings, similarity search |
| **Full-Text Search** | MeiliSearch | Typo-tolerant, fast, already in codebase |
| **Graph Queries** | Apache AGE (on Postgres) | Native graph database without separate infrastructure |
| **Workflow Engine** | Temporal.io | Distributed workflows, retry logic, resumability |
| **Async Tasks** | Redis Streams | Job queue, worker distribution, at-least-once delivery |
| **Real-Time** | Server-Sent Events (SSE) | Browser-native, no WebSocket complexity, progress tracking |
| **Monitoring** | Prometheus + Grafana | Metrics, dashboards, alerting |
| **Containerization** | Docker + Docker Compose | Reproducible environments, local dev, cloud deployment |
| **CI/CD** | GitHub Actions | Already configured, integrated with existing repo |

### Why Python (Not Go/Rust/Node)?

**Decision: Python with Rust for hot paths only.**

**Reasoning:**
- Existing codebase is Python + team expertise
- ML/NLP ecosystem is unmatched (scikit-learn, XGBoost, sentence-transformers)
- Data enrichment pipelines use pandas/Polars (Python)
- OSINT tools (Sherlock, holehe, Maigret) are Python-based
- Development velocity is critical in early stages
- **Do not rewrite in Rust.** Profile first, optimize only where Python bottlenecks exist
- Use Rust via PyO3 only for: string similarity (Levenshtein at 100K+ records/sec), Bloom filters, cryptographic hashing

### Database Architecture

#### Primary Database: PostgreSQL 16

**Core Tables (28 existing + 6 new = 34 total)**

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

**New Tables (Required for Phase 4-8):**
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

-- Full-text search (optional, use MeiliSearch instead)
CREATE INDEX idx_persons_name_search ON persons USING GIN(to_tsvector('english', name));
```

#### Cache Layer: Dragonfly (Redis-Compatible)

Dragonfly replaces Redis with 25x faster performance and 40% less memory:

```
Cache Keys:
  person:{id}:full_record       — Full person record with all relations (TTL: 24h)
  person:{id}:enrichment_v2     — Enriched data only (TTL: 7d)
  phone:{normalized}:person_id  — Phone-to-person mapping (TTL: 30d)
  email:{normalized}:person_id  — Email-to-person mapping (TTL: 30d)
  search:{search_id}:status     — Search status (TTL: 7d)
  search:{search_id}:results    — Cached results (TTL: 24h)
  scraper:{name}:health        — Scraper health status (TTL: 5m)
  rate_limit:{api_key}         — Per-key rate limit counter (TTL: 1m)
```

#### Vector Database: Qdrant

```
Collections:
  person_embeddings      — Sentence-BERT embeddings of person profiles (384-dim)
  social_profile_text    — Social profile text embeddings
  document_embeddings    — Text from documents (resumes, etc.)
```

Used for:
- Semantic similarity search
- Finding similar profiles across sources
- Anomaly detection (outlier embeddings)

#### Full-Text Search: MeiliSearch

Already in codebase. Maintain for typo-tolerant search.

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
  "timeout_seconds": 60
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
Get search results. Paginated.

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
      "confidence_score": 0.95
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
data: {"person_id": "person_abc", "name": "John Doe", "match_score": 0.98}

event: source_status
data: {"source": "facebook", "status": "checking"}

event: complete
data: {"total_results": 3, "duration_seconds": 330}
```

#### PATCH /api/v1/search/{search_id}/params
Update search parameters while search is running.

```json
Request:
{
  "expand_networks": true,
  "include_deceased": true,
  "timeout_seconds": 120
}

Response (200 OK):
{
  "search_id": "search_abc123def456",
  "updated_params": {
    "expand_networks": true,
    "include_deceased": true,
    "timeout_seconds": 120
  },
  "status": "running"
}
```

#### POST /api/v1/search/{search_id}/expand
Trigger growth expansion (find associated networks).

```json
Response (202 Accepted):
{
  "search_id": "search_abc123def456",
  "growth_started": true,
  "additional_sources": 15,
  "estimated_completion": "2026-03-24T10:20:00Z"
}
```

#### POST /api/v1/search/business
Search for business by name, EIN, address.

```json
Request:
{
  "business_name": "Acme Corp",
  "state": "CA",
  "ein": "12-3456789",
  "include_officers": true,
  "include_filings": true
}

Response:
{
  "search_id": "search_biz_def456",
  "status": "running",
  ...
}
```

#### POST /api/v1/search/phone
Reverse phone lookup.

```json
Request:
{
  "phone": "555-0123",
  "country": "US"
}

Response:
{
  "search_id": "search_phone_123",
  "phone": "555-0123",
  "matches": [
    {
      "person_id": "person_xyz",
      "name": "John Doe",
      "phone_type": "mobile",
      "last_updated": "2026-03-20"
    }
  ]
}
```

#### POST /api/v1/search/email
Reverse email lookup.

```json
Request:
{
  "email": "john@example.com"
}

Response:
{
  "search_id": "search_email_456",
  "email": "john@example.com",
  "matches": [
    {
      "person_id": "person_xyz",
      "name": "John Doe",
      "email_verified": true,
      "last_updated": "2026-03-20"
    }
  ]
}
```

### Person Data Endpoints

#### GET /api/v1/person/{person_id}
Full person profile.

```json
Response:
{
  "person_id": "person_xyz789",
  "name": "John Michael Doe",
  "aliases": ["J Doe", "John M Doe"],
  "dob": "1980-01-15",
  "age": 46,
  "gender": "Male",
  "ssn_last_4": "6789",
  "current_address": {
    "street": "123 Main St",
    "city": "Springfield",
    "state": "IL",
    "zip": "62701",
    "country": "US",
    "coordinates": [39.7817, -89.6501]
  },
  "address_history": [
    {
      "street": "456 Oak Ave",
      "city": "Chicago",
      "state": "IL",
      "zip": "60601",
      "from_date": "2018-01-15",
      "to_date": "2023-01-15"
    }
  ],
  "phones": [
    {
      "phone": "555-0123",
      "type": "mobile",
      "verified": true,
      "carrier": "Verizon",
      "last_seen": "2026-03-20"
    }
  ],
  "emails": [
    {
      "email": "john@example.com",
      "verified": true,
      "last_seen": "2026-03-20"
    }
  ],
  "employment": [
    {
      "employer": "Acme Corp",
      "position": "Senior Manager",
      "start_date": "2020-03-01",
      "end_date": null,
      "status": "current"
    }
  ],
  "education": [
    {
      "institution": "University of Illinois",
      "degree": "Bachelor of Science",
      "field": "Computer Science",
      "graduation_year": 2002
    }
  ],
  "social_profiles": [
    {
      "platform": "linkedin",
      "handle": "john-doe-123",
      "url": "https://linkedin.com/in/john-doe-123",
      "followers": 5000,
      "verified": true
    }
  ],
  "properties": [
    {
      "address": "123 Main St, Springfield, IL 62701",
      "county": "Sangamon",
      "property_type": "Single Family",
      "value_estimate": 450000,
      "ownership_date": "2019-06-15"
    }
  ],
  "vehicles": [
    {
      "year": 2021,
      "make": "Tesla",
      "model": "Model 3",
      "vin": "5YJ3E1EA5MF123456",
      "registered_owner": true
    }
  ],
  "court_records": [
    {
      "case_type": "Small Claims",
      "amount": 5000,
      "status": "Settled",
      "date": "2018-03-15"
    }
  ],
  "criminal_history": [
    {
      "offense": "Traffic Violation",
      "conviction_date": "2015-06-20",
      "sentence": "Fine",
      "status": "Closed"
    }
  ],
  "data_sources": [
    {
      "source_name": "spokeo",
      "last_collected": "2026-03-20",
      "collection_method": "scrape"
    }
  ],
  "confidence_score": 0.95,
  "data_freshness": "2026-03-20T00:00:00Z",
  "last_updated": "2026-03-24T10:00:00Z"
}
```

#### GET /api/v1/person/{person_id}/financial
Financial profile (credit, AML, fraud).

```json
Response:
{
  "person_id": "person_xyz789",
  "credit_profile": {
    "alt_credit_score": 680,
    "alt_credit_percentile": 65,
    "model_version": "v2.3",
    "calculated_date": "2026-03-24",
    "factors": [
      "limited_credit_history",
      "high_utilization",
      "missed_payments"
    ]
  },
  "aml_screening": {
    "screening_date": "2026-03-24T10:00:00Z",
    "overall_risk": "low",
    "sanctions_hit": false,
    "pep_status": "not_pep",
    "adverse_media": false,
    "pep_details": null,
    "sanctions_match": null
  },
  "fraud_risk": {
    "fraud_score": 0.15,
    "risk_level": "low",
    "indicators": [
      "velocity_check_passed",
      "address_consistency_good"
    ]
  }
}
```

#### GET /api/v1/person/{person_id}/marketing
Marketing tags and segments.

```json
Response:
{
  "person_id": "person_xyz789",
  "marketing_tags": [
    {
      "tag": "title_loan_candidate",
      "confidence": 0.78,
      "reason": "vehicle_ownership_high_debt_indicators"
    },
    {
      "tag": "gambler",
      "confidence": 0.45,
      "reason": "online_activity_patterns"
    }
  ],
  "ticket_size": {
    "estimated_clv": 45000,
    "percentile": 72,
    "segments": ["middle_income", "suburban", "family_oriented"]
  },
  "segments": [
    "suburban_middle_class",
    "family_household",
    "tech_adopter",
    "home_improvement_interest"
  ],
  "lead_score": 0.82,
  "propensity": {
    "car_loan": 0.88,
    "mortgage_refinance": 0.72,
    "credit_card": 0.65
  }
}
```

#### GET /api/v1/person/{person_id}/connections
Relationship graph.

```json
Response:
{
  "person_id": "person_xyz789",
  "direct_connections": 12,
  "network_size": 1247,
  "relationships": [
    {
      "connected_person_id": "person_abc123",
      "connected_name": "Jane Smith",
      "relationship_type": "family",
      "relationship_strength": 0.95,
      "common_attributes": ["address", "phone"]
    }
  ],
  "clusters": [
    {
      "cluster_id": "family_cluster_1",
      "size": 5,
      "members": ["person_xyz789", "person_abc123", ...]
    }
  ]
}
```

#### GET /api/v1/person/{person_id}/score
All scores aggregated.

```json
Response:
{
  "person_id": "person_xyz789",
  "credit_score": 680,
  "fraud_score": 0.15,
  "aml_risk_score": 0.05,
  "lead_score": 0.82,
  "data_quality_score": 0.93,
  "overall_risk_score": 0.15
}
```

### Business Endpoints

#### GET /api/v1/business/{business_id}
Full business profile.

```json
Response:
{
  "business_id": "business_acme123",
  "legal_name": "Acme Corporation",
  "dba_names": ["Acme Corp", "ACME"],
  "ein": "12-3456789",
  "state_id": "CA-123456",
  "business_type": "C Corporation",
  "founded_date": "1995-03-15",
  "status": "Active",
  "industry": "Technology",
  "naics_code": "541511",
  "headquarters": {
    "street": "100 Tech Drive",
    "city": "San Francisco",
    "state": "CA",
    "zip": "94105"
  },
  "phone": "415-555-0123",
  "website": "https://acme.com",
  "employees_estimated": 5000,
  "annual_revenue_estimated": 500000000,
  "officers": [
    {
      "name": "John Smith",
      "title": "CEO",
      "person_id": "person_xyz123",
      "tenure_start": "2010-01-15"
    }
  ],
  "filings": [
    {
      "filing_type": "Annual Report",
      "filing_date": "2024-12-31",
      "revenue": 500000000,
      "expenses": 450000000
    }
  ],
  "data_sources": ["linkedin", "sec_filings", "state_sos"],
  "risk_score": 0.08,
  "last_updated": "2026-03-24T10:00:00Z"
}
```

#### GET /api/v1/business/{business_id}/officers
Officers and beneficial owners.

```json
Response:
{
  "business_id": "business_acme123",
  "officers": [...],
  "beneficial_owners": [
    {
      "person_id": "person_xyz123",
      "name": "John Smith",
      "ownership_percent": 45.5,
      "title": "Beneficial Owner"
    }
  ]
}
```

### Enrichment Endpoints

#### POST /api/v1/enrich/person
Enrich a person record with external data.

```json
Request:
{
  "person_id": "person_xyz789"
}

Response (202 Accepted):
{
  "enrichment_id": "enrich_abc123",
  "person_id": "person_xyz789",
  "status": "queued",
  "estimated_completion": "2026-03-24T10:05:00Z"
}
```

#### POST /api/v1/enrich/batch
Batch enrichment.

```json
Request:
{
  "person_ids": ["person_xyz789", "person_abc123"],
  "data_types": ["financial", "marketing", "network"]
}

Response:
{
  "batch_id": "batch_enrich_456",
  "total_records": 2,
  "status": "queued"
}
```

### Financial Endpoints

#### POST /api/v1/financial/credit-score/{person_id}
Calculate alternative credit score.

```json
Request:
{
  "include_explainability": true
}

Response:
{
  "person_id": "person_xyz789",
  "credit_score": 680,
  "percentile": 65,
  "model": "v2.3",
  "factors": [
    {
      "factor": "payment_history",
      "impact": -0.15,
      "contribution": "negative"
    }
  ],
  "recommended_actions": [
    "reduce_credit_utilization",
    "maintain_payment_schedule"
  ]
}
```

#### POST /api/v1/financial/aml-screen
Run AML/KYC screening.

```json
Request:
{
  "person_id": "person_xyz789",
  "check_sanctions": true,
  "check_pep": true,
  "check_adverse_media": true
}

Response:
{
  "screening_id": "aml_screen_789",
  "person_id": "person_xyz789",
  "status": "complete",
  "overall_risk": "low",
  "checks": {
    "sanctions": { "status": "clear", "lists": ["OFAC", "EU", "UN"] },
    "pep": { "status": "clear" },
    "adverse_media": { "status": "no_hits" }
  },
  "recommendation": "approve"
}
```

### Marketing Endpoints

#### GET /api/v1/marketing/tags/{person_id}
Marketing tags for person.

```json
Response:
{
  "person_id": "person_xyz789",
  "tags": [
    {
      "tag": "title_loan_candidate",
      "confidence": 0.78,
      "model": "v1.2",
      "last_updated": "2026-03-24"
    }
  ]
}
```

#### POST /api/v1/marketing/segment
Assign person to segments.

```json
Request:
{
  "person_id": "person_xyz789"
}

Response:
{
  "person_id": "person_xyz789",
  "segments": ["suburban_middle_class", "family_household"],
  "confidence": 0.87
}
```

#### GET /api/v1/marketing/leads
Query leads by criteria.

```json
Request Query Parameters:
?segment=suburban_middle_class&min_lead_score=0.75&tag=car_loan_candidate&limit=1000

Response:
{
  "total_leads": 45000,
  "returned": 1000,
  "leads": [
    {
      "person_id": "person_xyz789",
      "name": "John Doe",
      "lead_score": 0.82,
      "tags": ["title_loan_candidate"],
      "segments": ["suburban_middle_class"]
    }
  ]
}
```

#### POST /api/v1/marketing/list/build
Build a marketing audience list.

```json
Request:
{
  "list_name": "Title Loan Prospects Q2 2026",
  "criteria": {
    "tags": ["title_loan_candidate"],
    "min_ticket_size": 50000,
    "segments": ["suburban_middle_class"]
  },
  "include_contact": true,
  "exclude_opted_out": true
}

Response:
{
  "list_id": "list_abc123",
  "estimated_size": 45000,
  "status": "building",
  "expires_at": "2026-04-24T10:00:00Z"
}
```

### Admin Endpoints

#### GET /api/v1/admin/health
System health check.

```json
Response:
{
  "status": "healthy",
  "timestamp": "2026-03-24T10:00:00Z",
  "services": {
    "postgres": "healthy",
    "dragonfly": "healthy",
    "temporal": "healthy",
    "qdrant": "healthy"
  },
  "queue_depth": 245,
  "active_searches": 12,
  "active_scrapers": 87
}
```

#### GET /api/v1/admin/scrapers
Scraper status dashboard.

```json
Response:
{
  "total_scrapers": 103,
  "healthy": 101,
  "degraded": 2,
  "failed": 0,
  "scrapers": [
    {
      "name": "spokeo_people_search",
      "status": "healthy",
      "last_run": "2026-03-24T09:55:00Z",
      "success_rate": 0.98,
      "records_collected_today": 45000,
      "errors": 0
    }
  ]
}
```

#### GET /api/v1/admin/metrics
Prometheus metrics (Grafana visualization).

#### GET /api/v1/admin/queue
Job queue status.

```json
Response:
{
  "total_jobs": 5000,
  "queued": 245,
  "running": 87,
  "completed": 4668,
  "failed": 0
}
```

### Compliance Endpoints

#### POST /api/v1/compliance/opt-out
Consumer opt-out request.

```json
Request:
{
  "first_name": "John",
  "last_name": "Doe",
  "dob": "1980-01-15",
  "email": "john@example.com",
  "reason": "gdpr"
}

Response (202 Accepted):
{
  "opt_out_id": "optout_xyz123",
  "status": "processing",
  "estimated_completion": "2026-03-31T00:00:00Z"
}
```

#### GET /api/v1/compliance/access/{person_id}
Consumer data access (GDPR, CCPA).

```json
Response:
{
  "person_id": "person_xyz789",
  "full_profile": {...},
  "data_sources": [...],
  "collection_dates": [...]
}
```

#### POST /api/v1/compliance/deletion
Consumer data deletion.

```json
Request:
{
  "person_id": "person_xyz789",
  "reason": "user_request"
}

Response (202 Accepted):
{
  "deletion_id": "del_xyz123",
  "status": "queued"
}
```

---

## Directory Structure (Target)

```
/lycan
├── /api                           # FastAPI application
│   ├── /routes                    # API endpoint modules
│   │   ├── search.py              # Search endpoints (person, business, phone, email)
│   │   ├── person.py              # Person data endpoints
│   │   ├── business.py            # Business data endpoints
│   │   ├── enrichment.py          # Data enrichment endpoints
│   │   ├── financial.py           # Credit/AML/fraud endpoints
│   │   ├── marketing.py           # Marketing tags/segments endpoints
│   │   ├── admin.py               # Health/metrics/admin endpoints
│   │   ├── compliance.py          # Opt-out/access/deletion endpoints
│   │   └── webhooks.py            # Incoming webhook handlers
│   ├── /middleware                # Authentication, logging, rate limiting
│   │   ├── auth.py                # JWT + API key validation
│   │   ├── rate_limiter.py        # Per-key rate limiting
│   │   ├── logging.py             # Structured request logging
│   │   ├── cors.py                # CORS configuration
│   │   └── request_id.py          # Request tracing
│   ├── /schemas                   # Pydantic models for validation
│   │   ├── search.py
│   │   ├── person.py
│   │   ├── business.py
│   │   ├── financial.py
│   │   └── common.py
│   └── app.py                     # FastAPI app factory & initialization
│
├── /crawlers                      # Data collection infrastructure
│   ├── /core                      # Base crawler classes
│   │   ├── base_crawler.py        # Abstract base for all crawlers
│   │   ├── http_crawler.py        # HTTP-based crawlers
│   │   ├── headless_crawler.py    # Playwright-based crawlers
│   │   ├── errors.py              # Crawler exceptions
│   │   └── rate_limiter.py        # Per-source rate limiting
│   ├── /people_search            # People search site scrapers
│   │   ├── spokeo.py
│   │   ├── whitepages.py
│   │   ├── peoplefinder.py
│   │   └── ...
│   ├── /social_media             # Social platform scrapers
│   │   ├── facebook.py
│   │   ├── linkedin.py
│   │   ├── twitter.py
│   │   ├── instagram.py
│   │   └── ...
│   ├── /public_records           # Government data scrapers
│   │   ├── sos_scraper.py        # Secretary of State
│   │   ├── property_records.py
│   │   ├── court_records.py
│   │   ├── business_licenses.py
│   │   └── ...
│   ├── /financial                # Financial data scrapers
│   │   ├── sec_filings.py
│   │   ├── credit_bureaus.py
│   │   └── ...
│   ├── /business                 # Business intelligence scrapers
│   │   ├── crunchbase.py
│   │   ├── bloomberg.py
│   │   └── ...
│   ├── /sanctions_aml            # Sanctions & AML list scrapers
│   │   ├── ofac_scraper.py
│   │   ├── eu_sanction_scraper.py
│   │   ├── un_scraper.py
│   │   ├── pep_scraper.py
│   │   └── ...
│   ├── /phone_email              # Contact validation
│   │   ├── phone_validator.py
│   │   ├── email_validator.py
│   │   └── ...
│   ├── /property                 # Property records
│   │   ├── zillow.py
│   │   ├── county_assessor.py
│   │   └── ...
│   ├── /monitoring               # Change detection & monitoring
│   │   ├── change_detector.py
│   │   └── alert_generator.py
│   ├── registry.py               # Auto-discovery scraper registry
│   └── health_check.py           # Scraper health monitoring
│
├── /modules                      # Core business logic (strictly modular)
│   ├── /dedup                    # Entity resolution & deduplication
│   │   ├── base.py               # Dedup pipeline interface
│   │   ├── exact_match.py        # Exact matching (100% confidence)
│   │   ├── fuzzy_match.py        # Fuzzy string matching
│   │   ├── graph_dedup.py        # Graph-based dedup
│   │   ├── ml_dedup.py           # ML-based matching (Rust bridge)
│   │   ├── golden_record.py      # Golden record construction
│   │   ├── bloom_filter.py       # Fast existence checks
│   │   └── confidence_scorer.py  # Dedup confidence scoring
│   ├── /enrichment               # Data enrichment pipeline
│   │   ├── pipeline.py           # Enrichment orchestrator
│   │   ├── normalizer.py         # Field normalization
│   │   ├── cross_reference.py    # Cross-source linking
│   │   ├── api_enricher.py       # External API enrichment
│   │   ├── confidence_scorer.py  # Data quality scoring
│   │   └── freshness_manager.py  # Data staleness detection
│   ├── /financial                # Financial intelligence
│   │   ├── alt_credit_score.py   # Alternative credit scoring
│   │   ├── aml_screener.py       # AML/KYC screening
│   │   ├── sanctions_checker.py  # Sanctions list matching
│   │   ├── pep_detector.py       # PEP detection
│   │   ├── fraud_detector.py     # Fraud risk modeling
│   │   └── adverse_media.py      # Adverse media monitoring
│   ├── /marketing                # Marketing intelligence
│   │   ├── consumer_tagger.py    # Consumer tag assignment
│   │   ├── ticket_sizer.py       # CLV estimation
│   │   ├── segment_engine.py     # Behavioral segmentation
│   │   ├── lead_scorer.py        # Lead scoring models
│   │   └── propensity_models.py  # Propensity to respond
│   ├── /search                   # Search orchestration
│   │   ├── orchestrator.py       # Search workflow coordinator
│   │   ├── progress_tracker.py   # SSE progress tracking
│   │   ├── growth_engine.py      # Network expansion search
│   │   └── result_combiner.py    # Multi-source result merging
│   ├── /patterns                 # Pattern detection & ML
│   │   ├── graph_analyzer.py     # Network graph analysis
│   │   ├── anomaly_detector.py   # Anomaly detection
│   │   ├── predictive_model.py   # ML-based predictions
│   │   └── fraud_ring_detector.py
│   └── /compliance               # Legal compliance & regulations
│       ├── opt_out_manager.py    # Opt-out request processing
│       ├── consumer_access.py    # GDPR/CCPA data access
│       ├── fcra_compliance.py    # FCRA compliance mode
│       ├── audit_logger.py       # Compliance audit trail
│       └── validator.py          # Data validation rules
│
├── /shared                       # Shared utilities (no internal imports)
│   ├── /db                       # Database layer
│   │   ├── models.py             # SQLAlchemy ORM models
│   │   ├── connect.py            # Database connection pool
│   │   ├── migrations/           # Alembic migration scripts
│   │   └── queries.py            # Common query utilities
│   ├── /cache                    # Cache layer (Dragonfly)
│   │   ├── client.py             # Dragonfly client wrapper
│   │   ├── keys.py               # Cache key conventions
│   │   └── invalidation.py       # Cache invalidation logic
│   ├── /config                   # Configuration management
│   │   ├── settings.py           # Pydantic settings from env
│   │   ├── features.py           # Feature flags
│   │   └── secrets.py            # Secret management
│   ├── /logging                  # Structured logging
│   │   ├── logger.py             # JSON structured logging
│   │   └── filters.py            # PII filtering
│   ├── /security                 # Auth & encryption
│   │   ├── jwt_handler.py        # JWT token generation/validation
│   │   ├── api_key_handler.py    # API key management
│   │   ├── encryption.py         # Field-level encryption
│   │   └── secrets_manager.py    # Secret retrieval
│   ├── /events                   # Event bus & SSE
│   │   ├── event_bus.py          # Event publisher
│   │   ├── sse_manager.py        # SSE connection manager
│   │   └── event_types.py        # Event schema definitions
│   ├── /http                     # HTTP utilities
│   │   ├── client.py             # Async HTTP client with retries
│   │   ├── retry_policy.py       # Retry logic
│   │   └── circuit_breaker.py    # Circuit breaker pattern
│   └── /utils                    # General utilities
│       ├── phone_normalizer.py
│       ├── email_validator.py
│       ├── string_similarity.py  # Rust bridge for Levenshtein
│       └── ...
│
├── /workflows                    # Temporal.io workflow definitions
│   ├── search_workflow.py        # Person/business search workflow
│   ├── enrichment_workflow.py    # Data enrichment workflow
│   ├── growth_workflow.py        # Network expansion workflow
│   ├── monitoring_workflow.py    # Continuous monitoring workflow
│   └── activities.py             # Workflow activity implementations
│
├── /migrations                   # Alembic database migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── /tests                        # Comprehensive test suite (target >80%)
│   ├── /unit                     # Unit tests
│   │   ├── test_dedup.py
│   │   ├── test_enrichment.py
│   │   ├── test_financial.py
│   │   └── ...
│   ├── /integration              # Integration tests
│   │   ├── test_search_workflow.py
│   │   ├── test_api_endpoints.py
│   │   └── ...
│   ├── /e2e                      # End-to-end tests
│   │   ├── test_full_search.py
│   │   └── ...
│   ├── conftest.py               # Pytest fixtures
│   ├── fixtures/                 # Test data
│   └── mocks.py                  # Mock implementations
│
├── /static                       # Frontend assets
│   ├── /css
│   ├── /js
│   └── /images
│
├── /templates                    # HTML templates (Jinja2)
│   ├── base.html
│   ├── search_results.html
│   └── ...
│
├── /scripts                      # Utility & operational scripts
│   ├── migrate_db.py            # Database migration runner
│   ├── bulk_enrich.py           # Bulk enrichment runner
│   ├── opt_out_processor.py     # Opt-out request processor
│   ├── scraper_health_check.py  # Health check runner
│   └── cleanup.py               # Data cleanup & retention
│
├── /docs                         # Specification documents
│   ├── 01-tech-stack.md         # Technology decisions
│   ├── 02-modular-architecture.md
│   ├── 03-deduplication-verification.md
│   ├── 04-[reserved]
│   ├── 05-data-enrichment-categories.md
│   ├── 06-financial-aml-credit.md
│   ├── 07-patterns-indexing-future.md
│   ├── 08-[reserved]
│   ├── 09-bots-crawlers-catalog.md
│   ├── 10-marketing-tags-scoring.md
│   ├── 11-progress-realtime-ui.md
│   └── 12-ethical-legal-compliance.md
│
├── docker-compose.yml            # Production services
├── docker-compose.dev.yml        # Local development services
├── Dockerfile                    # Application container
├── Makefile                      # Common commands
├── pyproject.toml               # Python project metadata & dependencies
├── setup.py                     # Package setup
├── lycan.py                     # CLI entry point
├── worker.py                    # Background worker entry point
├── wsgi.py                      # WSGI entry point for production
├── README.md                    # Project overview
└── .env.example                 # Example environment variables
```

---

## Build Phases (10 Phases, 24 Weeks to Production)

### Phase 1: Foundation & Security (Week 1-2) ⚠️ CRITICAL PRIORITY
**Goal:** Fix all critical security audit findings. Establish secure foundation.

**Tasks:**
1. Implement JWT + API key authentication on all endpoints
2. Add comprehensive Pydantic input validation to every route
3. Fix Tor circuit reuse vulnerability (rotate circuits)
4. Implement per-IP + per-API-key rate limiting (Dragonfly-backed)
5. Add credential filtering in logs (regex scrubbing)
6. Configure CORS properly (whitelist only safe origins)
7. Add request ID correlation header to all requests
8. Fix growth daemon infinite loop risk (add max iterations)
9. Set up CI/CD pipeline for automated security checks
10. Write security test suite

**Tests to Write:** 20+ security tests (auth, validation, injection prevention)

**Deliverables:**
- All endpoints require auth ✓
- No credentials in logs ✓
- Rate limiting enforced ✓
- Input validation on every route ✓

---

### Phase 2: Core Infrastructure (Week 3-4)
**Goal:** Build reliable backbone for at-scale operation.

**Tasks:**
1. Set up Temporal.io cluster (Docker Compose local, Kubernetes prod)
2. Implement Server-Sent Events (SSE) for progress streaming
3. Implement Redis Streams job queue (replace ad-hoc queuing)
4. Add circuit breaker to all HTTP requests (httpx-based)
5. Implement health check system (readiness + liveness probes)
6. Set up Prometheus metrics collection
7. Set up Grafana dashboards for: queue depth, scraper health, search latency
8. Implement structured JSON logging (remove console logs)
9. Build request tracing (Jaeger or OpenTelemetry)
10. Add database connection pooling validation

**Tests:** 15+ infrastructure tests

**Deliverables:**
- Temporal running locally and in production config ✓
- SSE streaming works end-to-end ✓
- Circuit breakers prevent cascading failures ✓
- Prometheus + Grafana dashboards live ✓

---

### Phase 3: Dedup & Entity Resolution (Week 5-6)
**Goal:** Build 4-pass dedup pipeline for zero-duplicate guarantee.

**Tasks:**
1. Implement exact match pass (hash on normalized fields)
2. Implement fuzzy match pass (Levenshtein distance, Jaro-Winkler)
3. Implement graph-based dedup (shared phones, addresses, emails)
4. Implement ML-based dedup (Rust bridge for string similarity at scale)
5. Build golden record construction (merge 4+ records)
6. Build Bloom filters for fast existence checks
7. Implement Apache AGE graph for relationship storage
8. Add confidence scoring to dedup matches
9. Add data freshness tracking
10. Build dedup audit trail

**Rust Components to Build:**
```rust
// string_similarity.rs — Fast string matching
pub fn levenshtein_distance(a: &str, b: &str) -> usize { ... }
pub fn jaro_winkler_similarity(a: &str, b: &str) -> f64 { ... }
pub fn phonetic_hash(s: &str) -> String { ... }  // Metaphone or Soundex
pub fn bloom_filter_check(key: &[u8], filter: &[u8]) -> bool { ... }
```

**Tests:** 30+ dedup tests (exact, fuzzy, graph, ML)

**Deliverables:**
- 4-pass dedup working end-to-end ✓
- Zero duplicate records in database ✓
- Golden records properly merged ✓
- Confidence scores on all matches ✓

---

### Phase 4: Scraper Expansion (Week 7-10)
**Goal:** Add 50+ new data sources. Establish reliable data pipeline.

**Tasks:**
1. Refactor all existing scrapers to use BaseCrawler interface
2. Add 50+ new scrapers from catalog (09-bots-crawlers-catalog.md):
   - People search: Spokeo, WhitePages, PeopleFinder, TruthFinder, Instant Checkmate
   - Social: Facebook, LinkedIn, Twitter, Instagram, TikTok
   - Public records: SOS, property assessor, court records, business licenses
   - Financial: SEC EDGAR, credit bureaus, financial filings
   - Business: Crunchbase, Bloomberg, Yahoo Finance
   - Sanctions: OFAC, EU, UN, UK sanctions lists
   - Phone/email: Phone lookup APIs, email validation services
3. Implement scraper registry with auto-discovery
4. Add per-scraper rate limiting (respect site ToS)
5. Add per-scraper circuit breakers
6. Build scraper health dashboard
7. Implement continuous data monitoring (change detection)
8. Add scraper failure alerts
9. Write scraper tests (mock HTTP responses)
10. Document each scraper's ToS and legal status

**Scraper Priority Order:**
1. People search (Spokeo, WhitePages, PeopleFinder)
2. Public records (SOS, property, court)
3. Social media (LinkedIn, Facebook)
4. Sanctions (OFAC, EU)
5. Financial (SEC, credit bureaus)
6. Business (Crunchbase)
7. Phone/email validators
8. Property (Zillow, county assessor)

**Tests:** 50+ scraper tests (one per scraper, mock responses)

**Deliverables:**
- 50+ scrapers active ✓
- Auto-discovery working ✓
- Health dashboard shows status ✓
- Rate limiting respected ✓

---

### Phase 5: Financial & AML Intelligence (Week 11-13)
**Goal:** Build financial risk assessment capability.

**Tasks:**
1. Build alternative credit scoring model:
   - Features: payment behavior, debt-to-income, credit utilization
   - Train on anonymized dataset
   - Version model (v1.0, v1.1, etc.)
   - Calculate percentile ranking

2. Implement AML/KYC screening:
   - OFAC screening (download list weekly)
   - EU sanctions (download weekly)
   - UN sanctions (download weekly)
   - UK sanctions (download weekly)

3. Build PEP detection:
   - Scrape PEP databases
   - Match against persons database
   - Flag high-risk profiles

4. Build adverse media monitoring:
   - News search APIs
   - Negative keyword flagging
   - Risk scoring

5. Build fraud detection model:
   - Velocity checks (new account, activity)
   - Address consistency
   - Device fingerprinting signals
   - Fraud ring detection

6. Add financial data aggregation:
   - Bank account data (where available)
   - Tax filing data
   - Investment activity

**ML Models to Train:**
- Credit score model (gradient boosting)
- Fraud detector (random forest)
- PEP classifier (simple rules + ML)

**Tests:** 20+ financial tests

**Deliverables:**
- Credit scores calculated ✓
- AML screening working ✓
- PEP detection active ✓
- Fraud models scoring ✓

---

### Phase 6: Marketing Intelligence (Week 14-15)
**Goal:** Add consumer targeting & lead scoring capability.

**Tasks:**
1. Build consumer tagging engine:
   - Title loan candidates (vehicle + debt indicators)
   - Gamblers (gaming site activity)
   - Home improvement interest (property records)
   - Travel enthusiasts (booking site activity)
   - Small business owners (employment + business records)
   - Parents (school enrollment records)

2. Implement ticket size estimation:
   - Income estimation from data
   - Asset estimation
   - Debt load assessment
   - Propensity modeling
   - Calculate CLV (Customer Lifetime Value)

3. Build segment engine:
   - Behavioral segmentation (online activity)
   - Demographic segmentation (age, income, family)
   - Geographic segmentation
   - Psychographic segmentation

4. Implement lead scoring:
   - Propensity to respond
   - Likelihood to convert
   - Revenue potential

5. Build marketing list generation:
   - Filter by tags, segments, scores
   - Export to CSV for campaigns
   - Respect opt-outs and compliance rules

**Models to Train:**
- Tag assignment (logistic regression per tag)
- Ticket size estimator (gradient boosting)
- Lead score model (ensemble)

**Tests:** 15+ marketing tests

**Deliverables:**
- Consumer tags assigned ✓
- Ticket sizes calculated ✓
- Segments assigned ✓
- Lead scoring working ✓

---

### Phase 7: Search & UI Enhancements (Week 16-17)
**Goal:** Make search fast, visual, and interactive.

**Tasks:**
1. Implement progress bars on all search operations:
   - Show % complete
   - Show sources being checked
   - Show results found so far

2. Build expanding search (growth engine):
   - Find related people via shared phone/email/address
   - Network expansion
   - Family unit detection
   - Business associate detection

3. Add editable search parameters:
   - Adjust search during flight
   - Add/remove criteria
   - Expand/narrow scope

4. Build network visualization:
   - Graph visualization (relationships)
   - Interactive node/edge inspection
   - Cluster detection visualization

5. Add map-based results view:
   - Plot addresses on map
   - Cluster analysis
   - Geographic patterns

6. Implement search history:
   - Saved searches
   - Recent searches
   - Search templates

7. Add bulk search capability:
   - Upload CSV of people to search
   - Batch processing
   - Export results

**Frontend Framework:** React or Vue (choose one)

**Tests:** 20+ UI/UX tests (including UI component tests)

**Deliverables:**
- Search progress visible ✓
- Growth expansion working ✓
- Network visualization interactive ✓
- Search history persistent ✓

---

### Phase 8: Pattern Detection & ML (Week 18-20)
**Goal:** Detect patterns, fraud rings, anomalies.

**Tasks:**
1. Implement graph-based pattern detection:
   - Community detection (shared resources)
   - Hub detection (highly connected nodes)
   - Path finding (connection discovery)

2. Build anomaly detection:
   - Isolation forests on numeric data
   - Density-based anomalies
   - Time-series anomalies

3. Train predictive models:
   - Risk prediction
   - Behavior prediction
   - Churn prediction

4. Build real-time alerting:
   - Alert on high-risk profiles
   - Alert on new fraud patterns
   - Alert on sanctions hits

5. Implement fraud ring detection:
   - Identify networks of coordinated fraud
   - Track cross-linked identities
   - Risk scoring for rings

6. Build recommendation engine:
   - Recommend similar profiles
   - Recommend related records

**Advanced ML:**
- Graph neural networks for relationship prediction
- Time-series forecasting
- Anomaly detection models

**Tests:** 15+ ML tests (with sample data)

**Deliverables:**
- Pattern detection working ✓
- Anomaly alerts firing ✓
- Fraud ring detection active ✓
- ML models scoring ✓

---

### Phase 9: Compliance & Hardening (Week 21-22)
**Goal:** Achieve compliance, audit-readiness, production hardening.

**Tasks:**
1. Build opt-out system:
   - Consumer opt-out requests
   - GDPR right to erasure
   - CCPA do-not-sell
   - CPA delete requests
   - Automatic enforcement

2. Implement consumer access portal:
   - GDPR/CCPA data access rights
   - Download data in portable format
   - Transparency about sources

3. Add FCRA compliance mode:
   - Disclaimer on person profiles
   - Permissible purpose checks
   - Access logging
   - Data source attribution

4. Build audit logging system:
   - Who accessed what data, when
   - Immutable audit trail
   - Compliance reporting

5. Implement data retention policies:
   - Auto-delete stale data
   - Archive old records
   - Retention schedule per data type

6. Add SOC 2 controls documentation:
   - Access controls
   - Data security
   - Audit trail
   - Incident response

7. Implement field-level encryption (optional):
   - SSN, DOB encryption at rest
   - Encryption keys in AWS KMS

8. Add data masking for display:
   - Show SSN last 4 only
   - Show full phone only to authorized users

**Tests:** 10+ compliance tests

**Deliverables:**
- Opt-out system working ✓
- Consumer access portal live ✓
- Audit logging immutable ✓
- SOC 2 documentation complete ✓

---

### Phase 10: Testing & Production (Week 23-24)
**Goal:** Comprehensive testing, optimization, production readiness.

**Tasks:**
1. Write comprehensive test suite (target >80% coverage):
   - 100+ unit tests
   - 50+ integration tests
   - 20+ e2e tests
   - All scrapers tested with mocks

2. Load testing:
   - 100 concurrent searches
   - 1000 concurrent searches
   - Monitor latency, memory, CPU
   - Optimize bottlenecks

3. Security audit:
   - Penetration testing
   - OWASP top 10 check
   - SSL/TLS validation
   - API security review

4. Performance optimization:
   - Database query optimization
   - Cache warming
   - Async optimization
   - Memory profiling

5. Documentation:
   - API documentation (OpenAPI/Swagger)
   - Architecture documentation
   - Runbooks for operations
   - Troubleshooting guides

6. Production deployment:
   - Kubernetes configuration
   - Secrets management (Vault)
   - Monitoring + alerting setup
   - Backup/recovery procedures

7. Disaster recovery:
   - Backup strategy (daily backups)
   - Recovery testing
   - RTO/RPO definition

8. Go-live checklist:
   - Security review sign-off
   - Performance sign-off
   - Compliance sign-off
   - Operations readiness

**Tests:** 170+ total tests (100+50+20)

**Deliverables:**
- All tests passing ✓
- Load test shows 1000 concurrent searches ✓
- Security audit complete ✓
- Production deployment ready ✓

---

## Critical Rules for Building

### 1. Modularity Rules (Non-Negotiable)

Every module MUST follow these rules:

```python
# ✓ Good: Clean, testable interface
from abc import ABC, abstractmethod

class DeduplicationEngine(ABC):
    @abstractmethod
    def match(self, record1: Dict, record2: Dict) -> float:
        """Return match confidence 0.0-1.0"""
        pass

class ExactMatchDeduplicator(DeduplicationEngine):
    def match(self, record1, record2) -> float:
        # Implementation
        pass

# ✗ Bad: Internal imports
from modules.dedup.internals import _private_function  # DON'T DO THIS
```

**Modularity Checklist:**
- [ ] Module has a clear interface (ABC or Protocol)
- [ ] Module imports only from `shared/` or other module interfaces
- [ ] Module can be tested without other modules
- [ ] Module has no hardcoded configuration
- [ ] Module never crashes the system (handles errors gracefully)
- [ ] Adding/removing module requires zero changes elsewhere

### 2. Performance Rules

**All I/O must be async:**
```python
# ✓ Good: Async all the way
async def search_person(criteria):
    results = await asyncio.gather(
        get_from_postgres(),
        get_from_cache(),
        get_from_qdrant()
    )
    return results

# ✗ Bad: Blocking call
import requests
response = requests.get(url)  # BLOCKS EVENT LOOP
```

**Connection pooling everywhere:**
```python
# ✓ Good: Pool connections
engine = create_async_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=10
)

# ✗ Bad: New connection per request
conn = psycopg2.connect(database_url)
```

**Cache aggressively:**
```python
# ✓ Good: Cache for 24 hours
await cache.setex(f"person:{person_id}:full", 86400, json.dumps(record))

# ✗ Bad: No caching
def get_person(person_id):
    return db.query(Person).filter_by(id=person_id).first()  # DB hit every time
```

### 3. Security Rules (Enforce Everywhere)

**All endpoints require auth:**
```python
# ✓ Good: Auth enforced
@app.get("/api/v1/person/{person_id}")
async def get_person(person_id: str, user=Depends(verify_auth)):
    return {...}

# ✗ Bad: No auth
@app.get("/api/person/{person_id}")
async def get_person(person_id: str):
    return {...}
```

**All input validated with Pydantic:**
```python
# ✓ Good: Strict validation
class PersonSearchRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    phone: Optional[str] = Field(None, regex=r'^\+?1?\d{10}$')
    email: Optional[EmailStr] = None

# ✗ Bad: No validation
@app.post("/search")
async def search(data: dict):
    first_name = data.get("first_name")  # Could be anything
    return search_db(first_name)
```

**All database queries are parameterized:**
```python
# ✓ Good: Parameterized (SQLAlchemy handles this)
query = persons.select().where(persons.c.id == person_id)
result = await db.execute(query, {"person_id": person_id})

# ✗ Bad: String interpolation (SQL injection!)
query = f"SELECT * FROM persons WHERE id = '{person_id}'"
```

**Secrets never in code:**
```python
# ✓ Good: From environment
POSTGRES_URL = os.getenv("DATABASE_URL")
API_KEY = os.getenv("API_KEY")

# ✗ Bad: Hardcoded
DATABASE_URL = "postgresql://user:password@localhost/lycan"
```

**Credentials filtered from logs:**
```python
# ✓ Good: Scrubbed
def log_request(request):
    body = scrub_sensitive_data(request.body)
    logger.info(f"Request: {body}")

# ✗ Bad: Leaking credentials
logger.info(f"Request: {request.body}")  # Shows SSN, API keys, etc.
```

### 4. Data Quality Rules (Absolute)

**Every data point must have:**
1. Source attribution (which scraper/API collected it)
2. Confidence score (0.0-1.0 trust level)
3. Timestamp (when collected)
4. Freshness indicator (how old is it)

```python
class DataPoint(BaseModel):
    value: str
    source: str  # "spokeo", "linkedin", etc.
    confidence: float  # 0.0-1.0
    collected_at: datetime
    freshness_days: int  # Days since collection

    @validator('confidence')
    def confidence_valid(cls, v):
        assert 0.0 <= v <= 1.0
        return v
```

**Duplicates are never acceptable:**
```python
# ✓ Good: Check for duplicates before insert
before_insert_count = await db.count(persons)
await dedup_engine.run(new_records)
after_insert_count = await db.count(persons)
assert after_insert_count == before_insert_count + unique_records
```

**Stale data must be flagged:**
```python
# ✓ Good: Mark stale data
def is_stale(collected_at: datetime, max_age_days: int = 90) -> bool:
    age = (datetime.now() - collected_at).days
    return age > max_age_days

# Then in queries:
stale_records = await db.query(persons).filter(
    persons.c.stale == True
).all()
```

---

## Technology Decisions Reference

For detailed tech stack decisions, read **doc 01-tech-stack.md**.

**TL;DR:**
- **Language:** Python 3.12+ (team knows it, ML ecosystem is critical)
- **API:** FastAPI (async-native, validation, OpenAPI)
- **Database:** PostgreSQL 16 (JSONB, full-text, graph extensions)
- **Cache:** Dragonfly (Redis alternative, 25x faster)
- **Workflows:** Temporal.io (distributed, resilient)
- **Scraping:** Playwright (headless browser), httpx (async HTTP)
- **ML:** scikit-learn, XGBoost, sentence-transformers
- **Search:** MeiliSearch (full-text), Qdrant (vector)
- **Monitoring:** Prometheus + Grafana

---

## Summary: Building Lycan

This specification defines a **complete, production-ready data broker platform**.

**Start here, read docs 01-12 for details, then build module by module following the 10-phase plan.**

Every decision in this spec has trade-offs documented in the detailed specs. Follow the rules. Test relentlessly. Ship confidently.

**Go build something great.**
