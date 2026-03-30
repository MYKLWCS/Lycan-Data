---
phase: 01-data-access
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - docker-compose.yml
  - docker-compose.dev.yml
  - modules/crawlers/curl_base.py
  - modules/crawlers/flaresolverr_base.py
  - shared/cf_cookie_cache.py
  - modules/crawlers/whitepages.py
  - modules/crawlers/fastpeoplesearch.py
  - modules/crawlers/truepeoplesearch.py
  - modules/crawlers/people_thatsthem.py
  - modules/crawlers/people_zabasearch.py
autonomous: true
requirements: [DATA-01]

must_haves:
  truths:
    - "Byparr container runs on port 8191 and responds to FlareSolverr-compatible API requests"
    - "curl_cffi uses auto-latest Chrome fingerprint instead of stale chrome124"
    - "CF-protected people-search crawlers use direct/residential proxy instead of Tor"
    - "CF clearance cookies cached in Garnet to avoid re-solving on every request"
  artifacts:
    - path: "docker-compose.yml"
      provides: "Byparr service replacing FlareSolverr"
      contains: "ghcr.io/thephaseless/byparr"
    - path: "modules/crawlers/curl_base.py"
      provides: "Updated TLS impersonation"
      contains: '_IMPERSONATE = "chrome"'
    - path: "shared/cf_cookie_cache.py"
      provides: "CF cookie persistence in Garnet"
      exports: ["get_cf_cookies", "set_cf_cookies"]
  key_links:
    - from: "modules/crawlers/flaresolverr_base.py"
      to: "docker-compose.yml byparr service"
      via: "HTTP POST to port 8191"
      pattern: "flaresolverr_url.*8191"
    - from: "modules/crawlers/whitepages.py"
      to: "shared/cf_cookie_cache.py"
      via: "cookie reuse before browser launch"
      pattern: "get_cf_cookies|set_cf_cookies"
---

<objective>
Infrastructure bypass upgrades: Replace dead FlareSolverr with Byparr, fix curl_cffi fingerprint, disable Tor for CF-protected sites, implement CF cookie caching.

Purpose: Every people-search crawler currently fails because (a) FlareSolverr is dead, (b) curl_cffi uses a 2-year-old fingerprint, and (c) Tor exit nodes are blocked by Cloudflare. Fixing these three infrastructure problems unblocks all downstream crawler work.

Output: Working Byparr sidecar, updated curl_cffi impersonation, CF cookie cache module, and all existing people-search crawlers switched off Tor.
</objective>

<execution_context>
@/home/wolf/.claude/get-shit-done/workflows/execute-plan.md
@/home/wolf/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phase-1/01-RESEARCH.md

@modules/crawlers/curl_base.py
@modules/crawlers/flaresolverr_base.py
@modules/crawlers/whitepages.py
@modules/crawlers/fastpeoplesearch.py
@modules/crawlers/truepeoplesearch.py
@modules/crawlers/people_thatsthem.py
@modules/crawlers/people_zabasearch.py
@docker-compose.yml
@shared/cf_cookie_cache.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Replace FlareSolverr with Byparr and fix curl_cffi fingerprint</name>
  <files>docker-compose.yml, docker-compose.dev.yml, modules/crawlers/curl_base.py, modules/crawlers/flaresolverr_base.py</files>
  <action>
1. In docker-compose.yml, replace the `flaresolverr` service block (lines ~177-191) with Byparr:
   - Change image from `ghcr.io/flaresolverr/flaresolverr:latest` to `ghcr.io/thephaseless/byparr:latest`
   - Change container_name to `lycan-byparr`
   - Keep port mapping `8191:8191`
   - Remove `CAPTCHA_SOLVER: none` env var (Byparr does not use it)
   - Keep `LOG_LEVEL: info` and `TZ` env vars
   - Keep healthcheck (Byparr supports /health endpoint on same port)
   - Keep restart policy
   - Update the comment line from "FlareSolverr" to "Byparr (Cloudflare bypass — FlareSolverr compatible API)"
   - IMPORTANT: Do NOT rename the service key from `flaresolverr` yet — other services reference it via Docker DNS (e.g., `FLARESOLVERR_URL: http://flaresolverr:8191/v1`). Renaming the service key would break those references. Keep the service key as `flaresolverr` but update the image and comments.

2. Apply the same image swap in docker-compose.dev.yml if it has a flaresolverr service.

