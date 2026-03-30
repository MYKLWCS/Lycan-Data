# Phase 1: Data Access & Cloudflare Bypass - Research

**Researched:** 2026-03-30
**Domain:** Web scraping anti-bot bypass, people-search data aggregation, OSINT data sourcing
**Confidence:** MEDIUM

## Summary

The primary blocker for Phase 1 is Cloudflare Enterprise protection on high-value people-search sites (WhitePages, FastPeopleSearch, TruePeopleSearch). The codebase already has a layered bypass stack: `httpx` (plain HTTP) -> `curl_cffi` (TLS fingerprint impersonation) -> FlareSolverr (headless Chrome challenge solver) -> `patchright` (stealth Playwright). However, FlareSolverr is effectively deprecated and its CAPTCHA solvers are nonfunctional as of January 2026. Cloudflare Enterprise uses per-customer ML models that adapt to each site's traffic, making generic bypass increasingly unreliable.

The realistic path forward combines three strategies: (1) Replace FlareSolverr with Byparr (Camoufox-based, FlareSolverr-compatible API, actively maintained) or CloudflareBypassForScraping (DrissionPage-based, server mode with Docker), (2) Upgrade curl_cffi impersonation targets from chrome124 to latest chrome/safari, and (3) Diversify data sources by adding crawlers for sites with weaker or no Cloudflare protection (ThatsThem already exists, add IDCrawl, FreePeopleSearch, Unmask, and enhance google_people_search). For profile photos, Gravatar API is free and already has a crawler; Instagram/Facebook require stealth browser approaches that are already wired in.

**Primary recommendation:** Replace FlareSolverr with Byparr (Docker drop-in, uses Camoufox Firefox stealth). Upgrade curl_cffi to latest version with `impersonate="chrome"` (auto-latest). Add 3-4 alternative people-search crawlers for sites with lighter protection. This multi-layered approach maximizes data yield without any paid services.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DATA-01 | Crawlers bypass Cloudflare Enterprise on people-search sites using free methods | Byparr replaces FlareSolverr; curl_cffi upgrade; CloudflareBypassForScraping as fallback; Camoufox already in codebase |
| DATA-02 | Phone numbers discovered from name searches via working data sources | ThatsThem, ZabaSearch already exist; add IDCrawl, FreePeopleSearch; enhance google_people_search with more search engines |
| DATA-03 | Addresses discovered from name searches via working data sources | Same sites as DATA-02 all return address data; ThatsThem is strongest free source |
| DATA-04 | Profile photos captured from all social crawlers that find them | Gravatar already implemented; Instagram/Facebook crawlers exist with patchright; add GitHub avatar extraction |
</phase_requirements>

## Standard Stack

### Core (Already in Codebase)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| curl_cffi | 0.15+ (upgrade from current) | TLS fingerprint impersonation for HTTP requests | Impersonates Chrome/Safari at TLS level; bypasses JA3 fingerprinting |
| patchright | latest | Stealth Playwright fork for browser automation | Patches CDP leaks, automation flags; 67% headless detection reduction |
| camoufox | latest | Firefox-based stealth browser | C++ level fingerprint spoofing; 0% headless detection; passes Cloudflare Turnstile |
| BeautifulSoup4 | 4.x | HTML parsing | Already used across all crawlers |
| httpx | 0.28+ | Base HTTP client | Already the foundation; lightweight, async |

### New Additions
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Byparr | 2.1.0 | FlareSolverr replacement (Camoufox + FastAPI) | Docker sidecar; drop-in replacement on port 8191 |
| CloudflareBypassForScraping | latest | DrissionPage-based CF bypass server | Secondary bypass; server mode on port 8000; MIT license |
| libphonenumber (phonenumbers) | 8.x | Phone number parsing/validation | Validate discovered phone numbers; no API key needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Byparr | Solvearr | Solvearr is ARCHIVED (May 2025), no longer maintained |
| Byparr | flare-bypasser | Uses zendriver/Chrome; Byparr's Camoufox is harder to detect |
| CloudflareBypassForScraping | nodriver | nodriver is good but DrissionPage avoids webdriver detection entirely |
| Camoufox | undetected-chromedriver | UC's success rate has dropped significantly; open-source evasions are targeted |

