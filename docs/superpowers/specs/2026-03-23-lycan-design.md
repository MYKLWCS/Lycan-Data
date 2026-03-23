# Lycan OSINT Engine — Design Document
**Date:** 2026-03-23
**Status:** Approved
**Base Spec:** `/home/wolf/osnit/lycan-osint-spec.md` (WC-OSINT-SPEC-002)

> **Note on base spec:** WC-OSINT-SPEC-002 defines the core architecture and is the primary reference for Modules 1–9 structure, data models, and build order. This design document **supersedes** the following in the base spec:
> - Section 2.2 Layer 4: "Bright Data" → **Tor** (see Section 3.1 below)
> - Section 2.2 Layer 5: "NumVerify", "Hunter.io" → **see replacement map Section 3.2**
> - `modules/enrichment/identity/pipl.py`, `fullcontact.py` → **replaced by Section 3.3 (Identity Enrichment)**
> - `modules/behavioural/nlp/claude_analyser.py` → **replaced by local NLP only (see Section 4, Module 6)**
> - Build order Steps 4, 8: **see revised build order Section 7**
> Where this document conflicts with the base spec, this document wins.

---

## 1. What We Are Building

Lycan is a recursive people-intelligence platform and alternative data broker. It takes any identifier — phone, email, social handle, name, national ID, wallet address — resolves it to a real person, builds a relationship graph around them, and continuously enriches that profile from surface web, deep web, and dark web sources.

Primary outputs consumed by:
- **Lending platforms** (Dollar Loans LLC, Kwacha, Pula, Rand): loan default risk score at application time
- **iGaming compliance** (Wolf Corporation, NuxGame): AML, fraud, and PEP screening
- **OSINT investigations**: full dossier, relationship graph, dark web exposure

Core design principles:
- **No paid APIs.** Every data point comes from direct scraping or free open-source tools.
- **Tor-first.** All outbound requests route through Tor. No raw IP exposure.
- **Maximum modularity.** Every module is independently testable. Kill switches for everything.
- **Data quality tracked.** Every fact carries freshness, source reliability, and corroboration scores.
- **Perpetual growth.** The daemon never stops. Data broker grows itself.

---

## 2. Full Module List

```
lycan/
  modules/
    ingestion/         MODULE 1  — universal input parser + type detection
    crawlers/          MODULE 2  — Tor-routed Scrapy spiders + Playwright actors
    enrichment/        MODULE 3  — free/self-hosted enrichment (Sherlock, Holehe, theHarvester)
    burner/            MODULE 3b — burner/VoIP phone detection
    resolution/        MODULE 4  — identity dedup, merge, confidence scoring
    scoring/           MODULE 5  — relationship scoring + importance scoring
    behavioural/       MODULE 6  — gambling, crypto, criminal, lifestyle signals
    daemon/            MODULE 7  — continuous growth + freshness engine
    alerts/            MODULE 8  — alert engine + delivery (Telegram, email, webhook, WS)
    export/            MODULE 9  — PDF dossier, CSV, JSON, GraphML, Maltego
    darkweb/           MODULE 10 — dark web scan + crypto intelligence
    credit_risk/       MODULE 11 — loan default risk scoring
    wealth/            MODULE 12 — wealth banding + income estimation

  shared/
    config.py          — Pydantic Settings, all env vars, kill switches
    db.py              — SQLAlchemy async engine
    models/            — ORM models (source of truth)
    schemas/           — Pydantic request/response schemas
    events.py          — Dragonfly pub/sub event bus
    tor.py             — Tor circuit manager (NEW)
    data_quality.py    — quality scoring helpers (NEW)
    freshness.py       — staleness tracking + decay (NEW)
    constants.py       — enums, tiers, relationship types
    utils/             — phone, email, social, scoring helpers
```

---

## 3. Architecture Decisions

### 3.1 Tor as Universal Proxy

Every HTTP request in the system routes through Tor. Three dedicated Tor instances run as Docker services.

**Port assignment:**

