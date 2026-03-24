# Crawler Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace broken TLS-fingerprinted crawlers with stealth transports (curl_cffi, patchright, camoufox, FlareSolverr), fix the five root-cause bugs preventing data return, and add six new OSINT crawlers — all without touching individual crawler `scrape()` methods.

**Architecture:** Three-layer composable transport hierarchy (`HttpxCrawler → CurlCrawler → FlareSolverrCrawler`); existing crawlers migrate by changing one import line. Bugs fixed in pivot_enricher, identifier model, and search normalization. New crawlers integrate via the same dispatch/ingest pipeline.

**Tech Stack:** curl-cffi (Chrome 130 TLS), patchright (stealth Playwright), camoufox[geoip] (Firefox stealth), FlareSolverr (Docker sidecar), fake-useragent, maigret CLI, socialscan, phoneinfoga CLI, Alembic, Dragonfly, FastAPI.

---

## File Map

**New files:**
- `modules/crawlers/curl_base.py` — CurlCrawler (Chrome 130 TLS)
- `modules/crawlers/flaresolverr_base.py` — FlareSolverrCrawler (Cloudflare bypass)
- `modules/crawlers/camoufox_base.py` — CamoufoxCrawler (Firefox stealth)
- `shared/health.py` — startup bypass-layer health check
- `shared/transport_registry.py` — Dragonfly-backed per-domain transport preference
- `modules/crawlers/username_maigret.py` — maigret CLI wrapper
- `modules/crawlers/email_socialscan.py` — socialscan async wrapper
- `modules/crawlers/phone_phoneinfoga.py` — phoneinfoga CLI wrapper
- `modules/crawlers/people_phonebook.py` — phonebook.name scraper
- `modules/crawlers/people_intelx.py` — IntelX API crawler
- `modules/crawlers/email_dehashed.py` — DeHashed API crawler
- `migrations/versions/<hash>_normalize_identifier_constraint.py` — Alembic migration

**Modified files:**
- `pyproject.toml` — add 7 new packages
- `docker-compose.yml` — add flaresolverr service
- `modules/crawlers/playwright_base.py` — swap to patchright, Chrome 130+ UAs, full nav patches
- `modules/pipeline/pivot_enricher.py` — fix 3 bugs, add 4 pivot types
- `shared/constants.py` — add 3 SeedType members
- `shared/models/identifier.py` — swap UniqueConstraint to normalized_value
- `api/routes/search.py` — add .lower() normalization, 6 new SEED_PLATFORM_MAP entries
- All 33 existing crawlers — parent class swap (one line each, grouped by transport tier)

---

## Phase 1 — Foundation (Tasks 1–8)

### Task 1: Add packages to pyproject.toml

**Files:**
- Modify: `pyproject.toml`
- Test: none (verified via `poetry check`)

- [ ] **Step 1: Read pyproject.toml**

Read the current `[tool.poetry.dependencies]` section.

- [ ] **Step 2: Add dependencies**

Under `[tool.poetry.dependencies]` add:
```toml
curl-cffi = "^0.7"
patchright = "^1.49"
"camoufox[geoip]" = "^0.4"
fake-useragent = "^1.5"
maigret = "^0.4"
socialscan = "^1.3"
phoneinfoga = "*"
```

- [ ] **Step 3: Verify**

```bash
poetry check
```
Expected: `All set!`

- [ ] **Step 4: Install patchright browser**

```bash
poetry run patchright install chromium
```
This downloads the patched Chromium binary. Required in addition to pip install.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "feat(deps): add curl-cffi, patchright, camoufox, fake-useragent, maigret, socialscan, phoneinfoga"
```

---

### Task 2: Add FlareSolverr to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`
- Test: `docker compose up flaresolverr -d && curl -sf http://localhost:8191/health`

- [ ] **Step 1: Read docker-compose.yml**

Read the current services section.

- [ ] **Step 2: Add flaresolverr service**

Append to `services:`:
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

- [ ] **Step 3: Verify syntax**

```bash
docker compose config --quiet
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(infra): add FlareSolverr sidecar service"
```

---

### Task 3: Upgrade playwright_base.py to patchright

**Files:**
- Modify: `modules/crawlers/playwright_base.py`
- Test: `tests/test_crawlers/test_playwright_base.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_crawlers/test_playwright_base.py`:
```python
import pytest
from modules.crawlers.playwright_base import PlaywrightBaseCrawler

def test_uses_patchright_import():
    import inspect, modules.crawlers.playwright_base as m
    src = inspect.getsource(m)
    assert "patchright" in src
    assert "playwright" not in src.split("patchright")[0]

def test_ua_is_chrome_130_plus():
    ua = PlaywrightBaseCrawler.USER_AGENTS[0]
    version = int(ua.split("Chrome/")[1].split(".")[0])
    assert version >= 130
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_crawlers/test_playwright_base.py -v
```
Expected: FAIL (old import, stale UA).

- [ ] **Step 3: Implement**

In `playwright_base.py`:
1. Replace `from playwright.async_api import async_playwright` → `from patchright.async_api import async_playwright`
2. Replace USER_AGENTS list with Chrome 130+ strings from fake-useragent
3. In `_launch_browser()`, after `page = await context.new_page()`, add:
```python
await page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
""")
```
4. Add viewport jitter: random width 1280–1920, height 720–1080

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_crawlers/test_playwright_base.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add modules/crawlers/playwright_base.py tests/test_crawlers/test_playwright_base.py
git commit -m "feat(crawlers): upgrade playwright_base to patchright with Chrome 130+ UAs and full nav patches"
```

---

### Task 4: Create CurlCrawler (curl_base.py)

**Files:**
- Create: `modules/crawlers/curl_base.py`
- Test: `tests/test_crawlers/test_curl_base.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_crawlers/test_curl_base.py`:
```python
import pytest
from modules.crawlers.curl_base import CurlCrawler

class _TestCrawler(CurlCrawler):
    platform = "test"
    async def scrape(self, identifier): return self._result(identifier, False)

@pytest.mark.asyncio
async def test_curl_crawler_is_httpx_subclass():
    from modules.crawlers.httpx_base import HttpxCrawler
    assert issubclass(CurlCrawler, HttpxCrawler)

@pytest.mark.asyncio
async def test_curl_crawler_instantiates():
    c = _TestCrawler()
    assert c is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_crawlers/test_curl_base.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `modules/crawlers/curl_base.py`:
```python
"""
CurlCrawler — extends HttpxCrawler with Chrome 130 TLS fingerprint impersonation.

Uses curl_cffi.requests.AsyncSession instead of httpx. Impersonates Chrome 130
at the TLS handshake level, bypassing TLS fingerprinting by Cloudflare, DataDome,
Akamai, and similar services that reject Python's default TLS signature.

Drop-in replacement: subclasses only change their parent import from
HttpxCrawler to CurlCrawler. The scrape() method is unchanged.
"""

from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler

logger = logging.getLogger(__name__)


class CurlCrawler(HttpxCrawler):
    """HttpxCrawler variant that impersonates Chrome 130 at the TLS layer."""

    _IMPERSONATE = "chrome130"

    async def get(self, url: str, **kwargs):
        """GET via curl_cffi AsyncSession with Chrome 130 TLS fingerprint."""
        try:
            from curl_cffi.requests import AsyncSession

            proxy = self.get_proxy()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            async with AsyncSession(impersonate=self._IMPERSONATE) as session:
                resp = await session.get(url, proxies=proxies, **kwargs)
                resp.raise_for_status()
                return resp
        except ImportError:
            logger.warning("curl_cffi not available, falling back to httpx")
            return await super().get(url, **kwargs)

    async def post(self, url: str, **kwargs):
        """POST via curl_cffi AsyncSession with Chrome 130 TLS fingerprint."""
        try:
            from curl_cffi.requests import AsyncSession

            proxy = self.get_proxy()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            async with AsyncSession(impersonate=self._IMPERSONATE) as session:
                resp = await session.post(url, proxies=proxies, **kwargs)
                resp.raise_for_status()
                return resp
        except ImportError:
            logger.warning("curl_cffi not available, falling back to httpx")
            return await super().post(url, **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_crawlers/test_curl_base.py -v
```

- [ ] **Step 5: Commit**

```bash
git add modules/crawlers/curl_base.py tests/test_crawlers/test_curl_base.py
git commit -m "feat(crawlers): add CurlCrawler with Chrome 130 TLS fingerprint impersonation"
```

---

### Task 5: Create FlareSolverrCrawler (flaresolverr_base.py)

**Files:**
- Create: `modules/crawlers/flaresolverr_base.py`
- Test: `tests/test_crawlers/test_flaresolverr_base.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_crawlers/test_flaresolverr_base.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch
from modules.crawlers.flaresolverr_base import FlareSolverrCrawler

class _TestCrawler(FlareSolverrCrawler):
    platform = "test"
    async def scrape(self, identifier): return self._result(identifier, False)

def test_flaresolverr_is_curl_subclass():
    from modules.crawlers.curl_base import CurlCrawler
    assert issubclass(FlareSolverrCrawler, CurlCrawler)

def test_health_cache_is_class_level():
    assert hasattr(FlareSolverrCrawler, "_fs_healthy")
    assert hasattr(FlareSolverrCrawler, "_fs_checked_at")

@pytest.mark.asyncio
async def test_fs_get_falls_back_when_unavailable():
    FlareSolverrCrawler._fs_healthy = False
    FlareSolverrCrawler._fs_checked_at = float("inf")
    c = _TestCrawler()
    with patch.object(c, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = AsyncMock(text="<html/>", status_code=200)
        result = await c.fs_get("http://example.com")
        mock_get.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_crawlers/test_flaresolverr_base.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `modules/crawlers/flaresolverr_base.py`:
```python
"""
FlareSolverrCrawler — extends CurlCrawler with Cloudflare JS-challenge bypass.

FlareSolverr is a Docker sidecar (localhost:8191) that spins up headless Chrome
to solve Cloudflare challenges and return the rendered HTML + cookies.

Health cache is CLASS-LEVEL so all instances share the same probe result:
- _fs_healthy = True → positive result cached indefinitely (FlareSolverr stays up)
- _fs_healthy = False → negative result cached for _FS_NEGATIVE_TTL seconds (60s)
  to avoid hammering a down sidecar on every request

Fallback chain: FlareSolverr → CurlCrawler (Chrome 130) → httpx
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from modules.crawlers.curl_base import CurlCrawler

logger = logging.getLogger(__name__)

_FS_URL = "http://localhost:8191/v1"
_FS_TIMEOUT = 60
_FS_NEGATIVE_TTL = 60  # seconds before re-probing a down sidecar


class FlareSolverrCrawler(CurlCrawler):
    """CurlCrawler variant that routes Cloudflare-protected URLs through FlareSolverr."""

    # Class-level health cache — shared across all instances
    _fs_healthy: bool | None = None
    _fs_checked_at: float = 0.0

    @classmethod
    async def _probe_flaresolverr(cls) -> bool:
        """Check if the FlareSolverr sidecar is reachable. Caches result."""
        now = time.monotonic()
        if cls._fs_healthy is True:
            return True  # positive: indefinite cache
        if cls._fs_healthy is False and (now - cls._fs_checked_at) < _FS_NEGATIVE_TTL:
            return False  # negative: within TTL
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get("http://localhost:8191/health")
                cls._fs_healthy = resp.status_code == 200
        except Exception:
            cls._fs_healthy = False
        cls._fs_checked_at = time.monotonic()
        return cls._fs_healthy

    async def fs_get(self, url: str, **kwargs) -> Any:
        """
        GET via FlareSolverr. Falls back to CurlCrawler.get() if sidecar unavailable.
        Returns a response-like object with .text and .status_code attributes.
        """
        if not await self._probe_flaresolverr():
            logger.debug("FlareSolverr unavailable, falling back to CurlCrawler for %s", url)
            return await self.get(url, **kwargs)

        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": _FS_TIMEOUT * 1000,
        }
        try:
            async with httpx.AsyncClient(timeout=_FS_TIMEOUT + 10) as client:
                resp = await client.post(_FS_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") != "ok":
                    raise RuntimeError(f"FlareSolverr error: {data.get('message')}")

                solution = data["solution"]

                class _FsResponse:
                    text = solution.get("response", "")
                    status_code = solution.get("status", 200)
                    cookies = {c["name"]: c["value"] for c in solution.get("cookies", [])}

                return _FsResponse()
        except Exception as exc:
            logger.warning("FlareSolverr request failed (%s), falling back to CurlCrawler", exc)
            FlareSolverrCrawler._fs_healthy = False
            FlareSolverrCrawler._fs_checked_at = time.monotonic()
            return await self.get(url, **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_crawlers/test_flaresolverr_base.py -v
```

- [ ] **Step 5: Commit**

```bash
git add modules/crawlers/flaresolverr_base.py tests/test_crawlers/test_flaresolverr_base.py
git commit -m "feat(crawlers): add FlareSolverrCrawler with class-level health cache and 60s negative TTL"
```

---

### Task 6: Create CamoufoxCrawler (camoufox_base.py)

**Files:**
- Create: `modules/crawlers/camoufox_base.py`
- Test: `tests/test_crawlers/test_camoufox_base.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_crawlers/test_camoufox_base.py
import pytest
from modules.crawlers.camoufox_base import CamoufoxCrawler
from modules.crawlers.base import BaseCrawler

def test_camoufox_is_base_subclass():
    assert issubclass(CamoufoxCrawler, BaseCrawler)

def test_camoufox_has_get_page():
    assert hasattr(CamoufoxCrawler, "get_page")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_crawlers/test_camoufox_base.py -v
```

- [ ] **Step 3: Implement**

Create `modules/crawlers/camoufox_base.py`:
```python
"""
CamoufoxCrawler — Firefox-based stealth browser.

