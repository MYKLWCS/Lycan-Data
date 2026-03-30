# Coding Conventions

**Analysis Date:** 2026-03-30

## Naming Patterns

**Files:**
- Use `snake_case.py` for all Python modules
- Model files: singular nouns (`person.py`, `identifier.py`, `crawl.py`)
- Crawler files: `{platform}_{type}.py` (e.g., `crypto_bitcoin.py`, `company_sec.py`, `court_courtlistener.py`)
- Test files: `test_{module}.py` or `test_{module}_{wave}.py` for coverage waves
- Schema files: match the model they serialize (`person.py` in `shared/schemas/`)

**Functions:**
- Use `snake_case` for all functions and methods
- Private/internal helpers prefixed with `_` (e.g., `_person_node()`, `_normalize_email_for_dedup()`, `_clamp()`)
- Public API functions: descriptive verb-noun (`find_duplicate_persons()`, `compute_freshness()`, `dispatch_job()`)
- Async functions use `async def` consistently (no sync wrappers around async)

**Variables:**
- Use `snake_case` for all variables
- Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_SCRAPER_RETRIES`, `DELAY_MIN`, `WEIGHT_FRESHNESS`)
- Logger instances: `logger = logging.getLogger(__name__)` or `_log = logging.getLogger(__name__)` (both patterns exist)

**Types/Classes:**
- Use `PascalCase` for classes: `BaseCrawler`, `EventBus`, `CircuitBreaker`, `MergeCandidate`
- Enums: `PascalCase` class names, `UPPER_SNAKE_CASE` members using `StrEnum`
- SQLAlchemy models: `PascalCase` singular nouns (`Person`, `Identifier`, `SocialProfile`)
- Pydantic schemas: `PascalCase` with descriptive suffixes (`PersonSummary`, `PersonResponse`, `SeedInput`)
- Dataclasses: `PascalCase` (`CrawlerResult`, `MergeCandidate`, `RateLimit`)

**Enums:**
- Always use `StrEnum` (Python 3.12 feature), not plain `Enum`
- Defined in `shared/constants.py` for shared enums (`SeedType`, `IdentifierType`, `Platform`, `LineType`)
- Module-specific enums live in their module file (e.g., `CircuitState` in `shared/circuit_breaker.py`)

## Code Style

**Formatting:**
- Tool: Ruff (format mode)
- Line length: 100 characters (configured in `pyproject.toml`)
- Target: Python 3.12

**Linting:**
- Tool: Ruff (lint mode)
- Enabled rule sets: `E` (pycodestyle), `W` (warnings), `F` (pyflakes), `I` (isort), `B` (bugbear), `C4` (comprehensions), `UP` (pyupgrade)
- Key ignores: `E501` (line length handled by formatter), `B008` (function calls in defaults), `E402` (import order in main.py)
- Per-file ignores:
  - `tests/**`: `F401`, `F811`, `E741`
  - `migrations/**`: `E501`, `F401`
  - `scripts/**`: `T201`, `E741`
  - `shared/models/**`: `F821` (SQLAlchemy forward references)

## Import Organization

**Order:**
1. Standard library (`import asyncio`, `import uuid`, `from datetime import ...`)
2. Third-party packages (`import pytest`, `from fastapi import ...`, `from sqlalchemy import ...`)
3. Local imports (`from shared.config import settings`, `from modules.crawlers.base import ...`)

**Path style:**
- Absolute imports only (no relative imports)
- Import from specific submodules, not package roots: `from shared.models.person import Person` not `from shared.models import Person`
- Exception: `shared/models/__init__.py` re-exports models for convenience in tests

**Path Aliases:**
- None. All imports use full dotted paths from project root.
- `PYTHONPATH=.` is set in CI to enable root-relative imports.

## Error Handling

**Patterns:**
- Crawlers: **never raise** from `scrape()`. Always return `CrawlerResult(found=False, error="description")`. The `BaseCrawler.run()` wrapper handles retries and circuit breaker logic.
- API routes: raise `HTTPException` with appropriate status codes (`401`, `404`, `503`)
- DB sessions: use try/except with rollback in `get_db()` dependency (`shared/db.py`)
- Fire-and-forget operations (audit logging, Redis): wrap in bare `except Exception: pass` to avoid blocking primary operations
- Startup checks: collect errors in a list, log all with `_log.critical()`, continue running

**Error return pattern in crawlers:**
```python
async def scrape(self, identifier: str) -> CrawlerResult:
    try:
        # ... scraping logic
        return CrawlerResult(platform=self.platform, identifier=identifier, found=True, data={...})
    except Exception as e:
        return CrawlerResult(platform=self.platform, identifier=identifier, found=False, error=str(e))
```

**HTTP error pattern in API routes:**
```python
person = await db.get(Person, person_id)
if not person:
    raise HTTPException(status_code=404, detail="Person not found")
```

## Logging

**Framework:** Python `logging` standard library

**Patterns:**
- Module-level logger: `logger = logging.getLogger(__name__)`
- Structured log messages with `%s` formatting (not f-strings): `logger.info("AUDIT %s %s %s", method, path, status)`
- Log levels used consistently:
  - `logger.info()` for operational events (startup, crawl results)
  - `logger.warning()` for degraded state (Redis unavailable, stale data)
  - `logger.critical()` for startup failures and missing dependencies
  - `logger.debug()` for verbose tracing (circuit breaker state changes)
- Audit middleware logs structured entries: `"AUDIT {method} {path} {status} key={key} ip={ip} dur={ms}ms"`

## Comments

**When to Comment:**
- Module-level docstrings on every file explaining purpose and scope
- Class docstrings on all public classes with usage examples (see `BaseCrawler` in `modules/crawlers/base.py`)
- Section dividers using `# ── Section Name ──...` with em-dash lines for visual separation
- Inline comments for non-obvious logic (weight calculations, composite key priorities)

**Docstring style:**
- Google-style docstrings with `Args:` and `Returns:` blocks for complex functions
- One-liner docstrings for simple helpers

**Section dividers (used consistently throughout):**
```python
# ── Section Name ──────────────────────────────────────────────────────────
```

## Function Design

**Size:** Most functions are 10-40 lines. Complex orchestration methods (like `BaseCrawler.run()`) can reach 80+ lines.

**Parameters:**
- Use type annotations on all parameters and return types
- Use `str | None` union syntax (Python 3.12 style, not `Optional[str]`)
- Default values for optional parameters: `conflict_flag: bool = False`
- Use dataclasses for structured parameter groups (`CrawlerResult`, `MergeCandidate`)

**Return Values:**
- Functions return typed values, not raw dicts (exception: serialization helpers like `_model_to_dict()`)
- Crawlers always return `CrawlerResult`, never raise
- Scoring functions return `float` clamped to 0.0-1.0

## Module Design

**Exports:**
- No `__all__` declarations in most modules
- `shared/models/__init__.py` re-exports all model classes for convenience
- `shared/utils/__init__.py` re-exports common utility functions

**Barrel Files:**
- `shared/models/__init__.py` acts as barrel file for all ORM models
- `shared/utils/__init__.py` re-exports from submodules (`email`, `phone`, `scoring`, `social`)
- `shared/schemas/__init__.py` re-exports Pydantic schemas

## Configuration

**Pattern:** Single `Settings` class using `pydantic-settings` in `shared/config.py`
- All config via environment variables, loaded from `.env` file
- Module-level singleton: `settings = Settings()`
- Kill switches for individual crawlers: `enable_instagram: bool = True`
- Sensible defaults for all settings (runs locally without any env vars)

## SQLAlchemy Model Pattern

**Base class:** `shared/models/base.py` provides `Base`, `TimestampMixin`, `DataQualityMixin`
- All models inherit from `Base`
- Most models mix in `TimestampMixin` (created_at, updated_at)
- Data-bearing models mix in `DataQualityMixin` (source_reliability, freshness_score, composite_quality)
- Use `Mapped[type]` annotations with `mapped_column()` (SQLAlchemy 2.0 style)
- UUIDs as primary keys: `id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)`
- JSONB columns for flexible metadata: `meta: Mapped[dict] = mapped_column(JSONB, default=dict)`

## FastAPI Route Pattern

**Router setup:**
```python
router = APIRouter()
```

**Dependency injection:**
- DB session via `DbDep = Depends(db_session)` (defined in `api/deps.py`)
- Auth via `verify_api_key` dependency applied at router level in `api/main.py`
- Pydantic `BaseModel` for request bodies, inline return dicts for responses

**Route registration in `api/main.py`:**
```python
app.include_router(persons.router, prefix="/persons", tags=["persons"], dependencies=_auth)
```

## Crawler Registration Pattern

**Decorator-based registration:**
```python
@register("myplatform")
class MyCrawler(BaseCrawler):
    platform = "myplatform"
    source_reliability = 0.6
    category = CrawlerCategory.SOCIAL_MEDIA
    requires_tor = True

    async def scrape(self, identifier: str) -> CrawlerResult:
        ...
```

- All crawlers auto-register via `_import_all_crawlers()` at startup
- Registry stored in `modules/crawlers/registry.py` as `CRAWLER_REGISTRY`
- Class attributes define metadata (platform, reliability, category, proxy tier)

---

*Convention analysis: 2026-03-30*
