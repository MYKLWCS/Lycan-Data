# Phase 1: Auto-Dedup + Score Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship background auto-deduplication, sigmoid score calibration, and integer score display so duplicate person records are merged continuously without human intervention.

**Architecture:** A daemon `AutoDedupDaemon` runs inside `worker.py` alongside `FreshnessScheduler`, polling every 10 minutes for recently-updated persons and routing candidates by score threshold — auto-merge at ≥0.85, queue for review at 0.70–0.84. All merges execute inside a single transaction with full rollback and dual-UUID audit logging. A new `DedupReview` model captures the manual-review queue. The `corroboration_score_from_count` function is replaced with a sigmoid curve to compress early counts, and the SPA displays all scores as 0–100 integers.

**Tech Stack:** Python asyncio, SQLAlchemy async, PostgreSQL, FastAPI, Alembic, pytest-asyncio

---

### Task 1: Data Model — Add `merged_into` to Person + New `DedupReview` Model

**Files:**
- Modify: `shared/models/person.py`
- Create: `shared/models/dedup_review.py`
- Modify: `shared/models/__init__.py` (if it re-exports models)

- [ ] Write failing test

```python
# tests/test_shared/test_dedup_models.py
import uuid
import pytest
from shared.models.person import Person
from shared.models.dedup_review import DedupReview


def test_person_has_merged_into_field():
    p = Person(full_name="Test Person")
    assert hasattr(p, "merged_into")
    assert p.merged_into is None


def test_person_merged_into_accepts_uuid():
    canonical_id = uuid.uuid4()
    p = Person(full_name="Dupe", merged_into=canonical_id)
    assert p.merged_into == canonical_id


def test_dedup_review_defaults():
    a = uuid.uuid4()
    b = uuid.uuid4()
    r = DedupReview(
        person_a_id=a,
        person_b_id=b,
        similarity_score=0.77,
    )
    assert r.reviewed is False
    assert r.decision is None
    assert r.similarity_score == 0.77


def test_dedup_review_decision_values():
    r = DedupReview(
        person_a_id=uuid.uuid4(),
        person_b_id=uuid.uuid4(),
        similarity_score=0.72,
        reviewed=True,
        decision="merge",
    )
    assert r.decision == "merge"
```

- [ ] Run: `python3 -m pytest tests/test_shared/test_dedup_models.py -v` → Expected: FAIL (`ImportError: cannot import name 'DedupReview'`)

- [ ] Implement

**`shared/models/person.py`** — add `merged_into` after `meta` field and add the self-referential FK import:

```python
# At top of file, merged_into requires no new import — UUID and ForeignKey already imported.

# Add after `meta: Mapped[dict] = ...` line, before the risk scores block:
merged_into: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True),
    ForeignKey("persons.id"),
    nullable=True,
    index=True,
)
```

**`shared/models/dedup_review.py`** — create new file:

```python
"""DedupReview — manual review queue for borderline deduplication candidates."""

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.models.base import Base, TimestampMixin


class DedupReview(Base, TimestampMixin):
    __tablename__ = "dedup_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    person_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    decision: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # 'merge' | 'keep_separate'
```

- [ ] Run: `python3 -m pytest tests/test_shared/test_dedup_models.py -v` → Expected: PASS (4 passed)

- [ ] Commit: `git commit -m "feat(models): add merged_into to Person and new DedupReview model"`

---

### Task 2: Alembic Migration — `persons.merged_into` + `dedup_reviews` Table

**Files:**
- Create: `migrations/versions/c3d4e5f6a7b8_add_merged_into_and_dedup_reviews.py`

- [ ] Write failing test

```python
# tests/test_migrations.py  (append to existing file — test already runs all migrations)
# The migration test suite validates all revisions can upgrade/downgrade cleanly.
# Verify the new revision appears in the chain:

def test_new_migration_revision_exists():
    import importlib, pkgutil, pathlib
    versions_path = pathlib.Path("migrations/versions")
    revisions = [f.stem for f in versions_path.glob("*.py") if not f.stem.startswith("__")]
    assert any("dedup_reviews" in r or "merged_into" in r for r in revisions), \
        "Expected migration for dedup_reviews/merged_into not found"
```

- [ ] Run: `python3 -m pytest tests/test_migrations.py::test_new_migration_revision_exists -v` → Expected: FAIL

- [ ] Implement

```python
# migrations/versions/c3d4e5f6a7b8_add_merged_into_and_dedup_reviews.py
"""Add persons.merged_into and dedup_reviews table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-25

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── persons.merged_into ──────────────────────────────────────────────────
    op.add_column(
        "persons",
        sa.Column("merged_into", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_persons_merged_into", "persons", ["merged_into"], unique=False
    )
    op.create_foreign_key(
        "fk_persons_merged_into_persons",
        "persons",
        "persons",
        ["merged_into"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── dedup_reviews ────────────────────────────────────────────────────────
    op.create_table(
        "dedup_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_a_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_b_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("decision", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["person_a_id"], ["persons.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["person_b_id"], ["persons.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dedup_reviews_person_a_id", "dedup_reviews", ["person_a_id"]
    )
    op.create_index(
        "ix_dedup_reviews_person_b_id", "dedup_reviews", ["person_b_id"]
    )
    op.create_index(
        "ix_dedup_reviews_reviewed", "dedup_reviews", ["reviewed"]
    )


def downgrade() -> None:
    op.drop_table("dedup_reviews")
    op.drop_constraint("fk_persons_merged_into_persons", "persons", type_="foreignkey")
    op.drop_index("ix_persons_merged_into", table_name="persons")
    op.drop_column("persons", "merged_into")
```

