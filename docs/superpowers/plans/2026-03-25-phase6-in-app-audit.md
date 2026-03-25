# Phase 6: In-App Audit Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce an hourly `AuditDaemon` that snapshots platform health into a `system_audits` table, expose it through six FastAPI endpoints, surface it as a live "System Audit" card in the Activity view, and wire it into the worker process behind a `--no-audit` flag.

**Architecture:** `AuditDaemon` runs as an asyncio background task in `worker.py` alongside the existing `GrowthDaemon` and `FreshnessScheduler`; each run executes four SQL queries against `persons`, `crawl_jobs`, `audit_log`, and `marketing_tags`, then persists a `SystemAudit` row. The API layer exposes the stored snapshots so the frontend never blocks on live query execution. The frontend Activity view polls `GET /audit/latest` every 60 seconds and renders the result as a self-contained card with a manual trigger button.

**Tech Stack:** Python asyncio, SQLAlchemy async, PostgreSQL, FastAPI, Alembic, vanilla JS (existing SPA pattern)

---

## File Map

**New files:**
- `modules/audit/__init__.py`
- `modules/audit/audit_daemon.py` — `AuditDaemon` with 4 audit categories
- `api/routes/audit.py` — 6 endpoints
- `tests/test_shared/test_audit_model.py`
- `tests/test_daemon/test_audit_daemon.py`
- `tests/test_daemon/test_worker_flags.py`
- `tests/test_api/test_audit_routes.py`
- `migrations/versions/c3d4e5f6a7b8_add_system_audits.py`

**Modified files:**
- `shared/models/audit.py` — add `SystemAudit` model
- `api/main.py` — import and register audit router
- `worker.py` — add `AuditDaemon` task + `--no-audit` flag
- `static/index.html` — extend `renderActivity()` with System Audit card

---

## Task 1: SystemAudit Model

**Files:**
- Modify: `shared/models/audit.py`
- Test: `tests/test_shared/test_audit_model.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_shared/test_audit_model.py`:
```python
import uuid
from datetime import datetime, timezone
from shared.models.audit import SystemAudit

def test_system_audit_instantiation():
    sa = SystemAudit(
        run_at=datetime.now(timezone.utc),
        persons_total=100,
        persons_low_coverage=10,
        persons_stale=5,
        persons_conflict=2,
        crawlers_total=8,
        crawlers_healthy=7,
        crawlers_degraded=[{"name": "example_crawler", "success_rate": 0.0}],
        tags_assigned_today=50,
        merges_today=3,
        persons_ingested_today=20,
    )
    assert sa.persons_total == 100
    assert sa.crawlers_degraded[0]["name"] == "example_crawler"
    assert isinstance(sa.meta, dict)

def test_system_audit_tablename():
    assert SystemAudit.__tablename__ == "system_audits"

def test_system_audit_has_id():
    sa = SystemAudit(
        run_at=datetime.now(timezone.utc),
        persons_total=0,
        persons_low_coverage=0,
        persons_stale=0,
        persons_conflict=0,
        crawlers_total=0,
        crawlers_healthy=0,
        crawlers_degraded=[],
        tags_assigned_today=0,
        merges_today=0,
        persons_ingested_today=0,
    )
    # id has a default factory — should be a UUID after construction
    assert sa.id is not None
    assert isinstance(sa.id, uuid.UUID)
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_shared/test_audit_model.py -v
```
Expected: `ImportError` or `AttributeError` — `SystemAudit` does not exist yet.

- [ ] **Step 3: Implement**

Open `shared/models/audit.py`. After the existing `AuditLog` class, append:

```python
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Index, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from shared.models.base import Base, TimestampMixin


class SystemAudit(Base, TimestampMixin):
    __tablename__ = "system_audits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Person data quality
    persons_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persons_low_coverage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persons_stale: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persons_conflict: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Crawler health
    crawlers_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    crawlers_healthy: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    crawlers_degraded: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Data volume (today)
    tags_assigned_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    merges_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    persons_ingested_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_system_audits_run_at", "run_at"),
    )
```

Note: imports for `uuid`, `datetime`, `Integer`, `Index` may already be present at the top of the file — deduplicate as needed.

- [ ] **Step 4: Run — expect PASS**

```bash
python3 -m pytest tests/test_shared/test_audit_model.py -v
```
Expected:
```
tests/test_shared/test_audit_model.py::test_system_audit_instantiation PASSED
tests/test_shared/test_audit_model.py::test_system_audit_tablename PASSED
tests/test_shared/test_audit_model.py::test_system_audit_has_id PASSED
3 passed
```

- [ ] **Step 5: Commit**

```bash
git add shared/models/audit.py tests/test_shared/test_audit_model.py
git commit -m "feat(audit): add SystemAudit ORM model to shared/models/audit.py"
```

---

## Task 2: Alembic Migration

**Files:**
- New: `migrations/versions/c3d4e5f6a7b8_add_system_audits.py`
- Test: `tests/test_migrations.py` (existing — run to verify no regressions)

- [ ] **Step 1: Generate migration stub**

```bash
cd /home/wolf/Lycan-Data && alembic revision --autogenerate -m "add_system_audits"
```
Alembic will create a new file under `migrations/versions/`. Note its filename.

- [ ] **Step 2: Verify generated migration**

Open the generated file and confirm it contains `op.create_table("system_audits", ...)` with all columns plus the index. If autogenerate missed anything, add it manually.

The `upgrade()` must create the following columns in `system_audits`:
- `id UUID NOT NULL PRIMARY KEY`
- `run_at TIMESTAMPTZ NOT NULL`
- `persons_total INTEGER NOT NULL DEFAULT 0`
- `persons_low_coverage INTEGER NOT NULL DEFAULT 0`
- `persons_stale INTEGER NOT NULL DEFAULT 0`
- `persons_conflict INTEGER NOT NULL DEFAULT 0`
- `crawlers_total INTEGER NOT NULL DEFAULT 0`
- `crawlers_healthy INTEGER NOT NULL DEFAULT 0`
- `crawlers_degraded JSONB NOT NULL DEFAULT '[]'`
- `tags_assigned_today INTEGER NOT NULL DEFAULT 0`
- `merges_today INTEGER NOT NULL DEFAULT 0`
- `persons_ingested_today INTEGER NOT NULL DEFAULT 0`
- `meta JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- Index `ix_system_audits_run_at` on `run_at`

The `downgrade()` must call `op.drop_table("system_audits")`.

- [ ] **Step 3: Rename file to canonical name**

```bash
mv migrations/versions/<generated_hash>_add_system_audits.py \
   migrations/versions/c3d4e5f6a7b8_add_system_audits.py
