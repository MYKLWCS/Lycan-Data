# Lycan Platform Intelligence Overhaul
**Date:** 2026-03-24
**Status:** Approved (v2 — spec review fixes applied)
**Scope:** Six phases — auto-dedup, contact card, knowledge graph, commercial tags, expanded crawlers, in-app audit

---

## Problem Statement

The platform collects data but does not surface it intelligently. Duplicate records pollute results. The person view is a list of fields, not a usable contact. The graph is a table. Risk modeling exists in score fields but is never translated into actionable commercial tags. Crawler coverage is wide but thin. The scoring system never reaches 1.0 even for fully-corroborated records. Audit is CI-only.

---

## Architecture Overview

```
Crawlers (128+) → Pipeline → DB (PostgreSQL)
                                  │
              ┌───────────────────┼──────────────────────┐
              │                   │                       │
        AutoDedup Job       CommercialTagger         AuditDaemon
        (asyncio loop)      (asyncio loop)           (asyncio loop)
              │                   │                       │
              └───────────────────┼──────────────────────┘
                                  │
                            FastAPI routes
                                  │
                           SPA (index.html)
                    ┌─────────────┼──────────────┐
              ContactCard    KnowledgeGraph    AuditView
```

All new background jobs follow the existing `asyncio` daemon pattern used by `FreshnessScheduler`, `GrowthDaemon`, and `CrawlDispatcher` in `worker.py`: a class with `async def start()` that loops with `asyncio.sleep`. No new dependencies (no APScheduler).

---

## Phase 1 — Auto-Deduplication + Score Calibration

### Auto-Dedup Background Job

**Location:** `modules/enrichers/auto_dedup.py`

A daemon class `AutoDedupDaemon` follows the existing pattern:

```python
class AutoDedupDaemon:
    async def start(self):
        while True:
            await self._run_batch()
            await asyncio.sleep(600)  # 10 minutes
```

**Candidate sourcing — in-process batch scan (Option A):**
The daemon queries for persons updated in the last 10 minutes:
```sql
SELECT id FROM persons WHERE updated_at > now() - interval '10 minutes'
```
For each person, it calls the existing `score_person_dedup(person_id, session)` from `modules/enrichers/deduplication.py`, which returns `MergeCandidate` instances. There is no external queue — candidates are produced and consumed in the same run.

**Processing per candidate pair:**
- Score ≥ 0.85: auto-merge immediately
- Score 0.70–0.84: insert `DedupReview` row for manual review
- Score < 0.70: skip

**Canonical record selection — richer-record-wins:**
```python
def _count_populated_fields(person, session) -> int:
    """Sum non-null scalar fields on Person + count of child rows across
    identifiers, social_profiles, addresses, employment, criminal_records."""
```
The person with the higher count becomes canonical. The other record's child rows (identifiers, social profiles, aliases, criminal records, addresses) are re-parented to the canonical ID. The source `Person` row is set `merged_into = canonical_id` and soft-deleted (not hard-deleted).

**Merge safety:**
- Both records' UUIDs written to `audit_log` with `action="auto_merge"`
- All child table updates and the `merged_into` write happen in a single transaction; any failure rolls back completely
- `merged_into` is indexed for fast lookup

**`GET /persons/{id}` redirect behaviour for merged IDs:**
If a request arrives for a merged person ID, the route returns HTTP 301 with `Location: /persons/<canonical_id>`. The response body also includes `{"merged_into": "<canonical_id>"}` for API clients that don't follow redirects.

### Score Calibration

**Problem:** `composite_quality = reliability × freshness × corroboration` uses a log curve in `shared/data_quality.py :: corroboration_score_from_count()` that reaches 1.0 only at ~10 sources.

**Fix:** Replace `corroboration_score_from_count()` with a sigmoid that saturates earlier:
```python
from math import exp

def corroboration_score_from_count(count: int) -> float:
    """Sigmoid curve: count=1→0.50, count=2→0.73, count=3→0.88, count=5→0.98, count=7→1.0"""
    if count <= 0:
        return 0.0
    return min(1.0, 1 / (1 + exp(-1.5 * (count - 1))))
```