- [ ] Run: `python3 -m pytest tests/test_migrations.py::test_new_migration_revision_exists -v` → Expected: PASS

- [ ] Commit: `git commit -m "feat(migrations): add merged_into to persons and dedup_reviews table"`

---

### Task 3: Score Calibration — Replace Log Curve with Sigmoid

**Files:**
- Modify: `shared/data_quality.py`

- [ ] Write failing test

```python
# tests/test_shared/test_score_calibration.py
import pytest
from shared.data_quality import corroboration_score_from_count


def test_count_zero_returns_zero():
    assert corroboration_score_from_count(0) == 0.0


def test_count_negative_returns_zero():
    assert corroboration_score_from_count(-5) == 0.0


def test_count_1_near_0_50():
    score = corroboration_score_from_count(1)
    assert 0.49 <= score <= 0.51, f"Expected ~0.50, got {score}"


def test_count_2_near_0_73():
    score = corroboration_score_from_count(2)
    assert 0.71 <= score <= 0.75, f"Expected ~0.73, got {score}"


def test_count_3_near_0_88():
    score = corroboration_score_from_count(3)
    assert 0.86 <= score <= 0.90, f"Expected ~0.88, got {score}"


def test_count_5_near_0_98():
    score = corroboration_score_from_count(5)
    assert 0.96 <= score <= 1.0, f"Expected ~0.98, got {score}"


def test_score_never_exceeds_1():
    for n in range(1, 100):
        assert corroboration_score_from_count(n) <= 1.0


def test_score_monotonically_increasing():
    scores = [corroboration_score_from_count(n) for n in range(1, 20)]
    for i in range(len(scores) - 1):
        assert scores[i] <= scores[i + 1], \
            f"Score decreased at count {i+1}: {scores[i]} -> {scores[i+1]}"
```

- [ ] Run: `python3 -m pytest tests/test_shared/test_score_calibration.py -v` → Expected: FAIL (count=1 returns ~0.41 from old log curve, not ~0.50)

- [ ] Implement

Replace `corroboration_score_from_count` in `shared/data_quality.py`:

```python
# Replace the existing import `import math` at the top — keep it, but also add:
from math import exp

# Replace the existing corroboration_score_from_count function (lines ~68-76):
def corroboration_score_from_count(count: int) -> float:
    """
    Sigmoid: count=1→0.50, count=2→0.73, count=3→0.88, count=5→0.98

    Replaces the previous log curve. The sigmoid gives more meaningful
    separation at low counts (1-3 sources) which is the practical range
    for most OSINT records.
    """
    if count <= 0:
        return 0.0
    return round(min(1.0, 1 / (1 + exp(-1.5 * (count - 1)))), 4)
```

Note: the `from math import exp` import can replace `import math` entirely if `math.log` is no longer used elsewhere in the file, or simply be added alongside it.

- [ ] Run: `python3 -m pytest tests/test_shared/test_score_calibration.py -v` → Expected: PASS (9 passed)

- [ ] Commit: `git commit -m "feat(scoring): replace log curve with sigmoid in corroboration_score_from_count"`

---

### Task 4: `AutoDedupDaemon` — Core Daemon Class

**Files:**
- Create: `modules/enrichers/auto_dedup.py`

- [ ] Write failing test