| Service | SOCKS5 Port | Control Port | Assigned To |
|---------|-------------|--------------|-------------|
| tor-1 | 9050 | 9051 | MODULE 2 social actors, MODULE 3b burner probes |
| tor-2 | 9052 | 9053 | MODULE 2 Scrapy spiders, MODULE 3 enrichment |
| tor-3 | 9054 | 9055 | MODULE 10 dark web + paste sites |

Control port auth: **password-based** (`HashedControlPassword` in torrc). Password set via `TOR_CONTROL_PASSWORD` env var. `stem` library handles all control port operations.

**`shared/tor.py` public interface:**
```python
class TorManager:
    def __init__(self, instance: int = 1)        # 1, 2, or 3
    def new_circuit(self) -> None                # NEWNYM on this instance's control port
    def get_exit_country(self) -> str            # Two-letter exit node country code
    def check_connectivity(self) -> bool         # Verify circuit is working
    def get_socks_port(self) -> int              # Returns 9050 / 9052 / 9054

def tor_session(instance: int = 1) -> requests.Session     # requests via Tor instance
def tor_playwright_args(instance: int = 1) -> list[str]    # Playwright proxy launch args
```

**Playwright integration:**
```python
# tor_playwright_args(1) → ["--proxy-server=socks5://127.0.0.1:9050"]
browser = await playwright.chromium.launch(args=tor_playwright_args(instance=1))
```

**Scrapy integration:** `shared/scrapy_middleware.py` — `TorProxyMiddleware` sets `proxy` meta on each Request, calls `new_circuit()` on 429/403.

Override: `PROXY_OVERRIDE=socks5://host:port` bypasses Tor for all instances.

### 3.2 No Paid APIs — Full Replacement Map

| Removed | Replaced With |
|---------|--------------|
| NumVerify | libphonenumber + scrape Fonefinder.net + CarrierLookup.com |
| HLR lookup | WhatsApp/Telegram unofficial registration probe |
| TrueCaller API | Scrape TrueCaller web UI via Playwright |
| Hunter.io | theHarvester (self-hosted) + direct website/LinkedIn scraping |
| HIBP paid | HIBP free API (60 req/min) + breach paste site scraping |
| Holehe | Run Holehe as subprocess (open-source, 120+ services) |
| Sherlock | Run Sherlock as subprocess (open-source, 400+ sites) |
| Pipl / FullContact | Scrape Whitepages, FastPeopleSearch, TruePeopleSearch, Spokeo, BeenVerified |
| Bright Data proxies | Tor (primary) + configurable SOCKS5 override |
| 2Captcha | Playwright-stealth + undetected-chromium + human delays |
| ipinfo.io | Free IP lookup pages + MaxMind GeoLite2 (self-hosted) |

### 3.3 Identity Enrichment Replacement Files

The base spec's `pipl.py` and `fullcontact.py` are removed. The `modules/enrichment/identity/` directory is replaced with:

```
modules/enrichment/identity/
  people_search.py      # Playwright scraper: Whitepages, FastPeopleSearch, TruePeopleSearch
  spokeo.py             # Playwright scraper: Spokeo profile pages
  beenverified.py       # Playwright scraper: BeenVerified public results
  social_searcher.py    # Kept from base spec — cross-platform social search
```

Each file follows the base enricher pattern: `class XEnricher(BaseEnricher)` with `enrich(identifier: Identifier) → EnrichmentResult`.

### 3.3 Anti-Detection Stack

- `undetected-chromedriver` / `playwright-stealth` for all JS-rendered scraping
- Fingerprint randomisation: User-Agent, viewport, WebGL, canvas, timezone, language
- Human-like delays: random 2–8s between requests, scroll patterns, mouse movements
- Cookie jar management per domain
- Rate limiting: per-domain configurable RPS with exponential backoff

### 3.4 Module Kill Switches

Every module and data source has an env var toggle:

```env
ENABLE_TOR=true
ENABLE_INSTAGRAM=true
ENABLE_LINKEDIN=true
ENABLE_DARKWEB=true
ENABLE_BURNER_CHECK=true
ENABLE_CREDIT_RISK=true
ENABLE_WEALTH=true
ENABLE_CRIMINAL_SIGNALS=true
ENABLE_CRYPTO_TRACE=true
DAILY_API_BUDGET_USD=0
```