No source-type weighting is added — the curve applies uniformly to count. This is the only change to `shared/data_quality.py`. No call-site or migration changes are needed since the function signature is unchanged.

**Display calibration:** Change all `0.0–1.0` score displays in `index.html` to `0–100` integers via `Math.round(score * 100)`. Already partially done for `composite_quality`; apply consistently to all four Person dials and all identifier/record confidence values.

### New API Endpoints

- `GET /dedup/auto-queue` — pending `DedupReview` rows (score, both person IDs, names)
- `POST /dedup/auto-merge/run` — trigger one batch immediately (for ops)
- `GET /persons/{id}` — add `merged_into` to response; return 301 if person is merged

---

## Phase 2 — Contact Intelligence Card

### Design

Replace the current two-column person detail layout with a full-screen contact card. Every piece of data is a clickable link.

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  [Avatar]  John Smith                                [× Close]  │
│            ◉ HIGH RISK  ◉ 94 Quality  ◉ VERIFIED               │
│            [Commercial Tags: TITLE LOAN] [MORTGAGE] [GAMBLING]  │
├──────────────────┬──────────────────────────────────────────────┤
│  LEFT RAIL        │  MAIN CONTENT (tabbed)                      │
│  (300px)          │  [Identity] [Connections] [Risk] [Activity] │
│                   │                                             │
│  Quick Facts      │  Tab content here                           │
│  DOB: [link]      │                                             │
│  Gender: Male     │                                             │
│  Nationality: US  │                                             │
│                   │                                             │
│  Scores (4 dials) │                                             │
│                   │                                             │
│  Actions          │                                             │
│  [View in Graph]  │                                             │
│  [Re-Enrich]      │                                             │
│  [Export]         │                                             │
│  [Flag for Review]│                                             │
└──────────────────┴──────────────────────────────────────────────┘
```

### Clickable Everything

| Field | Click action |
|-------|-------------|
| Email address | Opens `#/search?q=<email>&type=email` |
| Phone number | Opens `#/search?q=<phone>&type=phone` |
| Street address | Opens Google Maps (new tab) |
| Social profile handle | Opens platform URL (new tab) |
| Company name | Opens `#/graph?entity=company&q=<name>` |
| Related person name | Opens `#/persons/<id>` |
| Criminal record court | Opens CourtListener URL |
| Crypto wallet | Opens blockchain explorer |
| Domain | Opens URLScan.io for that domain |
| DOB | Opens `#/search?q=<dob>&type=dob` |
| IP address | Opens AbuseIPDB lookup |

### Tabs

**Identity tab:** All identifiers (email, phone, SSN, username, passport, DL), addresses, social profiles, employment history, education, aliases. Each row: type badge, value (clickable), confidence %, source reliability badge, last-scraped date.

**Connections tab:** Two sections:
1. Person relationships — each related person as a card: name (→ their contact card), relationship type, relationship score, shared identifiers count.
2. Entity connections — companies, locations, domains, wallets linked to this person with entity type badge and source.

**Risk tab:** 4 score dials + behavioral signals (gambling, financial distress, drug, violence, fraud — read from `BehaviouralSignals` rows) + OCEAN traits + watchlist matches + dark web mentions + criminal records + breach records.

**OCEAN storage fix (Phase 2 dependency):** OCEAN scores are currently computed in `modules/enrichers/psychological.py` as in-memory `PsychologicalProfile` fields and never persisted. As part of Phase 2, extend `_upsert_behavioural_profile()` in `modules/pipeline/aggregator.py` to write OCEAN scores into `BehaviouralProfile.meta`:

```python
# In aggregator._upsert_behavioural_profile():
if "ocean_openness" in crawler_data:
    profile.meta["ocean_openness"] = crawler_data["ocean_openness"]
    profile.meta["ocean_conscientiousness"] = crawler_data.get("ocean_conscientiousness")
    profile.meta["ocean_extraversion"] = crawler_data.get("ocean_extraversion")
    profile.meta["ocean_agreeableness"] = crawler_data.get("ocean_agreeableness")
    profile.meta["ocean_neuroticism"] = crawler_data.get("ocean_neuroticism")
```

The Risk tab reads these from `BehaviouralProfile.meta["ocean_openness"]` etc. If absent, the OCEAN section is hidden (not shown as zero).