3. In modules/crawlers/curl_base.py:
   - Change `_IMPERSONATE = "chrome124"` to `_IMPERSONATE = "chrome"` (auto-resolves to latest)
   - Update the class docstring from "Chrome 124" to "latest Chrome" references
   - Update the module docstring similarly

4. In modules/crawlers/flaresolverr_base.py:
   - Update the module docstring to note "Byparr (FlareSolverr-compatible)" instead of just "FlareSolverr"
   - Update the fallback chain comment from "chrome124" to "chrome (latest)"
   - No code changes needed — Byparr uses the same JSON API format ({cmd: "request.get", url, maxTimeout})
  </action>
  <verify>
    <automated>grep -q 'byparr' docker-compose.yml && grep -q '_IMPERSONATE = "chrome"' modules/crawlers/curl_base.py && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>docker-compose.yml uses Byparr image on port 8191, curl_cffi impersonates "chrome" (auto-latest), all docstrings updated</done>
</task>

<task type="auto">
  <name>Task 2: Disable Tor on CF-protected crawlers and implement CF cookie cache</name>
  <files>modules/crawlers/whitepages.py, modules/crawlers/fastpeoplesearch.py, modules/crawlers/truepeoplesearch.py, modules/crawlers/people_thatsthem.py, modules/crawlers/people_zabasearch.py, shared/cf_cookie_cache.py</files>
  <action>
1. Create shared/cf_cookie_cache.py (or update if stub exists):
   ```python
   """Cache Cloudflare clearance cookies in Garnet (Redis) to avoid re-solving challenges."""
   import json
   import logging
   from shared.cache import get_cache

   logger = logging.getLogger(__name__)
   CF_COOKIE_TTL = 1800  # 30 minutes — cf_clearance cookies typically last 30 min

   async def get_cf_cookies(domain: str) -> dict | None:
       """Retrieve cached CF cookies for a domain. Returns None if expired or missing."""
       try:
           r = await get_cache()
           raw = await r.get(f"cf_cookies:{domain}")
           return json.loads(raw) if raw else None
       except Exception:
           return None

   async def set_cf_cookies(domain: str, cookies: dict) -> None:
       """Cache CF cookies for domain with 30-min TTL."""
       try:
           r = await get_cache()
           await r.set(f"cf_cookies:{domain}", json.dumps(cookies), ex=CF_COOKIE_TTL)
           logger.debug("Cached CF cookies for %s (TTL %ds)", domain, CF_COOKIE_TTL)
       except Exception:
           logger.warning("Failed to cache CF cookies for %s", domain)
   ```

2. In whitepages.py:
   - Change `requires_tor = True` to `requires_tor = False`
   - Remove `tor_instance = TorInstance.TOR2` line
   - Remove the `from shared.tor import TorInstance` import if no longer used
   - Add import: `from shared.cf_cookie_cache import get_cf_cookies, set_cf_cookies`
   - In the scrape() method, before the FlareSolverr/Playwright attempt, try using cached CF cookies via curl_cffi first:
     - Call `cookies = await get_cf_cookies("whitepages.com")`
     - If cookies exist, attempt a curl_cffi GET with those cookies attached
     - If that returns valid content (len > 1000 and no "access denied" in title), use it
   - After a successful FlareSolverr/Playwright solve, extract cf_clearance cookie and call `set_cf_cookies("whitepages.com", cookies_dict)`

3. In fastpeoplesearch.py:
   - Change `requires_tor = True` to `requires_tor = False`
   - Remove tor_instance line and unused TorInstance import

4. In truepeoplesearch.py:
   - Change `requires_tor = True` to `requires_tor = False`
   - Remove tor_instance line and unused TorInstance import

5. In people_thatsthem.py:
   - Change `requires_tor = True` to `requires_tor = False`
   - Remove `tor_instance = TorInstance.TOR1` line
   - Remove the `from shared.tor import TorInstance` import
   - ThatsThem uses standard CF, curl_cffi with auto-latest Chrome should handle it without Tor