---

## 4. New Modules (Additions to Base Spec)

### MODULE 3b: Burner Detection

Detects VoIP, prepaid, and temporary phone numbers.

**Detection signals:**

| Signal | Method | Weight |
|--------|--------|--------|
| Line type = VoIP | libphonenumber | 0.40 |
| Carrier is known VoIP/burner provider | Carrier name match (curated list 200+) | 0.35 |
| Number prefix in known VoIP range | NPA-NXX database (free download) | 0.20 |
| Not registered on WhatsApp | Unofficial WA probe | 0.15 |
| Not registered on Telegram | Unofficial Telegram probe | 0.10 |
| WhatsApp profile < 30 days old | Profile metadata | 0.20 |
| No name in any reverse lookup | All reverse lookups empty | 0.15 |
| Number ported recently | CarrierLookup.com scrape | 0.15 |
| In TextNow/Google Voice/Hushed ranges | NPA-NXX cross-ref | 0.25 |

**Burner carrier list** (seeded, auto-growing): TextNow, Google Voice, Hushed, Burner, MySudo, Sideline, 2ndLine, iPlum, Talkatone, Bandwidth.com, Twilio, Vonage, Telnyx, Flowroute, and 200+ others.

**Confidence tiers:** Confirmed (0.70+), Likely (0.40–0.69), Possible (0.20–0.39), Clean (<0.20)

**New table:** `burner_assessments` (identifier_id, burner_score, line_type, carrier_category, signals JSONB, assessed_at)

**Public interface:**
```python
# modules/burner/__init__.py
def assess_burner(identifier: Identifier) -> BurnerAssessment:
    """
    Input:  Identifier (type=phone, normalised E.164 value)
    Output: BurnerAssessment(
                identifier_id: UUID,
                burner_score: float,          # 0.0–1.0
                burner_tier: str,             # CONFIRMED / LIKELY / POSSIBLE / CLEAN
                line_type: str,               # VoIP / mobile / landline / unknown
                carrier_name: str,
                carrier_category: str,        # voip_burner / voip_business / mvno / mno
                signals: list[BurnerSignal],  # per-signal evidence
                assessed_at: datetime
            )
    """
```

Consumed by MODULE 11 (Credit Risk) via: `from modules.burner import assess_burner`
Event published on completion: `burner.assessed` (see Section 8)

**Files:**
```
modules/burner/
  __init__.py           — public interface: assess_burner()
  README.md
  detector.py          — main burner score aggregator
  carrier_db.py        — curated carrier list loader + matcher
  npa_nxx.py           — NPA-NXX database lookup
  wa_probe.py          — WhatsApp registration probe
  telegram_probe.py    — Telegram registration probe
  reverse_scraper.py   — TrueCaller/Fonefinder scraping
  tests/
    test_detector.py
    fixtures/
```

---

### MODULE 6 Expansion: Criminal Activity Signals

Extends the behavioural module with illegal activity detection. All passive, read-only.

**NLP stack:** spaCy (local, no API cost) + keyword/regex matchers. `claude_analyser.py` from the base spec is **removed** — replaced by `local_nlp.py` using spaCy `en_core_web_lg` with custom entity rules.

| Dimension | Signals | Detection | New File |
|-----------|---------|-----------|----------|
| Drug dealing | Coded emojis, DM-for-prices, delivery language, cash app requests | spaCy NER + keyword | `signals/drug_dealing.py` |
| Fraud / scamming | Romance scam patterns, advance fee language, fake account signals | Keyword + dark web cross-ref | `signals/fraud.py` |
| Money laundering | Crypto mixer usage, rapid wallet cycling, structuring | Crypto tracer cross-ref | `signals/money_laundering.py` |
| Weapons / violence | Weapons references, threat language, dark web posts | spaCy NER + keyword | `signals/weapons.py` |
| Stolen goods | Cheap luxury patterns, serial number refs, listing analysis | Scrapy + keyword | `signals/stolen_goods.py` |
| Document fraud | ID/passport sale mentions, credential tools | Dark web scan cross-ref | `signals/document_fraud.py` |
| Financial crime | Shell company webs, sanctions evasion, fraud rings | Company registry + sanctions | `signals/financial_crime.py` |