**Activity tab:** Per-crawler run history from `CrawlJob` rows for this person. Shows: crawler name, ran_at, status (found/not-found/error), source reliability. Coverage percentage denominator = `SELECT COUNT(*) FROM data_sources WHERE is_enabled = TRUE` (live count, not hardcoded 128).

### Commercial Tags Display

Colored pill badges beneath person name:
- Red: `GAMBLING`, `PAYDAY LOAN`, `HIGH RISK CREDIT`
- Amber: `TITLE LOAN`, `AUTO LOAN`, `PERSONAL LOAN`
- Blue: `MORTGAGE`, `INVESTMENT`, `BANKING PREMIUM`
- Green: `HIGH NET WORTH`, `INSURANCE`

Hover tooltip shows `reasoning` list from `MarketingTag` row.

### API — Extend Existing `/persons/{id}/report`

The existing `GET /persons/{id}/report` endpoint in `api/routes/persons.py` is extended (not replaced) to include three new keys in its response dict:

```json
{
  "person": { ... },
  "identifiers": [ ... ],
  "addresses": [ ... ],
  "commercial_tags": [
    {
      "tag": "title_loan",
      "category": "lending",
      "confidence": 0.78,
      "reasoning": ["Vehicle record found", "Financial distress 62%", "No property ownership"],
      "scored_at": "2026-03-24T10:00:00Z"
    }
  ],
  "connections": {
    "persons": [
      {
        "person_id": "uuid",
        "full_name": "Jane Doe",
        "relationship_type": "co-location",
        "relationship_score": 0.82,
        "shared_identifier_count": 3
      }
    ],
    "entities": [
      {
        "entity_type": "company",
        "label": "Acme Corp",
        "source": "opencorporates",
        "linked_via": "employment"
      }
    ]
  },
  "coverage": {
    "sources_enabled": 131,
    "sources_attempted": 87,
    "sources_found": 61,
    "coverage_pct": 66,
    "crawl_history": [
      {
        "crawler": "twitter",
        "ran_at": "2026-03-20T08:00:00Z",
        "status": "found",
        "source_reliability": 0.55
      }
    ]
  }
}
```

No separate `/connections` or `/coverage` endpoints are needed — all data is in `/report`.

---

## Phase 3 — Knowledge Graph (D3.js)

### Library

**D3.js v7** force simulation, SVG rendering. Loaded from CDN. No external graph library.

### Entity Types and Visual Language

| Entity | Shape | Color |
|--------|-------|-------|
| Person | Circle (r=18) | `#1a6ef5` blue |
| Company | Square (28px) | `#805ad5` purple |
| Location | Diamond | `#d69e2e` amber |
| Email | Triangle | `#00c48c` green |
| Phone | Hexagon | `#38b2ac` teal |
| Crypto Wallet | Star | `#e53e3e` red |
| Domain | Octagon | `#ed8936` orange |
| IP Address | Circle (r=10) | `#718096` gray |

Edge colors: social=blue, financial=green, geographic=amber, criminal=red, shared-identifier=dim.

### Interactions

- **Click node** → side panel mini-card (name, top 3 facts, "Open full card" button)
- **Double-click node** → expand 1 hop deeper
- **Right-click node** → context menu: Expand, Hide, Focus, Find Path To
- **Drag** → pin node
- **Scroll / drag canvas** → zoom / pan
- **Shift+click two nodes** → find shortest path between them

### Filter Panel

Entity type checkboxes (Person, Company, Location, Email, Phone, Wallet, Domain), relationship type checkboxes (Social, Financial, Geographic, Criminal, Shared Identifier), date range slider, min relationship score slider, text search.

Filters update graph in real time — hidden entities fade, orphaned edges removed.

### Shortest Path

`GET /graph/path?from={id}&to={id}&entity_types=person,company&max_hops=6`

- `entity_types` is a **traversal filter**: only traverse through nodes of these types when finding the path. A path may not exist if the type constraint blocks all routes.
- `max_hops` default = 6, hard cap = 10 (server rejects requests above 10 with 400)
- BFS implementation on the backend; if no path found within `max_hops`, returns `{"path": null, "reason": "no_path_within_max_hops"}`
- Frontend highlights path in gold, dims all other nodes

