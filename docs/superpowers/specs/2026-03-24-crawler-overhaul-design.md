# Crawler Overhaul — Full Bypass Stack + Data Cascade Fix
**Date:** 2026-03-24
**Status:** Approved
**Scope:** Option C — New base crawlers, FlareSolverr sidecar, bug fixes, new sources

---

## Problem Statement

The platform has 130+ crawlers but is returning almost no data. Five distinct root causes:

1. **TLS fingerprinting** — `httpx` presents a Python TLS signature. Cloudflare, DataDome, and Akamai detect it immediately and block. Affects all data broker sites (WhitePages, ThatsThem, FastPeopleSearch, TruePeopleSearch).
2. **Playwright stealth is too thin** — Only masks the `webdriver` flag. Modern bot detection (PerimeterX, DataDome, Meta/Instagram) checks canvas fingerprint, WebGL, audio context, font enumeration, Chrome plugin lists. Social crawlers return empty pages.
3. **Stale user agents** — Chrome 122 (March 2024) agents in `playwright_base.py`. Sites cross-check Chrome version against TLS signature — mismatch = instant bot flag. Current Chrome is 130+.
4. **Pivot cap too low** — `_MAX_PIVOTS = 3` in `pivot_enricher.py` limits cascade to 3 new identifiers per result. Each only fans to 4–10 platforms. The chain dies too early.
5. **Case sensitivity in identifier storage** — `identifiers` table has `UniqueConstraint` on `value` (raw string). `@JohnSmith` and `@johnsmith` create separate person records that never merge. The cascade runs twice and the results scatter.

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
       │  (SEC, NMLS, SAM, FAA, FEC, etc.)   No bot protection, fast
       │
       ├─ Cloudflare-protected sites ──────► FlareSolverrCrawler (new)
       │  (WhitePages, ThatsThem,             Sends request to local FlareSolverr
       │   FastPeopleSearch, ZabaSearch,      Docker sidecar which solves CF
       │   TruePeopleSearch, Pastebin)        challenge, returns clean HTML
       │
       ├─ PerimeterX / DataDome sites ─────► CamoufoxCrawler (new)
       │  (Instagram, LinkedIn, Twitter,      Firefox-based stealth browser
       │   TikTok, Snapchat)                  beats canvas, WebGL, audio checks
       │
       └─ General HTTP (non-CF) ───────────► CurlCrawler (new)
          (APIs, news, crypto explorers,      curl_cffi impersonates Chrome TLS
           court records, breach DBs)         fingerprint — indistinguishable
                                              from real browser at network level
       │
       ▼
  CrawlerResult.found=True
       │
       ▼
  IngestionDaemon → aggregate_result → pivot_from_result (cap: 15)
                                              │
                                              ▼
                                   extracted email / phone / full_name
                                              │
                                              ▼
                                   dispatch_job() × pivot platforms
                                   (recursive, depth-limited)
```

---

## Section 1: New Python Packages

All free and open source. Added to `pyproject.toml` under `[tool.poetry.dependencies]`.

| Package | Purpose | Why |
|---|---|---|
| `curl_cffi` | TLS fingerprint impersonation | Impersonates Chrome 130 at TLS handshake level. Cloudflare can't distinguish it from a real browser. Drop-in async client. |
| `patchright` | Stealth Playwright fork | Drop-in replacement for `playwright`. Patches canvas, WebGL, fonts, audio, navigator properties. Maintained fork of `playwright-stealth`. |
| `camoufox[geoip]` | Firefox stealth browser | Firefox-based, undetected by PerimeterX and DataDome. Different fingerprint profile from Chrome — complements Patchright. |
| `fake-useragent` | Current UA database | Pulls real-world user agent distribution from web. Current Chrome 130+, Firefox 125+. Replaces static list in `playwright_base.py`. |
| `primp` | Hardened HTTP client | Rust-based Python binding. Browser-level TLS + HTTP/2 fingerprint. Fallback when curl_cffi is unavailable. |
| `maigret` | Username across 2000+ sites | Replaces/supplements Sherlock. Covers 10x more platforms, returns structured JSON. |
| `socialscan` | Email + username registration check | Async, fast, checks 30+ platforms simultaneously. |
| `phoneinfoga` | Phone OSINT CLI | Carrier, country, line type, OSINT sources. Wraps CLI output into structured data. |

---

## Section 2: New Base Crawlers

Three new abstract base classes in `modules/crawlers/`. All extend `BaseCrawler`. Fully composable — subclasses just inherit and call `self.get()` or `async with self.page()` as before.

### 2.1 `CurlCrawler` (`curl_base.py`)

Extends `HttpxCrawler` interface, swaps transport to `curl_cffi`.

```python
# Usage (identical to HttpxCrawler):
class MyCrawler(CurlCrawler):
    async def scrape(self, identifier):
        resp = await self.get("https://example.com/search?q=" + identifier)