**Updated `modules/behavioural/` additions:**
```
modules/behavioural/
  nlp/
    keyword_matcher.py     # kept
    local_nlp.py           # REPLACES claude_analyser.py — spaCy local NLP
    sentiment.py           # kept
  signals/
    # existing: gambling.py, crypto.py, political.py, lifestyle.py, adult.py, substance.py, risk.py
    drug_dealing.py        # NEW
    fraud.py               # NEW
    money_laundering.py    # NEW
    weapons.py             # NEW
    stolen_goods.py        # NEW
    document_fraud.py      # NEW
    financial_crime.py     # NEW
```

---

### MODULE 10: Dark Web & Deep Web Scanner

**Sources:**

| Source | Examples | Extracted |
|--------|----------|-----------|
| Dark web paste sites | Zerobin .onion, PrivateBin .onion | Credential dumps, PII leaks |
| Dark web search engines | Ahmia, Torch, DuckDuckGo .onion | Indexed .onion content |
| Dark web forums | Dread and mirrors | Username mentions, fraud forum posts |
| Breach/leak markets | Dark web credential markets (read-only) | Email/phone in leaked DBs |
| Telegram dark channels | Public criminal Telegram groups | Drug sales, fraud kits, trafficking ads |
| Clearnet paste sites | Pastebin, Ghostbin, BreachForums mirrors | Leaked databases, doxxes |
| IRC via Tor | Public IRC networks | Identity mentions |
| Crypto intelligence | Blockchain.info, Etherscan, Blockchair free APIs | Wallet history, mixer usage |

**Dark web exposure score:**

| Finding | Score | Severity |
|---------|-------|----------|
| Credentials in breach dump | 0.20 | MEDIUM |
| PII in paste/doxx | 0.30 | HIGH |
| Phone/email in fraud DB | 0.40 | HIGH |
| Username on criminal forum | 0.50 | HIGH |
| Crypto wallet flagged by exchange | 0.50 | HIGH |
| Wallet touched mixer | 0.60 | CRITICAL |
| Active market seller | 0.80 | CRITICAL |
| Named in trafficking/fraud op | 0.90 | CRITICAL |

**New tables:**
- `darkweb_mentions` (identifier_id, source_url_hash, source_type, mention_context, discovered_at, severity)
- `crypto_wallets` (person_id, address, chain, first_seen, last_seen, total_volume_usd, mixer_exposure, exchange_flags)
- `crypto_transactions` (wallet_id, tx_hash, counterparty_address, amount_usd, timestamp, risk_flags)

**Files:**
```
modules/darkweb/
  __init__.py
  README.md
  onion_crawler.py      — Tor Playwright actor for .onion sites
  paste_monitor.py      — clearnet + dark web paste scraper
  telegram_scanner.py   — public Telegram group/channel scanner
  irc_monitor.py        — IRC via Tor
  crypto_tracer.py      — free blockchain APIs
  leak_indexer.py       — index breach/leak data
  search_engines.py     — Ahmia, Torch query wrapper
  tests/
    test_onion_crawler.py
    test_crypto_tracer.py
```

---

### MODULE 11: Credit Risk Scorer

Produces `default_risk_score` (0.0–1.0) from pure OSINT. No credit bureau required.

**Signals:**

| Signal | Weight | Source Module |
|--------|--------|---------------|
| Gambling confirmed/likely | 0.25 | MODULE 6 |
| Financial distress language | 0.20 | MODULE 6 NLP |
| Multiple active loan app accounts | 0.15 | MODULE 3 (Holehe) |
| Payday lender / debt collector follows | 0.12 | MODULE 6 account analysis |
| Court judgments / debt orders | 0.18 | MODULE 2 (court spider) |
| Bankruptcy filings | 0.20 | MODULE 2 (company registry) |
| Dark web breach exposure | 0.10 | MODULE 10 |
| Burner phone used | 0.15 | MODULE 3b |
| Synthetic identity signals | 0.20 | MODULE 4 (resolution flags) |
| Address instability | 0.10 | shared/models/address.py |
| Employer instability | 0.10 | MODULE 12 |
| Lifestyle vs income inconsistency | 0.12 | MODULE 12 cross-ref |
| Criminal activity signals | 0.15 | MODULE 6 |
| Sanctions / watchlist hit | 0.30 | MODULE 2 (sanctions spider) |

