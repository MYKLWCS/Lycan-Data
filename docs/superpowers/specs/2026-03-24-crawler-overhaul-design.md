# Crawler Overhaul — Full Bypass Stack + Data Cascade Fix
**Date:** 2026-03-24
**Status:** Approved (v2 — spec review fixes applied)
**Scope:** Option C — New base crawlers, FlareSolverr sidecar, bug fixes, new sources

---

## Problem Statement

The platform has 130+ crawlers but is returning almost no data. Five distinct root causes:

1. **TLS fingerprinting** — `httpx` presents a Python TLS signature. Cloudflare, DataDome, and Akamai detect it immediately and block. Affects all data broker sites (WhitePages, ThatsThem, FastPeopleSearch, TruePeopleSearch).
2. **Playwright stealth is too thin** — Only masks the `webdriver` flag. Modern bot detection (PerimeterX, DataDome, Meta/Instagram) checks canvas fingerprint, WebGL, audio context, font enumeration, Chrome plugin lists. Social crawlers return empty pages.
3. **Stale user agents** — Chrome 122 (March 2024) agents in `playwright_base.py`. Sites cross-check Chrome version against TLS signature — mismatch = instant bot flag. Current Chrome is 130+.
4. **Pivot cap too low** — `_MAX_PIVOTS = 3` in `pivot_enricher.py` slices the extracted identifiers list before dispatch, capping the cascade at 3 total new identifier extractions per result. The chain dies too early.
5. **Case sensitivity in identifier storage** — `identifiers` table has `UniqueConstraint("type", "value")` (raw string). `@JohnSmith` and `@johnsmith` create separate person records that never merge.

---

## Architecture

```
Input (any identifier — name, email, phone, handle, IP, wallet)
       │
       ▼
  POST /search ─── normalize: strip + lowercase + type-detect
       │
       ▼
  SEED_PLATFORM_MAP → dispatch_job() × N platforms
       │
       ├─ Government / open APIs ──────────► HttpxCrawler (unchanged)
       │  (SEC, NMLS, SAM, FAA, FEC, etc.)
       │
       ├─ Cloudflare-protected sites ──────► FlareSolverrCrawler(CurlCrawler)
       │  (WhitePages, ThatsThem,             FlareSolverr Docker sidecar solves CF;
       │   FastPeopleSearch, Pastebin)        falls back to CurlCrawler if sidecar down
       │
       ├─ PerimeterX / DataDome sites ─────► CamoufoxCrawler
       │  (Instagram, LinkedIn, Twitter)      Firefox stealth browser; falls back to
       │                                      error result if camoufox unavailable
       │
       └─ General HTTP (non-CF) ───────────► CurlCrawler
          (APIs, breach DBs, crypto)          curl_cffi Chrome 130 TLS impersonation;
                                              falls back to httpx on import error
       │
       ▼
  CrawlerResult.found=True → IngestionDaemon → aggregate_result
                                              │
                                              ▼
                                        pivot_from_result
                                        total cap: 30 jobs/call
                                        per-type: email→6, phone→4,
                                                  name→12, handle→6, domain→4
                                              │
                                              ▼
                                   dispatch_job() × pivot platforms (recursive)
```

---

## Section 1: New Python Packages

All free and open source. Added to `pyproject.toml`.

| Package | Purpose | Why |
|---|---|---|
| `curl_cffi` | TLS fingerprint impersonation | Impersonates Chrome 130 at TLS handshake level — Cloudflare cannot distinguish it from a real browser. Primary HTTP transport for non-government sites. |
| `patchright` | Stealth Playwright fork | Drop-in for `playwright`. Patches canvas, WebGL, fonts, audio, navigator. Requires `patchright install chromium`. |
| `camoufox[geoip]` | Firefox stealth browser | Undetected by PerimeterX and DataDome. Different fingerprint from Chrome — complements Patchright. |
| `fake-useragent` | Current UA database | Real-world Chrome 130+, Firefox 125+ distribution. Replaces static list. |
| `maigret` | Username across 2000+ sites | CLI tool. 10x more coverage than Sherlock. Returns structured JSON. Wrapped with 120s timeout + 50-result cap. |
| `socialscan` | Email + username registration | Python async library. Checks 30+ platforms simultaneously. No subprocess needed. |
| `phoneinfoga` | Phone OSINT | CLI tool. Carrier, country, line type. Wrapped with 60s timeout. |

