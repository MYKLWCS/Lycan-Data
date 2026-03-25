"""
Smoke tests verifying the full dedup pipeline wires together correctly
without a live database. Uses mocks for all I/O.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import shared.models.address  # noqa: F401

# Import all models upfront so SQLAlchemy can resolve string-based relationships
import shared.models.criminal  # noqa: F401
import shared.models.identifier  # noqa: F401
import shared.models.identifier_history  # noqa: F401
import shared.models.identity_document  # noqa: F401
import shared.models.social_profile  # noqa: F401
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

    high = MergeCandidate(str(id_a), str(id_b), 0.90, ["name"])
    medium = MergeCandidate(str(id_a), str(id_c), 0.75, ["dob"])
    low = MergeCandidate(str(id_a), str(id_d), 0.50, [])

    added = []
    session.add = MagicMock(side_effect=added.append)

    with (
        patch(
            "modules.enrichers.auto_dedup.score_person_dedup",
            new=AsyncMock(return_value=[high, medium, low]),
        ),
        patch("modules.enrichers.auto_dedup.AsyncMergeExecutor") as MockExec,
    ):
        daemon._count_populated_fields = AsyncMock(return_value=10)
        # Make person fetches return dummy objects
        person_mock = MagicMock()
        person_mock.merged_into = None
        person_mock.id = id_a
        persons_fetch = MagicMock()
        persons_fetch.scalar_one_or_none.return_value = person_mock
        session.execute = AsyncMock(
            side_effect=[
                persons_result,  # initial recent persons query
                persons_fetch,  # fetch person_a for merge
                persons_fetch,  # fetch person_b for merge
            ]
        )

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