**Risk tiers:**
- 0.80–1.00: Do Not Lend
- 0.60–0.79: High Risk
- 0.40–0.59: Medium Risk
- 0.20–0.39: Low Risk
- 0.00–0.19: Preferred

**New table:** `credit_risk_assessments` (person_id, risk_score, risk_tier, signal_breakdown JSONB, assessed_at, version)

**Files:**
```
modules/credit_risk/
  __init__.py
  README.md
  scorer.py           — main risk score aggregator
  signals/
    gambling.py       — pull gambling confidence from behavioural
    court.py          — court judgment signals
    identity.py       — synthetic identity signals
    financial.py      — financial distress NLP
    darkweb.py        — dark web exposure signals
  tests/
    test_scorer.py
```

---

### MODULE 12: Wealth Intelligence

Estimates wealth band and income from OSINT signals.

**Signals:**

| Signal | Method | Indicator |
|--------|--------|-----------|
| Employer + job title | LinkedIn scrape + Glassdoor scrape | Income band |
| Property ownership + value | Deeds registry + property site | Asset base |
| Vehicle signals | Photo analysis, dealership location tags | Asset class |
| Travel patterns | Airline/hotel check-ins, lounge posts | Spend level |
| School / university | Education history | Lifetime earnings proxy |
| Company directorships | CIPC, Companies House, SEC | Business wealth |
| Crypto portfolio | Wallet balances via blockchain APIs | Investment wealth |
| Luxury brand engagement | Follows, tags | Spend band |
| Neighbourhood | Property value data for area | Wealth proxy |
| Restaurant / venue tier | Location tags | Spend band |

**Wealth bands:**
```
ULTRA_HNW    > $10M
HIGH_HNW     $1M – $10M
AFFLUENT     $250K – $1M
MIDDLE       $50K – $250K
LOWER        $15K – $50K
STRESSED     < $15K or active distress signals
UNKNOWN      insufficient data
```

**New table:** `wealth_assessments` (person_id, wealth_band, income_estimate_usd_annual, confidence, signal_breakdown JSONB, assessed_at)

**Files:**
```
modules/wealth/
  __init__.py
  README.md
  assessor.py         — main wealth band aggregator
  signals/
    employment.py     — employer/title → income
    property.py       — property value signals
    lifestyle.py      — luxury/travel/vehicle signals
    crypto.py         — crypto portfolio signals
    corporate.py      — directorship + business signals
  tests/
    test_assessor.py
```

---

## 5. Data Quality Engine

Every fact in the database carries quality metadata. Tracked via a shared `DataQuality` mixin applied to all ORM models.

**Quality dimensions:**

| Dimension | Description | Stored As |
|-----------|-------------|-----------|
| `freshness_score` | Recency — decays from 1.0 at scrape time | FLOAT, computed |
| `source_reliability` | How trustworthy is the source | FLOAT, from source registry |
| `corroboration_count` | How many independent sources confirm it | INTEGER |
| `corroboration_score` | Weighted corroboration (accounts for source quality) | FLOAT |
| `conflict_flag` | Contradicts another known fact | BOOLEAN |
| `verification_status` | unverified / corroborated / verified | ENUM |
| `composite_quality` | Single 0–1 quality score | FLOAT, computed |

**Freshness half-lives:**

```
Sanctions / watchlists     6 hours
Breach databases           24 hours
Social media profiles      7 days
Social media posts         3 days
Phone registration         14 days
Employment data            60 days
Property records           90 days
Court records              30 days
Education records          365 days
```

**Source reliability registry (examples):**

