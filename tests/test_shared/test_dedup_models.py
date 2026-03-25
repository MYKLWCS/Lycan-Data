"""Tests for DedupReview model and Person.merged_into field."""

import uuid
import pytest

# Import all models so SQLAlchemy can resolve string-based relationships
import shared.models.criminal  # noqa: F401
import shared.models.identifier  # noqa: F401
import shared.models.social_profile  # noqa: F401
import shared.models.address  # noqa: F401
import shared.models.identifier_history  # noqa: F401
import shared.models.identity_document  # noqa: F401
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