Uses camoufox (patched Firefox) which defeats PerimeterX, DataDome, and other
fingerprinting systems that have signatures for Chrome-based headless browsers.
Provides a different fingerprint than patchright/Playwright (Firefox vs Chrome).

Falls back gracefully if camoufox is not installed (ImportError is caught).
"""

from __future__ import annotations

import logging
import random

from modules.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)


class CamoufoxCrawler(BaseCrawler):
    """BaseCrawler variant using camoufox (patched Firefox) for stealth browsing."""

    async def get_page(self, url: str) -> str:
        """
        Fetch page HTML via camoufox stealth Firefox.
        Returns rendered HTML string. Falls back to empty string on error.
        """
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError:
            logger.warning("camoufox not installed; returning empty string for %s", url)
            return ""

        try:
            await self._human_delay()
            proxy = self.get_proxy()
            proxy_dict = {"server": proxy} if proxy else None

            async with AsyncCamoufox(
                headless=True,
                proxy=proxy_dict,
                geoip=True,
                viewport={
                    "width": random.randint(1280, 1920),
                    "height": random.randint(720, 1080),
                },
            ) as browser:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                return await page.content()
        except Exception as exc:
            logger.warning("CamoufoxCrawler.get_page failed for %s: %s", url, exc)
            return ""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_crawlers/test_camoufox_base.py -v
```

- [ ] **Step 5: Commit**

```bash
git add modules/crawlers/camoufox_base.py tests/test_crawlers/test_camoufox_base.py
git commit -m "feat(crawlers): add CamoufoxCrawler using Firefox stealth browser"
```

---

### Task 7: Add startup health check (shared/health.py)

**Files:**
- Create: `shared/health.py`
- Test: `tests/test_health.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_health.py
import pytest
from shared.health import check_bypass_layers

@pytest.mark.asyncio
async def test_check_bypass_layers_returns_dict():
    result = await check_bypass_layers()
    assert isinstance(result, dict)
    expected_keys = {"flaresolverr", "tor_1", "tor_2", "tor_3", "dragonfly", "postgres"}
    assert expected_keys.issubset(result.keys())

@pytest.mark.asyncio
async def test_check_bypass_layers_values_are_bool():
    result = await check_bypass_layers()
    for v in result.values():
        assert isinstance(v, bool)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_health.py -v
```

- [ ] **Step 3: Implement**

Create `shared/health.py`:
```python
"""
Startup health check for all bypass layers.
Call check_bypass_layers() at application startup to log availability.
Individual crawlers handle their own unavailability — this is informational only.
"""
from __future__ import annotations
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


async def _check_flaresolverr() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("http://localhost:8191/health")
            return r.status_code == 200
    except Exception:
        return False


async def _check_tor(port: int) -> bool:
    try:
        async with httpx.AsyncClient(
            proxies={"all://": f"socks5://127.0.0.1:{port}"}, timeout=10
        ) as c:
            r = await c.get("https://check.torproject.org/api/ip")
            return r.status_code == 200 and r.json().get("IsTor") is True
    except Exception:
        return False


async def _check_dragonfly() -> bool:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url("redis://localhost:6379", socket_connect_timeout=3)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


async def _check_postgres() -> bool:
    try:
        from shared.db import AsyncSessionLocal
        import sqlalchemy
        async with AsyncSessionLocal() as s:
            await s.execute(sqlalchemy.text("SELECT 1"))
        return True
    except Exception:
        return False


async def check_bypass_layers() -> dict[str, bool]:
    results = await asyncio.gather(
        _check_flaresolverr(),
        _check_tor(9050),
        _check_tor(9052),
        _check_tor(9054),
        _check_dragonfly(),
        _check_postgres(),
        return_exceptions=False,
    )
    status = {
        "flaresolverr": results[0],
        "tor_1": results[1],
        "tor_2": results[2],
        "tor_3": results[3],
        "dragonfly": results[4],
        "postgres": results[5],
    }
    for layer, ok in status.items():
        level = logging.INFO if ok else logging.WARNING
        logger.log(level, "Bypass layer %s: %s", layer, "OK" if ok else "UNAVAILABLE")
    return status
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_health.py -v
```

- [ ] **Step 5: Commit**

```bash
git add shared/health.py tests/test_health.py
git commit -m "feat(shared): add bypass-layer health check for startup diagnostics"
```

---

### Task 8: Add transport registry (shared/transport_registry.py)

**Files:**
- Create: `shared/transport_registry.py`
- Test: `tests/test_transport_registry.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_transport_registry.py
import pytest
from unittest.mock import AsyncMock, patch
from shared.transport_registry import TransportRegistry

@pytest.mark.asyncio
async def test_default_transport_is_httpx():
    reg = TransportRegistry()
    t = await reg.get_transport("example.com")
    assert t == "httpx"

@pytest.mark.asyncio
async def test_record_blocked_promotes_after_threshold():
    reg = TransportRegistry(threshold=3)
    for _ in range(3):
        await reg.record_blocked("example.com")
    t = await reg.get_transport("example.com")
    assert t == "flaresolverr"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_transport_registry.py -v
```

- [ ] **Step 3: Implement**

Create `shared/transport_registry.py`:
```python
"""
Per-domain transport preference registry backed by Dragonfly (Redis).