```
Government registry        0.95
Court records              0.92
Sanctions list             0.98
LinkedIn (verified)        0.75
Whitepages                 0.65
Instagram profile          0.55
Twitter bio                0.50
Paste site                 0.30
Dark web mention           0.20
```

**New tables:**
- `data_quality_log` (record_type, record_id, field_name, old_value, new_value, quality_before, quality_after, source, updated_at)
- `freshness_queue` (record_type, record_id, source, next_refresh_at, priority) — daemon reads this

---

## 6. Data Broker API Layer

External-facing API for lending platforms, iGaming, and third-party consumers.

```
GET  /api/v1/lookup/phone/{e164}
GET  /api/v1/lookup/email/{email}
GET  /api/v1/lookup/social/{platform}/{handle}
GET  /api/v1/lookup/name/{name}?country=ZA
POST /api/v1/lookup/batch               (up to 100 identifiers)

GET  /api/v1/person/{id}                (full dossier)
GET  /api/v1/person/{id}/credit-risk    (default_risk_score + breakdown)
GET  /api/v1/person/{id}/wealth         (wealth_band + income estimate)
GET  /api/v1/person/{id}/behavioural    (all behavioural profiles)
GET  /api/v1/person/{id}/darkweb        (dark web exposure report)
GET  /api/v1/person/{id}/quality        (data freshness + confidence)
GET  /api/v1/person/{id}/graph          (relationship graph)

POST /api/v1/web/create                 (plant seed, start web)
GET  /api/v1/web/{id}                   (web summary + stats)
GET  /api/v1/web/{id}/graph             (full graph)

GET  /api/v1/stats                      (system-wide stats)
```

API key auth with per-key rate limiting. Usage tracked per key per day.

---

## 7. Build Order (Critical Path)

Build in this exact order. Each step independently testable before proceeding.

**API is split into two phases:** skeleton (Step 8, wires what exists) and completion (Step 14, wires all modules). This prevents building endpoints against modules that don't exist yet.

| Step | What | Modules | Test Gate |
|------|------|---------|-----------|
| 1 | Shared foundation: DB, all ORM models (base + new tables), schemas, event bus, Tor manager, quality engine, Alembic migrations | shared/ | Migrations run clean; models CRUD; events pub/sub; Tor circuits connect |
| 2 | Ingestion: universal parser, normalisers, validators | MODULE 1 | 50 sample inputs → correct type + normalised form |
| 3 | Enrichment: Sherlock, Holehe, theHarvester, people-search scrapers | MODULE 3 | Known email/phone → enriched result |
| 4 | Burner detection | MODULE 3b | Known VoIP number → CONFIRMED; known mobile → CLEAN |
| 5 | Crawlers: Tor-routed, Instagram actor first, then others | MODULE 2 | Public Instagram profile → structured data via Tor |
| 6 | Resolution: candidate gen, feature extract, merger | MODULE 4 | Two fragments for same person → merged canonical record |
| 7 | Scoring: relationship scorer, importance scorer | MODULE 5 | Person pair + evidence → correct score + tier |
| 8 | **API skeleton + Frontend:** FastAPI with all routers stubbed; React SearchBox + GraphView; WebSocket; search → ingestion → resolution → graph display works end-to-end | api/ + frontend/ | Type input → see resolved person + graph (behavioural/risk fields return null stubs) |
| 9 | Behavioural: gambling, crypto, criminal signals, local NLP | MODULE 6 | Person with gambling follows → gambling flag set |
| 10 | Dark web: paste monitor, onion crawler, crypto tracer | MODULE 10 | Known breach email → darkweb mention found |
| 11 | Credit risk scorer | MODULE 11 | Person with court + gambling signals → HIGH risk tier |
| 12 | Wealth intelligence | MODULE 12 | Person with employer + property → correct wealth band |
| 13 | Daemon: expansion scheduler, re-crawl, freshness controller | MODULE 7 | Plant seed → web grows autonomously; stale data re-queued |
| 14 | **API completion + Alerts + Export:** Wire all module endpoints (behavioural, darkweb, credit-risk, wealth, quality); Telegram bot; PDF dossier; all endpoints return real data | api/ + MODULE 8 + MODULE 9 | All API endpoints return real data; PDF dossier generated; Telegram alert delivered |

