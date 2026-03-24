# Napkin Runbook — Lycan OSINT

## Curation Rules
- Re-prioritize on every read.
- Keep recurring, high-value notes only.
- Max 10 items per category.
- Each item includes date + "Do instead".

---

## Execution & Validation (Highest Priority)

1. **[2026-03-24] httpx needs `httpx[socks]` for SOCKS5 Tor proxy**
   Do instead: install `httpx[socks]` (adds `socksio`) in the venv. Without it, ALL httpx crawlers silently return `found=False` with `error="http_error"` — no exception raised, no log. Verify: `.venv/bin/pip show socksio`.

2. **[2026-03-24] People-search sites (fastpeoplesearch/whitepages/truepeoplesearch) are Cloudflare-blocked**
   Do instead: these Playwright crawlers return 0 results against all scraping (even with Tor). Don't rely on them for address data. Use court records, obituaries, news, OFAC/sanctions as primary data sources instead.

3. **[2026-03-24] Name-search crawlers expect pipe-delimited identifier: "First Last|City,State"**
   Do instead: when calling whitepages/fastpeoplesearch/truepeoplesearch with a city, always format identifier as `"John Smith|Dallas,TX"`. Plain `"John Smith"` omits the city/state filter.

4. **[2026-03-24] MeiliSearch filterableAttributes must be declared before filtering**
   Do instead: any new field used in filters or sorts MUST be added to both `filterableAttributes` AND `sortableAttributes` in `meili_indexer.py::MEILI_SETTINGS` before use, then re-run `_ensure_index()`.

2. **[2026-03-24] IndexDaemon must fetch Address + SocialProfile — not just Identifier**
   Do instead: in `index_daemon.py`, always query all three tables (Identifier, Address, SocialProfile) when building MeiliSearch docs, otherwise city/state/platforms will be missing from search.

3. **[2026-03-24] datetime.utcnow() is deprecated in Python 3.12**
   Do instead: `from datetime import timezone` and use `datetime.now(timezone.utc)` everywhere. Never use `datetime.utcnow()`.

4. **[2026-03-24] Persons list total count must use COUNT() — not len()**
   Do instead: in `persons.py::list_persons()`, run a separate `select(func.count()).select_from(base_q.subquery())` for the total. `len(persons)` only returns page size.

7. **[2026-03-24] WebSocket timeout kills subscription if not inner-caught**
   Do instead: wrap `asyncio.wait_for(websocket.receive_text(), timeout=25.0)` in an inner `try/except asyncio.TimeoutError` that sends a ping and continues the loop — never let it bubble to the outer block.

---

## Pipeline Architecture

0. **[2026-03-24] Project path: `/data/projects/data broker project` (was osnit)**
   Do instead: all paths, imports, venv scripts now reference `/data/projects/data broker project`. Start API with `.venv/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000`. Start worker with `.venv/bin/python worker.py --workers 4`.

1. **[2026-03-24] Tor `status()` now checks SOCKS TCP reachability as fallback to control port**
   Do instead: `tor_manager.status()` returns True when SOCKS port (9050/9052/9054) is TCP-reachable, even if stem control port is unreachable. `can_rotate()` returns True only when control port is also up. The `dperson/torproxy` image binds control to 127.0.0.1 inside the container — SOCKS always works, control never does without `--control-host 0.0.0.0`.

2. **[2026-03-24] Queue names: high / normal / low / ingest / index**
   Do instead: crawl jobs go to high/normal/low queues. Raw crawler results go to `ingest`. Index trigger events go to `index`. Never mix these up.

2. **[2026-03-24] CrawlDispatcher → IngestionDaemon → IndexDaemon is the canonical pipeline**
   Do instead: dispatcher pulls crawl jobs → runs crawler → publishes to `ingest` queue. IngestionDaemon consumes ingest → writes to PostgreSQL → publishes to `index` queue. IndexDaemon consumes index → fetches full person state → pushes to MeiliSearch.

3. **[2026-03-24] Crawler registration uses `@crawler_registry` decorator**
   Do instead: add `@crawler_registry("platform_name")` above the class definition in any new crawler module. The module must be imported somewhere (e.g., crawlers `__init__.py`) for the decorator to fire.

4. **[2026-03-24] GrowthDaemon listens for `crawl_complete` events — not queue messages**
   Do instead: GrowthDaemon subscribes to the `enrichment` pub/sub channel and fans out follow-up jobs when a crawl completes. Don't try to put growth logic in the dispatcher.

---

## Deduplication & Merging

