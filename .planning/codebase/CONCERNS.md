# Codebase Concerns

**Analysis Date:** 2026-03-30

## Tech Debt

**Silent Exception Swallowing:**
- Issue: Over 80 `except Exception: pass` blocks across the codebase silently swallow errors. While some are intentional (e.g., optional Tor setup, audit logging), many mask real failures during crawling, import, and ingestion.
- Files: `api/main.py` (lines 64, 73, 81, 88, 111, 162, 237), `worker.py` (lines 50, 217), `modules/crawlers/httpx_base.py` (line 41), `modules/audit/audit_daemon.py` (lines 36, 185), `modules/enrichers/auto_dedup.py`, `modules/discovery/crawler_builder.py` (line 145)
- Impact: Failed crawler imports, broken DB writes, and connection failures go completely unnoticed. Debug cycles lengthen because errors leave no trace.
- Fix approach: Replace `except Exception: pass` with `except Exception: logger.debug(...)` at minimum. For critical paths (crawler import, DB writes), log at WARNING level and emit a metric.

**Duplicated Crawler Import Logic:**
- Issue: `_import_all_crawlers()` is copy-pasted in three separate files with slightly different implementations (one uses `pkgutil.iter_modules`, two use `os.walk`).
- Files: `api/main.py` (line 46), `worker.py` (line 36), `lycan.py` (line 64)
- Impact: The `lycan.py` version only imports top-level crawler modules (misses subpackages like `crawlers/property/`, `crawlers/transport/`). This means CLI-launched searches silently skip 20+ crawlers.
- Fix approach: Consolidate into a single function in `modules/crawlers/__init__.py` or `modules/crawlers/registry.py`. All entry points call the same function.

**Unimplemented Builder Filters:**
- Issue: Five post-filter criteria in the People Builder accept parameters but do nothing — they log a warning and return unfiltered results.
- Files: `modules/builder/filters.py` (lines 52, 62, 91, 102, 107)
- Impact: Users of the `/builder` API can specify `property_value_range`, `vehicle_value_min`, `education_level`, `has_criminal_record`, or `has_bankruptcy` filters and silently get unfiltered results. This is a data correctness issue.
- Fix approach: Either implement the filters using existing model joins (CriminalRecord, Education, Property tables exist) or return a 400 error when unsupported filters are passed.

**Export Endpoint Uses Wrong Attribute Names:**
- Issue: The JSON export endpoint references `person.dob`, `person.risk_score`, `i.identifier_type`, and `i.platform` — none of which exist on the actual SQLAlchemy models. The Person model uses `date_of_birth`, `default_risk_score`, and the Identifier model uses `type` and no `platform` column.
- Files: `api/routes/export.py` (lines 39-47)
- Impact: The `/export/{person_id}/json` endpoint will throw `AttributeError` at runtime for every request. This is a broken endpoint.
- Fix approach: Update attribute references to match the model: `person.date_of_birth`, `person.default_risk_score`, `i.type`, and remove `i.platform` (or use a relevant field).

**Hardcoded Worker Counts:**
- Issue: Ingestion daemon count (2) is hardcoded in `worker.py` with no CLI flag or env var override.
- Files: `worker.py` (line 99)
- Impact: Cannot tune ingestion throughput without code changes.
- Fix approach: Add `--ingesters` CLI argument or `LYCAN_INGESTION_WORKERS` env var.

## Known Bugs

**Broken JSON Export Endpoint:**
- Symptoms: `/export/{person_id}/json` raises `AttributeError` on every call.
- Files: `api/routes/export.py` (lines 35-52)
- Trigger: Any call to the JSON export endpoint.
- Workaround: Use the CSV export endpoint or query the API directly.

**CLI Crawler Loader Misses Subpackages:**
- Symptoms: Running `python lycan.py --name "John Smith"` skips crawlers in subpackages (property, transport, gov, media, etc.).
- Files: `lycan.py` (line 64-73)
- Trigger: Any CLI search. Only top-level crawlers under `modules/crawlers/` are loaded; subpackage crawlers like `modules/crawlers/property/county_assessor_multi.py` and `modules/crawlers/transport/faa_aircraft_registry.py` are not imported.
- Workaround: Use the API or worker process instead of the CLI.