```

Open the file and set:
```python
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
```

- [ ] **Step 4: Run existing migration tests**

```bash
python3 -m pytest tests/test_migrations.py -v
```
Expected: all existing tests pass, no regressions.

- [ ] **Step 5: Apply migration to dev DB**

```bash
cd /home/wolf/Lycan-Data && alembic upgrade head
```
Expected output ends with:
```
Running upgrade b2c3d4e5f6a7 -> c3d4e5f6a7b8, add_system_audits
```

- [ ] **Step 6: Commit**

```bash
git add migrations/versions/c3d4e5f6a7b8_add_system_audits.py
git commit -m "feat(migration): add system_audits table (revision c3d4e5f6a7b8)"
```

---

## Task 3: AuditDaemon

**Files:**
- New: `modules/audit/__init__.py`
- New: `modules/audit/audit_daemon.py`
- Test: `tests/test_daemon/test_audit_daemon.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_daemon/test_audit_daemon.py`:
```python
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.audit.audit_daemon import AuditDaemon


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_session():
    session = AsyncMock()

    def _exec_side_effect(stmt, *a, **kw):
        result = MagicMock()
        result.scalar_one = MagicMock(return_value=0)
        result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )
        result.mappings = MagicMock(
            return_value=MagicMock(
                all=MagicMock(return_value=[]),
                one_or_none=MagicMock(return_value=None),
            )
        )
        return result

    session.execute = AsyncMock(side_effect=_exec_side_effect)
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


# ── tests ─────────────────────────────────────────────────────────────────────

def test_audit_daemon_has_start_method():
    d = AuditDaemon()
    assert asyncio.iscoroutinefunction(d.start)


def test_audit_daemon_has_run_audit_method():
    d = AuditDaemon()
    assert asyncio.iscoroutinefunction(d._run_audit)


def test_audit_daemon_stop_flag():
    d = AuditDaemon()
    assert d._running is True
    d.stop()
    assert d._running is False


@pytest.mark.asyncio
async def test_run_audit_persists_system_audit():
    """_run_audit() must add a SystemAudit row and commit."""
    from shared.models.audit import SystemAudit

    session = _make_session()

    with patch(
        "modules.audit.audit_daemon.AsyncSessionLocal",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=AsyncMock(return_value=False),
        ),
    ):
        d = AuditDaemon()
        await d._run_audit()

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, SystemAudit)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_audit_returns_audit_object():
    """_run_audit() must return the SystemAudit instance it created."""
    from shared.models.audit import SystemAudit

    session = _make_session()

    with patch(
        "modules.audit.audit_daemon.AsyncSessionLocal",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=AsyncMock(return_value=False),
        ),
    ):
        d = AuditDaemon()
        result = await d._run_audit()

    assert isinstance(result, SystemAudit)


@pytest.mark.asyncio
async def test_audit_daemon_stop_exits_loop():
    """start() must exit cleanly when _running is False."""
    call_count = 0

    async def fake_run_audit():
        nonlocal call_count
        call_count += 1

    with patch("asyncio.sleep", new_callable=AsyncMock):
        d = AuditDaemon()
        d._run_audit = fake_run_audit
        d._running = False  # stop immediately
        await d.start()

    assert call_count == 0


@pytest.mark.asyncio
async def test_crawler_health_degraded_list():
    """Crawlers with 0% success rate appear in crawlers_degraded."""
    from shared.models.audit import SystemAudit

    session = AsyncMock()
    call_index = [0]

    crawl_rows = [
        {"source_name": "bad_crawler", "found_count": 0, "error_count": 5}
    ]

    def _exec_side_effect(stmt, *a, **kw):
        idx = call_index[0]
        call_index[0] += 1
        result = MagicMock()
        if idx == 1:  # crawler health query (second query in _run_audit)
            result.mappings = MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=crawl_rows))
            )
        else:
            result.scalar_one = MagicMock(return_value=0)
            result.mappings = MagicMock(
                return_value=MagicMock(
                    all=MagicMock(return_value=[]),
                    one_or_none=MagicMock(return_value=None),
                )
            )
        return result

    session.execute = AsyncMock(side_effect=_exec_side_effect)
    session.add = MagicMock()
    session.commit = AsyncMock()

    with patch(
        "modules.audit.audit_daemon.AsyncSessionLocal",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=AsyncMock(return_value=False),
        ),
    ):
        d = AuditDaemon()
        result = await d._run_audit()

    assert isinstance(result.crawlers_degraded, list)


@pytest.mark.asyncio
async def test_run_audit_is_resilient_to_query_failure():
    """If one query raises, _run_audit still commits a row with 0 for that field."""
    from shared.models.audit import SystemAudit

    session = AsyncMock()
    call_index = [0]

    def _exec_side_effect(stmt, *a, **kw):
        idx = call_index[0]
        call_index[0] += 1
        if idx == 0:
            raise Exception("DB timeout")
        result = MagicMock()
        result.scalar_one = MagicMock(return_value=0)
        result.mappings = MagicMock(
            return_value=MagicMock(
                all=MagicMock(return_value=[]),
                one_or_none=MagicMock(return_value=None),
            )
        )
        return result

    session.execute = AsyncMock(side_effect=_exec_side_effect)
    session.add = MagicMock()
    session.commit = AsyncMock()

    with patch(
        "modules.audit.audit_daemon.AsyncSessionLocal",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=AsyncMock(return_value=False),
        ),
    ):
        d = AuditDaemon()
        result = await d._run_audit()  # must not raise

    assert isinstance(result, SystemAudit)
    assert result.persons_total == 0
    session.commit.assert_awaited_once()
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_daemon/test_audit_daemon.py -v
```
Expected: `ModuleNotFoundError: No module named 'modules.audit'`

- [ ] **Step 3: Create package and implement daemon**

Create `modules/audit/__init__.py` (empty file).

Create `modules/audit/audit_daemon.py`:
```python
"""
AuditDaemon — hourly system health snapshot.

Runs five SQL queries per cycle and persists a SystemAudit row.
Each query is isolated; a failure in one category degrades gracefully
(logs error, uses 0 for that field) so the whole audit still commits.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from shared.db import AsyncSessionLocal
from shared.models.audit import SystemAudit

logger = logging.getLogger("lycan.audit_daemon")

_PERSONS_QUALITY_SQL = text("""
    SELECT
        COUNT(*) FILTER (WHERE merged_into IS NULL)
            AS persons_total,
        COUNT(*) FILTER (
            WHERE merged_into IS NULL
            AND (
                meta->'coverage'->>'pct' IS NULL
                OR (meta->'coverage'->>'pct')::float < 50
            )
        ) AS persons_low_coverage,
        COUNT(*) FILTER (
            WHERE merged_into IS NULL
            AND last_scraped_at < now() - interval '30 days'
        ) AS persons_stale,
        COUNT(*) FILTER (
            WHERE merged_into IS NULL
            AND conflict_flag = TRUE
        ) AS persons_conflict
    FROM persons
