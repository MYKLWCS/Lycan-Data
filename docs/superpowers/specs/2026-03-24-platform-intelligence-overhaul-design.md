# Lycan Platform Intelligence Overhaul
**Date:** 2026-03-24
**Status:** Approved
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
        (APScheduler)       (APScheduler)            (APScheduler)
              │                   │                       │
              └───────────────────┼──────────────────────┘
                                  │
                            FastAPI routes
                                  │
                           SPA (index.html)
                    ┌─────────────┼──────────────┐
              ContactCard    KnowledgeGraph    AuditView
```

All new background jobs run on APScheduler (already used for pipeline tasks). No new infrastructure required.

---

## Phase 1 — Auto-Deduplication + Score Calibration

### Auto-Dedup Background Job

**Location:** `modules/enrichers/auto_dedup.py`

A scheduled job runs every 10 minutes and processes a batch of persons:

1. Pull unprocessed person pairs from the dedup candidate queue (already produced by `FuzzyDeduplicator`)
2. For each pair with similarity score ≥ 0.85: auto-merge without human confirmation
3. For pairs 0.70–0.84: create a `DedupReview` record for manual review in the UI
4. Below 0.70: ignore

**Canonical record selection — richer-record-wins:**
```python
def _count_populated_fields(person) -> int:
    """Count non-null, non-empty fields across person + all related records."""
```
The person with the higher field count becomes canonical. The other record's unique data (identifiers, social profiles, aliases, criminal records, addresses) is absorbed into the canonical record. No data is deleted — only the source `Person` row is removed after all child records are re-parented.

**Merge safety:**
- Both records' UUIDs are written to `audit_log` with action `auto_merge`
- A `merged_into` field is added to `Person` (nullable UUID FK) so old IDs resolve to canonical
- If a merge fails mid-transaction, it rolls back fully

### Score Calibration

**Problem:** `composite_quality = reliability × freshness × corroboration` where corroboration starts at 0.5 and only reaches 1.0 with 5+ independent sources. A government-sourced record with 3 corroborations scores ~0.57 max.

**Fix:** Recalibrate the corroboration curve so:
- 1 government source = 0.70 base corroboration
- 2 independent sources = 0.85
- 3+ independent sources = 1.0

Replace the linear multiplier with a sigmoid curve that saturates at 1.0:
```python
corroboration_score = 1 / (1 + exp(-2 * (corroboration_count - 1)))
```

**Display:** Change all score displays from `0.0–1.0` to `0–100` integers. `composite_quality: 0.97` → `97`. This makes "100" achievable and readable.

### New API Endpoints

- `GET /dedup/auto-queue` — pending auto-merge candidates (for monitoring)
- `POST /dedup/auto-merge/run` — trigger a batch manually
- `GET /persons/{id}` — add `merged_into` field to response

---

## Phase 2 — Contact Intelligence Card

### Design

Replace the current two-column person detail layout with a full-screen contact card. Every piece of data is a clickable link that either opens the source URL, searches for that value, or navigates to a related record.

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
│  ─────────────    │                                             │
│  DOB: [link]      │                                             │
│  Gender: Male     │                                             │
│  Nationality: US  │                                             │
│                   │                                             │
│  Scores           │                                             │
│  ─────────────    │                                             │
│  4 dials          │                                             │
│                   │                                             │
│  Actions          │                                             │
│  ─────────────    │                                             │
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

**Identity tab:** All identifiers (email, phone, SSN, username, passport, DL), addresses, social profiles, employment history, education, aliases. Each row has type badge, value (clickable), confidence %, source reliability badge, last-scraped date.

**Connections tab:** Two sections — (1) Person relationships: each related person as a card with their name (clickable → their contact card), relationship type, relationship score, shared identifiers count. (2) Entity connections: companies, locations, domains, wallets linked to this person.

**Risk tab:** 4 score dials + behavioral signals breakdown (gambling, financial distress, drug signals, violence, fraud) + watchlist matches + dark web mentions + criminal records + breach records.

**Activity tab:** Per-crawler run history — which crawlers ran, when, what they found (found/not-found/error), source reliability. Shows data coverage percentage: "87 of 128 sources attempted, 61 returned data."

### Commercial Tags Display

Tags displayed as colored pill badges beneath the person's name:
- Red: `GAMBLING`, `PAYDAY LOAN`, `HIGH RISK CREDIT`
- Amber: `TITLE LOAN`, `AUTO LOAN`, `PERSONAL LOAN`
- Blue: `MORTGAGE`, `INVESTMENT`, `BANKING PREMIUM`
- Green: `HIGH NET WORTH`, `INSURANCE`

Hovering a tag shows the reasoning list (e.g., "Vehicle record found · Financial distress 62% · No property ownership").

### New API Endpoints

- `GET /persons/{id}/report` — extend to include `commercial_tags`, `connections`, `crawler_coverage`
- `GET /persons/{id}/connections` — all person + entity connections with relationship metadata
- `GET /persons/{id}/coverage` — crawler run history for this person

---

## Phase 3 — Knowledge Graph (D3.js)

### Library

Use **D3.js v7** force simulation with SVG rendering. No external graph library — D3 gives full control over layout, styling, and interaction. Load from CDN in `index.html`.

### Entity Types and Visual Language

| Entity | Shape | Color |
|--------|-------|-------|
| Person | Circle (r=18) | `#1a6ef5` (blue) |
| Company | Square (28px) | `#805ad5` (purple) |
| Location | Diamond | `#d69e2e` (amber) |
| Email | Triangle | `#00c48c` (green) |
| Phone | Hexagon | `#38b2ac` (teal) |
| Crypto Wallet | Star | `#e53e3e` (red) |
| Domain | Octagon | `#ed8936` (orange) |
| IP Address | Circle (r=10) | `#718096` (gray) |