### Migration Strategy

All tables — base spec tables AND new tables from this document — are created in a **single initial migration**: `001_initial_schema.py`.

New tables added by this design doc (not in base spec):
- `burner_assessments`
- `darkweb_mentions`
- `crypto_wallets`
- `crypto_transactions`
- `credit_risk_assessments`
- `wealth_assessments`
- `data_quality_log`
- `freshness_queue`

All ORM models live in `shared/models/`. One Alembic migration captures the full schema. Future changes get `002_`, `003_`, etc.

---

## 7b. Event Bus — Complete Event Table

Extends the base spec event table with events for all new modules.

**Base spec events (unchanged):**

| Event | Publisher | Subscribers |
|-------|-----------|-------------|
| `seed.parsed` | MODULE 1 | MODULE 2, MODULE 7 |
| `data.scraped` | MODULE 2 | MODULE 4, MODULE 3 |
| `person.resolved` | MODULE 4 | MODULE 5, MODULE 6, MODULE 7 |
| `person.updated` | MODULE 4 | MODULE 5, MODULE 6, MODULE 8 |
| `relationship.created` | MODULE 4 | MODULE 5, MODULE 7, frontend WS |
| `relationship.scored` | MODULE 5 | MODULE 7, MODULE 8, frontend WS |
| `behaviour.profiled` | MODULE 6 | MODULE 8, frontend WS |
| `alert.created` | MODULE 8 | frontend WS, Telegram, email |
| `web.person_added` | MODULE 7 | frontend WS, stats |
| `web.merged` | MODULE 7 | MODULE 8, frontend WS |
| `crawl.completed` | MODULE 2 | MODULE 7, stats |
| `crawl.failed` | MODULE 2 | MODULE 8, MODULE 7 |

**New events from this design doc:**

| Event | Publisher | Subscribers |
|-------|-----------|-------------|
| `burner.assessed` | MODULE 3b | MODULE 11, MODULE 8, frontend WS |
| `darkweb.mention_found` | MODULE 10 | MODULE 11, MODULE 8, frontend WS |
| `darkweb.crypto_flagged` | MODULE 10 | MODULE 11, MODULE 6, MODULE 8 |
| `credit_risk.assessed` | MODULE 11 | MODULE 8, frontend WS, data broker API |
| `wealth.assessed` | MODULE 12 | MODULE 8, frontend WS, data broker API |
| `freshness.stale` | MODULE 7 | MODULE 7 (re-queues crawl), MODULE 8 |

---

## 8. Infrastructure

```yaml
services:
  postgres:        # PostgreSQL 16 + AGE extension + pgvector
  dragonfly:       # Redis-compatible cache + event bus
  meilisearch:     # Full-text search
  tor-1:           # Tor instance 1
  tor-2:           # Tor instance 2
  tor-3:           # Tor instance 3
  api:             # FastAPI
  daemon:          # Growth daemon
  worker:          # Scrapy/Crawlee workers (scale horizontally)
  frontend:        # React (Vite dev server or nginx)
```

All on Docker Compose. Dev overrides in `docker-compose.dev.yml`. Runs on existing ASUS server at 100.67.202.94 (`/data/docker-root`).

---

## 9. Key Design Constraints

1. **Modular above all else.** No module imports another module's internals. Only shared/ and the module's own public interface.
2. **Simplified within each module.** Each file does one thing. No god files.
3. **Robust over fast.** Retry logic, error handling, and graceful degradation everywhere. A failed spider does not crash the daemon.
4. **Quality tracked on everything.** No bare inserts without quality metadata.
5. **Tor-first, no exceptions.** No spider, actor, or enricher fires a request without routing through Tor or the configured proxy override.
6. **No CSAM.** The dark web crawler explicitly skips any .onion site known to host child abuse material. Maintained blocklist.
7. **Passive only.** System observes and indexes. Never interacts with criminal markets, never joins private criminal networks.