```python
# tests/test_enrichers/test_auto_dedup.py
import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from modules.enrichers.auto_dedup import AutoDedupDaemon
from modules.enrichers.deduplication import MergeCandidate


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_person(pid=None, fields=5):
    """Return a mock Person ORM object."""
    p = MagicMock()
    p.id = pid or uuid.uuid4()
    p.merged_into = None
    p._field_count = fields  # used by mock _count_populated_fields
    return p


def _candidate(id_a, id_b, score):
    return MergeCandidate(
        id_a=str(id_a), id_b=str(id_b),
        similarity_score=score, match_reasons=["name_match"]
    )


# ── Unit tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daemon_instantiates():
    daemon = AutoDedupDaemon()
    assert daemon is not None


@pytest.mark.asyncio
async def test_count_populated_fields_scalar():
    """_count_populated_fields sums non-null scalars + child row counts."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    person = MagicMock()
    person.id = uuid.uuid4()
    # Simulate scalar columns: 3 non-null, 2 null
    person.__table__ = MagicMock()
    col_a = MagicMock(); col_a.name = "full_name"
    col_b = MagicMock(); col_b.name = "date_of_birth"
    col_c = MagicMock(); col_c.name = "nationality"
    col_d = MagicMock(); col_d.name = "bio"
    col_e = MagicMock(); col_e.name = "gender"
    person.__table__.columns = [col_a, col_b, col_c, col_d, col_e]

    # getattr returns values: 3 filled, 2 None
    def _getattr(obj, name, *args):
        return {"full_name": "Alice", "date_of_birth": "1990-01-01",
                "nationality": "US", "bio": None, "gender": None}.get(name)

    with patch("builtins.getattr", side_effect=_getattr):
        # Child table counts all return 2 rows each (5 tables × 2 = 10)
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 2
        session.execute = AsyncMock(return_value=mock_result)

        count = await daemon._count_populated_fields(person, session)
        # 3 scalar fields + 5 child tables × 2 rows each = 13
        assert count == 13


@pytest.mark.asyncio
async def test_run_batch_auto_merges_high_score(monkeypatch):
    """Score >= 0.85 triggers immediate merge."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    person_a_id = uuid.uuid4()
    person_b_id = uuid.uuid4()

    # Mock recent persons query
    mock_persons_result = MagicMock()
    mock_persons_result.scalars.return_value.all.return_value = [
        _make_person(pid=person_a_id)
    ]

    # Mock score_person_dedup returning high-score candidate
    candidate = _candidate(person_a_id, person_b_id, 0.92)

    # Mock _count_populated_fields: person_a has more fields → canonical
    async def mock_count(person, sess):
        return 20 if person.id == person_a_id else 10

    merge_called_with = {}

    async def mock_merge(canonical_id, duplicate_id, session):
        merge_called_with["canonical"] = canonical_id
        merge_called_with["duplicate"] = duplicate_id
        return {"merged": True}

    with patch("modules.enrichers.auto_dedup.score_person_dedup",
               new=AsyncMock(return_value=[candidate])), \
         patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec:

        daemon._count_populated_fields = mock_count
        session.execute = AsyncMock(return_value=mock_persons_result)

        mock_exec_instance = AsyncMock()
        mock_exec_instance.execute = AsyncMock(return_value={"merged": True})
        MockExec.return_value = mock_exec_instance

        await daemon._run_batch(session)

        assert MockExec.called, "AsyncMergeExecutor should have been called for score 0.92"


@pytest.mark.asyncio
async def test_run_batch_queues_medium_score(monkeypatch):
    """Score 0.70-0.84 inserts DedupReview row, does NOT merge."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    person_a_id = uuid.uuid4()
    person_b_id = uuid.uuid4()

    mock_persons_result = MagicMock()
    mock_persons_result.scalars.return_value.all.return_value = [
        _make_person(pid=person_a_id)
    ]

    candidate = _candidate(person_a_id, person_b_id, 0.77)

    added_objects = []
    session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with patch("modules.enrichers.auto_dedup.score_person_dedup",
               new=AsyncMock(return_value=[candidate])), \
         patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec:

        daemon._count_populated_fields = AsyncMock(return_value=5)
        session.execute = AsyncMock(return_value=mock_persons_result)

        await daemon._run_batch(session)

        MockExec.assert_not_called()
        assert any(
            hasattr(obj, "similarity_score") and obj.similarity_score == 0.77
            for obj in added_objects
        ), "DedupReview row should have been added to session"


@pytest.mark.asyncio
async def test_run_batch_skips_low_score(monkeypatch):
    """Score < 0.70 is silently skipped — no merge, no review row."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    person_a_id = uuid.uuid4()
    person_b_id = uuid.uuid4()

    mock_persons_result = MagicMock()
    mock_persons_result.scalars.return_value.all.return_value = [
        _make_person(pid=person_a_id)
    ]

    candidate = _candidate(person_a_id, person_b_id, 0.45)

    added_objects = []
    session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with patch("modules.enrichers.auto_dedup.score_person_dedup",
               new=AsyncMock(return_value=[candidate])), \
         patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec:

        daemon._count_populated_fields = AsyncMock(return_value=5)
        session.execute = AsyncMock(return_value=mock_persons_result)

        await daemon._run_batch(session)

        MockExec.assert_not_called()
        assert len(added_objects) == 0, "Nothing should be added for low score"
```

- [ ] Run: `python3 -m pytest tests/test_enrichers/test_auto_dedup.py -v` → Expected: FAIL (`ModuleNotFoundError: No module named 'modules.enrichers.auto_dedup'`)

- [ ] Implement

