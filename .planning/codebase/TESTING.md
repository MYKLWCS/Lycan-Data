# Testing Patterns

**Analysis Date:** 2026-03-30

## Test Framework

**Runner:**
- pytest 8.3+
- Config: `pyproject.toml` `[tool.pytest.ini_options]`

**Async Support:**
- pytest-asyncio 0.24+ with `asyncio_mode = "auto"` (all async tests auto-detected, no `@pytest.mark.asyncio` needed in most cases)
- anyio 4.7+ as async backend

**Assertion Library:**
- Built-in `assert` statements
- `pytest.approx()` for floating point comparisons

**Run Commands:**
```bash
make test                # Run all tests: .venv/bin/python -m pytest tests/ -v --tb=short
make test-fast           # Skip crawlers, darkweb, government, integration: -q with ignores
make test-ci             # Full run with coverage: --cov=. --cov-report=xml --cov-fail-under=45
make test-load           # Load tests only: tests/test_load_concurrent_search.py
```

## Test File Organization

**Location:**
- All tests in `tests/` directory (separate from source)
- Mirrors source structure: `tests/test_enrichers/`, `tests/test_graph/`, `tests/test_api/`, `tests/test_shared/`, etc.

**Naming:**
- Files: `test_{module}.py`
- Wave/coverage expansion files: `test_{module}_wave{N}.py` (e.g., `test_crawlers_wave5.py`, `test_deduplication_wave3.py`)
- Special: `test_branch_coverage.py` and `test_final_gaps.py` for targeted branch coverage

**Directory structure:**
```
tests/
├── conftest.py                      # Global fixtures (auth bypass, DB, queue flush)
├── __init__.py
├── test_api/                        # API route tests (28 files)
│   ├── conftest.py                  # API-specific config
│   ├── test_routes.py               # Core route tests
│   ├── test_auth.py                 # Auth-specific tests
│   └── test_{feature}_wave{N}.py    # Coverage expansion
├── test_crawlers/                   # Crawler unit tests (100+ files)
│   ├── test_base.py                 # BaseCrawler tests
│   └── test_{platform}.py           # Per-platform tests
├── test_enrichers/                  # Enricher logic tests (30+ files)
├── test_graph/                      # Graph builder tests
├── test_shared/                     # Shared utility tests
├── test_pipeline/                   # Pipeline/orchestrator tests
├── test_dispatcher/                 # Job dispatcher tests
├── test_builder/                    # Query builder tests
├── test_patterns/                   # Anomaly/index pattern tests
├── test_search/                     # Search/Typesense tests
├── test_daemon/                     # Worker daemon tests
├── test_models/                     # ORM model tests
├── test_integration.py              # Full integration (requires DB+Redis)
├── test_branch_coverage.py          # Targeted branch coverage gaps
└── test_load_concurrent_search.py   # Load/concurrency tests
```

**Total test files:** 217

## Test Structure

**Suite Organization — Class-based (preferred for grouped tests):**
```python
class TestScoreSourceReliability:
    def test_no_sources(self):
        assert score_source_reliability([]) == 0.0

    def test_single_government(self):
        score = score_source_reliability(["government"])
        assert score >= 0.90

    def test_score_capped_at_1(self):
        sources = ["government", "government", "government"]
        score = score_source_reliability(sources)
        assert score <= 1.0
```

**Suite Organization — Function-based (common for simpler modules):**
```python
def test_normalize_name_strips_honorifics():
    result = normalize_name("Mr John Smith")
    assert "mr" not in result.split()

def test_normalize_phone_10_digit():
    result = normalize_phone("2025551234")
    assert result == "+12025551234"
```

**Section dividers in test files:**
```python
# ─── normalize_name ───────────────────────────────────────────────────────────

def test_normalize_name_strips_honorifics():
    ...

# ─── name_similarity ──────────────────────────────────────────────────────────

def test_name_similarity_identical():
    ...
```

**Docstrings on tests:**
- Most tests include a one-line docstring explaining what is being tested
- Branch coverage tests include line references: `"""Branch [33,-32]: message.person_id != person_id -> no send_json call."""`

## Mocking

**Framework:** `unittest.mock` (stdlib) — `MagicMock`, `AsyncMock`, `patch`

