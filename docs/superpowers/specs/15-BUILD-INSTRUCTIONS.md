# LYCAN BUILD INSTRUCTIONS — Exact Steps for Claude Code

## Setup (Do This First)

### 1. Copy Docs Into Your Repo
```bash
cd /path/to/osnit
mkdir -p docs/specs
# Copy all 15 .md files from your OSINT folder into docs/specs/
cp /path/to/OSINT/*.md docs/specs/
# Also copy these two:
cp Lycan_Definitive_Blueprint_v3.docx docs/specs/
cp LICENSING_NOTES.md docs/specs/
```

### 2. Add a CLAUDE.md to your repo root
Create `osnit/CLAUDE.md` with this content — Claude Code reads this automatically:
```markdown
# Lycan OSINT Platform — Build Context

## What This Is
Recursive people-intelligence OSINT + data broker platform for Rand Financial Holdings.
Government/enterprise grade. 100% free open-source tools.

## Critical Rules
- NO AGPL licensed tools (banned for government). NO BSL licensed tools.
- Only MIT, Apache 2.0, BSD, MPL 2.0, GPL-2/3, LGPL-3 (dynamic link only).
- Playwright + playwright-stealth (NOT Nodriver). Typesense (NOT MeiliSearch).
- ALL scrapers must extend BaseCrawler interface (see docs/specs/09-bots-crawlers-catalog.md).
- ALL scrapers must run async parallel with asyncio.gather(), never sequential.
- Every scraper needs: circuit breaker, retry with backoff, error handling, health check.
- Every search must emit SSE progress events.
- Zero duplicates — bloom filter + 4-pass entity resolution.

## Stack
- Python 3.12+ (Rust via PyO3 for hot paths in future)
- PostgreSQL 16 + Apache AGE (graph)
- Microsoft Garnet (Redis-compatible cache)
- Typesense (instant search)
- Qdrant (vector embeddings)
- Dramatiq + Apache Pulsar (task queue)
- Playwright + playwright-stealth (browser automation)
- FastAPI (API server)
- SSE for progress, WebSocket optional

## Spec Docs
All specs are in docs/specs/. Read 00-MASTER-SPEC.md first.
The audit of current bugs is in docs/specs/14-deep-code-audit.md.
```

### 3. Git Commit the Docs
```bash
git add docs/ CLAUDE.md
git commit -m "Add complete spec library and CLAUDE.md for build"
git push origin master
```

---

## Phase-by-Phase Build Plan

---

## PHASE 1: Fix What's Broken
**Model: Opus** | **Thinking: ON** | **Reasoning: High**

Why Opus: This phase requires understanding the full codebase, tracing bugs through multiple files, and making architectural judgment calls about what to fix vs rewrite.

### Prompt to paste into Claude Code:
```
Read docs/specs/14-deep-code-audit.md carefully. This is an audit of the current codebase
with every bug documented.

Fix these critical bugs in priority order:

1. API Authentication — add API key auth middleware to all endpoints.
   See the audit for details.

2. Make all scrapers async parallel — currently they run sequentially
   which means one slow/failed scraper blocks everything. Refactor to
   use asyncio.gather() with semaphore for concurrency control.

3. Add circuit breakers to every scraper — after 5 consecutive failures,
   skip that scraper for 60 seconds. See docs/specs/09-bots-crawlers-catalog.md
   for the BaseCrawler pattern.

4. Add retry logic with exponential backoff + jitter to every scraper.

5. Fix silent failures — every scraper error must be logged with
   structured logging (source name, error type, query, timestamp).

6. Fix the growth daemon infinite loop risk documented in the audit.

7. Add input validation on all search endpoints.

Run tests after each fix. Do NOT add new features yet.
```

### Expected time: 2-4 hours
### When done: Run `make test` and verify all tests pass

---

## PHASE 2: Modular Architecture Refactor
**Model: Opus** | **Thinking: ON** | **Reasoning: High**

Why Opus: This is the architectural foundation — wrong decisions here cascade through everything. Opus is better at system design.