Edges are colored by relationship type: social (blue), financial (green), geographic (amber), criminal (red), shared-identifier (white/dim).

### Interactions

- **Click node** → opens side panel with mini contact card (name, top 3 facts, "Open full card" button)
- **Double-click node** → expand its connections (loads 1 hop deeper via API)
- **Right-click node** → context menu: Expand, Hide, Focus (hide everything else), Find Path To (then click another node)
- **Drag node** → repositions it, pins it
- **Scroll** → zoom in/out
- **Drag canvas** → pan
- **Shift+click two nodes** → find shortest path between them (highlights the chain)

### Filter Panel (left sidebar)

```
Entity Types          Relationship Types
☑ Person (142)        ☑ Social
☑ Company (38)        ☑ Financial
☑ Location (91)       ☑ Geographic
☑ Email (207)         ☑ Criminal
☑ Phone (184)         ☑ Shared Identifier
☑ Wallet (12)
☑ Domain (55)

Date Range
[────●──────────] Last 90 days

Min Relationship Score
[──────●────────] 0.30

Search nodes
[_______________]
```

Filters update the graph in real time — hidden entities fade out, edges orphaned by the filter are removed.

### Shortest Path

1. User clicks "Find Path" button or right-clicks a node → "Find Path To"
2. Source node highlighted with pulsing ring
3. User clicks target node
4. API call: `GET /graph/path?from={id}&to={id}&entity_types=person,company`
5. Path returned as ordered node+edge list
6. Path highlighted in gold, all other nodes dimmed

### Performance

- Initial load: pull max 500 nodes (most-connected first)
- "Load more" button fetches next 500
- Nodes beyond viewport are culled from render (virtual canvas)
- Web Worker runs the force simulation off the main thread

### New API Endpoints

- `GET /graph/nodes` — all entity nodes with type, label, risk_score, pagination
- `GET /graph/edges` — all edges with type, score, pagination
- `GET /graph/path?from=&to=&entity_types=` — shortest path (BFS)
- `GET /graph/entity/{type}/{id}/expand` — expand a specific entity's connections
- (existing) `GET /graph/person/{id}/network` — extended to return full entity graph, not just person nodes

---

## Phase 4 — Risk Modeling + Commercial Tags

### Tag Engine

**Location:** `modules/enrichers/commercial_tagger.py`

A rule-based scoring engine that maps signals from existing data to commercial product tags. Runs as a background job every 15 minutes on newly enriched persons.

### Tags and Signal Mapping

```python
COMMERCIAL_TAGS = {
    "title_loan": TitleLoanRule,       # Car + financial distress + low income
    "auto_loan": AutoLoanRule,         # Car + no property + medium income
    "payday_loan": PaydayLoanRule,     # Financial distress high + no property + low income
    "personal_loan": PersonalLoanRule, # Any loan signal + credit history
    "mortgage": MortgageRule,          # Property record OR high income + homeowner signal
    "refinance": RefinanceRule,        # Existing mortgage + financial distress
    "investment_account": InvestRule,  # High income + net worth signals
    "banking_basic": BankingBasicRule, # Any working adult signal
    "banking_premium": BankingPremRule,# High income + investment signals
    "insurance_auto": InsAutoRule,     # Vehicle record
    "insurance_life": InsLifeRule,     # Has dependants signals + income
    "insurance_health": InsHealthRule, # Age + employment status
    "gambling": GamblingRule,          # gambling_score > 0.3
    "high_net_worth": HNWRule,         # Wealth data + property + investment
    "debt_consolidation": DebtRule,    # Multiple loan signals + financial distress
}
```