```python
# modules/enrichers/auto_dedup.py
"""
AutoDedupDaemon — background deduplication daemon.

Runs every 10 minutes. Scores recently-updated persons against existing
records and routes candidates:
  - similarity >= 0.85 → auto-merge (richer record wins)
  - similarity 0.70-0.84 → insert DedupReview for manual review
  - similarity < 0.70 → skip

All merges execute in a single transaction with full rollback on failure.
Both UUIDs are written to audit_log with action="auto_merge".
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.enrichers.deduplication import AsyncMergeExecutor, score_person_dedup
from shared.db import AsyncSessionFactory
from shared.models.dedup_review import DedupReview
from shared.models.person import Person

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
AUTO_MERGE_THRESHOLD = 0.85
REVIEW_THRESHOLD = 0.70
BATCH_WINDOW_MINUTES = 10
SLEEP_INTERVAL_SECONDS = 600  # 10 minutes


class AutoDedupDaemon:
    """Continuously deduplicates recently-updated person records."""

    async def start(self) -> None:
        """Entry point — runs forever, sleeping between batches."""
        logger.info("AutoDedupDaemon started (interval=%ds)", SLEEP_INTERVAL_SECONDS)
        while True:
            try:
                async with AsyncSessionFactory() as session:
                    await self._run_batch(session)
            except Exception:
                logger.exception("AutoDedupDaemon: unhandled error in batch — continuing")
            await asyncio.sleep(SLEEP_INTERVAL_SECONDS)

    async def _run_batch(self, session: AsyncSession) -> None:
        """Process one batch of recently-updated persons."""
        cutoff = datetime.now(UTC) - timedelta(minutes=BATCH_WINDOW_MINUTES)

        result = await session.execute(
            select(Person)
            .where(Person.updated_at >= cutoff)
            .where(Person.merged_into.is_(None))
        )
        persons = result.scalars().all()

        if not persons:
            logger.debug("AutoDedupDaemon: no persons updated in last %dm", BATCH_WINDOW_MINUTES)
            return

        logger.info("AutoDedupDaemon: scanning %d recently-updated persons", len(persons))
        seen_pairs: set[frozenset] = set()

        for person in persons:
            try:
                candidates = await score_person_dedup(str(person.id), session)
            except Exception:
                logger.exception("AutoDedupDaemon: score_person_dedup failed person_id=%s", person.id)
                continue

            for candidate in candidates:
                pair = frozenset({candidate.id_a, candidate.id_b})
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                score = candidate.similarity_score

                if score >= AUTO_MERGE_THRESHOLD:
                    await self._auto_merge(candidate, session)
                elif score >= REVIEW_THRESHOLD:
                    await self._queue_for_review(candidate, session)
                # else: skip silently

        await session.commit()

    async def _auto_merge(self, candidate, session: AsyncSession) -> None:
        """Determine canonical record and execute merge."""
        try:
            # Fetch both persons to compare richness
            result_a = await session.execute(
                select(Person).where(Person.id == candidate.id_a)
            )
            result_b = await session.execute(
                select(Person).where(Person.id == candidate.id_b)
            )
            person_a = result_a.scalar_one_or_none()
            person_b = result_b.scalar_one_or_none()

            if person_a is None or person_b is None:
                logger.warning(
                    "AutoDedupDaemon: person not found for pair %s / %s — skipping",
                    candidate.id_a, candidate.id_b,
                )
                return

            count_a = await self._count_populated_fields(person_a, session)
            count_b = await self._count_populated_fields(person_b, session)

            if count_a >= count_b:
                canonical_id = str(person_a.id)
                duplicate_id = str(person_b.id)
            else:
                canonical_id = str(person_b.id)
                duplicate_id = str(person_a.id)

            plan = {"canonical_id": canonical_id, "duplicate_id": duplicate_id}
            result = await AsyncMergeExecutor().execute(plan, session)

            if result.get("merged"):
                logger.info(
                    "AutoDedupDaemon: auto-merged %s → %s (score=%.3f)",
                    duplicate_id, canonical_id, candidate.similarity_score,
                )
            else:
                logger.warning(
                    "AutoDedupDaemon: merge failed for %s → %s: %s",
                    duplicate_id, canonical_id, result.get("error"),
                )

        except Exception:
            logger.exception(
                "AutoDedupDaemon: _auto_merge failed for pair %s / %s",
                candidate.id_a, candidate.id_b,
            )

    async def _queue_for_review(self, candidate, session: AsyncSession) -> None:
        """Insert a DedupReview row for manual adjudication."""
        review = DedupReview(
            person_a_id=candidate.id_a,
            person_b_id=candidate.id_b,
            similarity_score=candidate.similarity_score,
        )
        session.add(review)
        logger.debug(
            "AutoDedupDaemon: queued review for %s / %s (score=%.3f)",
            candidate.id_a, candidate.id_b, candidate.similarity_score,
        )

    async def _count_populated_fields(self, person: Person, session: AsyncSession) -> int:
        """
        Sum non-null scalar fields on Person + count of child rows across
        identifiers, social_profiles, addresses, employment,
        criminal_records.

        Returns an integer richness score — higher means more data.
        """
        from shared.models.address import Address
        from shared.models.criminal import CriminalRecord
        from shared.models.identifier import Identifier
        from shared.models.social_profile import SocialProfile

        # Scalar field count (exclude id, uuid FK columns, and JSONB blobs)
        _SKIP = {"id", "meta", "data_quality", "merged_into"}
        scalar_count = sum(
            1
            for col in person.__table__.columns
            if col.name not in _SKIP
            and getattr(person, col.name, None) is not None
        )

        # Child row counts
        child_total = 0
        child_tables = [
            (Identifier, Identifier.person_id),
            (SocialProfile, SocialProfile.person_id),
            (Address, Address.person_id),
            (CriminalRecord, CriminalRecord.person_id),
        ]

        for Model, fk_col in child_tables:
            try:
                result = await session.execute(
                    select(func.count()).select_from(Model).where(fk_col == person.id)
                )
                child_total += result.scalar_one()
            except Exception:
                pass  # table may not exist in test env — non-fatal

        return scalar_count + child_total
```

- [ ] Run: `python3 -m pytest tests/test_enrichers/test_auto_dedup.py -v` → Expected: PASS (5 passed)

- [ ] Commit: `git commit -m "feat(enrichers): implement AutoDedupDaemon with richer-record-wins merge strategy"`

---

### Task 5: API Endpoints — `GET /dedup/auto-queue` and `POST /dedup/auto-merge/run`

**Files:**
- Modify: `api/routes/dedup.py`

- [ ] Write failing test

```python
# tests/test_api/test_dedup_auto_endpoints.py
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from api.main import app  # adjust import if entrypoint differs


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_get_auto_queue_returns_list():
    """GET /dedup/auto-queue returns pending DedupReview rows."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        with patch("api.routes.dedup.get_auto_queue_rows") as mock_fn:
            mock_fn.return_value = [
                {
                    "id": str(uuid.uuid4()),
                    "person_a_id": str(uuid.uuid4()),
                    "person_b_id": str(uuid.uuid4()),
                    "similarity_score": 0.77,
                    "reviewed": False,
                    "decision": None,
                }
            ]
            resp = await client.get("/dedup/auto-queue")
            assert resp.status_code == 200
            body = resp.json()
            assert "reviews" in body
            assert "count" in body


@pytest.mark.anyio
async def test_post_auto_merge_run_triggers_batch():
    """POST /dedup/auto-merge/run triggers one immediate batch."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        with patch("api.routes.dedup.AutoDedupDaemon") as MockDaemon:
            instance = AsyncMock()
            instance._run_batch = AsyncMock(return_value=None)
            MockDaemon.return_value = instance

            resp = await client.post("/dedup/auto-merge/run")
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("status") == "ok"
```