**`primp` is not included.** `curl_cffi` covers the same use case with better ecosystem support.

---

## Section 2: New Base Crawlers

Three new classes in `modules/crawlers/`. All extend `BaseCrawler`. Fully composable — subclasses change only the parent class import; the `scrape()` method is untouched. Fallback is internal to each base class, invisible to subclasses.

### 2.1 `CurlCrawler` (`curl_base.py`)

Inherits from `HttpxCrawler`. Overrides `_client()` to build a `curl_cffi.AsyncSession` with `impersonate="chrome130"`. Inherits `get()`, `post()`, rate limiter, and circuit breaker from `HttpxCrawler` unchanged. If `curl_cffi` is not importable at runtime, logs a warning and delegates to `super()._client()` (plain httpx transport).

**Fallback chain:** curl_cffi chrome130 → httpx direct

### 2.2 `FlareSolverrCrawler` (`flaresolverr_base.py`)

Inherits from `CurlCrawler`. Adds `fs_get(url)` and `fs_post(url, data)` methods. These POST to the FlareSolverr HTTP API at `FLARESOLVERR_URL` (env var, default `http://localhost:8191`). FlareSolverr runs a headless Chrome, solves the CF JS challenge, and returns rendered HTML + cookies.

If FlareSolverr is unreachable, `fs_get` transparently delegates to `super().get()` (CurlCrawler) and returns `(response.text, {})`. No subclass code changes needed.

**Health check caching:** The FlareSolverr reachability result is cached at **class level** (shared across all instances), with a 60-second TTL on negative results. After 60 seconds of unavailability, the next `fs_get` call re-probes. A positive result (reachable) is cached indefinitely until a connection error occurs mid-request, which resets to a negative cache entry. This prevents repeated health probes on every request while allowing recovery detection within one minute.

Session persistence: FlareSolverr sessions are created per-domain and reused to carry cookies through challenge flows.

**Fallback chain:** FlareSolverr → CurlCrawler (chrome130) → httpx direct

### 2.3 `CamoufoxCrawler` (`camoufox_base.py`)

Inherits from `BaseCrawler`. Provides `async with self.page(url) as page:` context manager using `camoufox.AsyncNewBrowser`. `camoufox[geoip]` aligns timezone/locale to Tor exit IP automatically. Uses `fake-useragent` Firefox UAs. Block detection mirrors `PlaywrightCrawler.is_blocked()`. On block, calls `rotate_circuit()`.

If `camoufox` is not importable, the context manager raises `ImportError`, caught by `BaseCrawler.run()`, returned as `error="camoufox_unavailable"` result.

**Fallback chain:** camoufox Firefox → error result (subclasses may override `_fallback_page()`)

### 2.4 `PlaywrightCrawler` upgrade (`playwright_base.py`)

Swap: `from patchright.async_api import Browser, BrowserContext, Page, async_playwright`. API is identical. Update static `USER_AGENTS` to Chrome 130+ and supplement with `fake-useragent`. Add viewport jitter (±50px) and extra `navigator` property patches.

**CI / Dockerfile must add:** `patchright install chromium`

---

## Section 3: Bug Fixes

### 3.1a Deduplication — DB migration (critical, deploy atomically with 3.1b)

**Problem:** `UniqueConstraint("type", "value")` is case-sensitive. The lookup in `search.py` already uses `normalized_value` correctly — the constraint is what allows the duplicate insert to succeed.

**Migration steps:**
1. `UPDATE identifiers SET normalized_value = lower(value) WHERE normalized_value IS NULL` (backfill)
2. Drop `uq_identifier_type_value`
3. Add `uq_identifier_type_normalized` on `(type, normalized_value)`
4. Make `normalized_value` NOT NULL

### 3.1b Model update — `shared/models/identifier.py` (atomic with 3.1a)

Change `__table_args__` from `UniqueConstraint("type", "value", name="uq_identifier_type_value")` to `UniqueConstraint("type", "normalized_value", name="uq_identifier_type_normalized")`. If this is not done simultaneously with the migration, Alembic autogenerate will attempt to revert the constraint on the next run.

### 3.1c Type detection — `search.py` `_auto_detect_type()`

Separate fix (not deduplication): add `.lower()` at top of `_auto_detect_type()` before regex so uppercase-prefixed handles (`@JohnSmith`, `Instagram.com/X`) type-detect correctly. Minor correctness fix.