**Installation:**
```bash
# Upgrade curl_cffi
pip install --upgrade curl_cffi

# Phone validation (no API key)
pip install phonenumbers

# Byparr via Docker (replaces FlareSolverr)
# In docker-compose.yml, replace flaresolverr service with:
# byparr:
#   image: ghcr.io/thephaseless/byparr:latest
#   ports: ["8191:8191"]
#   restart: unless-stopped

# CloudflareBypassForScraping (optional secondary bypass)
# docker run -p 8000:8000 ghcr.io/sarperavci/cloudflarebypassforscraping:latest
```

## Architecture Patterns

### Bypass Cascade (Ordered by Resource Cost)

The existing fallback chain is good but needs updating:

```
Request arrives
    |
    v
1. curl_cffi (impersonate="chrome")     # Cheapest: no browser, TLS-only
    |-- Success? Return data
    |-- Blocked? Continue
    v
2. Byparr/FlareSolverr API (port 8191)  # Medium: headless Camoufox
    |-- Success? Return data
    |-- Blocked? Continue
    v
3. Patchright stealth browser            # Expensive: full browser + stealth
    |-- Success? Return data
    |-- Blocked? Continue
    v
4. Camoufox (Firefox stealth)            # Most expensive: custom Firefox build
    |-- Success? Return data
    |-- All failed? Return error
```

### Pattern 1: Multi-Source People Search
**What:** Instead of depending on a single Cloudflare-protected site, query multiple weaker-protected sources in parallel and merge results.
**When to use:** Always for name-based people lookups.
**Example:**
```python
# Fan out to multiple sources simultaneously
sources = [
    "people_thatsthem",      # FlareSolverr/curl_cffi (Cloudflare but lighter)
    "people_zabasearch",     # FlareSolverr/curl_cffi
    "google_people_search",  # DuckDuckGo API + Bing (no Cloudflare)
    "idcrawl",               # New: lighter protection
    "freepeoplesearch",      # New: public records aggregator
]
# Dispatch all, merge results by name similarity
```

### Pattern 2: Bypass Tier Escalation per Site
**What:** Each crawler specifies which bypass tiers to try in order, based on the target site's known protection level.
**When to use:** When adding or modifying people-search crawlers.
**Example:**
```python
class WhitepagesCrawler(PlaywrightCrawler):
    # Known: Cloudflare Enterprise - needs heavy bypass
    bypass_chain = ["byparr", "camoufox", "patchright"]
    proxy_tier = "residential"  # Tor IPs are blocked

class ThatsThem(FlareSolverrCrawler):
    # Known: Cloudflare standard - curl_cffi often works
    bypass_chain = ["curl_cffi", "byparr"]
    proxy_tier = "tor"
```

### Pattern 3: Cookie Persistence for CF-Protected Sites
**What:** Once a Cloudflare challenge is solved, cache the cf_clearance cookie and reuse it for subsequent requests to the same domain.
**When to use:** For any Cloudflare-protected site where you make multiple requests.
**Example:**
```python
# After Byparr/CloudflareBypass solves the challenge:
# 1. Extract cf_clearance cookie from response
# 2. Store in Redis/Garnet with domain key and TTL (typically 30 min)
# 3. Subsequent requests to same domain attach the cookie via curl_cffi/httpx
# 4. Only re-solve when cookie expires or gets a 403
```

### Anti-Patterns to Avoid
- **Single-source dependency:** Never rely on WhitePages alone. It has the strongest Cloudflare Enterprise. Always have 3+ alternative sources.
- **Tor for Cloudflare sites:** Tor exit nodes are mass-blocked by Cloudflare. Set `proxy_tier = "residential"` or `"direct"` for CF-protected targets.
- **Re-solving challenges on every request:** Cache cf_clearance cookies. Solving challenges is slow (5-15 seconds per solve).
- **Headless Chrome for everything:** Use curl_cffi first (50ms vs 5000ms). Only escalate to browser when TLS-only bypass fails.
- **Hardcoded impersonate versions:** Use `impersonate="chrome"` not `impersonate="chrome124"` -- curl_cffi auto-resolves to latest.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cloudflare challenge solving | Custom JS evaluator | Byparr / CloudflareBypassForScraping | Challenge format changes constantly; these projects track updates |
| TLS fingerprint matching | Custom TLS config | curl_cffi with impersonate | Fingerprint databases are complex; curl_cffi maintains them |
| Phone number validation | Regex-only matching | `phonenumbers` library (Google libphonenumber) | Handles international formats, carrier lookup, all edge cases |
| Browser fingerprint spoofing | navigator.webdriver patches | Camoufox (C++ level patches) | JS-level patches are detectable; C++ level is not |
| Cookie management across sessions | File-based cookie jar | Redis/Garnet with TTL | Shared across workers, auto-expiry, atomic operations |