6. In people_zabasearch.py:
   - If it has `requires_tor = True`, change to `requires_tor = False`
   - Remove tor_instance and TorInstance import if present
  </action>
  <verify>
    <automated>grep -rn "requires_tor = True" modules/crawlers/whitepages.py modules/crawlers/fastpeoplesearch.py modules/crawlers/truepeoplesearch.py modules/crawlers/people_thatsthem.py 2>/dev/null | wc -l | grep -q "^0$" && python -c "from shared.cf_cookie_cache import get_cf_cookies, set_cf_cookies; print('PASS')" && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>All 5 people-search crawlers have requires_tor=False, CF cookie cache module importable with get/set functions, whitepages.py uses cookie cache before browser escalation</done>
</task>

</tasks>

<verification>
1. `grep -c 'byparr' docker-compose.yml` returns >= 1
2. `grep '_IMPERSONATE' modules/crawlers/curl_base.py` shows "chrome" not "chrome124"
3. `grep -rn 'requires_tor = True' modules/crawlers/whitepages.py modules/crawlers/fastpeoplesearch.py modules/crawlers/truepeoplesearch.py modules/crawlers/people_thatsthem.py` returns nothing
4. `python -c "from shared.cf_cookie_cache import get_cf_cookies, set_cf_cookies"` succeeds
5. `pytest tests/test_crawlers/test_curl_base.py tests/test_crawlers/test_flaresolverr_base.py -x -q --timeout=60` passes
</verification>

<success_criteria>
- Byparr image in docker-compose.yml on port 8191 with FlareSolverr-compatible API
- curl_cffi impersonation set to "chrome" (auto-latest)
- All CF-protected people-search crawlers have requires_tor=False
- CF cookie cache module exists and is importable
- Existing test suite passes (no regressions)
</success_criteria>

<output>
After completion, create `.planning/phases/01-data-access/01-data-access-01-SUMMARY.md`
</output>

---
---

---
phase: 01-data-access
plan: 02
type: execute
wave: 2
depends_on: [01]
files_modified:
  - modules/crawlers/idcrawl.py
  - modules/crawlers/freepeoplesearch.py
  - modules/crawlers/__init__.py
autonomous: true
requirements: [DATA-02, DATA-03]

must_haves:
  truths:
    - "IDCrawl crawler returns person cards with name, phone, and address data from idcrawl.com"
    - "FreePeopleSearch crawler returns person cards with phone and address data"
    - "Both crawlers registered via @register decorator and discoverable by the dispatcher"
  artifacts:
    - path: "modules/crawlers/idcrawl.py"
      provides: "IDCrawl people-search crawler"
      contains: '@register("idcrawl")'
    - path: "modules/crawlers/freepeoplesearch.py"
      provides: "FreePeopleSearch crawler"
      contains: '@register("freepeoplesearch")'
  key_links:
    - from: "modules/crawlers/idcrawl.py"
      to: "modules/crawlers/curl_base.py"
      via: "class inheritance"
      pattern: "class IDCrawlCrawler\\(CurlCrawler\\)"
    - from: "modules/crawlers/freepeoplesearch.py"
      to: "modules/crawlers/curl_base.py"
      via: "class inheritance"
      pattern: "class FreePeopleSearchCrawler\\(CurlCrawler\\)"
---

<objective>
Add two new people-search crawlers (IDCrawl, FreePeopleSearch) that target sites with lighter or no Cloudflare protection, providing alternative data sources for phone numbers and addresses.

Purpose: Multi-source diversification is the primary strategy per research — 5+ lighter sources combined exceed what any single Enterprise-CF site provides. These two sites have minimal protection and return phone/address data.

Output: Two new registered crawlers producing CrawlerResult with phone numbers and addresses extracted via BeautifulSoup parsing.
</objective>

<execution_context>
@/home/wolf/.claude/get-shit-done/workflows/execute-plan.md
@/home/wolf/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phase-1/01-RESEARCH.md

@modules/crawlers/curl_base.py
@modules/crawlers/people_thatsthem.py
@modules/crawlers/core/result.py
@modules/crawlers/core/models.py
@modules/crawlers/registry.py

<interfaces>
<!-- Follow the patterns from people_thatsthem.py — it's the canonical people-search crawler -->

From modules/crawlers/core/result.py:
```python
@dataclass
class CrawlerResult:
    platform: str
    identifier: str
    found: bool
    data: dict = field(default_factory=dict)
    error: str | None = None
    source_reliability: float = 0.5
```

From modules/crawlers/core/models.py:
```python
class CrawlerCategory(str, Enum):
    PEOPLE = "people"
    ...

@dataclass
class RateLimit:
    requests_per_second: float = 1.0
    burst_size: int = 5
    cooldown_seconds: float = 1.0
```

