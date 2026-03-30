# Requirements: Lycan-Data

**Defined:** 2026-03-30
**Core Value:** Find and connect everything about a person from any starting identifier

## v1 Requirements

### Data Access

- [ ] **DATA-01**: Crawlers bypass Cloudflare Enterprise on people-search sites using free methods
- [ ] **DATA-02**: Phone numbers discovered from name searches via working data sources
- [ ] **DATA-03**: Addresses discovered from name searches via working data sources
- [ ] **DATA-04**: Profile photos captured from all social crawlers that find them

### Identity Resolution

- [ ] **IDEN-01**: All discovered identifiers (email, phone, username) stored as Identifier rows during ingestion
- [ ] **IDEN-02**: Cross-person collision detection merges duplicate persons automatically
- [ ] **IDEN-03**: Merge executor handles all 50+ person-linked tables without crashing
- [ ] **IDEN-04**: Search by any identifier type finds existing person within 5 seconds

### Enrichment

- [ ] **ENRI-01**: Enrichment runs once after all crawlers complete (not after each crawler)
- [ ] **ENRI-02**: Enrichment score accurately reflects data found (9 components)
- [ ] **ENRI-03**: Wikidata DOB, social handles, and family QIDs extracted and stored
- [ ] **ENRI-04**: Genealogy/family tree built automatically during enrichment pipeline

### Reliability

- [ ] **RELI-01**: All daemon enrichers have stop() method and _running flag for graceful shutdown
- [ ] **RELI-02**: All daemons registered in worker.py shutdown handler
- [ ] **RELI-03**: Crawler execution timeout prevents hung crawlers (120s configurable)
- [ ] **RELI-04**: Event bus connectivity checked before dispatching jobs

### Code Quality

- [ ] **QUAL-01**: JSON/CSV export endpoints use correct model attribute names
- [ ] **QUAL-02**: CLI lycan.py imports all crawler subpackages recursively
- [ ] **QUAL-03**: Aggregator model imports are required (fail fast, not silent None)
- [ ] **QUAL-04**: LIKE wildcards escaped in all user search input
- [ ] **QUAL-05**: No silent exception swallowing in critical pipeline paths

### Performance

- [ ] **PERF-01**: pg_trgm GIN index on persons.full_name for ILIKE performance
- [ ] **PERF-02**: Person detail endpoint uses eager loading (selectinload)
- [ ] **PERF-03**: DB connection pool configurable (50/100 default)

## v2 Requirements

### Data Access (Paid)

- **DATA-05**: Residential proxy integration for Cloudflare bypass (requires paid service)
- **DATA-06**: HIBP breach checking (requires $3.50/mo API key)

### Architecture

- **ARCH-01**: Split aggregator.py (1842 lines) into per-category sub-aggregators
- **ARCH-02**: Split deduplication.py (1156 lines) into separate modules
- **ARCH-03**: Consolidate _import_all_crawlers() into single shared function

### Observability

- **OBSV-01**: Dead letter queue for failed jobs
- **OBSV-02**: Metrics for queue depths and crawler success rates
- **OBSV-03**: Health endpoint includes Tor, FlareSolverr, and patchright status

## Out of Scope

| Feature | Reason |
|---------|--------|
| Paid API providers (Pipl, FullContact) | Budget constraint |
| Mobile app | Web-first, single-page SPA sufficient |
| Real-time monitoring | Batch intelligence platform |
| Multi-tenant SaaS | Single-organization deployment |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DATA-01 | Phase 1 | Pending |
| DATA-02 | Phase 1 | Pending |
| DATA-03 | Phase 1 | Pending |
| DATA-04 | Phase 1 | Pending |
| IDEN-01 | Phase 2 | Pending |
| IDEN-02 | Phase 2 | Pending |
| IDEN-03 | Phase 2 | Pending |
| IDEN-04 | Phase 2 | Pending |
| ENRI-01 | Phase 3 | Pending |
| ENRI-02 | Phase 3 | Pending |
| ENRI-03 | Phase 3 | Pending |
| ENRI-04 | Phase 3 | Pending |
| RELI-01 | Phase 4 | Pending |
| RELI-02 | Phase 4 | Pending |
| RELI-03 | Phase 4 | Pending |
| RELI-04 | Phase 4 | Pending |
| QUAL-01 | Phase 5 | Pending |
| QUAL-02 | Phase 5 | Pending |
| QUAL-03 | Phase 5 | Pending |
| QUAL-04 | Phase 5 | Pending |
| QUAL-05 | Phase 5 | Pending |
| PERF-01 | Phase 5 | Pending |
| PERF-02 | Phase 5 | Pending |
| PERF-03 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 24 total
- Mapped to phases: 24
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-30*
*Last updated: 2026-03-30 after GSD initialization*