### Prompt:
```
Read docs/specs/02-modular-architecture.md and docs/specs/00-MASTER-SPEC.md.

Refactor the codebase to match this modular architecture:

1. Create the BaseCrawler abstract class in crawlers/core/base_crawler.py
   exactly as specified in docs/specs/09-bots-crawlers-catalog.md.
   ALL scrapers must extend this.

2. Refactor every existing scraper to extend BaseCrawler with:
   - name, category, rate_limit, source_reliability properties
   - crawl() method returning List[CrawlerResult]
   - health_check() method
   - safe_crawl() method with circuit breaker built in

3. Create the ScraperOrchestrator that runs all scrapers via
   asyncio.gather() and streams results as they arrive.

4. Create the standardized CrawlerResult Pydantic model that ALL
   scrapers return (source_name, source_url, source_reliability,
   category, entity_type, raw_data, normalized_data, confidence_score,
   data_hash, collected_at, metadata).

5. Create a scraper registry (CRAWLER_REGISTRY dict) where new scrapers
   are registered. Adding a new scraper should require zero changes
   to existing code.

6. Ensure the folder structure matches:
   crawlers/core/, crawlers/people/, crawlers/social_media/,
   crawlers/public_records/, crawlers/financial/, crawlers/business/,
   crawlers/dark_web/, crawlers/phone_email/, crawlers/property/,
   crawlers/sanctions_aml/, crawlers/news_media/, crawlers/cyber/,
   crawlers/monitoring/

Run tests after refactor. All existing functionality must still work.
```

### Expected time: 3-5 hours

---

## PHASE 3: SSE Progress Bars + Real-Time UI
**Model: Sonnet** | **Thinking: ON** | **Reasoning: Medium**

Why Sonnet: This is implementation-heavy — lots of code to write, clear spec to follow. Sonnet is faster and the patterns are well-defined.

### Prompt:
```
Read docs/specs/11-progress-realtime-ui.md.

Implement the real-time progress system:

1. Create SSE endpoint: GET /api/v1/search/{search_id}/progress
   - Streams ProgressEvent objects as Server-Sent Events
   - Events: scraper_queued, scraper_running, scraper_done,
     scraper_failed, dedup_running, enrichment_running, search_complete

2. Create ProgressEvent Pydantic model with: search_id, event_type,
   scraper_name, progress_pct (0-100), results_found, total_scrapers,
   completed_scrapers, failed_scrapers, current_phase,
   estimated_seconds_remaining, partial_results

3. Progress calculation:
   - Phase 1 Collection (0-60%): completed_scrapers / total_scrapers
   - Phase 2 Dedup (60-75%): records processed / total
   - Phase 3 Enrichment (75-95%): enrichment tasks done / total
   - Phase 4 Finalization (95-100%): scoring + indexing

4. Use Redis pub/sub to publish progress from workers to the SSE endpoint.

5. Update the frontend to show:
   - Main progress bar with percentage
   - Phase indicator
   - Scraper status grid (green/yellow/red/gray)
   - Live result count
   - Results appearing as they arrive (don't wait for completion)

6. Results must stream to the UI as each scraper completes,
   not wait for all scrapers to finish.
```

### Expected time: 2-3 hours

---

## PHASE 4: Implement Missing Scrapers (Batch 1 — Top 20)
**Model: Sonnet** | **Thinking: ON** | **Reasoning: Medium**

Why Sonnet: Pure implementation work following the BaseCrawler pattern. Fast and repetitive.

### Prompt:
```
Read docs/specs/09-bots-crawlers-catalog.md.

Implement these 20 highest-priority scrapers. Each MUST extend BaseCrawler,
have proper error handling, and return CrawlerResult objects.

People Search (implement all 5):
1. TruePeopleSearch — browser scraper, returns name/address/phone/email/relatives
2. FastPeopleSearch — browser scraper, returns name/address/phone/age
3. WhitePages — browser+CF bypass, returns name/address/phone
4. ThatsThem — browser scraper, returns name/address/phone/email/IP
5. PeekYou — browser scraper, returns social profiles/web presence

Social Media (implement all 7):
6. Sherlock — subprocess call, username across 400+ sites
7. Maigret — subprocess call, username across 2500+ sites
8. Instaloader — Instagram profile/posts/followers
9. snscrape — Twitter/X tweets/profile
10. Reddit PRAW — post history/comments/karma
11. GitHub — profile/repos/email from commits (GitHub API, free)
12. Holehe — email to registered accounts check

Public Records (implement all 4):
13. SEC EDGAR — corporate filings/insider trades (free API)
14. FEC — campaign contributions (free API)
15. FBI Most Wanted — wanted persons (free API)
16. NSOPW — sex offender registry (free)

Financial (implement all 4):
17. OFAC SDN — US sanctions list (free XML download)
18. OpenSanctions — unified sanctions/PEP (free API)
19. ProPublica Nonprofit — IRS 990 data (free API)
20. FDIC BankFind — bank data (free API)

Register all in CRAWLER_REGISTRY. Write a test for each.
Use the anti-detection stack (playwright-stealth, cloudscraper, curl_cffi)
for browser scrapers. Use aiohttp for API scrapers.
```