From modules/crawlers/registry.py:
```python
def register(name: str) -> Callable:  # Decorator — @register("crawler_name")
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create IDCrawl people-search crawler</name>
  <files>modules/crawlers/idcrawl.py</files>
  <action>
Create modules/crawlers/idcrawl.py following the people_thatsthem.py pattern:

1. URL pattern: `https://www.idcrawl.com/` + name slugified (spaces to hyphens, lowercase). For "John Smith" -> `https://www.idcrawl.com/john-smith`

2. Class structure:
   ```python
   @register("idcrawl")
   class IDCrawlCrawler(CurlCrawler):
       platform = "idcrawl"
       category = CrawlerCategory.PEOPLE
       rate_limit = RateLimit(requests_per_second=0.3, burst_size=2, cooldown_seconds=3.0)
       source_reliability = 0.55
       requires_tor = False  # No Cloudflare Enterprise
   ```

3. scrape() method:
   - Parse identifier using the same "Name|City,State" format as whitepages.py (use first-last only for URL, ignore location)
   - Build URL: lowercase, hyphenate spaces
   - GET via self.get(url) (inherits curl_cffi from CurlCrawler)
   - If response is None or non-200, return found=False
   - Parse HTML with BeautifulSoup

4. HTML parsing (_parse_idcrawl_results):
   - IDCrawl shows social profile links and sometimes phone/email
   - Look for result cards: `div.result`, `div.person`, or similar card containers
   - Extract: name (from h2/h3), social profile URLs (from anchor tags), phone numbers (from tel: links or phone-class elements), addresses (from address-class elements)
   - Return list of person dicts

5. Return CrawlerResult with: found=bool(results), persons=results, profile_url=url
  </action>
  <verify>
    <automated>python -c "from modules.crawlers.idcrawl import IDCrawlCrawler; c = IDCrawlCrawler(); assert c.platform == 'idcrawl'; assert c.requires_tor == False; print('PASS')"</automated>
  </verify>
  <done>IDCrawl crawler importable, registered as "idcrawl", extends CurlCrawler, requires_tor=False, has scrape() that parses person cards</done>
</task>

<task type="auto">
  <name>Task 2: Create FreePeopleSearch crawler</name>
  <files>modules/crawlers/freepeoplesearch.py</files>
  <action>
Create modules/crawlers/freepeoplesearch.py following the same pattern:

1. URL pattern: `https://www.freepeoplesearch.com/name/` + first-last slugified. For "John Smith" -> `https://www.freepeoplesearch.com/name/john-smith`

2. Class structure:
   ```python
   @register("freepeoplesearch")
   class FreePeopleSearchCrawler(CurlCrawler):
       platform = "freepeoplesearch"
       category = CrawlerCategory.PEOPLE
       rate_limit = RateLimit(requests_per_second=0.3, burst_size=2, cooldown_seconds=3.0)
       source_reliability = 0.50
       requires_tor = False
   ```

3. scrape() method:
   - Same identifier parsing as IDCrawl (Name|City,State format, use name part for URL)
   - GET via self.get(url)
   - Handle non-200 and None responses
   - Parse HTML for person result cards

4. HTML parsing (_parse_freepeoplesearch_results):
   - Public records aggregator — shows name, age, addresses, phone numbers, relatives
   - Look for person cards: `div.card`, `div.person-card`, `div[class*='result']`
   - Extract: name, age (regex from text), address (street + city + state), phone numbers, relatives
   - Use the phonenumbers library to validate extracted phone numbers:
     ```python
     import phonenumbers
     try:
         parsed = phonenumbers.parse(phone_text, "US")
         if phonenumbers.is_valid_number(parsed):
             phone = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
     except phonenumbers.NumberParseException:
         pass
     ```

5. Return CrawlerResult with persons list, profile_url
  </action>
  <verify>
    <automated>python -c "from modules.crawlers.freepeoplesearch import FreePeopleSearchCrawler; c = FreePeopleSearchCrawler(); assert c.platform == 'freepeoplesearch'; assert c.requires_tor == False; print('PASS')"</automated>
  </verify>
  <done>FreePeopleSearch crawler importable, registered as "freepeoplesearch", extends CurlCrawler, parses phone/address/name data, validates phones with phonenumbers library</done>