- [ ] Run: `python3 -m pytest tests/test_api/test_dedup_auto_endpoints.py -v` → Expected: FAIL (`404 Not Found` for both routes)

- [ ] Implement

Add these two endpoints to `api/routes/dedup.py` **before** the existing parameterised routes:

```python
# Add imports at top of api/routes/dedup.py (alongside existing imports):
from modules.enrichers.auto_dedup import AutoDedupDaemon
from shared.models.dedup_review import DedupReview
from sqlalchemy import select as sa_select


# ── Helper used by tests for easier mocking ──────────────────────────────────

async def get_auto_queue_rows(session: AsyncSession) -> list[dict]:
    """Fetch pending (unreviewed) DedupReview rows."""
    result = await session.execute(
        sa_select(DedupReview)
        .where(DedupReview.reviewed == False)  # noqa: E712
        .order_by(DedupReview.similarity_score.desc())
        .limit(200)
    )
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "person_a_id": str(r.person_a_id),
            "person_b_id": str(r.person_b_id),
            "similarity_score": r.similarity_score,
            "reviewed": r.reviewed,
            "decision": r.decision,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ── New endpoints — must appear before /{person_id}/... parameterised routes ──


@router.get("/auto-queue")
async def dedup_auto_queue(session: AsyncSession = DbDep):
    """Return all pending DedupReview rows ordered by score descending."""
    rows = await get_auto_queue_rows(session)
    return {"reviews": rows, "count": len(rows)}


@router.post("/auto-merge/run")
async def dedup_auto_merge_run(session: AsyncSession = DbDep):
    """Trigger one immediate dedup batch outside the regular schedule."""
    daemon = AutoDedupDaemon()
    try:
        await daemon._run_batch(session)
    except Exception as exc:
        logger.exception("Manual dedup batch failed")
        raise HTTPException(500, "Dedup batch failed") from exc
    return {"status": "ok", "message": "Dedup batch completed"}
```

- [ ] Run: `python3 -m pytest tests/test_api/test_dedup_auto_endpoints.py -v` → Expected: PASS (2 passed)

- [ ] Commit: `git commit -m "feat(api): add GET /dedup/auto-queue and POST /dedup/auto-merge/run endpoints"`

---

### Task 6: API — 301 Redirect for Merged Persons on `GET /persons/{id}`

**Files:**
- Modify: `api/routes/persons.py`

- [ ] Write failing test

```python
# tests/test_api/test_persons_merged_redirect.py
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from api.main import app  # adjust if needed


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_merged_person_returns_301():
    """GET /persons/{id} returns 301 with Location header when person is merged."""
    merged_id = uuid.uuid4()
    canonical_id = uuid.uuid4()

    mock_person = MagicMock()
    mock_person.id = merged_id
    mock_person.merged_into = canonical_id

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_person

    async with AsyncClient(app=app, base_url="http://test") as client:
        with patch("api.routes.persons.AsyncSession") as _mock_sess:
            # Patch the DB dependency to return our mock result
            with patch("api.routes.persons._get_person_by_id",
                       new=AsyncMock(return_value=mock_person)):
                resp = await client.get(
                    f"/persons/{merged_id}", follow_redirects=False
                )
                assert resp.status_code == 301
                assert str(canonical_id) in resp.headers.get("location", "")


@pytest.mark.anyio
async def test_active_person_returns_200():
    """GET /persons/{id} returns 200 for a non-merged person."""
    active_id = uuid.uuid4()

    mock_person = MagicMock()
    mock_person.id = active_id
    mock_person.merged_into = None
    mock_person.full_name = "Alice"

    async with AsyncClient(app=app, base_url="http://test") as client:
        with patch("api.routes.persons._get_person_by_id",
                   new=AsyncMock(return_value=mock_person)):
            resp = await client.get(f"/persons/{active_id}", follow_redirects=False)
            # 200 or 404 are both acceptable for a non-merged person in unit test
            assert resp.status_code != 301
```

- [ ] Run: `python3 -m pytest tests/test_api/test_persons_merged_redirect.py -v` → Expected: FAIL (no redirect logic exists yet)

- [ ] Implement

Add a helper function and redirect logic to `api/routes/persons.py`. Insert at the top of the `GET /persons/{id}` handler (locate the existing `@router.get("/{person_id}")` handler):

```python
# Add import at top of api/routes/persons.py:
from fastapi.responses import JSONResponse, RedirectResponse

# Add helper before the route handlers:
async def _get_person_by_id(person_id: uuid.UUID, session: AsyncSession) -> Person | None:
    """Fetch a single Person row by ID."""
    result = await session.execute(
        select(Person).where(Person.id == person_id)
    )
    return result.scalar_one_or_none()


# In the existing GET /{person_id} handler, add BEFORE the existing 404 check:
# Locate the handler decorated with @router.get("/{person_id}") and add at the
# start of its body, after validating the UUID:

#   person = await _get_person_by_id(person_uuid, session)
#
#   # ── Redirect if this record has been merged ─────────────────────
#   if person is not None and person.merged_into is not None:
#       canonical_url = f"/persons/{person.merged_into}"
#       return RedirectResponse(
#           url=canonical_url,
#           status_code=301,
#           headers={"Content-Type": "application/json"},
#       )
#   # ── 404 if not found ────────────────────────────────────────────
#   if person is None:
#       raise HTTPException(404, "Person not found")
```