### Rule Structure

Each rule is a class with:
```python
class TitleLoanRule(BaseTagRule):
    tag = "title_loan"
    category = "lending"

    def score(self, person_data: PersonSignals) -> TagResult | None:
        """Returns TagResult(confidence=0.0-1.0, reasoning=[...]) or None."""
```

`PersonSignals` is a flat dataclass assembled by joining Person + Employment + Wealth + BehaviouralSignals + vehicle identifiers + property records + CriminalRecord count.

Confidence is computed as a weighted sum of present signals. Reasoning is a list of human-readable strings explaining what evidence contributed.

A tag is written to `MarketingTag` only if confidence ≥ 0.25. Existing tags are updated (not duplicated) via upsert on the `uq_marketing_tag_person_tag` constraint.

### Predisposition Display

In the Marketing view, each person shows:
- Tag badges grouped by category (Lending, Banking, Insurance, Risk)
- OCEAN psychological traits (already tracked in `behavioural_profiles`)
- Income tier estimate
- Spend tier estimate (from `TicketSize`)

### New API Endpoints

- `POST /persons/{id}/tag` — manually trigger tag computation for one person
- `GET /persons/{id}/tags` — return all commercial tags with confidence + reasoning
- `GET /tags/summary` — aggregate: how many persons per tag (for targeting)
- `POST /tags/batch` — trigger tag computation for all persons missing tags

---

## Phase 5 — Expanded Crawler Coverage

### Priority New Sources

**Social Interests (highest value — fills interest/likes/dislikes data):**
- `reddit_history` — Post + comment history, subreddit membership (via Pushshift or Pullpush.io)
- `youtube_channel` — Channel metadata, comment patterns, video categories (public data)
- `threads_profile` — Threads.net via public API
- `bluesky_profile` — AT Protocol public API
- `spotify_public` — Public playlists if profile is public

**People Search (missing coverage):**
- `spokeo` — FlareSolverr (Cloudflare-protected)
- `familytreenow` — Public records aggregator
- `beenverified_public` — Public search results
- `radaris` — People search
- `clustrmaps` — Address history

**Court Records (more states):**
- `pacer_federal` — Federal court records (PACER API)
- `case_net_mo` — Missouri courts
- `iclaim_ca` — California courts
- `txcourts` — Texas courts
- `fl_courts` — Florida courts

**News & Mentions:**
- `google_news_rss` — Person name + location in Google News RSS (no auth)
- `gdelt_mentions` — GDELT Project API (news event database)
- `bing_news` — Bing News search API

**Property & Vehicles (expanded):**
- `redfin_property` — Property details and ownership history
- `county_assessor_tx` — Texas county property records
- `county_assessor_fl` — Florida county property records
- `vin_decode` — VIN decoder (NHTSA already exists, add more detail)
- `licenseplatelookup` — State plate → VIN → owner chain

**Professional:**
- `linkedin_enhanced` — Enhance existing LinkedIn crawler to extract posts, skills, endorsements, education details
- `glassdoor_public` — Company reviews authored by person
- `github_profile` — Code contributions, repositories, bio
- `stackoverflow_profile` — Q&A activity, reputation

**Financial:**
- `opencorporates_officers` — Director/officer roles in companies
- `sec_insider` — SEC Form 4 insider trading filings
- `fincen_sar` — FinCEN SAR public data

**Interests Extractor:**
- `interests_extractor` — Meta-crawler that parses `interests`, `liked_pages`, `following` from existing social scrape results and normalizes them into `behavioural_profiles.interests[]`

### Coverage Score

New metric per person: `crawler_coverage_score = crawlers_attempted / total_crawlers`. Stored in `Person.meta["coverage"]`. Displayed in the Activity tab of the contact card. Drives the re-scrape priority queue.

---

## Phase 6 — In-App Audit Daemon

### Design

An APScheduler job runs a self-audit every hour. Results are stored in a new `SystemAudit` table and surfaced in the Activity view.

### What It Audits

**Per-person data quality:**
- Coverage score (% of crawlers run)
- Freshness: how many records are > 30 days old
- Completeness: % of Person model fields populated (name, DOB, gender, address, employment, etc.)
- Conflict flag: persons with `conflict_flag=True` that haven't been reviewed