### Performance

- Initial load: max 500 nodes (most-connected first via `ORDER BY degree DESC`)
- "Load more" fetches next 500
- Web Worker runs force simulation off main thread
- Nodes culled when outside viewport bounds

### New API Endpoints

All are new methods on `EntityGraphBuilder` in `api/routes/graph.py`:

- `GET /graph/nodes?limit=500&offset=0&entity_types=person,company` — paginated global node list
- `GET /graph/edges?limit=1000&offset=0` — paginated global edge list
- `GET /graph/path?from=&to=&entity_types=&max_hops=6` — BFS shortest path with traversal filter
- `GET /graph/entity/{entity_type}/{entity_id}/expand` — 1-hop expansion for any entity type

The existing `GET /graph/person/{id}/network` is extended to include non-person entity nodes (companies, addresses, domains) in its response, not just person nodes.

---

## Phase 4 — Risk Modeling + Commercial Tags

### Tag Engine

**Location:** `modules/enrichers/commercial_tagger.py`

This **extends** the existing `modules/enrichers/marketing_tags.py` engine. The existing functional scorer pattern (`_score_title_loan`, etc.) and `StrEnum` taxonomies (`LendingTag`, `BehaviouralTag`, etc.) are kept. Missing tags are added as new scorer functions following the same pattern. New tags added:

- `auto_loan` — vehicle record + no property + medium income
- `payday_loan` — financial_distress > 0.5 + no property + low income
- `insurance_auto` — vehicle record present
- `insurance_life` — dependant signals + income
- `insurance_health` — age 25–65 + employment
- `banking_basic` — any employed adult signal
- `banking_premium` — high income + investment signals
- `high_net_worth` — wealth data + property + investment
- `debt_consolidation` — multiple loan signals + financial distress

### PersonSignals Assembly

New dataclass `PersonSignals` in `modules/enrichers/commercial_tagger.py` assembles all signal data in a single DB query (JOIN across Person, Employment, Wealth, BehaviouralSignals, Identifier vehicle records, Address property flags):

```python
@dataclass
class PersonSignals:
    person_id: UUID
    has_vehicle: bool
    has_property: bool
    financial_distress_score: float   # sourced from BehaviouralProfile.financial_distress_score
    gambling_score: float             # sourced from BehaviouralProfile.gambling_score (via BehaviouralSignals)
    income_estimate: float | None     # sourced from Wealth.estimated_income_usd
    net_worth_estimate: float | None  # sourced from Wealth.estimated_net_worth_usd
    is_employed: bool                 # sourced from Employment rows (status == 'current')
    age: int | None                   # derived from Person.date_of_birth
    criminal_count: int               # COUNT of CriminalRecord rows
```

The existing `tag_person()` function is updated to call `_assemble_signals(person_id, session) -> PersonSignals` and pass it to all scorer functions.

### Confidence Threshold

Per-tag thresholds in the existing `_THRESHOLDS` dict continue to apply (0.65–0.70 per tag). The spec's "0.25 floor" is not used — existing thresholds are correct and prevent tag proliferation. New tags are added to `_THRESHOLDS` with per-tag values in the 0.60–0.70 range.

### Background Daemon

`CommercialTaggerDaemon` follows the asyncio loop pattern, running every 15 minutes on persons enriched since last run (via `last_scraped_at > last_run_at` filter).

### New API Endpoints

- `POST /persons/{id}/tag` — trigger tag computation for one person
- `GET /persons/{id}/tags` — all tags with confidence + reasoning (also included in `/report`)
- `GET /tags/summary` — `{tag: count}` aggregate across all persons
- `POST /tags/batch` — trigger computation for all persons with stale/missing tags

---

## Phase 5 — Expanded Crawler Coverage

### Priority New Sources

**Social Interests:**
- `reddit_history` — post/comment history + subreddit membership (Pullpush.io API)
- `youtube_channel` — channel metadata + video categories (public data)
- `threads_profile` — Threads.net public API
- `bluesky_profile` — AT Protocol public API (`https://public.api.bsky.app`)
- `spotify_public` — public playlists (no auth)

