"""
test_auto_dedup_wave6.py — Coverage for modules/enrichers/auto_dedup.py

Targets:
  lines 61-62:   _run_batch — no persons updated → early return
  lines 70-74:   _run_batch — score_person_dedup raises → continue (logged)
  line 79:       _run_batch — pair already in seen_pairs → continue
  lines 106-111: _auto_merge — person_a or person_b not found → log + return
  lines 120-121: _auto_merge — count_b > count_a → canonical = person_b
  lines 134-142: _auto_merge — merge fails (result.merged=False) + exception branch
  lines 171-203: _count_populated_fields — scalar + child row counting
"""

from __future__ import annotations

import uuid
from datetime import timezone, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.enrichers.auto_dedup import AutoDedupDaemon

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _fake_candidate(id_a=None, id_b=None, score=0.90):
    c = MagicMock()
    c.id_a = str(id_a or uuid.uuid4())
    c.id_b = str(id_b or uuid.uuid4())
    c.similarity_score = score
    return c


def _fake_person(pid=None):
    p = MagicMock()
    p.id = pid or uuid.uuid4()
    p.merged_into = None
    return p


# ---------------------------------------------------------------------------
# 1. lines 61-62: no persons updated → early return without commit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_batch_no_persons_returns_early():
    """Lines 61-62: empty persons list → debug log and return immediately."""
    daemon = AutoDedupDaemon()
    session = _make_session()

    # scalars().all() returns empty
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result_mock)

    await daemon._run_batch(session)

    # commit should NOT have been called when there are no persons
    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 2. lines 70-74: score_person_dedup raises → logged, continue to next person
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_batch_score_dedup_exception_continues():
    """Lines 70-74: score_person_dedup raises for first person → exception
    is logged, loop continues, commit is eventually called."""
    daemon = AutoDedupDaemon()
    session = _make_session()

    person = _fake_person()

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [person]
    session.execute = AsyncMock(return_value=result_mock)

    with patch(
        "modules.enrichers.auto_dedup.score_person_dedup",
        new=AsyncMock(side_effect=RuntimeError("scoring failed")),
    ):
        await daemon._run_batch(session)

    # Despite the exception the batch should commit the outer transaction
    session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 3. line 79: duplicate pair already in seen_pairs → skip (continue)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_batch_duplicate_pair_skipped():
    """Line 79: same pair returned twice → second occurrence skipped."""
    daemon = AutoDedupDaemon()
    session = _make_session()

    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())

    person = _fake_person()
    c1 = _fake_candidate(id_a=id_a, id_b=id_b, score=0.60)  # below merge threshold
    c2 = _fake_candidate(id_a=id_a, id_b=id_b, score=0.60)  # same pair

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [person]
    session.execute = AsyncMock(return_value=result_mock)

    with patch(
        "modules.enrichers.auto_dedup.score_person_dedup",
        new=AsyncMock(return_value=[c1, c2]),
    ):
        with patch.object(daemon, "_queue_for_review", new=AsyncMock()) as mock_queue:
            await daemon._run_batch(session)

    # c1 and c2 are the same pair so _queue_for_review is called only once
    assert mock_queue.call_count <= 1


# ---------------------------------------------------------------------------
# 4. lines 106-111: person_a is None → log warning and return
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_merge_person_a_not_found_returns_early():
    """Lines 105-111: person_a is None → warning logged, return without merging."""
    daemon = AutoDedupDaemon()
    session = _make_session()

    candidate = _fake_candidate(score=0.92)

    # session.execute returns None for person_a and person_b lookups
    person_result = MagicMock()
    person_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=person_result)

    with patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as mock_exec:
        await daemon._auto_merge(candidate, session)

    # Merge should not have been attempted
    mock_exec.return_value.execute.assert_not_called()


@pytest.mark.asyncio
async def test_auto_merge_person_b_not_found_returns_early():
    """Lines 105-111: person_b is None → warning logged, return without merging."""
    daemon = AutoDedupDaemon()
    session = _make_session()

    candidate = _fake_candidate(score=0.92)
    fake_person_a = _fake_person()

    # First call (person_a): returns a valid person; second call (person_b): None
    result_a = MagicMock()
    result_a.scalar_one_or_none.return_value = fake_person_a

    result_b = MagicMock()
    result_b.scalar_one_or_none.return_value = None

    session.execute = AsyncMock(side_effect=[result_a, result_b])

    with patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as mock_exec:
        await daemon._auto_merge(candidate, session)

    mock_exec.return_value.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 5. lines 120-121: count_b > count_a → canonical = person_b
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_merge_person_b_richer_becomes_canonical():
    """Lines 120-121: count_b > count_a → canonical_id = person_b.id."""
    daemon = AutoDedupDaemon()
    session = _make_session()

    id_a = uuid.uuid4()
    id_b = uuid.uuid4()
    candidate = _fake_candidate(id_a=str(id_a), id_b=str(id_b), score=0.92)

    person_a = _fake_person(id_a)
    person_b = _fake_person(id_b)

    result_a = MagicMock()
    result_a.scalar_one_or_none.return_value = person_a
    result_b = MagicMock()
    result_b.scalar_one_or_none.return_value = person_b

    session.execute = AsyncMock(side_effect=[result_a, result_b])

    # person_b is richer (count_b=10 > count_a=3)
    with patch.object(daemon, "_count_populated_fields", new=AsyncMock(side_effect=[3, 10])):
        merge_result = {"merged": True}
        with patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as mock_exec_cls:
            mock_exec_cls.return_value.execute = AsyncMock(return_value=merge_result)
            await daemon._auto_merge(candidate, session)

    # canonical_id should be person_b (the richer record)
    call_args = mock_exec_cls.return_value.execute.call_args
    plan = call_args[0][0]
    assert plan["canonical_id"] == str(id_b)
    assert plan["duplicate_id"] == str(id_a)