## Security Considerations

**SQL Injection via Dynamic Table Names in Merge:**
- Risk: The deduplication merge executor constructs SQL with f-strings: `f"UPDATE {table} SET person_id = :canonical WHERE person_id = :dup"`. Although `REASSIGN_TABLES` is a hardcoded tuple and there is a regex validation (`_SAFE_TABLE_RE`), the pattern of injecting table names into raw SQL is fragile. Any future modification that allows external table name input would be exploitable.
- Files: `modules/enrichers/deduplication.py` (lines 903-940)
- Current mitigation: Regex validation (`^[a-z_][a-z0-9_]{1,62}$`) and hardcoded table list.
- Recommendations: Use SQLAlchemy's `Table` objects or `inspector.get_table_names()` to validate table existence at startup. Consider using ORM-level cascade operations instead of raw SQL.

**Default Secrets in Configuration:**
- Risk: `secret_key`, `typesense_api_key`, and `tor_control_password` all default to `"changeme"` or similar placeholder values. While there is a startup warning for `secret_key` in non-dev environments, the other defaults have no warning.
- Files: `shared/config.py` (lines 32, 39, 80)
- Current mitigation: Startup check warns about `secret_key` only (`api/main.py` line 100).
- Recommendations: Add startup validation that rejects default values for all secret fields when `ENVIRONMENT != "dev"`. Better yet, make these fields required (no default) so the app fails to start without explicit configuration.

**ILIKE Queries With User Input:**
- Risk: Multiple API endpoints use `Person.full_name.ilike(f"%{q}%")` with user-supplied strings. While SQLAlchemy parameterizes these properly (no SQL injection), special SQL LIKE characters (`%`, `_`) in user input can cause unexpected matching behavior and potential performance issues with leading wildcards.
- Files: `api/routes/persons.py` (line 131), `api/routes/search.py` (lines 399, 575)
- Current mitigation: SQLAlchemy handles parameterization.
- Recommendations: Escape LIKE wildcards in user input (`q.replace('%', '\\%').replace('_', '\\_')`). Consider using PostgreSQL full-text search (`tsvector`/`tsquery`) for name searches — it is faster and more correct than ILIKE with leading wildcards.

**No Authentication on WebSocket:**
- Risk: The WebSocket endpoint `/ws/progress/{person_id}` validates a token via query param, but the person_id is a UUID that may be guessable. Any authenticated user can subscribe to any person's progress events.
- Files: `api/routes/ws.py` (lines 58-113)
- Current mitigation: API key auth via query parameter.
- Recommendations: Add authorization check — verify the requesting API key has permission to access the specific person record.

**Audit Log Fire-and-Forget With Silent Failure:**
- Risk: The `AuditLogMiddleware` writes audit entries in a fire-and-forget pattern with bare `except Exception: pass`. If the database is down or slow, audit logs are silently dropped with no indication.
- Files: `api/main.py` (lines 221-238)
- Current mitigation: None.
- Recommendations: Buffer failed audit entries in Redis/Dragonfly and retry. At minimum, log a counter of dropped audit entries.

## Performance Bottlenecks

**Leading-Wildcard ILIKE Queries:**
- Problem: `Person.full_name.ilike(f"%{q}%")` forces a sequential scan — PostgreSQL cannot use a B-tree index with leading wildcards.
- Files: `api/routes/persons.py` (line 131), `api/routes/search.py` (lines 399, 575)
- Cause: No GIN/GiST trigram index or full-text search index on `persons.full_name`.
- Improvement path: Add a `pg_trgm` GIN index on `persons.full_name` (supports `ILIKE '%pattern%'` efficiently) or switch to `tsvector`-based search for the name search endpoint.

**N+1 Risk in Person Detail Endpoint:**
- Problem: The person detail endpoint (`/persons/{person_id}`) loads the person and then issues separate queries for identifiers, social profiles, addresses, criminal records, etc.
- Files: `api/routes/persons.py` (line 179 onward)
- Cause: Each related table is queried individually rather than using `selectinload` or `joinedload`.
- Improvement path: Use SQLAlchemy's eager loading strategies. For the list endpoint, addresses are already bulk-loaded (good), but the detail endpoint should follow the same pattern.