### Expected time: 4-6 hours

---

## PHASE 5: Implement Missing Scrapers (Batch 2 — Next 20)
**Model: Sonnet** | **Thinking: ON** | **Reasoning: Medium**

### Prompt:
```
Read docs/specs/09-bots-crawlers-catalog.md.

Implement scrapers 21-40:

Social Media continued:
21. TikTok — TikTok-Api, profile/videos
22. YouTube — YouTube Data API, channel/videos
23. Telegram — Telethon, public channels
24. GHunt — Google account OSINT (isolated subprocess, AGPL)
25. LinkedIn public — browser scraper, public profiles

Phone & Email:
26. PhoneInfoga — phone OSINT tool (subprocess)
27. EmailRep — email reputation (free API)
28. MX/SMTP validator — email deliverability check
29. Disposable email checker — detect throwaway domains
30. Truecaller public — caller ID lookup

Public Records continued:
31. USPTO Patents — patent search (free API)
32. USPTO Trademarks — trademark search (free API)
33. USASpending — government contracts (free API)
34. OSHA — workplace violations (free API)
35. EPA — environmental violations (free API)

Cyber Intelligence:
36. Shodan free tier — internet device search
37. WHOIS lookup — domain registration
38. Certificate Transparency (crt.sh) — SSL cert search
39. HIBP — breach data (free API)
40. VirusTotal free — malware/URL scanning

Same rules: extend BaseCrawler, CrawlerResult output, tests,
register in CRAWLER_REGISTRY.
```

### Expected time: 4-6 hours

---

## PHASE 6: Entity Resolution & Dedup
**Model: Opus** | **Thinking: ON** | **Reasoning: High**

Why Opus: Entity resolution is algorithmically complex — fuzzy matching, ML models, graph-based dedup. Needs strong reasoning.

### Prompt:
```
Read docs/specs/03-deduplication-verification.md.

Implement the 4-pass entity resolution pipeline:

1. Pass 1 — Exact Match: Hash-based dedup using bloom filter in Garnet/Redis.
   Composite keys: (normalized_name + DOB) or (email) or (phone).

2. Pass 2 — Fuzzy Match: Jaro-Winkler for names (threshold 0.92),
   Levenshtein for addresses. Use blocking strategy to reduce comparisons.

3. Pass 3 — Graph-Based: Connected component analysis. If A matches B
   and B matches C, cluster A-B-C. Use Splink for probabilistic matching.

4. Pass 4 — ML-Based: Train on labeled pairs if available, otherwise
   use rule-based scoring as fallback.

5. Golden Record Construction: When duplicates found, merge into single
   record. Source priority: government > commercial > social > web scrape.
   Field-level merge rules. Full provenance tracking.

6. Verification Framework: 5 levels (Unverified → Format Valid →
   Cross-Referenced → Confirmed → Certified). Implement verification
   for phone (carrier lookup), email (MX/SMTP), address (geocoding).

7. Confidence scoring: base score from source reliability +
   cross-reference bonus + freshness decay + conflict penalty.

Integrate into the ingestion pipeline so all incoming data passes
through dedup before storage.
```

### Expected time: 4-6 hours

---

## PHASE 7: Knowledge Graph + Expanding Search
**Model: Opus** | **Thinking: ON** | **Reasoning: High**

Why Opus: Graph modeling and recursive expansion algorithms need strong architectural reasoning.

### Prompt:
```
Read docs/specs/13-knowledge-graph-company-intel.md.

1. Set up Apache AGE on PostgreSQL. Create the osint_graph with
   node types: Person, Company, Address, Phone, Email, Property,
   Vehicle, Court_Case, Social_Profile, Domain, Crypto_Wallet.

2. Edge types: OFFICER_OF, DIRECTOR_OF, OWNS, RELATIVE_OF,
   ASSOCIATE_OF, LIVES_AT, LOCATED_AT, HAS_PHONE, HAS_EMAIL, etc.

3. KnowledgeGraphBuilder service: add_entity(), add_relationship(),
   find_connections(), build_company_graph(), detect_patterns().

4. Implement the Saturation Crawler:
   - Search seed entity across all scrapers
   - Discover connected entities (relatives, associates, companies)
   - Queue connected entities for search
   - Track novelty rate (new vs duplicate data)
   - Stop when novelty < 5% (saturation reached)
   - Switch to enrichment mode

5. Growth controls: max depth (default 3), max entities (default 200),
   confidence threshold (0.6), relationship type filter.

6. Expanding search UI: show the person at center, connections
   radiating outward, click any node to expand further.
```