**Key insight:** Cloudflare's detection evolves weekly. Any hand-rolled bypass solution will break within days. Using actively-maintained open-source projects (Byparr, curl_cffi, Camoufox) that track these changes is the only sustainable free approach.

## Common Pitfalls

### Pitfall 1: FlareSolverr is Dead
**What goes wrong:** FlareSolverr's CAPTCHA solvers are nonfunctional as of January 2026. Cloudflare Enterprise challenges time out or loop.
**Why it happens:** FlareSolverr uses undetected-chromedriver which Cloudflare now specifically targets. The project is effectively unmaintained.
**How to avoid:** Replace FlareSolverr container with Byparr (same port 8191, compatible API). Byparr uses Camoufox (Firefox) which Cloudflare has fewer signatures for.
**Warning signs:** FlareSolverr logs showing repeated timeout errors, challenge not solved within 60s.

### Pitfall 2: Tor Exit Nodes Are Blocked
**What goes wrong:** All three people-search crawlers (whitepages, fastpeoplesearch, truepeoplesearch) use `requires_tor = True` and `tor_instance = TorInstance.TOR2`. Cloudflare blocks known Tor exit IPs.
**Why it happens:** Tor exit node IP lists are public. Cloudflare maintains blocklists.
**How to avoid:** Set `requires_tor = False` and `proxy_tier = "direct"` for Cloudflare-protected sites when using Byparr (which handles its own fingerprinting). Or use residential proxies when available.
**Warning signs:** Every request returns "access denied" or "blocked" page title.

### Pitfall 3: curl_cffi Using Outdated Fingerprint
**What goes wrong:** Current code uses `_IMPERSONATE = "chrome124"` which is from early 2024. Cloudflare flags old browser versions.
**Why it happens:** Chrome 124 is 2+ years old. Cloudflare's fingerprint database knows the TLS signature is suspicious when paired with a current User-Agent.
**How to avoid:** Change to `_IMPERSONATE = "chrome"` (auto-resolves to latest) or explicitly use `"chrome131"` or newer.
**Warning signs:** curl_cffi requests get 403 responses that regular browsers don't.

### Pitfall 4: Aggressive Rate Limiting Triggers Bans
**What goes wrong:** Scraping 5+ CF-protected sites simultaneously from the same IP triggers IP-level bans.
**Why it happens:** Cloudflare correlates requests across its customer sites. Same IP hitting multiple CF sites = obvious bot.
**How to avoid:** Stagger requests (current rate_limit settings are good at 0.5 req/s). Use different proxy tiers for different sites. Add 2-4 second random delays.
**Warning signs:** Getting blocked on Site B immediately after successfully scraping Site A.

### Pitfall 5: People-Search Sites Change HTML Structure
**What goes wrong:** Card selectors (`div.card-block`, `div[data-testid='person-card']`) break silently, returning empty results instead of errors.
**Why it happens:** Sites redesign frequently. CSS class names change without notice.
**How to avoid:** Validate parsed results have minimum expected fields (name at minimum). Log warnings when card count is 0 but page content is > 1000 bytes (indicates selector mismatch). Add fallback selectors.
**Warning signs:** Crawler returns `found=True` but `results=[]` consistently.

## Code Examples

### Upgrade curl_cffi Impersonation
```python
# modules/crawlers/curl_base.py - CHANGE
class CurlCrawler(HttpxCrawler):
    # OLD: _IMPERSONATE = "chrome124"
    _IMPERSONATE = "chrome"  # Auto-resolves to latest available (currently chrome145)
```