```

- Impersonates `chrome130` TLS fingerprint by default
- Inherits rate limiter + circuit breaker from `HttpxCrawler`
- Falls back to plain `httpx` if `curl_cffi` import fails (graceful degradation)
- SOCKS5 Tor proxy support via `curl_cffi` native proxy arg

### 2.2 `FlareSolverrCrawler` (`flaresolverr_base.py`)

Sends requests through the local FlareSolverr HTTP API (port 8191). FlareSolverr spins up a headless Chrome instance, solves the Cloudflare JS challenge, and returns the rendered HTML + cookies.

```python
# Usage:
class MyCrawler(FlareSolverrCrawler):
    async def scrape(self, identifier):
        html, cookies = await self.fs_get("https://www.whitepages.com/name/" + identifier)
        soup = BeautifulSoup(html, "html.parser")
```

- `fs_get(url)` → returns `(html: str, cookies: dict)`
- `fs_post(url, data)` → returns `(html: str, cookies: dict)`
- Configurable `FLARESOLVERR_URL` env var (default: `http://localhost:8191`)
- Health check on startup — falls back to `CurlCrawler` if FlareSolverr is unreachable
- Inherits rate limiter + circuit breaker
- Session persistence: reuses FlareSolverr sessions for cookie-carrying requests

### 2.3 `CamoufoxCrawler` (`camoufox_base.py`)

Firefox-based stealth browser. Different fingerprint profile from Chrome — PerimeterX and DataDome use separate detection trees for Chrome vs Firefox. Passing Firefox fingerprint checks requires a real Firefox engine.

```python
# Usage (identical to PlaywrightCrawler):
class MyCrawler(CamoufoxCrawler):
    async def scrape(self, identifier):
        async with self.page("https://www.instagram.com/" + identifier) as page:
            content = await page.content()
```

- Uses `camoufox` async context manager
- Injects `fake-useragent` Firefox UAs (current versions)
- Tor proxy support via camoufox proxy arg
- Automatic block detection + circuit rotation (same as `PlaywrightCrawler`)
- GeoIP data bundled via `camoufox[geoip]` — matches timezone/locale to exit IP

### 2.4 `PlaywrightCrawler` upgrade (`playwright_base.py`)

Swap `playwright` → `patchright` (drop-in). Update static user agent list to Chrome 130+. Add `fake-useragent` rotation for dynamic UAs.

Changes:
- `from patchright.async_api import ...` replaces `from playwright.async_api import ...`
- User agent list updated + supplemented by `fake-useragent` at runtime
- Add viewport jitter (±50px), extra `navigator` property patches

---

## Section 3: Bug Fixes

### 3.1 Case sensitivity — identifier deduplication

**Problem:** `UniqueConstraint("type", "value")` is case-sensitive. `@JohnSmith` ≠ `@johnsmith`.

**Fix:** Add database migration to:
1. Drop `uq_identifier_type_value` constraint
2. Add `uq_identifier_type_normalized` constraint on `(type, normalized_value)`
3. Ensure `normalized_value` is always populated on write (currently nullable)

Also fix `search.py` `_auto_detect_type()` — call `.lower()` before regex matching so Instagram handles starting with capital letters are detected correctly.

### 3.2 Pivot cap — `pivot_enricher.py`

**Problem:** `_MAX_PIVOTS = 3` starves the cascade.