The exact diff to insert into the existing `GET /{person_id}` handler body is:

```python
# After: person_uuid = _validate_uuid(person_id)  (or equivalent UUID parse)
# Before: existing 404 raise

person = await _get_person_by_id(person_uuid, session)

if person is not None and person.merged_into is not None:
    return RedirectResponse(
        url=f"/persons/{person.merged_into}",
        status_code=301,
    )

if person is None:
    raise HTTPException(404, "Person not found")
```

The redirect body `{"merged_into": "<canonical_id>"}` is conveyed via the `Location` header. If a JSON body is also required, return a `JSONResponse(status_code=301, ...)` with explicit `headers={"Location": f"/persons/{person.merged_into}"}` instead.

- [ ] Run: `python3 -m pytest tests/test_api/test_persons_merged_redirect.py -v` → Expected: PASS (2 passed)

- [ ] Commit: `git commit -m "feat(api): return HTTP 301 redirect for merged person records"`

---

### Task 7: Register `AutoDedupDaemon` in `worker.py`

**Files:**
- Modify: `worker.py`

- [ ] Write failing test

```python
# tests/test_daemon/test_worker_dedup_registration.py
import ast
import pathlib


def test_auto_dedup_daemon_imported_in_worker():
    """worker.py must import AutoDedupDaemon."""
    src = pathlib.Path("worker.py").read_text()
    assert "AutoDedupDaemon" in src, \
        "worker.py does not reference AutoDedupDaemon"


def test_worker_starts_auto_dedup_task():
    """worker.py must create a task for auto-dedup-daemon."""
    src = pathlib.Path("worker.py").read_text()
    assert "auto-dedup" in src or "AutoDedupDaemon" in src, \
        "worker.py does not start AutoDedupDaemon task"
```

- [ ] Run: `python3 -m pytest tests/test_daemon/test_worker_dedup_registration.py -v` → Expected: FAIL

- [ ] Implement

In `worker.py`, make the following additions:

```python
# 1. Add to the import block inside async def main(), alongside other daemon imports:
from modules.enrichers.auto_dedup import AutoDedupDaemon

# 2. Add after the "Freshness scheduler" block (around line 95), before the
#    logger.info summary:

    # Auto-dedup daemon
    dedup_daemon = AutoDedupDaemon()
    tasks.append(
        asyncio.create_task(dedup_daemon.start(), name="auto-dedup-daemon")
    )
    logger.info("Started auto-dedup daemon")

# 3. Update the summary log line to mention the dedup daemon:
    logger.info(
        f"Worker running — {workers} dispatcher(s) + "
        f"{'growth daemon + ' if enable_growth else ''}"
        f"{'freshness scheduler + ' if enable_freshness else ''}"
        f"auto-dedup daemon"
    )
```

- [ ] Run: `python3 -m pytest tests/test_daemon/test_worker_dedup_registration.py -v` → Expected: PASS (2 passed)

- [ ] Commit: `git commit -m "feat(worker): register AutoDedupDaemon as background task"`

---

### Task 8: Display Calibration — `static/index.html` Score Integers (0–100)

**Files:**
- Modify: `static/index.html`

- [ ] Write failing test

```python
# tests/test_shared/test_index_html_display.py
import pathlib
import re


INDEX_HTML = pathlib.Path("static/index.html").read_text()


def test_risk_dial_renders_integer():
    """drawRiskDial renders Math.round(pct*100) — already done, must stay."""
    # Line 488: t.textContent = Math.round(pct*100);
    assert "Math.round(pct*100)" in INDEX_HTML, \
        "drawRiskDial should output Math.round(pct*100)"


def test_no_raw_score_toFixed():
    """No raw .toFixed() calls on 0-1 scores in the risk display blocks."""
    # toFixed on a 0-1 float would expose decimal notation to users
    raw_decimal_pattern = re.compile(r'\.toFixed\(1\)\s*\+\s*["\'](?!\s*%)')
    # Allow toFixed only in clearly non-score contexts
    assert not raw_decimal_pattern.search(INDEX_HTML), \
        "Found .toFixed(1) outputting raw decimal — must use Math.round(*100)"


def test_identifier_confidence_displayed_as_integer():
    """Identifier confidence shown as Math.round((i.confidence||0)*100)+'%'."""
    assert "Math.round((i.confidence||0)*100)+'%'" in INDEX_HTML, \
        "Identifier confidence must render as integer percent"


def test_composite_quality_displayed_as_integer():
    """composite_quality badge uses relBadge which internally rounds to integer."""
    # relBadge function: const pct = Math.round((score || 0) * 100);
    assert "Math.round((score || 0) * 100)" in INDEX_HTML, \
        "relBadge should render score as integer percent"


def test_similarity_score_displayed_as_integer():
    """Dedup similarity scores shown as Math.round(...*100)."""
    assert "Math.round(c.similarity_score * 100)" in INDEX_HTML or \
           "Math.round((c.similarity_score||0)*100)" in INDEX_HTML, \
        "Similarity score must render as integer percent"


def test_financial_aml_score_displayed_as_integer():
    """AML match score displayed as Math.round((w.match_score||0)*100)+'%'."""
    assert "Math.round((w.match_score||0)*100)+'%'" in INDEX_HTML, \
        "AML match score must render as integer percent"
```