### 3.2 Pivot cap redesign + email extraction bug — `pivot_enricher.py`

**Problem 1:** `return found[:_MAX_PIVOTS]` in `_extract_pivots()` caps identifier types extracted, not job count. Meaningless to raise it since a result rarely has more than 3 distinct identifier types (email, phone, name).

**Problem 2:** Python operator precedence bug in the existing email extraction expression (lines 66-73). Due to the ternary `if/else` binding to the entire `or` chain rather than just the last clause, `email` evaluates to `None` whenever `data["emails"]` is not a list — even when `data["email"]`, `data["email_address"]`, or `data["contact_email"]` are populated. This silently drops email pivots from most crawler results.

**Fix:**
- Remove `return found[:_MAX_PIVOTS]` slice from `_extract_pivots()` entirely — return all found types (naturally bounded at ~3)
- Add `_MAX_JOBS_PER_CALL = 30` total job ceiling in `pivot_from_result()` applied to the running `jobs_queued` counter
- `_PIVOT_PLATFORMS` list lengths remain the per-type caps: email→6, phone→4, full_name→12
- Fix email extraction parenthesization so `data.get("emails", [None])[0]` is the ternary subject, not the entire `or` chain:
  ```
  email = (
      data.get("email")
      or data.get("email_address")
      or data.get("contact_email")
      or (data.get("emails", [None])[0] if isinstance(data.get("emails"), list) else None)
  )
  ```

### 3.3 New pivot types — `pivot_enricher.py`

Add extraction for:
- `instagram_handle` — from `data.get("instagram")`, `data.get("instagram_handle")`, URL pattern extraction
- `twitter_handle` — from `data.get("twitter")`, `data.get("twitter_handle")`
- `linkedin_url` — from `data.get("linkedin")`, `data.get("linkedin_url")`
- `domain` — from email domain part and explicit `data.get("domain")` fields

Platform lists for new types:
```
instagram_handle → instagram, username_maigret, username_sherlock
twitter_handle   → twitter, username_maigret, username_sherlock
linkedin_url     → linkedin
domain           → domain_whois, cyber_crt, cyber_urlscan, cyber_wayback
```

### 3.4 `SeedType` extension — `shared/constants.py`

Add to `SeedType` enum:
```
INSTAGRAM_HANDLE = "instagram_handle"
TWITTER_HANDLE   = "twitter_handle"
LINKEDIN_URL     = "linkedin_url"
```

**These are pivot-only types — they are not valid seed inputs from the API.** A user will not type an Instagram handle as a seed; they will type the username and it will be detected as `USERNAME`. The new types exist so that when a WhitePages result contains an Instagram URL, the pivot enricher can store and dispatch it correctly as `instagram_handle` rather than conflating it with `USERNAME`.

Because they are pivot-only, `_auto_detect_type()` does NOT need new detection branches for these types. They will never appear as seed input values at the API layer. `SEED_PLATFORM_MAP` must still have entries for them (so that when a pivot-created identifier is dispatched back through `dispatch_job`, the correct crawlers are selected).

`SEED_PLATFORM_MAP` entries for new types:
```
SeedType.INSTAGRAM_HANDLE → ["instagram", "username_maigret", "username_sherlock"]
SeedType.TWITTER_HANDLE   → ["twitter", "username_maigret", "username_sherlock"]
SeedType.LINKEDIN_URL     → ["linkedin"]
```

---

## Section 4: Crawler Migration

Only the parent class import changes in each file. `scrape()` methods are untouched.

| New Base Class | Crawlers |
|---|---|
| `FlareSolverrCrawler` | `whitepages`, `truepeoplesearch`, `fastpeoplesearch`, `people_thatsthem`, `people_zabasearch`, `paste_pastebin`, `paste_ghostbin`, `paste_psbdmp` |
| `CamoufoxCrawler` | `instagram`, `linkedin`, `twitter`, `tiktok`, `snapchat`, `discord`, `pinterest`, `facebook` |
| `CurlCrawler` | `email_hibp`, `email_holehe`, `email_emailrep`, `email_breach`, `cyber_shodan`, `cyber_virustotal`, `cyber_greynoise`, `cyber_abuseipdb`, `cyber_urlscan`, `cyber_crt`, `crypto_bitcoin`, `crypto_ethereum`, `crypto_blockchair`, `financial_crunchbase`, `news_search`, `news_wikipedia`, `domain_whois` |
| `HttpxCrawler` (unchanged) | All `gov_*`, `sanctions_*`, `court_*`, `bankruptcy_pacer`, `company_*`, `mortgage_*`, `vehicle_*`, `geo_*`, `public_*` |
| `PlaywrightCrawler` (patchright upgrade) | `youtube`, `reddit`, `mastodon`, `twitch`, `steam`, `darkweb_torch`, `darkweb_ahmia` |