Tracks block counts per domain. After `threshold` blocks, auto-promotes the
domain to FlareSolverr transport. Falls back to in-memory dict if Dragonfly
is unavailable (no crash, just no persistence across restarts).

Transport tiers (in order of capability):
  httpx → curl (Chrome TLS) → flaresolverr (Cloudflare bypass)
"""
from __future__ import annotations
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

_TIER_ORDER = ["httpx", "curl", "flaresolverr"]
_PREFIX = "transport:"
_BLOCK_PREFIX = "blocks:"


class TransportRegistry:
    def __init__(self, threshold: int = 3):
        self._threshold = threshold
        self._memory: dict[str, str] = {}
        self._blocks: dict[str, int] = defaultdict(int)
        self._redis = None

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url("redis://localhost:6379")
            await self._redis.ping()
        except Exception:
            self._redis = None
        return self._redis

    async def get_transport(self, domain: str) -> str:
        r = await self._get_redis()
        if r:
            try:
                val = await r.get(f"{_PREFIX}{domain}")
                return val.decode() if val else "httpx"
            except Exception:
                pass
        return self._memory.get(domain, "httpx")

    async def set_transport(self, domain: str, transport: str) -> None:
        r = await self._get_redis()
        if r:
            try:
                await r.set(f"{_PREFIX}{domain}", transport)
                return
            except Exception:
                pass
        self._memory[domain] = transport

    async def record_blocked(self, domain: str) -> None:
        r = await self._get_redis()
        count = 0
        if r:
            try:
                count = await r.incr(f"{_BLOCK_PREFIX}{domain}")
            except Exception:
                pass
        else:
            self._blocks[domain] += 1
            count = self._blocks[domain]

        if count >= self._threshold:
            current = await self.get_transport(domain)
            idx = _TIER_ORDER.index(current) if current in _TIER_ORDER else 0
            if idx < len(_TIER_ORDER) - 1:
                new_transport = _TIER_ORDER[idx + 1]
                await self.set_transport(domain, new_transport)
                logger.info(
                    "Domain %s promoted from %s to %s after %d blocks",
                    domain, current, new_transport, count,
                )


transport_registry = TransportRegistry()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_transport_registry.py -v
```

- [ ] **Step 5: Commit**

```bash
git add shared/transport_registry.py tests/test_transport_registry.py
git commit -m "feat(shared): add Dragonfly-backed transport registry with auto-promotion after 3 blocks"
```

---

## Phase 2 — Bug Fixes (Tasks 9–11)

### Task 9: DB migration + identifier.py model (ATOMIC — deploy together)

**Files:**
- Modify: `shared/models/identifier.py`
- Create: `migrations/versions/<hash>_normalize_identifier_constraint.py`

> **WARNING:** Steps 9a (model change) and 9b (migration) must be deployed together.
> Deploying the model without the migration — or vice versa — will break writes.

- [ ] **Step 1: Write failing test**

```python
# tests/test_models/test_identifier_constraint.py
import pytest

def test_unique_constraint_on_normalized_value():
    from shared.models.identifier import Identifier
    import sqlalchemy as sa
    table = Identifier.__table__
    constraints = {c.name for c in table.constraints if isinstance(c, sa.UniqueConstraint)}
    assert "uq_identifier_type_normalized" in constraints
    assert "uq_identifier_type_value" not in constraints

def test_normalized_value_not_nullable():
    from shared.models.identifier import Identifier
    col = Identifier.__table__.c.normalized_value
    assert col.nullable is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_models/test_identifier_constraint.py -v
```

- [ ] **Step 3a: Update the model**

In `shared/models/identifier.py`:
1. Change `UniqueConstraint("type", "value", name="uq_identifier_type_value")` to `UniqueConstraint("type", "normalized_value", name="uq_identifier_type_normalized")`
2. Change `normalized_value = Column(String, nullable=True, ...)` to `nullable=False`

- [ ] **Step 3b: Generate migration**

```bash
alembic revision --autogenerate -m "normalize_identifier_constraint"
```

**IMPORTANT:** Alembic autogenerate only detects schema changes — it does NOT emit data migrations. You must manually add the backfill line to the generated migration file before the constraint operations.

Open the generated file and manually insert this line at the top of `upgrade()`, before the constraint changes:
```python
op.execute("UPDATE identifier SET normalized_value = lower(trim(value)) WHERE normalized_value IS NULL")
```

Then verify the rest of upgrade() contains:
- Drop of `uq_identifier_type_value`
- Creation of `uq_identifier_type_normalized` on `(type, normalized_value)`
- `NOT NULL` constraint on `normalized_value`

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_models/test_identifier_constraint.py -v
```

- [ ] **Step 5: Commit (model + migration together)**

```bash
git add shared/models/identifier.py migrations/versions/
git commit -m "fix(db): swap UniqueConstraint to normalized_value, backfill NOT NULL — deploy atomically with migration"
```

---

### Task 10: Fix case sensitivity — constants.py + search.py

**Files:**
- Modify: `shared/constants.py`
- Modify: `api/routes/search.py`
- Test: `tests/test_api/test_search_normalization.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_api/test_search_normalization.py
import pytest
from api.routes.search import _auto_detect_type, SEED_PLATFORM_MAP
from shared.constants import SeedType

def test_auto_detect_type_is_case_insensitive():
    assert _auto_detect_type("USER@EXAMPLE.COM") == SeedType.EMAIL
    assert _auto_detect_type("  USER@EXAMPLE.COM  ") == SeedType.EMAIL

def test_auto_detect_type_phone():
    assert _auto_detect_type("+1-800-555-1234") == SeedType.PHONE

def test_seed_platform_map_has_new_crawlers():
    required = {
        "username_maigret",
        "email_socialscan",
        "phone_phoneinfoga",
        "people_phonebook",
        "people_intelx",
        "email_dehashed",
    }
    all_values = {v for vals in SEED_PLATFORM_MAP.values() for v in vals}
    assert required.issubset(all_values)

def test_instagram_handle_seed_type_exists():
    assert hasattr(SeedType, "INSTAGRAM_HANDLE")
    assert hasattr(SeedType, "TWITTER_HANDLE")
    assert hasattr(SeedType, "LINKEDIN_URL")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api/test_search_normalization.py -v
```

- [ ] **Step 3: Update constants.py**

Add to `SeedType(StrEnum)`:
```python
INSTAGRAM_HANDLE = "instagram_handle"
TWITTER_HANDLE = "twitter_handle"
LINKEDIN_URL = "linkedin_url"
```

- [ ] **Step 4: Update search.py**

In `_auto_detect_type()`:
```python
# Before all regex matches, normalize:
identifier = identifier.strip().lower()
```

In `SEED_PLATFORM_MAP`, add entries for new crawlers:
```python
SeedType.USERNAME: [...existing..., "username_maigret", "email_socialscan"],
SeedType.EMAIL: [...existing..., "email_socialscan", "email_dehashed"],
SeedType.PHONE: [...existing..., "phone_phoneinfoga"],
SeedType.FULL_NAME: [...existing..., "people_phonebook", "people_intelx"],
SeedType.DOMAIN: [...existing..., "people_phonebook", "people_intelx"],
# Pivot-only types — dispatched by pivot enricher, never from API input directly:
SeedType.INSTAGRAM_HANDLE: ["instagram", "username_maigret", "username_sherlock"],
SeedType.TWITTER_HANDLE: ["twitter", "username_maigret", "username_sherlock"],
SeedType.LINKEDIN_URL: ["linkedin"],
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_api/test_search_normalization.py -v
```

- [ ] **Step 6: Commit**

```bash
git add shared/constants.py api/routes/search.py tests/test_api/test_search_normalization.py
git commit -m "fix(search): add .lower() normalization to _auto_detect_type, add 3 SeedTypes, wire 6 new crawlers to SEED_PLATFORM_MAP"
```

---

### Task 11: Fix pivot_enricher.py (3 bugs + 4 new pivot types)

**Files:**
- Modify: `modules/pipeline/pivot_enricher.py`
- Test: `tests/test_pipeline/test_pivot_enricher.py` (add new cases)

- [ ] **Step 1: Write failing tests**

```python
# Add to existing tests/test_pipeline/test_pivot_enricher.py:
import pytest
from modules.pipeline.pivot_enricher import _extract_pivots

def test_email_extraction_operator_precedence():
    """emails list should be used when other email fields absent."""
    data = {"emails": ["test@example.com", "other@example.com"]}
    pivots = _extract_pivots("platform", data)
    emails = [p for p in pivots if p[0] == "email"]
    assert len(emails) >= 1
    assert emails[0][1] == "test@example.com"

def test_email_extraction_direct_field_wins():
    """data.get('email') should win over emails list."""
    data = {"email": "direct@example.com", "emails": ["list@example.com"]}
    pivots = _extract_pivots("platform", data)
    emails = [p for p in pivots if p[0] == "email"]
    assert emails[0][1] == "direct@example.com"

def test_extract_pivots_returns_all_types_not_capped():
    """_extract_pivots must not cap results — that's the caller's job."""
    data = {
        "email": "a@b.com",
        "phone": "+15551234567",
        "username": "johndoe",
        "full_name": "John Doe",
    }
    pivots = _extract_pivots("platform", data)
    assert len(pivots) == 4

def test_instagram_handle_pivot():
    data = {"instagram": "johndoe"}
    pivots = _extract_pivots("platform", data)
    handles = [p for p in pivots if p[0] == "instagram_handle"]
    assert len(handles) == 1

def test_max_jobs_per_call_cap_applied_in_caller():
    """The cap must be applied at dispatch level, not in _extract_pivots."""
    import inspect, modules.pipeline.pivot_enricher as m
    src = inspect.getsource(m._extract_pivots)
    # should not contain any slice of the returned list
    assert "found[:" not in src
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pipeline/test_pivot_enricher.py -v
```

- [ ] **Step 3: Fix pivot_enricher.py**

Make the following changes:

**3a. Remove `_MAX_PIVOTS = 3` and replace with:**
```python
_MAX_JOBS_PER_CALL = 30
```

**3b. Fix email extraction operator precedence (lines ~66-73):**
```python
# BEFORE (buggy — ternary binds to entire or chain):
email = (
    data.get("email")
    or data.get("email_address")
    or data.get("contact_email")
    or data.get("emails", [None])[0]
    if isinstance(data.get("emails"), list)
    else None
)

# AFTER (correct — parenthesize only the last clause):
email = (
    data.get("email")
    or data.get("email_address")
    or data.get("contact_email")
    or (data.get("emails", [None])[0] if isinstance(data.get("emails"), list) else None)
)
```

**3c. Remove `return found[:_MAX_PIVOTS]` from `_extract_pivots()` — change to `return found`**

**3d. Add new pivot extractions before `return found`:**
```python
# Instagram handle
ig = data.get("instagram") or data.get("instagram_handle") or data.get("instagram_username")
if ig:
    found.append(("instagram_handle", ig.lstrip("@").lower()))

# Twitter handle
tw = data.get("twitter") or data.get("twitter_handle") or data.get("twitter_username")
if tw:
    found.append(("twitter_handle", tw.lstrip("@").lower()))

# LinkedIn URL
li = data.get("linkedin") or data.get("linkedin_url") or data.get("linkedin_profile")
if li:
    found.append(("linkedin_url", li))

# Domain
domain = data.get("domain") or data.get("website") or data.get("url")
if domain and "." in str(domain):
    found.append(("domain", domain.lower()))
```

**3e. In `pivot_from_result()` (the caller), apply the cap:**
```python
pivots = _extract_pivots(platform, data)
jobs_queued = 0
for pivot_type, pivot_value in pivots:
    if jobs_queued >= _MAX_JOBS_PER_CALL:
        break
    # ... existing dispatch logic ...
    jobs_queued += 1
return jobs_queued
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_pipeline/test_pivot_enricher.py -v
```

- [ ] **Step 5: Commit**

```bash
git add modules/pipeline/pivot_enricher.py tests/test_pipeline/test_pivot_enricher.py
git commit -m "fix(pipeline): remove _MAX_PIVOTS slice, fix email operator precedence, add instagram/twitter/linkedin/domain pivots, cap at _MAX_JOBS_PER_CALL=30"
```

---

## Phase 3 — Migrate Existing Crawlers (Task 12)

### Task 12: Migrate 33 crawlers to new transport base classes

**Files:**
- Modify: all crawler files listed below

Each crawler only needs **one line changed**: the parent class import.
The `scrape()` method is untouched.

**Transport assignments (exact file names from spec Section 4):**

FlareSolverrCrawler (Cloudflare JS-challenge sites):
- `whitepages.py`, `truepeoplesearch.py`, `fastpeoplesearch.py`
- `people_thatsthem.py`, `people_zabasearch.py`
- `paste_pastebin.py`, `paste_ghostbin.py`, `paste_psbdmp.py`

CamoufoxCrawler (PerimeterX / DataDome — need Firefox fingerprint):
- `instagram.py`, `linkedin.py`, `twitter.py`, `tiktok.py`
- `snapchat.py`, `discord.py`, `pinterest.py`, `facebook.py`

CurlCrawler (TLS fingerprinting only — Chrome 130 sufficient):
- `email_hibp.py`, `email_holehe.py`, `email_emailrep.py`, `email_breach.py`
- `cyber_shodan.py`, `cyber_virustotal.py`, `cyber_greynoise.py`, `cyber_abuseipdb.py`, `cyber_urlscan.py`, `cyber_crt.py`
- `crypto_bitcoin.py`, `crypto_ethereum.py`, `crypto_blockchair.py`
- `financial_crunchbase.py`, `news_search.py`, `news_wikipedia.py`, `domain_whois.py`

Note: `youtube.py`, `reddit.py`, `social_mastodon.py`, `social_twitch.py`, `social_steam.py`, `darkweb_torch.py`, `darkweb_ahmia.py` are already on PlaywrightCrawler — they receive the patchright upgrade in Task 3, no parent-class change needed here.

- [ ] **Step 1: Write migration test**

```python
# tests/test_crawlers/test_crawler_transport_tiers.py
import pytest
from modules.crawlers.flaresolverr_base import FlareSolverrCrawler
from modules.crawlers.camoufox_base import CamoufoxCrawler
from modules.crawlers.curl_base import CurlCrawler

FLARESOLVERR_CRAWLERS = [
    "modules.crawlers.whitepages",
    "modules.crawlers.fastpeoplesearch",
    "modules.crawlers.paste_pastebin",
]
CAMOUFOX_CRAWLERS = [
    "modules.crawlers.instagram",
    "modules.crawlers.twitter",
    "modules.crawlers.facebook",
]
CURL_CRAWLERS = [
    "modules.crawlers.email_hibp",
    "modules.crawlers.cyber_shodan",
    "modules.crawlers.domain_whois",
]

@pytest.mark.parametrize("mod_path", FLARESOLVERR_CRAWLERS)
def test_flaresolverr_tier(mod_path):
    import importlib
    mod = importlib.import_module(mod_path)
    crawler_cls = [v for v in vars(mod).values()
                   if isinstance(v, type) and issubclass(v, FlareSolverrCrawler) and v is not FlareSolverrCrawler]
    assert crawler_cls, f"{mod_path} has no FlareSolverrCrawler subclass"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_crawlers/test_crawler_transport_tiers.py -v
```

- [ ] **Step 3: Apply migration**

For each crawler in the FlareSolverrCrawler group, e.g. `whitepages.py`:
```python
# Before:
from modules.crawlers.httpx_base import HttpxCrawler
class WhitepagesCrawler(HttpxCrawler):

# After:
from modules.crawlers.flaresolverr_base import FlareSolverrCrawler
class WhitepagesCrawler(FlareSolverrCrawler):
```

Apply same pattern for CamoufoxCrawler and CurlCrawler groups.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_crawlers/test_crawler_transport_tiers.py -v
```

- [ ] **Step 5: Commit**

```bash
git add modules/crawlers/
git commit -m "feat(crawlers): migrate 33 crawlers to tiered transport bases (FlareSolverr/Camoufox/Curl)"
```

---

## Phase 4 — New Crawlers (Tasks 13–15)

### Task 13: maigret + socialscan crawlers

**Files:**
- Create: `modules/crawlers/username_maigret.py`
- Create: `modules/crawlers/email_socialscan.py`
- Test: `tests/test_crawlers/test_new_osint_crawlers.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_crawlers/test_new_osint_crawlers.py
import pytest
from modules.crawlers.base import BaseCrawler

def test_maigret_crawler_is_base_subclass():
    from modules.crawlers.username_maigret import MaigretCrawler
    assert issubclass(MaigretCrawler, BaseCrawler)

def test_socialscan_crawler_is_base_subclass():
    from modules.crawlers.email_socialscan import SocialscanCrawler
    assert issubclass(SocialscanCrawler, BaseCrawler)

def test_maigret_has_platform_attribute():
    from modules.crawlers.username_maigret import MaigretCrawler
    assert MaigretCrawler.platform == "username_maigret"

def test_socialscan_has_platform_attribute():
    from modules.crawlers.email_socialscan import SocialscanCrawler
    assert SocialscanCrawler.platform in ("email_socialscan", "username_socialscan")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_crawlers/test_new_osint_crawlers.py::test_maigret_crawler_is_base_subclass -v
```

- [ ] **Step 3: Implement username_maigret.py**

Create `modules/crawlers/username_maigret.py`:
```python
"""
MaigretCrawler — wraps the `maigret` CLI to search 2000+ sites for a username.