**Fix:**
- Raise `_MAX_PIVOTS` to `15`
- Add per-type caps: email → 6 platforms, phone → 4 platforms, full_name → 12 platforms
- Add `instagram_handle`, `twitter_handle`, `linkedin_url` as new pivot types (currently ignored)
- Expand `_PIVOT_PLATFORMS` to include all platforms from `SEED_PLATFORM_MAP`

### 3.3 Instagram handle as pivot type

Currently `pivot_enricher.py` only pivots on `email`, `phone`, `full_name`. When a WhitePages result includes an Instagram handle, it's ignored. Fix: add `instagram_handle`, `twitter_handle`, `linkedin_url`, `domain` as pivot types with appropriate platform lists.

---

## Section 4: Crawler Migration

Which crawlers move to which new base class:

| Base Class | Crawlers |
|---|---|
| `FlareSolverrCrawler` | `whitepages`, `truepeoplesearch`, `fastpeoplesearch`, `people_thatsthem`, `people_zabasearch`, `paste_pastebin`, `paste_ghostbin`, `paste_psbdmp` |
| `CamoufoxCrawler` | `instagram`, `linkedin`, `twitter`, `tiktok`, `snapchat`, `discord`, `pinterest`, `facebook` |
| `CurlCrawler` | `email_hibp`, `email_holehe`, `email_emailrep`, `email_breach`, `cyber_shodan`, `cyber_virustotal`, `cyber_greynoise`, `cyber_abuseipdb`, `cyber_urlscan`, `cyber_crt`, `crypto_bitcoin`, `crypto_ethereum`, `crypto_blockchair`, `financial_crunchbase`, `news_search`, `news_wikipedia`, `domain_whois` |
| `HttpxCrawler` (unchanged) | All gov/public record crawlers: `gov_*`, `sanctions_*`, `court_*`, `bankruptcy_pacer`, `company_*`, `mortgage_*`, `vehicle_*`, `geo_*`, `public_*` |
| `PlaywrightCrawler` (upgraded) | `youtube`, `reddit`, `mastodon`, `twitch`, `steam`, `darkweb_torch`, `darkweb_ahmia` |

---

## Section 5: New Crawlers / Sources

All free/open source. Each follows the `@register("platform")` pattern.

| Crawler File | Platform Key | Source | Base Class |
|---|---|---|---|
| `username_maigret.py` | `username_maigret` | Maigret CLI (2000+ sites) | `BaseCrawler` (CLI wrapper) |
| `email_socialscan.py` | `email_socialscan` | socialscan library | `BaseCrawler` (async lib) |
| `phone_phoneinfoga.py` | `phone_phoneinfoga` | phoneinfoga CLI | `BaseCrawler` (CLI wrapper) |
| `people_phonebook.py` | `people_phonebook` | PhoneBook.cz | `CurlCrawler` |
| `people_intelx.py` | `people_intelx` | IntelligenceX free API | `CurlCrawler` |
| `email_dehashed.py` | `email_dehashed` | DeHashed free search | `CurlCrawler` |

Add all 6 to `SEED_PLATFORM_MAP` in `search.py` under appropriate seed types. Add to `_PIVOT_PLATFORMS` in `pivot_enricher.py`.

---

## Section 6: FlareSolverr Docker Service

Add to `docker-compose.yml`:

```yaml
flaresolverr:
  image: ghcr.io/flaresolverr/flaresolverr:latest
  environment:
    LOG_LEVEL: info
    LOG_HTML: false
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

Add `FLARESOLVERR_URL=http://localhost:8191` to `.env.example`.

---

## Section 7: Hardening + Resilience

### Fallback chain per base class

Every new base class has a fallback:
```
FlareSolverrCrawler → CurlCrawler → HttpxCrawler (direct)
CamoufoxCrawler     → PlaywrightCrawler (Chrome)
CurlCrawler         → HttpxCrawler (direct)
```
If the preferred transport is blocked or unavailable, the crawler degrades automatically rather than returning empty.

### Health check on startup

`shared/health.py` (new) — checks FlareSolverr, Tor instances, Dragonfly, Postgres on startup. Logs which bypass layers are active. Dispatcher uses this to know which base classes are available.