</task>

</tasks>

<verification>
1. `python -c "from modules.crawlers.idcrawl import IDCrawlCrawler"` succeeds
2. `python -c "from modules.crawlers.freepeoplesearch import FreePeopleSearchCrawler"` succeeds
3. Both crawlers appear in registry: `python -c "from modules.crawlers.registry import get_registry; r = get_registry(); assert 'idcrawl' in r; assert 'freepeoplesearch' in r; print('PASS')"`
4. `pytest tests/test_crawlers/ -x -q --timeout=120` passes (no regressions)
</verification>

<success_criteria>
- IDCrawl crawler registered and importable, extends CurlCrawler, requires_tor=False
- FreePeopleSearch crawler registered and importable, extends CurlCrawler, requires_tor=False
- Both crawlers parse person cards (name, phone, address) from HTML responses
- FreePeopleSearch validates phone numbers with phonenumbers library
- All existing tests pass
</success_criteria>

<output>
After completion, create `.planning/phases/01-data-access/01-data-access-02-SUMMARY.md`
</output>

---
---

---
phase: 01-data-access
plan: 03
type: execute
wave: 2
depends_on: [01]
files_modified:
  - modules/crawlers/github_profile.py
autonomous: true
requirements: [DATA-04]

must_haves:
  truths:
    - "GitHub crawler extracts avatar_url from user profiles and includes it in CrawlerResult"
    - "Social crawlers that find profile photos include photo URL in their result data"
  artifacts:
    - path: "modules/crawlers/github_profile.py"
      provides: "GitHub avatar extraction"
      contains: "avatar_url"
  key_links:
    - from: "modules/crawlers/github_profile.py"
      to: "https://api.github.com/users/{username}"
      via: "REST API GET"
      pattern: "api.github.com/users"
---

<objective>
Add profile photo capture to GitHub crawler (avatar_url from API) and verify existing social crawlers (Gravatar, Instagram, Facebook) include photo URLs in results.

Purpose: DATA-04 requires profile photos captured from all social crawlers that find them. Gravatar is already done. GitHub's API returns avatar_url for free with no auth. Existing patchright-based social crawlers (Instagram, Facebook) already have the browser infrastructure — just need to confirm photo extraction.

Output: GitHub crawler returns avatar_url, all photo-capable crawlers verified to include photo data in CrawlerResult.
</objective>

<execution_context>
@/home/wolf/.claude/get-shit-done/workflows/execute-plan.md
@/home/wolf/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phase-1/01-RESEARCH.md

@modules/crawlers/github_profile.py
@modules/crawlers/core/result.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add avatar extraction to GitHub crawler and audit social photo capture</name>
  <files>modules/crawlers/github_profile.py</files>
  <action>
1. Read modules/crawlers/github_profile.py to understand current implementation.

2. github_profile.py already extracts `avatar_url` at line 67. Verify it is included in the CrawlerResult data dict.
   - If `avatar_url` is in the data dict but not named `profile_photo_url`, add an alias: `data["profile_photo_url"] = data.get("avatar_url", "")`
   - If `avatar_url` is already in data dict, DATA-04 is satisfied for GitHub — just confirm and move on.

4. Verify Gravatar crawler (modules/crawlers/social_gravatar.py or similar):
   - Read it to confirm it already includes the avatar URL in results
   - If not, add `profile_photo_url` to its result data

5. Check Instagram/Facebook/Twitter crawlers (ls modules/crawlers/social_*.py):
   - For each social crawler that uses PlaywrightCrawler or CamoufoxCrawler:
   - Verify they extract profile photo URL when available
   - If a crawler already scrapes the profile page but skips the photo, add extraction:
     - Instagram: `meta[property='og:image']` or profile pic selector
     - Facebook: `meta[property='og:image']`
     - Twitter: `meta[property='og:image']` or avatar selector
   - Store consistently as `data["profile_photo_url"]`

6. If any social crawler does NOT have photo extraction and adding it requires more than 15 lines of changes, note it in the SUMMARY as future work — do not exceed scope.
  </action>
  <verify>
    <automated>python -c "from modules.crawlers.social_github import *; print('PASS')" && grep -q "profile_photo_url\|avatar_url" modules/crawlers/github_profile.py && echo "PHOTO_EXTRACTED" || echo "NEEDS_REVIEW"</automated>
  </verify>
  <done>GitHub crawler extracts avatar_url and stores as profile_photo_url in CrawlerResult data. Existing social crawlers audited for photo extraction — any gaps documented in SUMMARY.</done>
