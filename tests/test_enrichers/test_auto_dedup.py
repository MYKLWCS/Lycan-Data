"""Tests for AutoDedupDaemon — background deduplication daemon."""

import asyncio
import uuid
from datetime import timezone, datetime
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

import shared.models.address  # noqa: F401

# Import all models upfront so SQLAlchemy can resolve string-based relationships
import shared.models.criminal  # noqa: F401
import shared.models.identifier  # noqa: F401
import shared.models.identifier_history  # noqa: F401
import shared.models.identity_document  # noqa: F401
import shared.models.social_profile  # noqa: F401
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
        id_a=str(id_a), id_b=str(id_b), similarity_score=score, match_reasons=["name_match"]
    )


# ── Unit tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_daemon_instantiates():
    daemon = AutoDedupDaemon()
    assert daemon is not None


@pytest.mark.asyncio
async def test_run_batch_auto_merges_high_score(monkeypatch):
    """Score >= 0.85 triggers immediate merge."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    person_a_id = uuid.uuid4()
    person_b_id = uuid.uuid4()

    # Mock recent persons query
    mock_persons_result = MagicMock()
    mock_persons_result.scalars.return_value.all.return_value = [_make_person(pid=person_a_id)]

    # Mock score_person_dedup returning high-score candidate
    candidate = _candidate(person_a_id, person_b_id, 0.92)

    # Mock _count_populated_fields: person_a has more fields → canonical
    async def mock_count(person, sess):
        return 20 if person.id == person_a_id else 10

    with (
        patch(
            "modules.enrichers.auto_dedup.score_person_dedup",
            new=AsyncMock(return_value=[candidate]),
        ),
        patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec,
    ):
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
    mock_persons_result.scalars.return_value.all.return_value = [_make_person(pid=person_a_id)]

    candidate = _candidate(person_a_id, person_b_id, 0.77)

    added_objects = []
    session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with (
        patch(
            "modules.enrichers.auto_dedup.score_person_dedup",
            new=AsyncMock(return_value=[candidate]),
        ),
        patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec,
    ):
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
    mock_persons_result.scalars.return_value.all.return_value = [_make_person(pid=person_a_id)]

    candidate = _candidate(person_a_id, person_b_id, 0.45)

    added_objects = []
    session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with (
        patch(
            "modules.enrichers.auto_dedup.score_person_dedup",
            new=AsyncMock(return_value=[candidate]),
        ),
        patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec,
    ):
        daemon._count_populated_fields = AsyncMock(return_value=5)
        session.execute = AsyncMock(return_value=mock_persons_result)

        await daemon._run_batch(session)

        MockExec.assert_not_called()
        assert len(added_objects) == 0, "Nothing should be added for low score"


@pytest.mark.asyncio
async def test_run_batch_empty_persons_returns_early():
    """No recently-updated persons → early return (lines 60-62)."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    # Should return without calling score_person_dedup
    with patch(
        "modules.enrichers.auto_dedup.score_person_dedup", new=AsyncMock(return_value=[])
    ) as mock_score:
        await daemon._run_batch(session)
        mock_score.assert_not_called()


@pytest.mark.asyncio
async def test_run_batch_score_person_dedup_exception_continues():
    """score_person_dedup raises → exception logged, loop continues (lines 70-74)."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    person_a_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [_make_person(pid=person_a_id)]
    session.execute = AsyncMock(return_value=mock_result)

    with patch(
        "modules.enrichers.auto_dedup.score_person_dedup",
        new=AsyncMock(side_effect=RuntimeError("db error")),
    ):
        # Should not raise
        await daemon._run_batch(session)


@pytest.mark.asyncio
async def test_run_batch_deduplicates_seen_pairs():
    """Same pair appearing twice is processed only once (line 79)."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    pid_a = uuid.uuid4()
    pid_b = uuid.uuid4()

    person_a = _make_person(pid=pid_a)
    person_b = _make_person(pid=pid_b)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [person_a, person_b]
    session.execute = AsyncMock(return_value=mock_result)

    # Both persons return the same candidate pair (reversed)
    cand_ab = _candidate(pid_a, pid_b, 0.92)
    cand_ba = _candidate(pid_b, pid_a, 0.92)

    call_count = [0]

    async def score_side_effect(pid_str, sess):
        call_count[0] += 1
        # first call: pid_a, second call: pid_b — both return same pair
        return [cand_ab] if str(pid_a) in pid_str else [cand_ba]

    with (
        patch("modules.enrichers.auto_dedup.score_person_dedup", side_effect=score_side_effect),
        patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec,
    ):
        daemon._count_populated_fields = AsyncMock(return_value=5)
        mock_exec_instance = AsyncMock()
        mock_exec_instance.execute = AsyncMock(return_value={"merged": True})
        MockExec.return_value = mock_exec_instance

        await daemon._run_batch(session)

    # AsyncMergeExecutor should be called only once despite two persons seeing the same pair
    assert MockExec.call_count == 1