### Expected time: 4-6 hours

---

## PHASE 8: Financial Scoring + AML + Marketing Tags
**Model: Sonnet** | **Thinking: ON** | **Reasoning: Medium**

### Prompt:
```
Read docs/specs/06-financial-aml-credit.md and docs/specs/10-marketing-tags-scoring.md.

1. Alternative Credit Score (300-850):
   - Collect: property records, liens, judgments, bankruptcies,
     UCC filings, address stability, employment indicators
   - Score components: payment behavior proxy (30%), stability (25%),
     wealth indicator (20%), utilization proxy (15%), trajectory (10%)
   - Use XGBoost model (train on historical data when available,
     rule-based scoring as initial fallback)

2. AML Screening:
   - Download and index: OFAC SDN, EU sanctions, UN sanctions,
     UK HMT, Australia DFAT, Canada OSFI
   - Fuzzy name matching (Jaro-Winkler + phonetic) against all lists
   - PEP detection from government websites
   - Adverse media screening from news crawlers
   - AML risk score: composite of sanctions + PEP + adverse media +
     jurisdiction risk + entity complexity

3. Marketing Tags:
   - Title loan candidate: low credit proxy + car owner + high interest signals
   - Gambling propensity: casino proximity + gambling site accounts +
     cash advance patterns
   - Ticket size estimation: income estimate + property value +
     vehicle value + spending signals
   - Consumer segments: luxury, budget, health-conscious, tech-savvy,
     family-oriented, investor, small business owner
   - Life event detection: moving, new job, marriage, divorce, new baby,
     retirement, college

4. Wire all scores into the person profile and make them searchable/filterable.
```

### Expected time: 3-5 hours

---

## PHASE 9: Review Tab + Open Discovery
**Model: Sonnet** | **Thinking: ON** | **Reasoning: Medium**

### Prompt:
```
Read docs/specs/00-MASTER-SPEC.md section on Open Discovery Engine and Review Tab.

1. Open Discovery (Track 2 — parallel to known source crawling):
   - Run SpiderFoot, Amass, theHarvester as subprocesses
   - Run Sherlock + Maigret for username discovery
   - Google dorking for the person's identifiers
   - Certificate Transparency log mining (crt.sh)
   - Common Crawl search for mentions
   - Wayback Machine archive search

2. All discovered URLs flow into a review queue (PostgreSQL table).

3. Review Tab UI:
   - List all newly discovered URLs not in source database
   - Preview content and extracted data
   - Approve → adds to permanent crawler database with reliability rating
   - Reject → deprioritized in future
   - Tag with category, reliability tier (A-F), data type
   - Bulk approve/reject
   - "Build Crawler" button generates template for approved sites

4. Self-improving loop: track which approved sites yield valuable data,
   prioritize similar discoveries higher in future.
```

### Expected time: 3-4 hours

---

## PHASE 10: Enrichment Score + Favourites + Never-Give-Up Retry
**Model: Sonnet** | **Thinking: ON** | **Reasoning: Medium**

### Prompt:
```
Read docs/specs/00-MASTER-SPEC.md sections on Enrichment Score,
Favourited Profile, and Never-Give-Up Retry.

1. Enrichment Score (0-100):
   - Score = weighted sum of category completeness
   - Categories: identity (15%), contact (15%), social (10%),
     financial (15%), property (10%), employment (10%),
     legal/court (10%), digital footprint (10%), relationships (5%)
   - Visual gauge: 0-25 red, 26-50 orange, 51-75 yellow, 76-100 green
   - Gap analysis showing exactly which categories are missing
   - One-click "Deep Enrich" targeting missing categories only

2. Favourited Profiles:
   - User can favourite any profile for continuous monitoring
   - Re-crawl per SLA: social (6-12h), business (weekly),
     courts (monthly), sanctions (daily)
   - Diff notifications when data changes
   - New identifiers auto-pivot across all sources
   - Score recalculated every cycle; drops trigger alerts

3. Never-Give-Up Retry:
   - 1st fail: retry with different proxy
   - 2nd fail: retry after 5min with new UA + TLS fingerprint
   - 3rd fail: queue for off-peak batch retry
   - Capacity-based: when system load < 60%, retry all
     "exhausted" sources from last 24h
   - Source down for all queries: circuit breaker + admin alert
```