**DB Session Mocking (most common pattern):**
```python
def _scalars_result(items: list) -> MagicMock:
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    return result_mock

def _make_session(side_effects: list) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=side_effects)
    return session
```

**API Route Test Mocking:**
```python
def _make_session(execute_return=None, scalars_return=None, get_return=None):
    session = AsyncMock()
    default_exec = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=None),
    )
    session.execute.return_value = execute_return or default_exec
    session.get.return_value = get_return
    return session

def _override_db(session):
    async def _dep():
        yield session
    return _dep

# Usage in test:
session = _make_session()
app.dependency_overrides[db_session] = _override_db(session)
client = TestClient(app)
```

**Redis/Circuit Breaker Mocking:**
```python
class FakeRedis:
    def __init__(self):
        self._store: dict[str, dict[str, str]] = {}

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._store.get(key, {}))

    async def hset(self, key: str, field=None, value=None, mapping=None):
        if key not in self._store:
            self._store[key] = {}
        if mapping is not None:
            for k, v in mapping.items():
                self._store[key][str(k)] = str(v)

    async def expire(self, key: str, ttl: int):
        pass

    async def delete(self, key: str):
        self._store.pop(key, None)
```

**Model Mocking (for tests not hitting DB):**
```python
def _make_wealth(wealth_band="middle", vehicle_signal=0.0) -> MagicMock:
    m = MagicMock()
    m.wealth_band = wealth_band
    m.vehicle_signal = vehicle_signal
    m.income_estimate_usd = 50_000.0
    return m
```

**What to Mock:**
- Database sessions (always mock in unit tests)
- Redis/Dragonfly connections
- External HTTP calls (crawler targets)
- Event bus pub/sub
- Settings for auth-specific tests (`patch("api.deps.settings")`)

**What NOT to Mock:**
- Pure computation functions (scoring, normalization, deduplication logic)
- Data structures (dataclasses, Pydantic models)
- Constants and enum values

## Fixtures and Factories

**Global Fixtures (in `tests/conftest.py`):**

```python
@pytest.fixture(autouse=True)
def disable_api_auth():
    """Bypass API key auth in all tests by default."""
    async def _no_auth():
        return "test-key"
    app.dependency_overrides[verify_api_key] = _no_auth
    yield
    app.dependency_overrides.pop(verify_api_key, None)

@pytest.fixture
async def db():
    async for session in get_test_db():
        yield session

@pytest.fixture(scope="session", autouse=True)
def flush_test_queues():
    """Flush stale items from test queues before any test runs."""
    # Uses isolated event loop, handles Redis unavailable gracefully

@pytest.fixture(scope="session", autouse=True)
def check_db_reachable():
    """Verify test DB is reachable at session start. Logs warning if not."""
```

**Test Data Factories:**
- No formal factory library (no factory_boy)
- Inline `_make_*()` helper functions per test file
- `MagicMock()` with attributes set for model objects
- Direct ORM instantiation for integration tests:

```python
@pytest.fixture
async def test_person(db: AsyncSession):
    person = Person(full_name="Jane Doe", gender="female", nationality="US")
    db.add(person)
    await db.flush()
    return person
```

**Fixture Location:**
- Global: `tests/conftest.py`
- API-specific: `tests/test_api/conftest.py` (minimal, defers to root)
- Test-file-local: inline helper functions within each test module

## Coverage

**Requirements:**
- CI enforces minimum 45% coverage (`--cov-fail-under=45`)
- Branch coverage enabled (`branch = true` in `[tool.coverage.run]`)

**Omitted from coverage:**
- `tests/*`, `migrations/*`, `scripts/*`
- Entry points: `lycan.py`, `worker.py`
- Specific modules: `shared/scrapy_middleware.py`, `modules/crawlers/genealogy/*`, `modules/enrichers/genealogy_enricher.py`, `modules/export/*`

**Excluded lines:**
- `pragma: no cover`
- `if __name__ == "__main__":`
- `raise NotImplementedError`
- `except Exception.*pass`
- `while self._running:` (daemon loops)
- `async def start(self)` (daemon entry points)

**View Coverage:**
```bash
make test-ci                    # Runs with --cov-report=term-missing --cov-report=xml
# Output: coverage.xml in project root
```