**Aggregator File Size (1842 lines):**
- Problem: `modules/pipeline/aggregator.py` at 1842 lines handles routing for every crawler result type. Adding a new crawler result type requires modifying this monolithic file.
- Files: `modules/pipeline/aggregator.py`
- Cause: All result-type-specific ingestion logic lives in one file with per-platform set matching.
- Improvement path: Split into per-category sub-aggregators (social, financial, property, etc.) with a registry pattern similar to crawlers.

**Deduplication File Size (1156 lines):**
- Problem: `modules/enrichers/deduplication.py` combines fuzzy matching, merge execution, bloom filters, and ML scoring in one file.
- Files: `modules/enrichers/deduplication.py`
- Cause: Organic growth without module extraction.
- Improvement path: Extract `AsyncMergeExecutor` and fuzzy matching into separate modules.

## Fragile Areas

**Merge Executor Raw SQL:**
- Files: `modules/enrichers/deduplication.py` (lines 895-964)
- Why fragile: Uses raw SQL (`sa_text()`) with dynamic table names to reassign foreign keys during person merging. Adding a new table with a `person_id` FK requires manually adding it to `REASSIGN_TABLES`. Missing a table means orphaned records after a merge.
- Safe modification: When adding a new model with `person_id` FK, add the table name to `AsyncMergeExecutor.REASSIGN_TABLES`. Test with the existing dedup test suite.
- Test coverage: Test suite covers basic merge; does not verify all 15+ tables in `REASSIGN_TABLES` are correctly reassigned.

**Aggregator Platform Sets:**
- Files: `modules/pipeline/aggregator.py` (lines 79-194)
- Why fragile: Each new crawler platform must be added to the correct `_*_PLATFORMS` set (e.g., `_SOCIAL_PLATFORMS`, `_PHONE_PLATFORMS`, `_PROPERTY_PLATFORMS`). If a new crawler registers with a platform name not in any set, its results are silently dropped or misrouted.
- Safe modification: When adding a new crawler, add its platform string to the correct set in `aggregator.py`. Verify with an integration test.
- Test coverage: No automated check that all registered crawlers have a matching aggregator platform mapping.

**Optional Model Imports in Aggregator:**
- Files: `modules/pipeline/aggregator.py` (lines 40-74)
- Why fragile: Seven model classes are imported with try/except and set to `None` on failure (`EmploymentHistory`, `Education`, `Property`, `Vehicle`, `CryptoWallet`, `ProfessionalLicense`, `CorporateDirectorship`, `AdverseMedia`). If an import fails silently, all data for that category is silently skipped.
- Safe modification: These should be required imports. If the model file does not exist, the app should fail at startup rather than silently degrading.
- Test coverage: No test verifies all model imports succeed.

**Event Bus Single Point of Failure:**
- Files: `shared/events.py`
- Why fragile: All job dispatch, progress events, and inter-daemon communication flow through a single Dragonfly/Redis connection. If the connection drops, crawl jobs stop dispatching and progress events are lost. The `dequeue` and `dequeue_any` methods catch all exceptions and return `None`, making connection failures indistinguishable from an empty queue.
- Safe modification: Add a health check that surfaces Redis connection state. Consider automatic reconnection with backoff.
- Test coverage: Tests mock the event bus; no integration test verifies behavior under connection failure.

## Scaling Limits

**Database Connection Pool:**
- Current capacity: pool_size=50, max_overflow=100 (configurable via env vars).
- Limit: At 50 concurrent crawlers per worker + 2 ingesters + API requests, the pool can be exhausted during high-throughput crawling.
- Scaling path: Increase `LYCAN_DB_POOL_SIZE` or use PgBouncer for connection pooling at the infrastructure level.