**People Search:**
- `spokeo` — via FlareSolverr
- `familytreenow` — public records
- `radaris` — people search
- `clustrmaps` — address history

**Courts (more states):**
- `pacer_federal` — federal courts (PACER API)
- `txcourts` — Texas courts
- `fl_courts` — Florida courts
- `ca_courts` — California courts

**News & Mentions:**
- `google_news_rss` — name + location in Google News RSS
- `gdelt_mentions` — GDELT Project API
- `bing_news` — Bing News RSS

**Property & Vehicles:**
- `redfin_property` — ownership history
- `county_assessor_tx` — Texas property records
- `county_assessor_fl` — Florida property records
- `vin_decode_enhanced` — richer VIN decode detail

Note: `licenseplatelookup` approaches that claim ownership chain from plate number may be restricted by DPPA — implement only via official/licensed data sources.

**Professional:**
- `linkedin_enhanced` — extend existing crawler: posts, skills, endorsements, education detail
- `github_profile` — repos, bio, contributions
- `stackoverflow_profile` — Q&A activity

**Financial:**
- `opencorporates_officers` — company director roles
- `sec_insider` — Form 4 insider trading

**Interests Extractor:**
- `interests_extractor` — meta-crawler: reads completed crawler results for a person and normalizes interest/following/liked-page signals into `BehaviouralProfile.interests` (`ARRAY(String)` column, already exists)

### Coverage Score

`Person.meta["coverage"]` = `{"attempted": N, "found": M, "total_enabled": K, "pct": N/K}`. Updated after each crawl job completes (in `pipeline/enrichment_orchestrator.py`).

---

## Phase 6 — In-App Audit Daemon

### Design

`AuditDaemon` follows the asyncio loop pattern, running hourly. Results stored in `SystemAudit` table and surfaced in the Activity view.

### What It Audits

**Per-person data quality:**
- Coverage score (`Person.meta["coverage"]["pct"]`)
- Freshness: `last_scraped_at < now() - 30 days`
- Completeness: non-null count on 10 key Person fields (name, DOB, gender, nationality, bio, profile_image_url, primary_language, date_of_birth, verification_status, conflict_flag resolution)
- Unresolved conflict flags

**Crawler health (from `CrawlJob` table, last 24h):**
- Per-crawler: `success_rate = found / (found + error)` where found = status "found", error = status "error"
- Crawlers with `success_rate = 0` flagged as "degraded"

**Data volume:**
- New persons (created_at > today)
- Auto-merges (audit_log WHERE action = "auto_merge" AND created_at > today)
- Tags assigned (marketing_tags.scored_at > today)

### Output

```python
class SystemAudit(Base, TimestampMixin):
    __tablename__ = "system_audits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_at: Mapped[datetime]
    persons_total: Mapped[int]
    persons_low_coverage: Mapped[int]     # coverage_pct < 50
    persons_stale: Mapped[int]            # last_scraped_at > 30 days
    persons_conflict: Mapped[int]         # conflict_flag=True, unresolved
    crawlers_total: Mapped[int]
    crawlers_healthy: Mapped[int]
    crawlers_degraded: Mapped[list] = mapped_column(JSONB, default=list)  # [{name, success_rate}]
    tags_assigned_today: Mapped[int]
    merges_today: Mapped[int]
    persons_ingested_today: Mapped[int]
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)  # full per-crawler breakdown
```

### Frontend — Activity View Sub-Section

New "System Audit" card added to existing Activity view (`#/activity`), loaded from `GET /audit/latest`. Shows health overview, data activity today, and a crawler success rate leaderboard (sorted descending, degraded crawlers highlighted red at bottom).

### New API Endpoints

- `GET /audit/latest` — most recent `SystemAudit` row
- `POST /audit/run` — trigger immediately
- `GET /audit/history?limit=30` — last N audit runs
- `GET /audit/crawlers` — per-crawler health breakdown (24h)
- `GET /audit/persons/stale?limit=50&offset=0` — persons needing re-scrape
- `GET /audit/persons/low-coverage?limit=50&offset=0` — persons with coverage < 50%

---

## Data Model Changes

### Person — add `merged_into`
```python
merged_into: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True), ForeignKey("persons.id"), nullable=True, index=True
)
```

