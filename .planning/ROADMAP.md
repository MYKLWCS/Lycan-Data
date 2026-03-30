# Roadmap: Lycan-Data

**Created:** 2026-03-30
**Phases:** 5
**Requirements:** 24 v1

## Phase 1: Data Access & Cloudflare Bypass
**Goal:** Make people-search crawlers return actual data
**Requirements:** DATA-01, DATA-02, DATA-03, DATA-04
**Plans:** 4 plans

Plans:
- [ ] 01-data-access-01-PLAN.md — Infrastructure: Byparr replacement, curl_cffi upgrade, Tor removal, CF cookie cache
- [ ] 01-data-access-02-PLAN.md — New crawlers: IDCrawl and FreePeopleSearch for phone/address discovery
- [ ] 01-data-access-03-PLAN.md — Profile photos: GitHub avatar extraction, social crawler photo audit
- [ ] 01-data-access-04-PLAN.md — Testing and validation: new test files, full regression, live smoke test

**Success Criteria:**
1. WhitePages/FastPeopleSearch/TruePeopleSearch return person cards (not Cloudflare blocks)
2. Phone numbers extracted from people-search results and stored as Identifiers
3. Addresses extracted and stored in Address table
4. Profile photos captured from crawlers that find them

## Phase 2: OmniGraph Multi-Candidate Search
**Goal:** Handle multiple people with the same name as separate candidates
**Requirements:** IDEN-01, IDEN-02, IDEN-03, IDEN-04

**Success Criteria:**
1. Name searches return multiple candidate cards (not merged into one person)
2. Each candidate has unique person_id with their own data
3. User can select a candidate for deep investigation
4. Deep search runs all crawlers using the selected person's identifiers
5. Cross-person collision detection merges true duplicates automatically

## Phase 3: Enrichment Pipeline Hardening
**Goal:** Enrichment runs correctly once, produces accurate scores
**Requirements:** ENRI-01, ENRI-02, ENRI-03, ENRI-04

**Success Criteria:**
1. Enrichment runs ONCE after all crawlers complete (not 50+ times)
2. Score reflects actual data (media, corporate, identity, social, property)
3. Wikidata DOB and social handles stored on Person
4. Family tree built automatically when relationships exist

## Phase 4: Daemon Lifecycle & Reliability
**Goal:** Graceful shutdown, no hung processes, no silent failures
**Requirements:** RELI-01, RELI-02, RELI-03, RELI-04

**Success Criteria:**
1. SIGTERM cleanly stops all 12+ daemons within 30 seconds
2. No hung crawler blocks dispatcher slots (120s timeout)
3. EventBus connectivity verified before job dispatch
4. Failed jobs go to dead letter queue, not silently dropped

## Phase 5: Code Quality & Performance
**Goal:** Clean code, fast queries, correct exports
**Requirements:** QUAL-01, QUAL-02, QUAL-03, QUAL-04, QUAL-05, PERF-01, PERF-02, PERF-03

**Success Criteria:**
1. JSON/CSV export endpoints work correctly
2. CLI imports all 181 crawler subpackages
3. pg_trgm GIN index makes name search sub-100ms
4. No silent exception swallowing in critical paths
5. LIKE wildcards escaped in all user input

---
*Roadmap created: 2026-03-30*