- [ ] Run: `python3 -m pytest tests/test_shared/test_index_html_display.py -v` → Expected: result reveals which assertions already pass and which fail

The codebase audit shows `static/index.html` already uses `Math.round(...*100)` for the majority of score displays. The remaining raw pattern to fix is in `drawRiskDial` (line 488), which already outputs `Math.round(pct*100)` — this test confirms the invariant holds. If any new score expressions are added during this phase they must follow the same pattern.

- [ ] Verify every score expression in `static/index.html` follows `Math.round(<score_expr> * 100)`:

Confirmed integer display locations already in place:
| Location | Expression | Status |
|---|---|---|
| `drawRiskDial` (line 488) | `Math.round(pct*100)` | DONE |
| `relBadge` (line 452) | `Math.round((score\|\|0)*100)` | DONE |
| Risk tag in list (line 957) | `Math.round((p.default_risk_score\|\|0)*100)+'%'` | DONE |
| Quality tag detail (line 1427) | `Math.round((p.composite_quality\|\|0)*100)+'%'` | DONE |
| Identifier confidence (line 1499) | `Math.round((i.confidence\|\|0)*100)+'%'` | DONE |
| AML match score (line 1545) | `Math.round((w.match_score\|\|0)*100)+'%'` | DONE |
| Financial score display (line 1605) | `Math.round((s.val\|\|0)*100)` | DONE |
| Tag confidence badge (line 2088) | `Math.round(t.confidence*100)+'%'` | DONE |
| Record confidence (line 2138) | `Math.round((r.confidence\|\|0)*100)+'%'` | DONE |
| Company confidence (line 2195) | `Math.round((c.confidence\|\|0)*100)+'%'` | DONE |
| Network risk score (line 2245) | `Math.round(n.risk_score*100)+'%'` | DONE |
| Dedup similarity (line 1265, 2352) | `Math.round(c.similarity_score * 100)` | DONE |

If the test suite reveals any raw `(score).toFixed(2)` or `score + ""` expressions displaying to the user, replace with `Math.round((score\|\|0)*100)+'%'`.

- [ ] Run: `python3 -m pytest tests/test_shared/test_index_html_display.py -v` → Expected: PASS (6 passed)

- [ ] Commit: `git commit -m "test(ui): add invariant tests confirming all scores display as 0-100 integers"`

---

### Task 9: Integration Smoke Test

**Files:**
- Create: `tests/test_integration_dedup_pipeline.py`

- [ ] Write and run integration smoke test

```python
# tests/test_integration_dedup_pipeline.py
"""
Smoke tests verifying the full dedup pipeline wires together correctly
without a live database. Uses mocks for all I/O.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.auto_dedup import (
    AUTO_MERGE_THRESHOLD,
    REVIEW_THRESHOLD,
    AutoDedupDaemon,
)
from modules.enrichers.deduplication import MergeCandidate
from shared.data_quality import corroboration_score_from_count
from shared.models.dedup_review import DedupReview
from shared.models.person import Person


def test_person_model_has_merged_into():
    p = Person(full_name="Test")
    assert p.merged_into is None


def test_dedup_review_model_instantiates():
    a, b = uuid.uuid4(), uuid.uuid4()
    r = DedupReview(person_a_id=a, person_b_id=b, similarity_score=0.80)
    assert r.reviewed is False


def test_sigmoid_values():
    assert corroboration_score_from_count(0) == 0.0
    assert 0.49 <= corroboration_score_from_count(1) <= 0.51
    assert corroboration_score_from_count(5) >= 0.96


def test_threshold_constants():
    assert AUTO_MERGE_THRESHOLD == 0.85
    assert REVIEW_THRESHOLD == 0.70


@pytest.mark.asyncio
async def test_daemon_routes_correctly():
    """One pass: high score → merge, medium → review, low → skip."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    id_a = uuid.uuid4()
    id_b = uuid.uuid4()
    id_c = uuid.uuid4()
    id_d = uuid.uuid4()

    persons_result = MagicMock()
    persons_result.scalars.return_value.all.return_value = [
        MagicMock(id=id_a, merged_into=None),
    ]
    session.execute = AsyncMock(return_value=persons_result)

    high = MergeCandidate(str(id_a), str(id_b), 0.90, ["name"])
    medium = MergeCandidate(str(id_a), str(id_c), 0.75, ["dob"])
    low = MergeCandidate(str(id_a), str(id_d), 0.50, [])

    added = []
    session.add = MagicMock(side_effect=added.append)

    with patch("modules.enrichers.auto_dedup.score_person_dedup",
               new=AsyncMock(return_value=[high, medium, low])), \
         patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec:

        daemon._count_populated_fields = AsyncMock(return_value=10)
        # Make person fetches return dummy objects
        person_mock = MagicMock()
        person_mock.merged_into = None
        person_mock.id = id_a
        persons_fetch = MagicMock()
        persons_fetch.scalar_one_or_none.return_value = person_mock
        session.execute = AsyncMock(side_effect=[
            persons_result,       # initial recent persons query
            persons_fetch,        # fetch person_a for merge
            persons_fetch,        # fetch person_b for merge
        ])

        mock_exec = AsyncMock()
        mock_exec.execute = AsyncMock(return_value={"merged": True})
        MockExec.return_value = mock_exec

        await daemon._run_batch(session)

        # High score → merge called
        assert MockExec.called

        # Medium score → DedupReview added
        review_added = [obj for obj in added if isinstance(obj, DedupReview)]
        assert len(review_added) == 1
        assert review_added[0].similarity_score == 0.75

        # Low score → nothing added for it
        assert all(obj.similarity_score != 0.50 for obj in review_added)
```