maigret outputs JSON with found/not-found per site. We aggregate all found
sites into the result's `data` dict for the pivot enricher to process.

CLI invocation uses positional arguments only — no shell interpolation.
"""
from __future__ import annotations
import asyncio
import json
import logging
import shutil

from modules.crawlers.base import BaseCrawler
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)

_TIMEOUT = 120  # maigret can be slow across 2000+ sites


class MaigretCrawler(BaseCrawler):
    platform = "username_maigret"

    async def scrape(self, identifier: str) -> CrawlerResult:
        if not shutil.which("maigret"):
            logger.warning("maigret CLI not found in PATH")
            return self._result(identifier, False, error="maigret not installed")

        try:
            await self._human_delay()
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    "maigret", identifier, "--json", "/tmp/maigret_out.json",
                    "--no-color", "--timeout", "30",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=_TIMEOUT,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        except asyncio.TimeoutError:
            return self._result(identifier, False, error="maigret timeout")
        except Exception as exc:
            return self._result(identifier, False, error=str(exc))

        try:
            with open("/tmp/maigret_out.json") as f:
                raw = json.load(f)
            sites_found = {
                site: info
                for site, info in raw.items()
                if info.get("status", {}).get("id") == "found"
            }
            if not sites_found:
                return self._result(identifier, False)
            return self._result(
                identifier, True,
                data={
                    "username": identifier,
                    "sites_found": list(sites_found.keys()),
                    "profiles": {
                        site: info.get("url_user", "")
                        for site, info in sites_found.items()
                    },
                }
            )
        except Exception as exc:
            return self._result(identifier, False, error=f"parse error: {exc}")
```

- [ ] **Step 4: Implement email_socialscan.py**

Create `modules/crawlers/email_socialscan.py`:
```python
"""
SocialscanCrawler — checks email/username registration across major platforms.