**Single Dragonfly Instance:**
- Current capacity: All queues (high/normal/low/ingest/index) and pub/sub channels share one Dragonfly connection.
- Limit: Redis-compatible in-memory stores have single-thread bottlenecks for pub/sub at high message rates. With 50+ concurrent crawlers publishing results, pub/sub latency may spike.
- Scaling path: Separate queue operations (lists) from pub/sub onto different instances, or use Redis Cluster mode if supported by Dragonfly.

**Sequential Enrichment Pipeline:**
- Current capacity: Enrichers run sequentially per person (`EnrichmentOrchestrator` line 48: "run sequentially, no asyncio.gather").
- Limit: A person with 15+ enrichment steps takes the sum of all enricher durations. Financial/AML enrichment alone queries 6+ tables.
- Scaling path: Group enrichers by dependency and run independent groups concurrently with `asyncio.gather`.

## Dependencies at Risk

**Try/Except Model Imports:**
- Risk: Seven ORM model classes are conditionally imported in `modules/pipeline/aggregator.py`. If any model file has a syntax error or missing dependency, the import silently fails and the model is set to `None`, causing all data for that category to be silently skipped during ingestion.
- Impact: Property data, vehicle records, employment history, education, crypto wallets, professional licenses, and adverse media could all be silently dropped with no error.
- Migration plan: Convert to required imports. Fail fast at startup if any model cannot be imported.

**FlareSolverr Class-Level Health Cache:**
- Risk: `FlareSolverrCrawler._fs_healthy` is a class-level variable shared across all instances. Positive health is cached indefinitely (never re-probed). If FlareSolverr goes down after a successful probe, all subsequent requests will attempt FlareSolverr and fail before falling back.
- Impact: Extra latency (up to 70s per request) when FlareSolverr goes down after initial startup.
- Files: `modules/crawlers/flaresolverr_base.py` (lines 37-38, 44)
- Migration plan: Add a positive TTL (e.g., 300s) so the health probe is re-run periodically.

## Missing Critical Features

**No Input Sanitization for LIKE Wildcards:**
- Problem: User-supplied search queries are used directly in ILIKE patterns without escaping `%` and `_` characters.
- Blocks: Correct search behavior when users type these characters.

**No Rate Limiting on WebSocket/SSE Connections:**
- Problem: While HTTP endpoints have `slowapi` rate limiting (100/minute), WebSocket and SSE endpoints have no connection limits. A single client could open unlimited SSE streams.
- Files: `api/routes/ws.py`
- Blocks: Production deployment without abuse protection.

**No Graceful Degradation for Missing Services:**
- Problem: The API starts even when critical services (database, Redis, Typesense) are down. Startup checks log errors but do not prevent the app from accepting requests. Requests then fail with opaque 500 errors.
- Files: `api/main.py` (lines 114-155)
- Blocks: Reliable production operation. The health endpoint should reflect service availability.

## Test Coverage Gaps

**Export Endpoints:**
- What's not tested: The `/export/{person_id}/json` and `/export/{person_id}/csv` endpoints.
- Files: `api/routes/export.py`
- Risk: The JSON export endpoint is currently broken (wrong attribute names) and no test catches it.
- Priority: High

**Aggregator Platform Mapping Completeness:**
- What's not tested: No test verifies that every registered crawler platform has a corresponding entry in the aggregator's platform sets.
- Files: `modules/pipeline/aggregator.py`, `modules/crawlers/registry.py`
- Risk: New crawlers can be added and silently produce results that are never persisted.
- Priority: High

**Merge Executor Table Coverage:**
- What's not tested: No test verifies that all tables with a `person_id` FK are listed in `AsyncMergeExecutor.REASSIGN_TABLES`.
- Files: `modules/enrichers/deduplication.py` (line 815)
- Risk: Person merges leave orphaned records in tables not listed in `REASSIGN_TABLES`.
- Priority: Medium

**Event Bus Reconnection:**
- What's not tested: Behavior when Redis/Dragonfly connection drops mid-operation.
- Files: `shared/events.py`
- Risk: Silent failure mode — dispatchers spin endlessly getting `None` from dequeue without logging the connection loss.
- Priority: Medium

---

*Concerns audit: 2026-03-30*