</task>

</tasks>

<verification>
1. `grep 'profile_photo_url\|avatar_url' modules/crawlers/github_profile.py` shows extraction
2. `pytest tests/test_crawlers/test_social.py -x -q --timeout=60` passes
3. `python -c "from modules.crawlers.social_github import *"` succeeds
</verification>

<success_criteria>
- GitHub crawler includes profile_photo_url in result data
- Gravatar confirmed to include avatar URL
- Social crawlers audited — photo extraction present or gap documented
- No test regressions
</success_criteria>

<output>
After completion, create `.planning/phases/01-data-access/01-data-access-03-SUMMARY.md`
</output>

---
---

---
phase: 01-data-access
plan: 04
type: execute
wave: 3
depends_on: [01, 02, 03]
files_modified:
  - tests/test_crawlers/test_byparr_integration.py
  - tests/test_crawlers/test_cf_cookie_cache.py
  - tests/test_crawlers/test_idcrawl.py
  - tests/test_crawlers/test_freepeoplesearch.py
autonomous: false
requirements: [DATA-01, DATA-02, DATA-03, DATA-04]

must_haves:
  truths:
    - "All new code has test coverage — Byparr integration, cookie cache, new crawlers"
    - "Full test suite (6005+ tests) passes without regressions"
    - "At least one CF-protected site returns person card data (not a Cloudflare block page)"
  artifacts:
    - path: "tests/test_crawlers/test_byparr_integration.py"
      provides: "Byparr API compatibility tests"
    - path: "tests/test_crawlers/test_cf_cookie_cache.py"
      provides: "CF cookie cache unit tests"
    - path: "tests/test_crawlers/test_idcrawl.py"
      provides: "IDCrawl crawler tests"
    - path: "tests/test_crawlers/test_freepeoplesearch.py"
      provides: "FreePeopleSearch crawler tests"
  key_links:
    - from: "tests/"
      to: "modules/crawlers/"
      via: "pytest imports"
      pattern: "from modules.crawlers"
---

<objective>
Write tests for all new code (Wave 0 gaps from research), run full regression suite, and do a live smoke test against real people-search sites to validate the bypass stack works end-to-end.

Purpose: Research identified 4 test gaps that need closing. The full 6005-test suite must pass. And the ultimate validation is a live request to a CF-protected site returning actual person data instead of a block page.

Output: 4 new test files, full suite green, live smoke test confirming bypass works.
</objective>

<execution_context>
@/home/wolf/.claude/get-shit-done/workflows/execute-plan.md
@/home/wolf/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/phase-1/01-RESEARCH.md
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Write unit tests for new modules and integration tests for Byparr</name>
  <files>tests/test_crawlers/test_byparr_integration.py, tests/test_crawlers/test_cf_cookie_cache.py, tests/test_crawlers/test_idcrawl.py, tests/test_crawlers/test_freepeoplesearch.py</files>
  <behavior>
    - test_cf_cookie_cache: get returns None when no cached cookie, set then get returns the cookie dict, TTL is set to 1800
    - test_byparr_integration: FlareSolverrCrawler.fs_get() sends correct JSON payload (cmd, url, maxTimeout), falls back to CurlCrawler when sidecar is down, parses Byparr response correctly (status, solution.response, solution.cookies)
    - test_idcrawl: IDCrawlCrawler registered as "idcrawl", category is PEOPLE, requires_tor is False, scrape() returns CrawlerResult with found=False on non-200 response
    - test_freepeoplesearch: FreePeopleSearchCrawler registered as "freepeoplesearch", category is PEOPLE, requires_tor is False, phone validation uses phonenumbers library
  </behavior>
  <action>
1. tests/test_crawlers/test_cf_cookie_cache.py:
   - Mock redis_client (patch shared.redis_client.redis_client)
   - Test get_cf_cookies returns None when redis returns None
   - Test set_cf_cookies calls redis.set with correct key format "cf_cookies:{domain}" and TTL 1800
   - Test round-trip: set then get returns same dict