### Per-domain transport registry

`shared/transport_registry.py` (new) — maps domains to preferred crawler base. Automatically upgrades a domain to `FlareSolverrCrawler` after 3 consecutive `BLOCKED` results from `CurlCrawler`. Downgraded after 24h to re-test. Persisted in Dragonfly.

### User agent freshness

`fake-useragent` fetches current UA distribution on first use, caches to disk. Crawlers call `ua.chrome` / `ua.firefox` rather than static strings. Updated automatically.

---

## Section 8: Normalisation Rules

All identifier normalisation applied at `search.py` entry point and `pivot_enricher.py` extraction:

| Type | Normalisation |
|---|---|
| All | `.strip().lower()` |
| Email | strip, lowercase, strip leading `@` if present |
| Phone | strip non-digits, add `+` prefix if 10+ digits |
| Username | strip, lowercase, strip leading `@` |
| Full name | strip, title-case for display, lowercase for storage |
| Domain | strip, lowercase, strip `www.` |
| Crypto wallet | strip, lowercase (ETH), preserve case (BTC bech32) |

---

## Implementation Order

1. **pyproject.toml** — add new packages, `poetry install`
2. **docker-compose.yml** — add FlareSolverr service
3. **`playwright_base.py`** — swap patchright, update UAs
4. **`curl_base.py`** — new `CurlCrawler`
5. **`flaresolverr_base.py`** — new `FlareSolverrCrawler`
6. **`camoufox_base.py`** — new `CamoufoxCrawler`
7. **`shared/health.py`** — startup health check
8. **`shared/transport_registry.py`** — per-domain transport tracking
9. **DB migration** — fix identifier uniqueness constraint
10. **`search.py`** — normalize before type-detect, fix case
11. **`pivot_enricher.py`** — raise cap, add new pivot types, expand platforms
12. **Migrate existing crawlers** — update base class imports for the 30+ crawlers in migration table
13. **New crawlers** — maigret, socialscan, phoneinfoga, phonebook, intelx, dehashed
14. **`search.py` SEED_PLATFORM_MAP** — add new platform keys
15. **Tests** — unit tests for each new base class + integration smoke test

---

## Files Created / Modified

**New files:**
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

**Modified files:**
- `pyproject.toml`
- `docker-compose.yml`
- `modules/crawlers/playwright_base.py`
- `modules/crawlers/instagram.py`
- `modules/crawlers/linkedin.py`
- `modules/crawlers/twitter.py`
- `modules/crawlers/tiktok.py`
- `modules/crawlers/snapchat.py`
- `modules/crawlers/discord.py`
- `modules/crawlers/pinterest.py`
- `modules/crawlers/facebook.py`
- `modules/crawlers/whitepages.py`
- `modules/crawlers/truepeoplesearch.py`
- `modules/crawlers/fastpeoplesearch.py`
- `modules/crawlers/people_thatsthem.py`
- `modules/crawlers/people_zabasearch.py`
- `modules/crawlers/paste_pastebin.py`
- `modules/crawlers/paste_ghostbin.py`
- `modules/crawlers/paste_psbdmp.py`
- `modules/crawlers/email_hibp.py`
- `modules/crawlers/email_holehe.py`
- `modules/crawlers/email_emailrep.py`
- `modules/crawlers/email_breach.py`
- `modules/crawlers/cyber_shodan.py`
- `modules/crawlers/cyber_virustotal.py`
- `modules/crawlers/cyber_greynoise.py`
- `modules/crawlers/cyber_abuseipdb.py`
- `modules/crawlers/cyber_urlscan.py`
- `modules/crawlers/cyber_crt.py`
- `modules/crawlers/crypto_bitcoin.py`
- `modules/crawlers/crypto_ethereum.py`
- `modules/crawlers/crypto_blockchair.py`
- `modules/crawlers/news_search.py`
- `modules/crawlers/news_wikipedia.py`
- `modules/crawlers/domain_whois.py`
- `modules/pipeline/pivot_enricher.py`
- `api/routes/search.py`