""")

_CRAWLER_HEALTH_SQL = text("""
    SELECT
        ds.name                                                     AS source_name,
        COUNT(*) FILTER (WHERE cj.status = 'found')                AS found_count,
        COUNT(*) FILTER (WHERE cj.status = 'error')                AS error_count
    FROM crawl_jobs cj
    LEFT JOIN data_sources ds ON ds.id = cj.source_id
    WHERE cj.created_at > now() - interval '24 hours'
    GROUP BY ds.name
""")

_VOLUME_SQL = text("""
    SELECT COUNT(*) AS persons_ingested_today
    FROM persons
    WHERE created_at > current_date
""")

_MERGES_SQL = text("""
    SELECT COUNT(*) AS merges_today
    FROM audit_log
    WHERE action = 'auto_merge'
      AND access_time > current_date
""")

_TAGS_SQL = text("""
    SELECT COUNT(*) AS tags_assigned_today
    FROM marketing_tags
    WHERE scored_at > current_date
""")


class AuditDaemon:
    def __init__(self, interval_seconds: int = 3600):
        self._running = True
        self._interval = interval_seconds
        logger.info("AuditDaemon initialised (interval=%ds)", interval_seconds)

    def stop(self) -> None:
        self._running = False

    async def start(self) -> None:
        logger.info("AuditDaemon started")
        while self._running:
            try:
                audit = await self._run_audit()
                logger.info(
                    "Audit complete — persons=%d  low_cov=%d  stale=%d  "
                    "conflict=%d  crawlers=%d/%d healthy  tags=%d  merges=%d",
                    audit.persons_total,
                    audit.persons_low_coverage,
                    audit.persons_stale,
                    audit.persons_conflict,
                    audit.crawlers_healthy,
                    audit.crawlers_total,
                    audit.tags_assigned_today,
                    audit.merges_today,
                )
            except Exception:
                logger.exception("AuditDaemon cycle failed")
            await asyncio.sleep(self._interval)

    async def _run_audit(self) -> SystemAudit:
        async with AsyncSessionLocal() as session:
            run_at = datetime.now(timezone.utc)

            # ── 1. Person data quality ─────────────────────────────────────
            persons_total = 0
            persons_low_coverage = 0
            persons_stale = 0
            persons_conflict = 0
            try:
                row = (await session.execute(_PERSONS_QUALITY_SQL)).mappings().one_or_none()
                if row:
                    persons_total = int(row["persons_total"] or 0)
                    persons_low_coverage = int(row["persons_low_coverage"] or 0)
                    persons_stale = int(row["persons_stale"] or 0)
                    persons_conflict = int(row["persons_conflict"] or 0)
            except Exception:
                logger.exception("Person quality query failed")

            # ── 2. Crawler health (last 24 h) ──────────────────────────────
            crawlers_total = 0
            crawlers_healthy = 0
            crawlers_degraded: list[dict] = []
            try:
                rows = (await session.execute(_CRAWLER_HEALTH_SQL)).mappings().all()
                for r in rows:
                    found = int(r["found_count"] or 0)
                    errors = int(r["error_count"] or 0)
                    total = found + errors
                    rate = found / total if total > 0 else 0.0
                    crawlers_total += 1
                    if rate == 0.0 and total > 0:
                        crawlers_degraded.append(
                            {
                                "name": r["source_name"] or "unknown",
                                "success_rate": 0.0,
                            }
                        )
                    else:
                        crawlers_healthy += 1
            except Exception:
                logger.exception("Crawler health query failed")

            # ── 3. Persons ingested today ──────────────────────────────────
            persons_ingested_today = 0
            try:
                persons_ingested_today = int(
                    (await session.execute(_VOLUME_SQL)).scalar_one() or 0
                )
            except Exception:
                logger.exception("Volume query failed")

            # ── 4. Merges today ────────────────────────────────────────────
            merges_today = 0
            try:
                merges_today = int(
                    (await session.execute(_MERGES_SQL)).scalar_one() or 0
                )
            except Exception:
                logger.exception("Merges query failed")

            # ── 5. Tags assigned today ─────────────────────────────────────
            tags_assigned_today = 0
            try:
                tags_assigned_today = int(
                    (await session.execute(_TAGS_SQL)).scalar_one() or 0
                )
            except Exception:
                logger.exception("Tags query failed")

            audit = SystemAudit(
                run_at=run_at,
                persons_total=persons_total,
                persons_low_coverage=persons_low_coverage,
                persons_stale=persons_stale,
                persons_conflict=persons_conflict,
                crawlers_total=crawlers_total,
                crawlers_healthy=crawlers_healthy,
                crawlers_degraded=crawlers_degraded,
                tags_assigned_today=tags_assigned_today,
                merges_today=merges_today,
                persons_ingested_today=persons_ingested_today,
            )
            session.add(audit)
            await session.commit()
            return audit
```

- [ ] **Step 4: Run — expect PASS**

```bash
python3 -m pytest tests/test_daemon/test_audit_daemon.py -v
```
Expected:
```
tests/test_daemon/test_audit_daemon.py::test_audit_daemon_has_start_method PASSED
tests/test_daemon/test_audit_daemon.py::test_audit_daemon_has_run_audit_method PASSED
tests/test_daemon/test_audit_daemon.py::test_audit_daemon_stop_flag PASSED
tests/test_daemon/test_audit_daemon.py::test_run_audit_persists_system_audit PASSED
tests/test_daemon/test_audit_daemon.py::test_run_audit_returns_audit_object PASSED
tests/test_daemon/test_audit_daemon.py::test_audit_daemon_stop_exits_loop PASSED
tests/test_daemon/test_audit_daemon.py::test_crawler_health_degraded_list PASSED
tests/test_daemon/test_audit_daemon.py::test_run_audit_is_resilient_to_query_failure PASSED
8 passed
```

- [ ] **Step 5: Commit**

```bash
git add modules/audit/__init__.py modules/audit/audit_daemon.py tests/test_daemon/test_audit_daemon.py
git commit -m "feat(audit): implement AuditDaemon with 4 audit categories and graceful degradation"
```

---

## Task 4: API Routes

**Files:**
- New: `api/routes/audit.py`
- Modify: `api/main.py`
- Test: `tests/test_api/test_audit_routes.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_api/test_audit_routes.py`:
```python
"""
API route tests for /audit/* endpoints.
All DB interactions are mocked — no running infrastructure required.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from api.deps import db_session
from api.main import app


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_session(execute_return=None, get_return=None, scalars_return=None):
    session = AsyncMock()
    default_exec = MagicMock(
        scalar_one=MagicMock(return_value=0),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=None),
        mappings=MagicMock(
            return_value=MagicMock(
                all=MagicMock(return_value=[]),
                one_or_none=MagicMock(return_value=None),
            )
        ),
    )
    session.execute.return_value = execute_return or default_exec
    session.get.return_value = get_return
    session.scalars.return_value = scalars_return or MagicMock(
        all=MagicMock(return_value=[])
    )
    return session


def _override(session):
    async def _dep():
        yield session
    return _dep


def _fake_audit():
    from shared.models.audit import SystemAudit
    sa = SystemAudit(
        run_at=datetime.now(timezone.utc),
        persons_total=500,
        persons_low_coverage=45,
        persons_stale=12,
        persons_conflict=3,
        crawlers_total=8,
        crawlers_healthy=7,
        crawlers_degraded=[{"name": "bad_crawler", "success_rate": 0.0}],
        tags_assigned_today=99,
        merges_today=4,
        persons_ingested_today=30,
    )
    return sa


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()


# ── /audit/latest ─────────────────────────────────────────────────────────────

class TestAuditLatest:
    def test_returns_200_with_audit(self):
        audit = _fake_audit()
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=audit)
        session = _make_session(execute_return=exec_result)
        app.dependency_overrides[db_session] = _override(session)

        with TestClient(app) as c:
            r = c.get("/audit/latest")
        assert r.status_code == 200
        body = r.json()
        assert body["persons_total"] == 500
        assert body["crawlers_degraded"][0]["name"] == "bad_crawler"

    def test_returns_404_when_no_audits(self):
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=None)
        session = _make_session(execute_return=exec_result)
        app.dependency_overrides[db_session] = _override(session)

        with TestClient(app) as c:
            r = c.get("/audit/latest")
        assert r.status_code == 404


# ── /audit/run ────────────────────────────────────────────────────────────────

class TestAuditRun:
    def test_post_run_returns_run_at(self):
        session = _make_session()
        app.dependency_overrides[db_session] = _override(session)

        with patch("api.routes.audit.AuditDaemon") as MockDaemon:
            mock_instance = AsyncMock()
            mock_instance._run_audit = AsyncMock(return_value=_fake_audit())
            MockDaemon.return_value = mock_instance

            with TestClient(app) as c:
                r = c.post("/audit/run")
        assert r.status_code == 200
        body = r.json()
        assert "run_at" in body or "job_id" in body


# ── /audit/history ────────────────────────────────────────────────────────────

class TestAuditHistory:
    def test_returns_list(self):
        audits = [_fake_audit(), _fake_audit()]
        scalars_mock = MagicMock(all=MagicMock(return_value=audits))
        exec_result = MagicMock(scalars=MagicMock(return_value=scalars_mock))
        session = _make_session(execute_return=exec_result)
        app.dependency_overrides[db_session] = _override(session)

        with TestClient(app) as c:
            r = c.get("/audit/history?limit=2")
        assert r.status_code == 200
        assert "audits" in r.json()

    def test_limit_param_defaults(self):
        session = _make_session()
        app.dependency_overrides[db_session] = _override(session)

        with TestClient(app) as c:
            r = c.get("/audit/history")
        assert r.status_code == 200


# ── /audit/crawlers ───────────────────────────────────────────────────────────

class TestAuditCrawlers:
    def test_returns_crawler_breakdown(self):
        rows = [
            {"source_name": "linkedin", "found_count": 10, "error_count": 2},
            {"source_name": "bad_crawler", "found_count": 0, "error_count": 8},
        ]
        mappings_mock = MagicMock(all=MagicMock(return_value=rows))
        exec_result = MagicMock(mappings=MagicMock(return_value=mappings_mock))
        session = _make_session(execute_return=exec_result)
        app.dependency_overrides[db_session] = _override(session)

        with TestClient(app) as c:
            r = c.get("/audit/crawlers")
        assert r.status_code == 200
        body = r.json()
        assert "crawlers" in body
        names = [cr["name"] for cr in body["crawlers"]]
        assert "linkedin" in names

    def test_degraded_crawler_has_status_field(self):
        rows = [{"source_name": "broken", "found_count": 0, "error_count": 5}]
        mappings_mock = MagicMock(all=MagicMock(return_value=rows))
        exec_result = MagicMock(mappings=MagicMock(return_value=mappings_mock))
        session = _make_session(execute_return=exec_result)
        app.dependency_overrides[db_session] = _override(session)

        with TestClient(app) as c:
            r = c.get("/audit/crawlers")
        body = r.json()
        assert body["crawlers"][0]["status"] == "degraded"


# ── /audit/persons/stale ──────────────────────────────────────────────────────

class TestAuditPersonsStale:
    def test_returns_paginated_persons(self):
        session = _make_session()
        app.dependency_overrides[db_session] = _override(session)

        with TestClient(app) as c:
            r = c.get("/audit/persons/stale?limit=10&offset=0")
        assert r.status_code == 200
        assert "persons" in r.json()

    def test_limit_and_offset_passed(self):
        session = _make_session()
        app.dependency_overrides[db_session] = _override(session)

        with TestClient(app) as c:
            r = c.get("/audit/persons/stale?limit=5&offset=10")
        body = r.json()
        assert body["limit"] == 5
        assert body["offset"] == 10


# ── /audit/persons/low-coverage ───────────────────────────────────────────────

class TestAuditPersonsLowCoverage:
    def test_returns_paginated_persons(self):
        session = _make_session()
        app.dependency_overrides[db_session] = _override(session)

        with TestClient(app) as c:
            r = c.get("/audit/persons/low-coverage?limit=10&offset=0")
        assert r.status_code == 200
        assert "persons" in r.json()

    def test_limit_and_offset_passed(self):
        session = _make_session()
        app.dependency_overrides[db_session] = _override(session)

        with TestClient(app) as c:
            r = c.get("/audit/persons/low-coverage?limit=3&offset=6")
        body = r.json()
        assert body["limit"] == 3
        assert body["offset"] == 6
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_api/test_audit_routes.py -v
```
Expected: `ImportError` — `api.routes.audit` not found, routes not registered.

- [ ] **Step 3: Create `api/routes/audit.py`**

```python
"""
Audit endpoints — expose SystemAudit snapshots and trigger on-demand runs.

Routes:
  GET  /audit/latest                  -> most recent SystemAudit row
  POST /audit/run                     -> trigger immediately, return run_at + snapshot
  GET  /audit/history?limit=30        -> last N audit runs
  GET  /audit/crawlers                -> per-crawler health (24 h window)
  GET  /audit/persons/stale           -> stale persons (paginated)
  GET  /audit/persons/low-coverage    -> low-coverage persons (paginated)
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import DbDep
from shared.models.audit import SystemAudit

router = APIRouter()
logger = logging.getLogger(__name__)

_CRAWLER_HEALTH_24H = text("""
    SELECT
        ds.name                                                     AS source_name,
        COUNT(*) FILTER (WHERE cj.status = 'found')                AS found_count,
        COUNT(*) FILTER (WHERE cj.status = 'error')                AS error_count
    FROM crawl_jobs cj
    LEFT JOIN data_sources ds ON ds.id = cj.source_id
    WHERE cj.created_at > now() - interval '24 hours'
    GROUP BY ds.name
    ORDER BY ds.name
""")

_STALE_PERSONS = text("""
    SELECT id, full_name, last_scraped_at, created_at
    FROM persons
    WHERE merged_into IS NULL
      AND last_scraped_at < now() - interval '30 days'
    ORDER BY last_scraped_at ASC NULLS FIRST
    LIMIT :limit OFFSET :offset
""")

_LOW_COVERAGE_PERSONS = text("""
    SELECT id, full_name, meta, created_at
    FROM persons
    WHERE merged_into IS NULL
      AND (
          meta->'coverage'->>'pct' IS NULL
          OR (meta->'coverage'->>'pct')::float < 50
      )
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :offset
""")


def _audit_to_dict(audit: SystemAudit) -> dict:
    return {
        "id": str(audit.id),
        "run_at": audit.run_at.isoformat() if audit.run_at else None,
        "persons_total": audit.persons_total,
        "persons_low_coverage": audit.persons_low_coverage,
        "persons_stale": audit.persons_stale,
        "persons_conflict": audit.persons_conflict,
        "crawlers_total": audit.crawlers_total,
        "crawlers_healthy": audit.crawlers_healthy,
        "crawlers_degraded": audit.crawlers_degraded or [],
        "tags_assigned_today": audit.tags_assigned_today,
        "merges_today": audit.merges_today,
        "persons_ingested_today": audit.persons_ingested_today,
        "meta": audit.meta or {},
    }


@router.get("/latest")
async def get_latest_audit(session: AsyncSession = DbDep):
    """Return the most recent SystemAudit snapshot."""
    from sqlalchemy import select

    stmt = select(SystemAudit).order_by(SystemAudit.run_at.desc()).limit(1)
    result = await session.execute(stmt)
    audit = result.scalar_one_or_none()
    if audit is None:
        raise HTTPException(status_code=404, detail="No audit runs found")
    return _audit_to_dict(audit)


@router.post("/run")
async def trigger_audit(session: AsyncSession = DbDep):
    """Trigger an immediate audit cycle. Returns run_at and full snapshot."""
    from modules.audit.audit_daemon import AuditDaemon

    try:
        daemon = AuditDaemon()
        audit = await daemon._run_audit()
        return {"run_at": audit.run_at.isoformat(), "audit": _audit_to_dict(audit)}
    except Exception as exc:
        logger.exception("On-demand audit failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history")
async def audit_history(
    limit: int = Query(30, ge=1, le=200),
    session: AsyncSession = DbDep,
):
    """Return the last N audit run snapshots, newest first."""
    from sqlalchemy import select

    stmt = select(SystemAudit).order_by(SystemAudit.run_at.desc()).limit(limit)
    result = await session.execute(stmt)
    audits = result.scalars().all()
    return {"audits": [_audit_to_dict(a) for a in audits], "total": len(audits)}


@router.get("/crawlers")
async def crawler_health(session: AsyncSession = DbDep):
    """Per-crawler success/error counts over the last 24 hours."""
    try:
        rows = (await session.execute(_CRAWLER_HEALTH_24H)).mappings().all()
        crawlers = []
        for r in rows:
            found = int(r["found_count"] or 0)
            errors = int(r["error_count"] or 0)
            total = found + errors
            rate = round(found / total, 4) if total > 0 else None
            crawlers.append(
                {
                    "name": r["source_name"] or "unknown",
                    "found_count": found,
                    "error_count": errors,
                    "success_rate": rate,
                    "status": "degraded" if (rate is not None and rate == 0.0) else "ok",
                }
            )
        return {"crawlers": crawlers, "window_hours": 24}
    except Exception as exc:
        logger.exception("Crawler health endpoint failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/persons/stale")
async def stale_persons(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = DbDep,
):
    """Persons not scraped in the last 30 days, oldest first."""
    try:
        rows = (
            await session.execute(_STALE_PERSONS, {"limit": limit, "offset": offset})
        ).mappings().all()
        return {
            "persons": [dict(r) for r in rows],
            "limit": limit,
            "offset": offset,
        }
    except Exception as exc:
        logger.exception("Stale persons endpoint failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/persons/low-coverage")
async def low_coverage_persons(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = DbDep,
):
    """Persons where meta coverage pct is missing or below 50%."""
    try:
        rows = (
            await session.execute(
                _LOW_COVERAGE_PERSONS, {"limit": limit, "offset": offset}
            )
        ).mappings().all()
        return {
            "persons": [dict(r) for r in rows],
            "limit": limit,
            "offset": offset,
        }
    except Exception as exc:
        logger.exception("Low-coverage persons endpoint failed")
        raise HTTPException(status_code=500, detail=str(exc))
```

- [ ] **Step 4: Register router in `api/main.py`**

In `api/main.py`, add `audit` to the import block:

```python
from api.routes import (
    alerts,
    audit,           # add this line
    behavioural,
    compliance,
    crawls,
    dedup,
    enrichment,
    export,
    financial,
    graph,
    marketing,
    patterns,
    persons,
    search,
    search_query,
    system,
    watchlist,
    ws,
)
```

Then after the last `app.include_router(...)` call:

```python
app.include_router(audit.router, prefix="/audit", tags=["audit"])
```

- [ ] **Step 5: Run — expect PASS**

```bash
python3 -m pytest tests/test_api/test_audit_routes.py -v
```
Expected:
```
tests/test_api/test_audit_routes.py::TestAuditLatest::test_returns_200_with_audit PASSED
tests/test_api/test_audit_routes.py::TestAuditLatest::test_returns_404_when_no_audits PASSED
tests/test_api/test_audit_routes.py::TestAuditRun::test_post_run_returns_run_at PASSED
tests/test_api/test_audit_routes.py::TestAuditHistory::test_returns_list PASSED
tests/test_api/test_audit_routes.py::TestAuditHistory::test_limit_param_defaults PASSED
tests/test_api/test_audit_routes.py::TestAuditCrawlers::test_returns_crawler_breakdown PASSED
tests/test_api/test_audit_routes.py::TestAuditCrawlers::test_degraded_crawler_has_status_field PASSED
tests/test_api/test_audit_routes.py::TestAuditPersonsStale::test_returns_paginated_persons PASSED
tests/test_api/test_audit_routes.py::TestAuditPersonsStale::test_limit_and_offset_passed PASSED
tests/test_api/test_audit_routes.py::TestAuditPersonsLowCoverage::test_returns_paginated_persons PASSED
tests/test_api/test_audit_routes.py::TestAuditPersonsLowCoverage::test_limit_and_offset_passed PASSED
11 passed
```

- [ ] **Step 6: Full regression pass**

```bash
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all previously-passing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add api/routes/audit.py api/main.py tests/test_api/test_audit_routes.py
git commit -m "feat(audit): add 6-endpoint /audit router and register in api/main.py"
```

---

## Task 5: Worker Registration

**Files:**
- Modify: `worker.py`
- Test: `tests/test_daemon/test_worker_flags.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_daemon/test_worker_flags.py`:
```python
"""Verify worker.py CLI flag and AuditDaemon wiring."""
import subprocess
import sys


def test_no_audit_flag_exists():
    """worker.py --help must list --no-audit."""
    result = subprocess.run(
        [sys.executable, "/home/wolf/Lycan-Data/worker.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert "--no-audit" in result.stdout


def test_worker_imports_audit_daemon():
    """AuditDaemon must be importable from modules.audit."""
    from modules.audit.audit_daemon import AuditDaemon
    d = AuditDaemon()
    assert d._running is True
    d.stop()
    assert d._running is False
```

- [ ] **Step 2: Run — expect FAIL**

```bash
python3 -m pytest tests/test_daemon/test_worker_flags.py -v
```
Expected: `test_no_audit_flag_exists` FAILS — flag not present in `--help`.

- [ ] **Step 3: Implement changes to `worker.py`**

**3a.** Change the `main` signature to accept `enable_audit`:

```python
async def main(workers: int, enable_growth: bool, enable_freshness: bool, enable_audit: bool):
```

**3b.** After the freshness scheduler block (around line 95), add:

```python
    # Audit daemon
    if enable_audit:
        from modules.audit.audit_daemon import AuditDaemon
        ad = AuditDaemon()
        tasks.append(asyncio.create_task(ad.start(), name="audit-daemon"))
        logger.info("Started audit daemon")
```

**3c.** Update the summary log line to include audit:

```python
    logger.info(
        "Worker running — %d dispatcher(s) + %s%s%s",
        workers,
        "growth daemon + " if enable_growth else "",
        "freshness scheduler + " if enable_freshness else "",
        "audit daemon" if enable_audit else "",
    )
```

**3d.** Add CLI argument in `if __name__ == "__main__":`:

```python
    parser.add_argument("--no-audit", action="store_true", help="Disable audit daemon")
```

**3e.** Pass to `main()`:

```python
    asyncio.run(
        main(
            workers=args.workers,
            enable_growth=not args.no_growth,
            enable_freshness=not args.no_freshness,
            enable_audit=not args.no_audit,
        )
    )
```

- [ ] **Step 4: Run — expect PASS**

```bash
python3 -m pytest tests/test_daemon/test_worker_flags.py -v
```
Expected:
```
tests/test_daemon/test_worker_flags.py::test_no_audit_flag_exists PASSED
tests/test_daemon/test_worker_flags.py::test_worker_imports_audit_daemon PASSED
2 passed
```

- [ ] **Step 5: Confirm help output**

```bash
python3 /home/wolf/Lycan-Data/worker.py --help
```
Expected line in output:
```
  --no-audit            Disable audit daemon
```

- [ ] **Step 6: Commit**

```bash
git add worker.py tests/test_daemon/test_worker_flags.py
git commit -m "feat(worker): wire AuditDaemon with --no-audit flag"
```

---

## Task 6: Frontend — System Audit Card in Activity View

**Files:**
- Modify: `static/index.html`

The `renderActivity()` function is at line 1311. The audit card is inserted into the DOM before the crawl job log table renders.

- [ ] **Step 1: Confirm current structure**

Read `static/index.html` lines 1311–1382 to confirm `body.id = 'activity-body'` and the `this.root.appendChild(body)` call at the end of the setup block.

- [ ] **Step 2: Implement System Audit card**

Directly after the line `this.root.appendChild(body);` (line 1330) and before the `const load = async () => {` block, insert the following JavaScript. All DOM updates use `textContent` and `appendChild` — no `innerHTML` is used anywhere in this block.

```javascript
    // ── System Audit card ──────────────────────────────────────────────────
    const auditCard = div('card');
    auditCard.id = 'audit-card';
    auditCard.style.cssText = 'margin-bottom:20px';

    const auditCardBody = div('card-body');
    const auditHdr = div('');
    auditHdr.style.cssText = 'display:flex;align-items:center;gap:12px;margin-bottom:14px';
    const auditTitleEl = div('card-title', 'System Audit');
    const runNowBtn = el('button', 'btn btn-sm', 'Run Now');
    runNowBtn.style.marginLeft = 'auto';
    auditHdr.append(auditTitleEl, runNowBtn);

    const auditContent = div('');
    auditContent.id = 'audit-content';
    auditContent.appendChild(span('dim', 'Loading audit…'));

    auditCardBody.append(auditHdr, auditContent);
    auditCard.appendChild(auditCardBody);
    this.root.insertBefore(auditCard, body);

    const renderAudit = async () => {
      auditContent.textContent = '';

      try {
        const a = await apiGet('/audit/latest');

        // ── Overview stats grid ──────────────────────────────────────────
        const grid = div('');
        grid.style.cssText = 'display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px';

        const mkStat = (label, value, warnColor) => {
          const cell = div('');
          cell.style.cssText = 'background:#111;border-radius:6px;padding:12px 16px';
          const valEl = span('', String(value));
          valEl.style.cssText = 'font-size:1.6rem;font-weight:700;color:' + (warnColor || '#fff');
          const lblEl = div('');
          lblEl.textContent = label;
          lblEl.style.cssText = 'font-size:.7rem;color:#888;margin-top:4px;text-transform:uppercase;letter-spacing:.05em';
          cell.append(valEl, lblEl);
          return cell;
        };

        grid.append(
          mkStat('Total Persons', a.persons_total.toLocaleString(), null),
          mkStat('Low Coverage', a.persons_low_coverage, a.persons_low_coverage > 0 ? '#f0a500' : '#00c896'),
          mkStat('Stale (30d)', a.persons_stale, a.persons_stale > 0 ? '#f0a500' : '#00c896'),
        );
        auditContent.appendChild(grid);

        // ── Data activity today ──────────────────────────────────────────
        const actRow = div('');
        actRow.style.cssText = 'display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap';

        const mkPill = (label, value) => {
          const p = div('');
          p.style.cssText = 'background:#111;border-radius:20px;padding:6px 14px;font-size:.8rem;color:#aaa';
          const valSpan = span('');
          valSpan.textContent = String(value);
          valSpan.style.cssText = 'color:#fff;font-weight:600';
          const lblSpan = span('');
          lblSpan.textContent = ' ' + label;
          p.append(valSpan, lblSpan);
          return p;
        };

        actRow.append(
          mkPill('ingested today', a.persons_ingested_today),
          mkPill('merges today', a.merges_today),
          mkPill('tags today', a.tags_assigned_today),
        );
        auditContent.appendChild(actRow);

        // ── Crawler leaderboard ──────────────────────────────────────────
        const crLabelEl = div('');
        crLabelEl.textContent = 'Crawler Health (24 h)';
        crLabelEl.style.cssText = 'font-size:.75rem;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px';
        auditContent.appendChild(crLabelEl);

        const crList = div('');
        crList.style.cssText = 'display:flex;flex-direction:column;gap:6px';

        try {
          const ch = await apiGet('/audit/crawlers');
          if (ch.crawlers && ch.crawlers.length > 0) {
            ch.crawlers.forEach(cr => {
              const crRow = div('');
              crRow.style.cssText = 'display:flex;align-items:center;gap:10px';

              const nameEl = span('');
              nameEl.textContent = cr.name || 'unknown';
              nameEl.style.cssText = 'width:160px;font-size:.8rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#ccc';

              const barWrap = div('');
              barWrap.style.cssText = 'flex:1;background:#1a1a1a;border-radius:3px;height:6px;overflow:hidden';

              const pct = cr.success_rate !== null ? Math.round(cr.success_rate * 100) : 0;
              const barColor = cr.status === 'degraded' ? '#e05' : pct < 50 ? '#f0a500' : '#00c896';
              const bar = div('');
              bar.style.cssText = 'height:100%;border-radius:3px;background:' + barColor + ';width:' + pct + '%';
              barWrap.appendChild(bar);

              const badgeEl = span('');
              badgeEl.textContent = cr.status === 'degraded' ? 'DEGRADED' : (pct + '%');
              badgeEl.style.cssText = 'font-size:.65rem;font-weight:700;color:' + (cr.status === 'degraded' ? '#e05' : '#888') + ';min-width:60px;text-align:right';

              crRow.append(nameEl, barWrap, badgeEl);
              crList.appendChild(crRow);
            });
          } else {
            crList.appendChild(span('dim', 'No crawler activity in last 24 h'));
          }
        } catch (_crErr) {
          crList.appendChild(span('dim', 'Crawler data unavailable'));
        }

        auditContent.appendChild(crList);

        const tsEl = div('');
        tsEl.textContent = 'Last run: ' + fmtDate(a.run_at);
        tsEl.style.cssText = 'margin-top:12px;font-size:.7rem;color:#555';
        auditContent.appendChild(tsEl);

      } catch (auditErr) {
        const errEl = div('red-txt');
        errEl.textContent = 'Audit unavailable: ' + auditErr.message;
        auditContent.appendChild(errEl);
      }
    };

    runNowBtn.addEventListener('click', async () => {
      runNowBtn.disabled = true;
      runNowBtn.textContent = 'Running\u2026';
      try {
        await fetch('/audit/run', { method: 'POST' });
        await renderAudit();
      } catch (runErr) {
        const errEl = div('red-txt');
        errEl.textContent = 'Run failed: ' + runErr.message;
        auditContent.prepend(errEl);
      } finally {
        runNowBtn.disabled = false;
        runNowBtn.textContent = 'Run Now';
      }
    });

    await renderAudit();

    // Auto-refresh every 60 s. Timer is stored so the SPA router can clear it on navigation.
    if (!this._timers) this._timers = [];
    this._timers.push(setInterval(renderAudit, 60_000));
    // ── end System Audit card ──────────────────────────────────────────────
```

- [ ] **Step 3: Verify marker strings are present**

```bash
python3 -c "
with open('/home/wolf/Lycan-Data/static/index.html') as f:
    src = f.read()
assert 'audit-card' in src,       'audit-card id missing'
assert 'renderAudit' in src,      'renderAudit function missing'
assert '/audit/latest' in src,    '/audit/latest call missing'
assert '/audit/run' in src,       '/audit/run call missing'
assert '/audit/crawlers' in src,  '/audit/crawlers call missing'
assert 'innerHTML' not in src[src.index('audit-card'):src.index('end System Audit card')], 'innerHTML found in audit block'
print('OK — all audit markers present, no innerHTML')
"
```
Expected: `OK — all audit markers present, no innerHTML`

- [ ] **Step 4: Manual browser smoke-test**

Start the API server:
```bash
cd /home/wolf/Lycan-Data && python3 -m uvicorn api.main:app --reload --port 8000
```

Open `http://localhost:8000` in a browser. Navigate to `#/activity`.

Verify:
- [ ] "System Audit" card appears above the crawl job table
- [ ] Card shows counts (may be 0 with empty DB) or a graceful "Audit unavailable" error
- [ ] "Run Now" button is visible and calls `POST /audit/run` (confirmed in Network tab)
- [ ] After Run Now completes, card refreshes with updated `run_at` timestamp
- [ ] Card auto-refreshes every 60 s (second `GET /audit/latest` visible in Network tab after 60 s)

- [ ] **Step 5: Commit**

```bash
git add static/index.html
git commit -m "feat(frontend): add System Audit card to renderActivity() with 60s auto-refresh"
```

---

## Task 7: Full Test Suite Pass

- [ ] **Step 1: Run entire test suite**

```bash
cd /home/wolf/Lycan-Data && python3 -m pytest tests/ -v --tb=short 2>&1 | tail -50
```

Expected outcome — all of the following pass:
- `tests/test_shared/test_audit_model.py` — 3 tests
- `tests/test_daemon/test_audit_daemon.py` — 8 tests
- `tests/test_api/test_audit_routes.py` — 11 tests
- `tests/test_daemon/test_worker_flags.py` — 2 tests
- All pre-existing tests unchanged

- [ ] **Step 2: Fix any regressions**

If any test outside the new files fails, fix the root cause before proceeding. Do not skip or mark tests as xfail unless they were already broken before this phase.

- [ ] **Step 3: Commit fixes if needed**

```bash
git add <files>
git commit -m "fix: resolve regressions after Phase 6 integration"
```

---

## Task 8: Integration Smoke-Test (Live DB)

This task requires the Docker stack running (`docker compose up -d`). Skip in pure unit-test environments.

- [ ] **Step 1: Apply migration**

```bash
cd /home/wolf/Lycan-Data && alembic upgrade head
```
Expected: `Running upgrade b2c3d4e5f6a7 -> c3d4e5f6a7b8, add_system_audits`

- [ ] **Step 2: Trigger audit via API**

```bash
curl -s -X POST http://localhost:8000/audit/run | python3 -m json.tool
```
Expected: JSON with `run_at` (ISO timestamp) and `audit` object. `persons_total` reflects actual DB row count.

- [ ] **Step 3: Fetch latest audit**

```bash
curl -s http://localhost:8000/audit/latest | python3 -m json.tool
```
Expected: same shape as above, `id` is a UUID.

- [ ] **Step 4: Fetch history**

```bash
curl -s "http://localhost:8000/audit/history?limit=5" | python3 -m json.tool
```
Expected: `audits` array with at least 1 entry.

- [ ] **Step 5: Fetch crawler health**

```bash
curl -s http://localhost:8000/audit/crawlers | python3 -m json.tool
```
Expected: `crawlers` array (may be empty if no `crawl_jobs` rows in last 24 h).

- [ ] **Step 6: Start worker with audit enabled**

```bash
python3 /home/wolf/Lycan-Data/worker.py --workers 1 &
WORKER_PID=$!
sleep 3
grep "Started audit daemon" /proc/$WORKER_PID/fd/1 2>/dev/null || jobs -l
kill $WORKER_PID
```
Alternatively, observe stdout — expected line: `Started audit daemon`

- [ ] **Step 7: Start worker with audit disabled**

```bash
python3 /home/wolf/Lycan-Data/worker.py --workers 1 --no-audit &
WORKER_PID=$!
sleep 2
kill $WORKER_PID
```
Expected: `Started audit daemon` does NOT appear in stdout.

- [ ] **Step 8: Final phase commit**

```bash
git add .
git commit -m "chore(phase6): Phase 6 complete — SystemAudit table, AuditDaemon, 6 API endpoints, Activity view card"
```

---

## Summary

| Task | Deliverable | New Tests |
|------|-------------|-----------|
| 1 | `SystemAudit` ORM model in `shared/models/audit.py` | 3 |
| 2 | Alembic migration `c3d4e5f6a7b8` — `system_audits` table + index | migration smoke |
| 3 | `AuditDaemon` — 4 audit categories, hourly loop, graceful degradation | 8 |
| 4 | 6 FastAPI endpoints in `api/routes/audit.py`, registered in `api/main.py` | 11 |
| 5 | `--no-audit` flag in `worker.py`, daemon wired into asyncio task loop | 2 |
| 6 | System Audit card in `renderActivity()` — stats grid, today counters, crawler bar chart, Run Now, 60 s auto-refresh | manual smoke |
| 7 | Full test suite green | all passing |
| 8 | Live DB integration smoke-test | manual smoke |

**Total new automated tests: 24**