2. tests/test_crawlers/test_byparr_integration.py:
   - Mock httpx.AsyncClient for the health probe and the POST request
   - Test that fs_get sends payload with {cmd: "request.get", url: target_url, maxTimeout: 60000}
   - Test that when health probe fails, fs_get falls back to CurlCrawler.get()
   - Test that response parsing extracts solution.response as .text and solution.cookies as dict

3. tests/test_crawlers/test_idcrawl.py:
   - Test class attributes: platform, category, requires_tor, source_reliability
   - Mock self.get() to return fake HTML with person cards, verify parsing extracts name/phone
   - Mock self.get() to return None, verify found=False

4. tests/test_crawlers/test_freepeoplesearch.py:
   - Same attribute tests
   - Test phone validation integration (mock HTML with "(555) 123-4567", verify E164 output)
   - Test found=False on empty results
  </action>
  <verify>
    <automated>pytest tests/test_crawlers/test_cf_cookie_cache.py tests/test_crawlers/test_byparr_integration.py tests/test_crawlers/test_idcrawl.py tests/test_crawlers/test_freepeoplesearch.py -x -q --timeout=60</automated>
  </verify>
  <done>All 4 new test files pass, covering CF cookie cache, Byparr integration, IDCrawl crawler, and FreePeopleSearch crawler</done>
</task>

<task type="auto">
  <name>Task 2: Run full regression suite and fix any assertion mismatches</name>
  <files>tests/test_crawlers/test_curl_base.py, tests/test_crawlers/test_flaresolverr_base.py, tests/test_crawlers/test_people_search.py</files>
  <action>
Run the complete test suite to confirm no regressions from all Phase 1 changes:
```bash
pytest tests/ -x -q --timeout=120
```
If any tests fail:
- Read the failure output
- Determine if it's caused by Phase 1 changes (requires_tor removal, impersonate change, import changes)
- Fix the root cause in the relevant source file
- Re-run until green

Common failure modes to watch for:
- Tests that assert `_IMPERSONATE == "chrome124"` — update assertion to "chrome"
- Tests that assert `requires_tor == True` for people-search crawlers — update to False
- Tests that mock FlareSolverr health endpoint — may need path update if service name changed
- Import errors from new crawlers if __init__.py needs updating
  </action>
  <verify>
    <automated>pytest tests/ -x -q --timeout=120 2>&1 | tail -5</automated>
  </verify>
  <done>Full test suite (6005+ tests) passes with zero regressions</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>
Complete Phase 1 bypass infrastructure: Byparr replacing FlareSolverr, curl_cffi auto-latest fingerprint, Tor disabled on CF-protected crawlers, CF cookie cache, two new people-search crawlers (IDCrawl, FreePeopleSearch), GitHub avatar extraction, and full test coverage.
  </what-built>
  <how-to-verify>
1. Start the Docker stack: `docker compose up -d`
2. Wait for Byparr to be healthy: `docker compose ps` — byparr should show "healthy"
3. Test Byparr health endpoint: `curl -s http://localhost:8191/health` — should return JSON with status
4. Run a live smoke test against ThatsThem (lighter CF):
   ```bash
   python -c "
   import asyncio
   from modules.crawlers.people_thatsthem import PeopleThatsThemCrawler
   async def test():
       c = PeopleThatsThemCrawler()
       r = await c.scrape('John Smith')
       print(f'Found: {r.found}, Data: {r.data}')
   asyncio.run(test())
   "
   ```
5. Verify the result shows found=True with person data (not a Cloudflare block)
6. Check that WhitePages attempt at least reaches Byparr (may still get blocked by Enterprise CF, but should not get Tor-blocked):
   ```bash
   docker compose logs byparr --tail 20
   ```
  </how-to-verify>
  <resume-signal>Type "approved" if at least ThatsThem returns person data, or describe issues</resume-signal>
</task>

</tasks>

<verification>
1. `pytest tests/ -x -q --timeout=120` — full suite green
2. `curl http://localhost:8191/health` — Byparr responds
3. Live ThatsThem query returns person cards
4. No Tor-related blocks on any people-search crawler
</verification>

<success_criteria>
- All 4 new test files pass
- Full 6005+ test suite green with zero regressions
- Byparr Docker container healthy and responding on port 8191
- At least one CF-protected people-search site returns actual person data
- Phone numbers, addresses, and profile photos captured in crawler results
</success_criteria>

<output>
After completion, create `.planning/phases/01-data-access/01-data-access-04-SUMMARY.md`
</output>