---

## Section 5: New Crawlers / Sources

All free/open source. Follow `@register("platform")` pattern.

| File | Platform Key | Base | Notes |
|---|---|---|---|
| `username_maigret.py` | `username_maigret` | `BaseCrawler` | CLI wrapper. 120s timeout via `asyncio.wait_for`. Cap output to first 50 matches. |
| `email_socialscan.py` | `email_socialscan` | `BaseCrawler` | Python async library, no CLI needed. |
| `phone_phoneinfoga.py` | `phone_phoneinfoga` | `BaseCrawler` | CLI wrapper. 60s timeout via `asyncio.wait_for`. |
| `people_phonebook.py` | `people_phonebook` | `CurlCrawler` | PhoneBook.cz email/domain search. |
| `people_intelx.py` | `people_intelx` | `CurlCrawler` | IntelligenceX public search (no key required for basic). |
| `email_dehashed.py` | `email_dehashed` | `CurlCrawler` | DeHashed public search endpoint. |

CLI wrapper pattern: use `asyncio.wait_for(proc.communicate(), timeout=N)`. On `TimeoutError`, kill proc and return `error="timeout"` result. Parse stdout as JSON. All wrappers must pass identifier as a positional argument (never interpolated into a shell string) to prevent injection.

**`SEED_PLATFORM_MAP` entries for new crawlers:**

| Crawler | SeedType keys |
|---|---|
| `username_maigret` | `USERNAME`, `INSTAGRAM_HANDLE`, `TWITTER_HANDLE` |
| `email_socialscan` | `EMAIL`, `USERNAME` |
| `phone_phoneinfoga` | `PHONE` |
| `people_phonebook` | `FULL_NAME`, `EMAIL`, `DOMAIN` |
| `people_intelx` | `FULL_NAME`, `EMAIL`, `USERNAME`, `DOMAIN` |
| `email_dehashed` | `EMAIL`, `FULL_NAME` |

All 6 also added to `_PIVOT_PLATFORMS` under their primary identifier type.

---

## Section 6: FlareSolverr Docker Service

```yaml
flaresolverr:
  image: ghcr.io/flaresolverr/flaresolverr:latest
  environment:
    LOG_LEVEL: info
    LOG_HTML: "false"
    CAPTCHA_SOLVER: none
    TZ: America/New_York
  ports:
    - "8191:8191"
  healthcheck:
    test: ["CMD-SHELL", "curl -sf http://localhost:8191/health || exit 1"]
    interval: 10s
    timeout: 5s
    retries: 5
  restart: unless-stopped
```

Add to `.env.example`: `FLARESOLVERR_URL=http://localhost:8191`

---

## Section 7: Hardening + Resilience

### Canonical fallback chain

```
FlareSolverrCrawler.fs_get()  → CurlCrawler.get() (chrome130) → httpx direct
CamoufoxCrawler.page()        → error result (camoufox_unavailable)
CurlCrawler.get()             → httpx direct
PlaywrightCrawler.page()      → error (Playwright must be installed)
HttpxCrawler.get()            → error (base level)
```

Fallback is always internal to the base class method. Subclasses call `self.get()` or `self.fs_get()` — they never implement fallback.

### `shared/health.py` — startup health check

Checks: FlareSolverr HTTP endpoint, 3x Tor SOCKS ports, Dragonfly ping, Postgres connection. Logs a summary of active bypass layers. Non-fatal — missing services degrade gracefully.

### `shared/transport_registry.py` — per-domain transport tracking

Dragonfly-backed. Tracks consecutive BLOCKED count, last transport used, last tested timestamp per domain. After 3 consecutive BLOCKs from `CurlCrawler`, promotes domain to prefer `FlareSolverrCrawler`. Resets after 24h. Consulted by `FlareSolverrCrawler.fs_get()` to skip FlareSolverr for domains where curl already works.

### User agent freshness