### Byparr Docker Compose (Replace FlareSolverr)
```yaml
# docker-compose.yml - Replace the flaresolverr service
  byparr:
    image: ghcr.io/thephaseless/byparr:latest
    container_name: lycan-byparr
    ports:
      - "8191:8191"
    restart: unless-stopped
    environment:
      - LOG_LEVEL=info
    # Note: Byparr API is compatible with FlareSolverr
    # No code changes needed in flaresolverr_base.py
```

### CloudflareBypassForScraping as Secondary Bypass
```python
# New base class: modules/crawlers/cfbypass_base.py
"""
Secondary Cloudflare bypass using CloudflareBypassForScraping server.
Runs as Docker sidecar on port 8000. Uses DrissionPage (not detected as webdriver).
"""
import httpx
import logging

logger = logging.getLogger(__name__)

CF_BYPASS_URL = "http://cfbypass:8000"

async def cf_bypass_get(url: str, proxy: str | None = None) -> str | None:
    """Get page HTML via CloudflareBypassForScraping server mode."""
    try:
        headers = {"x-hostname": url.split("//")[1].split("/")[0]}
        if proxy:
            headers["x-proxy"] = proxy
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.get(f"{CF_BYPASS_URL}/html?url={url}", headers=headers)
            if resp.status_code == 200:
                return resp.text
    except Exception as exc:
        logger.warning("CF bypass server failed for %s: %s", url, exc)
    return None
```

### New IDCrawl People-Search Crawler
```python
# modules/crawlers/idcrawl.py
"""
IDCrawl - free people search aggregating social profiles.
URL: https://www.idcrawl.com/{name}
Light protection, usually no Cloudflare challenge.
"""
from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

@register("idcrawl")
class IDCrawlCrawler(CurlCrawler):
    platform = "idcrawl"
    category = CrawlerCategory.PEOPLE
    rate_limit = RateLimit(requests_per_second=0.3, burst_size=2, cooldown_seconds=3.0)
    source_reliability = 0.55
    requires_tor = False  # No Cloudflare Enterprise

    async def scrape(self, identifier: str) -> CrawlerResult:
        name = identifier.strip().replace(" ", "-").lower()
        url = f"https://www.idcrawl.com/{name}"
        resp = await self.get(url)
        if not resp or resp.status_code != 200:
            return self._result(identifier, found=False)
        # Parse social profile links, phone, email from response
        # (HTML parsing implementation here)
        ...
```