Uses the socialscan Python library (async, no CLI needed).
Returns a list of platforms where the identifier is registered.
"""
from __future__ import annotations
import logging

from modules.crawlers.base import BaseCrawler
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)


class SocialscanCrawler(BaseCrawler):
    platform = "email_socialscan"

    async def scrape(self, identifier: str) -> CrawlerResult:
        try:
            from socialscan.util import Platforms, QueryHandler, Query
        except ImportError:
            logger.warning("socialscan not installed")
            return self._result(identifier, False, error="socialscan not installed")

        try:
            await self._human_delay()
            queries = [Query(identifier, platform) for platform in Platforms]
            handler = QueryHandler()
            results = await handler.query(queries)
            claimed = [r.platform.value for r in results if r.available is False]
            if not claimed:
                return self._result(identifier, False)
            return self._result(
                identifier, True,
                data={"identifier": identifier, "registered_on": claimed}
            )
        except Exception as exc:
            return self._result(identifier, False, error=str(exc))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_crawlers/test_new_osint_crawlers.py -v
```

- [ ] **Step 6: Commit**

```bash
git add modules/crawlers/username_maigret.py modules/crawlers/email_socialscan.py tests/test_crawlers/test_new_osint_crawlers.py
git commit -m "feat(crawlers): add MaigretCrawler (2000+ sites) and SocialscanCrawler"
```

---

### Task 14: phoneinfoga crawler

**Files:**
- Create: `modules/crawlers/phone_phoneinfoga.py`
- Test: `tests/test_crawlers/test_new_osint_crawlers.py` (add cases)

- [ ] **Step 1: Write failing test**

```python
# Add to tests/test_crawlers/test_new_osint_crawlers.py:
def test_phoneinfoga_crawler_is_base_subclass():
    from modules.crawlers.phone_phoneinfoga import PhoneInfogaCrawler
    assert issubclass(PhoneInfogaCrawler, BaseCrawler)
    assert PhoneInfogaCrawler.platform == "phone_phoneinfoga"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_crawlers/test_new_osint_crawlers.py::test_phoneinfoga_crawler_is_base_subclass -v
```

- [ ] **Step 3: Implement**

Create `modules/crawlers/phone_phoneinfoga.py`:
```python
"""
PhoneInfogaCrawler — wraps the phoneinfoga CLI for phone number OSINT.