@pytest.mark.asyncio
async def test_auto_merge_person_not_found_returns_early():
    """person_a or person_b not in DB → warning logged, return early (lines 105-111)."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    pid_a = uuid.uuid4()
    pid_b = uuid.uuid4()
    candidate = _candidate(pid_a, pid_b, 0.92)

    # Both execute calls return None scalar
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    with patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec:
        await daemon._auto_merge(candidate, session)
        MockExec.assert_not_called()


@pytest.mark.asyncio
async def test_auto_merge_person_b_richer_becomes_canonical():
    """count_b > count_a → person_b becomes canonical (lines 120-121)."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    pid_a = uuid.uuid4()
    pid_b = uuid.uuid4()
    candidate = _candidate(pid_a, pid_b, 0.92)

    person_a = _make_person(pid=pid_a)
    person_b = _make_person(pid=pid_b)

    # First execute returns person_a, second returns person_b
    call_count = [0]

    async def fake_execute(stmt):
        r = MagicMock()
        c = call_count[0]
        call_count[0] += 1
        r.scalar_one_or_none.return_value = person_a if c == 0 else person_b
        return r

    session.execute = fake_execute

    # person_b has more fields → person_b is canonical
    async def mock_count(person, sess):
        return 5 if person.id == pid_a else 20

    daemon._count_populated_fields = mock_count

    with patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec:
        mock_exec = AsyncMock()
        mock_exec.execute = AsyncMock(return_value={"merged": True})
        MockExec.return_value = mock_exec

        await daemon._auto_merge(candidate, session)

    # Verify merge was called with person_b as canonical
    assert mock_exec.execute.called
    plan = mock_exec.execute.call_args[0][0]
    assert plan["canonical_id"] == str(pid_b)
    assert plan["duplicate_id"] == str(pid_a)


@pytest.mark.asyncio
async def test_auto_merge_merge_failed_logs_warning():
    """Merge returns merged=False → warning logged (lines 134-139)."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    pid_a = uuid.uuid4()
    pid_b = uuid.uuid4()
    candidate = _candidate(pid_a, pid_b, 0.92)

    person_a = _make_person(pid=pid_a)
    person_b = _make_person(pid=pid_b)

    call_count = [0]

    async def fake_execute(stmt):
        r = MagicMock()
        c = call_count[0]
        call_count[0] += 1
        r.scalar_one_or_none.return_value = person_a if c == 0 else person_b
        return r

    session.execute = fake_execute
    daemon._count_populated_fields = AsyncMock(return_value=5)

    with patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec:
        mock_exec = AsyncMock()
        mock_exec.execute = AsyncMock(return_value={"merged": False, "error": "conflict"})
        MockExec.return_value = mock_exec

        await daemon._auto_merge(candidate, session)

    assert mock_exec.execute.called


@pytest.mark.asyncio
async def test_auto_merge_exception_caught():
    """Exception inside _auto_merge is caught and logged (lines 141-146)."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    pid_a = uuid.uuid4()
    pid_b = uuid.uuid4()
    candidate = _candidate(pid_a, pid_b, 0.92)

    # execute raises on first call
    session.execute = AsyncMock(side_effect=RuntimeError("db crashed"))

    # Should not raise
    await daemon._auto_merge(candidate, session)


@pytest.mark.asyncio
async def test_count_populated_fields_with_mock_person():
    """_count_populated_fields works with a mock Person + mocked session (lines 171-203)."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    # Mock Person with __table__
    person = MagicMock()
    person.id = uuid.uuid4()

    col_name = MagicMock()
    col_name.name = "full_name"
    col_skip = MagicMock()
    col_skip.name = "id"

    person.__table__ = MagicMock()
    person.__table__.columns = [col_name, col_skip]
    person.full_name = "Alice Smith"
    person.id = uuid.uuid4()

    # Mock session.execute returning scalar count of 2 for child tables
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 2
    session.execute = AsyncMock(return_value=mock_result)

    count = await daemon._count_populated_fields(person, session)
    # 1 scalar field (full_name) + 4 child tables * 2 = 9
    assert count == 9


@pytest.mark.asyncio
async def test_count_populated_fields_child_table_exception_swallowed():
    """Exception in child table count query is swallowed (lines 200-201)."""
    daemon = AutoDedupDaemon()
    session = AsyncMock()

    person = MagicMock()
    person.id = uuid.uuid4()

    col_name = MagicMock()
    col_name.name = "full_name"
    person.__table__ = MagicMock()
    person.__table__.columns = [col_name]
    person.full_name = "Bob Jones"

    # All child table queries raise
    session.execute = AsyncMock(side_effect=RuntimeError("table does not exist"))

    # Should not raise; scalar_count = 1, child_total = 0
    count = await daemon._count_populated_fields(person, session)
    assert count == 1