### Cookie Caching for CF-Protected Sites
```python
# shared/cf_cookie_cache.py
"""Cache Cloudflare clearance cookies in Garnet (Redis) to avoid re-solving."""
import json
import logging
from shared.redis_client import redis_client

logger = logging.getLogger(__name__)
CF_COOKIE_TTL = 1800  # 30 minutes

async def get_cf_cookies(domain: str) -> dict | None:
    """Retrieve cached CF cookies for domain."""
    raw = await redis_client.get(f"cf_cookies:{domain}")
    return json.loads(raw) if raw else None

async def set_cf_cookies(domain: str, cookies: dict) -> None:
    """Cache CF cookies for domain with TTL."""
    await redis_client.set(f"cf_cookies:{domain}", json.dumps(cookies), ex=CF_COOKIE_TTL)
    logger.debug("Cached CF cookies for %s (TTL %ds)", domain, CF_COOKIE_TTL)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| FlareSolverr (undetected-chromedriver) | Byparr (Camoufox Firefox) | Mid-2025 | FlareSolverr CAPTCHA solvers broken; Byparr actively maintained |
| curl_cffi chrome99-124 | curl_cffi chrome145 / auto-latest | Ongoing | Old fingerprints flagged; use `impersonate="chrome"` for auto-latest |
| Puppeteer stealth / UC driver | Camoufox (C++ patched Firefox) | 2025 | Chromium-based stealth increasingly detected; Firefox less targeted |
| Playwright stealth JS patches | Patchright (CDP leak patches) | 2024 | JS-level patches detectable; CDP isolation is lower-level |
| JA3 fingerprint matching only | JA3 + HTTP/2 + HTTP/3 fingerprinting | 2025 | Cloudflare now checks HTTP/2 SETTINGS frames and priority trees |
| Single people-search source | Multi-source fanout + merge | Ongoing | No single free source is reliable; diversity is the strategy |

**Deprecated/outdated:**
- **FlareSolverr:** CAPTCHA solvers nonfunctional since Jan 2026. Replace with Byparr.
- **puppeteer-extra-stealth:** No longer maintained as of Feb 2025.
- **Solvearr:** Repository archived May 2025.
- **undetected-chromedriver:** Success rate dropped significantly; Cloudflare targets its patterns.
- **curl_cffi chrome124:** Two years old, suspicious when paired with modern User-Agent strings.

## People-Search Site Assessment

| Site | Cloudflare Level | Current Crawler | Status | Difficulty |
|------|-----------------|-----------------|--------|------------|
| WhitePages | Enterprise | whitepages.py | Blocked | HARD - heaviest CF protection |
| FastPeopleSearch | Enterprise | fastpeoplesearch.py | Blocked | HARD - US-only + CF |
| TruePeopleSearch | Enterprise | truepeoplesearch.py | Blocked | HARD - US-only + CF |
| ThatsThem | Standard CF | people_thatsthem.py | Working (with curl_cffi) | MEDIUM |
| ZabaSearch | Standard CF | people_zabasearch.py | Working (with curl_cffi) | MEDIUM |
| Spokeo | Enterprise | spokeo.py | Likely blocked | HARD - paid data behind paywall too |
| PeekYou | Standard | peekyou.py | Working (with patchright) | MEDIUM |
| Radaris | Minimal | radaris.py | Working | EASY |
| IDCrawl | None/minimal | NOT YET | Needs crawler | EASY |
| FreePeopleSearch | Unknown | NOT YET | Needs crawler | EASY-MEDIUM |
| FamilyTreeNow | Unknown | familytreenow.py | Needs testing | MEDIUM |
| Google/DuckDuckGo/Bing | None | google_people_search.py | Working | EASY |

**Strategy:** Focus effort on making ThatsThem, ZabaSearch, PeekYou, and Radaris reliable (they have lighter protection). Add IDCrawl and FreePeopleSearch (lighter or no CF). For WhitePages/FastPeopleSearch/TruePeopleSearch, implement Byparr bypass but accept lower success rates. The data from 5+ lighter sources combined exceeds what any single Enterprise-CF site provides.

## Profile Photo Sources

| Source | Method | API Key? | Reliability |
|--------|--------|----------|-------------|
| Gravatar | SHA256(email) -> REST API | No (100 req/hr unauthenticated) | HIGH for tech users |
| GitHub | `/users/{username}` -> avatar_url | No | HIGH for developers |
| Instagram | Patchright browser scrape | No | MEDIUM (anti-bot) |
| Facebook | Patchright browser scrape | No | LOW (heavy anti-scraping) |
| Twitter/X | Patchright browser scrape | No | MEDIUM |
| LinkedIn | Patchright browser scrape | No | LOW (blocks aggressively) |
| PeekYou | Aggregates social links | No | MEDIUM |

## Open Questions

1. **Byparr API compatibility depth**
   - What we know: Port 8191, documented as FlareSolverr compatible
   - What's unclear: Whether the exact JSON request/response format matches flaresolverr_base.py's expectations
   - Recommendation: Test Byparr container locally with existing flaresolverr_base.py code before deploying. May need minor response parsing adjustments.

2. **CloudflareBypassForScraping reliability on people-search sites**
   - What we know: DrissionPage-based, server mode with Docker, MIT license
   - What's unclear: Whether it handles Cloudflare Enterprise on WhitePages specifically
   - Recommendation: Deploy as secondary bypass. Test against each target site individually.

3. **Byparr license compatibility**
   - What we know: GPL-3.0 license
   - What's unclear: Whether GPL-3.0 is acceptable per project constraints (allowed: MIT, Apache 2.0, BSD, GPL-2/3, LGPL-3)
   - Recommendation: GPL-3.0 IS listed as acceptable. Safe to use.

4. **FreePeopleSearch.com and IDCrawl scraping viability**
   - What we know: Both listed as free people search alternatives
   - What's unclear: Exact HTML structure, Cloudflare protection level, data quality
   - Recommendation: Test manually in browser first, then implement curl_cffi crawlers.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | pyproject.toml |
| Quick run command | `pytest tests/test_crawlers/test_people_search.py -x -q` |
| Full suite command | `pytest tests/ -x -q --timeout=120` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-01 | Byparr replaces FlareSolverr; bypass chain works | integration | `pytest tests/test_crawlers/test_flaresolverr_base.py -x` | Yes (needs update for Byparr) |
| DATA-01 | curl_cffi uses latest impersonate target | unit | `pytest tests/test_crawlers/test_curl_base.py -x` | Yes (needs assertion update) |
| DATA-02 | Phone numbers extracted from people-search results | unit | `pytest tests/test_crawlers/test_people_search.py -x` | Yes |
| DATA-03 | Addresses extracted from people-search results | unit | `pytest tests/test_crawlers/test_people_search.py -x` | Yes |
| DATA-04 | Profile photos captured from social crawlers | unit | `pytest tests/test_crawlers/test_social.py -x` | Yes |

### Sampling Rate
- **Per task commit:** `pytest tests/test_crawlers/test_people_search.py tests/test_crawlers/test_flaresolverr_base.py tests/test_crawlers/test_curl_base.py -x -q`
- **Per wave merge:** `pytest tests/test_crawlers/ -x -q --timeout=120`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_crawlers/test_byparr_integration.py` -- covers Byparr replacing FlareSolverr (DATA-01)
- [ ] `tests/test_crawlers/test_cf_cookie_cache.py` -- covers cookie persistence for CF sites
- [ ] `tests/test_crawlers/test_idcrawl.py` -- covers new IDCrawl crawler (DATA-02, DATA-03)
- [ ] Update `tests/test_crawlers/test_curl_base.py` -- assert impersonate="chrome" not "chrome124"