### Expected time: 3-4 hours

---

## PHASE 11: Legal Compliance Layer
**Model: Opus** | **Thinking: ON** | **Reasoning: High**

Why Opus: Legal compliance requires careful reasoning about regulations.

### Prompt:
```
Read docs/specs/12-ethical-legal-compliance.md.

1. Consumer opt-out system:
   - Opt-out endpoint: POST /api/v1/optout
   - Suppression database checked before ANY data delivery
   - Multi-channel: web form, email, phone, mail
   - Propagation to all downstream systems
   - Audit trail for every opt-out

2. FCRA compliance mode (toggle):
   - Permissible purpose verification before access
   - Adverse action notice generation
   - Consumer dispute resolution workflow
   - 7/10 year data retention rules

3. Audit logging:
   - Every data access logged (who, what, when, why)
   - Every search logged with stated purpose
   - Immutable audit trail (append-only table)
   - 5-year retention minimum

4. Data retention & purge:
   - TTL per data type (configurable)
   - Automatic purge of expired data
   - Legal hold capability
```

### Expected time: 2-3 hours

---

## PHASE 12: Testing + Hardening + Deploy
**Model: Sonnet** | **Thinking: ON** | **Reasoning: Medium**

### Prompt:
```
1. Write integration tests for the full search pipeline:
   - Input a name → verify results come back from multiple scrapers
   - Verify dedup removes duplicates
   - Verify progress events are emitted
   - Verify results are stored in PostgreSQL, Typesense, and graph

2. Write unit tests for every scraper (mock external calls).

3. Load test: simulate 50 concurrent searches, verify system
   doesn't crash or deadlock.

4. Update docker-compose.yml with all services:
   PostgreSQL + AGE, Garnet, Typesense, Qdrant, Pulsar, Tor,
   FlareSolverr, the API server, workers.

5. Create Makefile targets:
   make dev — start all services
   make test — run all tests
   make scraper-health — check all scraper health
   make search — run a test search from CLI

6. Update README.md with setup instructions.
```

### Expected time: 3-4 hours

---

## Summary Table

| Phase | What | Model | Thinking | Reasoning | Time |
|-------|------|-------|----------|-----------|------|
| 1 | Fix critical bugs | **Opus** | ON | **High** | 2-4h |
| 2 | Modular architecture refactor | **Opus** | ON | **High** | 3-5h |
| 3 | SSE progress bars + real-time UI | **Sonnet** | ON | **Medium** | 2-3h |
| 4 | Scrapers batch 1 (top 20) | **Sonnet** | ON | **Medium** | 4-6h |
| 5 | Scrapers batch 2 (next 20) | **Sonnet** | ON | **Medium** | 4-6h |
| 6 | Entity resolution + dedup | **Opus** | ON | **High** | 4-6h |
| 7 | Knowledge graph + expanding search | **Opus** | ON | **High** | 4-6h |
| 8 | Financial scoring + AML + marketing tags | **Sonnet** | ON | **Medium** | 3-5h |
| 9 | Review tab + open discovery | **Sonnet** | ON | **Medium** | 3-4h |
| 10 | Enrichment score + favourites + retry | **Sonnet** | ON | **Medium** | 3-4h |
| 11 | Legal compliance layer | **Opus** | ON | **High** | 2-3h |
| 12 | Testing + hardening + deploy | **Sonnet** | ON | **Medium** | 3-4h |
| **TOTAL** | | | | | **~37-56h** |

---

## Rules for Every Phase

1. **One phase at a time.** Don't skip ahead. Don't combine phases.
2. **Test after every phase.** Don't move to the next phase if tests fail.
3. **Commit after every phase.** `git commit` with a clear message.
4. **If Claude Code gets confused**, restart a new chat for that phase. Fresh context helps.
5. **If a phase is too big**, split it. Tell Claude Code to do half, test, then the other half.
6. **Always reference the spec docs.** Every prompt starts with "Read docs/specs/..."
7. **Opus for architecture, Sonnet for implementation.** Don't use Opus for bulk code writing (slow and expensive). Don't use Sonnet for complex design decisions (may make wrong choices).