**Coverage strategy:**
- Wave-based expansion: `test_{module}_wave{N}.py` files add coverage incrementally
- `test_branch_coverage.py` targets specific missed branches with line number references
- `test_final_gaps.py` and `test_{module}_100pct.py` for final coverage push

## Test Types

**Unit Tests (majority):**
- Pure logic tests: scoring, normalization, deduplication, graph building
- No external dependencies required
- Located in module-specific test directories
- Example: `tests/test_enrichers/test_confidence_scorer.py`, `tests/test_shared/test_utils.py`

**API Route Tests:**
- Use `starlette.testclient.TestClient` (synchronous)
- Mock DB session via FastAPI dependency overrides
- Verify routing, status codes, response shapes
- Located in `tests/test_api/`
- Example: `tests/test_api/test_routes.py`, `tests/test_api/test_auth.py`

**Integration Tests:**
- Require running PostgreSQL and Redis/Dragonfly
- Test full data flow: create person -> attach identifier -> verify persistence
- Located at `tests/test_integration.py`, `tests/test_integration_dedup_pipeline.py`
- Skipped in `test-fast` and CI (ignored in CI run)

**Load Tests:**
- Concurrent search stress tests
- Located at `tests/test_load_concurrent_search.py`
- Run separately: `make test-load`

**E2E Tests:**
- Not present as a formal category
- Playwright is a dependency but used for crawling, not test automation

## Common Patterns

**Async Testing:**
```python
# asyncio_mode = "auto" means no @pytest.mark.asyncio needed in most cases
# But some files still use it explicitly:
@pytest.mark.asyncio
async def test_create_person_with_identifier(db: AsyncSession, test_person: Person):
    identifier = Identifier(person_id=test_person.id, type=IdentifierType.EMAIL.value, ...)
    db.add(identifier)
    await db.flush()
    assert identifier.id is not None
```

**Error Testing:**
```python
def test_unauthenticated_request_rejected():
    app = _get_app()
    with patch("api.deps.settings") as mock_settings:
        mock_settings.api_auth_enabled = True
        mock_settings.api_keys = "testkey123"
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/search", json={"value": "John Smith"})
        assert resp.status_code in (401, 403)
```

**Approximate Float Assertions:**
```python
assert score_cross_references(2) == pytest.approx(0.10)
assert score_cross_references(10) == pytest.approx(0.30)
```

**Boundary Testing (common in scoring tests):**
```python
def test_score_capped_at_1(self):
    sources = ["government", "government", "government"]
    score = score_source_reliability(sources)
    assert score <= 1.0

def test_no_sources(self):
    assert score_source_reliability([]) == 0.0
```

**Auth Override Pattern (for auth-specific tests):**
```python
@pytest.fixture(autouse=True)
def restore_auth_for_auth_tests():
    """Remove the conftest auth override so auth tests actually test auth."""
    from api.main import app
    app.dependency_overrides.pop(verify_api_key, None)
    yield
    app.dependency_overrides.pop(verify_api_key, None)
```

## CI Pipeline

**Location:** `.github/workflows/ci.yml`

**Jobs:**
1. **Lint** - Ruff check + Ruff format check
2. **Tests** - pytest with coverage (ignores `test_integration.py`), minimum 45%
3. **Security** - Bandit static analysis + pip-audit dependency scan
4. **Import Check** - `scripts/check_imports.py` verifies all modules import cleanly

**Runner:** Self-hosted (`[self-hosted, lycan]`)

**Test infrastructure in CI:**
- PostgreSQL via Docker container (`lycan-data-postgres-1`)
- Garnet (Redis-compatible) via Docker container (`lycan-data-garnet-1`)
- Test database created: `lycan_test`
- Extensions: `vector`, `uuid-ossp`
- Alembic migrations run before tests
- Redis flushed before test run

**pytest warnings suppressed:**
```ini
filterwarnings = [
    "ignore::DeprecationWarning",
    "ignore:coroutine 'Connection._cancel' was never awaited:RuntimeWarning",
]
```

**Additional options:**
- `--tb=short` for concise tracebacks
- `-p no:randomly` to disable random test ordering

---

*Testing analysis: 2026-03-30*