## Sources

### Primary (HIGH confidence)
- [curl_cffi GitHub](https://github.com/lexiforest/curl_cffi) - Impersonation targets, version info, HTTP/3 support
- [Byparr GitHub](https://github.com/ThePhaseless/Byparr) - v2.1.0, Docker setup, GPL-3.0, Camoufox-based
- [CloudflareBypassForScraping GitHub](https://github.com/sarperavci/CloudflareBypassForScraping) - Server mode, DrissionPage, MIT license, Docker
- [Camoufox stealth docs](https://camoufox.com/stealth/) - C++ level fingerprint spoofing, 0% headless detection
- [Gravatar REST API docs](https://docs.gravatar.com/rest-api/) - Free profile/avatar lookup, SHA256 hash, 100 req/hr

### Secondary (MEDIUM confidence)
- [ScrapeOps Cloudflare bypass guide](https://scrapeops.io/web-scraping-playbook/how-to-bypass-cloudflare/) - Confirmed FlareSolverr limitations, Byparr recommendation
- [ZenRows Patchright guide](https://www.zenrows.com/blog/patchright) - 67% headless detection reduction, CDP leak patches
- [ZenRows FlareSolverr guide](https://www.zenrows.com/blog/flaresolverr) - Confirmed CAPTCHA solvers nonfunctional Jan 2026
- [roundproxies Byparr guide](https://roundproxies.com/blog/byparr/) - Docker setup, API details, 1.1GB image size
- [TechRadar people search ranking](https://www.techradar.com/best/best-free-people-search-finder-services-and-engines-of-year) - Site difficulty/quality assessment

### Tertiary (LOW confidence)
- [roundproxies Patchright alternatives](https://roundproxies.com/blog/best-patchright-alternatives/) - Claims nodriver outperforms patchright on CF (needs validation)
- [proxies.sx Camoufox vs Nodriver comparison](https://www.proxies.sx/blog/ai-browser-automation-camoufox-nodriver-2026) - Comparative benchmarks (unverified)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Libraries verified via GitHub repos and official docs
- Architecture: MEDIUM - Bypass patterns are well-established but CF Enterprise effectiveness varies by site
- Pitfalls: HIGH - FlareSolverr deprecation and Tor blocking are well-documented facts
- People-search site assessment: MEDIUM - Protection levels inferred from search results and codebase comments, not live-tested

**Research date:** 2026-03-30
**Valid until:** 2026-04-15 (Cloudflare updates detection monthly; bypass landscape shifts fast)