**Crawler health:**
- Per-crawler success rate (last 24h): `found_count / (found_count + error_count)`
- Crawlers with 0% success rate flagged as "degraded"
- Average response time per crawler

**Data volume:**
- New persons ingested today/this week
- Merges performed (auto + manual)
- Tags assigned this week
- Graph edges created

**Schema compliance:**
- Sample 10 random crawler results and verify required fields are present

### Output

Results stored in `SystemAudit` table:
```python
class SystemAudit(Base):
    id: UUID
    run_at: DateTime
    persons_total: int
    persons_low_coverage: int       # coverage < 0.5
    persons_stale: int              # last_scraped_at > 30 days
    persons_conflict: int           # conflict_flag=True, unresolved
    crawlers_degraded: list         # JSONB: [{crawler, success_rate}]
    crawlers_healthy: int
    tags_assigned_today: int
    merges_today: int
    meta: dict                      # full per-crawler breakdown
```

### Frontend — Audit View

New sub-section in the Activity view:

```
⬡ System Audit  [Last run: 3 min ago]  [Run Now]

Health Overview
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ 94 crawlers healthy
⚠ 7 crawlers degraded: [nitter] [holehe] [whitepa…]
⚠ 1,203 persons stale (> 30 days)
⚠ 47 persons low coverage (< 50%)
● 12 conflict flags pending review

Data Activity (today)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Persons ingested:  142
Auto-merges:       8
Tags assigned:     391
Graph edges added: 2,841

Crawler Leaderboard (24h success rate)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[OFAC]           100%  ████████████████████
[FBI Wanted]      100%  ████████████████████
[SEC]             98%  ███████████████████░
[Shodan]          97%  ███████████████████░
...
[Nitter]          12%  ██░░░░░░░░░░░░░░░░░░  ⚠ Degraded
[WhitePages]       0%  ░░░░░░░░░░░░░░░░░░░░  ✗ Down
```

### New API Endpoints

- `GET /audit/latest` — most recent audit result
- `POST /audit/run` — trigger audit immediately
- `GET /audit/history` — last 30 audit runs
- `GET /audit/crawlers` — per-crawler health stats
- `GET /audit/persons/stale` — persons needing re-scrape (paginated)
- `GET /audit/persons/low-coverage` — persons with coverage < 0.5

---

## Data Model Changes

### Person — add `merged_into` field
```python
merged_into: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True), ForeignKey("persons.id"), nullable=True, index=True
)
```

### New: SystemAudit table
(fields above)

### New: DedupReview table (for 0.70–0.84 similarity candidates)
```python
class DedupReview(Base):
    id: UUID
    person_a_id: UUID (FK persons)
    person_b_id: UUID (FK persons)
    similarity_score: float
    created_at: DateTime
    reviewed: bool = False
    decision: str | None  # 'merge' | 'keep_separate'
```

No changes to existing MarketingTag, ConsumerSegment, BehaviouralProfile models — they already support the required fields.

---

## Build Order and Dependencies

```
Phase 1 (Auto-Dedup + Score Calibration)
    → no dependencies, do first to clean data
Phase 4 (Commercial Tags)
    → depends on Phase 1 (cleaner data = better tag signals)
Phase 2 (Contact Card)
    → depends on Phase 4 (tags display in card)
    → depends on Phase 1 (merged_into for ID resolution)
Phase 3 (Knowledge Graph)
    → depends on Phase 2 (node click opens contact card)
Phase 5 (Expanded Crawlers)
    → can run in parallel with 1-4, but more data improves graph
Phase 6 (In-App Audit)
    → depends on all others (audits crawlers, coverage, tags, merges)
```

---

## Testing Strategy

Each phase ships with:
- Unit tests for all new enricher/rule logic
- Integration tests for new API endpoints (using existing test DB fixtures)
- Frontend: manual UAT checklist in spec

Phases 1 and 4 are fully testable with mocked DB data. Phases 2 and 3 require browser testing. Phase 5 crawlers use the existing `HttpxCrawler` test pattern (mock HTTP responses). Phase 6 audit tests use seeded DB state.

---

## Non-Goals

- No ML model training — commercial tags use rule-based scoring only
- No real-time graph updates via WebSocket (graph is loaded on demand)
- No third-party graph databases (Neo4j, etc.) — PostgreSQL + the existing `relationships` table is sufficient
- No mobile layout — desktop only, same as current platform