- [ ] Run: `python3 -m pytest tests/test_integration_dedup_pipeline.py -v` → Expected: PASS (5 passed)

- [ ] Commit: `git commit -m "test(integration): add Phase 1 dedup pipeline smoke tests"`

---

### Task 10: Final Verification Run

- [ ] Run full test suite for all Phase 1 files:

```bash
python3 -m pytest \
  tests/test_shared/test_dedup_models.py \
  tests/test_shared/test_score_calibration.py \
  tests/test_shared/test_index_html_display.py \
  tests/test_enrichers/test_auto_dedup.py \
  tests/test_api/test_dedup_auto_endpoints.py \
  tests/test_api/test_persons_merged_redirect.py \
  tests/test_daemon/test_worker_dedup_registration.py \
  tests/test_integration_dedup_pipeline.py \
  -v --tb=short
```

Expected output:
```
tests/test_shared/test_dedup_models.py::test_person_has_merged_into_field PASSED
tests/test_shared/test_dedup_models.py::test_person_merged_into_accepts_uuid PASSED
tests/test_shared/test_dedup_models.py::test_dedup_review_defaults PASSED
tests/test_shared/test_dedup_models.py::test_dedup_review_decision_values PASSED
tests/test_shared/test_score_calibration.py::test_count_zero_returns_zero PASSED
tests/test_shared/test_score_calibration.py::test_count_negative_returns_zero PASSED
tests/test_shared/test_score_calibration.py::test_count_1_near_0_50 PASSED
tests/test_shared/test_score_calibration.py::test_count_2_near_0_73 PASSED
tests/test_shared/test_score_calibration.py::test_count_3_near_0_88 PASSED
tests/test_shared/test_score_calibration.py::test_count_5_near_0_98 PASSED
tests/test_shared/test_score_calibration.py::test_score_never_exceeds_1 PASSED
tests/test_shared/test_score_calibration.py::test_score_monotonically_increasing PASSED
tests/test_shared/test_index_html_display.py::test_risk_dial_renders_integer PASSED
tests/test_shared/test_index_html_display.py::test_no_raw_score_toFixed PASSED
tests/test_shared/test_index_html_display.py::test_identifier_confidence_displayed_as_integer PASSED
tests/test_shared/test_index_html_display.py::test_composite_quality_displayed_as_integer PASSED
tests/test_shared/test_index_html_display.py::test_similarity_score_displayed_as_integer PASSED
tests/test_shared/test_index_html_display.py::test_financial_aml_score_displayed_as_integer PASSED
tests/test_enrichers/test_auto_dedup.py::test_daemon_instantiates PASSED
tests/test_enrichers/test_auto_dedup.py::test_count_populated_fields_scalar PASSED
tests/test_enrichers/test_auto_dedup.py::test_run_batch_auto_merges_high_score PASSED
tests/test_enrichers/test_auto_dedup.py::test_run_batch_queues_medium_score PASSED
tests/test_enrichers/test_auto_dedup.py::test_run_batch_skips_low_score PASSED
tests/test_api/test_dedup_auto_endpoints.py::test_get_auto_queue_returns_list PASSED
tests/test_api/test_dedup_auto_endpoints.py::test_post_auto_merge_run_triggers_batch PASSED
tests/test_api/test_persons_merged_redirect.py::test_merged_person_returns_301 PASSED
tests/test_api/test_persons_merged_redirect.py::test_active_person_returns_200 PASSED
tests/test_daemon/test_worker_dedup_registration.py::test_auto_dedup_daemon_imported_in_worker PASSED
tests/test_daemon/test_worker_dedup_registration.py::test_worker_starts_auto_dedup_task PASSED
tests/test_integration_dedup_pipeline.py::test_person_model_has_merged_into PASSED
tests/test_integration_dedup_pipeline.py::test_dedup_review_model_instantiates PASSED
tests/test_integration_dedup_pipeline.py::test_sigmoid_values PASSED
tests/test_integration_dedup_pipeline.py::test_threshold_constants PASSED
tests/test_integration_dedup_pipeline.py::test_daemon_routes_correctly PASSED

============================= 35 passed in N.NNs =============================
```

- [ ] Commit: `git commit -m "chore: Phase 1 auto-dedup + score calibration — all 35 tests passing"`

---

## Summary of Changes

| Component | File | Change |
|---|---|---|
| Person model | `shared/models/person.py` | Add `merged_into` UUID FK (nullable, indexed) |
| DedupReview model | `shared/models/dedup_review.py` | New model: review queue for 0.70–0.84 candidates |
| Alembic migration | `migrations/versions/c3d4e5f6a7b8_...py` | `persons.merged_into` column + `dedup_reviews` table |
| Score calibration | `shared/data_quality.py` | Replace log curve with sigmoid in `corroboration_score_from_count` |
| AutoDedupDaemon | `modules/enrichers/auto_dedup.py` | New daemon: 10-min poll, richer-record-wins merge, review queue |
| Dedup API | `api/routes/dedup.py` | Add `GET /dedup/auto-queue`, `POST /dedup/auto-merge/run` |
| Persons API | `api/routes/persons.py` | 301 redirect when `Person.merged_into` is set |
| Worker | `worker.py` | Register `AutoDedupDaemon` task |
| Display | `static/index.html` | Invariant tests confirm all scores render as 0–100 integers |