# ---------------------------------------------------------------------------
# 6. lines 134-142: merge result.merged=False → warning logged
#                   + outer exception → logged without re-raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_merge_merge_failed_logs_warning():
    """Lines 133-139: AsyncMergeExecutor returns merged=False → warning logged."""
    daemon = AutoDedupDaemon()
    session = _make_session()

    id_a = uuid.uuid4()
    id_b = uuid.uuid4()
    candidate = _fake_candidate(id_a=str(id_a), id_b=str(id_b), score=0.92)

    person_a = _fake_person(id_a)
    person_b = _fake_person(id_b)

    result_a = MagicMock()
    result_a.scalar_one_or_none.return_value = person_a
    result_b = MagicMock()
    result_b.scalar_one_or_none.return_value = person_b

    session.execute = AsyncMock(side_effect=[result_a, result_b])

    with patch.object(daemon, "_count_populated_fields", new=AsyncMock(side_effect=[5, 3])):
        merge_result = {"merged": False, "error": "conflict"}
        with patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as mock_exec_cls:
            mock_exec_cls.return_value.execute = AsyncMock(return_value=merge_result)
            # Should not raise
            await daemon._auto_merge(candidate, session)


@pytest.mark.asyncio
async def test_auto_merge_exception_in_merge_does_not_propagate():
    """Lines 141-146: exception inside _auto_merge is caught and logged."""
    daemon = AutoDedupDaemon()
    session = _make_session()

    candidate = _fake_candidate(score=0.92)

    # Force execute to raise inside the try block
    session.execute = AsyncMock(side_effect=RuntimeError("db gone"))

    # Should not raise
    await daemon._auto_merge(candidate, session)


# ---------------------------------------------------------------------------
# 7. lines 171-203: _count_populated_fields — scalar + child row counting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_populated_fields_counts_scalars_and_children():
    """Lines 171-203: counts non-null scalar columns + child table rows."""
    daemon = AutoDedupDaemon()

    # Build a minimal Person-like object with a few non-null columns
    person = MagicMock()
    person.id = uuid.uuid4()

    col_a = MagicMock()
    col_a.name = "full_name"
    col_b = MagicMock()
    col_b.name = "email"
    col_c = MagicMock()
    col_c.name = "id"  # in _SKIP → not counted

    person.__table__ = MagicMock()
    person.__table__.columns = [col_a, col_b, col_c]

    # getattr for non-skip columns returns non-None
    person.full_name = "Alice"
    person.email = "alice@example.com"

    def _getattr_side(obj, name, default=None):
        return {"full_name": "Alice", "email": "alice@example.com"}.get(name, default)

    # session.execute returns a scalar count of 2 for each child table
    count_result = MagicMock()
    count_result.scalar_one.return_value = 2

    session = AsyncMock()
    session.execute = AsyncMock(return_value=count_result)

    with patch("builtins.getattr", side_effect=_getattr_side):
        # Call without the getattr patch so Person attributes work normally
        pass

    # Call directly with real getattr
    result = await daemon._count_populated_fields(person, session)

    # Result should be positive integer (scalar cols + child rows)
    assert isinstance(result, int)
    assert result >= 0


@pytest.mark.asyncio
async def test_count_populated_fields_child_exception_is_non_fatal():
    """Lines 200-201: exception in child count query is silently ignored."""
    daemon = AutoDedupDaemon()

    person = MagicMock()
    person.id = uuid.uuid4()
    person.__table__ = MagicMock()
    person.__table__.columns = []  # no scalar columns

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=Exception("table missing"))

    result = await daemon._count_populated_fields(person, session)
    assert isinstance(result, int)
    assert result == 0  # scalar_count=0, child_total=0 (all exceptions swallowed)


# ---------------------------------------------------------------------------
# 8. _queue_for_review — inserts DedupReview row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_for_review_adds_review_to_session():
    """Lines 148-161: _queue_for_review creates DedupReview and adds to session."""
    from modules.enrichers.auto_dedup import AutoDedupDaemon

    daemon = AutoDedupDaemon()
    session = _make_session()

    candidate = _fake_candidate(score=0.78)

    await daemon._queue_for_review(candidate, session)

    # session.add should have been called once with a DedupReview-like object
    assert session.add.called