1. **[2026-03-24] Dedup uses Jaccard similarity on normalized names + DOB + shared identifiers**
   Do instead: `modules/deduplication.py` has the scoring logic. The API layer in `persons.py` calls it for `/persons/deduplicate`. Merge via `POST /persons/merge` which reassigns all FK rows (identifiers, addresses, profiles) then deletes the duplicate and re-indexes.

2. **[2026-03-24] `_get_or_create_person` must normalize names before matching**
   Do instead: always call `_normalize_name()` (lowercase + collapse whitespace) and use `Person.full_name.ilike(norm)` — never exact equality — when checking for existing persons in `aggregator.py`.

---

## Region Targeting

1. **[2026-03-24] Region search requires Address JOIN in PostgreSQL and filter in MeiliSearch**
   Do instead: for DB queries, JOIN Address with `ilike` filter. For MeiliSearch, use `city = "Dallas"` filter string passed to `meili_indexer.search()`. Both paths must be kept in sync.

2. **[2026-03-24] Region grow re-enqueues crawl jobs for all persons in a geographic area**
   Do instead: `POST /persons/region/grow` finds person IDs via Address JOIN, then for each identifier of each person enqueues a crawl job on the appropriate queue. Don't call enrichment directly — use the queue.

---

## Frontend Patterns

1. **[2026-03-24] Never use innerHTML with crawled data — XSS risk**
   Do instead: all user-facing data (names, handles, addresses) must be set via `textContent` or `el()`/`span()`/`div()` DOM helper functions defined at the top of `static/index.html`. Raw innerHTML is only acceptable for static structural markup.

2. **[2026-03-24] Hash router pattern: `#/`, `#/persons`, `#/person/:id`, `#/region`, `#/deduplicate`, `#/activity`**
   Do instead: new pages must be added to the `route()` function's switch statement and to the nav sidebar. The router re-runs on `hashchange` and initial load.

3. **[2026-03-24] WebSocket client keepalive: 20s setInterval sending "ping"**
   Do instead: the WS client in `renderPerson()` uses `setInterval(() => ws.send("ping"), 20000)`. Server echoes back `{"event":"pong"}`. Always clear the interval in the `onclose` handler.

4. **[2026-03-24] System poller runs every 15s to update sidebar queue depth + crawler count**
   Do instead: `_pollSystem()` calls `GET /system/queues` and `GET /system/stats`. The sidebar dot turns red if total_pending > 50. Don't remove this — operators rely on it.

---

## Critical Bugs Fixed (2026-03-24)

1. **[2026-03-24] asyncio.gather on same AsyncSession causes "another operation in progress"**
   Do instead: NEVER use asyncio.gather() with SQLAlchemy AsyncSession queries. Run all DB fetches sequentially on the same session. asyncpg does not allow concurrent queries on one connection.

2. **[2026-03-24] BurnerAssessment FK is identifier_id not person_id**
   Do instead: fetch burners via `BurnerAssessment.identifier_id.in_([i.id for i in idents])`. It links to Identifier, not Person.

3. **[2026-03-24] WhatsApp stores phone as SocialProfile handle — not as Identifier**
   Do instead: after `_upsert_social_profile` for whatsapp/telegram platforms, call `_upsert_phone_identifier()` to also store the phone number as an Identifier row with type=phone.

## New Models (added 2026-03-24)

1. **[2026-03-24] CriminalRecord, IdentityDocument, CreditProfile, IdentifierHistory are now live**
   Do instead: always include these in `reassign_models` when doing merges. Migration file: `a1b2c3d4e5f6_add_criminal_identity_history.py`. Aggregator routes court → CriminalRecord, NSOPW → CriminalRecord(sex_offender=True), PACER → CreditProfile.

2. **[2026-03-24] IdentityDocument never stores full SSN/document numbers — partial only**
   Do instead: `doc_number_partial` holds max last-4 digits (e.g., "***-**-1234"). Never write full numbers.

3. **[2026-03-24] IdentifierHistory is append-only — upsert on (person_id, type, value)**
   Do instead: the unique constraint `uq_idhistory_person_type_value` handles dedup. Call `_record_identifier_history()` in aggregator after every successful crawl — it fires automatically now.

## Domain Behavior Guardrails

1. **[2026-03-24] DataQualityMixin fields exist on ALL models — expose them in every API response**
   Do instead: `source_reliability`, `freshness_score`, `corroboration_count`, `composite_quality`, `conflict_flag`, `verification_status` are columns on every model. Include them in every `_person_summary()` and detail response. Frontend `relBadge()` renders them.

2. **[2026-03-24] Risk tier labels: critical (≥0.8), high (≥0.6), medium (≥0.4), low (<0.4)**
   Do instead: compute `risk_tier` in `index_daemon.py` from `default_risk_score` using this mapping before pushing to MeiliSearch. It's a filterable attribute.