### New: DedupReview
```python
class DedupReview(Base, TimestampMixin):
    __tablename__ = "dedup_reviews"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.id"))
    person_b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.id"))
    similarity_score: Mapped[float]
    reviewed: Mapped[bool] = mapped_column(default=False)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 'merge'|'keep_separate'
```

### New: SystemAudit
(fields above)

Both new tables require Alembic migrations. Migrations are generated (`alembic revision --autogenerate`) as part of Phase 1 and Phase 6 respectively.

---

## Phase 7 — Family Tree Builder

### Purpose

Given any seed person, automatically build their family tree: trace ancestors backward as far as records exist, trace descendants forward, authenticate each link with cross-referenced sources, and connect every family member as a node in the knowledge graph.

### Data Model

Genealogical relationships are stored in the existing `Relationship` table using new `rel_type` values. No new table required — the relationship model already has `person_a_id`, `person_b_id`, `rel_type`, `score`, and `meta` JSONB.

New `rel_type` values for family:
```
parent_of, child_of, sibling_of, spouse_of,
grandparent_of, grandchild_of, aunt_uncle_of, niece_nephew_of,
half_sibling_of, step_parent_of, step_child_of
```

Each relationship row also carries:
- `score` (0–1): confidence in the relationship (based on source corroboration)
- `meta["sources"]`: list of source names that corroborate the link
- `meta["marriage_date"]`, `meta["divorce_date"]` for spouse relationships
- `meta["birth_record_url"]`, `meta["death_record_url"]` for parent/child links

A new `FamilyTreeSnapshot` table caches the assembled tree per person so repeated views don't re-query all relationships:

```python
class FamilyTreeSnapshot(Base, TimestampMixin):
    __tablename__ = "family_tree_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    root_person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("persons.id"), index=True)
    tree_json: Mapped[dict] = mapped_column(JSONB)           # full serialised tree
    depth_ancestors: Mapped[int]                              # how many generations back
    depth_descendants: Mapped[int]                            # how many generations forward
    source_count: Mapped[int]                                 # total sources used
    built_at: Mapped[datetime]
    is_stale: Mapped[bool] = mapped_column(default=False)    # set True when new data arrives
```

### Genealogy Crawlers

New crawlers in `modules/crawlers/genealogy/`:

| Crawler | Source | What it fetches |
|---------|--------|-----------------|
| `familysearch` | FamilySearch public API | Birth, marriage, death records; parent/child/spouse links |
| `findagrave` | FindAGrave.com | Memorial pages with birth/death dates, spouse names |
| `ancestry_hints` | Ancestry public hints (no auth) | Suggested relatives from public trees |
| `census_records` | US Census via FamilySearch | Household members, ages, relationships (1790–1940) |
| `obituary_search` | Legacy.com, Tributes.com | Survivor names (spouse, children, parents listed) |
| `vitals_records` | State vital records APIs (where public) | Birth certificates, death certificates, marriage licenses |
| `newspapers_archive` | Chronicling America (LOC) | Birth/marriage/death announcements |
| `geni_public` | Geni.com public profiles | Family tree data from public profiles |

Each crawler emits `CrawlerResult.data` with a standardised schema:
```python
{
    "person_name": str,
    "birth_date": str | None,
    "birth_place": str | None,
    "death_date": str | None,
    "death_place": str | None,
    "parents": [{"name": str, "birth_year": int | None}],
    "children": [{"name": str, "birth_year": int | None}],
    "spouses": [{"name": str, "marriage_date": str | None}],
    "siblings": [{"name": str, "birth_year": int | None}],
    "source_url": str,
    "record_type": str,   # "birth_cert" | "census" | "obituary" | "memorial" | "tree"
}
```

### Genealogy Enricher

**Location:** `modules/enrichers/genealogy_enricher.py`

`GenealogyEnricher` runs as an asyncio daemon checking for persons flagged `needs_genealogy=True` in `Person.meta`.

**Algorithm:**