`fake-useragent` fetches current distribution on first use, caches to disk. Base classes call `ua.chrome` / `ua.firefox`. No more static strings.

---

## Section 8: Normalisation Rules

Applied at `search.py` entry and `pivot_enricher.py` extraction:

| Type | Rule |
|---|---|
| All | `.strip().lower()` first |
| Email | strip, lowercase, strip leading `@` |
| Phone | strip non-digits, add `+` prefix if 10+ digits |
| Username / handle | strip, lowercase, strip leading `@` |
| Full name | lowercase for `normalized_value`; title-case for `value` display |
| Domain | strip, lowercase, strip leading `www.` |
| Crypto wallet | strip, lowercase ETH; preserve case BTC bech32 |
| IP address | strip only |

---

## Implementation Order

Steps 9a and 9b must deploy atomically (migration runs first, app code restarts after).

1. `pyproject.toml` — add packages, run `poetry install`
2. `docker-compose.yml` — add `flaresolverr` service
3. `playwright_base.py` — swap to patchright; add `patchright install chromium` to CI and Dockerfile
4. `modules/crawlers/curl_base.py` — new `CurlCrawler`
5. `modules/crawlers/flaresolverr_base.py` — new `FlareSolverrCrawler(CurlCrawler)`
6. `modules/crawlers/camoufox_base.py` — new `CamoufoxCrawler`
7. `shared/health.py` — startup health check
8. `shared/transport_registry.py` — per-domain transport tracking
9a. DB migration — backfill, swap constraint to `(type, normalized_value)`, NOT NULL
9b. `shared/models/identifier.py` — update `__table_args__` (atomic with 9a)
10. `shared/constants.py` — add `INSTAGRAM_HANDLE`, `TWITTER_HANDLE`, `LINKEDIN_URL` to `SeedType`
11. `api/routes/search.py` — normalize before type-detect, add new SeedType entries to `SEED_PLATFORM_MAP`
12. `modules/pipeline/pivot_enricher.py` — remove slice, add `_MAX_JOBS_PER_CALL`, add new pivot types
13. Migrate existing crawlers — update base class import for all 30+ crawlers in migration table
14. New crawlers — `username_maigret`, `email_socialscan`, `phone_phoneinfoga`, `people_phonebook`, `people_intelx`, `email_dehashed`
15. Tests — unit tests for each new base class; fallback smoke tests; pivot cascade integration test

---

## Files Created / Modified

**New:**
- `modules/crawlers/curl_base.py`
- `modules/crawlers/flaresolverr_base.py`
- `modules/crawlers/camoufox_base.py`
- `modules/crawlers/username_maigret.py`
- `modules/crawlers/email_socialscan.py`
- `modules/crawlers/phone_phoneinfoga.py`
- `modules/crawlers/people_phonebook.py`
- `modules/crawlers/people_intelx.py`
- `modules/crawlers/email_dehashed.py`
- `shared/health.py`
- `shared/transport_registry.py`
- `migrations/versions/XXXX_fix_identifier_case_uniqueness.py`

**Modified:**
- `pyproject.toml`
- `docker-compose.yml`
- `shared/constants.py`
- `shared/models/identifier.py`
- `modules/crawlers/playwright_base.py`
- `modules/crawlers/instagram.py` + `linkedin.py` + `twitter.py` + `tiktok.py` + `snapchat.py` + `discord.py` + `pinterest.py` + `facebook.py`
- `modules/crawlers/whitepages.py` + `truepeoplesearch.py` + `fastpeoplesearch.py` + `people_thatsthem.py` + `people_zabasearch.py`
- `modules/crawlers/paste_pastebin.py` + `paste_ghostbin.py` + `paste_psbdmp.py`
- `modules/crawlers/email_hibp.py` + `email_holehe.py` + `email_emailrep.py` + `email_breach.py`
- `modules/crawlers/cyber_shodan.py` + `cyber_virustotal.py` + `cyber_greynoise.py` + `cyber_abuseipdb.py` + `cyber_urlscan.py` + `cyber_crt.py`
- `modules/crawlers/crypto_bitcoin.py` + `crypto_ethereum.py` + `crypto_blockchair.py`
- `modules/crawlers/news_search.py` + `news_wikipedia.py` + `domain_whois.py` + `financial_crunchbase.py`
- `modules/pipeline/pivot_enricher.py`
- `api/routes/search.py`