phoneinfoga scans phone numbers using multiple sources: numverify, local,
googlesearch, scanner. Returns carrier, country, line type, and found URLs.

CLI invocation uses positional arguments only — no shell interpolation.
"""
from __future__ import annotations
import asyncio
import json
import logging
import shutil

from modules.crawlers.base import BaseCrawler
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)
_TIMEOUT = 60


class PhoneInfogaCrawler(BaseCrawler):
    platform = "phone_phoneinfoga"

    async def scrape(self, identifier: str) -> CrawlerResult:
        if not shutil.which("phoneinfoga"):
            logger.warning("phoneinfoga CLI not found in PATH")
            return self._result(identifier, False, error="phoneinfoga not installed")

        try:
            await self._human_delay()
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    "phoneinfoga", "scan", "-n", identifier, "--output", "json",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=_TIMEOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
        except asyncio.TimeoutError:
            return self._result(identifier, False, error="phoneinfoga timeout")
        except Exception as exc:
            return self._result(identifier, False, error=str(exc))

        try:
            data = json.loads(stdout.decode("utf-8", errors="replace"))
            if not data:
                return self._result(identifier, False)
            return self._result(identifier, True, data=data)
        except Exception as exc:
            return self._result(identifier, False, error=f"parse error: {exc}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_crawlers/test_new_osint_crawlers.py -v
```

- [ ] **Step 5: Commit**

```bash
git add modules/crawlers/phone_phoneinfoga.py tests/test_crawlers/test_new_osint_crawlers.py
git commit -m "feat(crawlers): add PhoneInfogaCrawler (phoneinfoga CLI wrapper)"
```

---

### Task 15: Data broker crawlers (phonebook, IntelX, DeHashed)

**Files:**
- Create: `modules/crawlers/people_phonebook.py`
- Create: `modules/crawlers/people_intelx.py`
- Create: `modules/crawlers/email_dehashed.py`
- Test: `tests/test_crawlers/test_new_osint_crawlers.py` (add cases)

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_crawlers/test_new_osint_crawlers.py:
def test_phonebook_crawler_exists():
    from modules.crawlers.people_phonebook import PhonebookCrawler
    from modules.crawlers.curl_base import CurlCrawler
    assert issubclass(PhonebookCrawler, CurlCrawler)

def test_intelx_crawler_exists():
    from modules.crawlers.people_intelx import IntelXCrawler
    from modules.crawlers.curl_base import CurlCrawler
    assert issubclass(IntelXCrawler, CurlCrawler)

def test_dehashed_crawler_exists():
    from modules.crawlers.email_dehashed import DeHashedCrawler
    from modules.crawlers.curl_base import CurlCrawler
    assert issubclass(DeHashedCrawler, CurlCrawler)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_crawlers/test_new_osint_crawlers.py -v -k "phonebook or intelx or dehashed"
```

- [ ] **Step 3: Implement people_phonebook.py**

Create `modules/crawlers/people_phonebook.py`:
```python
"""
PhonebookCrawler — scrapes phonebook.name for name/email lookups.
Uses CurlCrawler (Chrome 130 TLS fingerprint). No API key required.
"""
from __future__ import annotations
import logging
from bs4 import BeautifulSoup

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)


class PhonebookCrawler(CurlCrawler):
    platform = "people_phonebook"
    _BASE = "https://phonebook.name"

    async def scrape(self, identifier: str) -> CrawlerResult:
        url = f"{self._BASE}/search/?q={identifier.replace(' ', '+')}"
        try:
            resp = await self.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for row in soup.select(".result-row"):
                entry = {}
                name_el = row.select_one(".name")
                if name_el:
                    entry["full_name"] = name_el.get_text(strip=True)
                phone_el = row.select_one(".phone")
                if phone_el:
                    entry["phone"] = phone_el.get_text(strip=True)
                email_el = row.select_one(".email")
                if email_el:
                    entry["email"] = email_el.get_text(strip=True)
                if entry:
                    results.append(entry)
            if not results:
                return self._result(identifier, False)
            return self._result(identifier, True, data={"results": results})
        except Exception as exc:
            return self._result(identifier, False, error=str(exc))
```

- [ ] **Step 4: Implement people_intelx.py**

Create `modules/crawlers/people_intelx.py`:
```python
"""
IntelXCrawler — Intelligence X API for email/domain/phone OSINT.
Requires INTELX_API_KEY environment variable.
Uses CurlCrawler for Chrome 130 TLS fingerprint.
"""
from __future__ import annotations
import logging
import os

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)
_API_BASE = "https://2.intelx.io"


class IntelXCrawler(CurlCrawler):
    platform = "people_intelx"

    async def scrape(self, identifier: str) -> CrawlerResult:
        api_key = os.getenv("INTELX_API_KEY")
        if not api_key:
            return self._result(identifier, False, error="INTELX_API_KEY not set")

        headers = {"x-key": api_key, "Content-Type": "application/json"}
        try:
            search_resp = await self.post(
                f"{_API_BASE}/intelligent/search",
                json={"term": identifier, "maxresults": 100, "media": 0, "target": 0},
                headers=headers,
            )
            search_data = search_resp.json()
            search_id = search_data.get("id")
            if not search_id:
                return self._result(identifier, False)

            result_resp = await self.get(
                f"{_API_BASE}/intelligent/search/result?id={search_id}&limit=50&offset=0",
                headers=headers,
            )
            result_data = result_resp.json()
            records = result_data.get("records", [])
            if not records:
                return self._result(identifier, False)
            return self._result(identifier, True, data={"records": records[:50]})
        except Exception as exc:
            return self._result(identifier, False, error=str(exc))
```

- [ ] **Step 5: Implement email_dehashed.py**

Create `modules/crawlers/email_dehashed.py`:
```python
"""
DeHashedCrawler — breach database search via DeHashed API.
Requires DEHASHED_API_KEY and DEHASHED_EMAIL environment variables.
Returns breached credentials associated with an email address.
"""
from __future__ import annotations
import base64
import logging
import os

from modules.crawlers.curl_base import CurlCrawler
from modules.crawlers.result import CrawlerResult

logger = logging.getLogger(__name__)
_API_BASE = "https://api.dehashed.com"


class DeHashedCrawler(CurlCrawler):
    platform = "email_dehashed"

    async def scrape(self, identifier: str) -> CrawlerResult:
        api_key = os.getenv("DEHASHED_API_KEY")
        api_email = os.getenv("DEHASHED_EMAIL")
        if not api_key or not api_email:
            return self._result(identifier, False, error="DEHASHED_API_KEY/DEHASHED_EMAIL not set")

        creds = base64.b64encode(f"{api_email}:{api_key}".encode()).decode()
        headers = {
            "Authorization": f"Basic {creds}",
            "Accept": "application/json",
        }
        try:
            resp = await self.get(
                f"{_API_BASE}/search?query=email:{identifier}&size=50",
                headers=headers,
            )
            data = resp.json()
            entries = data.get("entries") or []
            if not entries:
                return self._result(identifier, False)
            return self._result(identifier, True, data={"breach_count": len(entries), "entries": entries})
        except Exception as exc:
            return self._result(identifier, False, error=str(exc))
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_crawlers/test_new_osint_crawlers.py -v
```

- [ ] **Step 7: Commit**

```bash
git add modules/crawlers/people_phonebook.py modules/crawlers/people_intelx.py modules/crawlers/email_dehashed.py tests/test_crawlers/test_new_osint_crawlers.py
git commit -m "feat(crawlers): add PhonebookCrawler, IntelXCrawler, DeHashedCrawler"
```

---

## Phase 5 — Validation (Task 16)

### Task 16: Full test suite validation

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tee /tmp/test_results.txt
```

- [ ] **Step 2: Check coverage**

```bash
pytest tests/ --cov=modules --cov=shared --cov-report=term-missing 2>&1 | tail -30
```
Expected: no new failures vs baseline, new files ≥ 70% coverage.

- [ ] **Step 3: Run linter**

```bash
ruff check modules/crawlers/ shared/ api/routes/search.py
```
Expected: no errors.

- [ ] **Step 4: Integration smoke test (if services running)**

```bash
docker compose up -d flaresolverr
python -c "
import asyncio
from shared.health import check_bypass_layers
result = asyncio.run(check_bypass_layers())
print(result)
"
```
Expected: flaresolverr: True (or False with WARNING if not started).

- [ ] **Step 5: Commit final state**

```bash
git add -u
git commit -m "test: full suite validation pass — crawler overhaul complete"
```

---

## Deployment Notes

1. **Atomic deploy of Task 9**: Run `alembic upgrade head` on the same deploy that ships `shared/models/identifier.py` changes. Never deploy one without the other.

2. **patchright browser install**: Add `patchright install chromium` to your Dockerfile and CI. It is a separate step from `pip install patchright`.

3. **Environment variables for new crawlers**:
   - `INTELX_API_KEY` — required for IntelXCrawler (get from intelx.io; basic free tier available). Without this, IntelXCrawler returns immediately with no data.
   - `DEHASHED_API_KEY` + `DEHASHED_EMAIL` — required for DeHashedCrawler (get from dehashed.com).
   - phoneinfoga and maigret work without API keys but need their binaries in PATH.
   - Add all three to `.env.example` alongside `FLARESOLVERR_URL`.

4. **FlareSolverr startup**: `docker compose up -d flaresolverr` before running the app. Crawlers fall back gracefully if it's unavailable.