```
build_tree(seed_person_id):
    queue = deque([(seed_person_id, 0, "root")])
    visited = set()

    while queue:
        person_id, generation, direction = queue.popleft()
        if person_id in visited or abs(generation) > 8:
            continue
        visited.add(person_id)

        results = run_all_genealogy_crawlers(person_id)
        relatives = parse_relatives(results)   # cross-reference across sources

        for relative in relatives:
            canonical = find_or_create_person(relative)  # dedup against existing persons
            create_or_update_relationship(person_id, canonical.id, rel_type, confidence)
            queue.append((canonical.id, generation + direction_delta, direction))
```

Generation depth limit: 8 ancestors back (great-great-great-great-great-great-grandparents), unlimited forward (but stops when no more descendants are found).

**Authentication (confidence scoring):**
- 1 source: confidence = 0.40
- 2 independent sources agree: 0.72
- 3+ sources agree: 0.92
- Government record (birth/death cert, census): +0.15 bonus, capped at 1.0
- Conflicting sources: confidence = max(source_scores) × 0.6, `conflict_flag=True` on relationship

### Family Tree View (Frontend)

New view accessible from:
- Person contact card → "View Family Tree" button in left rail
- Navigation: `#/persons/<id>/tree`

**Layout:** D3 tree layout (not force-directed — hierarchical). Ancestors above the root, descendants below.

```
                    [Great-grandparent] [Great-grandparent]
                           └──────┬──────┘
                          [Grandparent] [Grandparent]
                                  └──────┬──────┘
                               [Parent]  [Parent]
                                    └──────┬──────┘
                    [Sibling] ──── [ROOT PERSON] ──── [Sibling]
                                    ┌──────┴──────┐
                               [Child]          [Child]
                                  └──────┬──────┘
                               [Grandchild] [Grandchild]
```

Each node is clickable — opens that person's contact card. Confidence shown as opacity (high confidence = solid, low = faded). Source count badge on each connection edge.

**Controls:**
- Generation depth slider (1–8 ancestors / 1–5 descendants)
- "Show only verified (confidence ≥ 0.70)" toggle
- "Expand to graph" button — loads all family members into the main knowledge graph
- Export to GEDCOM format (standard genealogy file format)

### Integration with Knowledge Graph

Family tree nodes ARE Person nodes. When "Expand to graph" is clicked, all family members are added to the knowledge graph with `rel_type` edges. In the graph view, family edges are shown in a distinct color (gold) and the family filter checkbox controls their visibility.

### New API Endpoints

- `GET /persons/{id}/family-tree?depth_ancestors=4&depth_descendants=3` — return `FamilyTreeSnapshot` or trigger build if none exists
- `POST /persons/{id}/family-tree/build` — trigger full rebuild
- `GET /persons/{id}/family-tree/status` — build progress (how many generations complete)
- `GET /persons/{id}/relatives` — flat list of all known relatives with relationship type and confidence

---

## Build Order and Dependencies

```
Phase 1 (Auto-Dedup + Score Calibration)   ← start here, cleans data
Phase 4 (Commercial Tags)                   ← cleaner data = better signals
Phase 2 (Contact Card)                      ← surfaces tags + merged_into redirect
Phase 3 (Knowledge Graph)                   ← node click opens Phase 2 card
Phase 5 (Expanded Crawlers)                 ← can run in parallel with 1-4
Phase 7 (Family Tree)                       ← depends on Phase 2 (contact card) + Phase 3 (graph)
Phase 6 (In-App Audit)                      ← audits everything above
```

---

## Testing Strategy

- Phases 1, 4, 6: unit + integration tests with seeded DB (mock HTTP, real SQLite/asyncpg)
- Phase 2: existing `test_api_routes_extended.py` patterns; extend with new `/report` fields
- Phase 3: unit test path-finding logic; frontend graph tested manually
- Phase 5: each new crawler follows `test_crawler_gaps.py` mock-HTTP pattern
- Phase 7: unit test genealogy enricher tree algorithm with seeded relatives; integration test GEDCOM export; crawler tests with mocked genealogy source responses

---

## Non-Goals

- No ML model training — commercial tags are rule-based only
- No real-time graph WebSocket updates — graph loads on demand
- No Neo4j or graph databases — PostgreSQL `relationships` table is sufficient
- No mobile layout — desktop only
- No DPPA-restricted plate-to-owner chains via unlicensed sources
